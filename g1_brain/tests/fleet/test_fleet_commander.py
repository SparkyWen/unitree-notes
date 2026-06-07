from g1_brain.fleet.coordinator.fleet_commander import FleetCommander

SNAP = {"robots": [{"robot_id": "g1_a", "x": -1.5, "y": 0.0},
                   {"robot_id": "g1_b", "x": 1.5, "y": 0.0}]}


def test_rendezvous_intent_builds_two_goals():
    fc = FleetCommander(llm=None)
    plan = fc.plan("两个机器人到中间会合", SNAP)
    assert plan.coordination.type in ("rendezvous", "relay")
    assert {a.robot_id for a in plan.assignments} == {"g1_a", "g1_b"}
    assert all(a.goal is not None for a in plan.assignments)
    ga = next(a.goal for a in plan.assignments if a.robot_id == "g1_a")
    gb = next(a.goal for a in plan.assignments if a.robot_id == "g1_b")
    assert -1.0 < ga[0] < gb[0] < 1.0


def test_relay_intent_sets_handoff():
    fc = FleetCommander(llm=None)
    plan = fc.plan("让 g1_a 和 g1_b 会合，然后 a 把巡逻交给 b", SNAP)
    assert plan.coordination.type == "relay"
    assert plan.coordination.handoff_from == "g1_a"
    assert plan.coordination.handoff_to == "g1_b"
    assert plan.coordination.handoff_task == "patrol"


def test_unknown_intent_needs_clarification():
    fc = FleetCommander(llm=None)
    plan = fc.plan("make me a sandwich", SNAP)
    assert plan.needs_clarification


def test_validate_rejects_unknown_robot():
    fc = FleetCommander(llm=None)
    plan = fc.plan("rendezvous", SNAP)
    ok, _ = fc.validate(plan, known_ids={"g1_a", "g1_b"})
    assert ok
    plan.assignments[0].robot_id = "ghost"
    ok, reason = fc.validate(plan, known_ids={"g1_a", "g1_b"})
    assert not ok and "ghost" in reason
