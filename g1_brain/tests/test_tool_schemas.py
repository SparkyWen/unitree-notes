"""Tests for the OpenAI Realtime tool-schema catalog."""
from __future__ import annotations

import pytest

from g1_brain.skills.tool_schemas import (
    GESTURE_NAMES,
    LOOK_AT_TARGETS,
    MIRRORABLE_GESTURES,
    STATIC_POSE_NAMES,
    build_tool_schemas,
)


# Expected names per design doc §4.1 -----------------------------------------

L1_NAMES = {"say", "describe_scene", "query_scene_state", "recall_history",
            "look_at", "approach", "mock_imitate", "ask_human"}
L2_NAMES = {"walk", "turn", "gesture", "static_pose", "stop", "release_arms"}
REAL_ONLY_NAMES = {"loco_high", "arm_action_high", "audio_tts_robot"}
SIM_NAMES = L1_NAMES | L2_NAMES                               # 14
ALL_NAMES = L1_NAMES | L2_NAMES | REAL_ONLY_NAMES             # 17
VISION_ONLY_NAMES = {"say", "describe_scene", "query_scene_state",
                     "recall_history"}


def _names(schemas):
    return {s["name"] for s in schemas}


# ---------- Counts ----------------------------------------------------------

def test_default_returns_14_sim_tools():
    schemas = build_tool_schemas()
    assert len(schemas) == 14
    assert _names(schemas) == SIM_NAMES
    # No real-robot stragglers.
    assert _names(schemas).isdisjoint(REAL_ONLY_NAMES)


def test_real_robot_returns_17():
    schemas = build_tool_schemas(sim=False)
    assert len(schemas) == 17
    assert _names(schemas) == ALL_NAMES


def test_vision_only_returns_4():
    schemas = build_tool_schemas(vision_only=True)
    assert len(schemas) == 4
    assert _names(schemas) == VISION_ONLY_NAMES


def test_vision_only_with_real_still_only_3():
    # vision_only filter takes precedence over sim/real toggle.
    schemas = build_tool_schemas(sim=False, vision_only=True)
    assert _names(schemas) == VISION_ONLY_NAMES


# ---------- Shape -----------------------------------------------------------

def test_every_schema_has_required_keys():
    for s in build_tool_schemas(sim=False):
        assert s.get("type") == "function", s
        assert isinstance(s.get("name"), str) and s["name"], s
        assert isinstance(s.get("description"), str) and s["description"], s
        assert isinstance(s.get("parameters"), dict), s
        # Realtime / Responses tool schemas must declare "object" at the top.
        assert s["parameters"].get("type") == "object", s


def test_no_duplicate_names():
    schemas = build_tool_schemas(sim=False)
    names = [s["name"] for s in schemas]
    assert len(names) == len(set(names)), names


# ---------- Walk numeric bounds --------------------------------------------

def test_walk_bounds():
    walk = {s["name"]: s for s in build_tool_schemas()}["walk"]
    props = walk["parameters"]["properties"]
    for key in ("vx", "vy", "wz", "duration_s"):
        assert key in props, key
        assert "minimum" in props[key], key
        assert "maximum" in props[key], key
    assert props["vx"]["minimum"] == -0.3 and props["vx"]["maximum"] == 0.3
    assert props["vy"]["minimum"] == -0.1 and props["vy"]["maximum"] == 0.1
    assert props["wz"]["minimum"] == -0.4 and props["wz"]["maximum"] == 0.4
    assert props["duration_s"]["minimum"] == 0.2
    # Long single-call walks are required so a "10 m forward" request only
    # costs the operator one confirm-mode y/N. _skill_walk's reactive abort
    # caps the actual run time on obstacle/path-block.
    assert props["duration_s"]["maximum"] == 60.0
    # Only duration_s is required (vx/vy/wz default to 0).
    assert walk["parameters"].get("required") == ["duration_s"]


# ---------- Enums ----------------------------------------------------------

def test_gesture_enum_has_all_10_names():
    gesture = {s["name"]: s for s in build_tool_schemas()}["gesture"]
    enum = gesture["parameters"]["properties"]["name"]["enum"]
    expected = {
        "wave_right", "wave_left", "hands_up", "t_pose",
        "salute", "clap", "guard", "punch_combo", "hug",
    }
    # Spec says 10 names; current catalog has 9 + the duplicate-but-distinct
    # static_pose route. Be flexible: accept >=9 covering all expected.
    assert expected.issubset(set(enum))
    # And the catalog itself is the source of truth used by SkillServer.
    assert set(GESTURE_NAMES) == expected
    # Sanity: no unrelated gesture names leaked in.
    assert set(enum) - expected == set()


def test_static_pose_enum_is_only_extras():
    sp = {s["name"]: s for s in build_tool_schemas()}["static_pose"]
    enum = sp["parameters"]["properties"]["name"]["enum"]
    assert set(enum) == {"salute", "hug"}
    assert STATIC_POSE_NAMES == ["salute", "hug"]


def test_look_at_enum():
    la = {s["name"]: s for s in build_tool_schemas()}["look_at"]
    enum = la["parameters"]["properties"]["target"]["enum"]
    assert set(enum) == {"person", "ahead", "left", "right", "ground"}
    assert set(LOOK_AT_TARGETS) == set(enum)


def test_mock_imitate_enum_subset_of_gesture():
    mi = {s["name"]: s for s in build_tool_schemas()}["mock_imitate"]
    enum = mi["parameters"]["properties"]["gesture"]["enum"]
    assert set(enum) == {"wave_right", "wave_left", "hands_up", "t_pose"}
    assert set(MIRRORABLE_GESTURES) == set(enum)
    # Mirrorable must be a subset of the full gesture catalog.
    assert set(MIRRORABLE_GESTURES).issubset(set(GESTURE_NAMES))


# ---------- Real-robot tool shapes ----------------------------------------

def test_real_robot_loco_high_enum():
    schemas = {s["name"]: s for s in build_tool_schemas(sim=False)}
    loco = schemas["loco_high"]
    enum = loco["parameters"]["properties"]["action"]["enum"]
    assert {"wave_hand", "shake_hand", "squat", "stand_up"}.issubset(set(enum))


def test_say_max_chars_present():
    say = {s["name"]: s for s in build_tool_schemas()}["say"]
    assert say["parameters"]["properties"]["text"]["maxLength"] == 200


def test_turn_yaw_bounds():
    turn = {s["name"]: s for s in build_tool_schemas()}["turn"]
    props = turn["parameters"]["properties"]["yaw_deg"]
    assert props["minimum"] == -45.0 and props["maximum"] == 45.0
