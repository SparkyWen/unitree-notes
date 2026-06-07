"""AdmissionGate: the robot's local final authority over coordinator commands."""
from g1_brain.fleet.agent.admission_gate import AdmissionGate
from g1_brain.fleet.agent.local_planner import LocalPlanner
from g1_brain.fleet.agent.motion.mock import MockBackend
from g1_brain.fleet.contracts.models import CommandEnvelope
from g1_brain.safety.state_machine import RobotFsm, RobotFsmState

_ALL = {"sleep", "wake", "patrol", "resume_task", "idle", "stop"}


def _gate(initial=RobotFsmState.STANDING, supported=None, now=1000.0):
    fsm = RobotFsm(initial=initial)
    backend = MockBackend(n_joints=2)
    events = []
    planner = LocalPlanner(robot_id="g1_a", fsm=fsm, backend=backend, emit=events.append)
    gate = AdmissionGate(robot_id="g1_a", fsm=fsm, planner=planner,
                         supported_capabilities=supported or set(_ALL),
                         clock=lambda: now)
    return fsm, backend, gate


def _env(cap, *, issued_now=1000.0, ttl=30.0, idem=None, **payload):
    return CommandEnvelope.make(issued_by="c", issued_to="g1_a", capability=cap,
                                payload=payload, ttl_s=ttl, idempotency_key=idem,
                                now=issued_now)


def test_accept_valid_sleep_applies_dormant():
    fsm, backend, gate = _gate()
    d = gate.admit(_env("sleep"))
    assert d.decision == "accepted" and d.reason_code == "OK"
    assert fsm.state == RobotFsmState.DORMANT


def test_refuse_expired():
    fsm, backend, gate = _gate(now=2000.0)
    d = gate.admit(_env("sleep", issued_now=1000.0, ttl=30.0))  # expires 1030 < 2000
    assert d.decision == "refused" and d.reason_code == "EXPIRED"
    assert fsm.state == RobotFsmState.STANDING  # not applied


def test_refuse_duplicate_idempotency():
    fsm, backend, gate = _gate()
    env = _env("idle", idem="cmd-key-1")
    assert gate.admit(env).decision == "accepted"
    env2 = _env("idle", idem="cmd-key-1")
    d = gate.admit(env2)
    assert d.decision == "refused" and d.reason_code == "DUPLICATE"


def test_refuse_unsupported_capability():
    fsm, backend, gate = _gate(supported={"sleep", "wake"})
    d = gate.admit(_env("patrol"))
    assert d.decision == "refused" and d.reason_code == "UNSUPPORTED_CAPABILITY"


def test_refuse_patrol_while_dormant():
    fsm, backend, gate = _gate(initial=RobotFsmState.DORMANT)
    d = gate.admit(_env("patrol"))
    assert d.decision == "refused" and d.reason_code == "FSM_FORBIDDEN"


def test_accept_wake_while_dormant():
    fsm, backend, gate = _gate(initial=RobotFsmState.DORMANT)
    d = gate.admit(_env("wake"))
    assert d.decision == "accepted"
    assert fsm.state == RobotFsmState.STANDING


def test_refuse_command_when_faulted():
    fsm, backend, gate = _gate(initial=RobotFsmState.FAULT)
    d = gate.admit(_env("sleep"))
    assert d.decision == "refused" and d.reason_code == "FSM_FORBIDDEN"
