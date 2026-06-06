from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel
from g1_brain.fleet.contracts.models import RobotEvent, EventType


def _snap(robot, clear_path, persons):
    return RobotEvent.make(robot_id=robot, type=EventType.SCENE_SNAPSHOT, ts="t",
                           payload={"clear_path": clear_path, "persons_visible": persons,
                                    "nearest_person_m": 0.5 if persons else None})


def test_latest_snapshot_per_robot():
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    agg.ingest(_snap("r1", True, 0))
    agg.ingest(_snap("r1", False, 1))  # newer wins
    assert agg.latest("r1")["clear_path"] is False


def test_rollup_counts():
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    agg.ingest(_snap("r1", False, 1))
    agg.ingest(_snap("r2", True, 0))
    agg.ingest(_snap("r3", False, 2))
    roll = agg.rollup()
    assert roll["robots_path_blocked"] == 2
    assert roll["robots_with_humans"] == 2
    assert roll["robot_count"] == 3


def test_non_scene_events_ignored():
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    ev = RobotEvent.make(robot_id="r1", type=EventType.ACTION_RESULT, ts="t", payload={})
    agg.ingest(ev)
    assert agg.latest("r1") is None
