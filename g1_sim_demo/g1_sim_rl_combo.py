"""
G1 RL walk + arm-gesture combo demo for unitree_mujoco.

Single-process controller that runs the trained ONNX velocity policy
(closed-loop balance + walking) AND lets the keyboard trigger upper-body
arm gestures on top, without the rt/lowcmd publisher conflict you'd hit
by running g1_sim_rl_walk.py and g1_sim_keyboard.py at the same time.

Architecture
------------
- 50 Hz RL tick: builds 98-D obs from rt/lowstate, runs policy.onnx,
  converts raw_action -> q_target (29-D).
- The policy controls all 29 joints by default. Arms are only
  overridden while an arm gesture is actively playing or queued; as
  soon as the last keyframe finishes the arm slice (15..28) is handed
  back to the policy. This matches the canonical C++ deployment
  (`unitree_rl_mjlab/deploy/robots/g1/src/State_RLBase.cpp`), which
  writes all 29 joints of the policy output to lowcmd unmodified.
- Legs (0..11) and waist (12..14) are *always* under the RL policy.
- Only ONE publisher writes to rt/lowcmd, so no DDS race.

Why arm gestures don't break the policy
  Earlier versions clamped every gesture to ``default ± K*action_scale``
  (K=2.0) to keep arm `joint_pos_rel` inside the policy's training
  distribution. With shoulder action_scale=0.44 that capped each arm
  joint at ±0.88 rad — too narrow to express recognisable gestures
  (no real T-pose, no real overhead reach). The user's complaint
  "无法把动作做到正确的位置 / 失衡" (gestures can't reach the proper
  position; robot easily loses balance) was a direct consequence.

  The current approach removes that envelope and instead **masks the
  arm slice of the policy observation** while a gesture is active.
  Specifically, `_build_obs` zeroes `joint_pos_rel[15:29]`,
  `joint_vel_rel[15:29]`, and `last_raw_action[15:29]` whenever
  ``_arm_obs_masked == True``. The policy then sees "arms at default,
  not moving" and produces in-distribution leg/waist outputs, even
  while the arms physically swing all the way through the joint
  range. The arms themselves are still safety-clamped — but only to
  their *physical* MJCF limits (`ARM_JOINT_LIMITS`) and per-tick rate
  limit (`ARM_GESTURE_RATE_K_PER_SEC`).

Why only arms can be temporarily overridden
  Legs are responsible for balance; waist orientation feeds directly
  into the projected_gravity observation, so a commanded waist tilt
  would make the policy think "I'm falling" and drive the wrong
  recovery torques. Arms are mass-light and the obs-masking trick
  above keeps the legs' obs distribution clean regardless of arm pose,
  so brief gesture overlays are safe.

Anti-flying engagement gates
  When the controller starts (e.g. `g1_brain.apps.agent_main` boots),
  it does not hand control to the policy as soon as the boot ramp
  finishes. It first enters STANDBY, holds the trained default joint
  pose at full Kp, and waits until the robot is measurably settled
  (joint pose tol ENGAGE_POSE_TOL, joint velocity tol ENGAGE_VEL_TOL,
  body upright per ENGAGE_GRAV_Z, all true continuously for
  ENGAGE_HOLD_S). Only then is the policy engaged, and even its first
  POLICY_WARMUP_S of output is clipped + cosine-blended with the held
  default action so a single bad first inference can't slingshot a
  leg. Without this gate, agent_main used to engage the policy while
  the robot was still mid-air on the elastic band and the resulting
  OOD-ish obs caused the "robot flies away" behaviour the user kept
  having to work around with repeated MuJoCo resets.

Why only arms can be temporarily overridden:
  Legs are responsible for balance; waist orientation feeds directly
  into the projected_gravity observation, so a commanded waist tilt
  would make the policy think "I'm falling" and drive the wrong
  recovery torques. Arms are mass-light and the policy is robust to
  short, slow arm overrides (within the envelope above), so brief
  gesture overlays are safe.

Run order
---------
  Terminal 1:
      conda activate unitree
      cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
      python unitree_mujoco.py
      # robot starts at the trained default pose, suspended high up
      # by the elastic band (anchor at z=3, length=0). To bring it to
      # the ground:
      #   - press 8 a few times to lengthen the band (lower the robot);
      #   - press 7 if you over-shoot and want to lift it back up;
      #   - press 9 once on the ground to disable the band entirely.
      # The simulator's default-pose holding PD keeps the joints at
      # the trained pose throughout, so you never see the "robot
      # collapses to a sitting heap before I can launch the controller"
      # behaviour the older config produced.

  Terminal 2:
      conda activate unitree
      cd ~/unitree/unitree-notes/g1_sim_demo
      python g1_sim_rl_combo.py
      # wait for "[combo] policy engaged" then press keys

Walking keys:   w/s, a/d, q/e, r (stop), f (full forward)
Arm gestures:   1 wave R, 2 wave L, 3 hands up, 4 T-pose,
                5 salute, 6 clap, 7 guard, 8 punch combo, 0 release
System:         space (soften), ? (help), x (quit)
"""

from __future__ import annotations

import select
import sys
import termios
import threading
import time
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import yaml

try:
    import onnxruntime as ort
except ImportError as e:
    raise SystemExit(
        "[combo] onnxruntime is not installed in the current env. "
        "Run: pip install onnxruntime"
    ) from e

from unitree_sdk2py.core.channel import (
    ChannelFactoryInitialize,
    ChannelPublisher,
    ChannelSubscriber,
)
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_
from unitree_sdk2py.utils.crc import CRC
from unitree_sdk2py.utils.thread import RecurrentThread


# ---------------------------------------------------------------------------
# Joint indices (G1 29-DOF, PR mode). Same layout as g1_sim_keyboard.py.
# ---------------------------------------------------------------------------
G1_NUM_MOTOR = 29
ARM_START = 15        # joints 15..28 are arms (left 15..21, right 22..28)
ARM_END = 29          # exclusive
ARM_DIM = ARM_END - ARM_START   # 14


class J:
    LeftHipPitch       = 0
    LeftHipRoll        = 1
    LeftHipYaw         = 2
    LeftKnee           = 3
    LeftAnklePitch     = 4
    LeftAnkleRoll      = 5
    RightHipPitch      = 6
    RightHipRoll       = 7
    RightHipYaw        = 8
    RightKnee          = 9
    RightAnklePitch    = 10
    RightAnkleRoll     = 11
    WaistYaw           = 12
    WaistRoll          = 13
    WaistPitch         = 14
    LeftShoulderPitch  = 15
    LeftShoulderRoll   = 16
    LeftShoulderYaw    = 17
    LeftElbow          = 18
    LeftWristRoll      = 19
    LeftWristPitch     = 20
    LeftWristYaw       = 21
    RightShoulderPitch = 22
    RightShoulderRoll  = 23
    RightShoulderYaw   = 24
    RightElbow         = 25
    RightWristRoll     = 26
    RightWristPitch    = 27
    RightWristYaw      = 28


# Resolve the policy artifact directory relative to *this script*, not to
# $HOME, so the demo works regardless of where the unitree-notes repo is
# cloned. The script lives at <repo_root>/g1_sim_demo/g1_sim_rl_combo.py,
# so the repo root is its parent's parent.
_REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = (
    _REPO_ROOT
    / "unitree_rl_mjlab/deploy/robots/g1"
    / "config/policy/velocity/v0"
)
POLICY_ONNX = POLICY_DIR / "exported" / "policy.onnx"
POLICY_YAML = POLICY_DIR / "params" / "deploy.yaml"


# ---------------------------------------------------------------------------
# Deployment params loaded from deploy.yaml (matches g1_sim_rl_walk.py)
# ---------------------------------------------------------------------------
class DeployCfg:
    def __init__(self, yaml_path: Path):
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        self.step_dt: float = float(cfg["step_dt"])
        self.kp = np.asarray(cfg["stiffness"], dtype=np.float64)
        self.kd = np.asarray(cfg["damping"], dtype=np.float64)
        self.default_q = np.asarray(cfg["default_joint_pos"], dtype=np.float64)

        action = cfg["actions"]["JointPositionAction"]
        self.action_scale = np.asarray(action["scale"], dtype=np.float64)
        self.action_offset = np.asarray(action["offset"], dtype=np.float64)

        cmd_ranges = cfg["commands"]["base_velocity"]["ranges"]
        self.vx_range = tuple(cmd_ranges["lin_vel_x"])
        self.vy_range = tuple(cmd_ranges["lin_vel_y"])
        self.wz_range = tuple(cmd_ranges["ang_vel_z"])

        self.gait_period = float(
            cfg["observations"]["gait_phase"]["params"]["period"]
        )

        for name, arr in [
            ("kp", self.kp), ("kd", self.kd),
            ("default_q", self.default_q),
            ("action_scale", self.action_scale),
            ("action_offset", self.action_offset),
        ]:
            if arr.shape != (G1_NUM_MOTOR,):
                raise ValueError(
                    f"deploy.yaml '{name}' has shape {arr.shape}, "
                    f"expected ({G1_NUM_MOTOR},)"
                )


# ---------------------------------------------------------------------------
# ONNX policy wrapper
# ---------------------------------------------------------------------------
class Policy:
    OBS_DIM = 98          # 3 + 3 + 3 + 2 + 29 + 29 + 29
    ACT_DIM = G1_NUM_MOTOR

    def __init__(self, onnx_path: Path):
        if not onnx_path.exists():
            raise FileNotFoundError(f"policy not found: {onnx_path}")
        self.session = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
        ins = self.session.get_inputs()
        outs = self.session.get_outputs()
        self.in_name = ins[0].name
        self.out_name = outs[0].name
        if ins[0].shape[-1] != self.OBS_DIM:
            raise RuntimeError(
                f"policy expects obs dim {ins[0].shape[-1]}, demo builds {self.OBS_DIM}."
            )
        if outs[0].shape[-1] != self.ACT_DIM:
            raise RuntimeError(
                f"policy outputs dim {outs[0].shape[-1]}, demo expects {self.ACT_DIM}."
            )

    def __call__(self, obs: np.ndarray) -> np.ndarray:
        x = obs.astype(np.float32, copy=False).reshape(1, self.OBS_DIM)
        y = self.session.run([self.out_name], {self.in_name: x})[0]
        return y.reshape(self.ACT_DIM)


# ---------------------------------------------------------------------------
# Quaternion math: rotate world vector into body frame using IMU quat [w,x,y,z]
# ---------------------------------------------------------------------------
def quat_rotate_inverse(quat_wxyz: np.ndarray, v_world: np.ndarray) -> np.ndarray:
    w, x, y, z = quat_wxyz
    vx, vy, vz = v_world
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    rx = vx - w * tx + (y * tz - z * ty)
    ry = vy - w * ty + (z * tx - x * tz)
    rz = vz - w * tz + (x * ty - y * tx)
    return np.array([rx, ry, rz], dtype=np.float64)


GRAVITY_W = np.array([0.0, 0.0, -1.0], dtype=np.float64)


# ---------------------------------------------------------------------------
# Arm gesture poses.
#
# Each gesture is encoded as a 14-D *absolute* target for the arm slice
# (joints 15..28). Targets only set the joints the gesture actually moves;
# unset joints stay at the policy's arm_rest. Values were chosen to
# reproduce the recognisable poses from the legacy g1_sim_keyboard.py demo
# (which the user remembers as "the gestures looked right") and are
# clamped at runtime by `_clamp_arm_to_safe_envelope` to stay inside the
# physical joint limits.
#
# The previous delta-encoded version capped each joint at ±2 * action_scale
# from default. action_scale for the shoulder is 0.44 rad, so a "full"
# gesture only moved the shoulder by 0.88 rad — too small to actually
# raise the arm overhead or do a real T-pose. The user observed
# "无法把动作做到正确的位置" (can't reach the proper position). Switching
# to absolute targets fixes that. To prevent the larger arm deviations
# from putting the *policy* observation OOD, `_build_obs` masks the arm
# slice of joint_pos_rel / joint_vel_rel / last_raw_action with zeros
# while a gesture override is active — see ``_arm_obs_masked`` flag.
# Sign convention (matches the MJCF):
#   shoulder_pitch  − = arm forward/up
#   shoulder_roll   + = arm out (left side; mirrored on right)
#   elbow           + = elbow bent
#   wrist_pitch     − = palm down / forward
# ---------------------------------------------------------------------------
def _slot(j: int) -> int:
    """Map global joint index (15..28) to arm-local index (0..13)."""
    return j - ARM_START


def _abs_pose_from(arm_rest: np.ndarray, **overrides: float) -> np.ndarray:
    """Start from the policy's arm_rest and override the named joints.

    `overrides` keys must be attribute names on `J` (e.g. RightShoulderPitch).
    Returns a fresh 14-D pose; arm_rest is not mutated.
    """
    p = arm_rest.copy()
    for name, value in overrides.items():
        idx = getattr(J, name)
        p[_slot(idx)] = float(value)
    return p


def wave_right_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Right arm out and bent to the side, ready to wave."""
    return _abs_pose_from(
        arm_rest,
        RightShoulderPitch=-0.4,
        RightShoulderRoll=-1.2,
        RightElbow=1.4,
    )


def wave_left_pose(arm_rest: np.ndarray) -> np.ndarray:
    return _abs_pose_from(
        arm_rest,
        LeftShoulderPitch=-0.4,
        LeftShoulderRoll=1.2,
        LeftElbow=1.4,
    )


def hands_up_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Both arms straight up overhead. shoulder_pitch ≈ -π/2 sends the arm
    from "down by side" (positive default 0.35) all the way overhead."""
    return _abs_pose_from(
        arm_rest,
        LeftShoulderPitch=-1.6,
        RightShoulderPitch=-1.6,
        LeftElbow=0.0,
        RightElbow=0.0,
    )


def t_pose_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Both arms out to the sides at shoulder height."""
    return _abs_pose_from(
        arm_rest,
        LeftShoulderRoll=1.5,
        RightShoulderRoll=-1.5,
        LeftElbow=0.0,
        RightElbow=0.0,
    )


def salute_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Right hand to forehead."""
    return _abs_pose_from(
        arm_rest,
        RightShoulderPitch=-0.6,
        RightShoulderRoll=-0.4,
        RightElbow=1.55,
        RightWristPitch=-0.3,
    )


def clap_pose(arm_rest: np.ndarray) -> np.ndarray:
    return _abs_pose_from(
        arm_rest,
        LeftShoulderPitch=-0.8,
        LeftShoulderRoll=0.4,
        LeftElbow=1.2,
        RightShoulderPitch=-0.8,
        RightShoulderRoll=-0.4,
        RightElbow=1.2,
    )


def guard_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Boxer guard: both fists in front of face."""
    return _abs_pose_from(
        arm_rest,
        LeftShoulderPitch=-0.6,
        LeftShoulderRoll=0.5,
        LeftElbow=1.4,
        RightShoulderPitch=-0.6,
        RightShoulderRoll=-0.5,
        RightElbow=1.4,
    )


def punch_right_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Right arm extended forward (jab), left arm in guard."""
    p = guard_pose(arm_rest)
    p[_slot(J.RightShoulderPitch)] = -1.0
    p[_slot(J.RightShoulderRoll)]  = -0.1
    p[_slot(J.RightElbow)]         =  0.1
    return p


def punch_left_pose(arm_rest: np.ndarray) -> np.ndarray:
    p = guard_pose(arm_rest)
    p[_slot(J.LeftShoulderPitch)] = -1.0
    p[_slot(J.LeftShoulderRoll)]  =  0.1
    p[_slot(J.LeftElbow)]         =  0.1
    return p


# ---------------------------------------------------------------------------
# Action = ordered list of (duration_seconds, arm_pose_14d) keyframes.
# The arm controller blends the live "from" arm pose to the keyframe target
# over `duration` using cosine ease-in-out, then advances to the next.
# Every gesture ends with a keyframe back to ARM_REST so we hand control
# of the arms back to the policy default cleanly.
# ---------------------------------------------------------------------------
@dataclass
class ArmAction:
    key: str
    name: str
    keyframes: List[Tuple[float, np.ndarray]]


def hold(pose: np.ndarray, t: float) -> Tuple[float, np.ndarray]:
    return (t, pose.copy())


def build_arm_actions(arm_rest: np.ndarray,
                      arm_scale: np.ndarray) -> List[ArmAction]:
    """Build the gesture table.

    Each pose is an *absolute* 14-D arm target (see the gesture pose
    builders above). Targets are clamped at runtime by
    `_clamp_arm_to_safe_envelope` to physical joint limits, and the
    policy obs has its arm slice masked while the override is active so
    expressive arm motion does not put the policy OOD on legs.

    Static poses (hands_up, T-pose, salute, guard) use 2.0–2.5s blends so
    joint_vel during the swing is moderate and the legs have time to
    redistribute load. Dynamic poses (clap, punch) keep their snappy
    timing because they're inside the per-tick rate limit anyway.

    The `arm_scale` argument is kept for backward compatibility but is
    no longer used to scale gesture amplitudes.
    """
    del arm_scale  # unused — gestures are absolute now

    wave_r  = wave_right_pose(arm_rest)
    wave_l  = wave_left_pose(arm_rest)
    hands_u = hands_up_pose(arm_rest)
    t_p     = t_pose_pose(arm_rest)
    sal     = salute_pose(arm_rest)
    clp     = clap_pose(arm_rest)
    grd     = guard_pose(arm_rest)
    pr      = punch_right_pose(arm_rest)
    pl      = punch_left_pose(arm_rest)

    return [
        ArmAction("1", "wave right arm",
                  [(1.8, wave_r), hold(wave_r, 0.8),
                   (1.8, arm_rest)]),
        ArmAction("2", "wave left arm",
                  [(1.8, wave_l), hold(wave_l, 0.8),
                   (1.8, arm_rest)]),
        ArmAction("3", "hands up (cheer)",
                  [(2.0, hands_u), hold(hands_u, 1.0),
                   (2.0, arm_rest)]),
        ArmAction("4", "T-pose",
                  [(2.2, t_p), hold(t_p, 1.2),
                   (2.2, arm_rest)]),
        ArmAction("5", "salute",
                  [(1.5, sal), hold(sal, 1.5),
                   (1.5, arm_rest)]),
        ArmAction("6", "clap (twice)",
                  [(1.2, clp), (0.6, arm_rest),
                   (0.6, clp), (1.2, arm_rest)]),
        ArmAction("7", "boxer guard",
                  [(1.5, grd), hold(grd, 0.8),
                   (1.5, arm_rest)]),
        ArmAction("8", "punch combo (jab L+R)",
                  [(1.0, grd),
                   (0.4, pr), (0.35, grd),
                   (0.4, pl), (0.35, grd),
                   (1.2, arm_rest)]),
    ]


# ---------------------------------------------------------------------------
# Combo controller: RL legs + waist, keyboard arms.
# ---------------------------------------------------------------------------
class ComboController:
    LOWSTATE_TIMEOUT = 0.2     # seconds; if no lowstate, hold default pose

    # Per-arm-joint physical limits (rad). Sourced from g1_29dof.xml's
    # <joint range=...> attributes, then shrunk by ~5% on each side so the
    # commanded target never sits *exactly* on the soft-stop (which causes
    # the actuator to fight a hard wall and emit large reaction forces).
    # Indices 0..13 correspond to ARM_START..ARM_START+13 (i.e. left arm
    # then right arm in the same order as the deploy.yaml joint table).
    ARM_JOINT_LIMITS: tuple = (
        (-3.05, 2.65),   # 15 LeftShoulderPitch  (xml -3.0892, 2.6704)
        (-1.55, 2.20),   # 16 LeftShoulderRoll   (xml -1.5882, 2.2515)
        (-2.55, 2.55),   # 17 LeftShoulderYaw    (xml -2.618 , 2.618 )
        (-1.00, 2.05),   # 18 LeftElbow          (xml -1.0472, 2.0944)
        (-1.95, 1.95),   # 19 LeftWristRoll      (xml -1.9722, 1.9722)
        (-1.55, 1.55),   # 20 LeftWristPitch     (xml -1.6144, 1.6144)
        (-1.55, 1.55),   # 21 LeftWristYaw       (xml -1.6144, 1.6144)
        (-3.05, 2.65),   # 22 RightShoulderPitch
        (-2.20, 1.55),   # 23 RightShoulderRoll  (xml -2.2515, 1.5882)
        (-2.55, 2.55),   # 24 RightShoulderYaw
        (-1.00, 2.05),   # 25 RightElbow
        (-1.95, 1.95),   # 26 RightWristRoll
        (-1.55, 1.55),   # 27 RightWristPitch
        (-1.55, 1.55),   # 28 RightWristYaw
    )

    # `ARM_GESTURE_K` previously gated the *gesture amplitude* itself (clamp
    # commanded arm pose to default ± K*action_scale). That envelope is too
    # tight to express recognisable gestures (shoulder action_scale=0.44,
    # so K=2 caps the shoulder at ±0.88 rad — not enough for a real T-pose
    # or hands-up). Now gestures are clamped only to the *physical* joint
    # range (ARM_JOINT_LIMITS); the OOD risk this used to guard against is
    # eliminated by masking the arm slice of the policy's observation
    # while a gesture is active (see `_arm_obs_masked` and `_build_obs`).
    #
    # ARM_GESTURE_K is still used for one thing: clipping the value we
    # write into `last_raw_action[15:29]` so the next obs's last_action
    # entry stays in roughly the same magnitude range as the policy's own
    # outputs (raw_action ∈ ~[-1, 1]). Capping at K=4 keeps the
    # reverse-mapped action bounded even when the commanded arm pose
    # exceeds default ± 4*scale. Since the policy itself is fed zero in
    # those slots when the override is active, this is mostly cosmetic.
    ARM_GESTURE_K = 4.0

    # Per-tick maximum *change* in commanded arm angle, in units of
    # action_scale. Even if the gesture target is within the safe envelope,
    # a too-fast blend produces a `joint_vel_rel` spike that the policy
    # was never trained on. Cap the rate; the gesture's stated duration is
    # still respected unless it would violate this cap.
    ARM_GESTURE_RATE_K_PER_SEC = 4.0

    # ---- Engagement gating (anti-"flying" net) ------------------------
    # Boot ramp duration (measured pose -> default_q with reduced Kp).
    BOOT_DUR_S = 5.0
    # Kp scale at the start of the boot ramp; reaches 1.0 by the end.
    BOOT_KP_FLOOR = 0.3
    # After boot ramp finishes, the controller does NOT immediately hand
    # control to the policy. Instead it requires the robot to be:
    #   - at default_q within `ENGAGE_POSE_TOL` rad (per joint),
    #   - quiescent (|dq| < ENGAGE_VEL_TOL rad/s per joint) for at least
    #     ENGAGE_HOLD_S seconds,
    #   - upright (gravity_proj_z < ENGAGE_GRAV_Z, more negative = more upright).
    # Until those gates pass, the controller keeps publishing the held
    # default pose at full Kp instead of activating the policy. This
    # eliminates the "flying" startup transient where the policy was
    # activated while the robot was still mid-air on the elastic band, or
    # mid-recovery from a partial collapse.
    #
    # NOTE on tightening (2026-05-06): the previous gates (-0.85 / 0.8 s)
    # were tight enough that engagement happened while the body was still
    # marginally tilted; the policy then immediately produced raw_action
    # values that pushed gz from -0.85 to -0.50 within seconds. We now
    # require near-vertical (-0.95 ≈ 18° max tilt) held for 1.5 s before
    # the policy takes over. Combined with the stand-still bypass (see
    # `_tick`), the robot enters the policy phase only when it is genuinely
    # stable, and never relies on the policy to keep it standing still.
    ENGAGE_POSE_TOL = 0.08    # rad (per joint)
    ENGAGE_VEL_TOL = 0.30     # rad/s (per joint)
    ENGAGE_HOLD_S = 1.5
    ENGAGE_GRAV_Z = -0.95
    # Hard ceiling on time spent in the "holding default_q, waiting to
    # engage" state. After this many seconds since boot ramp finished we
    # engage the policy regardless, so the robot can't stall forever in
    # held-pose mode if the user never reaches a perfect quiescent state.
    # NOTE: this is generous on purpose — operators normally lower the
    # elastic band manually before launching agent_main, and this timer
    # only kicks in if everything else is wedged.
    ENGAGE_TIMEOUT_S = 30.0

    # During the first POLICY_WARMUP_S after engagement, the raw policy
    # output is hard-clipped to ±POLICY_WARMUP_CLIP and blended with the
    # held default action with a cosine ease-in. This protects against a
    # bad first action from a still-settling state estimator (e.g. IMU
    # gyro spike at hand-off) propagating into a runaway leg torque.
    POLICY_WARMUP_S = 0.6
    POLICY_WARMUP_CLIP = 0.8

    # ---- Stand-still bypass (anti-"can't stand still") ----------------
    # The trained velocity-tracking policy is marginally stable at zero
    # command in this MuJoCo deployment: with cmd=(0,0,0) and gait_phase
    # zeroed, the MLP still emits raw_action values of ~±0.5 on the leg
    # joints, which the action_scale (0.55 rad on hip/knee) blows up into
    # ±0.3 rad joint targets. The robot wobbles gz=-0.95→-0.50 within ~30 s
    # and falls. Diagnosis from the 2026-05-06 logs: the wobble starts
    # purely from policy execution — no walk command, no LLM call, no
    # auto-trigger event. The bridge's seed default-pose PD (used during
    # BOOT/STANDBY) keeps the robot stable, so the safe path is to keep
    # using that PD whenever no walking command is active.
    #
    # When ||cmd|| < STAND_CMD_THRESH we therefore bypass the policy and
    # publish default_q at full Kp (matching the bridge's behaviour during
    # STANDBY). The policy is only re-engaged when an explicit walk or
    # turn command lands. We do NOT lose any capability: the brain can
    # still walk/turn/gesture; it just can't ask the policy to "stand
    # still while taking small balance corrections", which the policy in
    # this build can't actually do well anyway.
    STAND_CMD_THRESH = 0.08    # ||cmd||₂ below this == "no walk command"
    # Hysteresis margin so transient brain-call latency at cmd=0 doesn't
    # flip in/out of policy mode. Once we're in policy mode we stay until
    # ||cmd|| < STAND_CMD_THRESH for at least STAND_HYST_HOLD_S.
    STAND_HYST_HOLD_S = 0.3
    # Cosine-eased blend from the policy's last q_target to default_q on
    # policy->stand transition. Without this, ending a walk mid-stride
    # (one leg in swing, body shifted) snaps q_target to default_q at
    # full Kp, the PD whips both legs straight, and the robot tips
    # forward over a few seconds (observed 2026-05-06: walk vx=0.2 dur=1.0
    # ends at t=32.2, gravity_z trips -0.81 at t=36.0). Same idea as the
    # BOOT phase's cosine ramp from measured pose -> default_q.
    STAND_WINDDOWN_S = 0.5

    def __init__(self, cfg: DeployCfg, policy: Policy):
        self.cfg = cfg
        self.policy = policy

        # Cache arm slices of the deploy params for the override math.
        self.arm_offset = self.cfg.action_offset[ARM_START:ARM_END].copy()
        self.arm_scale = self.cfg.action_scale[ARM_START:ARM_END].copy()

        self.low_cmd = unitree_hg_msg_dds__LowCmd_()
        self.low_state: Optional[LowState_] = None
        self.last_state_time = 0.0
        self.first_state_received = False
        self.mode_machine = 0
        self.crc = CRC()

        # Walking command (set by keyboard thread).
        self._cmd_lock = threading.Lock()
        self._cmd = np.zeros(3, dtype=np.float64)   # [vx, vy, wz]

        # RL state.
        self.last_raw_action = np.zeros(G1_NUM_MOTOR, dtype=np.float64)
        self.global_phase = 0.0

        # Boot ramp (measured pose -> default_q). The controller goes
        # through these phases in order:
        #
        #   BOOT (boot_dur seconds): blend measured pose -> default_q with
        #     Kp ramped from BOOT_KP_FLOOR -> 1.0 (cosine ease).
        #   STANDBY: hold default_q at full Kp, waiting for the engagement
        #     gates (pose / velocity / gravity / hold-time) to pass. This
        #     is the new "anti-flying" gate — without it the policy used
        #     to take over while the robot was still mid-air on the
        #     elastic band, fed garbage actions to the legs, and the
        #     robot "flew around" needing repeated MuJoCo resets.
        #   POLICY: policy controls all 29 joints. The first POLICY_WARMUP_S
        #     blends policy output with the held default action and clips
        #     raw_action to ±POLICY_WARMUP_CLIP so a single bad inference
        #     can't slingshot a leg.
        self.boot_q_from: Optional[np.ndarray] = None
        self.boot_t = 0.0
        self.boot_dur = self.BOOT_DUR_S
        self.boot_kp_floor = self.BOOT_KP_FLOOR
        self.policy_active = False
        # Phase tracking for STANDBY / POLICY logic.
        self._boot_done = False
        self._standby_since: Optional[float] = None
        self._engage_quiet_since: Optional[float] = None
        self._engage_at: Optional[float] = None    # time policy was engaged

        # Arm gesture state.
        # arm_rest is the policy's default arm pose; final fall-back target
        # the gesture queue ramps to before releasing arms back to the policy.
        self.arm_rest = self.cfg.default_q[ARM_START:ARM_END].copy()
        self.arm_q_target = self.arm_rest.copy()       # last fully-blended pose
        self.arm_blend_from: Optional[np.ndarray] = None
        self.arm_blend_to: Optional[np.ndarray] = None
        self.arm_blend_dur = 0.0
        self.arm_blend_t = 0.0
        self.arm_queue: List[Tuple[float, np.ndarray]] = []
        # When False the policy commands the arms directly. When True the
        # arm slice of q_target is replaced by `arm_q_target`. Flips False
        # automatically once the last queued keyframe finishes.
        self._arm_override_active = False
        self._arm_lock = threading.Lock()
        # Snapshot of the last 14-D arm slice we actually wrote to lowcmd;
        # used by _rate_limit_arm_step. Seeded lazily in _tick.
        self._last_arm_q_published: Optional[np.ndarray] = None
        # While an arm gesture is active the policy obs has its arm slice
        # masked (joint_pos_rel / joint_vel_rel / last_raw_action all set
        # to 0 for the 14 arm joints). This lets gestures be expressive
        # in absolute joint space without putting the policy OOD on legs.
        self._arm_obs_masked = False
        # Cached arm slice of action_offset / action_scale (== default_q
        # for arms / per-joint action scale). Used by the override math.
        self._arm_lo = np.array(
            [lo for (lo, _) in self.ARM_JOINT_LIMITS], dtype=np.float64
        )
        self._arm_hi = np.array(
            [hi for (_, hi) in self.ARM_JOINT_LIMITS], dtype=np.float64
        )

        # Soft Kp scale.
        self.kp_scale = 1.0
        self._soften_target = 1.0
        self._soften_step = 0.0
        self._soften_steps_left = 0

        # ---- Stand-still bypass / safe-hold state -------------------------
        # When True the controller publishes default_q at full Kp regardless
        # of the policy phase or commanded velocity. Set by the watchdog
        # manager when the FSM enters EMERGENCY_STOP so a pose-watchdog trip
        # actually stops the policy from flailing (without this hook, the
        # policy keeps running in EMERGENCY_STOP and the robot keeps falling
        # until it's fully on the ground).
        self._safe_hold = False
        # Cached "currently in stand-still bypass" flag so we hold the policy
        # off across hysteresis (cmd briefly bumps above threshold then
        # returns to 0 — without hysteresis we'd flap into policy mode for
        # a fraction of a second and back). _stand_below_thresh_since is the
        # monotonic timestamp at which ||cmd|| first dropped below
        # STAND_CMD_THRESH while in policy mode; None means "not currently
        # below threshold".
        self._stand_active = True
        self._stand_below_thresh_since: Optional[float] = None
        # Snapshot of the most recent policy-produced q_target (pre-arm-overlay).
        # Used to blend smoothly to default_q when a walk command ends so we
        # don't snap legs from a mid-stride pose to default at full Kp.
        self._last_policy_q_target: Optional[np.ndarray] = None
        # Wind-down blend state. _wind_down_at is set on the policy->stand
        # transition; while it's not None we're cosine-blending q_target from
        # _wind_down_from -> default_q. Cleared once the blend completes or
        # if the user issues a new walk before it finishes.
        self._wind_down_from: Optional[np.ndarray] = None
        self._wind_down_at: Optional[float] = None

        self._stop = threading.Event()

    # ----- DDS plumbing
    def init_dds(self):
        self.cmd_pub = ChannelPublisher("rt/lowcmd", LowCmd_)
        self.cmd_pub.Init()
        self.state_sub = ChannelSubscriber("rt/lowstate", LowState_)
        self.state_sub.Init(self._on_state, 10)

    def _on_state(self, msg: LowState_):
        self.low_state = msg
        self.last_state_time = time.monotonic()
        if not self.first_state_received:
            self.mode_machine = msg.mode_machine
            self.first_state_received = True

    # ----- public API
    def set_command(self, vx: float, vy: float, wz: float):
        vx = float(np.clip(vx, *self.cfg.vx_range))
        vy = float(np.clip(vy, *self.cfg.vy_range))
        wz = float(np.clip(wz, *self.cfg.wz_range))
        with self._cmd_lock:
            self._cmd[:] = (vx, vy, wz)

    def get_command(self) -> np.ndarray:
        with self._cmd_lock:
            return self._cmd.copy()

    def push_arm_action(self, keyframes: List[Tuple[float, np.ndarray]]):
        """Replace any in-flight gesture with this one. The first keyframe
        blends from the *live* measured arm pose so engaging the override
        from a policy-controlled state doesn't snap the arms.

        Every keyframe target is run through `_clamp_arm_to_safe_envelope`
        before queueing — defense-in-depth so even hand-built gesture
        tables can't drive an arm joint past its physical limit. The
        policy obs is also masked while the override is active, so any
        arm motion within the joint range is OOD-safe by construction.
        """
        with self._arm_lock:
            # Seed arm_q_target with where the arms actually are right now,
            # otherwise (if the policy was controlling them and had them
            # swung mid-gait) the blend would start from a stale value and
            # cause a position step. Clamp the snapshot too, in case the
            # policy was already commanding a fairly large arm swing.
            self.arm_q_target = self._clamp_arm_to_safe_envelope(
                self._read_current_arm_q()
            )
            self.arm_queue = [
                (float(d), self._clamp_arm_to_safe_envelope(p.copy()))
                for d, p in keyframes
            ]
            self.arm_blend_from = None
            self.arm_blend_to = None
            self.arm_blend_dur = 0.0
            self.arm_blend_t = 0.0
            self._arm_override_active = True

    def release_arms(self):
        """If a gesture is in progress, ramp arms back to rest and hand
        them back to the policy. If arms are already policy-controlled
        this is a no-op (don't grab arms just to release them).

        Uses a 1.5s ramp; with the rate-limit + envelope clamp this
        produces a well-conditioned final blend regardless of where the
        arms were when release_arms was called."""
        with self._arm_lock:
            if not self._arm_override_active and not self.arm_queue:
                return
            self.arm_q_target = self._clamp_arm_to_safe_envelope(
                self._read_current_arm_q()
            )
            self.arm_queue = [(1.5, self.arm_rest.copy())]
            self.arm_blend_from = None
            self.arm_blend_to = None
            self.arm_blend_dur = 0.0
            self.arm_blend_t = 0.0
            self._arm_override_active = True

    def soften(self, target_scale: float = 0.0, duration: float = 1.0):
        steps = int(max(duration, 1e-3) / self.cfg.step_dt)
        self._soften_target = float(target_scale)
        self._soften_step = (self._soften_target - self.kp_scale) / max(steps, 1)
        self._soften_steps_left = steps

    def set_safe_hold(self, active: bool) -> None:
        """Toggle the safe-hold override.

        When True, ``_tick`` ignores the policy and publishes ``default_q``
        at full Kp every cycle. The watchdog manager calls this with
        ``True`` when the FSM enters EMERGENCY_STOP so a pose-watchdog trip
        actually stops the policy from sending bad targets, and with
        ``False`` once the FSM auto-recovers back to STANDING. Idempotent
        and thread-safe (a single Python attribute write under the GIL).

        On the next tick after `set_safe_hold(False)` the controller goes
        back through the normal flow: if a walk command is active it'll
        re-engage the policy; otherwise the stand-still bypass keeps it
        on default_q anyway.
        """
        prev = self._safe_hold
        self._safe_hold = bool(active)
        if prev and not self._safe_hold:
            # Coming out of safe-hold — restart the engagement-quiescence
            # tracker so we re-validate the gates instead of assuming the
            # robot is still in the previous "engaged" state. We deliberately
            # don't force `policy_active = False` here so a walk command
            # arriving immediately after recovery isn't ignored: the
            # stand-still bypass below still keeps q_target at default_q
            # while ||cmd|| is small, so this is safe.
            self._engage_quiet_since = None
        if active and not prev:
            # Reset the stand-still tracker so a future ||cmd||>0 bump has
            # to satisfy hysteresis cleanly.
            self._stand_below_thresh_since = None
            self._stand_active = True
            # Drop the policy q_target snapshot — after EMERGENCY_STOP the
            # robot is on the ground, so blending toward default_q from a
            # fall pose at full Kp would be unsafe. The safe-hold branch
            # publishes default_q directly until the FSM recovers.
            self._last_policy_q_target = None
            self._wind_down_from = None
            self._wind_down_at = None

    def start(self):
        print("[combo] waiting for first /rt/lowstate ...")
        while not self.first_state_received:
            time.sleep(0.05)
        measured = np.array(
            [self.low_state.motor_state[i].q for i in range(G1_NUM_MOTOR)],
            dtype=np.float64,
        )
        self.boot_q_from = measured.copy()
        # Seed the arm overlay so it matches the boot ramp endpoint.
        self.arm_q_target = self.cfg.default_q[ARM_START:ARM_END].copy()
        self.boot_t = 0.0
        self._boot_done = False
        self._standby_since = None
        self._engage_quiet_since = None
        self._engage_at = None
        self.policy_active = False
        self.last_raw_action[:] = 0.0
        self.global_phase = 0.0
        # Start in stand-still mode. The policy is only used while a walk
        # command is active (||cmd||₂ > STAND_CMD_THRESH); see the
        # stand-still bypass in `_tick`. This is what eliminates the
        # "robot can't stand still" failure mode where the velocity policy
        # at cmd=0 produced ±0.3 rad joint wobble and tipped over.
        self._stand_active = True
        self._stand_below_thresh_since = None
        self._last_policy_q_target = None
        self._wind_down_from = None
        self._wind_down_at = None
        self._safe_hold = False
        # Start with reduced Kp; _tick ramps it up to 1.0 over boot_dur.
        self.kp_scale = self.boot_kp_floor

        self._thread = RecurrentThread(
            interval=self.cfg.step_dt, target=self._tick, name="combo_control"
        )
        self._thread.Start()
        print(
            f"[combo] mode_machine={self.mode_machine}. "
            f"Ramping to default pose over {self.boot_dur:.1f} s, "
            f"then waiting for the robot to settle (pose tol "
            f"{self.ENGAGE_POSE_TOL:.2f} rad / vel tol "
            f"{self.ENGAGE_VEL_TOL:.2f} rad·s, hold "
            f"{self.ENGAGE_HOLD_S:.1f} s) before engaging the policy."
        )

    def stop_and_settle(self):
        self.release_arms()
        self.soften(target_scale=0.0, duration=1.0)
        time.sleep(1.2)
        self._stop.set()

    # ----- 50 Hz tick
    def _tick(self):
        if self._stop.is_set() or not self.first_state_received:
            return

        # Soften ramp.
        if self._soften_steps_left > 0:
            self.kp_scale += self._soften_step
            self._soften_steps_left -= 1
            if self._soften_steps_left == 0:
                self.kp_scale = self._soften_target

        # Watchdog: if simulator stops sending state, hold default pose.
        if time.monotonic() - self.last_state_time > self.LOWSTATE_TIMEOUT:
            self._publish(self.cfg.default_q)
            return

        # ---- Safe-hold override (set by WatchdogManager on EMERGENCY_STOP).
        # Skip BOOT/STANDBY/POLICY entirely and just publish default_q at
        # full Kp. This makes a pose-watchdog trip *actually* stop the
        # policy instead of letting it keep flailing while the FSM
        # transitions are mere bookkeeping. We still allow the existing
        # arm overlay so a queued release_arms() during shutdown blends
        # cleanly to rest.
        if self._safe_hold:
            q_des = self.cfg.default_q.copy()
            self.kp_scale = 1.0
            arm_q = self._advance_arms()
            if arm_q is not None:
                arm_q = self._clamp_arm_to_safe_envelope(arm_q)
                arm_q = self._rate_limit_arm_step(arm_q)
                q_des[ARM_START:ARM_END] = arm_q
            self._publish(q_des)
            self._last_arm_q_published = q_des[ARM_START:ARM_END].copy()
            return

        # ---- BOOT phase: blend from measured pose to default_q with
        # gradually increasing Kp.
        if not self._boot_done:
            self.boot_t += self.cfg.step_dt
            if self.boot_t >= self.boot_dur:
                self._boot_done = True
                self._standby_since = time.monotonic()
                self.kp_scale = 1.0
                self._publish(self.cfg.default_q)
                return
            s = 0.5 - 0.5 * np.cos(np.pi * (self.boot_t / self.boot_dur))
            q_des = (1.0 - s) * self.boot_q_from + s * self.cfg.default_q
            self.kp_scale = self.boot_kp_floor + (1.0 - self.boot_kp_floor) * s
            self._publish(q_des)
            return

        # ---- STANDBY phase: hold default_q at full Kp until the robot
        # is settled enough to safely hand off to the policy. This is the
        # critical fix for the "robot flies away when agent_main starts"
        # issue: previously the policy activated 5 s after the first
        # lowstate regardless of pose / velocity / orientation, so if the
        # robot was still mid-air on the elastic band or recovering from
        # a partial collapse, the policy was fed garbage and produced
        # garbage. Now we require a measurable quiescent period first.
        if not self.policy_active:
            if self._can_engage_policy():
                self.policy_active = True
                self._engage_at = time.monotonic()
                self.kp_scale = 1.0
                # Reset last_raw_action so the first obs after engagement
                # has a clean self-consistent (joint_pos_rel ≈ 0,
                # last_action == 0) baseline.
                self.last_raw_action[:] = 0.0
                self.global_phase = 0.0
                # Re-arm the stand-still bypass on engage. The policy stays
                # in "standing on default_q" mode until ||cmd|| crosses
                # STAND_CMD_THRESH; this matches the bridge's STANDBY hold
                # so engagement is a clean continuation, not a hand-off.
                self._stand_active = True
                self._stand_below_thresh_since = None
                print(
                    "[combo] policy engaged (idling on default_q). "
                    "wsadqe to walk; 1-8 arm gestures; 0 release."
                )
                self._publish(self.cfg.default_q)
                return
            # Not yet eligible — keep holding default pose.
            self._publish(self.cfg.default_q)
            return

        # ---- POLICY phase ----
        # Stand-still bypass with hysteresis. The trained velocity-tracking
        # policy is marginally stable at zero command in this MuJoCo
        # deployment — it produces ~±0.5 raw_action even when fed cmd=0 +
        # gait=0, and the leg action_scale (0.55 rad/joint) blows that into
        # ±0.3 rad joint targets. Robot wobbles and falls within 30 s.
        # When ||cmd|| has been below STAND_CMD_THRESH for STAND_HYST_HOLD_S
        # we bypass the policy and publish default_q (matches the bridge's
        # seed-PD behaviour, which keeps the robot stable).
        cmd = self.get_command()
        cmd_norm = float(np.linalg.norm(cmd))
        now = time.monotonic()
        prev_stand_active = self._stand_active
        if cmd_norm < self.STAND_CMD_THRESH:
            if self._stand_below_thresh_since is None:
                self._stand_below_thresh_since = now
            if (
                self._stand_active
                or (now - self._stand_below_thresh_since) >= self.STAND_HYST_HOLD_S
            ):
                self._stand_active = True
        else:
            # Walk command is live — leave stand mode immediately so the
            # policy can react without delay.
            self._stand_below_thresh_since = None
            self._stand_active = False

        # Detect transitions to set up the policy<->stand handoff blends.
        if self._stand_active and not prev_stand_active:
            # Policy -> stand: snapshot the policy's last q_target so the
            # stand branch below can cosine-blend to default_q instead of
            # snapping. Without this the legs whip from mid-stride pose to
            # default at full Kp and the body tips forward.
            if self._last_policy_q_target is not None:
                self._wind_down_from = self._last_policy_q_target.copy()
                self._wind_down_at = now
        elif (not self._stand_active) and prev_stand_active:
            # Stand -> policy: cancel any in-flight wind-down and re-arm the
            # policy warm-up window so the first inference after a quiescent
            # stretch (where last_raw_action and gait_phase were zeroed)
            # gets the same cosine ease-in / clip protection as the very
            # first engagement.
            self._wind_down_from = None
            self._wind_down_at = None
            self._engage_at = now

        if self._stand_active:
            in_blend = (
                self._wind_down_at is not None
                and self._wind_down_from is not None
            )
            if in_blend:
                t_blend = now - self._wind_down_at
                if t_blend < self.STAND_WINDDOWN_S:
                    s = 0.5 - 0.5 * np.cos(
                        np.pi * (t_blend / self.STAND_WINDDOWN_S)
                    )
                    q_target = (
                        (1.0 - s) * self._wind_down_from
                        + s * self.cfg.default_q
                    )
                else:
                    # Blend complete — fall through to the steady-state
                    # default_q hold.
                    in_blend = False
                    self._wind_down_from = None
                    self._wind_down_at = None
            if not in_blend:
                q_target = self.cfg.default_q.copy()
                # Reset gait phase + last_action so when the policy is later
                # re-engaged its first obs has joint_pos_rel ≈ 0,
                # joint_vel_rel ≈ 0, last_action == 0, gait == (0,0). This
                # keeps the first inference in-distribution. We deliberately
                # do NOT reset these mid-blend, so a quick stand->policy
                # flip during the wind-down still has a valid last_action
                # context to feed back to the policy.
                self.last_raw_action[:] = 0.0
                self.global_phase = 0.0
        else:
            obs = self._build_obs()
            raw_action = self.policy(obs)

            # Warm-up gating: during the first POLICY_WARMUP_S after engagement,
            # blend the raw policy action with the held default action with a
            # cosine ease-in, and clip its magnitude. A bad first inference
            # (e.g. from a still-settling state estimator) can otherwise spike
            # a leg torque large enough to launch the robot.
            if self._engage_at is not None:
                t_since_engage = now - self._engage_at
                if t_since_engage < self.POLICY_WARMUP_S:
                    w = 0.5 - 0.5 * np.cos(
                        np.pi * (t_since_engage / self.POLICY_WARMUP_S)
                    )
                    clipped = np.clip(
                        raw_action,
                        -self.POLICY_WARMUP_CLIP, self.POLICY_WARMUP_CLIP,
                    )
                    # Held action is implicitly zero (default_q == offset).
                    raw_action = w * clipped

            q_target = raw_action * self.cfg.action_scale + self.cfg.action_offset
            # Default: feed back exactly what the policy commanded.
            self.last_raw_action[:] = raw_action
            # Snapshot before the arm overlay so a subsequent policy->stand
            # transition blends the legs from where the policy actually had
            # them (a gesture might be overriding arms, but for stability
            # all that matters is the leg slice).
            self._last_policy_q_target = q_target.copy()

        # ---- Arm overlay: only override q_target[15:29] if a gesture is
        # actively playing. Otherwise the policy keeps full control of the
        # arms (it learned to swing them for balance during walking).
        arm_q = self._advance_arms()
        if arm_q is not None:
            # Belt + suspenders: even though _advance_arms only emits poses
            # that came through clamp at queue time, also enforce the
            # envelope here in case a future change wires in another
            # source. Then rate-limit the per-tick change so a snapped
            # blend can't cause a joint_vel_rel spike larger than the
            # training distribution.
            arm_q = self._clamp_arm_to_safe_envelope(arm_q)
            arm_q = self._rate_limit_arm_step(arm_q)
            q_target[ARM_START:ARM_END] = arm_q

            # The policy obs has the arm slice masked (see _build_obs),
            # so it sees joint_pos_rel == 0 / last_action == 0 for all
            # arm joints regardless of the actual gesture amplitude.
            # That keeps the leg outputs in-distribution. We still write
            # `last_raw_action[ARM_START:ARM_END]` for diagnostics, but
            # use the *masked* value (0) so the next obs stays consistent
            # with what the policy was fed.
            self.last_raw_action[ARM_START:ARM_END] = 0.0
            self._arm_obs_masked = True
        else:
            self._arm_obs_masked = False

        self._publish(q_target)
        # Stash what we just published; rate limiter and restart-from-live
        # logic both want it.
        self._last_arm_q_published = q_target[ARM_START:ARM_END].copy()

    def _can_engage_policy(self) -> bool:
        """Decide if it's safe to hand control to the policy.

        Required conditions:
          - measured joint pose within ENGAGE_POSE_TOL of default_q;
          - measured joint velocities within ENGAGE_VEL_TOL;
          - body upright (gravity_proj_z < ENGAGE_GRAV_Z);
          - all of the above true continuously for ENGAGE_HOLD_S.

        If those gates haven't passed within ENGAGE_TIMEOUT_S of entering
        STANDBY we engage anyway — better to try than to stall forever
        when the user has set things up but happens to be just outside
        tolerance. Returns True when the controller should switch to the
        policy on the *next* tick.
        """
        s = self.low_state
        if s is None:
            return False
        now = time.monotonic()

        try:
            q = np.fromiter(
                (s.motor_state[i].q for i in range(G1_NUM_MOTOR)),
                dtype=np.float64, count=G1_NUM_MOTOR,
            )
            dq = np.fromiter(
                (s.motor_state[i].dq for i in range(G1_NUM_MOTOR)),
                dtype=np.float64, count=G1_NUM_MOTOR,
            )
        except Exception:  # noqa: BLE001
            return False
        # Pose / vel: only judge legs and waist (joints 0..14). Arms get
        # held by the same default-pose PD as the legs but their absolute
        # angles matter much less to balance, and the elastic band
        # transient sometimes leaves wrists in an odd offset that we don't
        # want to use as a reason to refuse engagement forever.
        pose_err = np.abs(q[:15] - self.cfg.default_q[:15]).max()
        vel_err = np.abs(dq[:15]).max()

        try:
            quat = np.array([
                s.imu_state.quaternion[0],
                s.imu_state.quaternion[1],
                s.imu_state.quaternion[2],
                s.imu_state.quaternion[3],
            ], dtype=np.float64)
            if np.linalg.norm(quat) < 1e-6:
                grav_z = -1.0
            else:
                grav_z = float(quat_rotate_inverse(quat, GRAVITY_W)[2])
        except Exception:  # noqa: BLE001
            grav_z = -1.0

        gates_ok = (
            pose_err <= self.ENGAGE_POSE_TOL
            and vel_err <= self.ENGAGE_VEL_TOL
            and grav_z <= self.ENGAGE_GRAV_Z
        )
        if gates_ok:
            if self._engage_quiet_since is None:
                self._engage_quiet_since = now
            elif now - self._engage_quiet_since >= self.ENGAGE_HOLD_S:
                return True
        else:
            self._engage_quiet_since = None

        # Timeout fallback so we never stall forever in STANDBY. Logged
        # once with the final failure mode so the operator can tune.
        if (
            self._standby_since is not None
            and now - self._standby_since > self.ENGAGE_TIMEOUT_S
        ):
            print(
                f"[combo] STANDBY -> POLICY by timeout ({self.ENGAGE_TIMEOUT_S:.1f}s); "
                f"last gate state: pose_err={pose_err:.3f} (tol "
                f"{self.ENGAGE_POSE_TOL:.3f}), vel_err={vel_err:.3f} "
                f"(tol {self.ENGAGE_VEL_TOL:.3f}), gravity_z={grav_z:.2f} "
                f"(tol {self.ENGAGE_GRAV_Z:.2f})"
            )
            return True
        return False

    def _clamp_arm_to_safe_envelope(self, arm_q: np.ndarray) -> np.ndarray:
        """Clamp a 14-D arm pose to the physical joint limits.

        The previous implementation clamped to `default ± K*action_scale`
        which kept every gesture inside the policy's training
        distribution but also crushed the gesture amplitude (shoulder
        action_scale=0.44, K=2 gave only ±0.88 rad swing). Recognisable
        gestures need more range. The OOD risk that envelope used to
        guard against is now eliminated by `_build_obs` masking the
        arm slice while the override is active, so we only need to
        protect the *physical* joint limits here. ARM_JOINT_LIMITS is
        copied from the MJCF with a small safety margin on each side.
        """
        return np.clip(arm_q, self._arm_lo, self._arm_hi)

    def _rate_limit_arm_step(self, arm_q: np.ndarray) -> np.ndarray:
        """Cap the per-tick arm-joint delta so we never produce a
        joint_vel_rel larger than `ARM_GESTURE_RATE_K_PER_SEC * scale`.

        The cosine ease-in-out blender already keeps motion smooth, but
        if user code shortens a duration (say 0.1s for a 2-scale swing),
        a 50 Hz tick would produce dq ≈ 0.4*scale per tick = 20*scale/sec,
        well outside the policy's training distribution for arm
        joint_vel. This guard pins worst case to ~4*scale/sec."""
        prev = getattr(self, "_last_arm_q_published", None)
        if prev is None:
            return arm_q
        max_step = self.ARM_GESTURE_RATE_K_PER_SEC * self.arm_scale * self.cfg.step_dt
        delta = arm_q - prev
        delta = np.clip(delta, -max_step, max_step)
        return prev + delta

    def _read_current_arm_q(self) -> np.ndarray:
        """Snapshot the live arm joint positions from rt/lowstate. Used
        as the starting point for a gesture blend so engaging the override
        doesn't introduce a position step."""
        s = self.low_state
        if s is None:
            return self.arm_rest.copy()
        return np.fromiter(
            (s.motor_state[ARM_START + i].q for i in range(ARM_DIM)),
            dtype=np.float64, count=ARM_DIM,
        )

    def _advance_arms(self) -> Optional[np.ndarray]:
        """Run one tick of the arm keyframe blender.

        Returns the 14-D arm pose to overlay onto q_target while a
        gesture is active, or None when arms should stay under policy
        control. The override auto-disengages once the last queued
        keyframe completes.
        """
        with self._arm_lock:
            # Need to start a new blend?
            if self.arm_blend_to is None and self.arm_queue:
                dur, pose = self.arm_queue.pop(0)
                self.arm_blend_from = self.arm_q_target.copy()
                self.arm_blend_to = pose.copy()
                self.arm_blend_dur = max(dur, 1e-3)
                self.arm_blend_t = 0.0

            # Advance current blend.
            if self.arm_blend_to is not None:
                self.arm_blend_t += self.cfg.step_dt
                if self.arm_blend_t >= self.arm_blend_dur:
                    self.arm_q_target = self.arm_blend_to.copy()
                    self.arm_blend_from = None
                    self.arm_blend_to = None
                    self.arm_blend_dur = 0.0
                    self.arm_blend_t = 0.0
                    # Last keyframe done and nothing else queued → release
                    # arms back to the policy on the next tick.
                    if not self.arm_queue:
                        self._arm_override_active = False
                else:
                    s = 0.5 - 0.5 * np.cos(
                        np.pi * (self.arm_blend_t / self.arm_blend_dur)
                    )
                    self.arm_q_target = (
                        (1.0 - s) * self.arm_blend_from + s * self.arm_blend_to
                    )

            if not self._arm_override_active:
                return None
            return self.arm_q_target.copy()

    def _build_obs(self) -> np.ndarray:
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
        joint_vel_rel = dq.copy()
        last_action_obs = self.last_raw_action.copy()

        # ---- Mask the arm slice while a gesture override is active.
        # The actual arm position and velocity are wherever the gesture
        # has driven them, which can be far outside the policy's
        # training distribution. Feeding that into the policy used to
        # corrupt its leg outputs even though the leg observations
        # themselves were fine. By zeroing the arm slice we tell the
        # policy "arms are at default and stationary" — the legs then
        # stay in their walking/standing distribution and the policy
        # can ignore the gesture entirely.
        if self._arm_obs_masked:
            joint_pos_rel[ARM_START:ARM_END] = 0.0
            joint_vel_rel[ARM_START:ARM_END] = 0.0
            last_action_obs[ARM_START:ARM_END] = 0.0

        ang_vel = np.array(
            [s.imu_state.gyroscope[0],
             s.imu_state.gyroscope[1],
             s.imu_state.gyroscope[2]],
            dtype=np.float64,
        )
        quat = np.array(
            [s.imu_state.quaternion[0],   # w
             s.imu_state.quaternion[1],   # x
             s.imu_state.quaternion[2],   # y
             s.imu_state.quaternion[3]],  # z
            dtype=np.float64,
        )
        if np.linalg.norm(quat) < 1e-6:
            quat = np.array([1.0, 0.0, 0.0, 0.0])
        projected_gravity = quat_rotate_inverse(quat, GRAVITY_W)

        cmd = self.get_command()
        cmd_norm = float(np.linalg.norm(cmd))
        self.global_phase = (
            self.global_phase + self.cfg.step_dt / self.cfg.gait_period
        ) % 1.0
        if cmd_norm < 0.1:
            gait = np.array([0.0, 0.0])
        else:
            theta = 2.0 * np.pi * self.global_phase
            gait = np.array([np.sin(theta), np.cos(theta)])

        return np.concatenate([
            ang_vel,                  # 3
            projected_gravity,        # 3
            cmd,                      # 3
            gait,                     # 2
            joint_pos_rel,            # 29
            joint_vel_rel,            # 29
            last_action_obs,          # 29
        ])  # -> 98

    def _publish(self, q_des: np.ndarray):
        self.low_cmd.mode_pr = 0
        self.low_cmd.mode_machine = self.mode_machine
        for i in range(G1_NUM_MOTOR):
            m = self.low_cmd.motor_cmd[i]
            m.mode = 1
            m.q = float(q_des[i])
            m.dq = 0.0
            m.tau = 0.0
            m.kp = float(self.cfg.kp[i] * self.kp_scale)
            m.kd = float(self.cfg.kd[i] * self.kp_scale)
        self.low_cmd.crc = self.crc.Crc(self.low_cmd)
        self.cmd_pub.Write(self.low_cmd)


# ---------------------------------------------------------------------------
# Non-blocking single-key reader (Linux/macOS terminals)
# ---------------------------------------------------------------------------
class RawKeyReader:
    def __enter__(self):
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc):
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

    def get(self, timeout: float = 0.1):
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if r else None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def format_help(actions: List[ArmAction]) -> str:
    lines = ["", "==== G1 RL walk + arm gesture combo ===="]
    lines.append("Walking:")
    lines.append("  w / s    forward / backward   (vx +/-0.2 m/s)")
    lines.append("  a / d    strafe left / right  (vy +/-0.1 m/s)")
    lines.append("  q / e    yaw left / right     (wz +/-0.3 rad/s)")
    lines.append("  r        stop walking         (cmd -> 0,0,0)")
    lines.append("  f        full forward         (vx -> vx_max)")
    lines.append("Arm gestures (briefly overlay; arms otherwise policy-controlled):")
    for a in actions:
        lines.append(f"  {a.key}        {a.name}")
    lines.append("  0        release arms (blend to rest, hand back to policy)")
    lines.append("System:")
    lines.append("  space    soft-disable Kp/Kd (robot collapses)")
    lines.append("  ?        print this help")
    lines.append("  x / Ctrl-C  quit (settles softly first)")
    lines.append("=========================================")
    return "\n".join(lines)


def main():
    if len(sys.argv) > 1 and sys.argv[1] not in ("lo", "sim"):
        ChannelFactoryInitialize(0, sys.argv[1])
        print(f"[combo] real-robot mode on {sys.argv[1]} (domain 0).")
        print("[combo] WARNING: keep the e-stop within reach.")
    else:
        ChannelFactoryInitialize(1, "lo")
        print("[combo] simulator mode on lo (domain 1).")

    cfg = DeployCfg(POLICY_YAML)
    print(
        f"[combo] loaded deploy.yaml "
        f"(vx in {cfg.vx_range}, vy in {cfg.vy_range}, wz in {cfg.wz_range}, "
        f"period={cfg.gait_period:.2f}s, step_dt={cfg.step_dt}s)"
    )
    policy = Policy(POLICY_ONNX)
    print(f"[combo] loaded policy: {POLICY_ONNX}")

    ctl = ComboController(cfg, policy)
    actions = build_arm_actions(ctl.arm_rest, ctl.arm_scale)
    actions_by_key = {a.key: a for a in actions}

    ctl.init_dds()
    ctl.start()

    DV_X = 0.2
    DV_Y = 0.1
    DW_Z = 0.3
    print(format_help(actions))

    with RawKeyReader() as kb:
        while True:
            ch = kb.get(0.1)
            if ch is None:
                continue
            if ch == "x" or ch == "\x03":  # x or Ctrl-C
                print("\n[combo] softening and exiting ...")
                break
            if ch == "?":
                print(format_help(actions))
                continue
            if ch == " ":
                print("[combo] soft-disable Kp/Kd")
                ctl.soften(0.0, duration=1.0)
                ctl.set_command(0.0, 0.0, 0.0)
                ctl.release_arms()
                continue

            cmd = ctl.get_command()
            if ch == "w":
                ctl.set_command(cmd[0] + DV_X, cmd[1], cmd[2])
            elif ch == "s":
                ctl.set_command(cmd[0] - DV_X, cmd[1], cmd[2])
            elif ch == "a":
                ctl.set_command(cmd[0], cmd[1] + DV_Y, cmd[2])
            elif ch == "d":
                ctl.set_command(cmd[0], cmd[1] - DV_Y, cmd[2])
            elif ch == "q":
                ctl.set_command(cmd[0], cmd[1], cmd[2] + DW_Z)
            elif ch == "e":
                ctl.set_command(cmd[0], cmd[1], cmd[2] - DW_Z)
            elif ch == "r":
                ctl.set_command(0.0, 0.0, 0.0)
            elif ch == "f":
                ctl.set_command(cfg.vx_range[1], 0.0, 0.0)
            elif ch == "0":
                print("[combo] release arms -> policy default")
                ctl.release_arms()
                continue
            else:
                act = actions_by_key.get(ch)
                if act is None:
                    continue
                print(f"[combo] arm gesture '{ch}' = {act.name}")
                ctl.push_arm_action(act.keyframes)
                continue

            new_cmd = ctl.get_command()
            print(
                f"[combo] cmd = vx={new_cmd[0]:+.2f}  vy={new_cmd[1]:+.2f}  "
                f"wz={new_cmd[2]:+.2f}"
            )

    ctl.stop_and_settle()
    print("[combo] done.")


if __name__ == "__main__":
    main()
