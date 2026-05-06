"""SafetySupervisor — gates every skill call before SkillServer executes it.

Implements the 11 rules from `docs/g1_plan.md` §3.2 in the documented order:

  1. whitelist
  2. FSM gating
  3. run_mode (observe / confirm / active)
  4. lowstate watchdog
  5. head-cam watchdog
  6. RL policy active watchdog
  7. body pose check (gravity-projection upright check)
  8. parameter clamp (vx/vy/wz/duration)
  9. scene check for walk (clear path / nearest obstacle / nearest person)
 10. scene check for gesture (nearest person)
 11. E-stop flag

Returns ``(ok, reason, sanitized_args)``. On rejection the supervisor does
NOT side-effect (no auto-stop) — the SkillServer is responsible for
issuing a stop if it rejected a motion mid-skill. The one exception: if
rule 7 (pose check) trips, the supervisor calls
``fsm.transition(EMERGENCY_STOP, …)`` because that signals an actual
fall-in-progress and we must not silently keep accepting other calls.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Set, Tuple

from ..scene_state.fusion import RobotStateBus, SceneStateBus
from .estop_client import EstopClient
from .pose_check import gravity_proj_z_from_quat
from .state_machine import IllegalTransitionError, RobotFsm, RobotFsmState

log = logging.getLogger(__name__)


# Canonical tool names that brain + SkillServer + supervisor all agree on.
ALLOWED_TOOLS_NO_MOTION: Set[str] = {
    "say",
    "describe_scene",
    "query_scene_state",
    "stop",
    "release_arms",
}
ALLOWED_MOTION_TOOLS: Set[str] = {
    "walk",
    "turn",
    "gesture",
    "static_pose",
    "look_at",
    "approach",
    "mock_imitate",
}
# Tools that are intentionally rejected in sim mode (real-robot only).
REAL_ROBOT_ONLY_TOOLS: Set[str] = {
    "loco_high",
    "arm_action_high",
    "audio_tts_robot",
}
ALLOWED_TOOLS: Set[str] = (
    ALLOWED_TOOLS_NO_MOTION | ALLOWED_MOTION_TOOLS | REAL_ROBOT_ONLY_TOOLS
)


# Per-state tool permissions. "no-motion" tools are always allowed except in
# BOOT (no audio etc. while booting). Motion permissions follow §3.1 table.
_FSM_MOTION_ALLOWED: Dict[RobotFsmState, Set[str]] = {
    RobotFsmState.BOOT: set(),
    RobotFsmState.STANDING: {"release_arms"},  # plus stop (no-motion)
    RobotFsmState.ENGAGED: ALLOWED_MOTION_TOOLS,
    RobotFsmState.ACTING: ALLOWED_MOTION_TOOLS,
    RobotFsmState.EMERGENCY_STOP: set(),
    RobotFsmState.FAULT: set(),
    RobotFsmState.RECOVERING: set(),
}
_FSM_NO_MOTION_ALLOWED: Dict[RobotFsmState, Set[str]] = {
    RobotFsmState.BOOT: {"stop"},
    RobotFsmState.STANDING: ALLOWED_TOOLS_NO_MOTION,
    RobotFsmState.ENGAGED: ALLOWED_TOOLS_NO_MOTION,
    RobotFsmState.ACTING: ALLOWED_TOOLS_NO_MOTION,
    RobotFsmState.EMERGENCY_STOP: ALLOWED_TOOLS_NO_MOTION,
    RobotFsmState.FAULT: {"say", "describe_scene", "query_scene_state"},
    RobotFsmState.RECOVERING: ALLOWED_TOOLS_NO_MOTION,
}

ConfirmFn = Callable[[str, Dict[str, Any]], Awaitable[bool]]


def _clip(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


async def _confirm_in_terminal(tool: str, sanitized: Dict[str, Any]) -> bool:
    """Single-keypress y/N confirm prompt.

    Earlier versions used readline() in canonical (line-buffered) mode and
    asked the operator to type ``y`` + Enter. Two real-world failures
    forced the rewrite to single-keypress cbreak mode:

      1. Stale arrow keys queued in stdin's line buffer would be returned
         by the next readline() instead of the operator's ``y``: the line
         ``"\\x1b[C\\n"`` strips/lowers to ``"\\x1b[c"``, which is not in
         the accepted set, and the call was silently declined while the
         operator's ``y`` queued for a never-coming next prompt. We used
         to mitigate with tcflush before readline; cbreak mode avoids the
         line buffer entirely.
      2. Operators typed ``y`` but forgot Enter (the prompt does not
         visually advertise that line-mode requires it). The 10 s timeout
         then fired with the user's ``y`` still sitting unconfirmed —
         "operator declined in confirm mode" with no way to recover.

    cbreak mode delivers each keypress as soon as it arrives, so ``y``
    accepts immediately, ``n`` (and any other key) declines immediately,
    and there is no readline-versus-stale-bytes race. We still strip
    leading escape sequences (arrow keys = ESC + ``[`` + final byte) so a
    stray right-arrow before the actual ``y`` does not get treated as a
    decline. Falls back to line mode + readline if termios/tty are not
    importable (piped stdin, Windows, CI).
    """
    msg = (
        f"\n[g1_brain confirm] execute {tool}({sanitized}) ? "
        f"press y to accept, any other key to decline: "
    )
    print(msg, end="", flush=True, file=sys.stderr)

    def _read_one_keypress() -> str:
        # Try cbreak (per-keypress) mode. If we cannot enter cbreak (not a
        # TTY, no termios/tty modules), fall through to legacy line mode.
        try:
            import termios  # noqa: WPS433 — POSIX-only
            import tty       # noqa: WPS433 — POSIX-only
        except (ImportError, OSError, AttributeError, ValueError):
            return sys.stdin.readline()

        try:
            fd = sys.stdin.fileno()
            old_attr = termios.tcgetattr(fd)
        except (OSError, AttributeError, ValueError, termios.error):
            # stdin is not a real TTY (piped input, sub-process). Read a
            # line and let the caller's strip+lower logic handle it.
            return sys.stdin.readline()

        try:
            tty.setcbreak(fd)
            # Discard anything queued *before* the prompt was printed so
            # accidental keystrokes from between prompts cannot decline
            # the call.
            termios.tcflush(sys.stdin, termios.TCIFLUSH)

            ch = sys.stdin.read(1)
            # If the keypress is the start of an escape sequence (arrow
            # key etc.), drain the rest of the sequence and read one more
            # real character so we do not treat ``\x1b[C`` as decline.
            if ch == "\x1b":
                # ESC then ``[`` then final byte (e.g. ``A``/``B``/``C``/``D``).
                second = sys.stdin.read(1)
                if second == "[":
                    sys.stdin.read(1)
                ch = sys.stdin.read(1)
            # Echo the captured character + newline so the terminal
            # transcript stays readable even though we never ran in
            # canonical mode.
            print(ch, file=sys.stderr, flush=True)
            return ch
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_attr)
            except Exception:  # noqa: BLE001 — best effort restore
                pass

    loop = asyncio.get_event_loop()
    try:
        raw = await asyncio.wait_for(
            loop.run_in_executor(None, _read_one_keypress), timeout=15.0
        )
    except asyncio.TimeoutError:
        print("[g1_brain confirm] timed out, declining.", file=sys.stderr)
        return False
    raw = (raw or "").strip().lower()
    return raw in ("y", "yes")


class SafetySupervisor:
    VALID_RUN_MODES = ("observe", "confirm", "active")

    def __init__(
        self,
        cfg: Dict[str, Any],
        scene_bus: SceneStateBus,
        robot_bus: RobotStateBus,
        fsm: RobotFsm,
        estop: EstopClient,
        run_mode: str = "confirm",
        confirm_fn: Optional[ConfirmFn] = None,
        perception_enabled: bool = True,
    ) -> None:
        if run_mode not in self.VALID_RUN_MODES:
            raise ValueError(
                f"run_mode must be one of {self.VALID_RUN_MODES}, got {run_mode!r}"
            )
        self.cfg = cfg
        self.scene_bus = scene_bus
        self.robot_bus = robot_bus
        self.fsm = fsm
        self.estop = estop
        self.run_mode = run_mode
        self._confirm_fn: ConfirmFn = confirm_fn or _confirm_in_terminal
        self.mode = str(cfg.get("mode", "sim"))
        # When False (operator launched with --no-perception), the
        # PerceptionRunner never starts, no one ever calls
        # `scene_bus.update_ground`, and `scene.ground` stays None forever.
        # Rule 9's `if ground is None: return False` would then permanently
        # block every walk/approach call, which is not what the operator
        # intended — they explicitly opted out of vision-based path checks
        # because the perception stack was overloading the agent process
        # and destabilizing the 50 Hz control loop. With perception
        # disabled we still apply rules 4/5/6/7/8 (lowstate, head_frame,
        # RL policy, pose, parameter clamp) but fall through Rule 9 since
        # the visual constraints it gates on are unavailable by design.
        self.perception_enabled = bool(perception_enabled)

        safety_cfg = dict(cfg.get("safety") or {})
        self._walk_cfg = dict(safety_cfg.get("walk") or {})
        self._scene_cfg = dict(safety_cfg.get("scene") or {})
        self._pose_cfg = dict(safety_cfg.get("pose") or {})
        self._wd_cfg = dict(safety_cfg.get("watchdog") or {})
        self._say_cfg = dict(safety_cfg.get("say") or {})

        # Watchdog-set "stale" flags. Any True flag rejects in-flight motion.
        # Watchdogs flip these via set_watchdog_trip(); we OR the live age
        # checks with these flags so the supervisor catches both fast (live)
        # and persistent (latched) trips.
        self._watchdog_trips: Dict[str, str] = {}

    # ------------------------------------------------------------------ API

    def set_watchdog_trip(self, name: str, reason: Optional[str]) -> None:
        """Called by WatchdogManager when a watchdog enters/leaves a tripped state.

        Pass ``reason=None`` to clear the trip.
        """
        if reason is None:
            self._watchdog_trips.pop(name, None)
        else:
            self._watchdog_trips[name] = reason

    def is_motion_tool(self, tool: str) -> bool:
        return tool in ALLOWED_MOTION_TOOLS

    async def validate(
        self, tool: str, args: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Run all 11 rules in order.

        Returns ``(ok, reason, sanitized_args)``. Caller MUST NOT execute
        on a False; on a True it MUST use ``sanitized_args`` (not ``args``).
        """
        args = dict(args or {})

        # --- Rule 1: whitelist ------------------------------------------------
        if tool not in ALLOWED_TOOLS:
            return False, f"unknown tool: {tool!r}", {}
        if tool in REAL_ROBOT_ONLY_TOOLS and self.mode != "real":
            return False, f"sim_only: {tool!r} is real-robot only", {}

        is_motion = self.is_motion_tool(tool)

        # --- Rule 2: FSM gating ----------------------------------------------
        cur_state = self.fsm.state
        if is_motion:
            if tool not in _FSM_MOTION_ALLOWED.get(cur_state, set()):
                return (
                    False,
                    f"fsm: motion tool {tool!r} not allowed in state {cur_state.value}",
                    {},
                )
        else:
            if tool not in _FSM_NO_MOTION_ALLOWED.get(cur_state, set()):
                return (
                    False,
                    f"fsm: tool {tool!r} not allowed in state {cur_state.value}",
                    {},
                )

        # --- Rule 11 (early): E-stop flag ------------------------------------
        # Hoisted up so we never confirm-prompt or motion-check while engaged.
        if self.estop.is_engaged():
            reason = self.estop.reason() or "engaged"
            # Even non-motion tools (except 'say' / 'stop') are rejected; we
            # still want to be able to talk to the user under e-stop.
            if tool not in {"say", "stop", "describe_scene", "query_scene_state"}:
                return False, f"estop engaged: {reason}", {}

        # --- Watchdog latched trips (covers rules 4/5/6) ----------------------
        # Any latched motion-blocking trip rejects all motion calls.
        if is_motion and self._watchdog_trips:
            tripped = ", ".join(
                f"{k}={v}" for k, v in self._watchdog_trips.items()
            )
            return False, f"watchdog tripped: {tripped}", {}

        # ---------------------------------------------------------------------
        # Skill-specific argument shaping for non-motion tools (no further
        # safety checks beyond 1/2/11/run_mode below).
        # ---------------------------------------------------------------------
        if not is_motion:
            sanitized = self._sanitize_no_motion(tool, args)
            if sanitized is None:
                return False, f"bad args for {tool!r}", {}
            return True, "", sanitized

        # ---------------------------------------------------------------------
        # Motion tools — apply rules 3..10 in order.
        # ---------------------------------------------------------------------

        # --- Rule 3: run_mode -------------------------------------------------
        if self.run_mode == "observe":
            return False, "observe_only mode: motion disabled", {}

        # --- Rule 4: lowstate watchdog (live) --------------------------------
        max_lowstate = float(self._wd_cfg.get("lowstate_max_age_s", 0.5))
        lowstate_age = self.robot_bus.lowstate_age_s()
        if lowstate_age > max_lowstate:
            return (
                False,
                f"watchdog: lowstate age {lowstate_age:.2f}s > {max_lowstate:.2f}s",
                {},
            )

        # --- Rule 5: head-cam watchdog (live) --------------------------------
        # `head_frame_age_s` returns float('inf') while no head frame has ever
        # arrived (camera still spinning up, or perception explicitly disabled
        # via --no-perception). We mirror the watchdog policy in
        # WatchdogManager._tick_head_frame: warming-up state is informational
        # only, not motion-blocking. Once the camera has produced at least one
        # frame, finite-but-stale ages still reject walk/approach because that
        # signals a camera that died mid-flight. Without this carve-out,
        # operators who run --no-perception (the documented fallback when the
        # full perception stack overloads the agent process and destabilizes
        # the 50 Hz control loop) cannot issue any walk command — every call
        # is rejected by this rule even though the operator has explicitly
        # chosen to forgo vision-based path checking.
        max_head = float(self._wd_cfg.get("head_frame_max_age_s", 2.0))
        head_age = self.scene_bus.head_frame_age_s()
        head_warming_up = head_age == float("inf")
        if (
            tool in {"walk", "approach"}
            and head_age > max_head
            and not head_warming_up
        ):
            return (
                False,
                f"watchdog: head frame age {head_age:.2f}s > {max_head:.2f}s",
                {},
            )

        # --- Rule 6: RL policy active ----------------------------------------
        rs = self.robot_bus.snapshot()
        if rs is None:
            return False, "watchdog: no RobotState snapshot yet", {}
        if not rs.rl_policy_active:
            return False, "watchdog: RL policy not active", {}

        # --- Rule 7: pose check ----------------------------------------------
        # Two ways to read it: prefer the live IMU on RobotState if present.
        gravity_z = float(rs.gravity_proj_z)
        # If args carry a quaternion (debug/synthetic path), recompute.
        if "quat_wxyz" in args:
            gravity_z = gravity_proj_z_from_quat(args["quat_wxyz"])
        gravity_z_min = float(self._pose_cfg.get("gravity_z_min", -0.85))
        if gravity_z > gravity_z_min:
            # Body is tipping — engage emergency state.
            try:
                self.fsm.transition(
                    RobotFsmState.EMERGENCY_STOP,
                    f"pose check: gravity_z={gravity_z:.2f} > {gravity_z_min:.2f}",
                )
            except IllegalTransitionError:
                # Already in EMERGENCY/FAULT; ignore.
                pass
            return (
                False,
                f"pose: gravity_z={gravity_z:.2f} > {gravity_z_min:.2f} (tipping)",
                {},
            )

        # --- Rule 8: parameter clamp -----------------------------------------
        sanitized = self._sanitize_motion(tool, args)
        if sanitized is None:
            return False, f"bad args for {tool!r}", {}

        # --- Rules 9/10: scene checks ----------------------------------------
        scene = self.scene_bus.snapshot()
        ground = scene.ground if scene is not None else None

        if tool in {"walk", "approach"}:
            min_obs = float(self._scene_cfg.get("min_obstacle_m", 0.6))
            min_per = float(self._scene_cfg.get("min_person_m", 0.8))
            if ground is None:
                # Two reasons `ground` can be None: (a) perception is still
                # warming up (we want the operator to wait); (b) perception
                # was explicitly disabled with --no-perception (we have to
                # let the call through or every walk fails forever). The
                # `perception_enabled` constructor flag carries that
                # operator intent in from agent_main.
                if self.perception_enabled:
                    return False, "scene: no ground constraint yet", {}
                # Perception explicitly disabled — fall through. The
                # operator has accepted the trade-off (no vision-based
                # clear_path / obstacle / person check) in exchange for
                # being able to use the 50 Hz controller without the
                # YOLO+MediaPipe load that overloads it.
            else:
                if not ground.clear_path:
                    return False, "scene: path not clear", {}
                if ground.nearest_obstacle_m < min_obs:
                    return (
                        False,
                        f"scene: obstacle at {ground.nearest_obstacle_m:.2f}m < {min_obs:.2f}m",
                        {},
                    )
                if ground.nearest_person_m < min_per:
                    return (
                        False,
                        f"scene: person at {ground.nearest_person_m:.2f}m < {min_per:.2f}m",
                        {},
                    )

        if tool in {"gesture", "mock_imitate", "static_pose"}:
            min_per_g = float(self._scene_cfg.get("min_person_for_gesture_m", 0.5))
            if ground is not None and ground.nearest_person_m < min_per_g:
                return (
                    False,
                    f"scene: person at {ground.nearest_person_m:.2f}m < "
                    f"{min_per_g:.2f}m (gesture)",
                    {},
                )

        # --- Rule 3 (continued): confirm prompt ------------------------------
        if self.run_mode == "confirm":
            ok = await self._confirm_fn(tool, sanitized)
            if not ok:
                return False, "operator declined in confirm mode", {}

        return True, "", sanitized

    # ----------------------------------------------------------- private

    def _sanitize_no_motion(
        self, tool: str, args: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if tool == "say":
            text = str(args.get("text", "")).strip()
            if not text:
                return None
            max_chars = int(self._say_cfg.get("max_chars", 200))
            if len(text) > max_chars:
                text = text[:max_chars]
            return {"text": text}
        if tool == "describe_scene":
            # OpenAI's Responses API only accepts these four values for
            # input_image.detail — passing anything else 400's the request.
            return {
                "question": str(args.get("question", "")).strip(),
                "detail": (
                    args.get("detail")
                    if args.get("detail") in ("low", "high", "auto", "original")
                    else "auto"
                ),
            }
        if tool == "query_scene_state":
            return {}
        if tool in {"stop", "release_arms"}:
            return {}
        return None

    def _sanitize_motion(
        self, tool: str, args: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if tool == "walk":
            try:
                vx = float(args.get("vx", 0.0))
                vy = float(args.get("vy", 0.0))
                wz = float(args.get("wz", 0.0))
                duration = float(args.get("duration_s", 0.5))
            except (TypeError, ValueError):
                return None
            vx_max = float(self._walk_cfg.get("vx_max", 0.2))
            vy_max = float(self._walk_cfg.get("vy_max", 0.1))
            wz_max = float(self._walk_cfg.get("wz_max", 0.3))
            d_min = float(self._walk_cfg.get("duration_min_s", 0.2))
            d_max = float(self._walk_cfg.get("duration_max_s", 1.0))
            return {
                "vx": _clip(vx, -vx_max, vx_max),
                "vy": _clip(vy, -vy_max, vy_max),
                "wz": _clip(wz, -wz_max, wz_max),
                "duration_s": _clip(duration, d_min, d_max),
            }
        if tool == "turn":
            try:
                yaw_deg = float(args.get("yaw_deg", 0.0))
            except (TypeError, ValueError):
                return None
            # Clamp roughly to ±60 deg per call (caller may chain).
            return {"yaw_deg": _clip(yaw_deg, -60.0, 60.0)}
        if tool == "gesture":
            name = str(args.get("name", ""))
            if not name:
                return None
            return {"name": name}
        if tool == "static_pose":
            name = str(args.get("name", ""))
            if not name:
                return None
            return {"name": name}
        if tool == "look_at":
            target = str(args.get("target", ""))
            if not target:
                return None
            return {"target": target}
        if tool == "approach":
            target_name = str(args.get("target_name", ""))
            try:
                target_distance_m = float(args.get("target_distance_m", 1.0))
            except (TypeError, ValueError):
                return None
            if not target_name:
                return None
            return {
                "target_name": target_name,
                "target_distance_m": _clip(target_distance_m, 0.3, 3.0),
            }
        if tool == "mock_imitate":
            from ..scene_state.types import GestureLabel
            gesture = str(args.get("gesture", ""))
            if gesture not in GestureLabel.MIRRORABLE:
                return None
            return {"gesture": gesture}
        return None


__all__ = [
    "SafetySupervisor",
    "ALLOWED_TOOLS",
    "ALLOWED_MOTION_TOOLS",
    "ALLOWED_TOOLS_NO_MOTION",
    "REAL_ROBOT_ONLY_TOOLS",
]
