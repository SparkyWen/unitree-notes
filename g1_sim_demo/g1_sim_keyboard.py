"""
G1 keyboard playground for unitree_mujoco/simulate_python.

This is a fuller version of `g1_sim_interactive.py`:
  - many more preset upper-body / lower-body actions
  - a real `reset` that captures the very first measured pose at startup and
    can return to it any time via the `r` key (or the dedicated 'INIT' key)
  - emergency-soften via 'x' (drops Kp/Kd to zero gently — useful when the
    elastic band is on and you want to "untension" without shutting down)
  - per-action duration scaling so you can slow everything down for debug
  - safe shutdown that always settles to zero pose first

Run order (read ./use1.md for details):

  Terminal 1:
      conda activate unitree
      cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
      python unitree_mujoco.py       # leaves G1 hanging from the elastic band

  Terminal 2:
      conda activate unitree
      cd ~/unitree/unitree-notes/g1_sim_demo
      python g1_sim_keyboard.py
      # press '?' inside this terminal for the live key map.

Architecture (same idea as g1_sim_interactive.py, just bigger):
  - control thread @ 500 Hz
  - each tick advances toward q_target via cosine ease-in-out between the last
    "from" pose and the current keyframe's target
  - pressing a key enqueues a sequence of (duration, target_pose) keyframes
  - LowState_ subscriber captures the very first measured pose -> that becomes
    the persistent INIT_POSE that 'r' / 'i' restore
"""

import sys
import time
import threading
import queue
import termios
import tty
import select
from dataclasses import dataclass

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
# G1 29-DOF joint indices (PR mode). See unitree_robots/g1/g1_joint_index_dds.md.
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


# Same gains as g1_sim_low_level.py — tuned for the 29-DOF model.
KP_DEFAULT = np.array([
    60, 60, 60, 100, 40, 40,      # left leg
    60, 60, 60, 100, 40, 40,      # right leg
    60, 40, 40,                   # waist
    40, 40, 40, 40, 40, 40, 40,   # left arm
    40, 40, 40, 40, 40, 40, 40,   # right arm
], dtype=np.float64)

KD_DEFAULT = np.array([
    1, 1, 1, 2, 1, 1,
    1, 1, 1, 2, 1, 1,
    1, 1, 1,
    1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1,
], dtype=np.float64)


class Mode:
    PR = 0
    AB = 1


# ---------------------------------------------------------------------------
# Pose builders. Every "pose" is a length-29 numpy array of joint angles (rad).
# Keep all values within the conservative envelope used by upstream demos:
# - shoulders/elbows: |q| <= ~1.6 rad
# - hips/knees/ankles: |q| <= ~1.6 rad
# - waist: |q| <= 0.5 rad
# ---------------------------------------------------------------------------
def zero_pose() -> np.ndarray:
    return np.zeros(G1_NUM_MOTOR, dtype=np.float64)


# ---- arms ----------------------------------------------------------------
def wave_right_pose() -> np.ndarray:
    p = zero_pose()
    p[J.RightShoulderPitch] = -0.4
    p[J.RightShoulderRoll]  = -1.2
    p[J.RightElbow]         =  1.4
    return p


def wave_left_pose() -> np.ndarray:
    p = zero_pose()
    p[J.LeftShoulderPitch] = -0.4
    p[J.LeftShoulderRoll]  =  1.2
    p[J.LeftElbow]         =  1.4
    return p


def hands_up_pose() -> np.ndarray:
    """Both arms straight up."""
    p = zero_pose()
    p[J.LeftShoulderPitch]  = -1.6
    p[J.RightShoulderPitch] = -1.6
    return p


def t_pose() -> np.ndarray:
    """Both arms straight out to the sides."""
    p = zero_pose()
    p[J.LeftShoulderRoll]   =  1.5
    p[J.RightShoulderRoll]  = -1.5
    return p


def salute_pose() -> np.ndarray:
    p = zero_pose()
    p[J.RightShoulderPitch] = -0.6
    p[J.RightShoulderRoll]  = -0.4
    p[J.RightElbow]         =  1.55
    p[J.RightWristRoll]     =  0.0
    p[J.RightWristPitch]    = -0.3
    return p


def clap_pose() -> np.ndarray:
    p = zero_pose()
    p[J.LeftShoulderPitch]  = -0.8
    p[J.LeftShoulderRoll]   =  0.4
    p[J.LeftElbow]          =  1.2
    p[J.RightShoulderPitch] = -0.8
    p[J.RightShoulderRoll]  = -0.4
    p[J.RightElbow]         =  1.2
    return p


def hug_pose() -> np.ndarray:
    p = zero_pose()
    p[J.LeftShoulderPitch]  = -0.8
    p[J.LeftShoulderRoll]   =  0.6
    p[J.LeftElbow]          =  1.5
    p[J.RightShoulderPitch] = -0.8
    p[J.RightShoulderRoll]  = -0.6
    p[J.RightElbow]         =  1.5
    return p


def boxer_guard_pose() -> np.ndarray:
    p = zero_pose()
    p[J.LeftShoulderPitch]  = -0.6
    p[J.LeftShoulderRoll]   =  0.5
    p[J.LeftElbow]          =  1.4
    p[J.RightShoulderPitch] = -0.6
    p[J.RightShoulderRoll]  = -0.5
    p[J.RightElbow]         =  1.4
    return p


def punch_right_pose() -> np.ndarray:
    p = boxer_guard_pose()
    p[J.RightShoulderPitch] = -1.0
    p[J.RightShoulderRoll]  = -0.1
    p[J.RightElbow]         =  0.1
    return p


def punch_left_pose() -> np.ndarray:
    p = boxer_guard_pose()
    p[J.LeftShoulderPitch] = -1.0
    p[J.LeftShoulderRoll]  =  0.1
    p[J.LeftElbow]         =  0.1
    return p


# ---- waist ---------------------------------------------------------------
def bow_pose() -> np.ndarray:
    p = zero_pose()
    p[J.WaistPitch] = 0.5
    return p


def lean_left_pose() -> np.ndarray:
    p = zero_pose()
    p[J.WaistRoll] = 0.35
    return p


def lean_right_pose() -> np.ndarray:
    p = zero_pose()
    p[J.WaistRoll] = -0.35
    return p


def twist_left_pose() -> np.ndarray:
    p = zero_pose()
    p[J.WaistYaw] = 0.5
    return p


def twist_right_pose() -> np.ndarray:
    p = zero_pose()
    p[J.WaistYaw] = -0.5
    return p


# ---- legs (only safe while the elastic band is engaged!) -----------------
def lift_left_knee_pose() -> np.ndarray:
    p = zero_pose()
    p[J.LeftHipPitch]   = -1.0
    p[J.LeftKnee]       =  1.6
    p[J.LeftAnklePitch] = -0.5
    return p


def lift_right_knee_pose() -> np.ndarray:
    p = zero_pose()
    p[J.RightHipPitch]   = -1.0
    p[J.RightKnee]       =  1.6
    p[J.RightAnklePitch] = -0.5
    return p


def squat_pose() -> np.ndarray:
    p = zero_pose()
    p[J.LeftHipPitch]    = -0.8
    p[J.LeftKnee]        =  1.3
    p[J.LeftAnklePitch]  = -0.5
    p[J.RightHipPitch]   = -0.8
    p[J.RightKnee]       =  1.3
    p[J.RightAnklePitch] = -0.5
    return p


def kick_right_pose() -> np.ndarray:
    p = zero_pose()
    p[J.RightHipPitch]   = -1.4
    p[J.RightKnee]       =  0.4
    p[J.RightAnklePitch] = -0.3
    return p


# ---------------------------------------------------------------------------
# Each action = an ordered list of (duration_seconds, target_pose) keyframes.
# The control thread blends from whatever it's currently commanding to the
# first target over `duration`, then to the second, etc. Holds are just the
# same pose repeated with a duration; that's how we get "stay there 1 s".
# ---------------------------------------------------------------------------
@dataclass
class Action:
    key: str
    name: str
    keyframes: list  # list[(float, np.ndarray)]


def hold(pose, t):
    """Convenience: hold a pose for `t` seconds (fed as an extra keyframe)."""
    return (t, pose.copy())


def build_actions():
    z = zero_pose()
    return [
        Action("z", "ramp to zero pose",
               [(2.0, z)]),

        Action("w", "wave right arm",
               [(1.2, wave_right_pose()), hold(wave_right_pose(), 0.6),
                (1.2, z)]),

        Action("e", "wave left arm",
               [(1.2, wave_left_pose()), hold(wave_left_pose(), 0.6),
                (1.2, z)]),

        Action("u", "hands up (cheer)",
               [(1.2, hands_up_pose()), hold(hands_up_pose(), 0.8),
                (1.2, z)]),

        Action("t", "T-pose",
               [(1.5, t_pose()), hold(t_pose(), 1.0),
                (1.5, z)]),

        Action("s", "salute",
               [(1.0, salute_pose()), hold(salute_pose(), 1.2),
                (1.0, z)]),

        Action("a", "clap (twice)",
               [(1.0, clap_pose()), (0.4, z),
                (0.4, clap_pose()), (1.0, z)]),

        Action("h", "hug",
               [(1.4, hug_pose()), hold(hug_pose(), 1.0),
                (1.4, z)]),

        Action("g", "boxer guard",
               [(1.0, boxer_guard_pose()), hold(boxer_guard_pose(), 0.6),
                (1.0, z)]),

        Action("p", "punch right (jab)",
               [(0.6, boxer_guard_pose()), (0.25, punch_right_pose()),
                (0.25, boxer_guard_pose()), (0.25, punch_left_pose()),
                (0.25, boxer_guard_pose()), (1.0, z)]),

        Action("b", "bow (waist pitch)",
               [(1.5, bow_pose()), hold(bow_pose(), 1.0),
                (1.5, z)]),

        Action("[", "lean left",
               [(1.0, lean_left_pose()), hold(lean_left_pose(), 0.8),
                (1.0, z)]),

        Action("]", "lean right",
               [(1.0, lean_right_pose()), hold(lean_right_pose(), 0.8),
                (1.0, z)]),

        Action(",", "twist left",
               [(1.0, twist_left_pose()), hold(twist_left_pose(), 0.5),
                (1.0, z)]),

        Action(".", "twist right",
               [(1.0, twist_right_pose()), hold(twist_right_pose(), 0.5),
                (1.0, z)]),

        Action("k", "lift left knee",
               [(1.5, lift_left_knee_pose()),
                hold(lift_left_knee_pose(), 1.0), (1.5, z)]),

        Action("l", "lift right knee",
               [(1.5, lift_right_knee_pose()),
                hold(lift_right_knee_pose(), 1.0), (1.5, z)]),

        Action("c", "squat (hold 1.5 s)",
               [(2.0, squat_pose()), hold(squat_pose(), 1.5),
                (2.0, z)]),

        Action("v", "right kick (hold)",
               [(1.4, kick_right_pose()), hold(kick_right_pose(), 0.8),
                (1.4, z)]),
    ]


# Special keys (handled outside the actions table):
#   r/i = restore the initial measured pose captured at startup
#   x   = soft-disable: ramp Kp/Kd toward 0 (useful before pressing 9 in viewer)
#   ?   = print key help
#   q   = quit (settles to zero first)
#   + / -  = increase / decrease the global "duration scale" (slow-mo / fast-mo)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------
class G1Controller:
    CONTROL_DT = 0.002    # 500 Hz

    def __init__(self):
        self.low_cmd = unitree_hg_msg_dds__LowCmd_()
        self.low_state: LowState_ = None
        self.first_state_received = False
        self.mode_machine = 0
        self.crc = CRC()

        self.q_cmd = None              # currently-commanded pose (29,)
        self.init_pose = None          # captured from very first lowstate
        self._active = None            # [q_from, q_to, dur, t]
        self._queue: "queue.Queue[tuple[float, np.ndarray]]" = queue.Queue()

        self.kp = KP_DEFAULT.copy()
        self.kd = KD_DEFAULT.copy()
        self.kp_scale = 1.0            # 'x' drives this toward 0

        self.duration_scale = 1.0      # '+' / '-' adjust this (0.5 = 2x slower)

        self._stop = threading.Event()

    # ----- DDS plumbing
    def init_dds(self):
        self.cmd_pub = ChannelPublisher("rt/lowcmd", LowCmd_)
        self.cmd_pub.Init()
        self.state_sub = ChannelSubscriber("rt/lowstate", LowState_)
        self.state_sub.Init(self._on_state, 10)

    def _on_state(self, msg: LowState_):
        self.low_state = msg
        if not self.first_state_received:
            self.mode_machine = msg.mode_machine
            measured = np.array(
                [msg.motor_state[i].q for i in range(G1_NUM_MOTOR)],
                dtype=np.float64,
            )
            self.q_cmd     = measured.copy()
            self.init_pose = measured.copy()
            self.first_state_received = True

    # ----- public API
    def push(self, keyframes):
        """Append keyframes (list of (dur, pose))."""
        for dur, pose in keyframes:
            self._queue.put(
                (float(dur) / max(self.duration_scale, 1e-3),
                 np.asarray(pose, dtype=np.float64)),
            )

    def cancel(self):
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._active = None

    def reset_to_init(self, duration=2.5):
        """Drop everything pending and ramp back to the captured init pose."""
        if self.init_pose is None:
            return
        self.cancel()
        self.push([(duration, self.init_pose),
                   (0.5, self.init_pose)])
        # restore PD to defaults if 'x' had softened them
        self.kp_scale = 1.0

    def soften(self, target_scale=0.0, duration=1.5):
        """Ramp Kp scale toward 0 over `duration` seconds. Useful before
        manually intervening in the viewer (gravity will take over)."""
        steps = int(duration / self.CONTROL_DT)
        self._soften_target = float(target_scale)
        self._soften_step = (self._soften_target - self.kp_scale) / max(steps, 1)
        self._soften_steps_left = steps

    def start(self):
        print("[g1] waiting for first /rt/lowstate ...")
        while not self.first_state_received:
            time.sleep(0.05)
        print(f"[g1] got lowstate (mode_machine={self.mode_machine}). "
              f"Ramping to zero pose.")
        self.push([(3.0, zero_pose())])
        self._soften_steps_left = 0
        self._soften_step = 0.0
        self._soften_target = 1.0
        self._thread = RecurrentThread(
            interval=self.CONTROL_DT, target=self._tick, name="g1_control"
        )
        self._thread.Start()

    def stop_and_settle(self):
        self.cancel()
        self.push([(2.5, zero_pose())])
        while self._active is not None or not self._queue.empty():
            time.sleep(0.05)
        self._stop.set()

    # ----- 500 Hz tick
    def _tick(self):
        if not self.first_state_received or self._stop.is_set():
            return

        # Soften ramp (kp_scale).
        if self._soften_steps_left > 0:
            self.kp_scale += self._soften_step
            self._soften_steps_left -= 1
            if self._soften_steps_left == 0:
                self.kp_scale = self._soften_target

        # Pull next keyframe if idle.
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
                s = 0.5 - 0.5 * np.cos(np.pi * (t / dur))
                self.q_cmd = (1.0 - s) * q_from + s * q_to
                self._active[3] = t

        self._publish(self.q_cmd)

    def _publish(self, q_des: np.ndarray):
        self.low_cmd.mode_pr = Mode.PR
        self.low_cmd.mode_machine = self.mode_machine
        for i in range(G1_NUM_MOTOR):
            m = self.low_cmd.motor_cmd[i]
            m.mode = 1
            m.q    = float(q_des[i])
            m.dq   = 0.0
            m.tau  = 0.0
            m.kp   = float(self.kp[i] * self.kp_scale)
            m.kd   = float(self.kd[i] * self.kp_scale)
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
def format_help(actions):
    lines = ["", "==== G1 keyboard playground ===="]
    lines.append("(Focus this terminal; viewer keys 7/8/9 still control band.)")
    lines.append("")
    for a in actions:
        lines.append(f"  {a.key}  {a.name}")
    lines.append("")
    lines.append("  r / i   reset to initial pose captured at startup")
    lines.append("  x       soften PD (ramp Kp,Kd -> 0 over 1.5 s)")
    lines.append("  +       slow-mo all actions (0.7x duration scale)")
    lines.append("  -       fast-mo all actions (1.4x duration scale)")
    lines.append("  =       reset duration scale to 1.0x")
    lines.append("  ?       print this help")
    lines.append("  q       quit (settles to zero pose first)")
    lines.append("===============================")
    return "\n".join(lines)


def main():
    if len(sys.argv) > 1 and sys.argv[1] not in ("lo", "sim"):
        ChannelFactoryInitialize(0, sys.argv[1])
        print(f"[g1] real-robot mode on {sys.argv[1]} (domain 0).")
        print("[g1] WARNING: keep the e-stop within reach.")
    else:
        ChannelFactoryInitialize(1, "lo")
        print("[g1] simulator mode on lo (domain 1).")

    actions = build_actions()
    actions_by_key = {a.key: a for a in actions}

    ctl = G1Controller()
    ctl.init_dds()
    ctl.start()

    print(format_help(actions))

    with RawKeyReader() as kb:
        while True:
            ch = kb.get(0.1)
            if ch is None:
                continue
            if ch == "q":
                print("\n[g1] settling to zero, then exiting ...")
                ctl.stop_and_settle()
                break
            if ch == "?":
                print(format_help(actions))
                continue
            if ch in ("r", "i"):
                print("[g1] reset to init pose")
                ctl.reset_to_init()
                continue
            if ch == "x":
                print("[g1] softening PD (Kp -> 0)")
                ctl.soften(0.0, duration=1.5)
                continue
            if ch == "+":
                ctl.duration_scale = max(0.4, ctl.duration_scale * 0.7)
                print(f"[g1] duration_scale = {ctl.duration_scale:.2f}  (slower)")
                continue
            if ch == "-":
                ctl.duration_scale = min(2.5, ctl.duration_scale * 1.4)
                print(f"[g1] duration_scale = {ctl.duration_scale:.2f}  (faster)")
                continue
            if ch == "=":
                ctl.duration_scale = 1.0
                print("[g1] duration_scale reset to 1.0")
                continue
            if ch == "\x03":  # Ctrl-C
                print("\n[g1] caught Ctrl-C, settling to zero, exiting ...")
                ctl.stop_and_settle()
                break
            act = actions_by_key.get(ch)
            if act is None:
                continue
            print(f"[g1] play '{ch}' = {act.name}  ({len(act.keyframes)} keyframes)")
            ctl.push(act.keyframes)

    print("[g1] done.")


if __name__ == "__main__":
    main()
