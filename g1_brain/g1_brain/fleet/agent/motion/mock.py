"""CI motion backend: no MuJoCo/DDS. Synthesizes LowState-like telemetry whose
joint effort depends on the requested posture, so the thermal model and anomaly
detector can be exercised deterministically."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from g1_brain.fleet.agent.motion.base import Posture

# Nominal per-joint effort by posture (arbitrary units consistent with tau_est).
_POSTURE_TAU = {
    Posture.ACTIVE: 6.0,
    Posture.PATROL: 14.0,
    Posture.WAKE: 10.0,
    Posture.IDLE: 4.0,
    Posture.SLEEP: 1.0,
    Posture.STOP: 0.5,
}


@dataclass
class MockLowstate:
    _tau: List[float]
    gravity_proj_z: float

    def tau_est(self) -> List[float]:
        return list(self._tau)


class MockBackend:
    def __init__(self, *, n_joints: int = 29, gravity_proj_z: float = -1.0):
        self._n = n_joints
        self._g = gravity_proj_z
        self.last_posture: Posture = Posture.IDLE
        self._load_override: Optional[float] = None

    def set_posture(self, posture: Posture) -> None:
        self.last_posture = posture

    def set_load(self, tau: float) -> None:
        """Force the per-joint effort (test hook to drive the thermal model)."""
        self._load_override = float(tau)

    def step(self) -> None:  # no physics to advance
        pass

    def read_lowstate(self) -> MockLowstate:
        tau = (self._load_override if self._load_override is not None
               else _POSTURE_TAU.get(self.last_posture, 5.0))
        return MockLowstate(_tau=[tau] * self._n, gravity_proj_z=self._g)

    def close(self) -> None:
        pass
