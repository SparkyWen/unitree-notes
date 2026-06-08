from g1_brain.fleet.sim.shared_world import SharedG1World


def test_bare_world_geometry_unchanged():
    bare = SharedG1World(scene="bare")
    assert bare.m.nq == 72 and bare.m.nu == 58          # same as today
    assert bare.obstacles() == [] and bare.landmarks() == {}


def test_demo_world_adds_static_geoms_no_dofs():
    bare = SharedG1World(scene="bare")
    demo = SharedG1World(scene="demo")
    assert demo.m.nq == bare.m.nq and demo.m.nv == bare.m.nv
    assert demo.m.ngeom > bare.m.ngeom
    assert len(demo.obstacles()) >= 4
    assert all(len(o) == 3 for o in demo.obstacles())
    assert "集合点" in demo.landmarks()


def test_demo_world_render_footprints():
    demo = SharedG1World(scene="demo")
    fp = demo.scene_render()
    assert fp and {"type", "x", "y", "sx", "sy", "rgba", "name"} <= set(fp[0])


def test_solo_spawn_defaults_for_one_robot():
    w = SharedG1World(robot_ids=("g1_a",), scene="demo")
    x, y, _ = w.base_pose("g1_a")
    assert x < -1.0
