"""MotionBackend for one robot in a SharedG1World, driven by the reused RL
controller + nav outer loop. A motion *mode* maps to a velocity command:

    idle   : zero velocity command (policy holds the stand)
    walk   : nav outer loop -> velocity command toward an (x,y) goal
    circle : fixed forward + yaw rate, sign = direction (cw / ccw)
    face   : turn in place until heading points at an (x,y) target

Plus an optional arm override (e.g. "raise both arms") layered on top of the
policy's legs/balance. SLEEP keeps the policy's standing balance (the velocity
policy is not a crouch)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.sim.nav import nav_command
from g1_brain.fleet.sim.rl_adapter import SharedWorldController

_CIRCLE_V = 0.15   # forward speed during a circle (m/s)
_CIRCLE_W = 0.6    # yaw rate magnitude during a circle (rad/s) -> ~0.25 m radius
_FACE_KYAW = 1.5   # P gain turning toward a face target
_FACE_TOL = 0.12   # rad: "facing" once heading error is within this
_ARM_RAISE_S = 2.0   # eased blend time to raise arms (slow enough to stay balanced)
_ARM_HOLD_S = 30.0   # hold arms up this long before they'd ease back
_ARM_LOWER_S = 1.5   # eased blend time to lower arms back to rest


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
        self.activity: str = "idle"       # human-readable status for telemetry
        self._mode: str = "idle"          # idle | walk | circle | face
        self._goal: Optional[Tuple[float, float]] = None
        self._circle_dir: str = "ccw"
        self._face_target: Optional[Tuple[float, float]] = None
        self._last_tau = [0.0] * 29

    def set_posture(self, posture: Posture) -> None:
        self.last_posture = posture
        if posture in (Posture.ACTIVE, Posture.IDLE, Posture.STOP, Posture.SLEEP):
            self._mode = "idle"
            self._goal = None
            self.activity = posture.value.lower()
            self.ctl.set_command(0.0, 0.0, 0.0)
        elif posture == Posture.PATROL:
            self._mode = "circle"
            self._circle_dir = "ccw"
            self.activity = "patrol"

    def set_nav_goal(self, x: float, y: float) -> None:
        self._mode = "walk"
        self._goal = (x, y)
        self.last_posture = Posture.WALK
        self.activity = "walk"

    def set_circle(self, direction: str = "ccw") -> None:
        self._mode = "circle"
        self._circle_dir = "cw" if str(direction).lower() == "cw" else "ccw"
        self.last_posture = Posture.WALK
        self.activity = f"circle_{self._circle_dir}"

    def set_face(self, x: float, y: float) -> None:
        self._mode = "face"
        self._face_target = (x, y)
        self.last_posture = Posture.WALK
        self.activity = "face"

    def set_idle(self) -> None:
        self._mode = "idle"
        self._goal = None
        self.last_posture = Posture.IDLE
        self.activity = "idle"

    def set_arms_up(self, up: bool) -> None:
        if up:
            pose = self.ctl.raise_arms_pose()   # arms out to sides (stable hold)
            # raise over _ARM_RAISE_S, then hold (2nd keyframe = same pose)
            self.ctl.push_arm_gesture([(_ARM_RAISE_S, pose), (_ARM_HOLD_S, pose)])
            self.activity = "arms_up"
        else:
            self.ctl.push_arm_gesture([(_ARM_LOWER_S, self.ctl.arm_rest)])

    def _drive(self) -> None:
        if self._mode == "walk" and self._goal is not None:
            vx, vy, wz = nav_command(self.world.base_pose(self.rid), self._goal)
            if (vx, vy, wz) == (0.0, 0.0, 0.0):
                self.last_posture = Posture.ACTIVE
                self._mode = "idle"
            self.ctl.set_command(vx, vy, wz)
        elif self._mode == "circle":
            wz = _CIRCLE_W if self._circle_dir == "ccw" else -_CIRCLE_W
            self.ctl.set_command(_CIRCLE_V, 0.0, wz)
        elif self._mode == "face" and self._face_target is not None:
            x, y, yaw = self.world.base_pose(self.rid)
            tx, ty = self._face_target
            err = math.atan2(ty - y, tx - x) - yaw
            err = math.atan2(math.sin(err), math.cos(err))  # wrap to [-pi,pi]
            wz = max(-1.0, min(1.0, _FACE_KYAW * err))
            self.ctl.set_command(0.0, 0.0, wz)
        else:  # idle
            self.ctl.set_command(0.0, 0.0, 0.0)

    def step(self) -> None:
        self._drive()
        q_target, kp, kd = self.ctl.compute()
        self.world.set_pd(self.rid, q_target, kp, kd)
        q, dq = self.world.joint_state(self.rid)
        self._last_tau = list(np.abs(kp * (q_target - q) - kd * dq))

    def read_lowstate(self) -> _Lowstate:
        return _Lowstate(_tau=self._last_tau,
                         gravity_proj_z=self.world.gravity_proj_z(self.rid))

    def close(self) -> None:
        pass
