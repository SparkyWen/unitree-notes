import numpy as np
from g1_brain.fleet.sim.shared_world import SharedG1World


def test_composes_two_g1s():
    w = SharedG1World(robot_ids=("g1_a", "g1_b"))
    assert w.m.nu == 58 and w.m.nq == 72
    assert set(w.slices) == {"g1_a", "g1_b"}


def test_distinct_base_positions():
    w = SharedG1World(robot_ids=("g1_a", "g1_b"),
                      spawn={"g1_a": (-1.5, 0.0), "g1_b": (1.5, 0.0)})
    xa, ya, _ = w.base_pose("g1_a")
    xb, yb, _ = w.base_pose("g1_b")
    assert xa < -1.0 and xb > 1.0


def test_joint_state_shapes():
    w = SharedG1World(robot_ids=("g1_a", "g1_b"))
    q, dq = w.joint_state("g1_a")
    assert q.shape == (29,) and dq.shape == (29,)


def test_spawns_at_default_pose_upright():
    w = SharedG1World()
    # default_q seeded -> matches the trained standing pose; upright at spawn
    q, _ = w.joint_state("g1_a")
    assert np.allclose(q, w.default_q, atol=1e-6)
    assert w.gravity_proj_z("g1_a") < -0.95


def test_neighbor_sense_symmetric():
    w = SharedG1World(robot_ids=("g1_a", "g1_b"),
                      spawn={"g1_a": (-1.5, 0.0), "g1_b": (1.5, 0.0)})
    na = w.neighbors("g1_a")
    assert na and na[0]["peer"] == "g1_b"
    assert abs(na[0]["dist"] - 3.0) < 0.6  # ~3m apart at spawn
