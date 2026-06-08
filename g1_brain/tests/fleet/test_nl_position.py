from g1_brain.fleet.coordinator.nl_position import parse_position_command

SNAP = {
    "robots": [
        {"robot_id": "g1_a", "x": -1.5, "y": 0.0, "yaw": 0.0},
        {"robot_id": "g1_b", "x": 1.5, "y": 0.0, "yaw": 3.14159},
    ],
    "landmarks": {"集合点": [0.0, 0.0], "红色柱子": [-2.5, 1.8], "左上角": [-3.5, 2.5]},
}


def test_absolute_coords():
    r = parse_position_command("g1_a 走到 2,1", SNAP)
    assert list(r["ops"]) == ["g1_a"]
    op = r["ops"]["g1_a"][0]
    assert op.op == "navigate" and op.args == {"x": 2.0, "y": 1.0}


def test_named_landmark():
    r = parse_position_command("让 g1_a 去红色柱子", SNAP)
    assert r["ops"]["g1_a"][0].args == {"x": -2.5, "y": 1.8}


def test_relative_forward():
    r = parse_position_command("g1_a 前进 2米", SNAP)
    args = r["ops"]["g1_a"][0].args
    assert abs(args["x"] - 0.5) < 1e-6 and abs(args["y"]) < 1e-6


def test_multi_robot_all():
    r = parse_position_command("两机都去集合点", SNAP)
    assert set(r["ops"]) == {"g1_a", "g1_b"}
    assert r["ops"]["g1_a"][0].args == {"x": 0.0, "y": 0.0}


def test_ambiguous_returns_none():
    assert parse_position_command("走到 2,1", SNAP) is None


def test_choreography_not_hijacked():
    assert parse_position_command("两机顺时针绕圈", SNAP) is None


def test_non_positional_returns_none():
    assert parse_position_command("你好", SNAP) is None
