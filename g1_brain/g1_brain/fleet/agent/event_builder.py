"""Build compact, semantic RobotEvents from a SceneState snapshot.

Doc principle: the center receives semantic events, never raw video/point clouds.
"""
from __future__ import annotations

import math
from typing import List

from g1_brain.scene_state.types import SceneState
from g1_brain.fleet.clock import iso_now as _iso_now
from g1_brain.fleet.contracts.models import EventType, RobotEvent


def build_perception_events(
    robot_id: str, scene: SceneState, *,
    person_thresh_m: float = 0.8, obstacle_thresh_m: float = 0.6,
) -> List[RobotEvent]:
    ts = _iso_now()
    summary = scene.summary_for_llm()
    events = [RobotEvent.make(robot_id=robot_id, type=EventType.SCENE_SNAPSHOT,
                              ts=ts, payload=summary)]
    g = scene.ground
    if g is not None:
        if math.isfinite(g.nearest_person_m) and g.nearest_person_m <= person_thresh_m:
            events.append(RobotEvent.make(
                robot_id=robot_id, type=EventType.HUMAN_DETECTED, ts=ts,
                payload={"nearest_person_m": round(g.nearest_person_m, 2)}))
        if (not g.clear_path) or (
            math.isfinite(g.nearest_obstacle_m) and g.nearest_obstacle_m <= obstacle_thresh_m
        ):
            events.append(RobotEvent.make(
                robot_id=robot_id, type=EventType.OBSTACLE_DETECTED, ts=ts,
                payload={"nearest_obstacle_m": (round(g.nearest_obstacle_m, 2)
                         if math.isfinite(g.nearest_obstacle_m) else None),
                         "clear_path": g.clear_path}))
    return events
