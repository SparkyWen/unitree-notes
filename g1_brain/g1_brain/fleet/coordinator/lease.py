"""LeaseManager — TTL leases with heartbeat renewal.

A robot under dispatch holds a lease; if the coordinator stops hearing from it
the lease expires and the DispatchController drives an on_expire action
(safe_pause/sleep). This is the network-partition safety valve (doc §11.2):
authority is time-bounded, not assumed-forever.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List


@dataclass
class LeaseRecord:
    lease_id: str
    robot_id: str
    expiry: float
    ttl_s: float


class LeaseManager:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._leases: Dict[str, LeaseRecord] = {}
        self._counter = 0

    def grant(self, robot_id: str, *, ttl_s: float = 30.0) -> str:
        self._counter += 1
        lid = f"lease-{self._counter}"
        self._leases[lid] = LeaseRecord(lid, robot_id, self._clock() + ttl_s, ttl_s)
        return lid

    def heartbeat(self, lease_id: str) -> bool:
        rec = self._leases.get(lease_id)
        if rec is None:
            return False
        rec.expiry = self._clock() + rec.ttl_s
        return True

    def tick(self) -> List[LeaseRecord]:
        now = self._clock()
        expired = [r for r in self._leases.values() if now > r.expiry]
        for r in expired:
            self._leases.pop(r.lease_id, None)
        return expired

    def active(self) -> List[LeaseRecord]:
        return list(self._leases.values())
