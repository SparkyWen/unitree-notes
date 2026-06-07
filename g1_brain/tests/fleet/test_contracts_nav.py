from g1_brain.fleet.contracts.models import CommandEnvelope, Pose
from g1_brain.fleet.agent.motion.base import Posture


def test_navigate_capability_allowed():
    env = CommandEnvelope.make(issued_by="c", issued_to="g1_a",
                               capability="navigate", payload={"x": 1.0, "y": 2.0})
    assert env.capability == "navigate"


def test_walk_posture_exists():
    assert Posture.WALK.value == "WALK"


def test_pose_model():
    p = Pose(frame_id="g1_a/map", x=1.0, y=2.0, theta=0.5)
    assert (p.x, p.y, p.theta) == (1.0, 2.0, 0.5)
