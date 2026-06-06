"""Hardening regressions from the adversarial code review."""
import asyncio

import pytest

from g1_brain.fleet.agent.admission_gate import AdmissionGate
from g1_brain.fleet.agent.local_planner import LocalPlanner
from g1_brain.fleet.agent.motion.mock import MockBackend
from g1_brain.fleet.agent.sim_harness import SimRobotHarness
from g1_brain.fleet.bus.loopback import LoopbackHub
from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.fleet.coordinator.controller import DispatchController
from g1_brain.fleet.coordinator.anomaly import AnomalyDetector
from g1_brain.fleet.coordinator.dispatch import DispatchEngine
from g1_brain.fleet.coordinator.gateway import CommandGateway
from g1_brain.fleet.coordinator.lease import LeaseManager
from g1_brain.fleet.coordinator.agent_llm import CoordinatorAgent, StructuredOp
from g1_brain.fleet.contracts.models import CommandEnvelope, Mission, TaskSpec
from g1_brain.safety.state_machine import RobotFsm, RobotFsmState

_ALL = {"sleep", "wake", "patrol", "resume_task", "idle", "stop"}


def _gate(initial=RobotFsmState.STANDING, now=1000.0):
    fsm = RobotFsm(initial=initial)
    events = []
    planner = LocalPlanner(robot_id="g1_a", fsm=fsm, backend=MockBackend(n_joints=2),
                           emit=events.append)
    gate = AdmissionGate(robot_id="g1_a", fsm=fsm, planner=planner,
                         supported_capabilities=set(_ALL), clock=lambda: now)
    return fsm, gate, events


def _env(cap, *, idem=None, now=1000.0, ttl=30.0):
    return CommandEnvelope.make(issued_by="c", issued_to="g1_a", capability=cap,
                                payload={}, ttl_s=ttl, idempotency_key=idem, now=now)


# --- (B) FSM-correct sleep/wake + idempotent no-op ---

def test_sleep_while_dormant_is_idempotent_noop():
    fsm, gate, events = _gate(initial=RobotFsmState.DORMANT)
    d = gate.admit(_env("sleep"))
    assert d.decision == "accepted"
    assert fsm.state == RobotFsmState.DORMANT
    assert not any(e.type.value == "robot_sleeping" for e in events)  # no spurious event


def test_wake_while_standing_is_idempotent_noop():
    fsm, gate, events = _gate(initial=RobotFsmState.STANDING)
    d = gate.admit(_env("wake"))
    assert d.decision == "accepted"
    assert fsm.state == RobotFsmState.STANDING
    assert not any(e.type.value == "robot_resumed" for e in events)


# --- (C) bounded idempotency: key expires with the command window ---

def test_idempotency_key_reusable_after_expiry():
    fsm = RobotFsm(initial=RobotFsmState.STANDING)
    planner = LocalPlanner(robot_id="g1_a", fsm=fsm, backend=MockBackend(n_joints=2),
                           emit=lambda e: None)
    t = [1000.0]
    gate = AdmissionGate(robot_id="g1_a", fsm=fsm, planner=planner,
                         supported_capabilities=set(_ALL), clock=lambda: t[0])
    e1 = CommandEnvelope.make(issued_by="c", issued_to="g1_a", capability="idle",
                              payload={}, ttl_s=30.0, idempotency_key="k", now=1000.0)
    assert gate.admit(e1).decision == "accepted"
    # advance past expiry; a fresh command reusing the key is no longer a dup
    t[0] = 1100.0
    e2 = CommandEnvelope.make(issued_by="c", issued_to="g1_a", capability="idle",
                              payload={}, ttl_s=30.0, idempotency_key="k", now=1100.0)
    assert gate.admit(e2).decision == "accepted"


# --- (D) bounded harness event queue (no OOM) ---

@pytest.mark.asyncio
async def test_harness_event_queue_is_bounded():
    h = SimRobotHarness.from_mock("g1_a", n_joints=2)
    # emit far more lifecycle events than the queue cap, with no consumer
    for i in range(600):
        cap = "sleep" if i % 2 == 0 else "wake"
        await h.on_command(CommandEnvelope.make(issued_by="c", issued_to="g1_a",
                                                capability=cap, payload={}))
    assert h._events.qsize() <= 256


# --- (A) manual sleep / lease release the held task (no stuck task) ---

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


@pytest.mark.asyncio
async def test_manual_sleep_releases_and_reassigns_task():
    hub, controller, harnesses, agents = await _fleet()
    try:
        await controller.dispatch_mission(Mission(
            mission_id="m1", created_by="op",
            tasks=[TaskSpec(task_id="t1", type="patrol", required_capabilities=["patrol"])]))
        await asyncio.sleep(0.05)
        holder = controller.engine.assignments["t1"]
        other = "g1_b" if holder == "g1_a" else "g1_a"
        # operator manually sleeps the busy robot
        await controller.run_op(StructuredOp("sleep", {"robot": holder}))
        await asyncio.sleep(0.05)
        # task must NOT be stuck on the now-dormant robot
        assert holder not in controller.engine.robot_task
        assert controller.engine.assignments.get("t1") == other
        assert harnesses[other].backend.last_posture.value == "PATROL"
    finally:
        for ag in agents:
            await ag.stop()


@pytest.mark.asyncio
async def test_manual_sleep_no_candidate_goes_needs_operator():
    hub, controller, harnesses, agents = await _fleet()
    try:
        # both available; sleep g1_b first so only the holder remains, then sleep holder
        await controller.dispatch_mission(Mission(
            mission_id="m1", created_by="op",
            tasks=[TaskSpec(task_id="t1", type="patrol", required_capabilities=["patrol"])]))
        await asyncio.sleep(0.05)
        holder = controller.engine.assignments["t1"]
        other = "g1_b" if holder == "g1_a" else "g1_a"
        await controller.run_op(StructuredOp("sleep", {"robot": other}))  # remove candidate
        await asyncio.sleep(0.05)
        await controller.run_op(StructuredOp("sleep", {"robot": holder}))
        await asyncio.sleep(0.05)
        assert "t1" in controller.engine.needs_operator
        assert holder not in controller.engine.robot_task
    finally:
        for ag in agents:
            await ag.stop()
