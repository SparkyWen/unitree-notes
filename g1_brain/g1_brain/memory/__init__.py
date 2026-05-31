"""Memory subsystem — Codex-style recall + ask_slow_brain for the G1 brain.

Public surface:
    MemorySubsystem  — singleton facade owned by agent_main
    MemoryConfig     — config dataclass (loaded from g1_brain.yaml memory:)
    AskResult        — return type of ask_slow_brain

Everything else is internal.
"""
from __future__ import annotations

import asyncio
import json
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

        # Two distinct codex usage modes share the same binary + codex_home.
        # Both inherit the "high reasoning + 1.5x priority tier" floor and a
        # 16 MB StreamReader buffer so long progress notifications can't
        # crash the read loop. Configurable via MemoryConfig.codex_*.
        self.codex_exec = CodexClient(
            codex_bin="codex",
            workdir=self.storage.memories_dir,
            codex_home=self.storage.codex_runtime_dir,
            sandbox="read-only",
            stdout_buffer_bytes=self.cfg.daemon_stdout_buffer_bytes,
            reasoning_effort=self.cfg.codex_reasoning_effort,
            reasoning_summary=self.cfg.codex_reasoning_summary,
            service_tier=self.cfg.codex_service_tier,
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
            stdout_buffer_bytes=self.cfg.daemon_stdout_buffer_bytes,
            reasoning_effort=self.cfg.codex_reasoning_effort,
            reasoning_summary=self.cfg.codex_reasoning_summary,
            service_tier=self.cfg.codex_service_tier,
            conversations_dir=self.conversations_dir,
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
        self._busy_gate = None
        self._backfill_task: Optional[asyncio.Task] = None

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

        # Backfill: any historical JSONL in conversations_dir that isn't
        # already represented in sessions/stage1_outputs gets queued for
        # Phase1 so future recalls can hit summaries, not just raw grep.
        # Deferred OFF the synchronous start() path: it only enqueues jobs (the
        # heavy Phase1 processing is gated by the busy_gate), and running it at
        # boot piled onto the perception-model-load GIL stall.
        try:
            self._backfill_task = asyncio.create_task(self._deferred_backfill())
        except Exception:  # noqa: BLE001
            log.exception("historical backfill scheduling failed (non-fatal)")

        # Daemon starts in background; failures are non-fatal
        try:
            asyncio.create_task(self.daemon.start())
        except Exception:  # noqa: BLE001
            log.exception("codex daemon start scheduling failed")

    def set_busy_gate(self, cb) -> None:
        """Wire a predicate (cb() -> bool) that is True while a conversation
        turn is active. agent_main calls this after the state machine exists.

        Propagates to Phase1/Phase2 so neither starts new codex work while the
        operator is mid-turn — the fix for "codex churns and starves wake/VAD
        during my conversation".
        """
        self._busy_gate = cb
        try:
            self.phase1.set_busy_gate(cb)
            self.phase2.set_busy_gate(cb)
        except Exception:  # noqa: BLE001
            log.exception("set_busy_gate propagation failed")

    async def _deferred_backfill(self) -> None:
        if not self.cfg.defer_when_conversation_active:
            delay = 0.0
        else:
            delay = max(0.0, float(self.cfg.backfill_delay_s))
        try:
            if delay:
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        try:
            await asyncio.to_thread(self._backfill_historical_sessions)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            log.exception("historical backfill failed (non-fatal)")

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        if self._backfill_task is not None:
            self._backfill_task.cancel()
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

    def _backfill_historical_sessions(self) -> None:
        """Register any JSONL transcript not yet in sessions and enqueue Phase1.

        The conversation logger uses a per-log random ID in the filename, not
        the in-event `session_id` — so reading the first JSONL line is the
        only way to map filename → durable session_id. Sessions that already
        have a stage1_output are skipped; the live session is also skipped
        (it will be handled by on_plan_done debounce / shutdown force-run).
        """
        if not self.conversations_dir.exists():
            return
        files = sorted(self.conversations_dir.glob("*.jsonl"))
        if not files:
            return
        live_path = self.rollout_path
        enqueued = 0
        for jsonl in files:
            try:
                if jsonl.resolve() == live_path.resolve():
                    continue
            except OSError:
                pass
            session_id = self._read_session_id_from_jsonl(jsonl)
            if not session_id:
                continue
            try:
                if self.storage.get_stage1_output(session_id) is not None:
                    continue
            except Exception:  # noqa: BLE001
                pass
            try:
                self.storage.upsert_session(
                    session_id=session_id,
                    rollout_path=jsonl,
                    robot_id=os.environ.get("UNITREE_ROBOT_ID", "g1"),
                )
            except Exception as e:  # noqa: BLE001
                # rollout_path is UNIQUE in the schema; if another session
                # already owns this path (rare) we just skip rather than
                # blowing up the whole backfill.
                log.debug("backfill upsert skipped for %s: %s", jsonl, e)
                continue
            try:
                self.storage.mark_session_ended(session_id)
                self.jobs.enqueue(
                    kind=JOB_KIND_PHASE1, job_key=session_id,
                    retry_remaining=2,
                )
                enqueued += 1
            except Exception:  # noqa: BLE001
                log.exception("backfill: failed for %s", jsonl)
        if enqueued:
            log.info("memory backfill: enqueued %d historical sessions for phase1", enqueued)

    @staticmethod
    def _read_session_id_from_jsonl(path: Path) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for _ in range(5):  # session_id is on the very first meta line
                    line = fh.readline()
                    if not line:
                        return None
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sid = ev.get("session_id") if isinstance(ev, dict) else None
                    if isinstance(sid, str) and sid:
                        return sid
        except OSError:
            return None
        return None

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
