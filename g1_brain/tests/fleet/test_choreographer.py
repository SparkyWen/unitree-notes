"""Choreographer: turn a free-form NL command into per-robot op sequences using
the rich vocabulary (circle/face/arms_up/...). Deterministic keyword path is
tested here (offline); plan_mission routing falls back to the FleetCommander for
plain rendezvous/relay so existing behaviour is unchanged."""
import pytest

from g1_brain.fleet.coordinator.choreographer import (
    VALID_OPS, deterministic_choreography, parse_ops, plan_mission)

SNAP = {"robots": [{"robot_id": "g1_a", "x": -1.5, "y": 0.0},
                   {"robot_id": "g1_b", "x": 1.5, "y": 0.0}]}
NL = "让两个机器人，一个顺时针走，一个逆时针走，30秒后站成一个横排，彼此面对面站立，然后抬起双手"


def test_deterministic_builds_circle_row_face_arms():
    out = deterministic_choreography(NL, SNAP)
    assert out is not None
    ops = out["ops"]
    assert [o.op for o in ops["g1_a"]] == ["circle", "navigate", "face", "arms_up"]
    assert [o.op for o in ops["g1_b"]] == ["circle", "navigate", "face", "arms_up"]
    # the two robots circle in OPPOSITE directions
    assert {ops["g1_a"][0].args["dir"], ops["g1_b"][0].args["dir"]} == {"cw", "ccw"}
    # "30秒" parsed into the circle duration
    assert ops["g1_a"][0].args["seconds"] == 30
    # they face each other: g1_a's face target is g1_b's row spot and vice-versa
    fa = ops["g1_a"][2].args
    fb = ops["g1_b"][2].args
    ga = ops["g1_a"][1].args   # g1_a row goal
    gb = ops["g1_b"][1].args
    assert (fa["x"], fa["y"]) == (gb["x"], gb["y"])
    assert (fb["x"], fb["y"]) == (ga["x"], ga["y"])


def test_deterministic_returns_none_for_plain_command():
    assert deterministic_choreography("两机到中间会合", SNAP) is None


def test_parse_ops_rejects_unknown_op():
    with pytest.raises(ValueError):
        parse_ops({"g1_a": [{"op": "teleport", "args": {}}]}, {"g1_a"})


def test_parse_ops_rejects_unknown_robot():
    with pytest.raises(ValueError):
        parse_ops({"ghost": [{"op": "idle", "args": {}}]}, {"g1_a", "g1_b"})


def test_valid_ops_covers_choreography():
    assert {"circle", "face", "arms_up", "hold"} <= VALID_OPS


def test_plan_mission_choreography_deterministic():
    r = plan_mission(NL, SNAP, llm=None, sub_llm=None)
    assert r["ok"] is True
    assert r["ops"]["g1_a"][0].op == "circle"
    assert r["plan"].coordination.type == "choreography"


def test_plan_mission_relay_falls_back_to_commander():
    r = plan_mission("两机到中间会合，然后 g1_a 把巡逻交给 g1_b",
                     SNAP, llm=None, sub_llm=None)
    assert r["ok"] is True
    assert r["ops"]["g1_a"][-1].op == "idle"      # hander idles
    assert r["ops"]["g1_b"][-1].op == "patrol"    # receiver patrols
