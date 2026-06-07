"""MotionBackend for one robot in a SharedG1World, driven by the reused RL
controller + nav outer loop. Posture maps to velocity-command behaviour:

    ACTIVE/IDLE/STOP/SLEEP : zero velocity command (policy holds the stand)
    WALK / nav goal        : nav outer loop -> velocity command toward goal

SLEEP keeps the policy's standing balance (the velocity policy is not a
crouch); a dedicated damped-crouch SLEEP is a P2 refinement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.sim.nav import nav_command
from g1_brain.fleet.sim.rl_adapter import SharedWorldController


@dataclass
class _Lowstate:
    _tau: List[float]
    gravity_proj_z: float

    def tau_est(self) -> List[float]:
        return list(self._tau)


class RlSharedBackend:
    def __init__(self, world, rid: str):
        self.world = world
        self.rid = rid
        self.ctl = SharedWorldController(world, rid)
        self.last_posture: Posture = Posture.ACTIVE
        self._goal: Optional[Tuple[float, float]] = None
        self._last_tau = [0.0] * 29

    def set_posture(self, posture: Posture) -> None:
        self.last_posture = posture
        if posture in (Posture.ACTIVE, Posture.IDLE, Posture.STOP, Posture.SLEEP):
            self._goal = None
            self.ctl.set_command(0.0, 0.0, 0.0)

    def set_nav_goal(self, x: float, y: float) -> None:
        self._goal = (x, y)
        self.last_posture = Posture.WALK

    def step(self) -> None:
        if self._goal is not None:
            vx, vy, wz = nav_command(self.world.base_pose(self.rid), self._goal)
            if (vx, vy, wz) == (0.0, 0.0, 0.0):
                self.last_posture = Posture.ACTIVE
                self._goal = None
            else:
                self.last_posture = Posture.WALK
            self.ctl.set_command(vx, vy, wz)
        q_target, kp, kd = self.ctl.compute()
        self.world.set_pd(self.rid, q_target, kp, kd)
        q, dq = self.world.joint_state(self.rid)
        self._last_tau = list(np.abs(kp * (q_target - q) - kd * dq))

    def read_lowstate(self) -> _Lowstate:
        return _Lowstate(_tau=self._last_tau,
                         gravity_proj_z=self.world.gravity_proj_z(self.rid))

    def close(self) -> None:
        pass
