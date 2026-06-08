from g1_brain.fleet.sim.live_executor import LiveExecutor
from g1_brain.fleet.coordinator.fleet_plan import FleetPlan, SubAgentOp, Coordination


class FakeWorld:
    def __init__(self):
        self.pose = {"g1_a": (0.0, 0.0, 0.0)}
        self.peer_avoid = {}
    def telemetry(self):
        return {"g1_a": {"pose": self.pose["g1_a"], "neighbors": []}}
    def set_nav_goal(self, rid, x, y): pass
    def set_face(self, rid, x, y): pass
    def set_idle(self, rid): pass
    def set_peer_avoid(self, rid, on): self.peer_avoid[rid] = on


def _exec_with(op):
    w = FakeWorld()
    ex = LiveExecutor(w)
    plan = FleetPlan(summary="t", coordination=Coordination(type="navigate"))
    ex.submit(plan, {"g1_a": [op]})
    ex.step()
    return w.peer_avoid["g1_a"]


def test_navigate_keeps_peer_avoid_on():
    assert _exec_with(SubAgentOp(op="navigate", args={"x": 2.0, "y": 0.0})) is True


def test_face_turns_peer_avoid_off():
    assert _exec_with(SubAgentOp(op="face", args={"x": 1.0, "y": 0.0})) is False
