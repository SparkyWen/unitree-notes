"""DispatchEngine: capability/health task allocation + sleep/reassign on anomaly."""
from g1_brain.fleet.coordinator.anomaly import Anomaly
from g1_brain.fleet.coordinator.dispatch import DispatchEngine
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.agent.sim_harness import DISPATCH_CAPABILITIES
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, CapabilityEntry, RobotStateMsg, CoreState, Battery,
    Health, SafetyStateMsg, TaskSpec,
)


def _state(rid, *, fsm="STANDING", soc=0.9, temp=25.0, health="ok", seq=1):
    return RobotStateMsg(
        robot_id=rid, ts="t", seq=seq, fsm_state=fsm,
        core=CoreState(battery=Battery(soc=soc, temperature_c=temp),
                       health=Health(level=health),
                       safety_state=SafetyStateMsg()))


def _reg(*robots):
    """robots: list of (rid, state_kwargs)."""
    reg = FleetRegistry()
    for rid, kw in robots:
        reg.register(CapabilityDescriptor(
            robot_id=rid, frame_id=f"{rid}/map",
            capabilities=[CapabilityEntry(name=c) for c in DISPATCH_CAPABILITIES]))
        reg.on_heartbeat(_state(rid, **kw))
    return reg


def _task(tid="t1"):
    return TaskSpec(task_id=tid, type="patrol", required_capabilities=["patrol"])


def test_assign_picks_healthy_robot_highest_soc():
    reg = _reg(("g1_a", {"soc": 0.5}), ("g1_b", {"soc": 0.9}))
    eng = DispatchEngine(reg)
    cmd = eng.assign(_task("t1"))
    assert cmd is not None and cmd.issued_to == "g1_b"  # higher SOC wins
    assert cmd.capability == "patrol"
    assert eng.assignments["t1"] == "g1_b"


def test_assign_skips_dormant_and_unhealthy_and_offline():
    reg = _reg(("g1_a", {"fsm": "DORMANT"}), ("g1_b", {"health": "warning"}))
    eng = DispatchEngine(reg)
    assert eng.assign(_task("t1")) is None
    assert "t1" in eng.needs_operator


def test_handle_anomaly_sleeps_and_reassigns():
    reg = _reg(("g1_a", {"soc": 0.9}), ("g1_b", {"soc": 0.8}))
    eng = DispatchEngine(reg)
    eng.assign(_task("t1"))  # -> g1_a (higher soc)
    assert eng.assignments["t1"] == "g1_a"

    plan = eng.handle_anomaly(Anomaly(robot_id="g1_a", kind="battery_overheat",
                                      severity="critical", evidence={"temperature_c": 75}))
    caps = [(c.capability, c.issued_to) for c in plan]
    assert ("sleep", "g1_a") in caps
    assert ("resume_task", "g1_b") in caps
    assert eng.assignments["t1"] == "g1_b"
    assert "g1_a" not in eng.robot_task


def test_handle_anomaly_no_candidate_holds_task():
    reg = _reg(("g1_a", {"soc": 0.9}))  # only one robot
    eng = DispatchEngine(reg)
    eng.assign(_task("t1"))
    plan = eng.handle_anomaly(Anomaly(robot_id="g1_a", kind="battery_overheat",
                                      severity="critical", evidence={}))
    assert [c.capability for c in plan] == ["sleep"]
    assert "t1" in eng.needs_operator


def test_takeover_moves_task():
    reg = _reg(("g1_a", {}), ("g1_b", {}))
    eng = DispatchEngine(reg)
    eng.assign(_task("t1"))  # -> some robot
    holder = eng.assignments["t1"]
    other = "g1_b" if holder == "g1_a" else "g1_a"
    plan = eng.takeover(holder, other)
    assert eng.assignments["t1"] == other
    assert any(c.capability == "resume_task" and c.issued_to == other for c in plan)


def test_sleep_and_wake_helpers():
    reg = _reg(("g1_a", {}))
    eng = DispatchEngine(reg)
    s = eng.sleep("g1_a")
    assert s.capability == "sleep" and s.issued_to == "g1_a"
    w = eng.wake("g1_a")
    assert w.capability == "wake" and w.issued_to == "g1_a"
