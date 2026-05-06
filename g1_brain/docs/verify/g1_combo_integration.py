"""End-to-end verification of the FIXED ComboController against MuJoCo.

Mirrors the user's typical workflow:
  1. Start sim with elastic band engaged (length=0, robot pulled up to anchor).
  2. Start combo controller.
  3. Combo BOOT (5 s) runs while robot is band-suspended.
  4. Policy engages.
  5. Operator lengthens band gradually (programmatic 8-press loop).
  6. Operator disables band (programmatic 9-press) — robot must now balance.
  7. Test long-term stand stability + walk-then-stand + safe_hold cycles.

Pass criterion for each phase: gz stays < -0.85 (≤ ~32° tilt from upright).
"""
import os
os.environ.setdefault("MUJOCO_GL", "osmesa")

import sys
import threading
import time
from pathlib import Path

import numpy as np
import mujoco

WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE / "g1_sim_demo"))
sys.path.insert(0, str(WORKSPACE / "unitree_mujoco/simulate_python"))

import config as sim_config  # type: ignore
sim_config.ENABLE_ELASTIC_BAND = True
sim_config.ELASTIC_BAND_INIT_LENGTH = 0.0  # match the default user workflow
sim_config.PRINT_SCENE_INFORMATION = False

from unitree_sdk2py.core.channel import ChannelFactoryInitialize  # noqa: E402
from unitree_sdk2py_bridge import UnitreeSdk2Bridge, ElasticBand  # noqa: E402

import g1_sim_rl_combo as combo_mod  # noqa: E402


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


# ---- bring up the simulator ------------------------------------------------
mj_model = mujoco.MjModel.from_xml_path(
    str(WORKSPACE / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml")
)
mj_data = mujoco.MjData(mj_model)
home_id = mujoco.mj_name2id(mj_model, mujoco.mjtObj.mjOBJ_KEY, "home")
mujoco.mj_resetDataKeyframe(mj_model, mj_data, home_id)
mj_model.opt.timestep = sim_config.SIMULATE_DT  # 0.005

ChannelFactoryInitialize(sim_config.DOMAIN_ID, sim_config.INTERFACE)
bridge = UnitreeSdk2Bridge(mj_model, mj_data)
band = ElasticBand()
band.length = float(sim_config.ELASTIC_BAND_INIT_LENGTH)
band_link = mj_model.body("torso_link").id

stop_evt = threading.Event()


def sim_thread():
    """Real-time-paced sim loop, matching unitree_mujoco.py's structure."""
    while not stop_evt.is_set():
        step_start = time.perf_counter()
        bridge.ApplyControl()
        if band.enable:
            mj_data.xfrc_applied[band_link, :3] = band.Advance(
                mj_data.qpos[:3], mj_data.qvel[:3]
            )
        else:
            mj_data.xfrc_applied[band_link, :3] = 0.0
        mujoco.mj_step(mj_model, mj_data)
        time_until_next_step = mj_model.opt.timestep - (
            time.perf_counter() - step_start
        )
        if time_until_next_step > 0:
            time.sleep(time_until_next_step)


t_sim = threading.Thread(target=sim_thread, daemon=True)
t_sim.start()
time.sleep(0.5)

# ---- bring up combo controller --------------------------------------------
cfg = combo_mod.DeployCfg(combo_mod.POLICY_YAML)
policy = combo_mod.Policy(combo_mod.POLICY_ONNX)
ctl = combo_mod.ComboController(cfg, policy)
ctl.init_dds()
ctl.start()

deadline = time.monotonic() + 30.0
t0 = time.monotonic()
while not ctl.policy_active and time.monotonic() < deadline:
    time.sleep(0.05)
print(f"[verify] policy_active={ctl.policy_active} after "
      f"{time.monotonic() - t0:.1f}s "
      f"(boot_done={ctl._boot_done})")


def gz_now():
    quat = mj_data.qpos[3:7].copy()
    n = np.linalg.norm(quat)
    quat = quat / n if n > 1e-9 else np.array([1.0, 0, 0, 0])
    return float(quat_rotate_inverse(quat, np.array([0.0, 0, -1.0]))[2])


def sample(label, dur_s, sample_every=2.0):
    t0 = time.monotonic()
    last_print = -1.0
    worst_gz = -1.0
    while time.monotonic() - t0 < dur_s:
        time.sleep(0.05)
        t = time.monotonic() - t0
        gz = gz_now()
        worst_gz = max(worst_gz, gz)
        if t - last_print >= sample_every - 1e-6:
            print(f"  [{label}] t={t:5.2f}  gz={gz:+.3f}  "
                  f"pelvis_z={mj_data.qpos[2]:.3f}  worst_gz={worst_gz:+.3f}")
            last_print = t
    return worst_gz


# Operator lengthens the band gradually so robot descends from z~3 to ground.
# The default sim has anchor at (0,0,3) and torso target at z=0.793 → distance
# 2.2m. Lengthening to 2.5m gives slack.
print("\n--- 0a) lower band over 4s (operator presses 8 ~25 times) ---")
n_press = 25
for i in range(n_press):
    band.length += 0.1
    time.sleep(4.0 / n_press)
print(f"[verify] band.length={band.length:.2f}, gz={gz_now():+.3f}, "
      f"pelvis_z={mj_data.qpos[2]:.3f}")

print("\n--- 0b) press 9 to disable band (robot must now balance) ---")
band.enable = False
mj_data.xfrc_applied[band_link, :] = 0.0
time.sleep(1.0)
print(f"[verify] gz={gz_now():+.3f}, pelvis_z={mj_data.qpos[2]:.3f}")

print("\n--- 1) idle 60s at cmd=(0,0,0) ---")
ctl.set_command(0.0, 0.0, 0.0)
worst_idle = sample("idle", 60.0, sample_every=5.0)

print("\n--- 2) walk(vx=0.2) for 1s, then idle 30s ---")
ctl.set_command(0.2, 0.0, 0.0)
sample("walk", 1.0, sample_every=0.5)
ctl.set_command(0.0, 0.0, 0.0)
worst_after_walk = sample("post_walk", 30.0, sample_every=5.0)

print("\n--- 3) safe_hold ON 5s then OFF + idle 20s (simulates EMERGENCY_STOP) ---")
ctl.set_safe_hold(True)
sample("safehold_on", 5.0, sample_every=2.0)
ctl.set_safe_hold(False)
worst_after_safehold = sample("safehold_off", 20.0, sample_every=5.0)

print("\n=== summary ===")
print(f"  worst gz during 60s idle:        {worst_idle:+.3f}  "
      f"(pass if < -0.85)  -> {'PASS' if worst_idle < -0.85 else 'FAIL'}")
print(f"  worst gz 30s after walk(0.2):    {worst_after_walk:+.3f}  "
      f"-> {'PASS' if worst_after_walk < -0.85 else 'FAIL'}")
print(f"  worst gz 20s after safe_hold:    {worst_after_safehold:+.3f}  "
      f"-> {'PASS' if worst_after_safehold < -0.85 else 'FAIL'}")

stop_evt.set()
ctl.stop_and_settle()
time.sleep(0.5)
