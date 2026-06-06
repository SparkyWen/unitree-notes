from g1_brain.scene_state.types import SceneState, GroundConstraint
from g1_brain.fleet.agent.event_builder import build_perception_events
from g1_brain.fleet.contracts.models import EventType


def _scene(nearest_person, nearest_obstacle, clear_path):
    s = SceneState()
    s.ground = GroundConstraint(clear_path=clear_path, nearest_obstacle_m=nearest_obstacle,
                                nearest_person_m=nearest_person, floor_visible_ratio=0.8,
                                surface_tilt_deg=2.0)
    return s


def test_always_emits_scene_snapshot_with_summary():
    evs = build_perception_events("r1", _scene(float("inf"), 3.0, True),
                                  person_thresh_m=0.8, obstacle_thresh_m=0.6)
    types = [e.type for e in evs]
    assert EventType.SCENE_SNAPSHOT in types
    snap = next(e for e in evs if e.type == EventType.SCENE_SNAPSHOT)
    assert snap.payload["clear_path"] is True
    assert snap.robot_id == "r1"


def test_emits_human_and_obstacle_when_thresholds_crossed():
    evs = build_perception_events("r1", _scene(0.5, 0.4, False),
                                  person_thresh_m=0.8, obstacle_thresh_m=0.6)
    types = {e.type for e in evs}
    assert EventType.HUMAN_DETECTED in types
    assert EventType.OBSTACLE_DETECTED in types


def test_no_threshold_events_when_clear():
    evs = build_perception_events("r1", _scene(float("inf"), 5.0, True),
                                  person_thresh_m=0.8, obstacle_thresh_m=0.6)
    types = {e.type for e in evs}
    assert EventType.HUMAN_DETECTED not in types
    assert EventType.OBSTACLE_DETECTED not in types
