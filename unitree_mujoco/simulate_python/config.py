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
# Initial length of the elastic band (m). The band's anchor sits at
# point=(0,0,3); force is `stiffness*(distance - length)` along the
# anchor->torso line, i.e. *upward* when distance > length. With the
# previous default of 0.0 and stiffness=200 the band yanked the torso
# toward z≈3 with ~390 N (≈ G1 weight), suspending the robot mid-air —
# the RL policy was trained with feet on the ground, so the resulting
# obs is OOD and the robot "flies around" right after agent_main starts.
# Setting length to 2.0 makes the band slack at the standing pose
# (torso at z≈1.05 -> distance≈1.95 < length, force≤0) so the robot
# stands on its own, while still catching falls when distance grows
# past 2.0 m. Press '9' in the viewer to disable the band entirely if
# you want a clean fall test; '8' / '7' nudge length by ±0.1 m.
ELASTIC_BAND_INIT_LENGTH = 2.0

SIMULATE_DT = 0.005  # Need to be larger than the runtime of viewer.sync()
VIEWER_DT = 0.02  # 50 fps for viewer
