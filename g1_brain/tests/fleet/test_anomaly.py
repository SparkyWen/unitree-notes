"""Deterministic AnomalyDetector over the FleetRegistry."""
from g1_brain.fleet.coordinator.anomaly import AnomalyDetector
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, CoreState, Battery, SafetyStateMsg,
)


def _state(rid="g1_a", temp=25.0, soc=0.9, gz=-1.0, motor=30.0, seq=1):
    return RobotStateMsg(
        robot_id=rid, ts="t", seq=seq, fsm_state="STANDING",
        core=CoreState(battery=Battery(soc=soc, temperature_c=temp),
                       safety_state=SafetyStateMsg(gravity_proj_z=gz)),
        extensions={"g1_sim": {"hottest_motor_c": motor}})


def _reg(state):
    reg = FleetRegistry()
    reg.register(CapabilityDescriptor(robot_id=state.robot_id,
                                      frame_id=f"{state.robot_id}/map"))
    reg.on_heartbeat(state)
    return reg


def test_no_anomaly_when_nominal():
    assert AnomalyDetector().scan(_reg(_state())) == []


def test_battery_overheat_detected():
    anoms = AnomalyDetector().scan(_reg(_state(temp=75.0)))
    a = [x for x in anoms if x.kind == "battery_overheat"]
    assert a and a[0].evidence["temperature_c"] == 75.0 and a[0].severity == "critical"


def test_motor_overheat_detected():
    anoms = AnomalyDetector(motor_hot_c=80.0).scan(_reg(_state(motor=85.0)))
    assert any(x.kind == "motor_overheat" for x in anoms)


def test_fall_detected():
    assert any(x.kind == "fall" for x in AnomalyDetector().scan(_reg(_state(gz=-0.2))))


def test_low_soc_detected():
    assert any(x.kind == "low_soc" for x in AnomalyDetector().scan(_reg(_state(soc=0.10))))


def test_hysteresis_edge_triggered():
    det = AnomalyDetector()
    reg = _reg(_state(temp=75.0))
    assert any(a.kind == "battery_overheat" for a in det.scan(reg))
    # still hot on the next scan -> not re-emitted
    assert not any(a.kind == "battery_overheat" for a in det.scan(reg))


def test_rearm_after_cooldown():
    det = AnomalyDetector(battery_hot_c=70.0, margin=3.0)
    reg = FleetRegistry()
    reg.register(CapabilityDescriptor(robot_id="g1_a", frame_id="x"))
    reg.on_heartbeat(_state(temp=75.0, seq=1))
    assert any(a.kind == "battery_overheat" for a in det.scan(reg))
    reg.on_heartbeat(_state(temp=60.0, seq=2))  # cool below hot-margin -> re-arm
    det.scan(reg)
    reg.on_heartbeat(_state(temp=75.0, seq=3))  # hot again
    assert any(a.kind == "battery_overheat" for a in det.scan(reg))


def test_stale_detected_when_offline():
    t = [1000.0]
    reg = FleetRegistry(now=lambda: t[0], stale_after_s=5.0, offline_after_s=15.0)
    reg.register(CapabilityDescriptor(robot_id="g1_a", frame_id="x"))
    reg.on_heartbeat(_state(seq=1))
    det = AnomalyDetector()
    assert det.scan(reg) == []          # online + nominal
    t[0] = 1100.0                        # 100 s later -> offline
    assert any(a.kind == "stale" for a in det.scan(reg))
