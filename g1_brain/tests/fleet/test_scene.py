from g1_brain.fleet.sim.scene import get_scene, resolve_landmark, Scene, Geom


def test_bare_scene_is_empty():
    s = get_scene("bare")
    assert isinstance(s, Scene) and s.geoms == [] and s.landmarks == {}


def test_demo_scene_has_props_and_landmarks():
    s = get_scene("demo")
    assert 8 <= len(s.geoms) <= 15            # props + terrain, within budget
    for name in ("集合点", "左上角", "右上角", "左下角", "右下角",
                 "红色柱子", "蓝色箱子", "地形测试区"):
        assert name in s.landmarks
    assert any(g.avoid_r > 0 for g in s.geoms)
    assert any(g.avoid_r == 0 for g in s.geoms)


def test_solo_scene_reuses_demo_geometry():
    assert get_scene("solo").landmarks == get_scene("demo").landmarks


def test_resolve_landmark_direct_and_alias():
    lm = get_scene("demo").landmarks
    assert resolve_landmark(lm, "去红色柱子那里") == lm["红色柱子"]
    assert resolve_landmark(lm, "all go to center") == lm["集合点"]
    assert resolve_landmark(lm, "走到 top left") == lm["左上角"]
    assert resolve_landmark(lm, "随便走走") is None


def test_unknown_scene_raises():
    import pytest
    with pytest.raises(KeyError):
        get_scene("nope")
