"""FleetBus abstraction. The WS implementation (later tasks) satisfies this."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional, Protocol

from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent,
)


@dataclass
class EventFilter:
    robot_ids: Optional[List[str]] = None
    types: Optional[List[str]] = field(default=None)


class FleetBus(Protocol):
    async def register(self, cap: CapabilityDescriptor) -> None: ...
    async def heartbeat(self, st: RobotStateMsg) -> None: ...
    async def publish(self, ev: RobotEvent) -> None: ...
    def subscribe(self, flt: EventFilter) -> AsyncIterator[RobotEvent]: ...
