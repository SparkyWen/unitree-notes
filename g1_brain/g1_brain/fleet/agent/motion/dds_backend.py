"""MotionBackend over DDS — drives a *separate* unitree_mujoco process.

This is the faithful transport used by the GUI two-process path: the harness
runs in its own process, subscribes to the sim's ``rt/lowstate`` (real joint
tau_est + IMU) and publishes ``rt/lowcmd`` (posture -> PD joint targets). The
sim (GUI ``unitree_mujoco.py`` or the headless runner) steps physics and applies
our lowcmd via its bridge. One DDS domain per process (sim and node use the
same domain; two robots use two domains).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.sim import g1_consts as C


@dataclass
class _DdsLowstate:
    _tau: List[float]
    gravity_proj_z: float

    def tau_est(self) -> List[float]:
        return list(self._tau)


class DdsMujocoBackend:
    def __init__(self, *, domain_id: int, interface: str = "lo",
                 n_joints: int = 29, init_factory: bool = True):
        from unitree_sdk2py.core.channel import (
            ChannelFactoryInitialize, ChannelPublisher, ChannelSubscriber,
        )
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_
        from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_

        if init_factory:
            ChannelFactoryInitialize(domain_id, interface)
        self._n = n_joints
        self._LowCmd = unitree_hg_msg_dds__LowCmd_
        self._pub = ChannelPublisher("rt/lowcmd", LowCmd_)
        self._pub.Init()
        self._sub = ChannelSubscriber("rt/lowstate", LowState_)
        self._sub.Init(self._on_state, 10)
        self._latest = None
        self._phase = 0.0
        self.last_posture: Posture = Posture.ACTIVE
        self._kp = C.G1_DEFAULT_KP[:n_joints]
        self._kd = C.G1_DEFAULT_KD[:n_joints]
        self._q = list(C.G1_DEFAULT_JOINT_POS[:n_joints])
        self._kp_scale = 1.0
        self.set_posture(Posture.ACTIVE)

    def _on_state(self, msg) -> None:
        self._latest = msg

    def set_posture(self, posture: Posture) -> None:
        self.last_posture = posture
        q = list(C.G1_DEFAULT_JOINT_POS[:self._n])
        if posture == Posture.SLEEP:
            q[C.KNEE_L] += 0.8
            q[C.KNEE_R] += 0.8
            q[C.HIP_PITCH_L] -= 0.5
            q[C.HIP_PITCH_R] -= 0.5
            q[C.SH_PITCH_L] = 0.0
            q[C.SH_PITCH_R] = 0.0
            q[C.ELBOW_L] = 0.2
            q[C.ELBOW_R] = 0.2
            self._kp_scale = 0.35
        else:
            self._kp_scale = 1.0
        self._q = q
        self._publish()

    def step(self) -> None:
        if self.last_posture == Posture.PATROL:
            self._phase += 0.15
            q = list(C.G1_DEFAULT_JOINT_POS[:self._n])
            wave = 0.5 * math.sin(self._phase)
            q[C.ELBOW_L] += wave
            q[C.ELBOW_R] += wave
            self._q = q
        self._publish()

    def _publish(self) -> None:
        cmd = self._LowCmd()
        for i in range(self._n):
            mc = cmd.motor_cmd[i]
            mc.q = float(self._q[i])
            mc.kp = float(self._kp[i] * self._kp_scale)
            mc.kd = float(self._kd[i])
            mc.dq = 0.0
            mc.tau = 0.0
        self._pub.Write(cmd)

    def read_lowstate(self) -> _DdsLowstate:
        s = self._latest
        if s is None:
            return _DdsLowstate([0.0] * self._n, -1.0)
        tau = [abs(float(s.motor_state[i].tau_est)) for i in range(self._n)]
        gz = C.gravity_proj_z_from_quat(s.imu_state.quaternion)
        return _DdsLowstate(tau, gz)

    def close(self) -> None:
        pass
