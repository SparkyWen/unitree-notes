"""
G1 RL walk + arm-gesture combo demo for unitree_mujoco.

Single-process controller that runs the trained ONNX velocity policy
(closed-loop balance + walking) AND lets the keyboard trigger upper-body
arm gestures on top, without the rt/lowcmd publisher conflict you'd hit
by running g1_sim_rl_walk.py and g1_sim_keyboard.py at the same time.

Architecture
------------
- 50 Hz RL tick: builds obs from rt/lowstate, runs policy.onnx,
  converts raw_action -> q_target. Obs/action dim auto-detected from ONNX.
- The policy controls all joints by default. Arms are only overridden
  while an arm gesture is actively playing or queued; as soon as the
  last keyframe finishes the arm slice is handed back to the policy.
- Legs (0..arm_start-1) are *always* under the RL policy.
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
  Specifically, `_build_obs` zeroes `joint_pos_rel[13:23]`,
  `joint_vel_rel[13:23]`, and `last_raw_action[13:23]` whenever
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
                5 salute, 6 clap, 7 guard, 8 punch combo, b bow, 0 release
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
# Joint indices (G1 23-DOF, PR mode).
# Policy space: 0..22. SDK slots: joint_ids_map = [0..12, 15..19, 22..26].
# Excluded SDK slots: 13,14 (WaistRoll/Pitch), 20,21 (LeftWristPitch/Yaw),
#                     27,28 (RightWristPitch/Yaw).
# ---------------------------------------------------------------------------
G1_NUM_MOTOR = 23
ARM_START = 13        # joints 13..22 are arms (left 13..17, right 18..22)
ARM_END = 23          # exclusive
ARM_DIM = ARM_END - ARM_START   # 10
G1_SDK_MOTOR_TOTAL = 29  # G1 always exposes 29 SDK slots


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
    LeftShoulderPitch  = 13
    LeftShoulderRoll   = 14
    LeftShoulderYaw    = 15
    LeftElbow          = 16
    LeftWristRoll      = 17
    RightShoulderPitch = 18
    RightShoulderRoll  = 19
    RightShoulderYaw   = 20
    RightElbow         = 21
    RightWristRoll     = 22


def _slot(j: int) -> int:
    """Convert a policy-space joint index (J.*) to an arm-local index."""
    return j - ARM_START


# Resolve the policy artifact directory relative to *this script*, not to
# $HOME, so the demo works regardless of where the unitree-notes repo is
# cloned. The script lives at <repo_root>/g1_sim_demo/g1_sim_rl_combo.py,
# so the repo root is its parent's parent.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_DIR = Path(__file__).resolve().parent

# Both the ONNX and the deploy config live in g1_sim_demo/policy/ so this
# file is portable when copied to any repo (e.g. cs47-command-center).
POLICY_ONNX = _SCRIPT_DIR / "policy" / "policy.onnx"
POLICY_YAML = _SCRIPT_DIR / "policy" / "params" / "deploy.yaml"

# ---------------------------------------------------------------------------
# Gesture library (gestures_23dof.npz, built from build_arm_actions at 50 Hz).
# obs: gesture_onehot [N_g] + arm_qpos_ref_horizon [k * ARM_DIM].
# ---------------------------------------------------------------------------
_GESTURE_FILE = _SCRIPT_DIR / "policy" / "gestures_23dof.npz"
_GESTURE_FPS = 50.0       # Hz at which the library was sampled
_GESTURE_K   = 5          # look-ahead horizon in obs
# gesture key → library index (must match names order in gestures_23dof.npz)
_KEY_TO_GESTURE_IDX: dict = {
    "1": 0,  # wave_right
    "2": 1,  # wave_left
    "3": 2,  # hands_up
    "4": 3,  # t_pose
    # keys 5-8 intentionally absent: gestures_23dof.npz was baked from the
    # old (wrong) pose functions, so the library trajectories are incorrect.
    # Falling through to the keyframe else-branch picks up the fixed poses.
    "hug": 8,  # for keyframe_extras / SkillServer
}


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

        # joint_ids_map[i] = SDK motor slot that carries policy joint i.
        self.joint_ids_map: List[int] = list(cfg["joint_ids_map"])
        self.num_motors: int = len(self.joint_ids_map)
        # SDK slots not in joint_ids_map; zeroed in _publish for safety.
        self.excluded_sdk_slots: frozenset = (
            frozenset(range(G1_SDK_MOTOR_TOTAL)) - frozenset(self.joint_ids_map)
        )

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
            if arr.shape != (self.num_motors,):
                raise ValueError(
                    f"deploy.yaml '{name}' has shape {arr.shape}, "
                    f"expected ({self.num_motors},)"
                )


# ---------------------------------------------------------------------------
# ONNX policy wrapper
# ---------------------------------------------------------------------------
class Policy:
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
        self.obs_dim: int = ins[0].shape[-1]
        self.act_dim: int = outs[0].shape[-1]
        if self.act_dim != G1_NUM_MOTOR:
            raise RuntimeError(
                f"policy outputs {self.act_dim} actions; expected {G1_NUM_MOTOR} (G1_NUM_MOTOR)."
            )

    def __call__(self, obs: np.ndarray) -> np.ndarray:
        x = obs.astype(np.float32, copy=False).reshape(1, self.obs_dim)
        y = self.session.run([self.out_name], {self.in_name: x})[0]
        return y.reshape(self.act_dim)


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
# Each gesture is encoded as a 10-D *absolute* target for the arm slice
# (joints 13..22). Targets only set the joints the gesture actually moves;
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
#   shoulder_roll   + = arm out (left side; − on right side = arm out)
#   elbow           + = elbow bent
# ---------------------------------------------------------------------------
def _abs_pose_from(arm_rest: np.ndarray, **overrides: float) -> np.ndarray:
    """Start from the policy's arm_rest and override the named joints.

    `overrides` keys must be attribute names on `J` (e.g. RightShoulderPitch).
    Returns a fresh arm_dim-D pose; arm_rest is not mutated.
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
    """Right hand to forehead — military salute.

    Upper arm elevated and to the right (pitch=-0.8, roll=-1.0), similar
    to wave_right but more elevated.  At yaw=0 the elbow's natural bend
    plane (set by the MJCF shoulder chain) swings the forearm upward and
    inward toward the head at this arm elevation — no axial yaw needed.
    Elbow=1.55 rad gives enough bend to bring the hand to the forehead.
    """
    return _abs_pose_from(
        arm_rest,
        RightShoulderPitch=-0.8,
        RightShoulderRoll=-1.0,
        RightElbow=1.55,
    )


def clap_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Both hands meeting at chest/face height — real clap geometry.

    Both arms come forward (pitch=-0.8) and cross INWARD (roll=-0.5 left,
    +0.5 right).  At yaw=0 the natural elbow bend swings the forearms
    upward and inward so the hands meet in front of the face — no axial
    yaw needed.
    """
    return _abs_pose_from(
        arm_rest,
        LeftShoulderPitch=-0.8,
        LeftShoulderRoll=-0.5,
        LeftElbow=1.4,
        RightShoulderPitch=-0.8,
        RightShoulderRoll=0.5,
        RightElbow=1.4,
    )


def guard_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Boxer guard: two vertical forearms ( I I ) in front of the face.

    pitch=-1.2 tilts the upper arm forward-and-upward (mostly forward,
    slightly down from horizontal).  At that elevation the MJCF shoulder
    chain's natural elbow bend plane (yaw=0) already swings the forearm
    mostly UPWARD (+Z ≈ 0.93) with only a slight forward lean — producing
    the 'I I' shape without any axial yaw twist.  roll=±0.4 spaces the
    arms slightly wider than the body so both forearms are visible
    side-by-side from the front.
    """
    return _abs_pose_from(
        arm_rest,
        LeftShoulderPitch=-1.2,
        LeftShoulderRoll=0.4,
        LeftElbow=1.5,
        RightShoulderPitch=-1.2,
        RightShoulderRoll=-0.4,
        RightElbow=1.5,
    )


def punch_right_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Right arm extended forward (jab), left arm stays in guard."""
    p = guard_pose(arm_rest)
    p[_slot(J.RightShoulderPitch)] = -1.2
    p[_slot(J.RightShoulderRoll)]  = -0.1
    p[_slot(J.RightElbow)]         =  0.1
    return p


def punch_left_pose(arm_rest: np.ndarray) -> np.ndarray:
    p = guard_pose(arm_rest)
    p[_slot(J.LeftShoulderPitch)] = -1.2
    p[_slot(J.LeftShoulderRoll)]  =  0.1
    p[_slot(J.LeftElbow)]         =  0.1
    return p


def bow_pose(arm_rest: np.ndarray) -> np.ndarray:
    """Namaste / prayer-hands bow substitute for 23-DOF.

    23-DOF has no WaistPitch, so the torso cannot lean forward — a
    physically correct forward bow is impossible.  The closest recognisable
    gesture is bringing both hands together at chest height (合掌 / namaste),
    which reads universally as a respectful bow.

    Both arms come forward (-0.7 pitch) and strongly INWARD (roll -0.4 left,
    +0.4 right) with elbows bent (1.3), so the hands meet at roughly
    chest/sternum height in front of the body.
    """
    return _abs_pose_from(
        arm_rest,
        LeftShoulderPitch=-0.7,
        LeftShoulderRoll=-0.4,
        LeftElbow=1.3,
        RightShoulderPitch=-0.7,
        RightShoulderRoll=0.4,
        RightElbow=1.3,
    )


# ---------------------------------------------------------------------------
# Action = ordered list of (duration_seconds, arm_pose_10d) keyframes.
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

    Each pose is an *absolute* 10-D arm target (see the gesture pose
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
    bw      = bow_pose(arm_rest)

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
        ArmAction("b", "bow (namaste — no waist pitch on 23DOF)",
                  [(1.8, bw), hold(bw, 1.0),
                   (1.8, arm_rest)]),
    ]


# ---------------------------------------------------------------------------
# Combo controller: RL legs + waist, keyboard arms.
# ---------------------------------------------------------------------------
class ComboController:
    LOWSTATE_TIMEOUT = 0.2     # seconds; if no lowstate, hold default pose

    # Per-arm-joint physical limits (rad), sourced from MJCF with ~5% margin.
    # Indices 0..9 correspond to policy joints ARM_START..ARM_END-1 (arm-local).
    # 23-DOF has no WaistRoll/Pitch or WristPitch/Yaw.
    ARM_JOINT_LIMITS: Tuple[Tuple[float, float], ...] = (
        (-3.05, 2.65),   # 13 LeftShoulderPitch  (SDK 15)
        (-1.55, 2.20),   # 14 LeftShoulderRoll   (SDK 16)
        (-2.55, 2.55),   # 15 LeftShoulderYaw    (SDK 17)
        (-1.00, 2.05),   # 16 LeftElbow          (SDK 18)
        (-1.95, 1.95),   # 17 LeftWristRoll      (SDK 19)
        (-3.05, 2.65),   # 18 RightShoulderPitch (SDK 22)
        (-2.20, 1.55),   # 19 RightShoulderRoll  (SDK 23)
        (-2.55, 2.55),   # 20 RightShoulderYaw   (SDK 24)
        (-1.00, 2.05),   # 21 RightElbow         (SDK 25)
        (-1.95, 1.95),   # 22 RightWristRoll     (SDK 26)
    )

    # `ARM_GESTURE_K` previously gated the *gesture amplitude* itself (clamp
    # commanded arm pose to default ± K*action_scale). That envelope is too
    # tight to express recognisable gestures (shoulder action_scale=0.44,
    # so K=2 caps the shoulder at ±0.88 rad — not enough for a real T-pose
    # or hands-up). Now gestures are clamped only to the *physical* joint
    # range (ARM_JOINT_LIMITS); the OOD risk this used to guard against is
    # eliminated by masking the arm slice of the policy's observation
    # while a gesture is active via the gesture_onehot / arm_qpos_ref_horizon obs.
    #
    # ARM_GESTURE_K is still used for one thing: clipping the value we
    # write into `last_raw_action[13:23]` so the next obs's last_action
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

    # ---- Per-arm Kp/Kd boost while a gesture is active ---------------------
    # deploy.yaml's arm Kp (14.3 shoulder/elbow, 16.8 wrist_pitch/yaw) is
    # tuned for the policy's training distribution where arms only deviate
    # by ~action_scale (~0.44 rad) from default. The policy uses small
    # incremental commands and the actuator's own low-pass mostly hides any
    # residual tracking lag.
    #
    # Static gesture targets are far larger (hands_up shoulder_pitch sweeps
    # 1.95 rad from default; T-pose shoulder_roll ±1.32 rad). At Kp=14.3 the
    # gravity load on a horizontal arm (≈3.7 N·m) produces a steady-state
    # deflection of 3.7/14.3 ≈ 0.26 rad — the gesture visibly under-shoots
    # ("没有执行到相应的位置"). With ζ ≈ Kd/(2√(Kp·I)) ≈ 0.38 the response
    # is also underdamped, so the arm oscillates while it tries to track a
    # moving cosine target ("造成大量的摇晃").
    #
    # The sibling `g1_sim_keyboard.py` (open-loop static-pose demo the user
    # remembers as "the gestures looked right") uses Kp=40 / Kd=1 on every
    # arm joint. Boosting deploy.yaml's arm Kp/Kd by ARM_GESTURE_KP_SCALE
    # while a gesture is active matches that proven gain (14.3 × 2.8 ≈ 40)
    # without affecting the legs or waist, which still need the policy's
    # training-time gains to behave in distribution. Scaling Kd by the same
    # factor *increases* the damping ratio (ζ scales as √k), giving an
    # over-damped tracking response — better suppresses the oscillation
    # than just raising stiffness.
    ARM_GESTURE_KP_SCALE = 2.8
    # Per-second slew on `_arm_kp_boost` toward its target value (1.0 when
    # idle, ARM_GESTURE_KP_SCALE during a gesture). 4.0/s = ~0.45 s ramp
    # from 1.0 to 2.8 — fast enough to be useful by the time the cosine
    # blend reaches peak amplitude (~1 s into a typical gesture), slow
    # enough that the Kp jump on gesture-press doesn't snap the arm.
    ARM_KP_RAMP_PER_SEC = 4.0

    # ---- Per-leg/waist Kp/Kd boost during stand-still / safe-hold ---------
    # deploy.yaml's leg/waist gains (hip pitch=40.2, ankle=28.5, waist=28.5)
    # are tuned for the policy's training distribution: the policy makes
    # small ±action_scale corrections every 20 ms and the resulting torques
    # average out to keep the body upright over a gait cycle. They are NOT
    # tuned for static balance — a body suspended at default_q with these
    # gains has only ~0.3 rad of stiffness margin against gravity moments
    # at the ankles, so once the elastic band releases (operator presses
    # `9` in the simulator viewer) any small disturbance accumulates into a
    # slow forward/backward drift that the watchdog eventually catches at
    # gz>-0.85. Symptom from 2026-05-06: stable for ~7 s after band release,
    # then gz drifts -0.95 → -0.79 → trip → fall.
    #
    # The sibling `g1_sim_keyboard.py` open-loop demo is documented as
    # holding default_q stably without the band; it uses noticeably stiffer
    # gains on the same actuators (hip pitch=60, hip yaw=60, knee=100,
    # ankle=40, waist yaw=60, waist roll/pitch=40). Boosting deploy.yaml's
    # leg/waist Kp/Kd by STAND_KP_BOOST_TARGET while the controller is
    # publishing default_q (stand-still bypass or watchdog safe-hold)
    # closes the gap toward those proven values without affecting the
    # policy's training distribution: the moment a walk command lands the
    # boost slews back to 1.0 over ~0.1 s, well before the warm-up window
    # ends. Scaling Kp and Kd together preserves the damping ratio (ζ
    # scales as √k), so the joints become stiffer without becoming
    # noticeably under- or over-damped.
    #
    # 1.4× picks deploy.yaml's hip pitch (40.2 → 56.3, near kb-demo's 60)
    # and ankle (28.5 → 39.9, near kb-demo's 40) up to the proven values.
    # Hip roll (99.1 → 138.7) and knee (99.1 → 138.7) end up stiffer than
    # kb-demo's 60/100, but those joints carry the heaviest mass and the
    # extra stiffness only helps static hold. Walking transitions back to
    # 1.0× before the policy starts producing torques, so the policy
    # never sees these boosted gains.
    STAND_KP_BOOST_TARGET = 1.4
    # Per-second slew on `_leg_kp_boost`. 4.0/s = ~0.1 s ramp from 1.0 to
    # 1.4 (and back). Matches `ARM_KP_RAMP_PER_SEC`. Fast enough that the
    # robot starts feeling the stiffer gains within a few control ticks of
    # entering stand-still; slow enough that the transition out (walk
    # command landing) doesn't snap leg torques as the policy spins up.
    STAND_KP_RAMP_PER_SEC = 4.0

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
        #   POLICY: policy controls all joints. The first POLICY_WARMUP_S
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
        # Snapshot of the last arm slice we actually wrote to lowcmd;
        # used by _rate_limit_arm_step. Seeded lazily in _tick.
        self._last_arm_q_published: Optional[np.ndarray] = None
        self._arm_lo = np.array([lo for lo, _ in self.ARM_JOINT_LIMITS], dtype=np.float64)
        self._arm_hi = np.array([hi for _, hi in self.ARM_JOINT_LIMITS], dtype=np.float64)

        # Gesture library (gestures_23dof.npz) for the arm-disturbance policy.
        # Library gestures (keys 1-8, hug) bypass the keyframe blend and use
        # pre-sampled 50Hz trajectories directly — matching training exactly.
        if _GESTURE_FILE.exists():
            _gdata = np.load(str(_GESTURE_FILE))
            self._gest_qpos: np.ndarray = _gdata["arm_qpos"].astype(np.float64)  # (N_g, T_max, arm_dim)
            self._gest_len: np.ndarray  = _gdata["lengths"]                       # (N_g,) int
            self._n_gestures: int       = int(self._gest_qpos.shape[0])           # 9
        else:
            self._gest_qpos  = np.zeros((0, 1, ARM_DIM), dtype=np.float64)
            self._gest_len   = np.zeros(0, dtype=np.int32)
            self._n_gestures = 0
        self._gest_id: int     = -1    # -1 = no library gesture; 0..N_g-1 = active
        self._gest_frame: float = 0.0  # current frame index (advances 1/tick @ 50Hz)

        # Soft Kp scale.
        self.kp_scale = 1.0
        self._soften_target = 1.0
        self._soften_step = 0.0
        self._soften_steps_left = 0

        # Per-arm Kp/Kd boost while an arm gesture override is active. Idle
        # value 1.0 (= deploy.yaml's training Kp). Slewed in `_tick` toward
        # ARM_GESTURE_KP_SCALE while `_arm_override_active`, back to 1.0
        # when the gesture queue drains. Applied only to arm indices in
        # `_publish` so leg/waist gains stay at the policy's training value.
        self._arm_kp_boost = 1.0

        # Per-leg/waist Kp/Kd boost while the controller is publishing
        # default_q for static balance (stand-still bypass or safe-hold).
        # Idle 1.0 (deploy.yaml's policy-training gains); slewed in `_tick`
        # toward STAND_KP_BOOST_TARGET while either the stand-still bypass
        # or the watchdog safe-hold is active, back to 1.0 the moment the
        # policy is driving (walk/turn). Applied only to indices 0..12 in
        # `_publish` so the policy still sees its training-time arm gains.
        self._leg_kp_boost = 1.0

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

    def start_library_gesture(self, gesture_id: int) -> None:
        """Start a library gesture (keys 1-8, hug). Arms are driven directly from
        the pre-sampled 50Hz trajectory in gestures_23dof.npz so the policy
        receives the same arm_qpos_ref_horizon obs it saw during training.

        gesture_id: index into the gesture library (see _KEY_TO_GESTURE_IDX).
        Falls back to a no-op if the library wasn't loaded or id is out of range.
        """
        if gesture_id < 0 or gesture_id >= self._n_gestures:
            return
        with self._arm_lock:
            # Clear any in-flight keyframe queue and set library mode.
            self.arm_queue.clear()
            self.arm_blend_from = None
            self.arm_blend_to = None
            self._gest_id = gesture_id
            self._gest_frame = 0.0
            self._arm_override_active = True

    def release_arms(self):
        """Stop any in-flight gesture and blend arms back to rest over 1.5s.
        No-op if arms are already policy-controlled."""
        with self._arm_lock:
            has_library = self._gest_id >= 0
            has_keyframe = self._arm_override_active or bool(self.arm_queue)
            if not has_library and not has_keyframe:
                return
            # Stop library playback.
            self._gest_id = -1
            self._gest_frame = 0.0
            # Start a keyframe ramp from wherever arms are now → arm_rest.
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
            [self.low_state.motor_state[self.cfg.joint_ids_map[i]].q
             for i in range(G1_NUM_MOTOR)],
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
        # Arm-only Kp boost is at 1.0 (no gesture in flight) on every start.
        self._arm_kp_boost = 1.0
        # Leg/waist Kp boost is at 1.0 on start; _tick ramps it up while we
        # are publishing default_q (stand-still bypass / safe-hold).
        self._leg_kp_boost = 1.0

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

        # Arm-only Kp boost slew: ramp toward ARM_GESTURE_KP_SCALE while a
        # gesture is queued / playing, back toward 1.0 when arms are
        # policy-controlled. Cosine ease-in/out is overkill here — a
        # constant-rate slew matches the instantaneous decision boundary
        # (override on/off is binary) and is bounded by ARM_KP_RAMP_PER_SEC.
        boost_target = (
            self.ARM_GESTURE_KP_SCALE if self._arm_override_active else 1.0
        )
        boost_step = self.ARM_KP_RAMP_PER_SEC * self.cfg.step_dt
        if self._arm_kp_boost < boost_target:
            self._arm_kp_boost = min(boost_target, self._arm_kp_boost + boost_step)
        elif self._arm_kp_boost > boost_target:
            self._arm_kp_boost = max(boost_target, self._arm_kp_boost - boost_step)

        # Leg/waist Kp boost slew. With the stand-still bypass removed (the
        # policy is what holds the robot up at cmd=0, not a default_q PD),
        # the boost only matters during BOOT — where the controller is
        # blending measured pose to default_q with a low Kp floor. Slewing
        # the boost toward STAND_KP_BOOST_TARGET while the policy is *not*
        # yet active gives the boot ramp a crisper hold, and back to 1.0
        # the moment the policy takes over so the policy sees its
        # training-time gains.
        leg_target = (
            self.STAND_KP_BOOST_TARGET
            if (not self._boot_done or not self.policy_active)
            else 1.0
        )
        leg_step = self.STAND_KP_RAMP_PER_SEC * self.cfg.step_dt
        if self._leg_kp_boost < leg_target:
            self._leg_kp_boost = min(leg_target, self._leg_kp_boost + leg_step)
        elif self._leg_kp_boost > leg_target:
            self._leg_kp_boost = max(leg_target, self._leg_kp_boost - leg_step)

        # Watchdog: if simulator stops sending state, hold default pose.
        if time.monotonic() - self.last_state_time > self.LOWSTATE_TIMEOUT:
            self._publish(self.cfg.default_q)
            return

        # ---- Safe-hold (set by WatchdogManager on EMERGENCY_STOP).
        # 2026-05-06 fix: Previously this branch published default_q at
        # full Kp on the assumption that "default pose + PD" is a passively
        # stable static stance. Headless MuJoCo verification (see
        # docs/stand_balance_root_cause.md) proved this assumption WRONG:
        # default_q + PD at any Kp scale (deploy.yaml × 1.0/1.4/2.0/3.0
        # and even kb-demo's stiffer 60/100/40 set) collapses the robot to
        # the ground in ~1.5 s, while the trained policy at cmd=(0,0,0)
        # keeps gz=-1.000 indefinitely (verified to 60 s).
        #
        # Hence safe-hold no longer changes the publish path — it stays a
        # bookkeeping flag (and the SafetySupervisor still rejects new
        # walk commands while the FSM is in EMERGENCY_STOP). The policy
        # keeps running, which is what gives the watchdog auto-recovery
        # any chance of bringing the robot back upright.

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

        # ---- STANDBY -> POLICY engagement.
        # 2026-05-06 fix: Previously this phase held default_q at full Kp
        # while waiting for engagement gates (gz<-0.95, pose_err<0.08,
        # vel_err<0.30, held 1.5 s). Headless verification proved that
        # publishing default_q on the ground collapses the robot in ~1.5 s
        # regardless of Kp — the gates therefore never pass on a grounded
        # robot, and the 30 s timeout fallback engaged the policy only
        # AFTER the robot was already lying flat. Meanwhile the policy
        # itself, when actually run, keeps cmd=0 stand stable indefinitely.
        # So we engage the policy as soon as BOOT finishes; the policy's
        # POLICY_WARMUP_S cosine ease-in + clip already protects against
        # a bad first inference. The elastic band (if still active) keeps
        # the body upright while the policy spins up — and once the user
        # disables it, the policy maintains balance on its own.
        if not self.policy_active:
            self.policy_active = True
            self._engage_at = time.monotonic()
            self.kp_scale = 1.0
            self.last_raw_action[:] = 0.0
            self.global_phase = 0.0
            self._stand_active = False
            self._stand_below_thresh_since = None
            print(
                "[combo] policy engaged. wsadqe to walk; "
                "1-8 arm gestures; 0 release."
            )

        # ---- POLICY phase ----
        # 2026-05-06 fix: the stand-still bypass that used to live here
        # (publish default_q when ||cmd||<STAND_CMD_THRESH) was the proximate
        # cause of "robot can't stand still / falls a few seconds after a
        # walk". Headless MuJoCo verification proved the policy at cmd=0
        # is rock-solid (gz=-1.000 for 60+ s) while default_q + PD collapses
        # the robot in ~1.5 s at any Kp. So we always run the policy here.
        # `_stand_active` is still tracked (for telemetry / future use) but
        # no longer redirects the publish path.
        cmd = self.get_command()
        cmd_norm = float(np.linalg.norm(cmd))
        now = time.monotonic()
        if cmd_norm < self.STAND_CMD_THRESH:
            self._stand_active = True
            if self._stand_below_thresh_since is None:
                self._stand_below_thresh_since = now
        else:
            self._stand_active = False
            self._stand_below_thresh_since = None
        # Wind-down state is unused after the bypass removal; clear it so
        # nothing else in the controller acts on stale snapshots.
        self._wind_down_from = None
        self._wind_down_at = None

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
        self.last_raw_action[:] = raw_action
        self._last_policy_q_target = q_target.copy()

        # ---- Arm override: library gesture (trained matching) or keyframe fallback.
        if self._gest_id >= 0:
            # Library gesture: drive arms from pre-sampled trajectory.
            # The arm-disturbance policy was trained with this exact arm reference,
            # so no obs masking is needed — the policy sees real arm positions +
            # gesture_onehot + arm_qpos_ref_horizon and compensates on the legs.
            arm_q = self._advance_library_gesture()
            if arm_q is not None:
                q_target[ARM_START:ARM_END] = self._clamp_arm_to_safe_envelope(arm_q)
        else:
            # Keyframe-based arm overlay (non-library gestures like bow).
            arm_q = self._advance_arms()
            if arm_q is not None:
                arm_q = self._clamp_arm_to_safe_envelope(arm_q)
                arm_q = self._rate_limit_arm_step(arm_q)
                q_target[ARM_START:ARM_END] = arm_q

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
                (s.motor_state[self.cfg.joint_ids_map[i]].q
                 for i in range(G1_NUM_MOTOR)),
                dtype=np.float64, count=G1_NUM_MOTOR,
            )
            dq = np.fromiter(
                (s.motor_state[self.cfg.joint_ids_map[i]].dq
                 for i in range(G1_NUM_MOTOR)),
                dtype=np.float64, count=G1_NUM_MOTOR,
            )
        except Exception:  # noqa: BLE001
            return False
        # Pose / vel: only judge legs and waist (policy joints 0..ARM_START-1).
        # Arms matter much less to balance, and wrist transients shouldn't
        # block engagement forever.
        pose_err = np.abs(q[:ARM_START] - self.cfg.default_q[:ARM_START]).max()
        vel_err = np.abs(dq[:ARM_START]).max()

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
        """Clamp a 10-D arm pose to the physical joint limits.

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
            (s.motor_state[self.cfg.joint_ids_map[ARM_START + i]].q
             for i in range(ARM_DIM)),
            dtype=np.float64, count=ARM_DIM,
        )

    def _advance_arms(self) -> Optional[np.ndarray]:
        """Run one tick of the arm keyframe blender.

        Returns the 10-D arm pose to overlay onto q_target while a
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

    def _advance_library_gesture(self) -> Optional[np.ndarray]:
        """Advance one control tick of a library gesture playback.

        Returns the arm_dim-D absolute arm pose for this tick, or None when
        the gesture finishes (which also clears _gest_id and _arm_override_active).
        Each tick advances by exactly 1 frame (step_dt=0.02s × fps=50Hz).
        """
        if self._gest_id < 0:
            return None
        fi = int(self._gest_frame)
        g_len = int(self._gest_len[self._gest_id])
        if fi >= g_len:
            self._gest_id = -1
            self._gest_frame = 0.0
            self._arm_override_active = False
            return None
        arm_pose = self._gest_qpos[self._gest_id, fi].copy()
        self._gest_frame += self.cfg.step_dt * _GESTURE_FPS  # = 1.0 at 50Hz
        return arm_pose

    def _build_obs(self) -> np.ndarray:
        s = self.low_state
        q = np.fromiter(
            (s.motor_state[self.cfg.joint_ids_map[i]].q
             for i in range(G1_NUM_MOTOR)),
            dtype=np.float64, count=G1_NUM_MOTOR,
        )
        dq = np.fromiter(
            (s.motor_state[self.cfg.joint_ids_map[i]].dq
             for i in range(G1_NUM_MOTOR)),
            dtype=np.float64, count=G1_NUM_MOTOR,
        )
        joint_pos_rel = q - self.cfg.default_q
        joint_vel_rel = dq.copy()
        last_action_obs = self.last_raw_action.copy()

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

        base_obs = np.concatenate([
            ang_vel,                  # 3
            projected_gravity,        # 3
            cmd,                      # 3
            gait,                     # 2
            joint_pos_rel,            # num_motors
            joint_vel_rel,            # num_motors
            last_action_obs,          # num_motors
        ])  # -> 11 + 3*num_motors = 80

        # Arm-disturbance policy (obs_dim > 80): append gesture obs.
        if self.policy.obs_dim > len(base_obs):
            # gesture_onehot [N_g]: one-hot for active library gesture, else zeros.
            if self._gest_id >= 0 and self._n_gestures > 0:
                onehot = np.zeros(self._n_gestures, dtype=np.float64)
                onehot[self._gest_id] = 1.0
            else:
                onehot = np.zeros(self._n_gestures, dtype=np.float64)
            # arm_qpos_ref_horizon [k * arm_dim]: next k library frames, else zeros.
            horizon = np.zeros(_GESTURE_K * ARM_DIM, dtype=np.float64)
            if self._gest_id >= 0:
                g_len = int(self._gest_len[self._gest_id])
                for i in range(_GESTURE_K):
                    fi = min(int(self._gest_frame) + i, g_len - 1)
                    horizon[i * ARM_DIM : (i + 1) * ARM_DIM] = (
                        self._gest_qpos[self._gest_id, fi]
                    )
            return np.concatenate([base_obs, onehot, horizon])

        return base_obs

    def _publish(self, q_des: np.ndarray):
        self.low_cmd.mode_pr = 0
        self.low_cmd.mode_machine = self.mode_machine
        # Per-joint Kp/Kd factor:
        #   - arms (13..22) get an extra `_arm_kp_boost` multiplier so a
        #     gesture can drive them to the commanded pose without raising
        #     the gain on balance-critical joints.
        #   - legs / waist (0..12) get `_leg_kp_boost` which slews up while
        #     the controller is publishing default_q for static balance and
        #     back to 1.0 while the policy is driving torques (walk/turn).
        # Both boosts default to 1.0, so the policy still sees its
        # training-time deploy.yaml gains during an active walk command.
        # Zero SDK slots not in joint_ids_map (unused joints for this DOF config).
        for sdk_slot in self.cfg.excluded_sdk_slots:
            m = self.low_cmd.motor_cmd[sdk_slot]
            m.mode = 0
            m.q = 0.0
            m.dq = 0.0
            m.tau = 0.0
            m.kp = 0.0
            m.kd = 0.0

        for i in range(G1_NUM_MOTOR):
            m = self.low_cmd.motor_cmd[self.cfg.joint_ids_map[i]]
            m.mode = 1
            m.q = float(q_des[i])
            m.dq = 0.0
            m.tau = 0.0
            scale = self.kp_scale
            if ARM_START <= i < ARM_END:
                scale *= self._arm_kp_boost
            else:
                scale *= self._leg_kp_boost
            m.kp = float(self.cfg.kp[i] * scale)
            m.kd = float(self.cfg.kd[i] * scale)
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
        f"period={cfg.gait_period:.2f}s, step_dt={cfg.step_dt}s, "
        f"num_motors={G1_NUM_MOTOR}, arm_start={ARM_START})"
    )
    policy = Policy(POLICY_ONNX)
    print(
        f"[combo] loaded policy: {POLICY_ONNX} "
        f"(obs_dim={policy.obs_dim}, act_dim={policy.act_dim})"
    )

    ctl = ComboController(cfg, policy)
    if ctl._n_gestures > 0:
        print(f"[combo] gesture library: {ctl._n_gestures} gestures loaded from {_GESTURE_FILE.name}")
    else:
        print(f"[combo] WARN: gesture library not found at {_GESTURE_FILE}; gesture obs will be zeros")
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
            elif ch in _KEY_TO_GESTURE_IDX and ctl._n_gestures > 0:
                # Library gesture: arm targets come from gestures_23dof.npz;
                # the policy receives matching gesture_onehot + arm_qpos_ref_horizon.
                # Fall back to keyframes if the library was built with fewer
                # gestures than needed (e.g. only 4 of the 9) — without this
                # check, start_library_gesture silently no-ops and nothing happens.
                gid = _KEY_TO_GESTURE_IDX[ch]
                act = actions_by_key.get(ch)
                name = act.name if act else f"gesture {gid}"
                if gid < ctl._n_gestures:
                    print(f"[combo] library gesture '{ch}' = {name} (id={gid})")
                    ctl.start_library_gesture(gid)
                elif act is not None:
                    print(f"[combo] arm gesture '{ch}' = {name} "
                          f"(keyframe fallback; library has {ctl._n_gestures} gestures)")
                    ctl.push_arm_action(act.keyframes)
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
