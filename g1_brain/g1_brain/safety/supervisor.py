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
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Set, Tuple

from ..scene_state.fusion import RobotStateBus, SceneStateBus
from .estop_client import EstopClient
from .pose_check import gravity_proj_z_from_quat
from .state_machine import IllegalTransitionError, RobotFsm, RobotFsmState

if False:  # TYPE_CHECKING — string annotation avoids the import cost at runtime
    from .vision_risk_gate import VisionRiskGate  # noqa: F401

log = logging.getLogger(__name__)


# Canonical tool names that brain + SkillServer + supervisor all agree on.
ALLOWED_TOOLS_NO_MOTION: Set[str] = {
    "say",
    "ask_human",
    "describe_scene",
    "query_scene_state",
    "recall_history",
    "recall_grep",
    "recall_read",
    "recall_glob",
    "ask_slow_brain",
    "stop",
    "release_arms",
    "start_phone_call",
    "end_call",
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
    RobotFsmState.FAULT: {"say", "describe_scene", "query_scene_state", "recall_history"},
    RobotFsmState.RECOVERING: ALLOWED_TOOLS_NO_MOTION,
}

ConfirmFn = Callable[..., Awaitable[bool]]   # (tool, sanitized, risk_reason=None) -> bool


def _clip(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


# Operator decision budget for the y/N confirm prompt. MUST stay below
# ``audio_control.plan_watchdog_s`` (default 30 s): if the confirm outlives
# the plan watchdog, the plan drains to IDLE while the prompt's stdin reader
# is still blocked — and the next turn's Enter-to-commit watcher then collides
# with that orphaned reader (the "I pressed Enter but it's stuck" bug). The
# vision-risk latency is already spent BEFORE this prompt is printed, so this
# budget only needs to cover the human decision, not the GPT round-trip.
CONFIRM_TIMEOUT_S = 20.0


def _read_one_keypress(should_stop: "threading.Event") -> str:
    """Read a single keypress (cbreak) or one line (fallback). Cancellable.

    Runs in a worker thread. The blocking read is broken into short
    ``select`` waits so the caller can cancel it via ``should_stop`` — a
    plain blocking ``sys.stdin.read(1)`` here used to ORPHAN the thread on
    timeout, which (1) left the TTY in cbreak mode and stole the operator's
    next Enter (the "pressed Enter but it's stuck" report), and (2) as a
    non-daemon thread blocked on read, wedged process exit so Ctrl-C did
    nothing. Polling ``should_stop`` guarantees we always reach the
    ``finally`` that restores the original TTY state and that the thread
    terminates promptly once the confirm coroutine is done.

    Falls back to line mode + readline if termios/tty are not importable or
    stdin is not a real TTY (piped stdin, Windows, CI).
    """
    try:
        import termios  # noqa: WPS433 — POSIX-only
        import tty       # noqa: WPS433 — POSIX-only
    except (ImportError, OSError, AttributeError, ValueError):
        return sys.stdin.readline()

    try:
        fd = sys.stdin.fileno()
        old_attr = termios.tcgetattr(fd)
    except (OSError, AttributeError, ValueError, termios.error):
        # stdin is not a real TTY (piped input, sub-process). Read a line
        # and let the caller's strip+lower logic handle it.
        return sys.stdin.readline()

    import select  # noqa: WPS433 — POSIX-only

    try:
        tty.setcbreak(fd)
        # Discard anything queued *before* the prompt was printed so
        # accidental keystrokes from between prompts cannot decline the call.
        termios.tcflush(sys.stdin, termios.TCIFLUSH)

        while not should_stop.is_set():
            try:
                ready, _, _ = select.select([fd], [], [], 0.15)
            except (OSError, ValueError):
                # fd went away under us (terminal detached / shutdown).
                return ""
            if not ready:
                continue
            ch = sys.stdin.read(1)
            if ch == "":
                return ""  # EOF on stdin
            # If the keypress is the start of an escape sequence (arrow key
            # etc.), drain the rest of the sequence and read one more real
            # character so we do not treat ``\x1b[C`` as decline.
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
        return ""  # cancelled before any keypress (timeout / turn ended)
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attr)
        except Exception:  # noqa: BLE001 — best effort restore
            pass


async def _confirm_in_terminal(
    tool: str,
    sanitized: Dict[str, Any],
    risk_reason: Optional[str] = None,
    *,
    timeout_s: float = CONFIRM_TIMEOUT_S,
) -> bool:
    """Single-keypress y/N confirm prompt.

    cbreak mode delivers each keypress as soon as it arrives, so ``y``
    accepts immediately, ``n`` (and any other key) declines immediately, and
    there is no readline-versus-stale-bytes race. Leading escape sequences
    (arrow keys = ESC + ``[`` + final byte) are stripped so a stray
    right-arrow before the actual ``y`` is not treated as a decline. Falls
    back to line mode + readline if termios/tty are not importable.

    The keypress read runs in a worker thread but is *cancellable*: on
    timeout (or when this coroutine is cancelled because the turn was torn
    down) we set ``should_stop`` and briefly await the reader so it restores
    the TTY and releases stdin BEFORE we return. That closes the window in
    which an orphaned reader would (a) steal the operator's next
    Enter-to-commit keystroke and (b) keep a non-daemon thread blocked on
    stdin so the process could not exit. See ``CONFIRM_TIMEOUT_S``.
    """
    header = f"\n[g1_brain confirm] execute {tool}({sanitized}) ?\n"
    if risk_reason:
        header += f"[RISK] {risk_reason}\n"
    msg = header + "press y to accept, any other key to decline: "
    print(msg, end="", flush=True, file=sys.stderr)

    should_stop = threading.Event()
    loop = asyncio.get_event_loop()
    fut = loop.run_in_executor(None, _read_one_keypress, should_stop)
    raw = ""
    try:
        # shield: a wait_for timeout cancels the *wrapper*, not the executor
        # future, so the reader thread keeps running until we set should_stop
        # in the finally below — at which point it exits cleanly.
        raw = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout_s)
    except asyncio.TimeoutError:
        print("[g1_brain confirm] timed out, declining.", file=sys.stderr, flush=True)
        raw = ""
    finally:
        # Always tell the reader to stop and give it a moment to restore the
        # TTY + free stdin before returning. Guarantees the thread can never
        # outlive this call and eat the operator's next keystroke.
        should_stop.set()
        if not fut.done():
            try:
                await asyncio.wait_for(asyncio.shield(fut), timeout=1.0)
            except Exception:  # noqa: BLE001 — Timeout/Cancelled/etc; thread is daemonless but bounded
                pass
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
        vision_gate: Optional["VisionRiskGate"] = None,
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
        # Optional Rule 12: GPT-5.5 vision risk gate. When set, motion-tool
        # validations call vision_gate.evaluate(...) AFTER rules 1-10 and
        # BEFORE the legacy confirm prompt; SAFE short-circuits to True,
        # RISK falls through to the existing _confirm_in_terminal y/N with
        # the reason printed inline. None disables the gate (preserves
        # pre-design behaviour bit-for-bit).
        self.vision_gate = vision_gate

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

        # --- Rule 12: vision risk gate ---------------------------------------
        risk_reason: Optional[str] = None
        if self.vision_gate is not None:
            verdict = await self.vision_gate.evaluate(tool, sanitized)
            log.info(
                "[vision_gate] tool=%s verdict=%s source=%s reason=%s",
                tool,
                "SAFE" if verdict.safe else "RISK",
                verdict.source,
                verdict.reason,
            )
            if verdict.safe:
                return True, "", sanitized
            risk_reason = verdict.reason

        # --- Rule 3 (continued): confirm prompt ------------------------------
        if self.run_mode == "confirm" or risk_reason is not None:
            ok = await self._confirm_fn(tool, sanitized, risk_reason=risk_reason)
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
        if tool == "ask_human":
            # ask_human shares the say tool's character budget — both end up
            # synthesising a single short utterance through OpenAI TTS. The
            # tool was missing from the whitelist; the brain prompt
            # advertised it and the LLM would call it for clarifications
            # ("how far do you want to walk?"), only for the supervisor to
            # reject it as 'unknown tool' and the user's original intent
            # ("walk forward") to disappear into a fallback say().
            question = str(args.get("question", "")).strip()
            if not question:
                return None
            max_chars = int(self._say_cfg.get("max_chars", 200))
            if len(question) > max_chars:
                question = question[:max_chars]
            return {"question": question}
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
        if tool == "recall_history":
            kind = args.get("kind")
            if kind not in {"actions", "user_turns", "all", None}:
                return None
            sanitized: Dict[str, Any] = {}
            if kind is not None:
                sanitized["kind"] = kind
            try:
                if "limit" in args:
                    sanitized["limit"] = int(args["limit"])
            except (TypeError, ValueError):
                pass
            return sanitized
        if tool in {"stop", "release_arms"}:
            return {}
        if tool == "recall_grep":
            pattern = str(args.get("pattern", "")).strip()
            if not pattern:
                return None
            scope = args.get("scope", "registry")
            if scope not in ("registry", "rollouts", "jsonl", "all"):
                scope = "registry"
            sanitized: Dict[str, Any] = {"pattern": pattern, "scope": scope}
            sid = args.get("session_id")
            if isinstance(sid, str) and sid:
                sanitized["session_id"] = sid
            try:
                if "max_lines" in args:
                    sanitized["max_lines"] = max(1, min(100, int(args["max_lines"])))
            except (TypeError, ValueError):
                pass
            return sanitized
        if tool == "recall_read":
            path = str(args.get("path", "")).strip()
            if not path:
                return None
            sanitized = {"path": path}
            try:
                if "start_line" in args:
                    sanitized["start_line"] = max(1, int(args["start_line"]))
            except (TypeError, ValueError):
                pass
            try:
                if args.get("end_line") is not None:
                    sanitized["end_line"] = max(1, int(args["end_line"]))
            except (TypeError, ValueError):
                pass
            return sanitized
        if tool == "recall_glob":
            pattern = str(args.get("pattern", "")).strip()
            if not pattern:
                return None
            sanitized = {"pattern": pattern}
            try:
                if "limit" in args:
                    sanitized["limit"] = max(1, min(200, int(args["limit"])))
            except (TypeError, ValueError):
                pass
            return sanitized
        if tool == "ask_slow_brain":
            query = str(args.get("query", "")).strip()
            if not query:
                return None
            sanitized = {"query": query}
            try:
                if "timeout_s" in args:
                    t = float(args["timeout_s"])
                    sanitized["timeout_s"] = _clip(t, 3.0, 90.0)
            except (TypeError, ValueError):
                pass
            return sanitized
        if tool == "start_phone_call":
            sanitized: Dict[str, Any] = {}
            to = args.get("to")
            if isinstance(to, str) and to.strip():
                sanitized["to"] = to.strip()
            return sanitized
        if tool == "end_call":
            # end_call takes no parameters.
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
            # Allow ±180° in one call. Pre-fix this was clamped at ±60°,
            # which forced the LLM to chain 7+ small turns for a "turn 180"
            # request — each call costs the operator one confirm-mode y/N
            # so the operator gave up after 6 prompts. _skill_turn already
            # routes through _skill_walk's reactive-abort loop, so a long
            # turn is no less safe than many short ones.
            return {"yaw_deg": _clip(yaw_deg, -180.0, 180.0)}
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
