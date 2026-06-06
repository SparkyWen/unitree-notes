"""RobotAgent wires the down-bound command path to the harness admission gate."""
import asyncio

import pytest

from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.fleet.agent.sim_harness import SimRobotHarness
from g1_brain.fleet.bus.loopback import LoopbackHub
from g1_brain.fleet.contracts.models import CommandEnvelope
from g1_brain.safety.state_machine import RobotFsmState


@pytest.mark.asyncio
async def test_agent_handles_command_via_admission_gate():
    hub = LoopbackHub()
    decisions = []
    hub.admission_sink = decisions.append
    bus = hub.client()
    harness = SimRobotHarness.from_mock("g1_a", n_joints=4)
    agent = RobotAgent(core=harness, bus=bus, heartbeat_interval_s=0.05,
                       perception_interval_s=None)
    await agent.start()
    try:
        env = CommandEnvelope.make(issued_by="coord", issued_to="g1_a",
                                   capability="sleep", payload={"reason": "overheat"})
        await hub.send_command("g1_a", env)
        await asyncio.sleep(0.05)
    finally:
        await agent.stop()

    assert decisions and decisions[0].decision == "accepted"
    assert harness.fsm.state == RobotFsmState.DORMANT


@pytest.mark.asyncio
async def test_agent_heartbeats_carry_battery():
    hub = LoopbackHub()
    bus = hub.client()
    harness = SimRobotHarness.from_mock("g1_b", n_joints=4)
    harness.inject(battery_temperature_c=70.0)
    agent = RobotAgent(core=harness, bus=bus, heartbeat_interval_s=0.05,
                       perception_interval_s=None)
    await agent.start()
    try:
        await asyncio.sleep(0.12)
    finally:
        await agent.stop()
    st = hub.registry.latest_state("g1_b")
    assert st is not None and st.core.battery is not None
    assert st.core.battery.temperature_c == 70.0
