"""
G1 dance-mimic demo — runs the BeyondMimic-style tracking policy at
``unitree_rl_mjlab/deploy/robots/g1/config/policy/mimic/dance1_subject2/``
using the same DDS/BOOT/engagement plumbing as `g1_sim_rl_combo.py`.

Why this exists
---------------
The mimic policy has a different obs schema (154-D) than the velocity
policy that `g1_sim_rl_combo.py` drives (98-D), so its obs builder and
policy session can't be dropped in. But the *controller plumbing* (DDS
publisher/subscriber, RecurrentThread, BOOT ramp from measured pose
to default_q with reduced Kp, full-Kp publish, soft-settle on exit)
is identical and known-good — so this script reuses ComboController
unchanged for that scaffolding and only overrides the parts that
differ for tracking:

  * ``DeployCfg`` is replaced by ``MimicDeployCfg`` (no gait_phase /
    base_velocity command ranges; mimic doesn't have them).
  * ``Policy`` checks for the mimic obs dim 154 instead of 98.
  * ``_build_obs`` reads the reference motion's joint pos/vel and
    computes ``motion_anchor_ori_b`` (6-D rotation matrix slice that
    tells the policy how the robot's torso has drifted from the
    motion's expected torso orientation, expressed in the original
    yaw-aligned start frame).
  * ``_engage`` samples ``init_R`` from the live IMU + the motion's
    frame-0 pelvis quat; thereafter the obs builder uses it to
    compute the anchor obs.
  * No keyboard arms, no walking command — the dance reference
    already drives all 29 joints.

Run order (canonical: same as g1_sim_rl_combo.py)
-------------------------------------------------
  Terminal 1:
      source ~/unitree_sdk2_python/unitree-env/bin/activate
      cd ~/unitree-notes/unitree_mujoco/simulate_python
      python unitree_mujoco.py
      # In the viewer: press 8 a few times to lower the elastic band
      # so the robot lands. Press 9 once on the ground to disable.

  Terminal 2:
      source ~/unitree_sdk2_python/unitree-env/bin/activate
      cd ~/unitree-notes/g1_sim_demo
      python g1_sim_rl_mimic.py --duration 30
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

import g1_sim_rl_combo as combo
from g1_sim_rl_combo import (
    ComboController,
    G1_NUM_MOTOR,
    Policy as _ComboPolicy,
    quat_rotate_inverse,
    GRAVITY_W,
)


# ---- Paths --------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
MIMIC_DIR = (_REPO_ROOT / "unitree_rl_mjlab/deploy/robots/g1"
             / "config/policy/mimic/dance1_subject2")
MIMIC_ONNX = MIMIC_DIR / "exported" / "policy.onnx"
MIMIC_YAML = MIMIC_DIR / "params" / "deploy.yaml"
MIMIC_NPZ  = MIMIC_DIR / "params" / "dance1_subject2.npz"

WAIST_YAW, WAIST_ROLL, WAIST_PITCH = 12, 13, 14
EXPECTED_OBS_DIM = 154   # 58 + 6 + 3 + 29 + 29 + 29


# ---- Quaternion helpers (wxyz, matching State_Mimic.cpp's Eigen ordering)
def _quat_mul(a, b):
    aw, ax, ay, az = a; bw, bx, by, bz = b
    return np.array([
        aw*bw - ax*bx - ay*by - az*bz,
        aw*bx + ax*bw + ay*bz - az*by,
        aw*by - ax*bz + ay*bw + az*bx,
        aw*bz + ax*by - ay*bx + az*bw,
    ])


def _axis_angle_quat(axis: str, angle: float) -> np.ndarray:
    h = 0.5 * angle
    c, s = np.cos(h), np.sin(h)
    return {"x": np.array([c, s, 0.0, 0.0]),
            "y": np.array([c, 0.0, s, 0.0]),
            "z": np.array([c, 0.0, 0.0, s])}[axis]


def _quat_to_R(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w),     2*(x*z + y*w)],
        [2*(x*y + z*w),     1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w),     2*(y*z + x*w),     1 - 2*(x*x + y*y)],
    ])


def _yaw_R(q: np.ndarray) -> np.ndarray:
    """Rotation matrix of the yaw-only component of q. Matches
    isaaclab/utils.h::yawQuaternion -> toRotationMatrix used in the
    C++ State_Mimic enter/obs path."""
    w, x, y, z = q
    yaw = np.arctan2(2.0*(w*z + x*y), 1.0 - 2.0*(y*y + z*z))
    c, s = np.cos(yaw), np.sin(yaw)
    return np.array([[c, -s, 0.0],
                     [s,  c, 0.0],
                     [0.0, 0.0, 1.0]])


def _torso_quat(root_q: np.ndarray, q_waist3: np.ndarray) -> np.ndarray:
    """Match State_Mimic.cpp::robot_quat_w / motion_anchor_quat_w:
    root_quat * AngleAxis(yaw,Z) * AngleAxis(roll,X) * AngleAxis(pitch,Y).
    """
    qz = _axis_angle_quat("z", q_waist3[0])
    qx = _axis_angle_quat("x", q_waist3[1])
    qy = _axis_angle_quat("y", q_waist3[2])
    out = _quat_mul(_quat_mul(_quat_mul(root_q, qz), qx), qy)
    n = np.linalg.norm(out)
    return out if n < 1e-9 else out / n


# ---- Replacement DeployCfg (mimic yaml has no base_velocity / gait_phase)
class MimicDeployCfg:
    def __init__(self, yaml_path: Path):
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        self.step_dt: float    = float(cfg["step_dt"])
        self.kp                = np.asarray(cfg["stiffness"], dtype=np.float64)
        self.kd                = np.asarray(cfg["damping"], dtype=np.float64)
        self.default_q         = np.asarray(cfg["default_joint_pos"], dtype=np.float64)
        action = cfg["actions"]["JointPositionAction"]
        self.action_scale  = np.asarray(action["scale"],  dtype=np.float64)
        self.action_offset = np.asarray(action["offset"], dtype=np.float64)
        # Mimic doesn't have a base_velocity command; ComboController
        # touches vx/vy/wz_range and gait_period during init even though
        # we never send walking commands. Stub them with degenerate
        # zero-only ranges so set_command(0,0,0) is a no-op pass-through
        # and gait_phase contributes nothing to anything we read.
        self.vx_range = (0.0, 0.0)
        self.vy_range = (0.0, 0.0)
        self.wz_range = (0.0, 0.0)
        self.gait_period = 1.0  # divisor; value irrelevant since we don't use gait
        for name, arr in (("kp", self.kp), ("kd", self.kd),
                          ("default_q", self.default_q),
                          ("action_scale", self.action_scale),
                          ("action_offset", self.action_offset)):
            if arr.shape != (G1_NUM_MOTOR,):
                raise ValueError(f"deploy.yaml '{name}' shape {arr.shape}")


# ---- Policy wrapper for mimic obs dim ----------------------------------
class MimicPolicy(_ComboPolicy):
    OBS_DIM = EXPECTED_OBS_DIM


# ---- Reference motion (npz) --------------------------------------------
class MotionLoader:
    def __init__(self, npz_path: Path):
        z = np.load(npz_path)
        self.fps        = float(z["fps"][0])
        self.dt         = 1.0 / self.fps
        self.joint_pos  = z["joint_pos"].astype(np.float64)
        self.joint_vel  = z["joint_vel"].astype(np.float64)
        self.root_quat  = z["body_quat_w"][:, 0, :].astype(np.float64)  # wxyz
        self.num_frames = self.joint_pos.shape[0]
        self.duration   = self.num_frames * self.dt

    def frame_at(self, t: float) -> int:
        f = int(np.floor(np.clip(t, 0.0, self.duration) / self.dt))
        return min(f, self.num_frames - 1)


# ---- Mimic controller: subclass of ComboController ---------------------
class MimicController(ComboController):
    """Reuses ComboController's BOOT ramp + DDS plumbing + soften/_publish.

    Overrides:
      - _build_obs  -> mimic obs (154-D)
      - _tick       -> drop walking-command handling; engage immediately
                       after BOOT (matches ComboController's post-fix
                       behaviour anyway), then advance motion phase.
      - on engagement, sample init_R for the anchor obs.

    Inherits:
      - DDS init/teardown
      - BOOT ramp from measured pose to default_q with Kp 0.3 -> 1.0
      - Soft Kp slewing, lowstate watchdog, stop_and_settle()
    """

    def __init__(self, cfg, policy, motion: MotionLoader,
                 dance_duration: float, fall_gz_thresh: float = -0.3,
                 log_path: Optional[Path] = None):
        super().__init__(cfg, policy)
        self.motion = motion
        self.dance_duration = dance_duration
        self.fall_gz_thresh = fall_gz_thresh
        self.log_path = log_path

        # Mimic-specific engagement state.
        self.init_R = np.eye(3)
        self.motion_t0 = 0.0
        self.fall_detected_at: Optional[float] = None
        self.log_lines: list = []
        self._last_log_t = 0.0
        # Dance completion: the controller flips this true when motion_t
        # reaches dance_duration. Main loop watches it and triggers a
        # graceful stop_and_settle (Kp slewing to 0). _tick keeps running
        # in "hold default_q at full Kp" mode in the meantime so the
        # robot is in a known-good pose when softening starts — without
        # this hand-off, _tick would early-exit on _stop and leave the
        # bridge stuck on the last policy q_target at full Kp ("stubborn
        # frozen posture" observed at the end of the smoke test).
        self.dance_done = False

    # ----- override: engage immediately, no BOOT / STANDBY gates.
    #
    # Why: the bridge's seed default-pose PD cannot hold the robot upright
    # statically without the elastic band; by the time a multi-second
    # boot ramp finishes the band has either been disabled (-> robot
    # already lying flat) or is still pulling the body to z=3 (-> robot
    # hanging on its side as the legs pendulum down). In either case
    # the gz reading at engage is wildly off-distribution. The mimic
    # policy is the only thing that can drive joint torques toward
    # standing balance, so we hand it the wheel on the first lowstate.
    def _tick(self):
        if self._stop.is_set() or not self.first_state_received:
            return

        # Soft-Kp ramp (inherited behaviour).
        if self._soften_steps_left > 0:
            self.kp_scale += self._soften_step
            self._soften_steps_left -= 1
            if self._soften_steps_left == 0:
                self.kp_scale = self._soften_target

        # Watchdog: if simulator stops sending state, hold default pose.
        if time.monotonic() - self.last_state_time > self.LOWSTATE_TIMEOUT:
            self._publish(self.cfg.default_q)
            return

        # ---- Engage on the very first tick.
        if not self.policy_active:
            self.policy_active = True
            self._engage_at = time.monotonic()
            self.kp_scale = 1.0
            self.last_raw_action[:] = 0.0
            self._engage()
            self.motion_t0 = self._engage_at
            print("[mimic] policy engaged. Dance starts now.")

        now = time.monotonic()
        motion_t = now - self.motion_t0

        # End condition: dance time elapsed. Hand control back to a
        # held-default pose so stop_and_settle's Kp slew has something
        # benign to publish; main loop will trigger the soft stop.
        if motion_t >= self.dance_duration:
            if not self.dance_done:
                self.dance_done = True
                print(f"[mimic] reached duration {self.dance_duration:.1f}s — "
                      "holding default_q until soft stop.")
            self._publish(self.cfg.default_q)
            return

        # Log gz but don't auto-abort: the band may keep the robot in
        # a non-upright orientation at engage time, and the policy may
        # take a few seconds to drive it toward the dance reference's
        # expected pelvis orientation. Visual observation is the
        # real signal here. Trace fall events for the post-run summary.
        gz = float(self._projected_gravity()[2])
        if gz > self.fall_gz_thresh and self.fall_detected_at is None:
            self.fall_detected_at = motion_t

        frame = self.motion.frame_at(motion_t)
        obs = self._build_obs(frame)
        raw_action = self.policy(obs)

        # Warm-up clip + cosine ease-in (inherited concept from
        # ComboController; the mimic policy is also sensitive to bad
        # first inferences right after BOOT).
        if self._engage_at is not None:
            t_since = now - self._engage_at
            if t_since < self.POLICY_WARMUP_S:
                w = 0.5 - 0.5 * np.cos(np.pi * (t_since / self.POLICY_WARMUP_S))
                raw_action = w * np.clip(raw_action,
                                         -self.POLICY_WARMUP_CLIP,
                                         self.POLICY_WARMUP_CLIP)

        q_target = raw_action * self.cfg.action_scale + self.cfg.action_offset
        self.last_raw_action[:] = raw_action
        self._publish(q_target)

        # 10 Hz telemetry.
        if motion_t - self._last_log_t >= 0.1:
            self._last_log_t = motion_t
            q_meas = np.fromiter(
                (self.low_state.motor_state[i].q for i in range(G1_NUM_MOTOR)),
                dtype=np.float64, count=G1_NUM_MOTOR,
            )
            err = q_meas - self.motion.joint_pos[frame]
            self.log_lines.append({
                "t": round(motion_t, 3),
                "frame": frame,
                "gz": round(gz, 4),
                "leg_err_max": round(float(np.max(np.abs(err[:12]))), 3),
                "arm_err_max": round(float(np.max(np.abs(err[15:29]))), 3),
                "anchor_norm": round(float(np.linalg.norm(obs[58:64])), 3),
            })

    # ----- engage: sample init_R from current robot vs motion frame 0
    def _engage(self):
        s = self.low_state
        root_quat_w = np.array(list(s.imu_state.quaternion))
        if np.linalg.norm(root_quat_w) < 1e-6:
            root_quat_w = np.array([1.0, 0.0, 0.0, 0.0])
        q_waist_real = np.array([s.motor_state[WAIST_YAW].q,
                                 s.motor_state[WAIST_ROLL].q,
                                 s.motor_state[WAIST_PITCH].q])
        real_torso = _torso_quat(root_quat_w, q_waist_real)
        m_waist = self.motion.joint_pos[0,
                  [WAIST_YAW, WAIST_ROLL, WAIST_PITCH]]
        ref_torso = _torso_quat(self.motion.root_quat[0], m_waist)
        # Equivalent of C++ init_quat = robot_yaw * ref_yaw.T (in matrix form).
        # The obs's (init * ref).conj() * real -> rotmat -> transpose chain
        # collapses to R_real.T @ (init_R @ R_ref).
        self.init_R = _yaw_R(real_torso) @ _yaw_R(ref_torso).T
        gz = float(self._projected_gravity()[2])
        print(f"[mimic] engaged. gz={gz:+.3f}, "
              f"motion-frame-0 hip_pitch={self.motion.joint_pos[0,0]:+.3f}")

    # ----- helpers reused/shared
    def _projected_gravity(self) -> np.ndarray:
        s = self.low_state
        q = np.array(list(s.imu_state.quaternion))
        if np.linalg.norm(q) < 1e-6:
            q = np.array([1.0, 0.0, 0.0, 0.0])
        return quat_rotate_inverse(q, GRAVITY_W)

    # ----- override: 154-D mimic obs
    def _build_obs(self, frame: int) -> np.ndarray:
        s = self.low_state
        q = np.fromiter(
            (s.motor_state[i].q for i in range(G1_NUM_MOTOR)),
            dtype=np.float64, count=G1_NUM_MOTOR,
        )
        dq = np.fromiter(
            (s.motor_state[i].dq for i in range(G1_NUM_MOTOR)),
            dtype=np.float64, count=G1_NUM_MOTOR,
        )
        joint_pos_rel = q - self.cfg.default_q
        joint_vel_rel = dq

        ang_vel = np.array([s.imu_state.gyroscope[0],
                            s.imu_state.gyroscope[1],
                            s.imu_state.gyroscope[2]])

        motion_cmd = np.concatenate([self.motion.joint_pos[frame],
                                     self.motion.joint_vel[frame]])

        root_quat_w = np.array(list(s.imu_state.quaternion))
        if np.linalg.norm(root_quat_w) < 1e-6:
            root_quat_w = np.array([1.0, 0.0, 0.0, 0.0])
        q_waist_real = np.array([q[WAIST_YAW], q[WAIST_ROLL], q[WAIST_PITCH]])
        real_torso = _torso_quat(root_quat_w, q_waist_real)
        m_waist = self.motion.joint_pos[frame,
                  [WAIST_YAW, WAIST_ROLL, WAIST_PITCH]]
        ref_torso = _torso_quat(self.motion.root_quat[frame], m_waist)
        R_real = _quat_to_R(real_torso)
        R_ref  = _quat_to_R(ref_torso)
        rot = R_real.T @ (self.init_R @ R_ref)
        anchor = np.array([rot[0, 0], rot[0, 1],
                           rot[1, 0], rot[1, 1],
                           rot[2, 0], rot[2, 1]])

        return np.concatenate([
            motion_cmd,         # 58
            anchor,             # 6
            ang_vel,            # 3
            joint_pos_rel,      # 29
            joint_vel_rel,      # 29
            self.last_raw_action,  # 29
        ])  # -> 154


# ---- main ---------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=30.0)
    p.add_argument("--network", default="lo")
    p.add_argument("--log", default=f"/tmp/mimic_smoke_{int(time.time())}.jsonl")
    args = p.parse_args()

    if args.network == "lo":
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        ChannelFactoryInitialize(1, "lo")
        print("[mimic] simulator mode on lo (domain 1).")
    else:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        ChannelFactoryInitialize(0, args.network)
        print(f"[mimic] real-robot mode on {args.network} (domain 0). "
              "Keep e-stop within reach.")

    cfg = MimicDeployCfg(MIMIC_YAML)
    policy = MimicPolicy(MIMIC_ONNX)
    motion = MotionLoader(MIMIC_NPZ)
    print(f"[mimic] loaded policy={MIMIC_ONNX.name} motion={MIMIC_NPZ.name} "
          f"({motion.num_frames} frames @ {motion.fps:.0f} fps, "
          f"{motion.duration:.1f}s)")

    ctl = MimicController(cfg, policy, motion,
                          dance_duration=args.duration,
                          log_path=Path(args.log))

    def _sigint(*_):
        print("\n[mimic] SIGINT — settling.")
        ctl._stop.set()
    signal.signal(signal.SIGINT, _sigint)

    ctl.init_dds()
    ctl.start()

    try:
        while not ctl._stop.is_set() and not ctl.dance_done:
            time.sleep(0.1)
    finally:
        # stop_and_settle ramps kp_scale to 0 over 1 s while _tick keeps
        # publishing default_q (set by the dance_done branch in _tick).
        # Without this hand-off the robot freezes at the last policy
        # q_target at full Kp once we exit the wait loop.
        ctl.stop_and_settle()

    Path(args.log).write_text(
        "\n".join(json.dumps(r) for r in ctl.log_lines) + "\n"
    )
    print(f"[mimic] wrote {len(ctl.log_lines)} samples -> {args.log}")
    if ctl.fall_detected_at is not None:
        print(f"[mimic] RESULT: FAIL (fall at t={ctl.fall_detected_at:.2f}s)")
        sys.exit(2)
    if ctl.log_lines:
        gzs = [r["gz"] for r in ctl.log_lines]
        leg = max((r["leg_err_max"] for r in ctl.log_lines), default=0.0)
        arm = max((r["arm_err_max"] for r in ctl.log_lines), default=0.0)
        print(f"[mimic] gz min/mean/max = "
              f"{min(gzs):.3f}/{np.mean(gzs):.3f}/{max(gzs):.3f}")
        print(f"[mimic] tracking err: leg max={leg:.3f} rad, arm max={arm:.3f} rad")
        if max(gzs) <= -0.85:
            print("[mimic] RESULT: PASS (upright throughout).")
        else:
            print("[mimic] RESULT: MARGINAL — gz exceeded -0.85 but no fall. Inspect trace.")
    else:
        print("[mimic] RESULT: NO DATA (didn't reach mimic phase)")


if __name__ == "__main__":
    main()
