import asyncio
import pytest

from g1_brain.safety.state_machine import RobotFsm, RobotFsmState
from g1_brain.scene_state.fusion import SceneStateBus, RobotStateBus
from g1_brain.scene_state.types import RobotState as BodyState, GroundConstraint
from g1_brain.fleet.harness_core.core import HarnessCore
from g1_brain.fleet.harness_core.event_fanout import EventSink, attach_to_logger
from g1_brain.fleet.contracts.models import EventType


class _FakeLogger:
    def log_safety_event(self, **kw): pass
    def log_action_result(self, **kw): pass
    def log_scene_snapshot(self, **kw): pass


def _make_core():
    fsm = RobotFsm(initial=RobotFsmState.STANDING)
    fsm.transition(RobotFsmState.ENGAGED, "test")
    scene = SceneStateBus()
    scene.update_ground(GroundConstraint(clear_path=True, nearest_obstacle_m=2.0,
                                         nearest_person_m=float("inf"),
                                         floor_visible_ratio=0.9, surface_tilt_deg=1.0))
    robot = RobotStateBus()
    robot.update(BodyState(standing=True, gravity_proj_z=-0.98,
                           base_ang_vel_xyz=(0, 0, 0), rl_policy_active=True,
                           last_lowstate_age_s=0.01, mode_machine=1))
    sink = EventSink(robot_id="g1-sim-01")
    core = HarnessCore(robot_id="g1-sim-01", fsm=fsm, scene_bus=scene,
                       robot_bus=robot, event_sink=sink, harness_version="0.1.0")
    return core, sink


def test_get_capabilities():
    core, _ = _make_core()
    cap = core.get_capabilities()
    assert cap.robot_id == "g1-sim-01"
    assert any(c.name == "walk" for c in cap.capabilities)


def test_get_state_maps_fsm_and_body():
    core, _ = _make_core()
    st = core.get_state(seq=7)
    assert st.robot_id == "g1-sim-01"
    assert st.fsm_state == "ENGAGED"
    assert st.seq == 7
    assert st.core.policy_active is True
    assert st.core.safety_state.gravity_proj_z == -0.98
    assert st.core.safety_state.watchdog_ok.lowstate is True


def test_snapshot_scene_returns_bus_snapshot():
    core, _ = _make_core()
    scene = core.snapshot_scene()
    assert scene.ground is not None
    assert scene.ground.clear_path is True


@pytest.mark.asyncio
async def test_subscribe_events_yields_fanned_out_event():
    core, sink = _make_core()
    logger = _FakeLogger()
    attach_to_logger(logger, sink)
    logger.log_safety_event(kind="reject", rule="RULE-9")
    agen = core.subscribe_events()
    ev = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    assert ev.type == EventType.SAFETY_EVENT


def test_admit_is_reserved():
    core, _ = _make_core()
    with pytest.raises(NotImplementedError):
        core.admit(None)
