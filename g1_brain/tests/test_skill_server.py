"""Tests for g1_brain.skills.skill_server.SkillServer.

We mock every collaborator so the test only exercises SkillServer's own
control flow: validate-then-dispatch, walk's reactive interrupt loop,
gesture/static_pose lookups, stop's combined effect, and the defensive
stop-on-exception path.

The g1_sim_rl_combo module is heavy (loads ONNX), so we monkey-patch
``skill_server._load_combo_module`` to return a tiny fake.
"""
from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pytest

from g1_brain.skills import skill_server as ss_mod
from g1_brain.skills.skill_server import SkillServer


# ---------- Fakes ----------------------------------------------------------

ARM_DIM = 14


@dataclasses.dataclass
class _FakeArmAction:
    """Tiny stand-in for g1_sim_rl_combo.ArmAction."""
    key: str
    name: str
    keyframes: List[Tuple[float, np.ndarray]]


def _fake_combo_module():
    """Build a minimal stand-in for g1_sim_rl_combo. Provides the only two
    symbols SkillServer touches: ArmAction (unused directly here, but
    nice to have) and build_arm_actions(arm_rest, arm_scale).
    """

    def build_arm_actions(arm_rest, arm_scale):
        # Fake the same 8 keys "1".."8" that combo.build_arm_actions yields,
        # in the same order.
        names = [
            ("1", "wave right arm"),
            ("2", "wave left arm"),
            ("3", "hands up (cheer)"),
            ("4", "T-pose"),
            ("5", "salute"),
            ("6", "clap (twice)"),
            ("7", "boxer guard"),
            ("8", "punch combo (jab L+R)"),
        ]
        out = []
        for key, name in names:
            target = arm_rest + 0.1 * arm_scale  # a small dummy delta
            out.append(_FakeArmAction(
                key=key, name=name,
                keyframes=[(1.5, target.copy()), (1.0, target.copy()),
                           (1.5, arm_rest.copy())],
            ))
        return out

    return SimpleNamespace(
        ArmAction=_FakeArmAction,
        build_arm_actions=build_arm_actions,
    )


@pytest.fixture(autouse=True)
def _patch_combo_loader(monkeypatch):
    """Make every test see the fake combo module."""
    monkeypatch.setattr(ss_mod, "_load_combo_module", _fake_combo_module)


class FakeCombo:
    """Stand-in for g1_sim_rl_combo.ComboController; just records calls."""

    def __init__(self):
        self.arm_rest = np.zeros(ARM_DIM)
        self.arm_scale = np.ones(ARM_DIM)
        self.arm_offset = np.zeros(ARM_DIM)
        self.set_command_calls: List[Tuple[float, float, float]] = []
        self.push_arm_action_calls: List[List[Tuple[float, np.ndarray]]] = []
        self.release_arms_calls: int = 0
        self.policy_active = True
        self.last_state_time = 0.0

    def set_command(self, vx, vy, wz):
        self.set_command_calls.append((float(vx), float(vy), float(wz)))

    def push_arm_action(self, keyframes):
        self.push_arm_action_calls.append(list(keyframes))

    def release_arms(self):
        self.release_arms_calls += 1


class FakeSafety:
    """Mock SafetySupervisor.validate(tool, args) -> (ok, reason, sanitized)."""

    def __init__(self, *, ok=True, reason="", sanitized=None,
                 raise_exc: Optional[Exception] = None):
        self.ok = ok
        self.reason = reason
        self.sanitized = sanitized   # if None, echo args back
        self.raise_exc = raise_exc
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def validate(self, tool: str, args: Dict[str, Any]):
        self.calls.append((tool, dict(args)))
        if self.raise_exc is not None:
            raise self.raise_exc
        sanitized = self.sanitized if self.sanitized is not None else dict(args)
        return self.ok, self.reason, sanitized


class FakeTTS:
    def __init__(self):
        self.calls: List[str] = []

    async def speak(self, text, voice=None):
        self.calls.append(text)


class FakeVision:
    async def describe(self, image_jpeg_b64, prompt, detail=None):
        return f"described({len(image_jpeg_b64 or '')}b, detail={detail})"


class FakeCameraHub:
    def __init__(self, jpeg: Optional[str] = "FAKEJPEG"):
        self._jpeg = jpeg
        self.calls = 0

    def latest_head_jpeg_b64(self):
        self.calls += 1
        return self._jpeg


@dataclasses.dataclass
class _FakeGround:
    clear_path: bool = True
    nearest_obstacle_m: float = 5.0
    nearest_person_m: float = 5.0
    floor_visible_ratio: float = 0.8
    surface_tilt_deg: float = 0.0


@dataclasses.dataclass
class _FakeScene:
    ground: Optional[_FakeGround]
    head_detections: list = dataclasses.field(default_factory=list)
    user_detections: list = dataclasses.field(default_factory=list)
    user_pose: Any = None

    def summary_for_llm(self):
        g = self.ground
        return {
            "persons_visible": 0,
            "nearest_obstacle_m": g.nearest_obstacle_m if g else None,
            "nearest_person_m": g.nearest_person_m if g else None,
            "clear_path": g.clear_path if g else None,
            "surface_tilt_deg": g.surface_tilt_deg if g else None,
            "user_gesture": None,
            "user_gesture_confidence": 0.0,
            "warnings": [],
        }


class FakeSceneBus:
    """SceneBus mock with a pluggable snapshot sequence.

    Pass a list of FakeScene objects to ``snapshots`` and they'll be served
    in order; the last one is repeated indefinitely. This lets tests
    simulate "path becomes blocked at iteration 2".
    """

    def __init__(self, snapshots: List[_FakeScene]):
        self.snapshots = snapshots
        self.idx = 0
        self.snapshot_count = 0

    def snapshot(self):
        self.snapshot_count += 1
        s = self.snapshots[min(self.idx, len(self.snapshots) - 1)]
        self.idx += 1
        return s


class FakeFsm:
    def __init__(self):
        from g1_brain.safety.state_machine import RobotFsmState
        self._state = RobotFsmState.ENGAGED
        self.transitions: List[Tuple[Any, str]] = []

    @property
    def state(self):
        return self._state

    def transition(self, new_state, reason=""):
        self._state = new_state
        self.transitions.append((new_state, reason))
        return new_state


# ---------- Helpers --------------------------------------------------------

def make_server(*, safety=None, scene=None, camera=None) -> SkillServer:
    return SkillServer(
        combo_ctl=FakeCombo(),
        safety=safety or FakeSafety(),
        tts=FakeTTS(),
        vision=FakeVision(),
        camera_hub=camera or FakeCameraHub(),
        scene_bus=scene or FakeSceneBus([_FakeScene(_FakeGround())]),
        fsm=FakeFsm(),
        sim=True,
    )


# ============================================================================
# Tests
# ============================================================================


# --- Safety gating ----------------------------------------------------------

async def test_safety_rejection_short_circuits():
    safety = FakeSafety(ok=False, reason="bounds violation")
    s = make_server(safety=safety)
    s.combo.set_command_calls.clear()
    result = await s.execute("walk", {"vx": 0.5, "duration_s": 0.5})
    assert result == {"ok": False, "skill": "walk", "reason": "bounds violation"}
    # Safety was consulted exactly once.
    assert len(safety.calls) == 1
    # And the skill body never ran (no set_command on walk).
    assert s.combo.set_command_calls == []


async def test_safety_acceptance_runs_skill_with_sanitized_args():
    safety = FakeSafety(ok=True, sanitized={"text": "clean"})
    s = make_server(safety=safety)
    result = await s.execute("say", {"text": "raw"})
    assert result["ok"] is True
    assert s.tts.calls == ["clean"]   # used sanitized version, not raw


async def test_safety_exception_returns_clean_failure():
    safety = FakeSafety(raise_exc=RuntimeError("boom"))
    s = make_server(safety=safety)
    result = await s.execute("stop", {})
    assert result["ok"] is False
    assert "safety exception" in result["reason"]


# --- _skill_walk: command issuance + zero on completion ---------------------

async def test_walk_sets_command_and_zeros_after_duration():
    s = make_server()
    result = await s.execute("walk", {"vx": 0.1, "vy": 0.0, "wz": 0.0, "duration_s": 0.4})
    assert result["ok"] is True
    # First call is the requested velocity; final call is zero.
    assert s.combo.set_command_calls[0] == (0.1, 0.0, 0.0)
    assert s.combo.set_command_calls[-1] == (0.0, 0.0, 0.0)
    # Should not have aborted.
    assert result.get("aborted") is False
    assert result["actual_duration_s"] >= 0.39
    # And a scene snapshot is attached on success.
    assert "scene_after" in result


async def test_walk_aborts_when_clear_path_becomes_false():
    """Scene starts clear, then on the second snapshot becomes blocked.

    We give walk a long duration so we're guaranteed to take >=2 snapshots
    (every 0.2s). The abort branch should fire and the test should finish
    well before duration_s elapses.
    """
    snapshots = [
        _FakeScene(_FakeGround(clear_path=True, nearest_obstacle_m=5.0)),
        _FakeScene(_FakeGround(clear_path=False, nearest_obstacle_m=0.4)),
    ]
    scene = FakeSceneBus(snapshots)
    s = make_server(scene=scene)
    result = await s.execute("walk", {"vx": 0.1, "duration_s": 1.4})
    assert result["ok"] is True   # ok=True because the abort is graceful
    assert result["aborted"] is True
    assert "blocked" in result["abort_reason"] or "obstacle" in result["abort_reason"]
    # We must have aborted *well* before the requested duration.
    assert result["actual_duration_s"] < 1.0
    # Final command must be zero (finally clause).
    assert s.combo.set_command_calls[-1] == (0.0, 0.0, 0.0)


async def test_walk_aborts_on_close_obstacle():
    snapshots = [
        _FakeScene(_FakeGround(clear_path=True, nearest_obstacle_m=5.0)),
        _FakeScene(_FakeGround(clear_path=True, nearest_obstacle_m=0.3)),  # < 0.5
    ]
    s = make_server(scene=FakeSceneBus(snapshots))
    result = await s.execute("walk", {"vx": 0.1, "duration_s": 1.4})
    assert result["aborted"] is True
    assert "obstacle" in result["abort_reason"]


# --- Exception inside walk triggers defensive stop --------------------------

async def test_walk_exception_triggers_stop_and_returns_failure():
    """If the scene_bus.snapshot() throws mid-walk, we should run the
    defensive stop and report ok=false."""
    bad_bus = FakeSceneBus([])  # empty list -> snapshot() will IndexError

    s = make_server(scene=bad_bus)
    # The empty snapshots list will raise IndexError on the first read.
    result = await s.execute("walk", {"vx": 0.1, "duration_s": 1.0})
    assert result["ok"] is False
    assert "exception" in result["reason"]
    # Defensive stop ran: there should be at least one (0,0,0) command and
    # release_arms should have been called via _skill_stop.
    assert (0.0, 0.0, 0.0) in s.combo.set_command_calls
    assert s.combo.release_arms_calls >= 1


# --- Gesture lookup --------------------------------------------------------

async def test_gesture_pushes_correct_keyframes():
    s = make_server()
    # Capture what build_arm_actions(...) made for "wave_right" (key "1") so
    # we can verify it's exactly what got pushed.
    expected = s._gesture_table["wave_right"]
    result = await s.execute("gesture", {"name": "wave_right"})
    assert result["ok"] is True
    assert s.combo.push_arm_action_calls
    pushed = s.combo.push_arm_action_calls[-1]
    assert pushed is expected.keyframes or pushed == expected.keyframes


async def test_gesture_unknown_name_rejected():
    s = make_server()
    result = await s.execute("gesture", {"name": "nope_not_a_gesture"})
    assert result["ok"] is False
    assert "unknown gesture" in result["reason"]
    assert s.combo.push_arm_action_calls == []


# --- static_pose -----------------------------------------------------------

async def test_static_pose_salute_uses_extras():
    s = make_server()
    # 'salute' lives in both combo's table (key 5) and our extras (added
    # second). The extras_by_name is consulted first by _skill_static_pose,
    # so we should see the extras keyframes.
    extras_action = s._extras_by_name["salute"]
    result = await s.execute("static_pose", {"name": "salute"})
    assert result["ok"] is True
    assert s.combo.push_arm_action_calls[-1] == extras_action.keyframes


async def test_static_pose_rejects_non_extra_name():
    s = make_server()
    # 'wave_right' is a valid gesture but not allowed via static_pose.
    result = await s.execute("static_pose", {"name": "wave_right"})
    assert result["ok"] is False
    # And no arm action queued.
    assert s.combo.push_arm_action_calls == []


# --- stop / release_arms ---------------------------------------------------

async def test_stop_zeros_command_and_releases_arms():
    s = make_server()
    result = await s.execute("stop", {})
    assert result["ok"] is True
    assert s.combo.set_command_calls[-1] == (0.0, 0.0, 0.0)
    assert s.combo.release_arms_calls == 1


async def test_release_arms_only_calls_release():
    s = make_server()
    result = await s.execute("release_arms", {})
    assert result["ok"] is True
    assert s.combo.release_arms_calls == 1
    # release_arms must not touch the velocity command.
    assert s.combo.set_command_calls == []


# --- describe_scene & query_scene_state ------------------------------------

async def test_describe_scene_uses_head_camera_and_returns_text():
    cam = FakeCameraHub(jpeg="FAKEJPEG")
    s = make_server(camera=cam)
    result = await s.execute("describe_scene", {"question": "what?"})
    assert result["ok"] is True
    assert "described" in result["description"]
    assert cam.calls == 1


async def test_describe_scene_no_frame_returns_failure():
    cam = FakeCameraHub(jpeg=None)
    s = make_server(camera=cam)
    result = await s.execute("describe_scene", {})
    assert result["ok"] is False
    assert "no frame" in result["reason"]


async def test_query_scene_state_returns_summary():
    s = make_server()
    result = await s.execute("query_scene_state", {})
    assert result["ok"] is True
    assert "scene" in result
    assert result["scene"]["clear_path"] is True


# --- real-robot tools (sim mode) -------------------------------------------

async def test_loco_high_rejected_in_sim():
    s = make_server()
    result = await s.execute("loco_high", {"action": "wave_hand"})
    assert result["ok"] is False
    assert "real-robot only" in result["reason"]


# --- unknown tool ----------------------------------------------------------

async def test_unknown_tool_returns_clean_failure():
    s = make_server()
    result = await s.execute("not_a_tool", {})
    assert result["ok"] is False
    assert "unknown tool" in result["reason"]


# --- compound: mock_imitate ------------------------------------------------

async def test_mock_imitate_delegates_to_gesture():
    s = make_server()
    result = await s.execute("mock_imitate", {"gesture": "wave_right"})
    assert result["ok"] is True
    # Should have pushed the wave_right keyframes through gesture.
    assert s.combo.push_arm_action_calls


async def test_mock_imitate_rejects_non_mirrorable():
    s = make_server()
    result = await s.execute("mock_imitate", {"gesture": "salute"})
    assert result["ok"] is False
    assert "mirrorable" in result["reason"]
