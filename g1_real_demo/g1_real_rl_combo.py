"""
G1 RL walk + arm-gesture combo demo — REAL ROBOT variant.

This is the real-hardware counterpart of `../g1_sim_demo/g1_sim_rl_combo.py`.
Use this file when driving a physical Unitree G1 over Ethernet; use the
mujoco one when running against `unitree_mujoco`'s python simulator. The
two files share the same RL/gesture core but the real-robot variant adds:
  - `MotionSwitcher` release on startup (the onboard "ai/normal/advanced"
    high-level controller owns rt/lowcmd by default and would overwrite
    our commands — see issue/realmachine.md for the diagnosis),
  - bounded `lowstate` wait with an actionable error checklist instead of
    an unbounded busy-wait,
  - `lying` CLI mode for wiring/DDS checks when the robot can't stand
    (see docs/demo-QA7.md),
  - a CycloneDDS tracing-off override.

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

Why arm gestures must stay inside the policy-tolerant envelope
  See docs/demo-QA5.md for the long version. Short version:
  the policy was trained with `actuator_names=(".*",)` and per-joint
  action_scale (shoulder=0.44, elbow=0.44, wrist_pitch/yaw=0.07). With
  scale=0.44 and a weak default-pose deviation reward, during training
  the arms typically stay within ~±0.44 rad of default — i.e. the
  observed `joint_pos_rel[15:29]` distribution is concentrated around 0
  with magnitude on the order of `action_scale`. If we forcibly drive
  an arm joint to `default ± 1.6 rad` (e.g. hands_up shoulder_pitch =
  -1.6 vs default 0.35) the policy sees `joint_pos_rel ≈ -1.95`,
  ~4.4× the training scale. That input is OOD; an MLP on OOD inputs
  produces garbage on every output dim — including legs. Robot
  collapses. Wrist_pitch/yaw are even tighter (action_scale=0.07): a
  -0.3 rad salute wrist tilt is already ~4× scale.

  Two safety nets are applied to every gesture frame:
  1. `clamp_arm_to_safe`  -- bounds each arm joint to
                             default_q[i] ± ARM_GESTURE_K * action_scale[i]
                             (default K=2.0). Visually-recognizable
                             gestures still come through; OOD spikes
                             are clipped at the source.
  2. `_synthesize_last_action_for_arms` -- when we override arm
                             q_target, we also rewrite the arm slice of
                             `last_raw_action` to `(arm_q - offset)/scale`
                             so the next obs has a self-consistent
                             (joint_pos_rel, last_action) pair. Without
                             this, even a small clipped override would
                             leave the action and the achieved pose
                             pointing in different directions, which is
                             still OOD for the policy.

Why only arms can be temporarily overridden:
  Legs are responsible for balance; waist orientation feeds directly
  into the projected_gravity observation, so a commanded waist tilt
  would make the policy think "I'm falling" and drive the wrong
  recovery torques. Arms are mass-light and the policy is robust to
  short, slow arm overrides (within the envelope above), so brief
  gesture overlays are safe.

Run order
---------
  Real robot (preferred for this file):
      conda activate unitree
      cd ~/unitree/unitree-notes/g1_real_demo
      # find the interface that's on the robot's 192.168.123.0/24 subnet:
      ip -br addr | grep 192.168.123
      python g1_real_rl_combo.py <iface>          # e.g. eno3
      # the script will release any active high-level mode (ai/normal/
      # advanced) before publishing on rt/lowcmd. Keep the e-stop in hand.

  Simulator (also works — same DDS surface):
      Terminal 1:
          conda activate unitree
          cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
          python unitree_mujoco.py
          # press 8 a few times to lower elastic band; optionally 9 to disable
      Terminal 2:
          conda activate unitree
          cd ~/unitree/unitree-notes/g1_real_demo
          python g1_real_rl_combo.py             # no <iface> -> sim mode

Walking keys:   w/s, a/d, q/e, r (stop), f (full forward)
Arm gestures:   1 wave R, 2 wave L, 3 hands up, 4 T-pose,
                5 salute, 6 clap, 7 guard, 8 punch combo, 0 release
System:         space (soften), ? (help), x (quit)

Lying-down test mode (real-robot wiring/comm check)
---------------------------------------------------
    python g1_real_rl_combo.py <iface> lying     # e.g. eno3 lying

Use this when the robot is lying flat and you only want to verify the
DDS round-trip (lowstate <-> lowcmd) and that motor commands reach the
joints. In lying mode the script:
  - skips the boot ramp toward default_q (does NOT try to stand the
    robot up),
  - skips the RL policy entirely (no obs build, no inference),
  - snapshots the measured pose on the first lowstate as the
    "baseline" and publishes it back at low Kp/Kd
    (kp_scale = LYING_KP_SCALE) as a heartbeat,
  - rebinds keys 1..7 to small per-joint arm wiggles
    (|delta| <= LYING_TEST_DELTA rad) that blend out from baseline,
    hold briefly, then blend back to baseline,
  - disables the walking keys (w/s/a/d/q/e/r/f) and prints a warning
    if pressed.
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

import os

os.environ["CYCLONEDDS_URI"] = """
<CycloneDDS>
  <Domain>
    <Tracing>
      <Verbosity>none</Verbosity>
    </Tracing>
  </Domain>
</CycloneDDS>
"""

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
from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import (
    MotionSwitcherClient,
)


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
# cloned. The script lives at <repo_root>/g1_real_demo/g1_real_rl_combo.py,
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
# Each gesture is built as a *delta from the policy's default arm pose*,
# scaled by per-joint `action_scale`. Concretely:
#
#     arm_pose = arm_rest + k * action_scale[15:29]
#
# where `k` is a 14-D unit-ish vector (each entry ~[-2, +2]). This keeps
# every gesture inside the same envelope the policy saw at training time
# (joint_pos_rel ≈ k * action_scale, so |joint_pos_rel|/action_scale ≈ |k|).
#
# Why not absolute joint angles?
#   The previous version used absolute targets like shoulder_pitch=-1.6 rad.
#   With action_scale=0.44, that's ~4.4× outside the training distribution
#   for that joint, and instantly puts both `joint_pos_rel` and the policy's
#   internal state OOD. Absolute targets that happen to be inside one
#   joint's envelope can still wreck another joint with a smaller scale
#   (e.g. wrist_pitch action_scale=0.07 — a "small" 0.3 rad tilt is 4×
#   that joint's scale). Encoding poses as scale-multiples removes that
#   foot-gun: a vector of ±2's is uniformly safe across all 14 arm DOFs.
# ---------------------------------------------------------------------------
def _arm_zero_delta() -> np.ndarray:
    """Zero-delta = policy's arm_rest."""
    return np.zeros(ARM_DIM, dtype=np.float64)


def _slot(j: int) -> int:
    """Map global joint index (15..28) to arm-local index (0..13)."""
    return j - ARM_START


# Each gesture below returns a 14-D *delta* in units of action_scale,
# i.e. final_pose = arm_rest + delta * action_scale[15:29]. Magnitudes
# are kept |delta| <= 2.0 per joint to stay inside the policy envelope.
# Sign convention follows the absolute-pose conventions of the legacy
# g1_sim_keyboard: shoulder_pitch -negative = arm forward/up,
# shoulder_roll +positive = arm out (left side; mirrored on right),
# elbow +positive = bent.
def wave_right_delta() -> np.ndarray:
    p = _arm_zero_delta()
    p[_slot(J.RightShoulderPitch)] = -2.0   # -0.88 rad delta -> arm slightly forward
    p[_slot(J.RightShoulderRoll)]  = -2.0   # -0.88 rad delta -> arm out to the right
    p[_slot(J.RightElbow)]         =  1.0   #  0.44 rad delta -> elbow bent
    return p


def wave_left_delta() -> np.ndarray:
    p = _arm_zero_delta()
    p[_slot(J.LeftShoulderPitch)] = -2.0
    p[_slot(J.LeftShoulderRoll)]  =  2.0
    p[_slot(J.LeftElbow)]         =  1.0
    return p


def hands_up_delta() -> np.ndarray:
    """Both arms reach forward / upward as far as the envelope allows."""
    p = _arm_zero_delta()
    p[_slot(J.LeftShoulderPitch)]  = -2.0   # default 0.35 + (-2*0.44) = -0.53 rad
    p[_slot(J.RightShoulderPitch)] = -2.0
    p[_slot(J.LeftElbow)]          = -1.0   # straighter than default 0.87
    p[_slot(J.RightElbow)]         = -1.0
    return p


def t_pose_delta() -> np.ndarray:
    p = _arm_zero_delta()
    p[_slot(J.LeftShoulderRoll)]   =  2.0   # default 0.18 + 0.88 = 1.06 rad
    p[_slot(J.RightShoulderRoll)]  = -2.0   # default -0.18 - 0.88 = -1.06 rad
    return p


def salute_delta() -> np.ndarray:
    p = _arm_zero_delta()
    p[_slot(J.RightShoulderPitch)] = -1.5
    p[_slot(J.RightShoulderRoll)]  = -1.0
    p[_slot(J.RightElbow)]         =  1.5   # bent toward forehead
    p[_slot(J.RightWristPitch)]    = -2.0   # action_scale 0.07 -> -0.14 rad
    return p


def clap_delta() -> np.ndarray:
    p = _arm_zero_delta()
    p[_slot(J.LeftShoulderPitch)]  = -1.5
    p[_slot(J.LeftShoulderRoll)]   =  0.5
    p[_slot(J.LeftElbow)]          =  1.0
    p[_slot(J.RightShoulderPitch)] = -1.5
    p[_slot(J.RightShoulderRoll)]  = -0.5
    p[_slot(J.RightElbow)]         =  1.0
    return p


def guard_delta() -> np.ndarray:
    p = _arm_zero_delta()
    p[_slot(J.LeftShoulderPitch)]  = -1.2
    p[_slot(J.LeftShoulderRoll)]   =  1.0
    p[_slot(J.LeftElbow)]          =  1.5
    p[_slot(J.RightShoulderPitch)] = -1.2
    p[_slot(J.RightShoulderRoll)]  = -1.0
    p[_slot(J.RightElbow)]         =  1.5
    return p


def punch_right_delta() -> np.ndarray:
    p = guard_delta()
    p[_slot(J.RightShoulderPitch)] = -2.0
    p[_slot(J.RightShoulderRoll)]  =  0.5     # tuck toward midline a bit
    p[_slot(J.RightElbow)]         = -1.5     # arm extended
    return p


def punch_left_delta() -> np.ndarray:
    p = guard_delta()
    p[_slot(J.LeftShoulderPitch)] = -2.0
    p[_slot(J.LeftShoulderRoll)]  = -0.5
    p[_slot(J.LeftElbow)]         = -1.5
    return p


def materialize(delta: np.ndarray, arm_rest: np.ndarray,
                arm_scale: np.ndarray) -> np.ndarray:
    """Convert a unit-scale delta to an absolute 14-D arm pose."""
    return arm_rest + delta * arm_scale


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
    """Build the gesture table. Each pose is `arm_rest + delta*arm_scale`,
    with delta magnitudes capped at ~2.0 per joint to stay inside the
    policy's training envelope.

    Durations are deliberately conservative (>=1.0s for big swings) so
    joint_vel_rel during the blend stays within training distribution.
    """
    def m(d: np.ndarray) -> np.ndarray:
        return materialize(d, arm_rest, arm_scale)

    wave_r  = m(wave_right_delta())
    wave_l  = m(wave_left_delta())
    hands_u = m(hands_up_delta())
    t_p     = m(t_pose_delta())
    sal     = m(salute_delta())
    clp     = m(clap_delta())
    grd     = m(guard_delta())
    pr      = m(punch_right_delta())
    pl      = m(punch_left_delta())

    return [
        ArmAction("1", "wave right arm",
                  [(1.5, wave_r), hold(wave_r, 0.6),
                   (1.5, arm_rest)]),
        ArmAction("2", "wave left arm",
                  [(1.5, wave_l), hold(wave_l, 0.6),
                   (1.5, arm_rest)]),
        ArmAction("3", "hands up (cheer)",
                  [(1.5, hands_u), hold(hands_u, 0.8),
                   (1.5, arm_rest)]),
        ArmAction("4", "T-pose",
                  [(1.8, t_p), hold(t_p, 1.0),
                   (1.8, arm_rest)]),
        ArmAction("5", "salute",
                  [(1.2, sal), hold(sal, 1.2),
                   (1.2, arm_rest)]),
        ArmAction("6", "clap (twice)",
                  [(1.1, clp), (0.5, arm_rest),
                   (0.5, clp), (1.1, arm_rest)]),
        ArmAction("7", "boxer guard",
                  [(1.2, grd), hold(grd, 0.6),
                   (1.2, arm_rest)]),
        ArmAction("8", "punch combo (jab L+R)",
                  [(0.8, grd),
                   (0.35, pr), (0.30, grd),
                   (0.35, pl), (0.30, grd),
                   (1.2, arm_rest)]),
    ]


# ---------------------------------------------------------------------------
# Lying-down test gestures.
#
# Each gesture moves a SINGLE arm joint by a small absolute delta from the
# captured baseline pose, holds briefly, then returns to baseline. Magnitudes
# are deliberately small (<= LYING_TEST_DELTA = 0.25 rad) and absolute (not
# action_scale-relative) because the policy isn't running and the baseline
# isn't `default_q`.
#
# Use case: robot is lying flat (cable too short to stand) and we just want
# to confirm that lowcmd messages reach the motors and produce visible
# motion. Driving one joint at a time makes it obvious which channel is
# (mis)responding.
# ---------------------------------------------------------------------------
def build_lying_test_actions(arm_baseline: np.ndarray) -> List[ArmAction]:
    """Build the lying-mode wiggle table.

    `arm_baseline` is the 14-D arm slice of the measured pose captured at
    controller start; every gesture is anchored to it and ends back at it.
    """
    base = arm_baseline.copy()

    def wiggle(joint_global: int, delta: float) -> np.ndarray:
        target = base.copy()
        target[joint_global - ARM_START] += delta
        return target

    def bilateral_shoulder_roll(delta: float) -> np.ndarray:
        # +delta on left, -delta on right rolls both arms outward by the
        # same amount; sign mirrored because shoulder_roll is symmetric.
        target = base.copy()
        target[J.LeftShoulderRoll - ARM_START]  += delta
        target[J.RightShoulderRoll - ARM_START] -= delta
        return target

    def one_joint_action(key: str, name: str,
                         joint_global: int, delta: float) -> ArmAction:
        target = wiggle(joint_global, delta)
        return ArmAction(
            key, name,
            [(1.0, target), hold(target, 0.5), (1.0, base)],
        )

    bil_target = bilateral_shoulder_roll(0.10)

    return [
        one_joint_action("1", "wiggle right shoulder pitch +0.15",
                         J.RightShoulderPitch, +0.15),
        one_joint_action("2", "wiggle left shoulder pitch +0.15",
                         J.LeftShoulderPitch,  +0.15),
        one_joint_action("3", "wiggle right elbow +0.20",
                         J.RightElbow,         +0.20),
        one_joint_action("4", "wiggle left elbow +0.20",
                         J.LeftElbow,          +0.20),
        one_joint_action("5", "wiggle right wrist roll +0.15",
                         J.RightWristRoll,     +0.15),
        one_joint_action("6", "wiggle left wrist roll +0.15",
                         J.LeftWristRoll,      +0.15),
        ArmAction("7", "bilateral shoulder roll outward 0.10",
                  [(1.0, bil_target), hold(bil_target, 0.5), (1.0, base)]),
    ]


# ---------------------------------------------------------------------------
# Combo controller: RL legs + waist, keyboard arms.
# ---------------------------------------------------------------------------
class ComboController:
    LOWSTATE_TIMEOUT = 0.2     # seconds; if no lowstate, hold default pose

    # Maximum arm joint deviation from `default` we are willing to command,
    # measured in units of action_scale. The policy was trained where
    # `joint_pos_rel ≈ scale * raw_action` and raw_action lives in roughly
    # [-1, 1], so |joint_pos_rel|/scale on the order of 1.0 is in-distribution
    # and <=2.0 is a reasonable safety margin (slightly outside but still
    # close enough that the MLP's output stays sane on legs/waist). Above
    # ~3.0 the policy starts producing garbage on every dim. See QA5.
    ARM_GESTURE_K = 2.0

    # Per-tick maximum *change* in commanded arm angle, in units of
    # action_scale. Even if the gesture target is within the safe envelope,
    # a too-fast blend produces a `joint_vel_rel` spike that the policy
    # was never trained on. Cap the rate; the gesture's stated duration is
    # still respected unless it would violate this cap.
    ARM_GESTURE_RATE_K_PER_SEC = 4.0

    # ----- Lying-down test mode (no policy, no boot ramp) -----
    # Low gain when holding the captured baseline pose. High enough that
    # arm wiggles are visible on a lying robot, low enough that the legs
    # don't fight the floor.
    LYING_KP_SCALE = 0.2
    # Maximum absolute deviation (rad) of any arm-joint target from the
    # captured baseline pose. Bounds every wiggle gesture, in lieu of the
    # policy-training envelope used in normal mode.
    LYING_TEST_DELTA = 0.25

    # ----- Real-robot startup: how long to wait for first lowstate before
    # giving up with a useful error. The G1 streams lowstate at ~500 Hz once
    # the motors are powered, so 5 s is plenty even on a cold boot.
    LOWSTATE_WAIT_TIMEOUT = 5.0

    def __init__(self, cfg: DeployCfg, policy: Policy,
                 lying_mode: bool = False, real_robot: bool = False):
        self.cfg = cfg
        self.policy = policy
        self.lying_mode = lying_mode
        self.real_robot = real_robot
        self._msc: Optional[MotionSwitcherClient] = None

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

        # Lying-down test mode: snapshot of the measured pose at the time
        # the controller starts. In lying mode the tick publishes this back
        # at low Kp instead of running the policy or the boot ramp toward
        # default_q. Set in `start()` once the first lowstate has arrived.
        self.lying_q_baseline = np.zeros(G1_NUM_MOTOR, dtype=np.float64)

        # Boot ramp (measured pose -> default_q). 5 s instead of 3 s gives the
        # robot time to settle (e.g. when the elastic band is still engaged or
        # the initial pose is far from default_q). Kp is also ramped from
        # boot_kp_floor*kp to full kp over the ramp so an aggressive PD pull
        # can't slingshot the robot before the policy takes over.
        self.boot_q_from: Optional[np.ndarray] = None
        self.boot_t = 0.0
        self.boot_dur = 5.0
        self.boot_kp_floor = 0.3
        self.policy_active = False

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

        # Soft Kp scale.
        self.kp_scale = 1.0
        self._soften_target = 1.0
        self._soften_step = 0.0
        self._soften_steps_left = 0

        self._stop = threading.Event()

    # ----- DDS plumbing
    def init_dds(self):
        # On the real robot the onboard high-level controller (mode "ai" /
        # "normal" / "advanced") owns rt/lowcmd by default and will overwrite
        # anything we publish — so user-visible symptom is "I press 1 and the
        # robot does nothing." Release it BEFORE we open our publisher so
        # there's never a window where two writers fight on the bus. The
        # simulator bridge does not implement MotionSwitcher, so we skip it
        # there (calling the RPC against the sim would just time out).
        if self.real_robot:
            self._release_high_level_mode()

        self.cmd_pub = ChannelPublisher("rt/lowcmd", LowCmd_)
        self.cmd_pub.Init()
        self.state_sub = ChannelSubscriber("rt/lowstate", LowState_)
        self.state_sub.Init(self._on_state, 10)

    def _release_high_level_mode(self):
        """Tell the robot's MotionSwitcher to release whatever high-level
        controller it's currently running, so this script's lowcmd reaches
        the motors. Mirrors the canonical procedure from
        `unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py`:
        loop CheckMode -> ReleaseMode until `result['name']` is empty.

        Failures here are non-fatal and only printed: an older G1 firmware
        without MotionSwitcher will return an error code, in which case the
        user must release the high-level mode manually (L2+R2 on the remote
        / `damping` mode), but the rest of the script can still run."""
        try:
            self._msc = MotionSwitcherClient()
            self._msc.SetTimeout(5.0)
            self._msc.Init()
        except Exception as e:
            print(f"[combo] WARN: could not init MotionSwitcherClient ({e}).")
            print("[combo] If the robot ignores motor commands, switch to")
            print("[combo] low-level mode manually (L2+R2 / damping).")
            self._msc = None
            return

        try:
            status, result = self._msc.CheckMode()
        except Exception as e:
            print(f"[combo] WARN: MotionSwitcher CheckMode raised ({e}).")
            return
        if status != 0 or result is None:
            print(f"[combo] WARN: MotionSwitcher CheckMode failed status={status}.")
            print("[combo] Continuing — release high-level mode manually if motors don't respond.")
            return

        active = result.get("name", "") or ""
        if not active:
            print("[combo] MotionSwitcher: no high-level mode active. OK.")
            return

        print(f"[combo] MotionSwitcher: releasing high-level mode '{active}' ...")
        # Try a few release rounds. CheckMode may briefly still report the
        # old mode while the controller is shutting down.
        deadline = time.monotonic() + 8.0
        while True:
            try:
                self._msc.ReleaseMode()
            except Exception as e:
                print(f"[combo] WARN: ReleaseMode raised ({e}). Continuing.")
                return
            time.sleep(0.5)
            try:
                status, result = self._msc.CheckMode()
            except Exception as e:
                print(f"[combo] WARN: CheckMode raised after release ({e}).")
                return
            if status == 0 and result is not None and not (result.get("name") or ""):
                print("[combo] MotionSwitcher: high-level mode released.")
                return
            if time.monotonic() > deadline:
                still = (result or {}).get("name", "?") if result else "?"
                print(
                    f"[combo] WARN: high-level mode still '{still}' after 8s. "
                    "Continuing anyway."
                )
                return

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
        tables that don't go through `materialize()` can't push the policy
        OOD."""
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

    def start(self):
        # Bounded wait for the first lowstate: previously this was a `while
        # True` busy-loop, so a misconfigured interface or a robot still in
        # high-level mode would leave the script hanging here forever — and
        # because the keyboard reader only opens AFTER start() returns, the
        # user sees "1/2/3 do nothing" instead of a useful error. Time out
        # after LOWSTATE_WAIT_TIMEOUT and raise with a checklist.
        print(
            f"[combo] waiting for first /rt/lowstate "
            f"(timeout {self.LOWSTATE_WAIT_TIMEOUT:.1f}s) ..."
        )
        deadline = time.monotonic() + self.LOWSTATE_WAIT_TIMEOUT
        while not self.first_state_received:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "no rt/lowstate received within "
                    f"{self.LOWSTATE_WAIT_TIMEOUT:.1f}s. Common causes:\n"
                    "  * wrong network interface (check `ip -br addr`)\n"
                    "  * wrong DDS domain (real robot=0, sim=1)\n"
                    "  * robot still in high-level mode and not publishing\n"
                    "    lowstate to subscribers (try power-cycle)\n"
                    "  * robot powered off / Ethernet link down\n"
                    "  * firewall / multicast blocked on this interface"
                )
            time.sleep(0.05)
        measured = np.array(
            [self.low_state.motor_state[i].q for i in range(G1_NUM_MOTOR)],
            dtype=np.float64,
        )

        if self.lying_mode:
            # Snapshot the lying-down pose; everything else hangs off this.
            # arm_rest is rebound to the live arm pose so release_arms() and
            # gesture keyframes that target arm_rest blend back to where the
            # arms actually are, not to the standing default.
            self.lying_q_baseline = measured.copy()
            self.arm_rest = self.lying_q_baseline[ARM_START:ARM_END].copy()
            self.arm_q_target = self.arm_rest.copy()
            self.policy_active = False
            self.last_raw_action[:] = 0.0
            self.kp_scale = self.LYING_KP_SCALE
            tick_target = self._tick_lying
            start_msg = (
                f"[combo] LYING-DOWN TEST MODE. Holding measured pose "
                f"at kp_scale={self.LYING_KP_SCALE:.2f}. "
                f"No policy, no boot ramp."
            )
        else:
            self.boot_q_from = measured.copy()
            # Seed the arm overlay so it matches the boot ramp endpoint.
            self.arm_q_target = self.cfg.default_q[ARM_START:ARM_END].copy()
            self.boot_t = 0.0
            self.policy_active = False
            self.last_raw_action[:] = 0.0
            self.global_phase = 0.0
            # Start with reduced Kp; _tick ramps it up to 1.0 over boot_dur.
            self.kp_scale = self.boot_kp_floor
            tick_target = self._tick
            start_msg = (
                f"[combo] mode_machine={self.mode_machine}. "
                f"Ramping to default pose over {self.boot_dur:.1f} s ..."
            )

        self._thread = RecurrentThread(
            interval=self.cfg.step_dt, target=tick_target, name="combo_control"
        )
        self._thread.Start()
        print(start_msg)

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

        # Boot ramp before policy takes over.
        if not self.policy_active:
            self.boot_t += self.cfg.step_dt
            if self.boot_t >= self.boot_dur:
                self.policy_active = True
                self.kp_scale = 1.0
                print("[combo] policy ready. wsadqe to walk; 1-8 arm gestures; 0 release.")
                self._publish(self.cfg.default_q)
                return
            s = 0.5 - 0.5 * np.cos(np.pi * (self.boot_t / self.boot_dur))
            q_des = (1.0 - s) * self.boot_q_from + s * self.cfg.default_q
            # Ramp Kp from boot_kp_floor -> 1.0 with the same easing so the
            # robot is pulled toward default_q gently at first.
            self.kp_scale = self.boot_kp_floor + (1.0 - self.boot_kp_floor) * s
            self._publish(q_des)
            return

        # ---- Policy step (all 29 joints) ----
        obs = self._build_obs()
        raw_action = self.policy(obs)
        q_target = raw_action * self.cfg.action_scale + self.cfg.action_offset
        # Default: feed back exactly what the policy commanded.
        self.last_raw_action[:] = raw_action

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

            # ---- CRITICAL: keep last_raw_action consistent with what we
            # actually published. The policy's own raw_action[15:29] would
            # imply a different q_target than the override; feeding that
            # mismatched action back into next tick's `last_action` obs
            # decouples joint_pos_rel from last_action, which is the OOD
            # state the policy was *never* trained against. By rewriting
            # the arm slice of last_raw_action to the inverse map of the
            # override, the (joint_pos_rel ≈ scale*last_action) invariant
            # holds and the obs stays in distribution. See QA5 §3.2.
            arm_raw = (arm_q - self.arm_offset) / self.arm_scale
            # Clip to a slightly wider range than [-1, 1] so we don't lie
            # too hard if a clamp boundary is hit; the policy's own actions
            # occasionally exceed [-1, 1] in training too.
            arm_raw = np.clip(arm_raw, -self.ARM_GESTURE_K, self.ARM_GESTURE_K)
            self.last_raw_action[ARM_START:ARM_END] = arm_raw

        self._publish(q_target)
        # Stash what we just published; rate limiter and restart-from-live
        # logic both want it.
        self._last_arm_q_published = q_target[ARM_START:ARM_END].copy()

    # ----- 50 Hz tick for LYING-DOWN TEST MODE
    # No policy, no boot ramp. Publishes the captured baseline pose every
    # tick at low Kp/Kd as a heartbeat, with optional small arm wiggles
    # overlaid via the same _advance_arms / clamp / rate-limit pipeline as
    # the normal-mode arm overlay.
    def _tick_lying(self):
        if self._stop.is_set() or not self.first_state_received:
            return

        # Soften ramp (lets `space` collapse the motors even in lying mode).
        if self._soften_steps_left > 0:
            self.kp_scale += self._soften_step
            self._soften_steps_left -= 1
            if self._soften_steps_left == 0:
                self.kp_scale = self._soften_target

        # Watchdog: if the robot stops sending state, keep publishing the
        # baseline so the motors stay quiet rather than free-running.
        if time.monotonic() - self.last_state_time > self.LOWSTATE_TIMEOUT:
            self._publish(self.lying_q_baseline)
            return

        q_target = self.lying_q_baseline.copy()

        arm_q = self._advance_arms()
        if arm_q is not None:
            arm_q = self._clamp_arm_to_safe_envelope(arm_q)
            arm_q = self._rate_limit_arm_step(arm_q)
            q_target[ARM_START:ARM_END] = arm_q

        self._publish(q_target)
        self._last_arm_q_published = q_target[ARM_START:ARM_END].copy()

    def _clamp_arm_to_safe_envelope(self, arm_q: np.ndarray) -> np.ndarray:
        """Clamp a 14-D arm pose to a safe envelope.

        Normal mode: `default ± K * action_scale` per joint, where K is
        `ARM_GESTURE_K` (default 2.0). This keeps every gesture inside the
        policy's training distribution.

        Lying-down test mode: `baseline ± LYING_TEST_DELTA` per joint
        (uniform 0.25 rad cap). The policy isn't running, so the
        training-distribution envelope is irrelevant; what matters is that
        we don't command large arm motions on a robot whose arms might be
        pinned under its body."""
        if self.lying_mode:
            base = self.lying_q_baseline[ARM_START:ARM_END]
            return np.clip(
                arm_q,
                base - self.LYING_TEST_DELTA,
                base + self.LYING_TEST_DELTA,
            )
        lo = self.arm_offset - self.ARM_GESTURE_K * self.arm_scale
        hi = self.arm_offset + self.ARM_GESTURE_K * self.arm_scale
        return np.clip(arm_q, lo, hi)

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
        joint_vel_rel = dq

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
            self.last_raw_action,     # 29
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
def format_help(actions: List[ArmAction], lying_mode: bool = False) -> str:
    lines = ["", "==== G1 RL walk + arm gesture combo ===="]
    if lying_mode:
        lines.append("LYING-DOWN TEST MODE — robot stays at measured pose.")
        lines.append("No policy, no boot ramp, walking keys disabled.")
        lines.append("Arm wiggles (small per-joint motion, returns to baseline):")
        for a in actions:
            lines.append(f"  {a.key}        {a.name}")
        lines.append("  0        cancel wiggle, return arms to baseline")
    else:
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
    lines.append("  space    soft-disable Kp/Kd (release motors)")
    lines.append("  ?        print this help")
    lines.append("  x / Ctrl-C  quit (settles softly first)")
    lines.append("=========================================")
    return "\n".join(lines)


def main():
    # Parse argv. The legacy positional usage is `<script> <iface>`; we now
    # also accept the literal token `lying` anywhere after the script name to
    # enable lying-down test mode (e.g. `python g1_real_rl_combo.py eno3 lying`).
    raw_args = sys.argv[1:]
    lying_mode = "lying" in raw_args
    pos_args = [a for a in raw_args if a != "lying"]

    real_robot = bool(pos_args) and pos_args[0] not in ("lo", "sim")
    if real_robot:
        ChannelFactoryInitialize(0, pos_args[0])
        if lying_mode:
            print(f"[combo] LYING TEST MODE on {pos_args[0]} (domain 0).")
            print("[combo] No policy, no boot ramp. Robot holds measured pose.")
        else:
            print(f"[combo] real-robot mode on {pos_args[0]} (domain 0).")
            print("[combo] WARNING: keep the e-stop within reach.")
        print(
            "[combo] will release any active high-level mode "
            "(ai/normal/advanced) before taking low-level control."
        )
    else:
        ChannelFactoryInitialize(1, "lo")
        if lying_mode:
            print("[combo] LYING TEST MODE on simulator (domain 1, iface=lo).")
        else:
            print("[combo] simulator mode on lo (domain 1).")

    cfg = DeployCfg(POLICY_YAML)
    print(
        f"[combo] loaded deploy.yaml "
        f"(vx in {cfg.vx_range}, vy in {cfg.vy_range}, wz in {cfg.wz_range}, "
        f"period={cfg.gait_period:.2f}s, step_dt={cfg.step_dt}s)"
    )
    policy = Policy(POLICY_ONNX)
    print(f"[combo] loaded policy: {POLICY_ONNX}")

    ctl = ComboController(cfg, policy, lying_mode=lying_mode, real_robot=real_robot)
    ctl.init_dds()
    try:
        ctl.start()
    except RuntimeError as e:
        # Most likely the lowstate-timeout we now raise. Print and exit
        # cleanly — the user has already typed the command, so a stack
        # trace from a daemon thread is just noise.
        print(f"[combo] startup aborted: {e}")
        return
    # Build the gesture table AFTER start(): in lying mode the baseline arm
    # pose isn't known until the first lowstate has been received and
    # stashed into ctl.arm_rest by start().
    if lying_mode:
        actions = build_lying_test_actions(ctl.arm_rest)
    else:
        actions = build_arm_actions(ctl.arm_rest, ctl.arm_scale)
    actions_by_key = {a.key: a for a in actions}

    DV_X = 0.2
    DV_Y = 0.1
    DW_Z = 0.3
    walking_keys = {"w", "s", "a", "d", "q", "e", "r", "f"}
    print(format_help(actions, lying_mode=lying_mode))

    with RawKeyReader() as kb:
        while True:
            ch = kb.get(0.1)
            if ch is None:
                continue
            if ch == "x" or ch == "\x03":  # x or Ctrl-C
                print("\n[combo] softening and exiting ...")
                break
            if ch == "?":
                print(format_help(actions, lying_mode=lying_mode))
                continue
            if ch == " ":
                print("[combo] soft-disable Kp/Kd")
                ctl.soften(0.0, duration=1.0)
                ctl.set_command(0.0, 0.0, 0.0)
                ctl.release_arms()
                continue

            if lying_mode and ch in walking_keys:
                print("[combo] walking keys disabled in lying-down test mode")
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
                if lying_mode:
                    print("[combo] return arms to baseline")
                else:
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
