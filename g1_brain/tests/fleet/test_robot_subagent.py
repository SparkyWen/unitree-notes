from g1_brain.fleet.coordinator.fleet_plan import Coordination, RobotAssignment
from g1_brain.fleet.coordinator.robot_subagent import RobotSubAgent


def _coord():
    return Coordination(type="relay", point=(0.0, 0.0), handoff_task="patrol",
                        handoff_from="g1_a", handoff_to="g1_b")


def test_receiver_navigates_waits_then_patrols():
    sa = RobotSubAgent("g1_b", llm=None)
    ops = sa.plan_ops(RobotAssignment(robot_id="g1_b", goal=(0.4, 0.0)), _coord())
    kinds = [o.op for o in ops]
    assert kinds == ["navigate", "await_barrier", "patrol"]
    assert ops[0].args == {"x": 0.4, "y": 0.0}


def test_hander_navigates_waits_then_idles():
    sa = RobotSubAgent("g1_a", llm=None)
    ops = sa.plan_ops(RobotAssignment(robot_id="g1_a", goal=(-0.4, 0.0)), _coord())
    assert [o.op for o in ops] == ["navigate", "await_barrier", "idle"]


def test_plain_rendezvous_just_navigates_and_waits():
    sa = RobotSubAgent("g1_a", llm=None)
    c = Coordination(type="rendezvous", point=(0.0, 0.0))
    ops = sa.plan_ops(RobotAssignment(robot_id="g1_a", goal=(-0.4, 0.0)), c)
    assert [o.op for o in ops] == ["navigate", "await_barrier"]
