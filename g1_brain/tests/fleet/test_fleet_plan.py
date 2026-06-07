from g1_brain.fleet.coordinator.fleet_plan import (
    FleetPlan, Coordination, RobotAssignment, SubAgentOp)


def test_fleetplan_roundtrip():
    p = FleetPlan(
        summary="meet in the middle then hand off patrol",
        coordination=Coordination(type="relay", point=(0.0, 0.0),
                                  handoff_task="patrol", handoff_from="g1_a", handoff_to="g1_b"),
        assignments=[RobotAssignment(robot_id="g1_a", role="hander", objective="go to centre", goal=(-0.4, 0.0)),
                     RobotAssignment(robot_id="g1_b", role="receiver", objective="go to centre", goal=(0.4, 0.0))],
        risk="low")
    d = p.model_dump()
    assert FleetPlan.model_validate(d).coordination.type == "relay"


def test_subagentop():
    op = SubAgentOp(op="navigate", args={"x": 1.0, "y": 2.0})
    assert op.op == "navigate" and op.args["x"] == 1.0
