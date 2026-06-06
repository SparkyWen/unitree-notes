"""Tier-1 end-to-end dispatch scenario (pure Python, no MuJoCo/DDS).

Two SimRobotHarness over a LoopbackHub + the full coordinator dispatch brain.
Proves the closed loop deterministically: overheat -> anomaly -> safe-sleep ->
reassign, plus the human-command collaboration path, asserted by replaying the
append-only event log.
"""
import asyncio

import pytest

from g1_brain.fleet.bus.loopback import LoopbackHub
from g1_brain.fleet.agent.sim_harness import SimRobotHarness
from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.fleet.coordinator.controller import DispatchController
from g1_brain.fleet.coordinator.anomaly import AnomalyDetector
from g1_brain.fleet.coordinator.dispatch import DispatchEngine
from g1_brain.fleet.coordinator.gateway import CommandGateway
from g1_brain.fleet.coordinator.lease import LeaseManager
from g1_brain.fleet.coordinator.agent_llm import CoordinatorAgent, StructuredOp
from g1_brain.fleet.contracts.models import Mission, TaskSpec, EventType


async def _fleet():
    hub = LoopbackHub()
    gw = CommandGateway(send_command=hub.send_command, event_log=hub.event_log)
    hub.admission_sink = gw.record_admission
    harnesses = {}
    controller = DispatchController(
        registry=hub.registry, detector=AnomalyDetector(), engine=DispatchEngine(hub.registry),
        gateway=gw, event_log=hub.event_log, lease=LeaseManager(), agent=CoordinatorAgent(),
        inject_hook=lambda rid, **kw: harnesses[rid].inject(**kw))
    agents = []
    for rid in ("g1_a", "g1_b"):
        h = SimRobotHarness.from_mock(rid, n_joints=4)
        harnesses[rid] = h
        ag = RobotAgent(core=h, bus=hub.client(), heartbeat_interval_s=0.03,
                        perception_interval_s=None)
        await ag.start()
        agents.append(ag)
    await asyncio.sleep(0.08)
    return hub, controller, harnesses, agents


def _ordered_subsequence(seq, sub) -> bool:
    it = iter(seq)
    return all(any(x == s for x in it) for s in sub)


@pytest.mark.asyncio
async def test_full_closed_loop_and_human_handoff():
    hub, controller, harnesses, agents = await _fleet()
    try:
        # --- assign a patrol mission ---
        await controller.dispatch_mission(Mission(
            mission_id="m1", created_by="op:li", intent_text="patrol zone A",
            tasks=[TaskSpec(task_id="t1", type="patrol", required_capabilities=["patrol"])]))
        await asyncio.sleep(0.05)
        holder = controller.engine.assignments["t1"]
        other = "g1_b" if holder == "g1_a" else "g1_a"
        assert harnesses[holder].backend.last_posture.value == "PATROL"

        # --- autonomous: overheat -> sleep -> reassign ---
        controller.inject(holder, battery_temperature_c=75.0, fault="battery_hot")
        await asyncio.sleep(0.08)
        anomalies = await controller.tick()
        await asyncio.sleep(0.05)
        assert any(a.kind == "battery_overheat" and a.robot_id == holder for a in anomalies)
        assert harnesses[holder].fsm.state.value == "DORMANT"
        assert harnesses[holder].backend.last_posture.value == "SLEEP"
        assert controller.engine.assignments["t1"] == other
        assert harnesses[other].backend.last_posture.value == "PATROL"

        # ordered coordinator chain on the anomaly trace
        trace = f"trace-battery_overheat-1"
        chain = [(e.type, e.payload.get("capability")) for e in hub.event_log.replay(trace)]
        types_only = [t for t, _ in chain]
        assert _ordered_subsequence(types_only, [
            EventType.ANOMALY_DETECTED, EventType.COMMAND_ISSUED,
            EventType.TASK_REASSIGNED, EventType.COMMAND_ISSUED])
        # sleep + resume_task were both issued + accepted on this trace
        issued_caps = {cap for t, cap in chain if t == EventType.COMMAND_ISSUED}
        assert {"sleep", "resume_task"} <= issued_caps
        assert sum(1 for t, _ in chain if t == EventType.COMMAND_ACCEPTED) >= 2

        # --- human collaboration: wake the hot robot, hand the task back ---
        controller.inject(holder, battery_temperature_c=30.0)  # cooled (for realism)
        res = await controller.run_op(StructuredOp("wake", {"robot": holder}))
        assert res["ok"] is True
        await asyncio.sleep(0.05)
        assert harnesses[holder].fsm.state.value == "STANDING"

        await controller.run_op(StructuredOp("takeover", {"from": other, "to": holder}))
        await asyncio.sleep(0.05)
        assert controller.engine.assignments["t1"] == holder
        assert harnesses[holder].backend.last_posture.value == "PATROL"
    finally:
        for ag in agents:
            await ag.stop()
