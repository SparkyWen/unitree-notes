"""Tests for memory/phase1.py — JSONL projection + JSON parse + worker."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from g1_brain.memory.codex_client import CodexExecError, CodexExecResult
from g1_brain.memory.phase1 import (
    Phase1Worker,
    build_session_projection,
    parse_stage1_json,
)
from g1_brain.memory.schemas import (
    JOB_KIND_PHASE1,
    JOB_STATUS_DONE,
    Stage1Output,
)
from g1_brain.memory.jobs import JobScheduler
from g1_brain.memory.storage import StorageLayer, now_ms


# ---------- parse_stage1_json ----------

def test_parse_clean_json() -> None:
    text = json.dumps({
        "raw_memory": "- a fact",
        "rollout_summary": "summary",
        "rollout_slug": "my-test",
    })
    out = parse_stage1_json(text)
    assert isinstance(out, Stage1Output)
    assert out.raw_memory == "- a fact"
    assert out.rollout_summary == "summary"
    assert out.rollout_slug == "my-test"


def test_parse_json_wrapped_in_fence() -> None:
    text = (
        '```json\n'
        '{"raw_memory":"x","rollout_summary":"y","rollout_slug":"z"}\n'
        '```'
    )
    out = parse_stage1_json(text)
    assert out.raw_memory == "x"
    assert out.rollout_summary == "y"
    assert out.rollout_slug == "z"


def test_parse_json_with_leading_prose() -> None:
    text = (
        'Here is the memory:\n'
        '{"raw_memory":"x","rollout_summary":"y","rollout_slug":"abc"}\n'
        'thanks!'
    )
    out = parse_stage1_json(text)
    assert out.raw_memory == "x"


def test_parse_sanitizes_slug() -> None:
    text = json.dumps({
        "raw_memory": "x", "rollout_summary": "y",
        "rollout_slug": "Walk Test With Obstacle!! 2025",
    })
    out = parse_stage1_json(text)
    assert out.rollout_slug
    assert all(ch.isalnum() or ch in "-_" for ch in out.rollout_slug)
    assert len(out.rollout_slug) <= 40


def test_parse_handles_missing_keys() -> None:
    text = '{"raw_memory":"only this"}'
    out = parse_stage1_json(text)
    assert out.raw_memory == "only this"
    assert out.rollout_summary == ""
    assert out.rollout_slug is None


def test_parse_raises_on_bad_json() -> None:
    with pytest.raises((json.JSONDecodeError, ValueError)):
        parse_stage1_json("not json at all {{ }}")


# ---------- build_session_projection ----------

def _write_jsonl(path: Path, events: list[dict]) -> None:
    with open(path, "w") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")


def test_projection_includes_user_assistant_tool(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    _write_jsonl(p, [
        {"uuid": "1", "session_id": "s1", "turn_id": "t-0001",
         "timestamp": "2026-05-21T10:00:00.000Z", "type": "meta",
         "subtype": "session_start", "data": {}},
        {"uuid": "2", "session_id": "s1", "turn_id": "t-0001",
         "timestamp": "2026-05-21T10:00:05.000Z", "type": "user",
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "走两步"}]}},
        {"uuid": "3", "session_id": "s1", "turn_id": "t-0001",
         "timestamp": "2026-05-21T10:00:06.000Z", "type": "tool_use",
         "message": {"role": "assistant",
                     "content": [{"type": "tool_use", "id": "c1",
                                  "name": "walk", "input": {"vx": 0.3}}]}},
        {"uuid": "4", "session_id": "s1", "turn_id": "t-0001",
         "timestamp": "2026-05-21T10:00:07.000Z", "type": "meta",
         "subtype": "action_result",
         "data": {"tool_name": "walk", "status": "ok",
                  "outcome_metrics": {"displacement_m": 0.58,
                                       "end_safety_state": "STANDING"}}},
        {"uuid": "5", "session_id": "s1", "turn_id": "t-0001",
         "timestamp": "2026-05-21T10:00:08.000Z", "type": "assistant",
         "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "好的"}]}},
        {"uuid": "6", "session_id": "s1", "turn_id": "t-0001",
         "timestamp": "2026-05-21T10:00:09.000Z", "type": "meta",
         "subtype": "plan_done", "data": {"turn_id": "t-0001"}},
    ])
    proj = build_session_projection(p, max_bytes=80_000)
    assert "session_id: s1" in proj
    assert "走两步" in proj
    assert "walk" in proj
    assert "displacement=0.58" in proj
    assert "plan_done" in proj


def test_projection_includes_safety_event(tmp_path: Path) -> None:
    p = tmp_path / "y.jsonl"
    _write_jsonl(p, [
        {"uuid": "1", "session_id": "s", "turn_id": "t-0001",
         "timestamp": "T", "type": "meta", "subtype": "safety_event",
         "data": {"kind": "tool_rejected",
                  "rule": "scene_check_walk",
                  "details": "obstacle 0.2m"}},
    ])
    proj = build_session_projection(p)
    assert "safety_event" in proj
    assert "scene_check_walk" in proj


def test_projection_trims_to_max_bytes(tmp_path: Path) -> None:
    p = tmp_path / "big.jsonl"
    events = []
    for i in range(200):
        events.append({
            "uuid": str(i), "session_id": "s", "turn_id": f"t-{i:04d}",
            "timestamp": "T", "type": "user",
            "message": {"role": "user",
                        "content": [{"type": "text", "text": "x" * 500}]},
        })
    _write_jsonl(p, events)
    proj = build_session_projection(p, max_bytes=20_000)
    # Should be ≤ 20_000 plus a small overhead for header
    assert len(proj.encode("utf-8")) <= 25_000


def test_projection_handles_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    proj = build_session_projection(p)
    assert "# Session metadata" in proj


# ---------- worker integration (mock codex) ----------

class _FakeCodexClient:
    """Drop-in replacement for CodexClient that returns canned text."""

    def __init__(self, response_text: str = "", raise_error: bool = False):
        self.response_text = response_text
        self.raise_error = raise_error
        self.call_count = 0
        self.last_prompt: str = ""

    def is_available(self) -> bool:
        return True

    async def exec_once(self, prompt: str, **kwargs) -> CodexExecResult:
        self.call_count += 1
        self.last_prompt = prompt
        if self.raise_error:
            raise CodexExecError("simulated failure")
        return CodexExecResult(text=self.response_text, stderr_tail="", returncode=0)


@pytest.fixture
def storage(tmp_path: Path):
    s = StorageLayer(tmp_path / "robot")
    s.init()
    yield s
    s.close()


@pytest.fixture
def jobs_and_storage(storage):
    return JobScheduler(storage), storage


@pytest.mark.asyncio
async def test_phase1_run_one_now_persists_output(tmp_path: Path, storage) -> None:
    # Create a session JSONL
    jsonl = tmp_path / "x.jsonl"
    _write_jsonl(jsonl, [
        {"uuid": "1", "session_id": "s1", "turn_id": "t-0001",
         "timestamp": "T", "type": "user",
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "hi"}]}},
    ])
    storage.upsert_session(session_id="s1", rollout_path=jsonl)

    codex = _FakeCodexClient(response_text=json.dumps({
        "raw_memory": "- said hi",
        "rollout_summary": "Greeting.",
        "rollout_slug": "greeting",
    }))
    worker = Phase1Worker(
        storage=storage, jobs=JobScheduler(storage), codex=codex,
        max_jsonl_bytes=80_000,
    )
    out = await worker.run_one_now("s1")
    assert out is not None
    assert out.raw_memory == "- said hi"
    assert codex.call_count == 1

    row = storage.get_stage1_output("s1")
    assert row is not None
    assert "said hi" in row["raw_memory"]


@pytest.mark.asyncio
async def test_phase1_retries_on_parse_failure(tmp_path: Path, storage) -> None:
    jsonl = tmp_path / "y.jsonl"
    _write_jsonl(jsonl, [
        {"uuid": "1", "session_id": "s2", "turn_id": "t-0001",
         "timestamp": "T", "type": "user",
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "hi"}]}},
    ])
    storage.upsert_session(session_id="s2", rollout_path=jsonl)

    # Bad output: not valid JSON
    codex = _FakeCodexClient(response_text="this is not json at all")
    worker = Phase1Worker(
        storage=storage, jobs=JobScheduler(storage), codex=codex,
    )
    out = await worker.run_one_now("s2")
    # After 2 failed parses, persists noop output
    assert out is not None
    assert out.raw_memory == ""
    assert codex.call_count == 2  # retried once


@pytest.mark.asyncio
async def test_phase1_returns_none_if_no_session_row(storage) -> None:
    codex = _FakeCodexClient()
    worker = Phase1Worker(
        storage=storage, jobs=JobScheduler(storage), codex=codex,
    )
    out = await worker.run_one_now("missing-session")
    assert out is None
    assert codex.call_count == 0


@pytest.mark.asyncio
async def test_phase1_worker_loop_drains_pending(tmp_path: Path, storage) -> None:
    jsonl = tmp_path / "z.jsonl"
    _write_jsonl(jsonl, [
        {"uuid": "1", "session_id": "s3", "turn_id": "t-0001",
         "timestamp": "T", "type": "user",
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "hi"}]}},
    ])
    storage.upsert_session(session_id="s3", rollout_path=jsonl)
    js = JobScheduler(storage)
    js.enqueue(kind=JOB_KIND_PHASE1, job_key="s3")

    codex = _FakeCodexClient(response_text=json.dumps({
        "raw_memory": "- hi", "rollout_summary": "h", "rollout_slug": "hi",
    }))
    done_evt = asyncio.Event()

    def _on_done(session_id):
        done_evt.set()

    worker = Phase1Worker(
        storage=storage, jobs=js, codex=codex,
        poll_interval_s=0.1,
    )
    worker.set_on_complete(_on_done)
    await worker.start()
    try:
        await asyncio.wait_for(done_evt.wait(), timeout=3.0)
    finally:
        await worker.stop()

    assert js.status_of(JOB_KIND_PHASE1, "s3") == JOB_STATUS_DONE
    row = storage.get_stage1_output("s3")
    assert row is not None
    assert row["raw_memory"] == "- hi"


@pytest.mark.asyncio
async def test_phase1_busy_gate_pauses_then_resumes(tmp_path: Path, storage) -> None:
    """While the busy-gate reports a turn is active, no job is claimed; once it
    clears, the pending job drains. This is the 'don't run codex during my
    conversation' fix."""
    jsonl = tmp_path / "b.jsonl"
    _write_jsonl(jsonl, [
        {"uuid": "1", "session_id": "sb", "turn_id": "t-0001",
         "timestamp": "T", "type": "user",
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "hi"}]}},
    ])
    storage.upsert_session(session_id="sb", rollout_path=jsonl)
    js = JobScheduler(storage)
    js.enqueue(kind=JOB_KIND_PHASE1, job_key="sb")

    codex = _FakeCodexClient(response_text=json.dumps({
        "raw_memory": "- hi", "rollout_summary": "h", "rollout_slug": "hi",
    }))
    busy = {"v": True}
    done_evt = asyncio.Event()
    worker = Phase1Worker(
        storage=storage, jobs=js, codex=codex, poll_interval_s=0.05,
    )
    worker.set_busy_gate(lambda: busy["v"])
    worker.set_on_complete(lambda sid: done_evt.set())
    await worker.start()
    try:
        # While busy, the job must NOT be claimed/processed.
        await asyncio.sleep(0.25)
        assert js.status_of(JOB_KIND_PHASE1, "sb") != JOB_STATUS_DONE
        assert not done_evt.is_set()
        # Release the gate → the worker drains the pending job.
        busy["v"] = False
        await asyncio.wait_for(done_evt.wait(), timeout=3.0)
    finally:
        await worker.stop()
    assert js.status_of(JOB_KIND_PHASE1, "sb") == JOB_STATUS_DONE
