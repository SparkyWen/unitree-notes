ROBOT = "g1" # Robot name, "go2", "b2", "b2w", "h1", "go2w", "g1"
# For g1 use the clean scene_29dof.xml (just floor); scene.xml is an obstacle
# course and the heightfields/random boxes make the simulation unstable when
# the trained walking policy starts.
if ROBOT == "g1":
    ROBOT_SCENE = "../unitree_robots/g1/scene_29dof.xml"
else:
    ROBOT_SCENE = "../unitree_robots/" + ROBOT + "/scene.xml"
DOMAIN_ID = 1 # Domain id
INTERFACE = "lo" # Interface

USE_JOYSTICK = 0 # Simulate Unitree WirelessController using a gamepad
JOYSTICK_TYPE = "xbox" # support "xbox" and "switch" gamepad layout
JOYSTICK_DEVICE = 0 # Joystick number

PRINT_SCENE_INFORMATION = True # Print link, joint and sensors information of robot
ENABLE_ELASTIC_BAND = True # Virtual spring band, used for lifting h1
# Initial length of the elastic band (m). Original behaviour: band attached
# at point=(0,0,3) lifts the torso up to ~z=1.5 at startup so the robot is
# suspended in mid-air *before* any controller is running. This gives the
# operator full manual control over how the robot meets the ground:
#   - press '8' a few times to lengthen the band so the robot descends to
#     the ground at a controlled rate (recommended workflow);
#   - press '9' to disable the band entirely (clean fall test);
#   - press '7' to shorten the band (lift the robot back up).
# Combined with the default-pose holding PD seeded by `UnitreeSdk2Bridge`
# (see DEFAULT_HOLD_*) the robot now sits in the trained default joint
# pose while suspended, NOT collapsed mid-air, so when agent_main attaches
# the policy sees in-distribution joint_pos_rel ≈ 0 and does not "fly".
ELASTIC_BAND_INIT_LENGTH = 0.0

SIMULATE_DT = 0.005  # Need to be larger than the runtime of viewer.sync()
VIEWER_DT = 0.02  # 50 fps for viewer

# ---------------------------------------------------------------------------
# Default-pose holding PD (G1 only).
#
# Until an external controller (e.g. g1_brain.apps.agent_main, or
# g1_sim_rl_walk.py / g1_sim_rl_combo.py) starts publishing rt/lowcmd, the
# bridge seeds its lowcmd cache with these values so the simulator actively
# holds the robot in its trained default joint pose. Without this the
# unactuated robot collapses to the ground at MuJoCo startup — the user
# saw this as "MuJoCo opens with the robot already sitting" — and even
# after the user presses Reset, it collapses again before they can launch
# agent_main, leading to a chain of MuJoCo resets to "get lucky" with the
# starting pose.
#
# The values are copied verbatim from
#   unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml
# so the held pose matches the policy's offset/default exactly. As soon as
# the external controller's lowcmd lands (LowCmdHandler), it overwrites
# this seed and PD is computed from real commands.
# ---------------------------------------------------------------------------
G1_DEFAULT_JOINT_POS = [
    -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
    -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
    0.0, 0.0, 0.0,
    0.35, 0.18, 0.0, 0.87, 0.0, 0.0, 0.0,
    0.35, -0.18, 0.0, 0.87, 0.0, 0.0, 0.0,
]
G1_DEFAULT_KP = [
    40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
    40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
    40.2, 28.5, 28.5,
    14.3, 14.3, 14.3, 14.3, 14.3, 16.8, 16.8,
    14.3, 14.3, 14.3, 14.3, 14.3, 16.8, 16.8,
]
G1_DEFAULT_KD = [
    2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
    2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
    2.6, 1.8, 1.8,
    0.9, 0.9, 0.9, 0.9, 0.9, 1.1, 1.1,
    0.9, 0.9, 0.9, 0.9, 0.9, 1.1, 1.1,
]
