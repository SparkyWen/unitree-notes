"""Aggregate N per-robot semantic scene snapshots + fleet roll-up."""
from __future__ import annotations

from typing import Dict, Optional

from g1_brain.fleet.contracts.models import RobotEvent, EventType
from g1_brain.fleet.coordinator.world_model import FleetWorldModel


class PerceptionAggregator:
    def __init__(self, *, world_model: FleetWorldModel):
        self._wm = world_model
        self._latest: Dict[str, dict] = {}

    def ingest(self, ev: RobotEvent) -> None:
        if ev.type != EventType.SCENE_SNAPSHOT:
            return
        self._latest[ev.robot_id] = ev.payload

    def latest(self, robot_id: str) -> Optional[dict]:
        return self._latest.get(robot_id)

    def rollup(self) -> dict:
        blocked = sum(1 for s in self._latest.values() if s.get("clear_path") is False)
        humans = sum(1 for s in self._latest.values() if (s.get("persons_visible") or 0) > 0)
        return {
            "robot_count": len(self._latest),
            "robots_path_blocked": blocked,
            "robots_with_humans": humans,
            "fused": self._wm.fuse_detections(self._latest),
        }
