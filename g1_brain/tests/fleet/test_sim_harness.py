"""SimRobotHarness: the assembled headless fast/slow brain used in sim + Tier-1."""
import pytest

from g1_brain.fleet.agent.sim_harness import SimRobotHarness
from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.contracts.models import CommandEnvelope
from g1_brain.safety.state_machine import RobotFsmState


def test_capabilities_advertise_dispatch_verbs():
    h = SimRobotHarness.from_mock("g1_a", n_joints=4)
    caps = {c.name for c in h.get_capabilities().capabilities}
    assert {"sleep", "wake", "patrol", "stop"} <= caps


def test_state_reports_battery_and_health_default_ok():
    h = SimRobotHarness.from_mock("g1_a", n_joints=4)
    st = h.get_state(seq=3)
    assert st.robot_id == "g1_a" and st.seq == 3
    assert st.core.battery is not None
    assert st.core.health.level == "ok"
    assert st.fsm_state == "STANDING"


def test_load_then_tick_raises_reported_temperature():
    h = SimRobotHarness.from_mock("g1_a", n_joints=4)
    h.backend.set_load(30.0)
    base = h.get_state().core.battery.temperature_c
    for _ in range(100):
        h.tick()
    hot = h.get_state().core.battery.temperature_c
    assert hot > base


def test_inject_overheat_surfaces_in_state():
    h = SimRobotHarness.from_mock("g1_a", n_joints=4)
    h.inject(battery_temperature_c=75.0, fault="battery_hot")
    st = h.get_state()
    assert st.core.battery.temperature_c == 75.0
    assert st.core.health.level == "warning"
    assert "battery_hot" in st.core.health.faults


@pytest.mark.asyncio
async def test_on_command_sleep_drives_dormant_and_sleep_posture():
    h = SimRobotHarness.from_mock("g1_a", n_joints=4)
    env = CommandEnvelope.make(issued_by="coord", issued_to="g1_a",
                               capability="sleep", payload={"reason": "overheat"})
    decision = await h.on_command(env)
    assert decision.decision == "accepted"
    assert h.fsm.state == RobotFsmState.DORMANT
    assert h.backend.last_posture == Posture.SLEEP
    st = h.get_state()
    assert st.fsm_state == "DORMANT"


@pytest.mark.asyncio
async def test_lifecycle_events_are_subscribable():
    h = SimRobotHarness.from_mock("g1_a", n_joints=4)
    agen = h.subscribe_events()
    env = CommandEnvelope.make(issued_by="coord", issued_to="g1_a",
                               capability="patrol", payload={"task_id": "t1"})
    await h.on_command(env)
    import asyncio
    ev = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    assert ev.payload.get("task_id") == "t1"
