"""End-to-end vertical-slice test: Brain tool call → SkillServer → SafetySupervisor → ComboController.

This is the integration test: it does NOT touch DDS / OpenAI / MuJoCo /
cameras, but it wires the real classes together and asserts that a tool
call from the brain layer reaches a (mocked) ComboController via the
real SafetySupervisor and the real SkillServer.

The va-demo dependency is mocked because we don't want this test to
require va-demo to be on sys.path.
"""
from __future__ import annotations

import asyncio
import math
import sys
import types

import pytest

from g1_brain.scene_state import (
    SceneStateBus,
    RobotStateBus,
    SceneState,
    GroundConstraint,
    RobotState,
)
from g1_brain.safety import (
    SafetySupervisor,
    RobotFsm,
    RobotFsmState,
    EstopClient,
)
from g1_brain.skills import SkillServer


@pytest.fixture
def busses_with_safe_scene():
    """A SceneStateBus + RobotStateBus seeded with 'all clear, robot upright'."""
    scene = SceneStateBus()
    robot = RobotStateBus()
    scene.update_head_frame(ts=99999.0, resolution=(640, 480))
    scene.update_ground(GroundConstraint(
        clear_path=True,
        nearest_obstacle_m=2.0,
        nearest_person_m=2.0,
        floor_visible_ratio=0.7,
        surface_tilt_deg=0.0,
    ))
    robot.update(RobotState(
        standing=True,
        gravity_proj_z=-0.99,
        base_ang_vel_xyz=(0.0, 0.0, 0.0),
        rl_policy_active=True,
        last_lowstate_age_s=0.05,
        mode_machine=0,
    ))
    return scene, robot


@pytest.fixture
def estop_temp(tmp_path):
    return EstopClient(str(tmp_path / "estop_flag"))


@pytest.fixture
def fsm_engaged():
    fsm = RobotFsm()
    fsm.transition(RobotFsmState.STANDING, "init")
    fsm.transition(RobotFsmState.ENGAGED, "test")
    return fsm


@pytest.fixture
def fake_combo_ctl():
    """Stand-in for g1_sim_rl_combo.ComboController."""
    import numpy as np
    ctl = types.SimpleNamespace()
    ctl.policy_active = True
    ctl.last_state_time = 99999.0
    ctl.set_command_calls = []
    ctl.push_arm_action_calls = []
    ctl.release_calls = 0

    def _set_command(vx, vy, wz):
        ctl.set_command_calls.append((vx, vy, wz))

    def _push_arm_action(kfs):
        ctl.push_arm_action_calls.append(list(kfs))

    def _release():
        ctl.release_calls += 1

    ctl.set_command = _set_command
    ctl.push_arm_action = _push_arm_action
    ctl.release_arms = _release
    ctl.arm_rest = np.zeros(14)
    ctl.arm_scale = np.ones(14) * 0.44
    ctl.arm_offset = np.zeros(14)
    return ctl


@pytest.fixture
def cfg_active_mode():
    return {
        "mode": "sim",
        "safety": {
            "walk": {
                "vx_max": 0.2, "vy_max": 0.1, "wz_max": 0.3,
                "duration_max_s": 1.0, "duration_min_s": 0.2,
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
        },
    }


@pytest.fixture
def real_safety_supervisor(cfg_active_mode, busses_with_safe_scene, estop_temp,
                           fsm_engaged):
    scene, robot = busses_with_safe_scene
    return SafetySupervisor(
        cfg=cfg_active_mode,
        scene_bus=scene,
        robot_bus=robot,
        fsm=fsm_engaged,
        estop=estop_temp,
        run_mode="active",
    )


@pytest.fixture
def real_skill_server(real_safety_supervisor, busses_with_safe_scene,
                      fsm_engaged, fake_combo_ctl):
    scene, _ = busses_with_safe_scene

    class _FakeTts:
        async def speak(self, text):
            self.last_text = text
            return None

    class _FakeVision:
        async def describe(self, **kw):
            return "(fake vision result)"

    class _FakeCameraHub:
        def latest_head_jpeg_b64(self, **kw):
            return "ZmFrZQ=="
        def latest_usb_jpeg_b64(self, **kw):
            return "ZmFrZQ=="

    return SkillServer(
        combo_ctl=fake_combo_ctl,
        safety=real_safety_supervisor,
        tts=_FakeTts(),
        vision=_FakeVision(),
        camera_hub=_FakeCameraHub(),
        scene_bus=scene,
        fsm=fsm_engaged,
        sim=True,
    )


# --------------------------- the tests ----------------------------


@pytest.mark.asyncio
async def test_brain_to_combo_walk_full_path(real_skill_server, fake_combo_ctl):
    """Brain → SkillServer.execute('walk') → safety pass → combo.set_command."""
    result = await real_skill_server.execute(
        "walk",
        {"vx": 0.18, "vy": 0.0, "wz": 0.0, "duration_s": 0.3},
    )
    assert result["ok"] is True, result
    # Expect set_command(vx,vy,wz) then set_command(0,0,0) on completion.
    assert (0.18, 0.0, 0.0) in fake_combo_ctl.set_command_calls
    assert fake_combo_ctl.set_command_calls[-1] == (0.0, 0.0, 0.0)


@pytest.mark.asyncio
async def test_brain_to_combo_gesture_full_path(real_skill_server, fake_combo_ctl):
    result = await real_skill_server.execute("gesture", {"name": "wave_right"})
    assert result["ok"] is True, result
    assert len(fake_combo_ctl.push_arm_action_calls) == 1


@pytest.mark.asyncio
async def test_walk_gets_clamped_by_safety(real_skill_server, fake_combo_ctl):
    """LLM tries vx=10 m/s; safety clamps to vx_max=0.2 before combo gets it."""
    await real_skill_server.execute(
        "walk",
        {"vx": 10.0, "vy": 0.0, "wz": 0.0, "duration_s": 0.3},
    )
    issued = [v for v in fake_combo_ctl.set_command_calls if v != (0.0, 0.0, 0.0)]
    assert issued, "no non-zero command was issued"
    assert all(abs(vx) <= 0.2 for vx, _, _ in issued)


@pytest.mark.asyncio
async def test_estop_engaged_blocks_walk(real_skill_server, estop_temp,
                                          fake_combo_ctl):
    estop_temp.engage("test")
    try:
        result = await real_skill_server.execute(
            "walk",
            {"vx": 0.1, "vy": 0.0, "wz": 0.0, "duration_s": 0.3},
        )
    finally:
        estop_temp.release()
    assert result["ok"] is False
    assert "estop" in result["reason"].lower()
    # combo must NOT have been touched.
    issued = [v for v in fake_combo_ctl.set_command_calls if v != (0.0, 0.0, 0.0)]
    assert not issued, f"combo was driven despite estop: {issued}"


@pytest.mark.asyncio
async def test_obstacle_blocks_walk(real_skill_server, busses_with_safe_scene,
                                    fake_combo_ctl):
    scene, _ = busses_with_safe_scene
    scene.update_ground(GroundConstraint(
        clear_path=False,
        nearest_obstacle_m=0.4,
        nearest_person_m=2.0,
        floor_visible_ratio=0.5,
        surface_tilt_deg=0.0,
    ))
    result = await real_skill_server.execute(
        "walk",
        {"vx": 0.1, "vy": 0.0, "wz": 0.0, "duration_s": 0.3},
    )
    assert result["ok"] is False
    issued = [v for v in fake_combo_ctl.set_command_calls if v != (0.0, 0.0, 0.0)]
    assert not issued


@pytest.mark.asyncio
async def test_query_scene_state_returns_summary(real_skill_server):
    result = await real_skill_server.execute("query_scene_state", {})
    assert result["ok"] is True
    assert "scene" in result
    assert result["scene"]["clear_path"] is True
    assert math.isclose(result["scene"]["nearest_obstacle_m"], 2.0)


@pytest.mark.asyncio
async def test_unknown_tool_clean_failure(real_skill_server):
    result = await real_skill_server.execute("teleport", {"target": "moon"})
    assert result["ok"] is False
    assert "unknown" in result["reason"].lower() or "unhandled" in result["reason"].lower()
