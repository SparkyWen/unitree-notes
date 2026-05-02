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

Why arms must NOT stay locked when idle
  The policy was trained with `actuator_names=(".*",)`, i.e. arms
  included. It learns to swing the arms during walking/turning to
  cancel leg-induced angular momentum. Pinning the arms to default_q
  full-time breaks that — the body's yaw momentum has nowhere to go,
  so the torso starts spinning, and the joint_pos_rel / last_action
  observation pair becomes out-of-distribution (policy commanded a
  swing, joints didn't move), which drives the legs to flail. That
  failure mode is exactly "press w/s/a/d -> legs go crazy + robot
  spins, r doesn't recover", which is why the overlay is gated on a
  live gesture.

Why only arms can be temporarily overridden:
  Legs are responsible for balance; waist orientation feeds directly
  into the projected_gravity observation, so a commanded waist tilt
  would make the policy think "I'm falling" and drive the wrong
  recovery torques. Arms are mass-light and the policy is robust to
  short, slow arm overrides, so brief gesture overlays are safe.

Run order
---------
  Terminal 1:
      conda activate unitree
      cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
      python unitree_mujoco.py
      # press 8 a few times to lower elastic band; optionally 9 to disable

  Terminal 2:
      conda activate unitree
      cd ~/unitree/unitree-notes/g1_sim_demo
      python g1_sim_rl_combo.py
      # wait for "[combo] policy ready" then press keys

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


POLICY_DIR = (
    Path.home()
    / "unitree/unitree-notes/unitree_rl_mjlab/deploy/robots/g1"
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
# Arm gesture poses. Each function returns a 14-D np.ndarray of joint angles
# (rad) for arm joints [LeftShoulderPitch .. RightWristYaw]. Values are
# absolute targets, not deltas. Keep them within G1's safe envelope
# (|q_shoulder/elbow| <= ~1.6, wrists smaller).
# ---------------------------------------------------------------------------
def _arm_zero() -> np.ndarray:
    """Hands hanging straight down (g1_sim_keyboard's reference)."""
    return np.zeros(ARM_DIM, dtype=np.float64)


def _slot(j: int) -> int:
    """Map global joint index (15..28) to arm-local index (0..13)."""
    return j - ARM_START


def wave_right() -> np.ndarray:
    p = _arm_zero()
    p[_slot(J.RightShoulderPitch)] = -0.4
    p[_slot(J.RightShoulderRoll)]  = -1.2
    p[_slot(J.RightElbow)]         =  1.4
    return p


def wave_left() -> np.ndarray:
    p = _arm_zero()
    p[_slot(J.LeftShoulderPitch)] = -0.4
    p[_slot(J.LeftShoulderRoll)]  =  1.2
    p[_slot(J.LeftElbow)]         =  1.4
    return p


def hands_up() -> np.ndarray:
    p = _arm_zero()
    p[_slot(J.LeftShoulderPitch)]  = -1.6
    p[_slot(J.RightShoulderPitch)] = -1.6
    return p


def t_pose() -> np.ndarray:
    p = _arm_zero()
    p[_slot(J.LeftShoulderRoll)]   =  1.5
    p[_slot(J.RightShoulderRoll)]  = -1.5
    return p


def salute() -> np.ndarray:
    p = _arm_zero()
    p[_slot(J.RightShoulderPitch)] = -0.6
    p[_slot(J.RightShoulderRoll)]  = -0.4
    p[_slot(J.RightElbow)]         =  1.55
    p[_slot(J.RightWristPitch)]    = -0.3
    return p


def clap() -> np.ndarray:
    p = _arm_zero()
    p[_slot(J.LeftShoulderPitch)]  = -0.8
    p[_slot(J.LeftShoulderRoll)]   =  0.4
    p[_slot(J.LeftElbow)]          =  1.2
    p[_slot(J.RightShoulderPitch)] = -0.8
    p[_slot(J.RightShoulderRoll)]  = -0.4
    p[_slot(J.RightElbow)]         =  1.2
    return p


def guard() -> np.ndarray:
    p = _arm_zero()
    p[_slot(J.LeftShoulderPitch)]  = -0.6
    p[_slot(J.LeftShoulderRoll)]   =  0.5
    p[_slot(J.LeftElbow)]          =  1.4
    p[_slot(J.RightShoulderPitch)] = -0.6
    p[_slot(J.RightShoulderRoll)]  = -0.5
    p[_slot(J.RightElbow)]         =  1.4
    return p


def punch_right() -> np.ndarray:
    p = guard()
    p[_slot(J.RightShoulderPitch)] = -1.0
    p[_slot(J.RightShoulderRoll)]  = -0.1
    p[_slot(J.RightElbow)]         =  0.1
    return p


def punch_left() -> np.ndarray:
    p = guard()
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


def build_arm_actions(arm_rest: np.ndarray) -> List[ArmAction]:
    """Build the gesture table. arm_rest is policy default arm pose."""
    return [
        ArmAction("1", "wave right arm",
                  [(1.2, wave_right()), hold(wave_right(), 0.6),
                   (1.2, arm_rest)]),
        ArmAction("2", "wave left arm",
                  [(1.2, wave_left()), hold(wave_left(), 0.6),
                   (1.2, arm_rest)]),
        ArmAction("3", "hands up (cheer)",
                  [(1.2, hands_up()), hold(hands_up(), 0.8),
                   (1.2, arm_rest)]),
        ArmAction("4", "T-pose",
                  [(1.5, t_pose()), hold(t_pose(), 1.0),
                   (1.5, arm_rest)]),
        ArmAction("5", "salute",
                  [(1.0, salute()), hold(salute(), 1.2),
                   (1.0, arm_rest)]),
        ArmAction("6", "clap (twice)",
                  [(0.9, clap()), (0.4, arm_rest),
                   (0.4, clap()), (0.9, arm_rest)]),
        ArmAction("7", "boxer guard",
                  [(1.0, guard()), hold(guard(), 0.6),
                   (1.0, arm_rest)]),
        ArmAction("8", "punch combo (jab L+R)",
                  [(0.6, guard()),
                   (0.25, punch_right()), (0.25, guard()),
                   (0.25, punch_left()),  (0.25, guard()),
                   (1.0, arm_rest)]),
    ]


# ---------------------------------------------------------------------------
# Combo controller: RL legs + waist, keyboard arms.
# ---------------------------------------------------------------------------
class ComboController:
    LOWSTATE_TIMEOUT = 0.2     # seconds; if no lowstate, hold default pose

    def __init__(self, cfg: DeployCfg, policy: Policy):
        self.cfg = cfg
        self.policy = policy

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

        # Soft Kp scale.
        self.kp_scale = 1.0
        self._soften_target = 1.0
        self._soften_step = 0.0
        self._soften_steps_left = 0

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
        from a policy-controlled state doesn't snap the arms."""
        with self._arm_lock:
            # Seed arm_q_target with where the arms actually are right now,
            # otherwise (if the policy was controlling them and had them
            # swung mid-gait) the blend would start from a stale value and
            # cause a position step.
            self.arm_q_target = self._read_current_arm_q()
            self.arm_queue = [(float(d), p.copy()) for d, p in keyframes]
            self.arm_blend_from = None
            self.arm_blend_to = None
            self.arm_blend_dur = 0.0
            self.arm_blend_t = 0.0
            self._arm_override_active = True

    def release_arms(self):
        """If a gesture is in progress, ramp arms back to rest and hand
        them back to the policy. If arms are already policy-controlled
        this is a no-op (don't grab arms just to release them)."""
        with self._arm_lock:
            if not self._arm_override_active and not self.arm_queue:
                return
            self.arm_q_target = self._read_current_arm_q()
            self.arm_queue = [(1.0, self.arm_rest.copy())]
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
        self.policy_active = False
        self.last_raw_action[:] = 0.0
        self.global_phase = 0.0
        # Start with reduced Kp; _tick ramps it up to 1.0 over boot_dur.
        self.kp_scale = self.boot_kp_floor

        self._thread = RecurrentThread(
            interval=self.cfg.step_dt, target=self._tick, name="combo_control"
        )
        self._thread.Start()
        print(
            f"[combo] mode_machine={self.mode_machine}. "
            f"Ramping to default pose over {self.boot_dur:.1f} s ..."
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
        self.last_raw_action[:] = raw_action

        # ---- Arm overlay: only override q_target[15:29] if a gesture is
        # actively playing. Otherwise the policy keeps full control of the
        # arms (it learned to swing them for balance during walking).
        arm_q = self._advance_arms()
        if arm_q is not None:
            q_target[ARM_START:ARM_END] = arm_q

        self._publish(q_target)

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
    actions = build_arm_actions(ctl.arm_rest)
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
