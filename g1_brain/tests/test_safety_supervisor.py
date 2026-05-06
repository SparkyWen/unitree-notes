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


# ----- _confirm_in_terminal: stale-stdin handling ---------------------------
# Regression for "operator typed `y` but the walk was declined": when the
# terminal is in canonical mode and the operator presses arrow keys (or any
# other Enter-terminated noise) between prompts, those bytes sit unread in
# stdin's line buffer. Without flushing, the next prompt's `readline` returns
# the stale bytes and the operator's actual `y` ends up queued for nobody.
# The fix flushes stdin inside the executor right before readline, so only
# fresh post-prompt input is honored.

@pytest.mark.asyncio
async def test_confirm_in_terminal_flushes_stdin_before_read(monkeypatch):
    """tcflush must be called before readline so stale bytes are dropped."""
    from g1_brain.safety import supervisor as sup_mod

    call_order: list[str] = []

    class _FakeTermios:
        TCIFLUSH = 0
        @staticmethod
        def tcflush(_fd, _what):
            call_order.append("tcflush")

    class _FakeStdin:
        def fileno(self):
            return 0
        def readline(self):
            call_order.append("readline")
            return "y\n"

    monkeypatch.setitem(__import__("sys").modules, "termios", _FakeTermios)
    monkeypatch.setattr(sup_mod.sys, "stdin", _FakeStdin())

    ok = await sup_mod._confirm_in_terminal("walk", {"vx": 0.1})
    assert ok is True
    assert call_order == ["tcflush", "readline"], call_order


@pytest.mark.asyncio
async def test_confirm_in_terminal_decline_on_non_yes(monkeypatch):
    """Anything that isn't y/yes after strip+lower must decline."""
    from g1_brain.safety import supervisor as sup_mod

    class _FakeTermios:
        TCIFLUSH = 0
        @staticmethod
        def tcflush(_fd, _what):
            pass

    class _FakeStdin:
        def __init__(self, line):
            self._line = line
        def fileno(self):
            return 0
        def readline(self):
            return self._line

    monkeypatch.setitem(__import__("sys").modules, "termios", _FakeTermios)

    # Stale escape sequence (right-arrow + Enter) — exactly what the live
    # 2026-05-06 incident produced.
    monkeypatch.setattr(sup_mod.sys, "stdin", _FakeStdin("\x1b[C\n"))
    assert await sup_mod._confirm_in_terminal("walk", {}) is False

    # EOF (closed stdin) returns empty string — must also decline.
    monkeypatch.setattr(sup_mod.sys, "stdin", _FakeStdin(""))
    assert await sup_mod._confirm_in_terminal("walk", {}) is False


@pytest.mark.asyncio
async def test_confirm_in_terminal_survives_no_termios(monkeypatch):
    """On platforms without termios (e.g. piped stdin) we must still read."""
    from g1_brain.safety import supervisor as sup_mod
    import sys as _sys

    # Hide termios so the inner import fails like a non-TTY environment.
    monkeypatch.setitem(_sys.modules, "termios", None)

    class _FakeStdin:
        def fileno(self):
            return 0
        def readline(self):
            return "y\n"

    monkeypatch.setattr(sup_mod.sys, "stdin", _FakeStdin())
    assert await sup_mod._confirm_in_terminal("walk", {}) is True
