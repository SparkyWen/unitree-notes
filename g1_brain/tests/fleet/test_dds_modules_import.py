"""Import + pure-logic coverage for the DDS path modules.

The live DDS path is verified out-of-process by
g1_brain.fleet.sim.verify_dds_fleet (needs running sims); here we only guard
against import/syntax breakage and check the mujoco-free helpers.
"""


def test_g1_consts_shapes_and_gravity_helper():
    from g1_brain.fleet.sim import g1_consts as C
    assert len(C.G1_DEFAULT_JOINT_POS) == 29
    assert len(C.G1_DEFAULT_KP) == 29 and len(C.G1_DEFAULT_KD) == 29
    # upright quaternion -> gravity_proj_z == -1; flipped about x -> +1
    assert abs(C.gravity_proj_z_from_quat([1, 0, 0, 0]) + 1.0) < 1e-9
    assert abs(C.gravity_proj_z_from_quat([0, 1, 0, 0]) - 1.0) < 1e-9


def test_dds_backend_importable():
    import g1_brain.fleet.agent.motion.dds_backend as m
    assert hasattr(m, "DdsMujocoBackend")  # DDS init deferred to __init__


def test_sim_entrypoints_importable():
    import g1_brain.fleet.sim.robot_node as rn
    import g1_brain.fleet.sim.headless_sim as hs
    import g1_brain.fleet.sim.verify_dds_fleet as vf
    assert hasattr(rn, "main") and hasattr(hs, "main") and hasattr(vf, "run")
