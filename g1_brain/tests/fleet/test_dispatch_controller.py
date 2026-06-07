"""DispatchController: the autonomous detect->sleep->reassign loop over a real
in-process harness pair (LoopbackHub), plus the human-command path."""
import asyncio

import pytest

from g1_brain.fleet.bus.loopback import LoopbackHub
from g1_brain.fleet.agent.sim_harness import SimRobotHarness
from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.fleet.coordinator.controller import DispatchController
from g1_brain.fleet.coordinator.anomaly import AnomalyDetector
from g1_brain.fleet.coordinator.dispatch import DispatchEngine
from g1_brain.fleet.coordinator.gateway import CommandGateway
from g1_brain.fleet.coordinator.agent_llm import CoordinatorAgent, StructuredOp
from g1_brain.fleet.contracts.models import Mission, TaskSpec, EventType


async def _build():
    hub = LoopbackHub()
    gw = CommandGateway(send_command=hub.send_command, event_log=hub.event_log)
    hub.admission_sink = gw.record_admission
    engine = DispatchEngine(hub.registry)
    harnesses = {}
    controller = DispatchController(
        registry=hub.registry, detector=AnomalyDetector(), engine=engine,
        gateway=gw, event_log=hub.event_log, agent=CoordinatorAgent(),
        inject_hook=lambda rid, **kw: harnesses[rid].inject(**kw))
    agents = []
    for rid in ("g1_a", "g1_b"):
        h = SimRobotHarness.from_mock(rid, n_joints=4)
        harnesses[rid] = h
        ag = RobotAgent(core=h, bus=hub.client(), heartbeat_interval_s=0.03,
                        perception_interval_s=None)
        await ag.start()
        agents.append(ag)
    await asyncio.sleep(0.08)  # let heartbeats populate the registry
    return hub, controller, harnesses, agents


@pytest.mark.asyncio
async def test_autonomous_overheat_sleep_reassign():
    hub, controller, harnesses, agents = await _build()
    try:
        await controller.dispatch_mission(Mission(
            mission_id="m1", created_by="op",
            tasks=[TaskSpec(task_id="t1", type="patrol", required_capabilities=["patrol"])]))
        await asyncio.sleep(0.05)
        holder = controller.engine.assignments["t1"]
        other = "g1_b" if holder == "g1_a" else "g1_a"

        controller.inject(holder, battery_temperature_c=75.0, fault="battery_hot")
        await asyncio.sleep(0.08)         # heartbeats carry the new temperature up
        await controller.tick()            # coordinator perceives + acts
        await asyncio.sleep(0.05)          # commands round-trip

        assert harnesses[holder].fsm.state.value == "DORMANT"
        assert controller.engine.assignments["t1"] == other
        assert harnesses[other].backend.last_posture.value == "PATROL"

        types = {e.type for e in hub.event_log.query(limit=2000)}
        assert EventType.ANOMALY_DETECTED in types
        assert EventType.TASK_REASSIGNED in types
        assert EventType.ROBOT_SLEEPING in types     # robot-side planner event
    finally:
        for ag in agents:
            await ag.stop()


@pytest.mark.asyncio
async def test_human_sleep_then_wake():
    hub, controller, harnesses, agents = await _build()
    try:
        await controller.run_op(StructuredOp("sleep", {"robot": "g1_a"}))
        await asyncio.sleep(0.05)
        assert harnesses["g1_a"].fsm.state.value == "DORMANT"
        await controller.run_op(StructuredOp("wake", {"robot": "g1_a"}))
        await asyncio.sleep(0.05)
        assert harnesses["g1_a"].fsm.state.value == "STANDING"
    finally:
        for ag in agents:
            await ag.stop()


@pytest.mark.asyncio
async def test_run_op_rejects_unknown_robot():
    hub, controller, harnesses, agents = await _build()
    try:
        res = await controller.run_op(StructuredOp("sleep", {"robot": "ghost"}))
        assert res["ok"] is False
    finally:
        for ag in agents:
            await ag.stop()
