"""Unit tests for safety supervisor: whitelist, bounds, modes, watchdog."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from va_demo.safety import SafetyConfig, SafetySupervisor, WatchdogState


def _wd(frame_age=0.0, lowstate_age=0.0, max_frame=2.0, max_lowstate=0.5):
    return WatchdogState(
        last_frame_age_provider=lambda: frame_age,
        last_lowstate_age_provider=lambda: lowstate_age,
        max_frame_age_s=max_frame,
        max_lowstate_age_s=max_lowstate,
    )


def _sup(mode="active", **wd_kwargs):
    return SafetySupervisor(SafetyConfig(), _wd(**wd_kwargs), run_mode=mode)


def _run(coro):
    return asyncio.run(coro)


def test_unknown_tool_rejected():
    sup = _sup()
    ok, reason, _ = _run(sup.validate("self_destruct", {}))
    assert not ok
    assert "unknown tool" in reason


def test_say_strips_and_caps():
    sup = _sup()
    ok, _, args = _run(sup.validate("say", {"text": "hi"}))
    assert ok and args["text"] == "hi"

    ok, _, args = _run(sup.validate("say", {"text": "x" * 500}))
    assert ok and len(args["text"]) == sup.cfg.say_max_chars

    ok, reason, _ = _run(sup.validate("say", {"text": "   "}))
    assert not ok and "empty" in reason


def test_walk_bounds_clipped():
    sup = _sup()
    ok, _, args = _run(sup.validate("walk", {
        "vx": 5.0, "vy": -5.0, "wz": 10.0, "duration_s": 99.0
    }))
    assert ok
    assert args["vx"] == sup.cfg.vx_max
    assert args["vy"] == -sup.cfg.vy_max
    assert args["wz"] == sup.cfg.wz_max
    assert args["duration_s"] == sup.cfg.duration_max_s


def test_walk_duration_min_clipped():
    sup = _sup()
    ok, _, args = _run(sup.validate("walk", {"duration_s": 0.05}))
    assert ok
    assert args["duration_s"] == sup.cfg.duration_min_s


def test_observe_mode_blocks_motion():
    sup = _sup(mode="observe")
    for tool in ("walk", "gesture", "stop", "release_arms"):
        args = {"name": "wave_right", "duration_s": 0.5} if tool != "stop" else {}
        ok, reason, _ = _run(sup.validate(tool, args))
        assert not ok, tool
        assert "observe_only" in reason, tool


def test_observe_mode_allows_say_and_describe():
    sup = _sup(mode="observe")
    ok, _, _ = _run(sup.validate("say", {"text": "hi"}))
    assert ok
    ok, _, _ = _run(sup.validate("describe_scene", {}))
    assert ok


def test_lowstate_watchdog_blocks_motion():
    sup = _sup(mode="active", lowstate_age=1.0)
    ok, reason, _ = _run(sup.validate("walk", {"duration_s": 0.5}))
    assert not ok and "lowstate" in reason


def test_lowstate_watchdog_does_not_block_say_or_scene():
    sup = _sup(mode="active", lowstate_age=10.0)
    ok, _, _ = _run(sup.validate("say", {"text": "hi"}))
    assert ok
    ok, _, _ = _run(sup.validate("describe_scene", {}))
    assert ok


def test_frame_watchdog_blocks_describe_scene():
    sup = _sup(mode="active", frame_age=10.0)
    ok, reason, _ = _run(sup.validate("describe_scene", {}))
    assert not ok and "no recent frame" in reason


def test_unknown_gesture_rejected():
    sup = _sup()
    ok, reason, _ = _run(sup.validate("gesture", {"name": "moonwalk"}))
    assert not ok and "unknown gesture" in reason


def test_known_gestures_pass():
    sup = _sup()
    for n in ["wave_right", "wave_left", "hands_up", "t_pose",
              "salute", "clap", "guard", "punch_combo"]:
        ok, _, args = _run(sup.validate("gesture", {"name": n}))
        assert ok and args["name"] == n


def test_describe_scene_detail_sanitized():
    sup = _sup()
    ok, _, args = _run(sup.validate("describe_scene", {"detail": "ultra-mega"}))
    assert ok and args["detail"] == "medium"


def test_invalid_run_mode():
    with pytest.raises(ValueError):
        SafetySupervisor(SafetyConfig(), _wd(), run_mode="auto-pilot")


def test_walk_bad_args():
    sup = _sup()
    ok, reason, _ = _run(sup.validate("walk", {"vx": "fast", "duration_s": 0.5}))
    assert not ok and "bad args" in reason
