ROBOT = "g1" # Robot name, "go2", "b2", "b2w", "h1", "go2w", "g1"
# For g1 use scene_23dof_terrain.xml: the 23-DOF control space omits 6 motors
# (waist roll/pitch, left/right wrist pitch/yaw) that are not part of the
# trained policy's action space. The scene file still loads a 29-motor MuJoCo
# model (all motors defined in XML), but control code only actuates 23 of them.
#
# The 23-DOF model reduces complexity: gestures (trained with arm disturbances)
# don't need wrist articulation, and the policy doesn't train to actuate those
# joints. This keeps the policy obs/act dims manageable.
USE_TERRAIN = True
if ROBOT == "g1":
    if USE_TERRAIN:
        ROBOT_SCENE = "../unitree_robots/g1/scene_23dof_terrain.xml"
    else:
        ROBOT_SCENE = "../unitree_robots/g1/scene_23dof.xml"
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
# Cadence at which the Python side calls `viewer.sync()` to copy MjData into
# the rendered scene. This only paces how often the *robot animation* updates
# in the viewer -- it does NOT control window redraw or mouse-rotation
# responsiveness, both of which live entirely in MuJoCo's C++ render_loop
# thread (paced by display vsync). 0.02 = 50 Hz scene-data update, which
# matches the original native-Linux behaviour. An earlier round briefly set
# this to 0.033 hoping it would smooth viewer-window stutter; it doesn't,
# because the stutter root cause is per-frame render cost in the C++ loop
# (shadows + reflections + MSAA on a heavy scene), not sync cadence.
VIEWER_DT = 0.02

# Viewer-window visual quality. WSL2's Mesa->D3D12 translation layer charges
# a per-call overhead, so multi-pass effects (shadow map, reflection probe,
# MSAA) blow per-frame cost past the 16.6 ms vsync budget and trigger 60->30
# frame drops that read as "laggy when rotating with the mouse". With these
# defaults the viewer renders at a steady 60 fps even on scene_29dof_terrain.
# Set False if you want full visual fidelity (e.g. for screenshots) and can
# tolerate the stutter -- shadows and reflections are also toggleable live
# from the viewer's "Rendering" panel (or keys S / R if rebound).
LOW_QUALITY_VIEWER = True

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
# 23-DOF control space (22 actual joints: left leg, right leg, waist-yaw, arms).
# Maps to 29-DOF motor indices: [0,1,2,3,4,5, 6,7,8,9,10,11, 12, 15,16,17,18,19, 22,23,24,25,26]
# Unused motors (13,14,20,21,27,28) get zero gain by default.
_G1_CTRL_JOINTS_23DOF = [
    -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,   # left leg: hip, hip, hip, knee, ankle, ankle
    -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,   # right leg: hip, hip, hip, knee, ankle, ankle
    0.0,                                # waist yaw
    0.35, 0.18, 0.0, 0.87, 0.0,       # left arm
    0.35, -0.18, 0.0, 0.87, 0.0,      # right arm
]
_G1_KP_JOINTS_23DOF = [
    40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
    40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
    40.2,
    14.3, 14.3, 14.3, 14.3, 14.3,
    14.3, 14.3, 14.3, 14.3, 14.3,
]
_G1_KD_JOINTS_23DOF = [
    2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
    2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
    2.6,
    0.9, 0.9, 0.9, 0.9, 0.9,
    0.9, 0.9, 0.9, 0.9, 0.9,
]

# Expand to 29-DOF: zeros for disabled motors (13,14,20,21,27,28), values from 23-DOF elsewhere
_G1_CTRL_MAP_23TO29 = [0,1,2,3,4,5, 6,7,8,9,10,11, 12, 15,16,17,18,19, 22,23,24,25,26]
G1_DEFAULT_JOINT_POS = [0.0] * 29
G1_DEFAULT_KP = [0.0] * 29
G1_DEFAULT_KD = [0.0] * 29
for i, j in enumerate(_G1_CTRL_MAP_23TO29):
    G1_DEFAULT_JOINT_POS[j] = _G1_CTRL_JOINTS_23DOF[i]
    G1_DEFAULT_KP[j] = _G1_KP_JOINTS_23DOF[i]
    G1_DEFAULT_KD[j] = _G1_KD_JOINTS_23DOF[i]
