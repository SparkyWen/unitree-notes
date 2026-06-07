from g1_brain.fleet.contracts.capability_export import build_capability_descriptor


def test_descriptor_covers_real_tool_catalog():
    cap = build_capability_descriptor(robot_id="g1-sim-02", harness_version="9.9.9")
    names = {c.name for c in cap.capabilities}
    assert {"walk", "turn", "gesture", "say", "ask_slow_brain"} <= names
    assert "loco_high" not in names
    assert cap.robot_id == "g1-sim-02"
    assert cap.harness_version == "9.9.9"


def test_risk_levels_assigned():
    cap = build_capability_descriptor(robot_id="r")
    by_name = {c.name: c.risk_level for c in cap.capabilities}
    assert by_name["walk"] == "medium"
    assert by_name["gesture"] == "low"
    assert by_name["say"] == "none"
