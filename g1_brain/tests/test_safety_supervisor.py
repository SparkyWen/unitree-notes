"""Coverage of all 11 SafetySupervisor rules from `docs/g1_plan.md` §3.2.

We stub the busses (no DDS) and use an in-memory EstopClient. Each test
sets up the minimum viable "happy" state and then perturbs one variable
to exercise one rule.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock

import pytest

from g1_brain.safety.estop_client import EstopClient
from g1_brain.safety.state_machine import RobotFsm, RobotFsmState
from g1_brain.safety.supervisor import (
    ALLOWED_TOOLS_NO_MOTION,
    SafetySupervisor,
)
from g1_brain.scene_state.fusion import RobotStateBus, SceneStateBus
from g1_brain.scene_state.types import GroundConstraint, RobotState


# --------------------------------------------------------------------- helpers

def _good_robot_state(
    *,
    standing: bool = True,
    gravity_proj_z: float = -0.99,
    rl_policy_active: bool = True,
    last_lowstate_age_s: float = 0.05,
) -> RobotState:
    return RobotState(
        standing=standing,
        gravity_proj_z=gravity_proj_z,
        base_ang_vel_xyz=(0.0, 0.0, 0.0),
        rl_policy_active=rl_policy_active,
        last_lowstate_age_s=last_lowstate_age_s,
    )


def _good_ground(
    *,
    clear: bool = True,
    obstacle_m: float = 5.0,
    person_m: float = 5.0,
    floor_visible: float = 0.9,
    tilt_deg: float = 0.0,
) -> GroundConstraint:
    return GroundConstraint(
        clear_path=clear,
        nearest_obstacle_m=obstacle_m,
        nearest_person_m=person_m,
        floor_visible_ratio=floor_visible,
        surface_tilt_deg=tilt_deg,
    )


class _StubSceneBus(SceneStateBus):
    """Lets tests pin head/usb frame ages and ground constraint directly."""

    def __init__(self) -> None:
        super().__init__()
        self._head_age = 0.1
        self._usb_age = 0.1

    def head_frame_age_s(self, now: Optional[float] = None) -> float:  # type: ignore[override]
        return self._head_age

    def usb_frame_age_s(self, now: Optional[float] = None) -> float:  # type: ignore[override]
        return self._usb_age


class _StubRobotBus(RobotStateBus):
    """Lets tests pin lowstate age directly."""

    def __init__(self) -> None:
        super().__init__()
        self._age = 0.05

    def lowstate_age_s(self, now: Optional[float] = None) -> float:  # type: ignore[override]
        return self._age


def _cfg() -> Dict[str, Any]:
    """Reasonable defaults; matches `configs/g1_brain.yaml` thresholds."""
    return {
        "mode": "sim",
        "safety": {
            "walk": {
                "vx_max": 0.2,
                "vy_max": 0.1,
                "wz_max": 0.3,
                "duration_max_s": 1.0,
                "duration_min_s": 0.2,
            },
            "scene": {
                "min_obstacle_m": 0.6,
                "min_person_m": 0.8,
                "min_person_for_gesture_m": 0.5,
            },
            "pose": {"gravity_z_min": -0.85},
            "watchdog": {
                "lowstate_max_age_s": 0.5,
                "head_frame_max_age_s": 2.0,
                "usb_frame_max_age_s": 3.0,
            },
            "say": {"max_chars": 200},
            "estop": {"flag_path": "/tmp/__never_used_in_tests__"},
        },
    }


@pytest.fixture
def env(tmp_path):
    """Bundle of (cfg, scene_bus, robot_bus, fsm, estop, supervisor)
    pre-configured for a successful happy-path validate()."""
    cfg = _cfg()
    scene_bus = _StubSceneBus()
    robot_bus = _StubRobotBus()
    fsm = RobotFsm()
    fsm.transition(RobotFsmState.STANDING, "boot done")
    fsm.transition(RobotFsmState.ENGAGED, "wake")
    estop = EstopClient(tmp_path / "estop_flag")
    sup = SafetySupervisor(
        cfg,
        scene_bus=scene_bus,
        robot_bus=robot_bus,
        fsm=fsm,
        estop=estop,
        run_mode="active",  # default to active so motion isn't blocked
    )
    # Seed busses with healthy data.
    robot_bus.update(_good_robot_state())
    scene_bus.update_ground(_good_ground())
    return {
        "cfg": cfg,
        "scene_bus": scene_bus,
        "robot_bus": robot_bus,
        "fsm": fsm,
        "estop": estop,
        "sup": sup,
    }


# --------------------------------------------------------------------- tests


# Rule 1: whitelist
async def test_unknown_tool_rejected(env):
    sup = env["sup"]
    ok, reason, sanitized = await sup.validate("dance", {})
    assert ok is False
    assert "unknown tool" in reason
    assert sanitized == {}


async def test_real_robot_only_tool_rejected_in_sim(env):
    sup = env["sup"]
    for tool in ("loco_high", "arm_action_high", "audio_tts_robot"):
        ok, reason, _ = await sup.validate(tool, {})
        assert ok is False, tool
        assert "sim_only" in reason


async def test_ask_human_whitelisted_and_sanitized(env):
    """Regression: ask_human is exposed in the LLM tool schema and the
    brain prompt advertises it, but the whitelist used to omit it — every
    call was rejected as 'unknown tool', and the model would fall back to
    a plain say() that lost the user's original intent (operator-reported:
    'walk forward' produced 'how far would you like to walk?' instead of a
    walk command). Keep this test as the canary that the schema, the
    skill server's _skill_ask_human, and the supervisor whitelist stay
    aligned.
    """
    sup = env["sup"]
    ok, reason, sanitized = await sup.validate(
        "ask_human", {"question": "你想往前走多远？"}
    )
    assert ok is True, reason
    assert sanitized["question"] == "你想往前走多远？"
    # Truncates to safety.say.max_chars (default 200) without rejecting.
    long_q = "a" * 500
    ok, reason, sanitized = await sup.validate(
        "ask_human", {"question": long_q}
    )
    assert ok is True, reason
    assert len(sanitized["question"]) == 200
    # Empty / whitespace-only is rejected with a useful reason.
    ok, reason, _ = await sup.validate("ask_human", {"question": "   "})
    assert ok is False
    assert "bad args" in reason


# Rule 2: FSM gating
async def test_motion_rejected_from_boot(env):
    sup = env["sup"]
    sup.fsm._state = RobotFsmState.BOOT  # direct override (test-only)
    ok, reason, _ = await sup.validate(
        "walk", {"vx": 0.1, "vy": 0.0, "wz": 0.0, "duration_s": 0.5}
    )
    assert ok is False
    assert "fsm" in reason


async def test_motion_rejected_from_emergency(env):
    sup = env["sup"]
    # First try fully legal happy path.
    ok, _, _ = await sup.validate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert ok is True
    # Now go EMERGENCY.
    sup.fsm.transition(RobotFsmState.EMERGENCY_STOP, "test")
    ok, reason, _ = await sup.validate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert ok is False
    assert "fsm" in reason


async def test_motion_rejected_from_fault(env):
    sup = env["sup"]
    sup.fsm._state = RobotFsmState.FAULT
    ok, reason, _ = await sup.validate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert ok is False
    assert "fsm" in reason


async def test_say_allowed_from_emergency(env):
    sup = env["sup"]
    sup.fsm.transition(RobotFsmState.EMERGENCY_STOP, "test")
    ok, _, sanitized = await sup.validate("say", {"text": "estop engaged"})
    assert ok is True
    assert sanitized["text"] == "estop engaged"


# Rule 3: run_mode
async def test_observe_rejects_motion(env):
    env["sup"].run_mode = "observe"
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "observe" in reason


async def test_active_passes_motion(env):
    env["sup"].run_mode = "active"
    ok, reason, sanitized = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True, reason
    assert sanitized["vx"] == pytest.approx(0.1)


async def test_confirm_calls_confirm_fn_yes(env):
    fn = AsyncMock(return_value=True)
    env["sup"]._confirm_fn = fn
    env["sup"].run_mode = "confirm"
    ok, _, _ = await env["sup"].validate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert ok is True
    fn.assert_awaited_once()


async def test_confirm_calls_confirm_fn_no(env):
    fn = AsyncMock(return_value=False)
    env["sup"]._confirm_fn = fn
    env["sup"].run_mode = "confirm"
    ok, reason, _ = await env["sup"].validate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert ok is False
    assert "declined" in reason
    fn.assert_awaited_once()


# Rule 4: lowstate watchdog
async def test_lowstate_watchdog_rejects_motion(env):
    env["robot_bus"]._age = 1.0
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "lowstate" in reason


# Rule 5: head frame watchdog
async def test_head_frame_watchdog_rejects_walk(env):
    env["scene_bus"]._head_age = 3.0
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "head frame" in reason


async def test_head_frame_watchdog_does_not_block_gesture(env):
    env["scene_bus"]._head_age = 3.0
    ok, _, _ = await env["sup"].validate("gesture", {"name": "wave_right"})
    assert ok is True


async def test_head_frame_inf_age_does_not_block_walk(env):
    """Regression: with --no-perception (or while head camera is still
    warming up), `head_frame_age_s()` returns float('inf'). The supervisor
    must mirror the watchdog policy — warming-up is not motion-blocking,
    only finite-but-stale ages reject walk. Otherwise --no-perception is
    unusable: every walk fails with `head frame age infs > 2.00s` even
    though the operator explicitly opted out of vision.
    """
    env["scene_bus"]._head_age = float("inf")
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True, f"walk rejected with reason: {reason!r}"


async def test_perception_disabled_skips_ground_constraint(tmp_path):
    """With perception_enabled=False (operator passed --no-perception),
    Rule 9's `if ground is None` must NOT block walk/approach. Without
    this carve-out, --no-perception is a dead-end mode: every walk gets
    "scene: no ground constraint yet" and the only motion calls left are
    gestures. Regression for the 2026-05-06 incident where the operator
    fell back to --no-perception to escape the perception-induced control
    instability and then could not move at all.
    """
    cfg = _cfg()
    scene_bus = _StubSceneBus()
    robot_bus = _StubRobotBus()
    fsm = RobotFsm()
    fsm.transition(RobotFsmState.STANDING, "boot done")
    fsm.transition(RobotFsmState.ENGAGED, "wake")
    estop = EstopClient(tmp_path / "estop_flag")
    sup = SafetySupervisor(
        cfg,
        scene_bus=scene_bus,
        robot_bus=robot_bus,
        fsm=fsm,
        estop=estop,
        run_mode="active",
        perception_enabled=False,
    )
    robot_bus.update(_good_robot_state())
    # Deliberately do NOT call scene_bus.update_ground(...) — that mirrors
    # the production state when no PerceptionRunner is running.

    ok, reason, _ = await sup.validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True, f"walk rejected with reason: {reason!r}"


async def test_perception_disabled_still_honors_other_rules(tmp_path):
    """Belt + suspenders: even with perception_enabled=False, the other
    rules (lowstate watchdog, RL policy active, pose check, parameter
    clamp) must still fire. perception_enabled is a Rule 9 carve-out
    only, not a blanket bypass."""
    cfg = _cfg()
    scene_bus = _StubSceneBus()
    robot_bus = _StubRobotBus()
    fsm = RobotFsm()
    fsm.transition(RobotFsmState.STANDING, "boot done")
    fsm.transition(RobotFsmState.ENGAGED, "wake")
    estop = EstopClient(tmp_path / "estop_flag")
    sup = SafetySupervisor(
        cfg,
        scene_bus=scene_bus,
        robot_bus=robot_bus,
        fsm=fsm,
        estop=estop,
        run_mode="active",
        perception_enabled=False,
    )
    # Stale lowstate must still reject motion even with perception off.
    robot_bus._age = 1.0
    ok, reason, _ = await sup.validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False, "perception_enabled=False must not bypass lowstate"
    assert "lowstate" in reason


# Rule 6: RL policy active
async def test_rl_policy_inactive_rejects_motion(env):
    env["robot_bus"].update(_good_robot_state(rl_policy_active=False))
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "RL policy" in reason


async def test_no_robot_state_rejects_motion(env):
    env["robot_bus"]._state = None  # simulate early-startup case
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "RobotState" in reason or "snapshot" in reason


# Rule 7: pose check
async def test_pose_check_rejects_and_emergency(env):
    env["robot_bus"].update(_good_robot_state(gravity_proj_z=-0.5))
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "pose" in reason
    assert env["fsm"].state == RobotFsmState.EMERGENCY_STOP


# Rule 8: parameter clamp
async def test_param_clamp_walk(env):
    ok, _, sanitized = await env["sup"].validate(
        "walk",
        {"vx": 10.0, "vy": -5.0, "wz": 99.0, "duration_s": 99.0},
    )
    assert ok is True
    assert sanitized["vx"] == pytest.approx(0.2)
    assert sanitized["vy"] == pytest.approx(-0.1)
    assert sanitized["wz"] == pytest.approx(0.3)
    assert sanitized["duration_s"] == pytest.approx(1.0)


async def test_param_clamp_walk_lower_bound(env):
    ok, _, sanitized = await env["sup"].validate(
        "walk",
        {"vx": -10.0, "duration_s": 0.0},
    )
    assert ok is True
    assert sanitized["vx"] == pytest.approx(-0.2)
    assert sanitized["duration_s"] == pytest.approx(0.2)


# Rule 9: scene check (walk)
async def test_walk_rejected_when_path_blocked(env):
    env["scene_bus"].update_ground(_good_ground(clear=False))
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "clear" in reason or "path" in reason


async def test_walk_rejected_when_obstacle_close(env):
    env["scene_bus"].update_ground(_good_ground(obstacle_m=0.4))
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "obstacle" in reason


async def test_walk_rejected_when_person_close(env):
    env["scene_bus"].update_ground(_good_ground(person_m=0.4))
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "person" in reason


# Rule 10: scene check (gesture)
async def test_gesture_rejected_when_person_too_close(env):
    env["scene_bus"].update_ground(_good_ground(person_m=0.3))
    ok, reason, _ = await env["sup"].validate(
        "gesture", {"name": "wave_right"}
    )
    assert ok is False
    assert "person" in reason and "gesture" in reason


async def test_gesture_passes_when_person_far_enough(env):
    env["scene_bus"].update_ground(_good_ground(person_m=1.0))
    ok, _, sanitized = await env["sup"].validate(
        "gesture", {"name": "wave_right"}
    )
    assert ok is True
    assert sanitized["name"] == "wave_right"


# Rule 11: estop flag
async def test_estop_blocks_motion(env):
    env["estop"].engage("manual")
    try:
        for tool, args in [
            ("walk", {"vx": 0.1, "duration_s": 0.5}),
            ("gesture", {"name": "wave_right"}),
            ("release_arms", {}),
        ]:
            ok, reason, _ = await env["sup"].validate(tool, args)
            assert ok is False, tool
            assert "estop" in reason.lower(), reason
    finally:
        env["estop"].release()


async def test_estop_allows_say_and_describe(env):
    env["estop"].engage("manual")
    try:
        ok, _, _ = await env["sup"].validate("say", {"text": "we are stopped"})
        assert ok is True
        ok, _, _ = await env["sup"].validate(
            "describe_scene", {"question": "what?"}
        )
        assert ok is True
    finally:
        env["estop"].release()


# --------------------------- bonus / coverage ------------------------

async def test_say_empty_rejected(env):
    ok, reason, _ = await env["sup"].validate("say", {"text": "  "})
    assert ok is False
    assert "bad args" in reason or "empty" in reason


async def test_say_truncated(env):
    big = "x" * 500
    ok, _, sanitized = await env["sup"].validate("say", {"text": big})
    assert ok is True
    assert len(sanitized["text"]) == 200


async def test_unknown_gesture_rejected(env):
    ok, reason, _ = await env["sup"].validate("gesture", {"name": ""})
    assert ok is False


async def test_mock_imitate_only_mirrorable(env):
    # MIRRORABLE = wave_right/wave_left/hands_up/t_pose
    ok, _, sanitized = await env["sup"].validate(
        "mock_imitate", {"gesture": "wave_right"}
    )
    assert ok is True
    assert sanitized["gesture"] == "wave_right"

    ok, _, _ = await env["sup"].validate(
        "mock_imitate", {"gesture": "stop_palm"}  # not in MIRRORABLE
    )
    assert ok is False


async def test_describe_scene_default_detail(env):
    ok, _, sanitized = await env["sup"].validate(
        "describe_scene", {"question": "what's there?", "detail": "ultra"}
    )
    assert ok is True
    # Modern OpenAI Responses API only accepts low/high/auto/original; we
    # fall back to "auto" when the caller passes anything else (or omits it).
    assert sanitized["detail"] == "auto"


async def test_watchdog_trip_flag_blocks_motion(env):
    sup = env["sup"]
    sup.set_watchdog_trip("lowstate", "age=1.5s")
    ok, reason, _ = await sup.validate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert ok is False
    assert "watchdog" in reason
    sup.set_watchdog_trip("lowstate", None)
    ok, _, _ = await sup.validate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert ok is True


def test_invalid_run_mode_raises(tmp_path):
    cfg = _cfg()
    with pytest.raises(ValueError):
        SafetySupervisor(
            cfg,
            scene_bus=_StubSceneBus(),
            robot_bus=_StubRobotBus(),
            fsm=RobotFsm(),
            estop=EstopClient(tmp_path / "x"),
            run_mode="silly",
        )


# ----- _confirm_in_terminal: single-keypress cbreak prompt ------------------
# Regression for two real-world failures (see `_confirm_in_terminal` docstring
# in supervisor.py): (a) stale arrow-key bytes in the line buffer caused
# readline to return non-`y` strings; (b) operators pressed `y` without
# Enter and the 10 s timeout decline-fired with their `y` still queued.
# cbreak mode reads each keypress immediately and avoids both.

class _FakeTermios:
    TCIFLUSH = 0
    TCSADRAIN = 0
    error = type("error", (Exception,), {})

    def __init__(self):
        self.tcflush_calls = 0
        self.tcgetattr_calls = 0
        self.tcsetattr_calls = 0

    def tcflush(self, _fd, _what):
        self.tcflush_calls += 1

    def tcgetattr(self, _fd):
        self.tcgetattr_calls += 1
        return ["dummy_attrs"]

    def tcsetattr(self, _fd, _when, _attr):
        self.tcsetattr_calls += 1


class _FakeTty:
    def __init__(self):
        self.cbreak_calls = 0

    def setcbreak(self, _fd):
        self.cbreak_calls += 1


class _FakeStdin:
    """Simulates one keypress at a time; supports escape sequences."""

    def __init__(self, sequence):
        self._buf = list(sequence)

    def fileno(self):
        return 0

    def read(self, n):
        out = []
        for _ in range(n):
            if not self._buf:
                return ""
            out.append(self._buf.pop(0))
        return "".join(out)

    def readline(self):
        # Fallback path (no termios). Drain to newline.
        out = []
        while self._buf:
            ch = self._buf.pop(0)
            out.append(ch)
            if ch == "\n":
                break
        return "".join(out)


@pytest.mark.asyncio
async def test_confirm_in_terminal_accepts_single_y_keypress(monkeypatch):
    """`y` alone (no Enter) must accept — that is the entire point of the
    cbreak rewrite. Earlier readline-based code timed out on this path."""
    from g1_brain.safety import supervisor as sup_mod

    fake_term = _FakeTermios()
    fake_tty = _FakeTty()
    monkeypatch.setitem(__import__("sys").modules, "termios", fake_term)
    monkeypatch.setitem(__import__("sys").modules, "tty", fake_tty)
    monkeypatch.setattr(sup_mod.sys, "stdin", _FakeStdin("y"))

    ok = await sup_mod._confirm_in_terminal("walk", {"vx": 0.1})
    assert ok is True
    # We must have entered cbreak (else we are back in line mode).
    assert fake_tty.cbreak_calls == 1
    # And we must have flushed pre-prompt bytes before reading.
    assert fake_term.tcflush_calls == 1
    # And we must have restored the original tty state on exit.
    assert fake_term.tcsetattr_calls == 1


@pytest.mark.asyncio
async def test_confirm_in_terminal_decline_on_non_yes(monkeypatch):
    """Any non-`y` keypress declines — including arrow keys (escape
    sequence) followed by a stray character."""
    from g1_brain.safety import supervisor as sup_mod

    fake_term = _FakeTermios()
    fake_tty = _FakeTty()
    monkeypatch.setitem(__import__("sys").modules, "termios", fake_term)
    monkeypatch.setitem(__import__("sys").modules, "tty", fake_tty)

    # `n` declines.
    monkeypatch.setattr(sup_mod.sys, "stdin", _FakeStdin("n"))
    assert await sup_mod._confirm_in_terminal("walk", {}) is False

    # Right-arrow (\x1b[C) followed by `n` — the operator hit an arrow
    # key first, then the actual decline. Escape sequence is drained
    # transparently, so the `n` is what we evaluate.
    monkeypatch.setattr(sup_mod.sys, "stdin", _FakeStdin("\x1b[Cn"))
    assert await sup_mod._confirm_in_terminal("walk", {}) is False


@pytest.mark.asyncio
async def test_confirm_in_terminal_falls_back_when_not_tty(monkeypatch):
    """When termios.tcgetattr raises (piped stdin / sub-process), fall
    back to readline so CI and pytest still work."""
    from g1_brain.safety import supervisor as sup_mod

    class _FailingTermios(_FakeTermios):
        def tcgetattr(self, _fd):
            raise _FailingTermios.error("Inappropriate ioctl for device")

    fake_term = _FailingTermios()
    monkeypatch.setitem(__import__("sys").modules, "termios", fake_term)
    monkeypatch.setitem(__import__("sys").modules, "tty", _FakeTty())
    monkeypatch.setattr(sup_mod.sys, "stdin", _FakeStdin("y\n"))

    assert await sup_mod._confirm_in_terminal("walk", {}) is True


@pytest.mark.asyncio
async def test_confirm_in_terminal_survives_no_termios(monkeypatch):
    """Without termios (Windows / piped stdin) we still readline so the
    function never crashes."""
    from g1_brain.safety import supervisor as sup_mod
    import sys as _sys

    monkeypatch.setitem(_sys.modules, "termios", None)
    monkeypatch.setattr(sup_mod.sys, "stdin", _FakeStdin("y\n"))
    assert await sup_mod._confirm_in_terminal("walk", {}) is True


# Rule 12: vision risk gate ----------------------------------------------

class _StubGate:
    """Stand-in for VisionRiskGate.evaluate."""

    def __init__(self, verdict_safe: bool, reason: str = "stub") -> None:
        from g1_brain.safety.vision_risk_gate import RiskVerdict
        self._verdict = RiskVerdict(verdict_safe, reason, "vision_llm")
        self.calls = 0

    async def evaluate(self, tool, sanitized):
        self.calls += 1
        return self._verdict


async def test_active_with_safe_gate_skips_confirm(env):
    gate = _StubGate(verdict_safe=True, reason="clear floor")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "active"
    fn = AsyncMock(return_value=True)
    env["sup"]._confirm_fn = fn
    ok, _, sanitized = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True
    assert sanitized["vx"] == pytest.approx(0.1)
    assert gate.calls == 1
    fn.assert_not_called()


async def test_active_with_risk_gate_calls_confirm_with_reason(env):
    gate = _StubGate(verdict_safe=False, reason="person 0.5 m ahead")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "active"
    received = {}

    async def fn(tool, sanitized, risk_reason=None):
        received["tool"] = tool
        received["risk_reason"] = risk_reason
        return True

    env["sup"]._confirm_fn = fn
    ok, _, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True
    assert gate.calls == 1
    assert received["risk_reason"] == "person 0.5 m ahead"
    assert received["tool"] == "walk"


async def test_confirm_with_safe_gate_skips_confirm(env):
    """The biggest UX win: confirm-mode operator stops being asked
    when the vision gate already said SAFE."""
    gate = _StubGate(verdict_safe=True, reason="empty hallway")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "confirm"
    fn = AsyncMock(return_value=True)
    env["sup"]._confirm_fn = fn
    ok, _, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True
    assert gate.calls == 1
    fn.assert_not_called()


async def test_confirm_with_risk_gate_calls_confirm_with_reason(env):
    gate = _StubGate(verdict_safe=False, reason="glass cup on path")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "confirm"
    received = {}

    async def fn(tool, sanitized, risk_reason=None):
        received["risk_reason"] = risk_reason
        return False

    env["sup"]._confirm_fn = fn
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "declined" in reason
    assert received["risk_reason"] == "glass cup on path"


async def test_no_gate_preserves_old_behaviour_active(env):
    env["sup"].vision_gate = None
    env["sup"].run_mode = "active"
    ok, _, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True


async def test_gate_skipped_for_non_motion_tools(env):
    """Non-motion tools take the early `is_motion=False` return — they
    must not consume the gate even when one is wired in."""
    gate = _StubGate(verdict_safe=False, reason="should never be called")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "active"
    ok, _, _ = await env["sup"].validate("say", {"text": "hi"})
    assert ok is True
    assert gate.calls == 0
