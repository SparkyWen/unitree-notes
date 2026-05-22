"""Tests for g1_brain.brain.conversation_logger.ConversationLogger.

Covers:
- Claude-shape rendering of user/assistant/tool_use/tool_result/system events
- session_id / turn_id / parent_uuid chaining
- text trimming for oversized payloads
- keep_last_n rotation
- close() emits a final shutdown meta line
- best-effort behaviour when the file cannot be opened
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

# va-demo isn't needed here — ConversationLogger has no va-demo deps —
# but we still need g1_brain on sys.path. conftest.py handles that.
from g1_brain.brain.conversation_logger import (
    ConversationLogger,
    _trim_text,
)


def _read_lines(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_basic_session_emits_shutdown(tmp_path):
    lg = ConversationLogger(tmp_path, keep_last_n=10, max_text_kb=4)
    lg.log_session_start(argv=["agent_main"], config_path="cfg.yaml")
    lg.close()
    lines = _read_lines(lg.path)
    types = [(rec.get("type"), rec.get("subtype")) for rec in lines]
    assert ("meta", "session_start") in types
    assert ("meta", "shutdown") in types


def test_user_assistant_tool_use_tool_result_shapes(tmp_path):
    lg = ConversationLogger(tmp_path, keep_last_n=10, max_text_kb=4)
    lg.log_session_start(argv=["agent_main"], config_path="cfg.yaml")
    lg.begin_turn()
    lg.log_user_transcript("走五米")
    lg.log_assistant_transcript("好的")
    lg.log_tool_use("call_1", "walk", {"vx": 0.2, "duration_s": 1.0})
    lg.log_tool_result("call_1", "walk", {"ok": True, "executed": "walk"})
    lg.log_plan_done()
    lg.close()

    recs = _read_lines(lg.path)
    types = [r.get("type") for r in recs]
    # session_start, turn_start, user, assistant, tool_use, tool_result,
    # plan_done, shutdown
    assert types.count("user") == 1
    assert types.count("assistant") == 1
    assert types.count("tool_use") == 1
    assert types.count("tool_result") == 1

    user = next(r for r in recs if r.get("type") == "user")
    assert user["message"]["role"] == "user"
    assert user["message"]["content"][0] == {"type": "text", "text": "走五米"}

    assistant = next(r for r in recs if r.get("type") == "assistant")
    assert assistant["message"]["role"] == "assistant"
    assert assistant["message"]["content"][0]["text"] == "好的"

    tool_use = next(r for r in recs if r.get("type") == "tool_use")
    block = tool_use["message"]["content"][0]
    assert block["type"] == "tool_use"
    assert block["id"] == "call_1"
    assert block["name"] == "walk"
    assert block["input"] == {"vx": 0.2, "duration_s": 1.0}

    tool_result = next(r for r in recs if r.get("type") == "tool_result")
    block = tool_result["message"]["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "call_1"
    # The content sub-block is text containing the JSON-serialised result.
    inner = block["content"][0]
    assert inner["type"] == "text"
    assert json.loads(inner["text"]) == {"ok": True, "executed": "walk"}


def test_session_id_is_stable_across_records(tmp_path):
    lg = ConversationLogger(tmp_path, keep_last_n=10)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_user_transcript("hi")
    lg.close()
    recs = _read_lines(lg.path)
    sids = {r["session_id"] for r in recs}
    assert len(sids) == 1
    assert sids.pop() == lg.session_id


def test_turn_id_increments_per_begin_turn(tmp_path):
    lg = ConversationLogger(tmp_path, keep_last_n=10)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_user_transcript("hi 1")
    lg.begin_turn()
    lg.log_user_transcript("hi 2")
    lg.close()
    recs = _read_lines(lg.path)
    user_recs = [r for r in recs if r.get("type") == "user"]
    assert [r["turn_id"] for r in user_recs] == ["t-0001", "t-0002"]


def test_parent_uuid_chains_within_turn(tmp_path):
    """Chain holds inside a turn; turn_start / session_start reset to None.

    Intent: a future graph view can reconstruct order within a turn without
    relying on file order. Cross-turn boundaries deliberately break the
    chain so a turn is a self-contained unit.
    """
    lg = ConversationLogger(tmp_path, keep_last_n=10)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_user_transcript("a")
    lg.log_assistant_transcript("b")
    lg.close()
    recs = _read_lines(lg.path)
    # session_start: no parent.
    assert recs[0]["parent_uuid"] is None
    # turn_start: turn boundary resets chain.
    turn_start = next(r for r in recs if r.get("subtype") == "turn_start")
    assert turn_start["parent_uuid"] is None
    # Within the turn, user -> assistant chain.
    user = next(r for r in recs if r.get("type") == "user")
    assistant = next(r for r in recs if r.get("type") == "assistant")
    assert user["parent_uuid"] == turn_start["uuid"]
    assert assistant["parent_uuid"] == user["uuid"]


def test_text_trimming_oversized_payload(tmp_path):
    # max 1 KB → 1024 bytes; ascii so 1 char = 1 byte.
    big = "x" * 5000
    lg = ConversationLogger(tmp_path, keep_last_n=10, max_text_kb=1)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_user_transcript(big)
    lg.close()
    user = next(r for r in _read_lines(lg.path) if r.get("type") == "user")
    text = user["message"]["content"][0]["text"]
    assert len(text.encode("utf-8")) <= 1024 + len("…[trimmed]".encode("utf-8")) + 8
    assert text.endswith("[trimmed]")


def test_keep_last_n_rotation(tmp_path):
    # Pre-create five fake jsonl files with stagger mtimes.
    files = []
    for i in range(5):
        p = tmp_path / f"old-{i:02d}.jsonl"
        p.write_text("{}\n")
        # stagger mtime explicitly so sort order is deterministic
        os.utime(p, (1_000_000 + i, 1_000_000 + i))
        files.append(p)

    # Now construct logger with keep_last_n=2 — rotation should delete the
    # 3 oldest pre-existing files. The new logger's own file is created
    # AFTER rotation, so it survives unconditionally.
    lg = ConversationLogger(tmp_path, keep_last_n=2)
    lg.close()

    # Files 0,1,2 should be gone; 3,4 retained; new file present.
    survivors = sorted(p.name for p in tmp_path.glob("*.jsonl"))
    assert "old-00.jsonl" not in survivors
    assert "old-01.jsonl" not in survivors
    assert "old-02.jsonl" not in survivors
    assert "old-03.jsonl" in survivors
    assert "old-04.jsonl" in survivors
    assert lg.path.name in survivors


def test_disabled_logger_writes_no_files(tmp_path):
    lg = ConversationLogger(tmp_path, enabled=False)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_user_transcript("hello")
    lg.close()
    assert list(tmp_path.glob("*.jsonl")) == []


def test_open_failure_does_not_raise(monkeypatch, tmp_path):
    # Force open() to fail by pointing at a path under a non-existent dir
    # and pre-creating the dir as a *file* so mkdir can't create it.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    target_dir = blocker / "subdir"
    lg = ConversationLogger(target_dir, keep_last_n=10)
    # Logger should have disabled itself; subsequent calls must not raise.
    assert lg.enabled is False
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_user_transcript("hello")
    lg.close()


def test_meta_helpers(tmp_path):
    lg = ConversationLogger(tmp_path)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_wake_event("hi sparky")
    lg.log_barge_in(from_state="SPEAKING", wake_text="hi sparky")
    lg.log_state_transition(from_state="IDLE", to_state="CAPTURING", reason="wake")
    lg.log_plan_done()
    lg.log_no_speech_idle(timeout_s=4.0)
    lg.log_response_canceled(reason="barge_in")
    lg.log_plan_watchdog_timeout(pending=["call_xy"])
    lg.log_error(where="test", msg="boom")
    lg.close()
    subtypes = [
        r.get("subtype") for r in _read_lines(lg.path)
        if r.get("type") == "meta"
    ]
    expected = {
        "session_start", "turn_start", "wake_event", "barge_in",
        "state_transition", "plan_done", "no_speech_idle", "response_canceled",
        "plan_watchdog_timeout", "error", "shutdown",
    }
    assert expected.issubset(set(subtypes))


class _FakeUser:
    def __init__(self, pose=None, gesture=None):
        self.pose = pose
        self.gesture = gesture


class _FakeDetection:
    def __init__(self, class_name):
        self.class_name = class_name


class _FakeSceneState:
    """Minimal duck-typed scene state for log_scene_snapshot tests."""

    def __init__(
        self, persons_visible=1, user=None,
        nearest_person_m=1.3, nearest_obstacle_m=0.8,
        ground_constraint="flat", warnings=None, detections=None,
    ):
        self.persons_visible = persons_visible
        self.user = user
        self.nearest_person_m = nearest_person_m
        self.nearest_obstacle_m = nearest_obstacle_m
        self.ground_constraint = ground_constraint
        self.warnings = warnings or []
        self.detections = detections or {}


def test_log_scene_snapshot_full(tmp_path):
    lg = ConversationLogger(tmp_path)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    scene = _FakeSceneState(
        persons_visible=2,
        user=_FakeUser(pose="standing", gesture="wave"),
        nearest_person_m=1.5,
        nearest_obstacle_m=0.6,
        ground_constraint="flat",
        warnings=["close_obstacle"],
        detections={
            "head_cam": [_FakeDetection("person"),
                         _FakeDetection("person"),
                         _FakeDetection("chair")],
        },
    )
    lg.log_scene_snapshot(trigger="turn_start", scene_state=scene)
    lg.close()
    recs = _read_lines(lg.path)
    snaps = [r for r in recs if r.get("subtype") == "scene_snapshot"]
    assert len(snaps) == 1
    d = snaps[0]["data"]
    assert d["trigger"] == "turn_start"
    assert d["persons_visible"] == 2
    assert d["user_pose"] == "standing"
    assert d["user_gesture"] == "wave"
    assert d["nearest_obstacle_m"] == 0.6
    assert d["ground_constraint"] == "flat"
    assert "close_obstacle" in d["warnings"]
    assert d["detections_summary"]["head_cam"]["person"] == 2
    assert d["detections_summary"]["head_cam"]["chair"] == 1
    assert d["frame_ref"] is None


def test_log_scene_snapshot_missing_fields(tmp_path):
    """If scene_state lacks fields, snapshot is still emitted with Nones."""
    lg = ConversationLogger(tmp_path)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_scene_snapshot(trigger="pre_motion", scene_state=None)
    lg.close()
    snaps = [r for r in _read_lines(lg.path)
             if r.get("subtype") == "scene_snapshot"]
    assert len(snaps) == 1
    d = snaps[0]["data"]
    assert d["trigger"] == "pre_motion"
    assert d["persons_visible"] is None


def test_log_action_result(tmp_path):
    lg = ConversationLogger(tmp_path)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_action_result(
        tool_use_id="call_abc",
        tool_name="walk",
        args={"vx": 0.3, "duration": 2.0},
        status="ok",
        outcome_metrics={"displacement_m": 0.58,
                         "end_safety_state": "STANDING"},
        result_payload_brief='{"walked": 0.58}',
    )
    lg.close()
    recs = _read_lines(lg.path)
    ars = [r for r in recs if r.get("subtype") == "action_result"]
    assert len(ars) == 1
    d = ars[0]["data"]
    assert d["tool_use_id"] == "call_abc"
    assert d["tool_name"] == "walk"
    assert d["status"] == "ok"
    assert d["outcome_metrics"]["displacement_m"] == 0.58
    assert d["blocked_reason"] is None


def test_log_action_result_blocked(tmp_path):
    lg = ConversationLogger(tmp_path)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_action_result(
        tool_use_id="call_x",
        tool_name="turn",
        args={"yaw_deg": 90},
        status="blocked_by_safety",
        blocked_reason="scene_check_turn:person_close",
    )
    lg.close()
    ars = [r for r in _read_lines(lg.path) if r.get("subtype") == "action_result"]
    assert ars[0]["data"]["status"] == "blocked_by_safety"
    assert "person_close" in ars[0]["data"]["blocked_reason"]


def test_log_action_result_brief_trimmed(tmp_path):
    lg = ConversationLogger(tmp_path)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    long_payload = "x" * 1000
    lg.log_action_result(
        tool_use_id="c", tool_name="t", args={}, status="ok",
        result_payload_brief=long_payload,
    )
    lg.close()
    ar = [r for r in _read_lines(lg.path)
          if r.get("subtype") == "action_result"][0]
    assert len(ar["data"]["result_payload_brief"]) <= 256


def test_log_safety_event_all_kinds(tmp_path):
    lg = ConversationLogger(tmp_path)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_safety_event(kind="tool_rejected", rule="scene_check_walk",
                        details="obstacle 0.2m",
                        associated_tool_use_id="c1")
    lg.log_safety_event(kind="fsm_transition", from_state="STANDING",
                        to_state="ACTING")
    lg.log_safety_event(kind="vision_gate_risk", details="cardboard box")
    lg.log_safety_event(kind="estop", details="user pressed button")
    lg.close()
    evts = [r for r in _read_lines(lg.path)
            if r.get("subtype") == "safety_event"]
    kinds = [e["data"]["kind"] for e in evts]
    assert kinds == ["tool_rejected", "fsm_transition",
                     "vision_gate_risk", "estop"]
    assert evts[0]["data"]["associated_tool_use_id"] == "c1"
    assert evts[1]["data"]["from_state"] == "STANDING"


def test_log_safety_event_details_trimmed(tmp_path):
    lg = ConversationLogger(tmp_path)
    lg.log_session_start(argv=[], config_path="")
    lg.begin_turn()
    lg.log_safety_event(kind="estop", details="x" * 2000)
    lg.close()
    evt = [r for r in _read_lines(lg.path)
           if r.get("subtype") == "safety_event"][0]
    assert len(evt["data"]["details"]) <= 512


def test_trim_text_preserves_short_strings():
    assert _trim_text("hello", 4096) == "hello"


def test_trim_text_handles_utf8_boundaries():
    # "中" is 3 bytes in UTF-8 (U+4E2D → E4 B8 AD). At 400 chars that's
    # 1200 bytes, comfortably above the 1024-byte cap. The trimmer should
    # back off to a valid utf-8 boundary; 1023 / 3 = 341, so we keep 341
    # chars and the partial 2 bytes of char 342 are dropped.
    s = "中" * 400
    out = _trim_text(s, 1024)
    assert out.endswith("[trimmed]")
    # Verify the kept prefix is exactly 341 valid CJK chars.
    kept = out[: -len("…[trimmed]")]
    assert kept == "中" * 341
