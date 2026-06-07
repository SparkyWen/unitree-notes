"""Deterministic rendezvous barrier: cooperation timing is NOT left to the LLM.
A handoff step is released only once every participant has arrived (marked
explicitly, or detected within `radius` of the meeting point from telemetry)."""
from __future__ import annotations

import math
from typing import Optional, Set, Tuple


class RendezvousBarrier:
    def __init__(self, participants: Set[str], *,
                 point: Optional[Tuple[float, float]] = None, radius: float = 0.6):
        self.participants = set(participants)
        self.point = point
        self.radius = radius
        self._arrived: Set[str] = set()

    def mark_arrived(self, robot_id: str) -> None:
        if robot_id in self.participants:
            self._arrived.add(robot_id)

    def update_position(self, robot_id: str, xy: Tuple[float, float]) -> None:
        if self.point is None or robot_id not in self.participants:
            return
        if math.hypot(xy[0] - self.point[0], xy[1] - self.point[1]) <= self.radius:
            self._arrived.add(robot_id)

    def arrived(self) -> Set[str]:
        return set(self._arrived)

    def is_released(self) -> bool:
        return self.participants.issubset(self._arrived)
