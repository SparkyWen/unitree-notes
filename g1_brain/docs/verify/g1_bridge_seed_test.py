"""Verify the bridge's seed default-pose PD: does it hold the robot upright?

This is what runs while no external controller has published lowcmd yet
(e.g. during BOOT ramp / STANDBY phases) and what the safe_hold path
falls back to. If this is unstable, the entire "publish default_q at
full Kp to stand still" assumption is wrong.
"""
import os
os.environ.setdefault("MUJOCO_GL", "osmesa")

from pathlib import Path

import numpy as np
import mujoco

WORKSPACE = Path(__file__).resolve().parents[3]
MJCF = str(WORKSPACE / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml")

# From simulate_python/config.py — these are what the bridge seeds.
G1_DEFAULT_Q = np.array(
    [-0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
     -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
     0.0, 0.0, 0.0,
     0.35, 0.18, 0.0, 0.87, 0.0, 0.0, 0.0,
     0.35, -0.18, 0.0, 0.87, 0.0, 0.0, 0.0],
    dtype=np.float64,
)
G1_DEFAULT_KP = np.array(
    [40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
     40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
     40.2, 28.5, 28.5,
     14.3, 14.3, 14.3, 14.3, 14.3, 16.8, 16.8,
     14.3, 14.3, 14.3, 14.3, 14.3, 16.8, 16.8],
    dtype=np.float64,
)
G1_DEFAULT_KD = np.array(
    [2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
     2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
     2.6, 1.8, 1.8,
     0.9, 0.9, 0.9, 0.9, 0.9, 1.1, 1.1,
     0.9, 0.9, 0.9, 0.9, 0.9, 1.1, 1.1],
    dtype=np.float64,
)


def quat_rotate_inverse(q, v):
    w, x, y, z = q
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return np.array([
        vx - w * tx + (y * tz - z * ty),
        vy - w * ty + (z * tx - x * tz),
        vz - w * tz + (x * ty - y * tx),
    ])


model = mujoco.MjModel.from_xml_path(MJCF)
data = mujoco.MjData(model)
home_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
mujoco.mj_resetDataKeyframe(model, data, home_id)
model.opt.timestep = 0.005

print(f"sim_dt={model.opt.timestep}, gravity={model.opt.gravity}")
print(f"initial qpos[0:3]={data.qpos[0:3]}, quat={data.qpos[3:7]}")

n_steps = int(15.0 / model.opt.timestep)
last_print = -1.0
for i in range(n_steps):
    q = data.qpos[7:7 + model.nu]
    dq = data.qvel[6:6 + model.nu]
    tau = G1_DEFAULT_KP * (G1_DEFAULT_Q - q) - G1_DEFAULT_KD * dq
    data.ctrl[:] = tau
    mujoco.mj_step(model, data)

    if data.time - last_print >= 1.0 - 1e-6:
        quat = data.qpos[3:7].copy()
        n = np.linalg.norm(quat)
        quat = quat / n if n > 1e-9 else np.array([1.0, 0, 0, 0])
        gz = float(quat_rotate_inverse(quat, np.array([0.0, 0, -1.0]))[2])
        print(f"  t={data.time:5.2f}  gz={gz:+.3f}  pelvis_z={data.qpos[2]:.3f}  "
              f"max|q-q*|[legs]={float(np.max(np.abs(q - G1_DEFAULT_Q)[:15])):.3f}")
        last_print = data.time
