"""Headless MuJoCo G1 — real physics, no viewer, no DDS.

A single G1 in its own MjModel/MjData world. Kept upright by the same elastic
band the GUI sim uses (torso spring toward an anchor) plus a mild upright
restoring torque, while joint PD holds whatever target pose the posture asks
for. This lets two real G1 physics worlds run in one process for the Tier-2
dispatch verification, with real joint effort (tau) feeding the thermal model.

Joint order / gains are copied from
unitree_rl_mjlab/.../velocity/v0/params/deploy.yaml (same as the GUI sim's
config.py default-hold) so the held pose is in-distribution.
"""
from __future__ import annotations

import numpy as np
import mujoco

from g1_brain.fleet.sim import g1_consts

G1_DEFAULT_JOINT_POS = np.array(g1_consts.G1_DEFAULT_JOINT_POS)
G1_DEFAULT_KP = np.array(g1_consts.G1_DEFAULT_KP)
G1_DEFAULT_KD = np.array(g1_consts.G1_DEFAULT_KD)


class MujocoG1:
    def __init__(self, scene_path: str, *, timestep: float = 0.005,
                 band_anchor_z: float = 3.0, band_length: float = 1.5,
                 band_k: float = 200.0, band_d: float = 100.0,
                 upright_k: float = 400.0, upright_d: float = 40.0):
        self.m = mujoco.MjModel.from_xml_path(scene_path)
        self.d = mujoco.MjData(self.m)
        self.m.opt.timestep = timestep
        self.nu = self.m.nu
        n = self.nu
        self.q_def = G1_DEFAULT_JOINT_POS[:n].copy()
        self.kp = G1_DEFAULT_KP[:n].copy()
        self.kd = G1_DEFAULT_KD[:n].copy()
        self.d.qpos[7:7 + n] = self.q_def
        if np.linalg.norm(self.d.qpos[3:7]) < 1e-6:
            self.d.qpos[3:7] = (1.0, 0.0, 0.0, 0.0)
        mujoco.mj_forward(self.m, self.d)
        self._torso = self.m.body("torso_link").id
        self._q_des = self.q_def.copy()
        self._kp_scale = 1.0
        self._band_pt = np.array([0.0, 0.0, band_anchor_z])
        self._band_len = band_length
        self._band_k = band_k
        self._band_d = band_d
        self._up_k = upright_k
        self._up_d = upright_d

    def set_targets(self, q_des, *, kp_scale: float = 1.0) -> None:
        self._q_des = np.asarray(q_des, dtype=np.float64)[:self.nu]
        self._kp_scale = float(kp_scale)

    def _apply_holds(self) -> None:
        # Elastic band: torso spring toward anchor (keeps the robot suspended,
        # like the GUI sim's band) — purely vertical-ish translational support.
        x = self.d.qpos[:3]
        dx = self.d.qvel[:3]
        delta = self._band_pt - x
        dist = float(np.linalg.norm(delta))
        if dist > 1e-6:
            direction = delta / dist
            v = float(np.dot(dx, direction))
            f = (self._band_k * (dist - self._band_len) - self._band_d * v) * direction
            self.d.xfrc_applied[self._torso, :3] = f
        # Mild upright restoring torque (the band alone doesn't fix orientation).
        quat = self.d.qpos[3:7]               # w,x,y,z (pelvis)
        omega = self.d.qvel[3:6]              # pelvis angular velocity
        torque = -self._up_k * quat[1:4] - self._up_d * omega
        self.d.xfrc_applied[self._torso, 3:6] = torque

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            q = self.d.qpos[7:7 + self.nu]
            dq = self.d.qvel[6:6 + self.nu]
            self.d.ctrl[:self.nu] = (self.kp * self._kp_scale * (self._q_des - q)
                                     - self.kd * dq)
            self._apply_holds()
            mujoco.mj_step(self.m, self.d)

    def tau_est(self):
        """Per-joint applied torque magnitude — the real effort the thermal
        model integrates."""
        return list(np.abs(self.d.ctrl[:self.nu]))

    def gravity_proj_z(self) -> float:
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, self.d.qpos[3:7])
        R = R.reshape(3, 3)
        g_body = R.T @ np.array([0.0, 0.0, -1.0])
        return float(g_body[2])

    def pelvis_z(self) -> float:
        return float(self.d.qpos[2])
