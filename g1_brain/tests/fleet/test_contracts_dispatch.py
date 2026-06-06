"""Tests for the promoted command/task contracts + battery/health telemetry."""
from g1_brain.fleet.contracts.models import (
    CommandEnvelope, AdmissionDecision, TaskSpec, Mission, ReplanProposal,
    Lease, SafetyEnvelope, Battery, Health, CoreState, EventType,
)


def test_command_envelope_make_sets_hash_and_ids():
    env = CommandEnvelope.make(
        issued_by="coord", issued_to="g1_a", capability="sleep",
        payload={"reason": "overheat"}, ttl_s=30.0, trace_id="t1",
    )
    assert env.command_id
    assert env.idempotency_key
    assert env.expires_at > env.issued_at_epoch
    assert env.payload_hash.startswith("sha256:")
    assert env.capability == "sleep"
    assert env.issued_to == "g1_a"
    j = env.model_dump(mode="json")
    assert CommandEnvelope.model_validate(j) == env


def test_command_envelope_idempotency_key_defaults_to_command_id():
    env = CommandEnvelope.make(issued_by="c", issued_to="r", capability="wake", payload={})
    assert env.idempotency_key == env.command_id


def test_command_envelope_explicit_idempotency_key_preserved():
    env = CommandEnvelope.make(issued_by="c", issued_to="r", capability="patrol",
                               payload={}, idempotency_key="mission-1-task-1")
    assert env.idempotency_key == "mission-1-task-1"


def test_admission_decision_roundtrip():
    d = AdmissionDecision(command_id="c1", robot_id="g1_a", decision="refused",
                          reason_code="EXPIRED", reason_detail="ttl",
                          ts="2026-06-06T00:00:00Z")
    assert AdmissionDecision.model_validate(d.model_dump(mode="json")) == d


def test_core_state_has_battery_health():
    cs = CoreState(battery=Battery(soc=0.4, temperature_c=72.0, charging=False),
                   health=Health(level="warning", faults=["battery_hot"]))
    assert cs.battery.temperature_c == 72.0
    assert "battery_hot" in cs.health.faults
    # roundtrip
    assert CoreState.model_validate(cs.model_dump(mode="json")) == cs


def test_core_state_defaults_health_ok_no_battery():
    cs = CoreState()
    assert cs.battery is None
    assert cs.health.level == "ok"
    assert cs.health.faults == []


def test_task_and_mission_roundtrip():
    t = TaskSpec(task_id="task-1", mission_id="m-1", type="patrol",
                 required_capabilities=["patrol"], params={"zone": "A"},
                 success_criteria=["patrol_started"], cancel_policy={"on_network_loss": "safe_pause"})
    m = Mission(mission_id="m-1", created_by="op:li", intent_text="patrol zone A",
                priority="normal", tasks=[t])
    assert Mission.model_validate(m.model_dump(mode="json")) == m
    assert m.tasks[0].type == "patrol"


def test_lease_and_safety_envelope_on_command():
    env = CommandEnvelope.make(
        issued_by="c", issued_to="r", capability="patrol", payload={},
        lease=Lease(lease_id="l1", heartbeat_interval_s=2.0, ttl_s=30.0, on_expire="safe_pause"),
        safety_envelope=SafetyEnvelope(max_speed_mps=0.3, allowed_capabilities=["patrol", "stop"]),
    )
    assert env.lease.on_expire == "safe_pause"
    assert env.safety_envelope.max_speed_mps == 0.3


def test_replan_proposal_roundtrip():
    p = ReplanProposal(trigger="battery_overheat",
                       evidence=[{"event": "battery 75C"}],
                       actions=[{"sleep": "g1_a"}, {"reassign": "task-1"}],
                       risk_level="low", requires_human_approval=False,
                       explanation="A overheating; B has slack")
    assert ReplanProposal.model_validate(p.model_dump(mode="json")) == p


def test_new_event_types_exist():
    expected = ["anomaly_detected", "command_issued", "command_accepted",
                "command_refused", "task_assigned", "task_reassigned",
                "robot_sleeping", "robot_resumed", "lease_expired"]
    values = {e.value for e in EventType}
    for n in expected:
        assert n in values, f"missing EventType {n}"
