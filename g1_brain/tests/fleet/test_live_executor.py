"""LiveExecutor — drives a plan's per-robot ops against a live world and lets a
new operator command *preempt* the running one (latest intent wins). Unit-tested
against a fast fake world (teleports toward goals) so we exercise the control
logic + preemption without 20 s of real physics."""
import math

from g1_brain.fleet.coordinator.fleet_plan import (
    Coordination, FleetPlan, RobotAssignment, SubAgentOp)
from g1_brain.fleet.sim.live_executor import LiveExecutor


class FakeWorld:
    """Minimal stand-in for WorldSim: moves each robot a fraction toward its
    last nav goal whenever tick() is called."""
    def __init__(self, poses):
        self._pose = {rid: (x, y, 0.0) for rid, (x, y) in poses.items()}
        self._goal = {}
        self._posture = {rid: "IDLE" for rid in poses}

    def set_nav_goal(self, rid, x, y):
        self._goal[rid] = (x, y)

    def set_posture(self, rid, posture):
        self._posture[rid] = getattr(posture, "value", str(posture))

    def telemetry(self):
        out = {}
        for rid, (x, y, yaw) in self._pose.items():
            nb = [{"peer": o, "dist": math.hypot(self._pose[o][0] - x,
                                                 self._pose[o][1] - y)}
                  for o in self._pose if o != rid]
            out[rid] = {"pose": (x, y, yaw), "neighbors": nb,
                        "posture": self._posture[rid], "gz": -1.0}
        return out

    def tick(self, frac=0.5):
        for rid, (gx, gy) in self._goal.items():
            x, y, yaw = self._pose[rid]
            self._pose[rid] = (x + (gx - x) * frac, y + (gy - y) * frac, yaw)


def _plan(summary, ctype, assigns):
    return FleetPlan(summary=summary, coordination=Coordination(type=ctype),
                     assignments=[RobotAssignment(robot_id=r, goal=g)
                                  for r, g in assigns])


def test_executor_completes_navigate_ops():
    world = FakeWorld({"g1_a": (-2.0, 0.0), "g1_b": (2.0, 0.0)})
    ex = LiveExecutor(world)
    plan = _plan("go", "none", [("g1_a", (0.0, 0.0)), ("g1_b", (0.6, 0.0))])
    ops = {"g1_a": [SubAgentOp(op="navigate", args={"x": 0.0, "y": 0.0})],
           "g1_b": [SubAgentOp(op="navigate", args={"x": 0.6, "y": 0.0})]}
    m = ex.submit(plan, ops)
    for _ in range(40):
        ex.step()
        world.tick()
        if m.complete:
            break
    assert m.complete
    assert world._goal["g1_a"] == (0.0, 0.0)


def test_new_command_preempts_running_mission():
    world = FakeWorld({"g1_a": (-2.0, 0.0)})
    ex = LiveExecutor(world)
    mA = ex.submit(_plan("A", "none", [("g1_a", (-1.0, 0.0))]),
                   {"g1_a": [SubAgentOp(op="navigate", args={"x": -1.0, "y": 0.0})]})
    ex.step(); world.tick()
    assert world._goal["g1_a"] == (-1.0, 0.0)

    # operator changes their mind mid-flight:
    mB = ex.submit(_plan("B", "none", [("g1_a", (3.0, 0.0))]),
                   {"g1_a": [SubAgentOp(op="navigate", args={"x": 3.0, "y": 0.0})]})
    assert mB.gen > mA.gen
    assert ex.mission is mB and ex.mission is not mA
    ex.step()
    assert world._goal["g1_a"] == (3.0, 0.0)        # now driving to the NEW goal

    for _ in range(40):
        ex.step(); world.tick()
        if mB.complete:
            break
    assert mB.complete
    assert not mA.complete                           # preempted mission never finished


def test_relay_sets_postures_after_barrier():
    world = FakeWorld({"g1_a": (-1.5, 0.0), "g1_b": (1.5, 0.0)})
    ex = LiveExecutor(world)
    coord = Coordination(type="relay", point=(0.0, 0.0), handoff_task="patrol",
                         handoff_from="g1_a", handoff_to="g1_b")
    plan = FleetPlan(summary="relay", coordination=coord,
                     assignments=[RobotAssignment(robot_id="g1_a", goal=(-0.4, 0.0)),
                                  RobotAssignment(robot_id="g1_b", goal=(0.4, 0.0))])
    ops = {
        "g1_a": [SubAgentOp(op="navigate", args={"x": -0.4, "y": 0.0}),
                 SubAgentOp(op="await_barrier", args={"point": [0.0, 0.0]}),
                 SubAgentOp(op="idle")],
        "g1_b": [SubAgentOp(op="navigate", args={"x": 0.4, "y": 0.0}),
                 SubAgentOp(op="await_barrier", args={"point": [0.0, 0.0]}),
                 SubAgentOp(op="patrol")],
    }
    m = ex.submit(plan, ops)
    for _ in range(60):
        ex.step(); world.tick()
        if m.complete:
            break
    assert m.complete
    assert world._posture["g1_b"] == "PATROL"
    assert world._posture["g1_a"] == "IDLE"
