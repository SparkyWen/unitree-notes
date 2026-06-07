"""MotionBackend protocol + the Posture vocabulary.

A Posture is the *physical intent* the LocalPlanner asks the backend to hold.
Every backend (mock / elastic-PD / RL) must map all postures, but how visibly
they differ depends on the backend.
"""
from __future__ import annotations

import enum
from typing import List, Protocol, runtime_checkable


class Posture(str, enum.Enum):
    ACTIVE = "ACTIVE"   # available, balanced, idle stance
    PATROL = "PATROL"   # performing a patrol task (visible periodic motion)
    SLEEP = "SLEEP"     # safe quiescent / damped posture (DORMANT)
    WAKE = "WAKE"       # transition back to stand from sleep
    IDLE = "IDLE"       # quiet stand, no task
    STOP = "STOP"       # zero motion
    WALK = "WALK"       # navigating to a waypoint (RL gait, nonzero velocity cmd)


@runtime_checkable
class Lowstate(Protocol):
    def tau_est(self) -> List[float]: ...
    @property
    def gravity_proj_z(self) -> float: ...


@runtime_checkable
class MotionBackend(Protocol):
    def set_posture(self, posture: Posture) -> None: ...
    def step(self) -> None: ...
    def read_lowstate(self) -> Lowstate: ...
    def close(self) -> None: ...
