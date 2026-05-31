"""ConversationLogger — per-process Claude-shape jsonl transcript.

Owns a single file under ``logs/conversations/<ISO>-<uuid>.jsonl``,
opened at agent_main start and closed at shutdown. Each line is one JSON
object whose schema mirrors the Claude session jsonl (role-tagged content
blocks, ``uuid`` / ``parent_uuid`` chaining, ``session_id`` / ``turn_id``
grouping) so the user's eventual Claude-harness ingest layer can read
these files without a schema migration.

Why these fields specifically:

- ``session_id`` / ``turn_id`` group events for retrieval. ``turn_id``
  increments on every IDLE→CAPTURING transition (one per "hi sparky").
- ``parent_uuid`` chains events within a turn so a future graph view
  can reconstruct the conversation order even if file reads interleave.
- ``timestamp`` is ISO-8601 UTC with millisecond precision so SQLite
  FTS5 / lexical sort stays consistent.
- Per-event ``text`` is trimmed to ``max_text_kb`` so the jsonl stays
  skim-friendly; the full text remains in ``agent.log``.

The logger is best-effort: if the file fails to open, it logs a warning
and silently no-ops. We never want a logging failure to take down the
agent.

See docs/audio-control-update01.md.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional  # noqa: F401

log = logging.getLogger(__name__)


def _iso_utc_now_ms() -> str:
    """ISO-8601 UTC with millisecond precision."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _filename_now_iso() -> str:
    """Filesystem-safe ISO-8601 UTC for filenames (colons replaced)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _short_uuid() -> str:
    return uuid.uuid4().hex[:8]


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    """getattr with isinstance fallback for dataclasses or dicts."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _safe_user_field(scene_state: Any, field: str) -> Any:
    """Safely pluck scene_state.user.<field>."""
    if scene_state is None:
        return None
    user = _safe_attr(scene_state, "user")
    if user is None:
        return None
    return _safe_attr(user, field)


def _safe_list(obj: Any, name: str) -> list:
    val = _safe_attr(obj, name)
    if isinstance(val, (list, tuple, set)):
        return list(val)
    return []


def _summarize_detections(scene_state: Any) -> Dict[str, Dict[str, int]]:
    """Best-effort detections summary: {camera_name: {class_name: count}}."""
    result: Dict[str, Dict[str, int]] = {}
    detections = _safe_attr(scene_state, "detections")
    if detections is None:
        return result
    # detections may be a dict of {camera: list_of_detections}
    if isinstance(detections, dict):
        for cam_name, det_list in detections.items():
            counts: Dict[str, int] = {}
            if isinstance(det_list, (list, tuple)):
                for d in det_list:
                    cls = _safe_attr(d, "class_name") or _safe_attr(d, "label")
                    if cls:
                        counts[str(cls)] = counts.get(str(cls), 0) + 1
            if counts:
                result[str(cam_name)] = counts
    return result


def _trim_text(text: str, max_bytes: int) -> str:
    """Trim text to max_bytes (utf-8) without splitting a multi-byte char.

    UTF-8 chars span 1–4 bytes; a slice at an arbitrary byte offset can
    end mid-char. We try decoding and back off one byte at a time (up to
    4) until the prefix decodes cleanly. The 4-iteration cap is the worst
    case for valid UTF-8.
    """
    if max_bytes <= 0:
        return text
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    for _ in range(4):
        try:
            return truncated.decode("utf-8") + "…[trimmed]"
        except UnicodeDecodeError:
            truncated = truncated[:-1]
            if not truncated:
                break
    # Should not reach here for valid input; conservative last-resort.
    return text[: max_bytes // 4] + "…[trimmed]"


class ConversationLogger:
    """Append-only Claude-shape jsonl writer for one agent_main process.

    Thread-safe: a single lock serialises ``write+flush`` so callers can be
    on either the asyncio event-loop thread or a wake-word worker thread.
    """

    def __init__(
        self,
        log_dir: Path,
        *,
        keep_last_n: int = 50,
        max_text_kb: int = 4,
        enabled: bool = True,
    ):
        self.enabled = enabled
        self._max_text_bytes = max(0, int(max_text_kb)) * 1024
        self._lock = threading.Lock()
        self._closed = False
        self.session_id = uuid.uuid4().hex
        self._turn_id_counter = 0
        self.current_turn_id: Optional[str] = None
        self._last_uuid: Optional[str] = None  # parent_uuid chain within a turn
        self._fh = None
        self.path: Optional[Path] = None

        if not self.enabled:
            log.info("ConversationLogger disabled by config")
            return

        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning(
                "ConversationLogger: cannot create %s (%s); disabling", log_dir, e,
            )
            self.enabled = False
            return

        self._rotate(log_dir, keep_last_n)

        fname = f"{_filename_now_iso()}-{_short_uuid()}.jsonl"
        self.path = log_dir / fname
        try:
            # Line-buffered append. We also explicitly flush per write so a
            # SIGKILL keeps everything up to the last completed event.
            self._fh = open(self.path, "a", encoding="utf-8", buffering=1)
        except OSError as e:
            log.warning(
                "ConversationLogger: cannot open %s (%s); disabling", self.path, e,
            )
            self.enabled = False
            self._fh = None

    # ------------------------------------------------------------------ housekeeping

    @staticmethod
    def _rotate(log_dir: Path, keep_last_n: int) -> None:
        """Delete oldest jsonl files beyond keep_last_n.

        Best-effort: swallow FS errors so a permission glitch on cleanup
        never blocks the new launch.
        """
        if keep_last_n is None or keep_last_n <= 0:
            return
        try:
            files = sorted(
                log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
            )
        except OSError:
            return
        excess = len(files) - keep_last_n
        for old in files[: max(0, excess)]:
            try:
                old.unlink()
            except OSError:
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._emit_meta("shutdown", {})
        with self._lock:
            self._closed = True
            if self._fh is not None:
                try:
                    self._fh.flush()
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None

    # ------------------------------------------------------------------ public API

    def log_session_start(self, *, argv: List[str], config_path: str) -> None:
        self._emit_meta("session_start", {
            "argv": argv,
            "config_path": config_path,
            "pid": os.getpid(),
        })

    def begin_turn(self) -> str:
        """Mark the start of a new user turn (called by CSM on IDLE→CAPTURING)."""
        self._turn_id_counter += 1
        self.current_turn_id = f"t-{self._turn_id_counter:04d}"
        self._last_uuid = None
        self._emit_meta("turn_start", {"turn_id": self.current_turn_id})
        return self.current_turn_id

    def log_user_transcript(self, text: str) -> None:
        self._emit(
            "user",
            message={
                "role": "user",
                "content": [{"type": "text", "text": self._trim(text)}],
            },
        )

    def log_assistant_transcript(self, text: str) -> None:
        self._emit(
            "assistant",
            message={
                "role": "assistant",
                "content": [{"type": "text", "text": self._trim(text)}],
            },
        )

    def log_tool_use(self, call_id: str, name: str, input_args: Dict[str, Any]) -> None:
        self._emit(
            "tool_use",
            message={
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": input_args,
                }],
            },
        )

    def log_tool_result(self, call_id: str, name: str, result: Dict[str, Any]) -> None:
        # Serialise the result dict as JSON text inside the tool_result block,
        # matching the Claude convention (a tool_result content block has a
        # `content` list of typed sub-blocks; we use a single text sub-block).
        try:
            payload = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            payload = repr(result)
        self._emit(
            "tool_result",
            message={
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": [{"type": "text", "text": self._trim(payload)}],
                }],
            },
            extra={"tool_name": name},
        )

    def log_system_message(self, text: str) -> None:
        self._emit(
            "system",
            message={
                "role": "system",
                "content": [{"type": "text", "text": self._trim(text)}],
            },
        )

    # ---- meta helpers ------------------------------------------------

    def log_wake_event(self, text: str) -> None:
        self._emit_meta("wake_event", {"text": text})

    def log_barge_in(self, *, from_state: str, wake_text: str) -> None:
        self._emit_meta(
            "barge_in", {"from_state": from_state, "wake_text": wake_text},
        )

    def log_state_transition(self, *, from_state: str, to_state: str,
                             reason: Optional[str] = None) -> None:
        data: Dict[str, Any] = {"from": from_state, "to": to_state}
        if reason:
            data["reason"] = reason
        self._emit_meta("state_transition", data)

    def log_plan_done(self) -> None:
        self._emit_meta("plan_done", {"turn_id": self.current_turn_id})

    def log_plan_watchdog_timeout(self, *, pending: List[str]) -> None:
        self._emit_meta("plan_watchdog_timeout", {"pending": list(pending)})

    def log_no_speech_idle(self, *, timeout_s: float) -> None:
        self._emit_meta("no_speech_idle", {"timeout_s": float(timeout_s)})

    def log_response_canceled(self, *, reason: str) -> None:
        self._emit_meta("response_canceled", {"reason": reason})

    def log_error(self, *, where: str, msg: str) -> None:
        self._emit_meta("error", {"where": where, "msg": msg})

    # ---- memory-subsystem event helpers ------------------------------

    def log_scene_snapshot(
        self,
        *,
        trigger: str,
        scene_state: Any,
        frame_paths: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a keyframe of the perceived scene.

        Triggered at turn_start, pre_motion, post_motion. Not for every
        perception frame — only inflection points the memory pipeline
        should see.

        Best-effort: extracts whatever fields are available from
        scene_state; missing fields become None. Caller-side failure to
        snapshot must never propagate out.
        """
        try:
            data: Dict[str, Any] = {
                "ts_ms": int(time.time() * 1000),
                "trigger": trigger,
                "persons_visible": _safe_attr(scene_state, "persons_visible"),
                "user_pose": _safe_user_field(scene_state, "pose"),
                "user_gesture": _safe_user_field(scene_state, "gesture"),
                "nearest_person_m": _safe_attr(scene_state, "nearest_person_m"),
                "nearest_obstacle_m": _safe_attr(scene_state, "nearest_obstacle_m"),
                "ground_constraint": _safe_attr(scene_state, "ground_constraint"),
                "warnings": _safe_list(scene_state, "warnings"),
                "detections_summary": _summarize_detections(scene_state),
                "frame_ref": (
                    {k: str(v) for k, v in frame_paths.items()}
                    if frame_paths else None
                ),
            }
            self._emit_meta("scene_snapshot", data)
        except Exception:  # noqa: BLE001
            log.exception("log_scene_snapshot failed; dropped")

    def log_action_result(
        self,
        *,
        tool_use_id: str,
        tool_name: str,
        args: Dict[str, Any],
        status: str,
        blocked_reason: Optional[str] = None,
        outcome_metrics: Optional[Dict[str, Any]] = None,
        result_payload_brief: str = "",
    ) -> None:
        try:
            self._emit_meta("action_result", {
                "ts_ms": int(time.time() * 1000),
                "tool_use_id": tool_use_id,
                "tool_name": tool_name,
                "args": args,
                "status": status,
                "blocked_reason": blocked_reason,
                "outcome_metrics": outcome_metrics,
                "result_payload_brief": (result_payload_brief or "")[:256],
            })
        except Exception:  # noqa: BLE001
            log.exception("log_action_result failed; dropped")

    def log_safety_event(
        self,
        *,
        kind: str,
        rule: Optional[str] = None,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        details: str = "",
        associated_tool_use_id: Optional[str] = None,
    ) -> None:
        try:
            self._emit_meta("safety_event", {
                "ts_ms": int(time.time() * 1000),
                "kind": kind,
                "rule": rule,
                "from_state": from_state,
                "to_state": to_state,
                "details": (details or "")[:512],
                "associated_tool_use_id": associated_tool_use_id,
            })
        except Exception:  # noqa: BLE001
            log.exception("log_safety_event failed; dropped")

    # ------------------------------------------------------------------ internals

    def _trim(self, text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        return _trim_text(text, self._max_text_bytes) if self._max_text_bytes > 0 else text

    def _emit(self, type_: str, *,
              message: Optional[Dict[str, Any]] = None,
              extra: Optional[Dict[str, Any]] = None) -> None:
        record: Dict[str, Any] = {
            "uuid": uuid.uuid4().hex,
            "parent_uuid": self._last_uuid,
            "session_id": self.session_id,
            "turn_id": self.current_turn_id,
            "timestamp": _iso_utc_now_ms(),
            "type": type_,
        }
        if message is not None:
            record["message"] = message
        if extra:
            record.update(extra)
        self._write(record)
        self._last_uuid = record["uuid"]

    def _emit_meta(self, subtype: str, data: Dict[str, Any]) -> None:
        record = {
            "uuid": uuid.uuid4().hex,
            "parent_uuid": self._last_uuid,
            "session_id": self.session_id,
            "turn_id": self.current_turn_id,
            "timestamp": _iso_utc_now_ms(),
            "type": "meta",
            "subtype": subtype,
            "data": data,
        }
        self._write(record)
        # Meta events still chain so the file stays linear, but we deliberately
        # do not advance `_last_uuid` for meta-only subtypes that are noisy
        # (state_transition fires very frequently). Keeping it advanced is
        # actually fine for jsonl reads either way; cost is null.
        self._last_uuid = record["uuid"]

    def _write(self, record: Dict[str, Any]) -> None:
        if not self.enabled or self._fh is None or self._closed:
            return
        try:
            line = json.dumps(record, ensure_ascii=False)
        except (TypeError, ValueError):
            log.exception("ConversationLogger: failed to serialise record")
            return
        with self._lock:
            if self._closed or self._fh is None:
                return
            try:
                self._fh.write(line + "\n")
                self._fh.flush()
            except OSError as e:
                log.warning("ConversationLogger write failed: %s", e)
                # Don't disable on a single failure; could be transient.
