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
# Initial length of the elastic band (m). Default 0.0 matches the original
# behaviour — band attached at point=(0,0,3) holds the torso near standing
# height. For the RL walking demos (g1_sim_rl_walk.py, g1_sim_rl_combo.py)
# you want the robot fully on the ground: in the viewer press '8' a few
# times to lengthen the band, then '9' to disable it.
ELASTIC_BAND_INIT_LENGTH = 0.0

SIMULATE_DT = 0.005  # Need to be larger than the runtime of viewer.sync()
VIEWER_DT = 0.02  # 50 fps for viewer
