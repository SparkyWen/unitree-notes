import math
from g1_brain.fleet.sim.nav import nav_command, RANGES


def test_toward_goal_straight_ahead():
    # facing +x (yaw=0), goal 2m ahead -> forward vx>0, no lateral/turn
    vx, vy, wz = nav_command(pose=(0.0, 0.0, 0.0), goal=(2.0, 0.0))
    assert vx > 0.1 and abs(vy) < 1e-6 and abs(wz) < 1e-6


def test_stops_within_radius():
    vx, vy, wz = nav_command(pose=(0.0, 0.0, 0.0), goal=(0.05, 0.0), stop_radius=0.2)
    assert (vx, vy, wz) == (0.0, 0.0, 0.0)


def test_turns_toward_goal_behind():
    # goal behind-left -> nonzero yaw rate to turn
    vx, vy, wz = nav_command(pose=(0.0, 0.0, 0.0), goal=(-1.0, 1.0))
    assert abs(wz) > 0.1


def test_clamps_to_ranges():
    vx, vy, wz = nav_command(pose=(0.0, 0.0, 0.0), goal=(100.0, 0.0))
    assert RANGES["vx"][0] <= vx <= RANGES["vx"][1]
    assert RANGES["vy"][0] <= vy <= RANGES["vy"][1]
    assert RANGES["wz"][0] <= wz <= RANGES["wz"][1]
