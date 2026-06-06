"""Tests for g1_brain.fleet.contracts.models typed contracts."""
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
    CommandEnvelope, TaskSpec, AdmissionDecision,
)


def test_capability_descriptor_roundtrip():
    cap = CapabilityDescriptor(
        robot_id="g1-sim-01",
        harness_version="0.1.0",
        frame_id="g1-sim-01/map",
        capabilities=[{"name": "walk", "risk_level": "medium", "params_schema": "walk.v1"}],
    )
    dumped = cap.model_dump_json()
    back = CapabilityDescriptor.model_validate_json(dumped)
    assert back == cap
    assert back.schema_version == "CapabilityDescriptor.v1"
    assert back.embodiment.type == "humanoid_g1"


def test_robot_state_msg_minimal():
    st = RobotStateMsg(robot_id="g1-sim-01", ts="2026-06-06T08:00:00Z", seq=1,
                       fsm_state="ENGAGED", motion_state="idle")
    assert st.schema_version == "RobotStateMsg.v1"
    assert st.core.safety_state.e_stop is False
    assert st.core.policy_active is False


def test_robot_event_hash_is_deterministic():
    ev1 = RobotEvent.make(robot_id="r", trace_id="t", type=EventType.SCENE_SNAPSHOT,
                          ts="2026-06-06T08:00:00Z", payload={"a": 1, "b": 2})
    ev2 = RobotEvent.make(robot_id="r", trace_id="t", type=EventType.SCENE_SNAPSHOT,
                          ts="2026-06-06T08:00:00Z", payload={"b": 2, "a": 1})
    assert ev1.payload_hash == ev2.payload_hash
    assert ev1.event_id != ev2.event_id


def test_reserved_contracts_are_marked():
    assert CommandEnvelope().status == "reserved"
    assert TaskSpec().status == "reserved"
    assert AdmissionDecision().status == "reserved"
