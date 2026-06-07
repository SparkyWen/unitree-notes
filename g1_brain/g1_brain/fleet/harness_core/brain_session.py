"""OperatorBrainSession — attachable fast/slow brain interface (this slice: stub).

The voice app attaches a concrete session to a local HarnessCore. Multi-robot
focus switching is a later slice; here we only fix the interface.
"""
from __future__ import annotations

from typing import Protocol


class OperatorBrainSession(Protocol):
    async def attach(self, core: "object") -> None: ...
    async def detach(self) -> None: ...
