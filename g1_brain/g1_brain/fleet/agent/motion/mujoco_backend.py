"""MotionBackend backed by a headless MujocoG1 (real physics, direct coupling).

Maps each Posture to joint PD targets so the dispatch outcomes are physically
visible and produce a distinct real joint-effort (tau) signature:

    ACTIVE/IDLE/WAKE/STOP : hold trained default stand
    PATROL                : default stand + periodic elbow wave (higher effort)
    SLEEP                 : crouch/tuck at low stiffness (damped, low effort)

Joint indices follow the G1 29-DoF order (legs, waist, left arm, right arm).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.sim.mujoco_world import MujocoG1

# 29-DoF joint indices of interest.
_KNEE_L, _KNEE_R = 3, 9
_HIP_PITCH_L, _HIP_PITCH_R = 0, 6
_SH_PITCH_L, _SH_PITCH_R = 15, 22
_ELBOW_L, _ELBOW_R = 18, 25


@dataclass
class _Lowstate:
    _tau: List[float]
    gravity_proj_z: float

    def tau_est(self) -> List[float]:
        return list(self._tau)


class MujocoBackend:
    def __init__(self, world: MujocoG1, *, steps_per_tick: int = 10):
        self._w = world
        self._steps = steps_per_tick
        self._phase = 0.0
        self.last_posture: Posture = Posture.ACTIVE
        self.set_posture(Posture.ACTIVE)

    def set_posture(self, posture: Posture) -> None:
        self.last_posture = posture
        q = self._w.q_def.copy()
        if posture == Posture.SLEEP:
            # crouch + tuck arms, low stiffness = visibly damped, low effort
            q[_KNEE_L] += 0.8
            q[_KNEE_R] += 0.8
            q[_HIP_PITCH_L] -= 0.5
            q[_HIP_PITCH_R] -= 0.5
            q[_SH_PITCH_L] = 0.0
            q[_SH_PITCH_R] = 0.0
            q[_ELBOW_L] = 0.2
            q[_ELBOW_R] = 0.2
            self._w.set_targets(q, kp_scale=0.35)
        else:
            self._w.set_targets(q, kp_scale=1.0)

    def step(self) -> None:
        if self.last_posture == Posture.PATROL:
            self._phase += 0.15
            q = self._w.q_def.copy()
            wave = 0.5 * math.sin(self._phase)
            q[_ELBOW_L] += wave
            q[_ELBOW_R] += wave
            self._w.set_targets(q, kp_scale=1.0)
        self._w.step(self._steps)

    def read_lowstate(self) -> _Lowstate:
        return _Lowstate(_tau=self._w.tau_est(), gravity_proj_z=self._w.gravity_proj_z())

    def close(self) -> None:
        pass
