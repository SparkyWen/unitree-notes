"""
G1 low-level demo for the Python MuJoCo simulator.

Adapted from `unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py`
to work against `unitree_mujoco/simulate_python` instead of a real robot:

  - Connects on DDS domain 1, interface "lo" (matches simulate_python/config.py).
  - Skips MotionSwitcherClient, which the sim bridge does not provide.
  - Initializes mode_machine = 0 (sim default; real robot reports its own).

Three-stage motion identical to the upstream example:
  Stage 1 (0 - 3 s)  : interpolate every joint from current pose to zero pose.
  Stage 2 (3 - 6 s)  : sinusoidal ankle swing in PR (pitch/roll) mode.
  Stage 3 (6 s - inf): sinusoidal ankle swing in AB mode + wrist roll wave.
"""

import time
import sys

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


G1_NUM_MOTOR = 29

Kp = [
    60, 60, 60, 100, 40, 40,      # left leg
    60, 60, 60, 100, 40, 40,      # right leg
    60, 40, 40,                   # waist
    40, 40, 40, 40, 40, 40, 40,   # left arm
    40, 40, 40, 40, 40, 40, 40,   # right arm
]

Kd = [
    1, 1, 1, 2, 1, 1,
    1, 1, 1, 2, 1, 1,
    1, 1, 1,
    1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1,
]


class G1JointIndex:
    LeftHipPitch = 0
    LeftHipRoll = 1
    LeftHipYaw = 2
    LeftKnee = 3
    LeftAnklePitch = 4
    LeftAnkleB = 4
    LeftAnkleRoll = 5
    LeftAnkleA = 5
    RightHipPitch = 6
    RightHipRoll = 7
    RightHipYaw = 8
    RightKnee = 9
    RightAnklePitch = 10
    RightAnkleB = 10
    RightAnkleRoll = 11
    RightAnkleA = 11
    WaistYaw = 12
    WaistRoll = 13
    WaistA = 13
    WaistPitch = 14
    WaistB = 14
    LeftShoulderPitch = 15
    LeftShoulderRoll = 16
    LeftShoulderYaw = 17
    LeftElbow = 18
    LeftWristRoll = 19
    LeftWristPitch = 20
    LeftWristYaw = 21
    RightShoulderPitch = 22
    RightShoulderRoll = 23
    RightShoulderYaw = 24
    RightElbow = 25
    RightWristRoll = 26
    RightWristPitch = 27
    RightWristYaw = 28


class Mode:
    PR = 0
    AB = 1


class Custom:
    def __init__(self):
        self.time_ = 0.0
        self.control_dt_ = 0.002
        self.duration_ = 3.0
        self.counter_ = 0
        self.mode_pr_ = Mode.PR
        self.mode_machine_ = 0
        self.low_cmd = unitree_hg_msg_dds__LowCmd_()
        self.low_state = None
        self.first_state_received_ = False
        self.crc = CRC()

    def Init(self):
        self.lowcmd_publisher_ = ChannelPublisher("rt/lowcmd", LowCmd_)
        self.lowcmd_publisher_.Init()

        self.lowstate_subscriber = ChannelSubscriber("rt/lowstate", LowState_)
        self.lowstate_subscriber.Init(self.LowStateHandler, 10)

    def Start(self):
        self.lowCmdWriteThreadPtr = RecurrentThread(
            interval=self.control_dt_, target=self.LowCmdWrite, name="control"
        )
        print("[g1_sim] waiting for first /rt/lowstate from simulator ...")
        while not self.first_state_received_:
            time.sleep(0.1)
        print("[g1_sim] got lowstate, starting control loop.")
        self.lowCmdWriteThreadPtr.Start()

    def LowStateHandler(self, msg: LowState_):
        self.low_state = msg
        if not self.first_state_received_:
            self.mode_machine_ = self.low_state.mode_machine
            self.first_state_received_ = True

        self.counter_ += 1
        if self.counter_ % 500 == 0:
            self.counter_ = 0
            print(f"[g1_sim] imu rpy: {self.low_state.imu_state.rpy}")

    def LowCmdWrite(self):
        self.time_ += self.control_dt_

        if self.time_ < self.duration_:
            # Stage 1: ramp every joint to zero.
            for i in range(G1_NUM_MOTOR):
                ratio = np.clip(self.time_ / self.duration_, 0.0, 1.0)
                self.low_cmd.mode_pr = Mode.PR
                self.low_cmd.mode_machine = self.mode_machine_
                self.low_cmd.motor_cmd[i].mode = 1
                self.low_cmd.motor_cmd[i].tau = 0.0
                self.low_cmd.motor_cmd[i].q = (1.0 - ratio) * self.low_state.motor_state[i].q
                self.low_cmd.motor_cmd[i].dq = 0.0
                self.low_cmd.motor_cmd[i].kp = Kp[i]
                self.low_cmd.motor_cmd[i].kd = Kd[i]

        elif self.time_ < self.duration_ * 2:
            # Stage 2: ankle swing in PR mode.
            max_P = np.pi * 30.0 / 180.0
            max_R = np.pi * 10.0 / 180.0
            t = self.time_ - self.duration_
            L_P_des = max_P * np.sin(2.0 * np.pi * t)
            L_R_des = max_R * np.sin(2.0 * np.pi * t)
            R_P_des = max_P * np.sin(2.0 * np.pi * t)
            R_R_des = -max_R * np.sin(2.0 * np.pi * t)

            self.low_cmd.mode_pr = Mode.PR
            self.low_cmd.mode_machine = self.mode_machine_
            self.low_cmd.motor_cmd[G1JointIndex.LeftAnklePitch].q = L_P_des
            self.low_cmd.motor_cmd[G1JointIndex.LeftAnkleRoll].q = L_R_des
            self.low_cmd.motor_cmd[G1JointIndex.RightAnklePitch].q = R_P_des
            self.low_cmd.motor_cmd[G1JointIndex.RightAnkleRoll].q = R_R_des

        else:
            # Stage 3: ankle swing in AB mode + wrist roll wave.
            max_A = np.pi * 30.0 / 180.0
            max_B = np.pi * 10.0 / 180.0
            t = self.time_ - self.duration_ * 2
            L_A_des = max_A * np.sin(2.0 * np.pi * t)
            L_B_des = max_B * np.sin(2.0 * np.pi * t + np.pi)
            R_A_des = -max_A * np.sin(2.0 * np.pi * t)
            R_B_des = -max_B * np.sin(2.0 * np.pi * t + np.pi)

            self.low_cmd.mode_pr = Mode.AB
            self.low_cmd.mode_machine = self.mode_machine_
            self.low_cmd.motor_cmd[G1JointIndex.LeftAnkleA].q = L_A_des
            self.low_cmd.motor_cmd[G1JointIndex.LeftAnkleB].q = L_B_des
            self.low_cmd.motor_cmd[G1JointIndex.RightAnkleA].q = R_A_des
            self.low_cmd.motor_cmd[G1JointIndex.RightAnkleB].q = R_B_des

            max_WristYaw = np.pi * 30.0 / 180.0
            L_WristYaw_des = max_WristYaw * np.sin(2.0 * np.pi * t)
            R_WristYaw_des = max_WristYaw * np.sin(2.0 * np.pi * t)
            self.low_cmd.motor_cmd[G1JointIndex.LeftWristRoll].q = L_WristYaw_des
            self.low_cmd.motor_cmd[G1JointIndex.RightWristRoll].q = R_WristYaw_des

        self.low_cmd.crc = self.crc.Crc(self.low_cmd)
        self.lowcmd_publisher_.Write(self.low_cmd)


if __name__ == "__main__":
    print(
        "[g1_sim] Make sure simulate_python/unitree_mujoco.py is already running\n"
        "         with ROBOT='g1', DOMAIN_ID=1, INTERFACE='lo'.\n"
        "         In the viewer, press 9 to grab the elastic band so the robot stays upright."
    )

    if len(sys.argv) > 1 and sys.argv[1] not in ("lo", "sim"):
        # Real-robot path: domain 0 + given network interface.
        ChannelFactoryInitialize(0, sys.argv[1])
        print(f"[g1_sim] connecting to real robot on {sys.argv[1]} (domain 0).")
    else:
        ChannelFactoryInitialize(1, "lo")
        print("[g1_sim] connecting to simulator on lo (domain 1).")

    custom = Custom()
    custom.Init()
    custom.Start()

    while True:
        time.sleep(1)
