"""Safety supervisor: whitelist, numeric bounds, run-mode gate, watchdog.

The Realtime tool dispatcher MUST run every tool call through `validate()`
before executing it.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)


GESTURE_NAMES = {
    "wave_right",
    "wave_left",
    "hands_up",
    "t_pose",
    "salute",
    "clap",
    "guard",
    "punch_combo",
}

ALLOWED_TOOLS = {"say", "stop", "release_arms", "walk", "gesture", "describe_scene"}


@dataclass
class WatchdogState:
    last_frame_age_provider: callable = None
    last_lowstate_age_provider: callable = None
    max_frame_age_s: float = 2.0
    max_lowstate_age_s: float = 0.5

    def frame_age(self) -> float:
        return self.last_frame_age_provider() if self.last_frame_age_provider else 0.0

    def lowstate_age(self) -> float:
        return self.last_lowstate_age_provider() if self.last_lowstate_age_provider else 0.0


@dataclass
class SafetyConfig:
    vx_max: float = 0.3
    vy_max: float = 0.1
    wz_max: float = 0.4
    duration_max_s: float = 1.5
    duration_min_s: float = 0.2
    say_max_chars: int = 200


class SafetySupervisor:
    """Validates tool calls, gates motion via run_mode, runs watchdog checks."""

    VALID_MODES = ("observe", "confirm", "active")

    def __init__(
        self,
        cfg: SafetyConfig,
        watchdog: WatchdogState,
        run_mode: str = "confirm",
    ):
        if run_mode not in self.VALID_MODES:
            raise ValueError(f"run_mode must be one of {self.VALID_MODES}, got {run_mode!r}")
        self.cfg = cfg
        self.wd = watchdog
        self.run_mode = run_mode

    # ----- main entry point ----------------------------------------------------
    async def validate(self, tool: str, args: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """Returns (ok, reason, sanitized_args).

        sanitized_args is the (possibly clamped) args dict the caller should
        actually use when ok=True.
        """
        if tool not in ALLOWED_TOOLS:
            return False, f"unknown tool: {tool}", {}

        if tool == "say":
            text = str(args.get("text", "")).strip()
            if not text:
                return False, "empty text", {}
            if len(text) > self.cfg.say_max_chars:
                text = text[: self.cfg.say_max_chars]
            return True, "", {"text": text}

        if tool == "describe_scene":
            if self.wd.frame_age() > self.wd.max_frame_age_s:
                return False, f"no recent frame (age={self.wd.frame_age():.1f}s)", {}
            sanitized = {
                "question": str(args.get("question", "")).strip(),
                "detail": args.get("detail", "medium"),
            }
            if sanitized["detail"] not in ("low", "medium", "high"):
                sanitized["detail"] = "medium"
            return True, "", sanitized

        # Motion tools below.
        if self.run_mode == "observe":
            return False, "observe_only mode: motion disabled", {}

        if self.wd.lowstate_age() > self.wd.max_lowstate_age_s:
            return False, f"stale lowstate (age={self.wd.lowstate_age():.2f}s)", {}

        if tool == "stop":
            sanitized: Dict[str, Any] = {}
        elif tool == "release_arms":
            sanitized = {}
        elif tool == "walk":
            try:
                vx = float(args.get("vx", 0.0))
                vy = float(args.get("vy", 0.0))
                wz = float(args.get("wz", 0.0))
                duration = float(args.get("duration_s", 0.5))
            except (TypeError, ValueError) as e:
                return False, f"bad args: {e!s}", {}

            vx = _clip(vx, -self.cfg.vx_max, self.cfg.vx_max)
            vy = _clip(vy, -self.cfg.vy_max, self.cfg.vy_max)
            wz = _clip(wz, -self.cfg.wz_max, self.cfg.wz_max)
            duration = _clip(duration, self.cfg.duration_min_s, self.cfg.duration_max_s)
            sanitized = {"vx": vx, "vy": vy, "wz": wz, "duration_s": duration}
        elif tool == "gesture":
            name = str(args.get("name", ""))
            if name not in GESTURE_NAMES:
                return False, f"unknown gesture: {name!r}", {}
            sanitized = {"name": name}
        else:
            return False, f"unhandled tool: {tool}", {}

        if self.run_mode == "confirm":
            ok = await _confirm_in_terminal(tool, sanitized)
            if not ok:
                return False, "operator declined in confirm mode", {}

        return True, "", sanitized


def _clip(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


async def _confirm_in_terminal(tool: str, sanitized: Dict[str, Any]) -> bool:
    """Print the action to stderr and read y/n from stdin in a worker thread."""

    msg = f"\n[va-demo confirm] execute {tool}({sanitized}) ? [y/N] "
    print(msg, end="", flush=True, file=sys.stderr)
    loop = asyncio.get_event_loop()
    try:
        line = await asyncio.wait_for(
            loop.run_in_executor(None, sys.stdin.readline), timeout=10.0
        )
    except asyncio.TimeoutError:
        print("[va-demo confirm] timed out, declining.", file=sys.stderr)
        return False
    line = (line or "").strip().lower()
    return line in ("y", "yes")
