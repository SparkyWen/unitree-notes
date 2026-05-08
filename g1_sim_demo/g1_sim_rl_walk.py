"""
G1 RL velocity-tracking demo against unitree_mujoco/simulate_python.

This is the natural sequel to `g1_sim_keyboard.py`. Where that demo only
sends static joint-angle keyframes (good for waving / posing while the
elastic band holds the robot up), this demo loads the trained ONNX policy
shipped with `unitree_rl_mjlab` and runs the *full* RL deployment pipeline:

    rt/lowstate  ─►  build 80-D obs  ─►  policy.onnx  ─►  23-D raw action
        ▲                                                       │
        │                                                       ▼
        └───  publish lowcmd (q_target, Kp, Kd)  ◄─  scale + offset

The same pipeline runs on the real G1 (see `unitree_rl_mjlab/deploy/robots/g1_23dof/`).

Run order:
  Terminal 1:
      conda activate unitree
      cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
      python unitree_mujoco.py
      # In the viewer:
      #   - press '8' a few times to lower the elastic band so the feet
      #     reach the ground (safe), then optionally press '9' to disable
      #     the band entirely. Don't press '9' immediately — the robot
      #     will fall before the policy starts.

  Terminal 2:
      conda activate unitree
      cd ~/unitree/unitree-notes/g1_sim_demo
      python g1_sim_rl_walk.py
      # Wait for "[rl] policy ready, standing in place." then press keys:
      #   w/s   forward / backward       a/d   strafe left / right
      #   q/e   yaw left / right         r     zero command (stand)
      #   f     full forward speed (vx capped at 1.0 m/s by training range)
      #   space soft-disable (Kp,Kd → 0); useful before quitting
      #   x     quit (settles softly first)

Dependencies (one-time):
  pip install onnxruntime          # CPU is fine; ~50 Hz inference is cheap
  # OR pip install onnxruntime-gpu # if you really want CUDA

The policy and its deployment yaml come from:
  ~/unitree/unitree-notes/unitree_rl_mjlab/deploy/robots/g1_23dof/config/policy/velocity/v0/

Note: this policy was trained with vx ∈ [-0.5, 1.0] m/s. So 'f' is "fast walk",
not real running. To get real running, retrain with a wider velocity range
using `unitree_rl_mjlab/scripts/train.py`.
"""

from __future__ import annotations

import select
import sys
import termios
import threading
import time
import tty
from pathlib import Path

import numpy as np
import yaml

try:
    import onnxruntime as ort
except ImportError as e:
    raise SystemExit(
        "[rl] onnxruntime is not installed in the current env. "
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


G1_NUM_MOTOR = 23

POLICY_DIR = (
    Path.home()
    / "unitree/unitree-notes/unitree_rl_mjlab/deploy/robots/g1_23dof"
    / "config/policy/velocity/v0"
)
POLICY_ONNX = POLICY_DIR / "exported" / "policy.onnx"
POLICY_YAML = POLICY_DIR / "params" / "deploy.yaml"


# ---------------------------------------------------------------------------
# Deployment params loaded from deploy.yaml
# ---------------------------------------------------------------------------
class DeployCfg:
    def __init__(self, yaml_path: Path):
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        self.step_dt: float = float(cfg["step_dt"])
        self.kp = np.asarray(cfg["stiffness"], dtype=np.float64)
        self.kd = np.asarray(cfg["damping"], dtype=np.float64)
        self.default_q = np.asarray(cfg["default_joint_pos"], dtype=np.float64)
        self.joint_ids_map = list(cfg["joint_ids_map"])

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

        # Sanity checks.
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
# Policy wrapper
# ---------------------------------------------------------------------------
class Policy:
    OBS_DIM = 80          # 3 + 3 + 3 + 2 + 23 + 23 + 23
    ACT_DIM = G1_NUM_MOTOR

    def __init__(self, onnx_path: Path):
        if not onnx_path.exists():
            raise FileNotFoundError(f"policy not found: {onnx_path}")
        self.session = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
        ins = self.session.get_inputs()
        outs = self.session.get_outputs()
        if len(ins) != 1 or len(outs) != 1:
            raise RuntimeError(
                f"policy.onnx has {len(ins)} input(s) / {len(outs)} output(s); "
                "expected 1 of each."
            )
        self.in_name = ins[0].name
        self.out_name = outs[0].name
        in_shape = ins[0].shape
        out_shape = outs[0].shape
        # Allow batch dim or fixed; just verify the trailing dim.
        if in_shape[-1] != self.OBS_DIM:
            raise RuntimeError(
                f"policy expects obs dim {in_shape[-1]}, demo builds {self.OBS_DIM}."
            )
        if out_shape[-1] != self.ACT_DIM:
            raise RuntimeError(
                f"policy outputs dim {out_shape[-1]}, demo expects {self.ACT_DIM}."
            )

    def __call__(self, obs: np.ndarray) -> np.ndarray:
        x = obs.astype(np.float32, copy=False).reshape(1, self.OBS_DIM)
        y = self.session.run([self.out_name], {self.in_name: x})[0]
        return y.reshape(self.ACT_DIM)


# ---------------------------------------------------------------------------
# Math helper: rotate a world-frame vector into body frame using IMU quaternion.
# Unitree LowState quaternion is [w, x, y, z]. The body's world orientation R
# satisfies v_world = R * v_body, so v_body = R^T * v_world. With unit quat
# [w, x, y, z], R^T application equals rotation by the conjugate [w,-x,-y,-z].
# ---------------------------------------------------------------------------
def quat_rotate_inverse(quat_wxyz: np.ndarray, v_world: np.ndarray) -> np.ndarray:
    w, x, y, z = quat_wxyz
    # Standard formula for q^{-1} * v * q on a pure quaternion vec.
    vx, vy, vz = v_world
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    # v' = v - w*t + cross(q.xyz, t)   (this is rotation by conjugate)
    rx = vx - w * tx + (y * tz - z * ty)
    ry = vy - w * ty + (z * tx - x * tz)
    rz = vz - w * tz + (x * ty - y * tx)
    return np.array([rx, ry, rz], dtype=np.float64)


GRAVITY_W = np.array([0.0, 0.0, -1.0], dtype=np.float64)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------
class RLController:
    LOWSTATE_TIMEOUT = 0.2     # seconds; if no lowstate, freeze command

    def __init__(self, cfg: DeployCfg, policy: Policy):
        self.cfg = cfg
        self.policy = policy

        self.low_cmd = unitree_hg_msg_dds__LowCmd_()
        self.low_state: LowState_ | None = None
        self.last_state_time = 0.0
        self.first_state_received = False
        self.mode_machine = 0
        self.crc = CRC()

        # Command (set by keyboard thread).
        self._cmd_lock = threading.Lock()
        self._cmd = np.zeros(3, dtype=np.float64)   # [vx, vy, wz]

        # State of the policy loop.
        self.last_raw_action = np.zeros(G1_NUM_MOTOR, dtype=np.float64)
        self.global_phase = 0.0                      # in [0, 1)

        # Boot-up ramp from initial measured pose to default_joint_pos.
        # This runs at the same 50 Hz tick before policy starts.
        self.boot_q_from: np.ndarray | None = None
        self.boot_t = 0.0
        self.boot_dur = 3.0
        self.policy_active = False

        # Soft Kp scale (1.0 normal; ramped to 0 on quit / space).
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

    def soften(self, target_scale: float = 0.0, duration: float = 1.0):
        steps = int(max(duration, 1e-3) / self.cfg.step_dt)
        self._soften_target = float(target_scale)
        self._soften_step = (self._soften_target - self.kp_scale) / max(steps, 1)
        self._soften_steps_left = steps

    def start(self):
        print("[rl] waiting for first /rt/lowstate ...")
        while not self.first_state_received:
            time.sleep(0.05)
        # Seed the ramp: blend from measured initial pose to default_q.
        measured = np.array(
            [self.low_state.motor_state[i].q for i in range(G1_NUM_MOTOR)],
            dtype=np.float64,
        )
        self.boot_q_from = measured.copy()
        self.boot_t = 0.0
        self.policy_active = False

        # Pre-fill last_raw_action so the first obs is sane.
        self.last_raw_action[:] = 0.0
        self.global_phase = 0.0

        self._thread = RecurrentThread(
            interval=self.cfg.step_dt, target=self._tick, name="rl_control"
        )
        self._thread.Start()
        print(
            f"[rl] mode_machine={self.mode_machine}. "
            f"Ramping to default pose over {self.boot_dur:.1f} s ..."
        )

    def stop_and_settle(self):
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

        if not self.policy_active:
            # Boot-up ramp: cosine ease-in-out from boot_q_from → default_q.
            self.boot_t += self.cfg.step_dt
            if self.boot_t >= self.boot_dur:
                self.policy_active = True
                print("[rl] policy ready, standing in place. wsadqe to drive.")
                self._publish(self.cfg.default_q)
                return
            s = 0.5 - 0.5 * np.cos(np.pi * (self.boot_t / self.boot_dur))
            q_des = (1.0 - s) * self.boot_q_from + s * self.cfg.default_q
            self._publish(q_des)
            return

        # ---- Policy step ----
        obs = self._build_obs()
        raw_action = self.policy(obs)

        # Apply scale + offset to get joint targets, then publish.
        q_target = raw_action * self.cfg.action_scale + self.cfg.action_offset
        self._publish(q_target)

        self.last_raw_action[:] = raw_action

    def _build_obs(self) -> np.ndarray:
        s = self.low_state
        # Joint pos / vel.
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

        # IMU.
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
        # If the simulator hasn't filled the quaternion yet (all zeros),
        # fall back to identity to avoid NaNs.
        if np.linalg.norm(quat) < 1e-6:
            quat = np.array([1.0, 0.0, 0.0, 0.0])
        projected_gravity = quat_rotate_inverse(quat, GRAVITY_W)

        # Command + gait phase.
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
            joint_pos_rel,            # 23
            joint_vel_rel,            # 23
            self.last_raw_action,     # 23
        ])  # → 80

    def _publish(self, q_des: np.ndarray):
        # mode_pr = 0 (PR mode); same as g1_sim_keyboard.py and the deploy
        # config. mode_machine echoes whatever the bridge reports first.
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
HELP = """
==== G1 RL velocity demo ====
  w / s     forward / backward   (vx ±0.2 m/s, clamped to training range)
  a / d     strafe left / right  (vy ±0.1 m/s)
  q / e     yaw left / right     (wz ±0.3 rad/s)
  r         zero command (stand still)
  f         full forward speed (vx → vx_max)
  space     soft-disable (Kp,Kd → 0); robot collapses gently
  ?         print this help
  x / Ctrl-C  quit (settles softly first)
==================================
""".strip()


def main():
    if len(sys.argv) > 1 and sys.argv[1] not in ("lo", "sim"):
        ChannelFactoryInitialize(0, sys.argv[1])
        print(f"[rl] real-robot mode on {sys.argv[1]} (domain 0).")
        print("[rl] WARNING: keep the e-stop within reach.")
    else:
        ChannelFactoryInitialize(1, "lo")
        print("[rl] simulator mode on lo (domain 1).")

    cfg = DeployCfg(POLICY_YAML)
    print(
        f"[rl] loaded deploy.yaml "
        f"(vx∈{cfg.vx_range}, vy∈{cfg.vy_range}, wz∈{cfg.wz_range}, "
        f"period={cfg.gait_period:.2f}s, step_dt={cfg.step_dt}s)"
    )
    policy = Policy(POLICY_ONNX)
    print(f"[rl] loaded policy: {POLICY_ONNX}")

    ctl = RLController(cfg, policy)
    ctl.init_dds()
    ctl.start()

    # ---- key thresholds for incremental commands
    DV_X = 0.2
    DV_Y = 0.1
    DW_Z = 0.3
    print(HELP)

    with RawKeyReader() as kb:
        while True:
            ch = kb.get(0.1)
            if ch is None:
                continue
            cmd = ctl.get_command()
            if ch == "x" or ch == "\x03":  # x or Ctrl-C
                print("\n[rl] softening and exiting ...")
                break
            elif ch == "?":
                print(HELP)
            elif ch == "w":
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
            elif ch == " ":
                print("[rl] soft-disable Kp/Kd")
                ctl.soften(0.0, duration=1.0)
                ctl.set_command(0.0, 0.0, 0.0)
            else:
                continue
            new_cmd = ctl.get_command()
            print(
                f"[rl] cmd = vx={new_cmd[0]:+.2f}  vy={new_cmd[1]:+.2f}  "
                f"wz={new_cmd[2]:+.2f}"
            )

    ctl.stop_and_settle()
    print("[rl] done.")


if __name__ == "__main__":
    main()
