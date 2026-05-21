"""End-to-end memory pipeline integration tests.

Exercises the full path:
    JSONL → Phase1 worker → state DB → Phase2 worker → MEMORY.md

with the only mock being the codex exec subprocess (drop-in
_FakeCodexClient). SQLite, git, files all real.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from g1_brain.memory import MemorySubsystem
from g1_brain.memory.codex_client import CodexExecResult
from g1_brain.memory.schemas import JOB_KIND_PHASE1, JOB_STATUS_DONE


class _ScriptedCodex:
    """CodexClient drop-in that returns a different response per call.

    Stage1 prompts contain the project's Phase1 system prompt; Stage2 the
    Phase2 system prompt. We dispatch on that.
    """

    def __init__(self, *, phase1: str = "", phase2: str = ""):
        self.phase1 = phase1
        self.phase2 = phase2
        self.phase1_calls = 0
        self.phase2_calls = 0

    def is_available(self) -> bool:
        return True

    async def exec_once(self, prompt: str, **kwargs) -> CodexExecResult:
        if "Memory Writing Agent: Phase 1" in prompt or "raw_memory" in prompt.lower():
            self.phase1_calls += 1
            return CodexExecResult(text=self.phase1, stderr_tail="", returncode=0)
        # Default to phase2 (consolidation)
        self.phase2_calls += 1
        return CodexExecResult(text=self.phase2, stderr_tail="", returncode=0)


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


@pytest.mark.asyncio
async def test_full_round_trip_jsonl_to_memory_md(tmp_path: Path) -> None:
    robot_root = tmp_path / "robot"
    rollout = tmp_path / "logs" / "session-abc12345.jsonl"
    _write_jsonl(rollout, [
        {"uuid": "1", "session_id": "abc12345", "turn_id": "t-0001",
         "timestamp": "T", "type": "meta", "subtype": "session_start",
         "data": {}},
        {"uuid": "2", "session_id": "abc12345", "turn_id": "t-0001",
         "timestamp": "T", "type": "user",
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "go look at the red cup"}]}},
        {"uuid": "3", "session_id": "abc12345", "turn_id": "t-0001",
         "timestamp": "T", "type": "meta", "subtype": "plan_done",
         "data": {"turn_id": "t-0001"}},
    ])

    phase1_response = json.dumps({
        "raw_memory": "- user asked about a red cup",
        "rollout_summary": "User mentioned the red cup.",
        "rollout_slug": "red-cup",
    })
    phase2_response = json.dumps({
        "memory_md": "# G1 Memory\n\n## Places\n- red cup mentioned\n",
        "memory_summary_md": "Robot has heard about a red cup.",
    })

    mem = MemorySubsystem(
        robot_root=robot_root,
        rollout_path=rollout,
        session_id="abc12345",
        cfg={"phase1_debounce_s": 0},
        conversations_dir=rollout.parent,
    )
    # Inject scripted codex (replace BOTH client refs)
    scripted = _ScriptedCodex(phase1=phase1_response, phase2=phase2_response)
    mem.codex_exec = scripted
    mem.phase1._codex = scripted
    mem.phase2._codex = scripted

    await mem.start()
    try:
        # Force-run Phase1 synchronously
        out = await mem.phase1.run_one_now("abc12345")
        assert out is not None
        assert "red cup" in out.raw_memory

        # Force Phase2
        changed = await mem.phase2.run_once_now()
        assert changed is True

        # Files should exist
        memory_md = robot_root / "memories" / "MEMORY.md"
        summary_md = robot_root / "memories" / "memory_summary.md"
        raw_md = robot_root / "memories" / "raw_memories.md"
        assert memory_md.exists()
        assert summary_md.exists()
        assert raw_md.exists()
        assert "red cup" in memory_md.read_text()
        assert "red cup" in raw_md.read_text()
    finally:
        await mem.stop()


@pytest.mark.asyncio
async def test_recall_after_pipeline(tmp_path: Path) -> None:
    robot_root = tmp_path / "robot"
    rollout = tmp_path / "logs" / "sess-deadbeef.jsonl"
    _write_jsonl(rollout, [
        {"uuid": "1", "session_id": "deadbeef", "turn_id": "t-0001",
         "timestamp": "T", "type": "user",
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "remember the coffee machine"}]}},
    ])

    phase1_response = json.dumps({
        "raw_memory": "- coffee machine is to the left of the sink",
        "rollout_summary": "Robot learned coffee machine location.",
        "rollout_slug": "coffee-mapping",
    })
    phase2_response = json.dumps({
        "memory_md": "# Memory\n\n## Places\n- coffee machine left of sink",
        "memory_summary_md": "Coffee machine left of sink.",
    })

    mem = MemorySubsystem(
        robot_root=robot_root, rollout_path=rollout,
        session_id="deadbeef", cfg={"phase1_debounce_s": 0},
        conversations_dir=rollout.parent,
    )
    scripted = _ScriptedCodex(phase1=phase1_response, phase2=phase2_response)
    mem.codex_exec = scripted
    mem.phase1._codex = scripted
    mem.phase2._codex = scripted

    await mem.start()
    try:
        await mem.phase1.run_one_now("deadbeef")
        await mem.phase2.run_once_now()

        # Now recall via the searcher (what skill_server's recall_grep does)
        r = await mem.recall.grep(pattern="coffee", scope="registry")
        assert r["status"] == "ok"
        assert any("coffee" in m for m in r["matches"])

        # Read MEMORY.md
        rr = await mem.recall.read(path="MEMORY.md")
        assert rr["status"] == "ok"
        assert any("coffee" in ln for ln in rr["lines"])
    finally:
        await mem.stop()


@pytest.mark.asyncio
async def test_passive_context_built_from_phase2_output(tmp_path: Path) -> None:
    robot_root = tmp_path / "robot"
    rollout = tmp_path / "logs" / "sess-c0ffee01.jsonl"
    _write_jsonl(rollout, [
        {"uuid": "1", "session_id": "c0ffee01", "turn_id": "t-0001",
         "timestamp": "T", "type": "user",
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "x"}]}},
    ])
    phase1_response = json.dumps({
        "raw_memory": "- some fact",
        "rollout_summary": "summary",
        "rollout_slug": "noop",
    })
    phase2_response = json.dumps({
        "memory_md": "# Mem",
        "memory_summary_md": "PASSIVE_SUMMARY_CONTENT_TOKEN",
    })

    mem = MemorySubsystem(
        robot_root=robot_root, rollout_path=rollout,
        session_id="c0ffee01", cfg={"phase1_debounce_s": 0},
        conversations_dir=rollout.parent,
    )
    scripted = _ScriptedCodex(phase1=phase1_response, phase2=phase2_response)
    mem.codex_exec = scripted
    mem.phase1._codex = scripted
    mem.phase2._codex = scripted

    await mem.start()
    try:
        # Initially memory_summary.md does not exist
        ctx0 = mem.build_passive_context()
        # AGENTS.md is created at init, so ctx0 will have AGENTS but not summary
        assert "PASSIVE_SUMMARY_CONTENT_TOKEN" not in ctx0
        # Run pipeline
        await mem.phase1.run_one_now("c0ffee01")
        await mem.phase2.run_once_now()
        ctx1 = mem.build_passive_context()
        assert "PASSIVE_SUMMARY_CONTENT_TOKEN" in ctx1
    finally:
        await mem.stop()


@pytest.mark.asyncio
async def test_on_plan_done_enqueues_phase1(tmp_path: Path) -> None:
    robot_root = tmp_path / "robot"
    rollout = tmp_path / "logs" / "p.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text('{"uuid":"1","session_id":"abc","turn_id":"t-0001","timestamp":"T","type":"user","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}\n')

    mem = MemorySubsystem(
        robot_root=robot_root, rollout_path=rollout,
        session_id="abc", cfg={"phase1_debounce_s": 0},
        conversations_dir=rollout.parent,
    )
    # Don't actually run codex
    mem.codex_exec = _ScriptedCodex(phase1=json.dumps({
        "raw_memory": "", "rollout_summary": "", "rollout_slug": "noop",
    }), phase2=json.dumps({"memory_md": "", "memory_summary_md": ""}))
    mem.phase1._codex = mem.codex_exec

    await mem.start()
    try:
        await mem.on_plan_done()
        # Job should now be pending (or leased/done by worker if it claimed)
        status = mem.jobs.status_of(JOB_KIND_PHASE1, "abc")
        assert status in ("pending", "leased", "done")
    finally:
        await mem.stop()


@pytest.mark.asyncio
async def test_memory_subsystem_survives_codex_unavailable(tmp_path: Path) -> None:
    """If the codex binary is missing, daemon stays DEAD but recall still works."""
    robot_root = tmp_path / "robot"
    rollout = tmp_path / "logs" / "x.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n")

    mem = MemorySubsystem(
        robot_root=robot_root, rollout_path=rollout, session_id="ssss",
        cfg={"phase1_debounce_s": 0},
        conversations_dir=rollout.parent,
    )
    # Point codex at a non-existent binary
    mem.daemon._bin = "/does/not/exist/codex"

    await mem.start()
    try:
        # Give daemon a moment to fail
        await asyncio.sleep(0.2)
        # Recall must still work (it doesn't need daemon)
        r = await mem.recall.grep(pattern="something", scope="registry")
        assert r["status"] == "ok"
        # ask_slow_brain returns daemon_dead, doesn't raise
        ask = await mem.daemon.ask_slow_brain("hi", timeout_s=1.0)
        assert ask.status == "daemon_dead"
    finally:
        await mem.stop()
