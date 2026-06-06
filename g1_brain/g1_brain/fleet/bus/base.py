"""FleetBus abstraction. The WS implementation (later tasks) satisfies this."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    AsyncIterator, Awaitable, Callable, List, Optional, Protocol,
)

from g1_brain.fleet.contracts.models import (
    AdmissionDecision, CapabilityDescriptor, CommandEnvelope, RobotStateMsg,
    RobotEvent,
)


@dataclass
class EventFilter:
    robot_ids: Optional[List[str]] = None
    types: Optional[List[str]] = field(default=None)


# Robot-side callback the bus invokes when a down-bound COMMAND arrives.
OnCommand = Callable[[CommandEnvelope], Awaitable[Optional[AdmissionDecision]]]


class FleetBus(Protocol):
    """Robot-side telemetry bus + down-bound command intake seam.

    ``on_command`` is an attribute (not a method) set by the RobotAgent; the
    transport calls it for each inbound CommandEnvelope and returns the
    resulting AdmissionDecision back to the coordinator.
    """
    on_command: Optional[OnCommand]

    async def register(self, cap: CapabilityDescriptor) -> None: ...
    async def heartbeat(self, st: RobotStateMsg) -> None: ...
    async def publish(self, ev: RobotEvent) -> None: ...
    def subscribe(self, flt: EventFilter) -> AsyncIterator[RobotEvent]: ...


class CommandTransport(Protocol):
    """Coordinator-side seam: deliver a command to a connected robot."""
    async def send_command(self, robot_id: str, env: CommandEnvelope) -> None: ...
