"""Two G1s in ONE MjModel (MjSpec.attach), with per-robot slices, PD step,
and neighbor sense. The RL controller (rl_adapter) supplies (q_target,kp,kd);
this world turns them into joint torque tau = kp*(q_target-q) - kd*dq.

Verified compile (probe): nq=72, nu=58, nv=70. Per robot the actuator order
(0..28 for g1_a, 29..57 for g1_b) and the contiguous hinge qpos/qvel slices
match the policy joint order (legs, waist, left arm, right arm)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import yaml
import mujoco

_WS = Path(__file__).resolve().parents[4]
_CHILD = _WS / "unitree_mujoco" / "unitree_robots" / "g1" / "g1_29dof.xml"
_DEPLOY = (_WS / "unitree_rl_mjlab" / "deploy" / "robots" / "g1" / "config"
           / "policy" / "velocity" / "v0" / "params" / "deploy.yaml")
_NJ = 29
_STAND_Z = 0.78  # pelvis spawn height (m); puts feet ~on the floor at default_q


def _load_default_q() -> np.ndarray:
    cfg = yaml.safe_load(open(_DEPLOY))
    return np.asarray(cfg["default_joint_pos"], dtype=np.float64)


@dataclass
class RobotSlice:
    qpos_adr: int   # base free-joint qpos start (7: xyz + quat)
    qvel_adr: int   # base free-joint qvel start (6: lin + ang)
    qj_adr: int     # first hinge-joint qpos index
    dqj_adr: int    # first hinge-joint qvel index
    act_adr: int    # first actuator index
    torso_bid: int  # pelvis body id (for xpos)


class SharedG1World:
    def __init__(self, *, robot_ids=("g1_a", "g1_b"),
                 spawn: Dict[str, Tuple[float, float]] | None = None,
                 timestep: float = 0.005):
        spawn = spawn or {robot_ids[0]: (-1.5, 0.0), robot_ids[1]: (1.5, 0.0)}
        self.default_q = _load_default_q()
        spec = mujoco.MjSpec()
        spec.worldbody.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.05])
        for rid in robot_ids:
            x, y = spawn[rid]
            child = mujoco.MjSpec.from_file(str(_CHILD))
            frame = spec.worldbody.add_frame(pos=[x, y, _STAND_Z])
            frame.attach_body(child.worldbody.first_body(), f"{rid}/", "")
        self.m = spec.compile()
        self.m.opt.timestep = timestep
        self.d = mujoco.MjData(self.m)
        self.robot_ids = list(robot_ids)
        self.slices: Dict[str, RobotSlice] = {}
        for rid in robot_ids:
            base_j = self.m.joint(f"{rid}/floating_base_joint")
            first_hinge = self.m.joint(f"{rid}/left_hip_pitch_joint")
            self.slices[rid] = RobotSlice(
                qpos_adr=int(base_j.qposadr[0]), qvel_adr=int(base_j.dofadr[0]),
                qj_adr=int(first_hinge.qposadr[0]), dqj_adr=int(first_hinge.dofadr[0]),
                act_adr=_first_act_for(self.m, rid),
                torso_bid=self.m.body(f"{rid}/pelvis").id)
        # per-robot held PD setpoint (q_target, kp, kd); recomputed into torque
        # every *sim* step (see step()) so torque never goes stale at 50 Hz.
        self._pd: Dict[str, tuple] = {}
        # seed each robot: spawn xy + standing height, identity quat, default pose
        for rid in robot_ids:
            sl = self.slices[rid]
            x, y = spawn[rid]
            self.d.qpos[sl.qpos_adr:sl.qpos_adr + 3] = (x, y, _STAND_Z)
            self.d.qpos[sl.qpos_adr + 3:sl.qpos_adr + 7] = (1.0, 0.0, 0.0, 0.0)
            self.d.qpos[sl.qj_adr:sl.qj_adr + _NJ] = self.default_q
        mujoco.mj_forward(self.m, self.d)

    # ---- per-robot accessors ----
    def base_pose(self, rid: str) -> Tuple[float, float, float]:
        sl = self.slices[rid]
        x, y = self.d.qpos[sl.qpos_adr], self.d.qpos[sl.qpos_adr + 1]
        quat = self.d.qpos[sl.qpos_adr + 3:sl.qpos_adr + 7]
        yaw = math.atan2(2 * (quat[0] * quat[3] + quat[1] * quat[2]),
                         1 - 2 * (quat[2] ** 2 + quat[3] ** 2))
        return float(x), float(y), float(yaw)

    def base_quat(self, rid: str) -> np.ndarray:
        sl = self.slices[rid]
        return np.array(self.d.qpos[sl.qpos_adr + 3:sl.qpos_adr + 7])

    def base_angvel(self, rid: str) -> np.ndarray:
        sl = self.slices[rid]
        return np.array(self.d.qvel[sl.qvel_adr + 3:sl.qvel_adr + 6])

    def joint_state(self, rid: str):
        sl = self.slices[rid]
        q = np.array(self.d.qpos[sl.qj_adr:sl.qj_adr + _NJ])
        dq = np.array(self.d.qvel[sl.dqj_adr:sl.dqj_adr + _NJ])
        return q, dq

    def gravity_proj_z(self, rid: str) -> float:
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, self.base_quat(rid))
        return float((R.reshape(3, 3).T @ np.array([0.0, 0.0, -1.0]))[2])

    def set_pd(self, rid: str, q_target: np.ndarray, kp: np.ndarray, kd: np.ndarray) -> None:
        """Hold a PD setpoint for this robot. The torque is recomputed from
        fresh q/dq on every sim step (see step()), matching the unitree bridge:
        applying PD only at the 50 Hz control rate makes torque stale relative
        to the integrator and drives Kp oscillation -> instability."""
        self._pd[rid] = (np.asarray(q_target, dtype=np.float64),
                         np.asarray(kp, dtype=np.float64),
                         np.asarray(kd, dtype=np.float64))

    def _apply_pd(self) -> None:
        for rid, (q_target, kp, kd) in self._pd.items():
            sl = self.slices[rid]
            q, dq = self.joint_state(rid)
            self.d.ctrl[sl.act_adr:sl.act_adr + _NJ] = kp * (q_target - q) - kd * dq

    def neighbors(self, rid: str) -> List[dict]:
        x, y, yaw = self.base_pose(rid)
        out = []
        for other in self.robot_ids:
            if other == rid:
                continue
            ox, oy, _ = self.base_pose(other)
            dx, dy = ox - x, oy - y
            dist = math.hypot(dx, dy)
            bearing = math.atan2(dy, dx) - yaw
            out.append({"peer": other, "dx": dx, "dy": dy, "dist": dist,
                        "bearing": math.atan2(math.sin(bearing), math.cos(bearing))})
        return out

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self._apply_pd()  # fresh torque every sim step (200 Hz), not stale 50 Hz
            mujoco.mj_step(self.m, self.d)


def _first_act_for(m, rid: str) -> int:
    for i in range(m.nu):
        if m.actuator(i).name.startswith(f"{rid}/"):
            return i
    raise KeyError(rid)
