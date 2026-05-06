"""Headless MuJoCo verification: does default_q + PD hold the G1 stable?

Loads scene_29dof.xml at the trained 'home' keyframe (so the robot starts
on the floor at default joint pose), no elastic band, and runs PD control
toward default_q with various Kp/Kd scales. Measures gravity_proj_z and
joint pose error over time.

This isolates the question: "is the stand-still bypass's choice of
publishing default_q at full Kp sufficient to keep the robot upright?"
"""
import os
os.environ.setdefault("MUJOCO_GL", "osmesa")  # headless

from pathlib import Path

import numpy as np
import mujoco

# This script lives at <workspace>/g1_brain/docs/verify/, so the
# unitree-notes workspace root is its grandparent's grandparent.
WORKSPACE = Path(__file__).resolve().parents[3]
MJCF = str(WORKSPACE / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml")

DEFAULT_Q = np.array(
    [-0.1, 0, 0, 0.3, -0.2, 0,
     -0.1, 0, 0, 0.3, -0.2, 0,
     0, 0, 0,
     0.35, 0.18, 0, 0.87, 0, 0, 0,
     0.35, -0.18, 0, 0.87, 0, 0, 0],
    dtype=np.float64,
)

DEPLOY_KP = np.array(
    [40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
     40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
     40.2, 28.5, 28.5,
     14.3, 14.3, 14.3, 14.3, 14.3, 16.8, 16.8,
     14.3, 14.3, 14.3, 14.3, 14.3, 16.8, 16.8],
    dtype=np.float64,
)
DEPLOY_KD = np.array(
    [2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
     2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
     2.6, 1.8, 1.8,
     0.9, 0.9, 0.9, 0.9, 0.9, 1.1, 1.1,
     0.9, 0.9, 0.9, 0.9, 0.9, 1.1, 1.1],
    dtype=np.float64,
)

# kb-demo gains, from g1_sim_keyboard.py KP_DEFAULT/KD_DEFAULT.
KB_KP = np.array(
    [60, 60, 60, 100, 40, 40,
     60, 60, 60, 100, 40, 40,
     60, 40, 40,
     40, 40, 40, 40, 40, 40, 40,
     40, 40, 40, 40, 40, 40, 40], dtype=np.float64)
KB_KD = np.array(
    [1, 1, 1, 2, 1, 1,
     1, 1, 1, 2, 1, 1,
     1, 1, 1,
     1, 1, 1, 1, 1, 1, 1,
     1, 1, 1, 1, 1, 1, 1], dtype=np.float64)


def quat_rotate_inverse_wxyz(q, v):
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


def run_one(label: str, kp: np.ndarray, kd: np.ndarray, dur_s: float = 12.0):
    model = mujoco.MjModel.from_xml_path(MJCF)
    data = mujoco.MjData(model)
    model.opt.timestep = 0.005  # match unitree_mujoco config.SIMULATE_DT
    # Use the "home" keyframe (default trained pose, on ground).
    home_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
    if home_id < 0:
        raise SystemExit("home keyframe not found")
    mujoco.mj_resetDataKeyframe(model, data, home_id)
    nu = model.nu
    assert nu == 29, f"unexpected nu={nu}"
    sim_dt = float(model.opt.timestep)
    n_steps = int(dur_s / sim_dt)

    samples = []  # (t, gz, pose_err, vel_err, pelvis_z)
    for i in range(n_steps):
        # PD: tau = kp*(q_des - q) + kd*(0 - dq)
        q = data.qpos[7:7 + nu]
        dq = data.qvel[6:6 + nu]
        tau = kp * (DEFAULT_Q - q) - kd * dq
        data.ctrl[:] = tau
        mujoco.mj_step(model, data)

        if i % 25 == 0:  # ~ every 50ms
            quat = data.qpos[3:7].copy()  # wxyz
            n = np.linalg.norm(quat)
            quat = quat / n if n > 1e-9 else np.array([1.0, 0, 0, 0])
            gz = float(quat_rotate_inverse_wxyz(quat, np.array([0.0, 0, -1.0]))[2])
            pose_err = float(np.max(np.abs(q - DEFAULT_Q)[:15]))
            vel_err = float(np.max(np.abs(dq[:15])))
            samples.append((
                data.time, gz, pose_err, vel_err, float(data.qpos[2]),
            ))

    # Print summary
    print(f"\n=== {label} ===")
    print(f"  duration={dur_s}s  step={sim_dt}s  steps={n_steps}")
    final = samples[-1]
    print(f"  final t={final[0]:.2f}  gz={final[1]:+.3f}  "
          f"pose_err={final[2]:.3f}  vel_err={final[3]:.3f}  "
          f"pelvis_z={final[4]:.3f}")
    # Find first time gz>-0.95, gz>-0.85, gz>-0.5 (32deg, 32deg threshold, 60deg)
    def first_above(thresh):
        for t, gz, *_ in samples:
            if gz > thresh:
                return t
        return None

    for thr, label_thr in [(-0.95, "gz>-0.95 (~18°)"),
                           (-0.85, "gz>-0.85 (~32°)"),
                           (-0.50, "gz>-0.50 (~60°)"),
                           ( 0.00, "gz> 0.00  (horizontal)")]:
        t = first_above(thr)
        print(f"  first {label_thr}: {t}")
    # Print every 2s sample
    print("  trace (every 2s): t  gz   pose_err  vel_err  pelvis_z")
    last_print = -1.0
    for t, gz, p, v, z in samples:
        if t - last_print >= 2.0 - 1e-6:
            print(f"    t={t:5.2f}  gz={gz:+.3f}  pose_err={p:.3f}  "
                  f"vel_err={v:5.2f}  pelvis_z={z:.3f}")
            last_print = t
    return samples


if __name__ == "__main__":
    import sys
    print("MuJoCo G1 default_q + PD stand-still verification (no elastic band)")
    print("MJCF =", MJCF)

    run_one("deploy.yaml × 1.0 (policy training gains)", DEPLOY_KP, DEPLOY_KD)
    run_one("deploy.yaml × 1.4 (current STAND_KP_BOOST_TARGET)",
            DEPLOY_KP * 1.4, DEPLOY_KD * 1.4)
    run_one("deploy.yaml × 2.0", DEPLOY_KP * 2.0, DEPLOY_KD * 2.0)
    run_one("deploy.yaml × 3.0", DEPLOY_KP * 3.0, DEPLOY_KD * 3.0)
    run_one("kb-demo gains (60/100/40, kd=1/2/1)", KB_KP, KB_KD)
    run_one("kb-demo gains × 1.5", KB_KP * 1.5, KB_KD * 1.5)
