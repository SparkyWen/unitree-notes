"""LiveExecutor choreography ops: circle (timed), face (until aligned),
arms_up (one-shot trigger + timed), hold (timed). Driven against a fake world +
an injected clock so timing is deterministic and instant (no real waiting)."""
import math

from g1_brain.fleet.coordinator.fleet_plan import Coordination, FleetPlan
from g1_brain.fleet.sim.live_executor import LiveExecutor
from g1_brain.fleet.coordinator.fleet_plan import SubAgentOp


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class ChoreoFakeWorld:
    def __init__(self, poses):
        self._pose = dict(poses)             # rid -> (x, y, yaw)
        self.circle_calls = []
        self.face_calls = []
        self.idle_calls = []
        self.arms_calls = []

    def set_circle(self, rid, direction="ccw"):
        self.circle_calls.append((rid, direction))

    def set_face(self, rid, x, y):
        self.face_calls.append((rid, x, y))

    def set_idle(self, rid):
        self.idle_calls.append(rid)

    def set_arms_up(self, rid, up=True):
        self.arms_calls.append((rid, up))

    def set_nav_goal(self, rid, x, y):
        pass

    def set_posture(self, rid, posture):
        pass

    def set_yaw(self, rid, yaw):
        x, y, _ = self._pose[rid]
        self._pose[rid] = (x, y, yaw)

    def telemetry(self):
        return {rid: {"pose": p, "neighbors": [], "posture": "ACTIVE",
                      "activity": "x", "gz": -1.0}
                for rid, p in self._pose.items()}


def _plan(summary="x"):
    return FleetPlan(summary=summary, coordination=Coordination(type="none"))


def test_circle_op_runs_for_duration_then_stops():
    world = ChoreoFakeWorld({"g1_a": (0.0, 0.0, 0.0)})
    clock = FakeClock()
    ex = LiveExecutor(world, clock=clock.now)
    m = ex.submit(_plan("circle"),
                  {"g1_a": [SubAgentOp(op="circle", args={"dir": "ccw", "seconds": 30})]})
    ex.step()
    assert world.circle_calls[-1] == ("g1_a", "ccw")
    assert not m.complete                       # still circling
    clock.advance(31)
    ex.step()
    assert m.complete                           # duration elapsed -> done
    assert world.idle_calls[-1] == "g1_a"       # and it stopped circling


def test_face_op_completes_when_heading_aligned():
    # g1_a at (0,-0.6) facing +x (yaw 0); target is due north -> wants yaw +90°
    world = ChoreoFakeWorld({"g1_a": (0.0, -0.6, 0.0)})
    ex = LiveExecutor(world, clock=FakeClock().now)
    m = ex.submit(_plan("face"),
                  {"g1_a": [SubAgentOp(op="face", args={"x": 0.0, "y": 0.6})]})
    ex.step()
    assert world.face_calls[-1] == ("g1_a", 0.0, 0.6)
    assert not m.complete                       # yaw 0, not yet facing north
    world.set_yaw("g1_a", math.pi / 2)          # now facing the target
    ex.step()
    assert m.complete


def test_arms_up_settles_then_triggers_once_then_completes():
    world = ChoreoFakeWorld({"g1_a": (0.0, 0.0, 0.0)})
    clock = FakeClock()
    ex = LiveExecutor(world, clock=clock.now)
    m = ex.submit(_plan("arms"),
                  {"g1_a": [SubAgentOp(op="arms_up", args={"seconds": 2.0})]})
    ex.step()                                   # t=0: settle, not raised yet
    assert world.arms_calls == []
    assert world.idle_calls[-1] == "g1_a"       # it stops/settles first
    clock.advance(1.6); ex.step()               # past the settle -> raise
    clock.advance(0.5); ex.step()               # still only one gesture queued
    assert world.arms_calls == [("g1_a", True)]
    assert not m.complete
    clock.advance(2.0); ex.step()               # settle + hold elapsed -> done
    assert m.complete


def test_hold_op_waits_then_completes():
    world = ChoreoFakeWorld({"g1_a": (0.0, 0.0, 0.0)})
    clock = FakeClock()
    ex = LiveExecutor(world, clock=clock.now)
    m = ex.submit(_plan("hold"),
                  {"g1_a": [SubAgentOp(op="hold", args={"seconds": 5})]})
    ex.step()
    assert not m.complete
    clock.advance(6)
    ex.step()
    assert m.complete
