"""FleetWorldModel seam. Identity now; shared-frame fusion is a later slice."""
from __future__ import annotations

from typing import Dict, List, Protocol


class FleetWorldModel(Protocol):
    def to_global(self, robot_id: str, pose: dict) -> dict: ...
    def fuse_detections(self, per_robot: Dict[str, dict]) -> List[dict]: ...


class IdentityWorldModel:
    """Each robot lives in its own frame; no cross-robot fusion."""
    def to_global(self, robot_id: str, pose: dict) -> dict:
        return pose

    def fuse_detections(self, per_robot: Dict[str, dict]) -> List[dict]:
        return [{"robot_id": rid, **snap} for rid, snap in per_robot.items()]
