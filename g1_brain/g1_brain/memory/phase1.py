"""Phase 1: per-session memory extraction.

Reads one session's JSONL, projects it into a compact text representation,
sends it through `codex exec` with a strict JSON output prompt, parses
{raw_memory, rollout_summary, rollout_slug}, and persists to stage1_outputs.
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
    JOB_KIND_PHASE1,
    Stage1Output,
)
from .storage import StorageLayer, now_ms

log = logging.getLogger(__name__)


def _load_phase1_system_prompt() -> str:
    p = Path(__file__).parent / "prompts" / "phase1_system.md"
    return p.read_text(encoding="utf-8")


def build_session_projection(
    jsonl_path: Path, max_bytes: int = 80_000,
) -> str:
    """Read a session JSONL and produce a compact text view for the model.

    If the projection exceeds max_bytes, drop earliest turns first while
    keeping the metadata header.
    """
    lines = []
    metadata_lines = []
    metadata_lines.append("# Session metadata")

    events_by_turn: dict = {}  # turn_id -> list of text lines
    current_turn = "t-pre"
    session_id_seen = ""
    started_at_seen = ""
    ended_at_seen = ""

    try:
        with open(jsonl_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not session_id_seen and ev.get("session_id"):
                    session_id_seen = ev["session_id"]
                ts = ev.get("timestamp", "")
                if not started_at_seen:
                    started_at_seen = ts
                ended_at_seen = ts or ended_at_seen

                turn = ev.get("turn_id") or current_turn
                current_turn = turn
                events_by_turn.setdefault(turn, [])

                etype = ev.get("type")
                if etype == "user":
                    txt = _extract_text(ev.get("message"))
                    if txt:
                        events_by_turn[turn].append(
                            f"[{turn}] user: {_clip(txt, 500)}"
                        )
                elif etype == "assistant":
                    txt = _extract_text(ev.get("message"))
                    if txt:
                        events_by_turn[turn].append(
                            f"[{turn}] assistant: {_clip(txt, 500)}"
                        )
                elif etype == "tool_use":
                    name, inp = _extract_tool_use(ev.get("message"))
                    events_by_turn[turn].append(
                        f"[{turn}] tool_use[{name}]: {_clip(json.dumps(inp, ensure_ascii=False), 200)}"
                    )
                elif etype == "tool_result":
                    name = ev.get("tool_name", "?")
                    body = _extract_tool_result(ev.get("message"))
                    events_by_turn[turn].append(
                        f"[{turn}] tool_result[{name}]: {_clip(body, 200)}"
                    )
                elif etype == "meta":
                    subtype = ev.get("subtype", "")
                    data = ev.get("data") or {}
                    line = _render_meta(turn, subtype, data)
                    if line:
                        events_by_turn[turn].append(line)
                # system: drop (no value for memory)
    except OSError as e:
        log.warning("phase1 projection: cannot read %s: %s", jsonl_path, e)

    metadata_lines.append(f"session_id: {session_id_seen}")
    metadata_lines.append(f"started_at: {started_at_seen}")
    metadata_lines.append(f"ended_at:   {ended_at_seen}")
    metadata_lines.append("")
    metadata_lines.append("# Events (chronological)")

    # Assemble in turn order; turns are like "t-0001" so simple sort works
    def _turn_key(t: str) -> tuple[int, str]:
        m = re.match(r"t-(\d+)$", t or "")
        return (int(m.group(1)) if m else 0, t or "")

    body_lines: list[str] = []
    for turn in sorted(events_by_turn.keys(), key=_turn_key):
        for ln in events_by_turn[turn]:
            body_lines.append(ln)

    full = "\n".join(metadata_lines + body_lines)
    if len(full.encode("utf-8")) <= max_bytes:
        return full

    # Trim: drop earliest turns until under budget. Always keep metadata.
    turns_sorted = sorted(events_by_turn.keys(), key=_turn_key)
    while turns_sorted and len(full.encode("utf-8")) > max_bytes:
        drop_turn = turns_sorted.pop(0)
        events_by_turn.pop(drop_turn, None)
        body_lines = []
        for turn in turns_sorted:
            for ln in events_by_turn[turn]:
                body_lines.append(ln)
        full = "\n".join(metadata_lines + ["[earlier turns trimmed]"] + body_lines)
    return full


def _extract_text(message) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                t = c.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "".join(parts)
    return ""


def _extract_tool_use(message) -> tuple[str, dict]:
    if not isinstance(message, dict):
        return "?", {}
    content = message.get("content")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                return c.get("name", "?"), c.get("input") or {}
    return "?", {}


def _extract_tool_result(message) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_result":
                inner = c.get("content")
                if isinstance(inner, list):
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            t = sub.get("text")
                            if isinstance(t, str):
                                return t
    return ""


def _render_meta(turn: str, subtype: str, data: dict) -> str:
    if subtype == "scene_snapshot":
        trig = data.get("trigger", "?")
        pers = data.get("persons_visible")
        obs = data.get("nearest_obstacle_m")
        gnd = data.get("ground_constraint", "?")
        warns = data.get("warnings") or []
        bits = [f"trigger={trig}"]
        if pers is not None:
            bits.append(f"persons={pers}")
        if obs is not None:
            bits.append(f"obstacle_m={obs}")
        bits.append(f"ground={gnd}")
        if warns:
            bits.append(f"warn={','.join(map(str, warns))}")
        return f"[{turn}] scene: " + ", ".join(bits)
    if subtype == "action_result":
        name = data.get("tool_name", "?")
        status = data.get("status", "?")
        reason = data.get("blocked_reason")
        outcome = data.get("outcome_metrics") or {}
        bits = [f"status={status}"]
        if reason:
            bits.append(f"reason={reason}")
        if outcome.get("displacement_m") is not None:
            bits.append(f"displacement={outcome['displacement_m']}")
        if outcome.get("end_safety_state"):
            bits.append(f"end={outcome['end_safety_state']}")
        return f"[{turn}] action_result[{name}]: " + ", ".join(bits)
    if subtype == "safety_event":
        kind = data.get("kind", "?")
        rule = data.get("rule")
        det = data.get("details", "")
        return f"[{turn}] safety_event[{kind}]: rule={rule} {_clip(det, 200)}"
    if subtype == "plan_done":
        return f"[{turn}] plan_done"
    if subtype == "wake_event":
        wake = data.get("text", "")
        return f"[{turn}] wake: {_clip(wake, 80)}"
    return ""


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"


def parse_stage1_json(text: str) -> Stage1Output:
    """Parse the JSON output from Phase 1 codex exec.

    Accepts a bare JSON object or a JSON object wrapped in ```json fences.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Strip ```json ... ``` fence
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    # Find the first { ... last } in case there's leading/trailing prose
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first >= 0 and last > first:
        cleaned = cleaned[first : last + 1]

    obj = json.loads(cleaned)
    if not isinstance(obj, dict):
        raise ValueError(f"phase1 output is not a JSON object: {type(obj)}")

    raw_memory = obj.get("raw_memory", "")
    rollout_summary = obj.get("rollout_summary", "")
    rollout_slug = obj.get("rollout_slug")

    if not isinstance(raw_memory, str):
        raw_memory = str(raw_memory) if raw_memory is not None else ""
    if not isinstance(rollout_summary, str):
        rollout_summary = str(rollout_summary) if rollout_summary is not None else ""
    if rollout_slug is not None and not isinstance(rollout_slug, str):
        rollout_slug = str(rollout_slug)

    # Sanitize slug
    if rollout_slug:
        rollout_slug = re.sub(r"[^a-z0-9\-_]+", "-", rollout_slug.lower())[:40].strip("-")
        rollout_slug = rollout_slug or None

    return Stage1Output(
        raw_memory=raw_memory.strip(),
        rollout_summary=rollout_summary.strip(),
        rollout_slug=rollout_slug,
    )


class Phase1Worker:
    """Single asyncio task that drains phase1 jobs from the jobs table."""

    def __init__(
        self,
        *,
        storage: StorageLayer,
        jobs: JobScheduler,
        codex: CodexClient,
        max_jsonl_bytes: int = 80_000,
        model_override: Optional[str] = None,
        poll_interval_s: float = 2.0,
        codex_timeout_s: float = 120.0,
    ):
        self._storage = storage
        self._jobs = jobs
        self._codex = codex
        self._max_bytes = max_jsonl_bytes
        self._model = model_override
        self._poll_interval = poll_interval_s
        self._codex_timeout = codex_timeout_s
        self._stop_evt = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._on_complete_cb = None
        self._system_prompt = _load_phase1_system_prompt()

    def set_on_complete(self, cb) -> None:
        """cb(session_id: str) called after each successful job."""
        self._on_complete_cb = cb

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_evt.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop_evt.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                claimed = await asyncio.to_thread(
                    self._jobs.try_claim, kind=JOB_KIND_PHASE1, lease_s=120,
                )
            except Exception:  # noqa: BLE001
                log.exception("phase1 claim failed")
                await asyncio.sleep(self._poll_interval)
                continue

            if claimed is None:
                try:
                    await asyncio.wait_for(
                        self._stop_evt.wait(), timeout=self._poll_interval,
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            session_id = claimed["job_key"]
            token = claimed["ownership_token"]
            try:
                await self._run_one(session_id, token)
            except Exception as e:  # noqa: BLE001
                log.exception("phase1 worker exception for %s", session_id)
                try:
                    await asyncio.to_thread(
                        self._jobs.fail, JOB_KIND_PHASE1, session_id, token,
                        error=str(e),
                    )
                except Exception:  # noqa: BLE001
                    log.exception("phase1 fail() raised")

    async def run_one_now(self, session_id: str) -> Optional[Stage1Output]:
        """Run Phase1 synchronously for a session, bypassing jobs table.

        Used by integration tests and the force-on-shutdown path.
        """
        row = await asyncio.to_thread(self._storage.get_session, session_id)
        if row is None:
            log.warning("phase1.run_one_now: no session %s in DB", session_id)
            return None
        jsonl_path = Path(row["rollout_path"])
        if not jsonl_path.exists():
            log.warning("phase1.run_one_now: jsonl missing %s", jsonl_path)
            return None
        return await self._extract_and_persist(session_id, jsonl_path)

    async def _run_one(self, session_id: str, token: str) -> None:
        # Heartbeat task
        hb_task = asyncio.create_task(self._heartbeat(session_id, token))
        try:
            row = await asyncio.to_thread(self._storage.get_session, session_id)
            if row is None:
                log.warning("phase1: session %s not in DB; marking done (noop)",
                            session_id)
                await asyncio.to_thread(
                    self._jobs.complete, JOB_KIND_PHASE1, session_id, token,
                )
                return
            jsonl_path = Path(row["rollout_path"])
            if not jsonl_path.exists():
                log.warning("phase1: jsonl missing for %s; marking done (noop)",
                            session_id)
                await asyncio.to_thread(
                    self._jobs.complete, JOB_KIND_PHASE1, session_id, token,
                )
                return

            out = await self._extract_and_persist(session_id, jsonl_path)
            if out is None:
                await asyncio.to_thread(
                    self._jobs.fail, JOB_KIND_PHASE1, session_id, token,
                    error="extraction returned None",
                )
                return

            await asyncio.to_thread(
                self._jobs.complete, JOB_KIND_PHASE1, session_id, token,
                watermark=int(jsonl_path.stat().st_size),
            )
            if self._on_complete_cb is not None:
                try:
                    cb_result = self._on_complete_cb(session_id)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result
                except Exception:  # noqa: BLE001
                    log.exception("phase1 on_complete callback raised")
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _extract_and_persist(
        self, session_id: str, jsonl_path: Path,
    ) -> Optional[Stage1Output]:
        projection = await asyncio.to_thread(
            build_session_projection, jsonl_path, self._max_bytes,
        )
        prompt = self._system_prompt + "\n\n---\n\n" + projection

        # Try once, then retry once with stricter re-prompt on parse failure
        for attempt in (1, 2):
            try:
                result = await self._codex.exec_once(
                    prompt,
                    timeout_s=self._codex_timeout,
                    model_override=self._model,
                    ephemeral=True,
                )
            except CodexQuotaExhausted as e:
                log.warning("phase1: codex quota exhausted: %s", e)
                # Defer the job's retry by raising; outer worker will mark
                # retry via fail()
                raise
            except CodexExecError as e:
                log.warning("phase1 codex exec failed (attempt %d): %s",
                            attempt, e)
                if attempt == 2:
                    raise
                continue

            try:
                out = parse_stage1_json(result.text)
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("phase1 parse failed (attempt %d): %s", attempt, e)
                if attempt == 2:
                    # Persist a noop output to avoid infinite retry
                    out = Stage1Output(
                        raw_memory="",
                        rollout_summary="",
                        rollout_slug=None,
                    )
                    break
                prompt = (
                    self._system_prompt
                    + "\n\n---\n\nREMINDER: Output ONLY one JSON object with "
                    + 'keys "raw_memory", "rollout_summary", "rollout_slug". '
                    + "No prose. No markdown fence.\n\n---\n\n"
                    + projection
                )
                continue
            break

        source_updated_at = (
            int(jsonl_path.stat().st_mtime * 1000) if jsonl_path.exists() else now_ms()
        )
        await asyncio.to_thread(
            self._storage.upsert_stage1_output,
            session_id, out, source_updated_at,
        )
        return out

    async def _heartbeat(self, session_id: str, token: str) -> None:
        try:
            while not self._stop_evt.is_set():
                await asyncio.sleep(20)
                ok = await asyncio.to_thread(
                    self._jobs.heartbeat, JOB_KIND_PHASE1, session_id, token,
                )
                if not ok:
                    return
        except asyncio.CancelledError:
            return
