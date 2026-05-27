"""Phase 2: global consolidation.

Triggered after Phase 1 completes for any session. Steps:
1. Claim global lock (single concurrent Phase 2 per robot).
2. Pull top-N stage1 outputs from DB.
3. Sync raw_memories.md + rollout_summaries/*.md.
4. Run `git status` to detect changes from baseline.
5. If dirty, call codex exec with consolidation prompt → MEMORY.md + memory_summary.md.
6. Commit baseline.
7. Release lock.

Only Phase1-done triggers it. There is no idle/periodic tick.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from .codex_client import CodexClient, CodexExecError, CodexQuotaExhausted
from .jobs import JobScheduler
from .schemas import (
    JOB_KIND_PHASE2_GLOBAL_LOCK,
    PHASE2_GLOBAL_LOCK_KEY,
)
from .storage import StorageLayer, atomic_write

log = logging.getLogger(__name__)


def _load_phase2_system_prompt() -> str:
    p = Path(__file__).parent / "prompts" / "phase2_system.md"
    return p.read_text(encoding="utf-8")


def parse_phase2_json(text: str) -> tuple[str, str]:
    """Parse {memory_md, memory_summary_md} from a phase2 model output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first >= 0 and last > first:
        cleaned = cleaned[first : last + 1]
    obj = json.loads(cleaned)
    if not isinstance(obj, dict):
        raise ValueError("phase2 output is not a JSON object")
    memory_md = obj.get("memory_md", "")
    memory_summary_md = obj.get("memory_summary_md", "")
    if not isinstance(memory_md, str):
        memory_md = str(memory_md)
    if not isinstance(memory_summary_md, str):
        memory_summary_md = str(memory_summary_md)
    return memory_md, memory_summary_md


class Phase2Worker:
    """Drives one Phase 2 consolidation pass under the global lock."""

    DEFAULT_LEASE_S = 3600

    def __init__(
        self,
        *,
        storage: StorageLayer,
        jobs: JobScheduler,
        codex: CodexClient,
        max_raw_memories: int = 256,
        max_unused_days: int = 30,
        max_rollout_summary_files: int = 200,
        model_override: Optional[str] = None,
        codex_timeout_s: float = 600.0,
    ):
        self._storage = storage
        self._jobs = jobs
        self._codex = codex
        self._max_raw_memories = max_raw_memories
        self._max_unused_days = max_unused_days
        self._max_rollout_files = max_rollout_summary_files
        self._model = model_override
        self._codex_timeout = codex_timeout_s
        self._system_prompt = _load_phase2_system_prompt()
        self._stop_evt = asyncio.Event()
        self._lock = asyncio.Lock()
        self._busy_gate = None

    async def stop(self) -> None:
        self._stop_evt.set()

    def set_busy_gate(self, cb) -> None:
        """cb() -> bool: True when a conversation turn is active."""
        self._busy_gate = cb

    def _is_busy(self) -> bool:
        if self._busy_gate is None:
            return False
        try:
            return bool(self._busy_gate())
        except Exception:  # noqa: BLE001
            log.exception("phase2 busy_gate raised; treating as not busy")
            return False

    async def trigger_after_phase1(self, session_id: str) -> None:
        """Called from Phase1Worker after a successful Phase1.

        Fire-and-forget by design; we don't block Phase1.
        """
        # Heaviest codex pass (consolidation). Skip while a turn is active; the
        # next Phase1 completion re-triggers us once the operator is idle.
        if self._is_busy():
            log.info("phase2: conversation active; deferring consolidation")
            return
        # Best-effort, single-flight on this process. The DB-side global
        # lock is the cross-process backstop.
        async with self._lock:
            try:
                await self._run_once()
            except Exception:  # noqa: BLE001
                log.exception("phase2 trigger_after_phase1 failed")

    async def run_once_now(self) -> bool:
        """Force-run a Phase 2 pass. Returns True if anything was changed."""
        async with self._lock:
            return await self._run_once()

    async def _run_once(self) -> bool:
        if self._stop_evt.is_set():
            return False

        claimed = await asyncio.to_thread(
            self._jobs.enqueue,
            kind=JOB_KIND_PHASE2_GLOBAL_LOCK,
            job_key=PHASE2_GLOBAL_LOCK_KEY,
            retry_remaining=2,
        )
        claimed = await asyncio.to_thread(
            self._jobs.try_claim,
            kind=JOB_KIND_PHASE2_GLOBAL_LOCK,
            lease_s=self.DEFAULT_LEASE_S,
            job_key=PHASE2_GLOBAL_LOCK_KEY,
        )
        if claimed is None:
            log.info("phase2: global lock held; skipping")
            return False

        token = claimed["ownership_token"]
        hb_task = asyncio.create_task(self._heartbeat(token))
        try:
            return await self._do_pass(token)
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await asyncio.to_thread(
                self._jobs.complete,
                JOB_KIND_PHASE2_GLOBAL_LOCK, PHASE2_GLOBAL_LOCK_KEY, token,
            )

    async def _do_pass(self, token: str) -> bool:
        rows = await asyncio.to_thread(
            self._storage.list_stage1_for_phase2,
            self._max_raw_memories, self._max_unused_days,
        )
        # Fast no-op: no stage1 outputs at all means there is nothing to
        # consolidate. Don't touch raw_memories.md to keep the workspace
        # clean (so subsequent passes also no-op cheaply).
        if not rows:
            log.info("phase2: no stage1 outputs available; skipping")
            return False

        # 1. Always sync the deterministic file representation
        await asyncio.to_thread(self._storage.write_raw_memories_md, rows)

        for row in rows:
            await asyncio.to_thread(self._storage.write_rollout_summary, row)
            await asyncio.to_thread(self._storage.bump_stage1_usage,
                                    row["session_id"])

        deleted = await asyncio.to_thread(
            self._storage.evict_old_rollout_summaries,
            self._max_rollout_files,
        )
        if deleted:
            log.info("phase2: evicted %d old rollout summaries", deleted)

        # 2. Check whether the workspace diverges from baseline
        status = await asyncio.to_thread(self._storage.git_status_porcelain)
        if not status.strip():
            log.info("phase2: workspace clean vs baseline; no consolidation needed")
            return False

        diff_text = await asyncio.to_thread(self._storage.git_diff_text)
        # Persist diff for the consolidation agent to read
        atomic_write(
            self._storage.memories_dir / "phase2_workspace_diff.md",
            "# Phase 2 workspace diff\n\n```diff\n"
            + diff_text[:200_000]
            + "\n```\n",
        )

        # 3. Build consolidation prompt
        raw_memories_md = (
            self._storage.memories_dir / "raw_memories.md"
        ).read_text(encoding="utf-8") if (
            self._storage.memories_dir / "raw_memories.md"
        ).exists() else ""
        current_memory_md = (
            self._storage.memories_dir / "MEMORY.md"
        ).read_text(encoding="utf-8") if (
            self._storage.memories_dir / "MEMORY.md"
        ).exists() else ""

        prompt = (
            self._system_prompt
            + "\n\n---\n\n## Current raw_memories.md\n\n"
            + raw_memories_md
            + "\n\n---\n\n## Current MEMORY.md (may be empty)\n\n"
            + current_memory_md
            + "\n\n---\n\n## Workspace diff (since last baseline)\n\n"
            + diff_text[:50_000]
            + "\n\n---\n\nNow output the JSON object."
        )

        try:
            result = await self._codex.exec_once(
                prompt,
                timeout_s=self._codex_timeout,
                model_override=self._model,
                ephemeral=True,
            )
        except CodexQuotaExhausted as e:
            log.warning("phase2: codex quota exhausted: %s", e)
            return False
        except CodexExecError as e:
            log.warning("phase2: codex exec failed: %s", e)
            return False

        try:
            memory_md, summary_md = parse_phase2_json(result.text)
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("phase2: parse failed: %s; first 200 chars: %r",
                        e, result.text[:200])
            return False

        if not memory_md and not summary_md:
            log.info("phase2: model returned empty; skipping write")
            return False

        # 4. atomic write
        await asyncio.to_thread(
            atomic_write, self._storage.memories_dir / "MEMORY.md", memory_md,
        )
        await asyncio.to_thread(
            atomic_write,
            self._storage.memories_dir / "memory_summary.md", summary_md,
        )

        # 5. commit baseline
        from datetime import datetime, timezone
        msg = f"phase2 consolidation @ {datetime.now(timezone.utc).isoformat()}"
        await asyncio.to_thread(self._storage.git_commit_baseline, msg)
        log.info("phase2: consolidation written and committed")
        return True

    async def _heartbeat(self, token: str) -> None:
        try:
            while not self._stop_evt.is_set():
                await asyncio.sleep(30)
                ok = await asyncio.to_thread(
                    self._jobs.heartbeat,
                    JOB_KIND_PHASE2_GLOBAL_LOCK, PHASE2_GLOBAL_LOCK_KEY, token,
                    extend_s=self.DEFAULT_LEASE_S,
                )
                if not ok:
                    return
        except asyncio.CancelledError:
            return
