"""Memory subsystem — Codex-style recall + ask_slow_brain for the G1 brain.

Public surface:
    MemorySubsystem  — singleton facade owned by agent_main
    MemoryConfig     — config dataclass (loaded from g1_brain.yaml memory:)
    AskResult        — return type of ask_slow_brain

Everything else is internal.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

from .codex_client import CodexClient
from .context import ContextBuilder
from .daemon import CodexDaemon
from .jobs import JobScheduler
from .phase1 import Phase1Worker
from .phase2 import Phase2Worker
from .recall import RecallSearcher
from .schemas import (
    AskResult,
    JOB_KIND_PHASE1,
    MemoryConfig,
)
from .storage import StorageLayer, config_hash_of, now_ms

log = logging.getLogger(__name__)

__all__ = ["MemorySubsystem", "MemoryConfig", "AskResult"]


class MemorySubsystem:
    """Singleton facade. agent_main creates one and calls start() / stop().

    Constructor parameters (kwargs only):
        robot_root       Path to ~/.unitree/g1_brain (or override)
        rollout_path     Absolute path to current session's JSONL
        session_id       ConversationLogger.session_id (32-hex)
        cfg              MemoryConfig (or dict from yaml)
        conversations_dir  Directory holding all session JSONLs (defaults
                         to rollout_path.parent)
        config_hash_input  Optional dict; we hash it as sessions.config_hash
    """

    def __init__(
        self,
        *,
        robot_root: Path,
        rollout_path: Path,
        session_id: str,
        cfg: Any = None,
        conversations_dir: Optional[Path] = None,
        config_hash_input: Optional[dict] = None,
    ):
        if isinstance(cfg, dict):
            self.cfg = MemoryConfig.from_dict(cfg)
        elif isinstance(cfg, MemoryConfig):
            self.cfg = cfg
        else:
            self.cfg = MemoryConfig()

        self.robot_root = robot_root.expanduser().resolve()
        self.rollout_path = Path(rollout_path).expanduser().resolve()
        self.session_id = session_id
        self.conversations_dir = (
            conversations_dir.expanduser().resolve()
            if conversations_dir
            else self.rollout_path.parent
        )
        self._config_hash_input = config_hash_input

        self.storage = StorageLayer(self.robot_root)
        self.jobs = JobScheduler(self.storage)

        # Two distinct codex usage modes share the same binary + codex_home
        self.codex_exec = CodexClient(
            codex_bin="codex",
            workdir=self.storage.memories_dir,
            codex_home=self.storage.codex_runtime_dir,
            sandbox="read-only",
        )
        self.daemon = CodexDaemon(
            codex_bin="codex",
            workdir=self.storage.memories_dir,
            codex_home=self.storage.codex_runtime_dir,
            sandbox="read-only",
            model_override=(self.cfg.slow_brain_model or None),
            ping_interval_s=self.cfg.daemon_ping_interval_s,
            max_restart_attempts=self.cfg.daemon_restart_max_attempts,
            ask_queue_max=self.cfg.ask_queue_max,
        )

        self.phase1 = Phase1Worker(
            storage=self.storage,
            jobs=self.jobs,
            codex=self.codex_exec,
            max_jsonl_bytes=self.cfg.phase1_max_jsonl_bytes,
            model_override=(self.cfg.phase1_model or None),
        )
        self.phase2 = Phase2Worker(
            storage=self.storage,
            jobs=self.jobs,
            codex=self.codex_exec,
            max_raw_memories=self.cfg.phase2_max_raw_memories,
            max_unused_days=self.cfg.phase2_max_unused_days,
            model_override=(self.cfg.phase2_model or None),
        )
        self.phase1.set_on_complete(self._on_phase1_complete)

        self.recall = RecallSearcher(
            memories_dir=self.storage.memories_dir,
            conversations_dir=self.conversations_dir,
            default_max_lines=self.cfg.recall_grep_default_max_lines,
            read_max_bytes=self.cfg.recall_read_max_bytes,
        )
        self.context = ContextBuilder(
            memories_dir=self.storage.memories_dir,
            passive_summary_max_tokens=self.cfg.passive_summary_max_tokens,
            passive_agents_md_max_tokens=self.cfg.passive_agents_md_max_tokens,
        )

        self._started = False
        self._stopping = False
        self._cancel_tokens: dict[str, asyncio.Event] = {}

    # ---------- lifecycle ----------

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        await asyncio.to_thread(self.storage.init)
        try:
            await asyncio.to_thread(
                self.storage.upsert_session,
                session_id=self.session_id,
                rollout_path=self.rollout_path,
                robot_id=os.environ.get("UNITREE_ROBOT_ID", "g1"),
                git_sha=self._read_git_sha(),
                config_hash=(
                    config_hash_of(self._config_hash_input)
                    if self._config_hash_input is not None else None
                ),
            )
        except Exception:  # noqa: BLE001
            log.exception("upsert_session failed; memory will run degraded")

        # Phase1 worker
        try:
            await self.phase1.start()
        except Exception:  # noqa: BLE001
            log.exception("phase1 worker start failed")

        # Daemon starts in background; failures are non-fatal
        try:
            asyncio.create_task(self.daemon.start())
        except Exception:  # noqa: BLE001
            log.exception("codex daemon start scheduling failed")

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        # Force Phase1 on current session before tearing down
        try:
            await asyncio.to_thread(
                self.storage.mark_session_ended, self.session_id,
            )
            self.jobs.enqueue(
                kind=JOB_KIND_PHASE1, job_key=self.session_id,
                retry_remaining=2,
            )
        except Exception:  # noqa: BLE001
            log.exception("phase1 final enqueue failed")
        try:
            await self.phase1.run_one_now(self.session_id)
        except Exception:  # noqa: BLE001
            log.exception("phase1 force-run on shutdown failed")
        try:
            await self.phase2.trigger_after_phase1(self.session_id)
        except Exception:  # noqa: BLE001
            log.exception("phase2 final trigger failed")
        try:
            await self.phase1.stop()
        except Exception:  # noqa: BLE001
            log.exception("phase1 stop failed")
        try:
            await self.phase2.stop()
        except Exception:  # noqa: BLE001
            log.exception("phase2 stop failed")
        try:
            await self.daemon.stop()
        except Exception:  # noqa: BLE001
            log.exception("codex daemon stop failed")
        await asyncio.to_thread(self.storage.close)

    # ---------- public facade ----------

    def build_passive_context(self) -> str:
        try:
            return self.context.build()
        except Exception:  # noqa: BLE001
            log.exception("build_passive_context failed; returning empty")
            return ""

    async def on_plan_done(self) -> None:
        """Called by agent_main / brain_agent after each plan_done.

        Schedules Phase1 for the current session with debounce.
        """
        if not self._started or self._stopping:
            return
        debounce_until = now_ms() + int(self.cfg.phase1_debounce_s * 1000)
        try:
            await asyncio.to_thread(
                self.jobs.enqueue,
                kind=JOB_KIND_PHASE1,
                job_key=self.session_id,
                retry_remaining=3,
                debounce_until_ms=debounce_until,
            )
        except Exception:  # noqa: BLE001
            log.exception("on_plan_done enqueue failed")

    # ---------- cancel tokens (for SkillServer ask_slow_brain) ----------

    def register_cancel_token(self, call_id: str) -> asyncio.Event:
        evt = asyncio.Event()
        self._cancel_tokens[call_id] = evt
        return evt

    def unregister_cancel_token(self, call_id: str) -> None:
        self._cancel_tokens.pop(call_id, None)

    def cancel_all_in_flight(self) -> int:
        """Set every registered cancel_event. Used on barge-in."""
        n = 0
        for evt in list(self._cancel_tokens.values()):
            if not evt.is_set():
                evt.set()
                n += 1
        return n

    # ---------- internal callbacks ----------

    def _on_phase1_complete(self, session_id: str):
        return self.phase2.trigger_after_phase1(session_id)

    @staticmethod
    def _read_git_sha() -> Optional[str]:
        """Best-effort git SHA of the g1_brain repo."""
        try:
            import subprocess
            r = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0:
                return r.stdout.strip() or None
        except (subprocess.SubprocessError, OSError):
            return None
        return None
