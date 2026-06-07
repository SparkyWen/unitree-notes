"""LocalPlanner: slow-brain capability -> posture/FSM mapping + lifecycle events."""
from g1_brain.fleet.agent.local_planner import LocalPlanner
from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.agent.motion.mock import MockBackend
from g1_brain.fleet.contracts.models import CommandEnvelope, EventType
from g1_brain.safety.state_machine import RobotFsm, RobotFsmState


def _planner(events, initial=RobotFsmState.STANDING):
    fsm = RobotFsm(initial=initial)
    backend = MockBackend(n_joints=2)
    planner = LocalPlanner(robot_id="g1_a", fsm=fsm, backend=backend, emit=events.append)
    return fsm, backend, planner


def _env(cap, **payload):
    return CommandEnvelope.make(issued_by="c", issued_to="g1_a", capability=cap,
                                payload=payload, trace_id="trace-1")


def test_sleep_sets_dormant_and_sleep_posture():
    events = []
    fsm, backend, planner = _planner(events)
    planner.apply(_env("sleep", reason="overheat"))
    assert fsm.state == RobotFsmState.DORMANT
    assert backend.last_posture == Posture.SLEEP
    ev = [e for e in events if e.type == EventType.ROBOT_SLEEPING]
    assert ev and ev[0].trace_id == "trace-1"


def test_sleep_from_acting_passes_through_standing():
    events = []
    fsm, backend, planner = _planner(events, initial=RobotFsmState.ACTING)
    planner.apply(_env("sleep"))
    assert fsm.state == RobotFsmState.DORMANT


def test_wake_from_dormant_restores_standing():
    events = []
    fsm, backend, planner = _planner(events, initial=RobotFsmState.DORMANT)
    planner.apply(_env("wake"))
    assert fsm.state == RobotFsmState.STANDING
    assert backend.last_posture == Posture.ACTIVE
    assert any(e.type == EventType.ROBOT_RESUMED for e in events)


def test_patrol_sets_posture_and_task_event():
    events = []
    fsm, backend, planner = _planner(events)
    planner.apply(_env("patrol", task_id="t1"))
    assert backend.last_posture == Posture.PATROL
    ta = [e for e in events if e.type == EventType.TASK_ASSIGNED]
    assert ta and ta[0].payload["task_id"] == "t1"


def test_resume_task_sets_patrol():
    events = []
    fsm, backend, planner = _planner(events)
    planner.apply(_env("resume_task", task_id="t9"))
    assert backend.last_posture == Posture.PATROL


def test_stop_and_idle():
    events = []
    fsm, backend, planner = _planner(events)
    planner.apply(_env("idle"))
    assert backend.last_posture == Posture.IDLE
    planner.apply(_env("stop"))
    assert backend.last_posture == Posture.STOP
