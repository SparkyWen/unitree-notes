"""In-memory fleet registry + staleness. Persistence not needed read-only slice."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from g1_brain.fleet.contracts.models import CapabilityDescriptor, RobotStateMsg


@dataclass
class _Entry:
    cap: CapabilityDescriptor
    last_state: Optional[RobotStateMsg] = None
    last_seen: float = 0.0
    last_seq: int = -1


class FleetRegistry:
    def __init__(self, *, stale_after_s: float = 5.0, offline_after_s: float = 15.0,
                 now: Callable[[], float] = time.monotonic):
        self._stale = stale_after_s
        self._offline = offline_after_s
        self._now = now
        self._robots: Dict[str, _Entry] = {}

    def register(self, cap: CapabilityDescriptor) -> None:
        e = self._robots.get(cap.robot_id)
        if e is None:
            self._robots[cap.robot_id] = _Entry(cap=cap, last_seen=self._now())
        else:
            e.cap = cap
            e.last_seen = self._now()

    def on_heartbeat(self, st: RobotStateMsg) -> None:
        e = self._robots.get(st.robot_id)
        if e is None:
            return  # heartbeat before register: ignore until registered
        if st.seq < e.last_seq:
            return  # out of order
        e.last_seq = st.seq
        e.last_state = st
        e.last_seen = self._now()

    def status(self, robot_id: str) -> str:
        e = self._robots.get(robot_id)
        if e is None:
            return "unknown"
        age = self._now() - e.last_seen
        if age >= self._offline:
            return "offline"
        if age >= self._stale:
            return "stale"
        return "online"

    def latest_state(self, robot_id: str) -> Optional[RobotStateMsg]:
        e = self._robots.get(robot_id)
        return e.last_state if e else None

    def list_robots(self) -> List[dict]:
        out = []
        for rid, e in self._robots.items():
            out.append({
                "robot_id": rid,
                "status": self.status(rid),
                "capabilities": [c.name for c in e.cap.capabilities],
                "state": e.last_state.model_dump(mode="json") if e.last_state else None,
            })
        return out
