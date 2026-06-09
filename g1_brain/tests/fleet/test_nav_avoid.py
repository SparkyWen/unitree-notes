from g1_brain.fleet.sim.nav import nav_command, RANGES


def test_no_obstacle_matches_plain_goal():
    a = nav_command((0.0, 0.0, 0.0), (4.0, 0.0))
    b = nav_command((0.0, 0.0, 0.0), (4.0, 0.0), obstacles=())
    assert a == b


def test_obstacle_induces_lateral_or_turn():
    base = nav_command((1.0, 0.0, 0.0), (4.0, 0.0))
    avo = nav_command((1.0, 0.0, 0.0), (4.0, 0.0), obstacles=[(2.0, 0.0, 0.4)])
    assert abs(avo[1]) > abs(base[1]) + 1e-3 or abs(avo[2]) > abs(base[2]) + 1e-3


def test_peer_pushes_away():
    avo = nav_command((0.0, 0.0, 0.0), (4.0, 0.0), peer=(0.6, 0.4))
    assert abs(avo[1]) > 1e-3 or abs(avo[2]) > 1e-3


def test_still_clamped_to_ranges_with_obstacles():
    vx, vy, wz = nav_command((1.0, 0.0, 0.0), (100.0, 0.0),
                             obstacles=[(2.0, 0.1, 0.4)])
    assert RANGES["vx"][0] <= vx <= RANGES["vx"][1]
    assert RANGES["vy"][0] <= vy <= RANGES["vy"][1]
    assert RANGES["wz"][0] <= wz <= RANGES["wz"][1]
