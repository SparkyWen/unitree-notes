"""
G1 interactive low-level demo against unitree_mujoco/simulate_python.

Run order:
  Terminal 1:
      conda activate unitree
      cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
      python unitree_mujoco.py
      # In the viewer, press '9' to grab the elastic band (keeps G1 upright).

  Terminal 2:
      conda activate unitree
      cd ~/unitree/unitree-notes/g1_sim_demo
      python g1_sim_interactive.py
      # Then press keys in this terminal:
      #   z = zero pose          w = wave right arm
      #   b = bow (waist pitch)  k = lift left knee
      #   a = clap (both arms)   q = quit (ramp back to zero first)

Architecture:
  - A control thread runs at 500 Hz. Each tick it advances toward `q_target`
    using a smooth (cosine) interpolation between two keyframes, and writes
    the resulting pose into a LowCmd_ which is published on rt/lowcmd.
  - Pressing a key enqueues a *sequence* of keyframes (each keyframe is a
    full 29-dim pose + a duration). The control thread plays them back
    one after another. The robot never jumps — every motion is a smooth
    blend from the current commanded pose to the next keyframe.
  - LowState_ from the simulator is captured in a callback so we always
    know the real measured pose; only the *first* state is used as the
    starting pose for the initial ramp to zero.
"""

import sys
import time
import threading
import queue
import termios
import tty
import select

import numpy as np

from unitree_sdk2py.core.channel import (
    ChannelPublisher,
    ChannelSubscriber,
    ChannelFactoryInitialize,
)
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_
from unitree_sdk2py.utils.crc import CRC
from unitree_sdk2py.utils.thread import RecurrentThread


# ---------------------------------------------------------------------------
# Joint layout (G1 29-DOF, mode_pr = PR variant; see g1_joint_index_dds.md)
# ---------------------------------------------------------------------------
G1_NUM_MOTOR = 29

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
    WaistRoll          = 13   # = WaistA in AB mode
    WaistPitch         = 14   # = WaistB in AB mode
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


# Same gains as the upstream g1 example — tuned for the 29-DOF model.
Kp = np.array([
    60, 60, 60, 100, 40, 40,      # left leg
    60, 60, 60, 100, 40, 40,      # right leg
    60, 40, 40,                   # waist (yaw, roll/A, pitch/B)
    40, 40, 40, 40, 40, 40, 40,   # left arm
    40, 40, 40, 40, 40, 40, 40,   # right arm
], dtype=np.float64)

Kd = np.array([
    1, 1, 1, 2, 1, 1,
    1, 1, 1, 2, 1, 1,
    1, 1, 1,
    1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1,
], dtype=np.float64)


class Mode:
    PR = 0   # ankle/waist expressed as Pitch+Roll
    AB = 1   # ankle/waist expressed as motor A+B


# ---------------------------------------------------------------------------
# Pose helpers — every "pose" is a length-29 numpy array of joint angles (rad)
# ---------------------------------------------------------------------------
def zero_pose() -> np.ndarray:
    return np.zeros(G1_NUM_MOTOR, dtype=np.float64)


def wave_right_arm_pose() -> np.ndarray:
    p = zero_pose()
    p[J.RightShoulderPitch] = -0.4    # raise arm forward/up
    p[J.RightShoulderRoll]  = -1.2    # out to the side
    p[J.RightElbow]         =  1.4    # bend elbow up
    p[J.RightWristRoll]     =  0.0
    return p


def bow_pose() -> np.ndarray:
    p = zero_pose()
    p[J.WaistPitch] = 0.5             # lean forward ~28 deg
    return p


def lift_left_knee_pose() -> np.ndarray:
    p = zero_pose()
    p[J.LeftHipPitch]   = -1.0
    p[J.LeftKnee]       =  1.6
    p[J.LeftAnklePitch] = -0.5
    return p


def clap_pose() -> np.ndarray:
    p = zero_pose()
    # both arms forward, hands meet near the chest
    p[J.LeftShoulderPitch]  = -0.8
    p[J.LeftShoulderRoll]   =  0.4
    p[J.LeftElbow]          =  1.2
    p[J.RightShoulderPitch] = -0.8
    p[J.RightShoulderRoll]  = -0.4
    p[J.RightElbow]         =  1.2
    return p


# Each "trajectory" is a list of (duration_seconds, target_pose) tuples.
# The controller blends from whatever it's currently commanding to the
# first target over `duration`, then to the second, etc.
TRAJECTORIES = {
    "z": [(2.0, zero_pose())],
    "w": [(1.5, wave_right_arm_pose()),
          (0.6, wave_right_arm_pose() * np.array([1]*26 + [1, 1, 1])),  # hold
          (1.5, zero_pose())],
    "b": [(1.5, bow_pose()), (1.0, bow_pose()), (1.5, zero_pose())],
    "k": [(1.5, lift_left_knee_pose()), (1.0, lift_left_knee_pose()),
          (1.5, zero_pose())],
    "a": [(1.2, clap_pose()), (0.4, zero_pose()), (0.4, clap_pose()),
          (0.4, zero_pose()), (0.4, clap_pose()), (1.2, zero_pose())],
}

KEY_HELP = """
Keys (focus this terminal):
  z = ramp to zero pose
  w = wave right arm
  b = bow (waist pitch)
  k = lift left knee
  a = clap (twice)
  q = quit  (ramps to zero first, then exits)
""".strip()


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------
class G1Controller:
    """500 Hz position-control loop driven by a queue of keyframes."""

    CONTROL_DT = 0.002   # 500 Hz

    def __init__(self):
        self.low_cmd = unitree_hg_msg_dds__LowCmd_()
        self.low_state: LowState_ = None
        self.first_state_received = False
        self.mode_machine = 0
        self.crc = CRC()

        # Currently-commanded pose. Starts as None until first lowstate.
        self.q_cmd = None
        # Active keyframe = (q_from, q_to, duration, t_elapsed).
        self._active = None
        # FIFO of pending keyframes (q_to, duration). Pose chains through them.
        self._queue: "queue.Queue[tuple[float, np.ndarray]]" = queue.Queue()

        self._stop = threading.Event()

    # ------------------------------------------------------------------ DDS
    def init_dds(self):
        self.cmd_pub = ChannelPublisher("rt/lowcmd", LowCmd_)
        self.cmd_pub.Init()
        self.state_sub = ChannelSubscriber("rt/lowstate", LowState_)
        self.state_sub.Init(self._on_state, 10)

    def _on_state(self, msg: LowState_):
        self.low_state = msg
        if not self.first_state_received:
            self.mode_machine = msg.mode_machine
            # Seed q_cmd to whatever the robot is currently at, so the first
            # commanded pose doesn't jump.
            self.q_cmd = np.array(
                [msg.motor_state[i].q for i in range(G1_NUM_MOTOR)],
                dtype=np.float64,
            )
            self.first_state_received = True

    # -------------------------------------------------------------- public
    def push(self, trajectory: list):
        """Append a sequence of (duration, target_pose) keyframes."""
        for dur, pose in trajectory:
            self._queue.put((float(dur), np.asarray(pose, dtype=np.float64)))

    def start(self):
        print("[g1] waiting for first /rt/lowstate ...")
        while not self.first_state_received:
            time.sleep(0.05)
        print(f"[g1] got lowstate (mode_machine={self.mode_machine}). "
              f"Ramping to zero pose over 3 s.")
        self.push([(3.0, zero_pose())])
        self._thread = RecurrentThread(
            interval=self.CONTROL_DT, target=self._tick, name="g1_control"
        )
        self._thread.Start()

    def stop_and_settle(self):
        """Drain queue, ramp to zero, then stop publishing."""
        # Empty whatever is queued.
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._active = None
        self.push([(2.0, zero_pose())])
        # Wait until current+queued motion finishes.
        while self._active is not None or not self._queue.empty():
            time.sleep(0.05)
        self._stop.set()

    # -------------------------------------------------------------- tick
    def _tick(self):
        if not self.first_state_received or self._stop.is_set():
            return

        # If no active keyframe, pull the next one from the queue.
        if self._active is None and not self._queue.empty():
            dur, q_to = self._queue.get_nowait()
            self._active = [self.q_cmd.copy(), q_to, max(dur, 1e-3), 0.0]

        if self._active is not None:
            q_from, q_to, dur, t = self._active
            t += self.CONTROL_DT
            if t >= dur:
                self.q_cmd = q_to.copy()
                self._active = None
            else:
                # Cosine ease-in-out: smoother than linear, safer for joints.
                s = 0.5 - 0.5 * np.cos(np.pi * (t / dur))
                self.q_cmd = (1.0 - s) * q_from + s * q_to
                self._active[3] = t

        self._publish(self.q_cmd)

    def _publish(self, q_des: np.ndarray):
        self.low_cmd.mode_pr = Mode.PR
        self.low_cmd.mode_machine = self.mode_machine
        for i in range(G1_NUM_MOTOR):
            m = self.low_cmd.motor_cmd[i]
            m.mode = 1            # enable PD control
            m.q    = float(q_des[i])
            m.dq   = 0.0
            m.tau  = 0.0
            m.kp   = float(Kp[i])
            m.kd   = float(Kd[i])
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

    def get(self, timeout: float = 0.1) -> str | None:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if r else None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) > 1 and sys.argv[1] not in ("lo", "sim"):
        ChannelFactoryInitialize(0, sys.argv[1])
        print(f"[g1] real-robot mode on {sys.argv[1]} (domain 0).")
    else:
        ChannelFactoryInitialize(1, "lo")
        print("[g1] simulator mode on lo (domain 1).")

    ctl = G1Controller()
    ctl.init_dds()
    ctl.start()

    print(KEY_HELP)
    with RawKeyReader() as kb:
        while True:
            ch = kb.get(0.1)
            if ch is None:
                continue
            if ch == "q":
                print("\n[g1] settling to zero, then exiting ...")
                ctl.stop_and_settle()
                break
            traj = TRAJECTORIES.get(ch)
            if traj is None:
                continue
            print(f"[g1] play '{ch}' ({len(traj)} keyframes)")
            ctl.push(traj)

    print("[g1] done.")


if __name__ == "__main__":
    main()
