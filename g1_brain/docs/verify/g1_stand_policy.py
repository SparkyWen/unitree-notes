"""Verify if RUNNING the policy at cmd=0 is more stable than publishing default_q.

This mirrors what g1_sim_rl_combo's POLICY phase does, but headless and
isolated from agent_main / DDS / watchdogs / arms. It also tests a third
mode: a *modified* default_q with hip_pitch/ankle_pitch reduced so the COM
sits over the ankles (passively stable static stance).
"""
import os
os.environ.setdefault("MUJOCO_GL", "osmesa")

import sys
from pathlib import Path

import numpy as np
import mujoco
import yaml
import onnxruntime as ort

WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE / "g1_sim_demo"))

MJCF = str(WORKSPACE / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml")
POLICY_DIR = WORKSPACE / "unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0"
ONNX = POLICY_DIR / "exported/policy.onnx"
DEPLOY_YAML = POLICY_DIR / "params/deploy.yaml"

with open(DEPLOY_YAML) as f:
    cfg = yaml.safe_load(f)

KP = np.asarray(cfg["stiffness"], dtype=np.float64)
KD = np.asarray(cfg["damping"], dtype=np.float64)
DEFAULT_Q = np.asarray(cfg["default_joint_pos"], dtype=np.float64)
ACT_SCALE = np.asarray(cfg["actions"]["JointPositionAction"]["scale"], dtype=np.float64)
ACT_OFFSET = np.asarray(cfg["actions"]["JointPositionAction"]["offset"], dtype=np.float64)
GAIT_PERIOD = float(cfg["observations"]["gait_phase"]["params"]["period"])
STEP_DT = float(cfg["step_dt"])  # 0.02 (50 Hz)


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


def build_obs(q, dq, quat_wxyz, gyro, last_action, cmd, gait):
    n = np.linalg.norm(quat_wxyz)
    quat = quat_wxyz / n if n > 1e-9 else np.array([1.0, 0, 0, 0])
    proj_g = quat_rotate_inverse(quat, np.array([0.0, 0, -1.0]))
    return np.concatenate([
        gyro,                  # 3
        proj_g,                # 3
        cmd,                   # 3
        gait,                  # 2
        q - DEFAULT_Q,         # 29
        dq,                    # 29
        last_action,           # 29
    ])


def run_policy(label: str, dur_s: float = 12.0, kp_scale: float = 1.0,
               cmd=(0.0, 0.0, 0.0), warmup_clip: float = 0.8,
               warmup_dur_s: float = 0.6):
    sess = ort.InferenceSession(str(ONNX), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name

    model = mujoco.MjModel.from_xml_path(MJCF)
    data = mujoco.MjData(model)
    home_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
    mujoco.mj_resetDataKeyframe(model, data, home_id)

    nu = model.nu
    sim_dt = float(model.opt.timestep)
    ticks_per_policy = int(round(STEP_DT / sim_dt))  # 0.02 / 0.002 = 10

    last_action = np.zeros(nu, dtype=np.float64)
    global_phase = 0.0
    cmd = np.asarray(cmd, dtype=np.float64)
    cmd_norm = float(np.linalg.norm(cmd))

    # PD targets are updated at policy rate (50 Hz); ctrl is recomputed each
    # sim step (200 Hz) using the held target.
    q_target = DEFAULT_Q.copy()

    n_steps = int(dur_s / sim_dt)
    samples = []
    t_engage = 0.0
    for i in range(n_steps):
        t_now = data.time
        if i % ticks_per_policy == 0:
            q = data.qpos[7:7 + nu].copy()
            dq = data.qvel[6:6 + nu].copy()
            gyro = data.qvel[3:6].copy()
            quat = data.qpos[3:7].copy()  # wxyz
            global_phase = (global_phase + STEP_DT / GAIT_PERIOD) % 1.0
            if cmd_norm < 0.1:
                gait = np.array([0.0, 0.0])
            else:
                theta = 2.0 * np.pi * global_phase
                gait = np.array([np.sin(theta), np.cos(theta)])
            obs = build_obs(q, dq, quat, gyro, last_action, cmd, gait)
            raw = sess.run([out_name], {in_name: obs.astype(np.float32).reshape(1, -1)})[0].reshape(-1)
            # Warm-up clip + cosine ramp like reference combo.
            t_since_engage = t_now - t_engage
            if t_since_engage < warmup_dur_s:
                w = 0.5 - 0.5 * np.cos(np.pi * (t_since_engage / warmup_dur_s))
                raw = w * np.clip(raw, -warmup_clip, warmup_clip)
            last_action = raw.copy()
            q_target = raw * ACT_SCALE + ACT_OFFSET

        # PD inner loop (200 Hz)
        q = data.qpos[7:7 + nu]
        dq = data.qvel[6:6 + nu]
        tau = (KP * kp_scale) * (q_target - q) - (KD * kp_scale) * dq
        data.ctrl[:] = tau
        mujoco.mj_step(model, data)

        if i % 25 == 0:
            quat = data.qpos[3:7].copy()
            n = np.linalg.norm(quat)
            quat = quat / n if n > 1e-9 else np.array([1.0, 0, 0, 0])
            gz = float(quat_rotate_inverse(quat, np.array([0.0, 0, -1.0]))[2])
            pose_err = float(np.max(np.abs(q - DEFAULT_Q)[:15]))
            samples.append((data.time, gz, pose_err, float(data.qpos[2])))

    print(f"\n=== {label} ===")
    final = samples[-1]
    print(f"  final t={final[0]:.2f}  gz={final[1]:+.3f}  "
          f"pose_err={final[2]:.3f}  pelvis_z={final[3]:.3f}")
    def first_above(thr):
        for t, gz, *_ in samples:
            if gz > thr:
                return t
        return None
    for thr, lab in [(-0.95, "gz>-0.95"), (-0.85, "gz>-0.85"),
                     (-0.50, "gz>-0.50"), (0.0, "gz>0 (horizontal)")]:
        t = first_above(thr)
        print(f"  first {lab}: {t}")
    last_print = -1.0
    for t, gz, p, z in samples:
        if t - last_print >= 2.0 - 1e-6:
            print(f"    t={t:5.2f}  gz={gz:+.3f}  pose_err={p:.3f}  pelvis_z={z:.3f}")
            last_print = t
    return samples


def run_walk_then_stop():
    """Replicates user's pattern: walk vx=0.2 dur=1.0 then idle."""
    sess = ort.InferenceSession(str(ONNX), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name

    model = mujoco.MjModel.from_xml_path(MJCF)
    data = mujoco.MjData(model)
    home_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
    mujoco.mj_resetDataKeyframe(model, data, home_id)
    model.opt.timestep = 0.005
    nu = model.nu
    sim_dt = float(model.opt.timestep)
    ticks_per_policy = int(round(STEP_DT / sim_dt))

    last_action = np.zeros(nu)
    global_phase = 0.0
    q_target = DEFAULT_Q.copy()

    schedule = [
        # (t_until_s, cmd)
        (2.0,  np.array([0.0, 0.0, 0.0])),  # idle 2s
        (3.0,  np.array([0.2, 0.0, 0.0])),  # walk 1s
        (60.0, np.array([0.0, 0.0, 0.0])),  # idle 57s
    ]
    samples = []
    t_engage = 0.0

    def cmd_at(t):
        for end_t, c in schedule:
            if t < end_t:
                return c
        return schedule[-1][1]

    n_steps = int(60.0 / sim_dt)
    for i in range(n_steps):
        if i % ticks_per_policy == 0:
            cmd = cmd_at(data.time)
            cmd_norm = float(np.linalg.norm(cmd))
            q = data.qpos[7:7 + nu].copy()
            dq = data.qvel[6:6 + nu].copy()
            gyro = data.qvel[3:6].copy()
            quat = data.qpos[3:7].copy()
            global_phase = (global_phase + STEP_DT / GAIT_PERIOD) % 1.0
            if cmd_norm < 0.1:
                gait = np.array([0.0, 0.0])
            else:
                theta = 2.0 * np.pi * global_phase
                gait = np.array([np.sin(theta), np.cos(theta)])
            obs = build_obs(q, dq, quat, gyro, last_action, cmd, gait)
            raw = sess.run([out_name], {in_name: obs.astype(np.float32).reshape(1, -1)})[0].reshape(-1)
            t_since_engage = data.time - t_engage
            if t_since_engage < 0.6:
                w = 0.5 - 0.5 * np.cos(np.pi * (t_since_engage / 0.6))
                raw = w * np.clip(raw, -0.8, 0.8)
            last_action = raw.copy()
            q_target = raw * ACT_SCALE + ACT_OFFSET

        q = data.qpos[7:7 + nu]
        dq = data.qvel[6:6 + nu]
        tau = KP * (q_target - q) - KD * dq
        data.ctrl[:] = tau
        mujoco.mj_step(model, data)

        if i % 50 == 0:
            quat = data.qpos[3:7].copy()
            n = np.linalg.norm(quat)
            quat = quat / n if n > 1e-9 else np.array([1.0, 0, 0, 0])
            gz = float(quat_rotate_inverse(quat, np.array([0.0, 0, -1.0]))[2])
            samples.append((data.time, gz, float(data.qpos[2]), float(data.qpos[0])))

    print("\n=== walk(vx=0.2, 1s) then idle for 57s, policy always running ===")
    last_print = -1.0
    for t, gz, z, x in samples:
        if t - last_print >= 2.0 - 1e-6:
            print(f"  t={t:5.2f}  gz={gz:+.3f}  pelvis_z={z:.3f}  pelvis_x={x:+.3f}")
            last_print = t


if __name__ == "__main__":
    print("policy@cmd=0, 60s:")
    run_policy("policy at cmd=0 (kp×1.0, 60s)", dur_s=60.0, kp_scale=1.0,
               cmd=(0.0, 0.0, 0.0))
    run_walk_then_stop()
