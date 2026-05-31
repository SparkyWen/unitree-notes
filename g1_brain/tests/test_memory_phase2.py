"""Tests for memory/phase2.py."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from g1_brain.memory.codex_client import CodexExecError, CodexExecResult
from g1_brain.memory.jobs import JobScheduler
from g1_brain.memory.phase2 import Phase2Worker, parse_phase2_json
from g1_brain.memory.schemas import Stage1Output
from g1_brain.memory.storage import StorageLayer, now_ms


class _FakeCodexClient:
    def __init__(self, response_text: str = "", raise_error: bool = False):
        self.response_text = response_text
        self.raise_error = raise_error
        self.call_count = 0

    def is_available(self) -> bool:
        return True

    async def exec_once(self, prompt: str, **kwargs) -> CodexExecResult:
        self.call_count += 1
        if self.raise_error:
            raise CodexExecError("simulated")
        return CodexExecResult(text=self.response_text, stderr_tail="", returncode=0)


@pytest.fixture
def storage(tmp_path: Path):
    s = StorageLayer(tmp_path / "robot")
    s.init()
    yield s
    s.close()


def _seed_session_and_stage1(storage: StorageLayer, sid: str, mem: str) -> None:
    jsonl = storage.robot_root.parent / f"{sid}.jsonl"
    jsonl.write_text("{}\n")
    storage.upsert_session(session_id=sid, rollout_path=jsonl)
    storage.upsert_stage1_output(
        sid,
        Stage1Output(raw_memory=mem, rollout_summary=f"{sid} summary",
                     rollout_slug=f"{sid}-slug"),
        source_updated_at=now_ms(),
    )


# ---------- parse_phase2_json ----------

def test_parse_phase2_json_clean() -> None:
    text = json.dumps({
        "memory_md": "# header",
        "memory_summary_md": "summary",
    })
    m, s = parse_phase2_json(text)
    assert m == "# header"
    assert s == "summary"


def test_parse_phase2_json_fence() -> None:
    text = (
        '```json\n'
        '{"memory_md":"x","memory_summary_md":"y"}\n'
        '```'
    )
    m, s = parse_phase2_json(text)
    assert m == "x"
    assert s == "y"


def test_parse_phase2_json_raises_on_bad() -> None:
    with pytest.raises((json.JSONDecodeError, ValueError)):
        parse_phase2_json("nope")


# ---------- worker ----------

@pytest.mark.asyncio
async def test_phase2_no_op_when_no_stage1(storage) -> None:
    codex = _FakeCodexClient()
    worker = Phase2Worker(storage=storage, jobs=JobScheduler(storage),
                          codex=codex)
    # Commit baseline so workspace is clean
    storage.git_commit_baseline("baseline")
    changed = await worker.run_once_now()
    assert changed is False
    # codex never invoked since workspace is clean and no stage1 outputs
    assert codex.call_count == 0


@pytest.mark.asyncio
async def test_phase2_writes_files_when_dirty(storage) -> None:
    _seed_session_and_stage1(storage, "aaa", "- aaa knows X")
    _seed_session_and_stage1(storage, "bbb", "- bbb did Y")

    # Commit current baseline (before sync), so sync produces diff
    storage.git_commit_baseline("pre-sync baseline")

    codex = _FakeCodexClient(response_text=json.dumps({
        "memory_md": "# Memory\n\nfact A\nfact B",
        "memory_summary_md": "Robot learned X and Y.",
    }))
    worker = Phase2Worker(storage=storage, jobs=JobScheduler(storage),
                          codex=codex)
    changed = await worker.run_once_now()
    assert changed is True
    assert codex.call_count == 1

    mem = (storage.memories_dir / "MEMORY.md").read_text()
    assert "fact A" in mem
    summary = (storage.memories_dir / "memory_summary.md").read_text()
    assert "Robot learned" in summary

    # Workspace should be clean after baseline commit
    status = storage.git_status_porcelain().strip()
    assert status == ""


@pytest.mark.asyncio
async def test_phase2_skips_on_codex_error(storage) -> None:
    _seed_session_and_stage1(storage, "ccc", "- some memory")
    storage.git_commit_baseline("baseline")
    codex = _FakeCodexClient(raise_error=True)
    worker = Phase2Worker(storage=storage, jobs=JobScheduler(storage),
                          codex=codex)
    changed = await worker.run_once_now()
    # codex failed → consolidation skipped → returns False
    assert changed is False
    # raw_memories.md still got written
    assert (storage.memories_dir / "raw_memories.md").exists()


@pytest.mark.asyncio
async def test_phase2_skips_on_parse_failure(storage) -> None:
    _seed_session_and_stage1(storage, "ddd", "- mem")
    storage.git_commit_baseline("baseline")
    codex = _FakeCodexClient(response_text="garbage not json")
    worker = Phase2Worker(storage=storage, jobs=JobScheduler(storage),
                          codex=codex)
    changed = await worker.run_once_now()
    assert changed is False


@pytest.mark.asyncio
async def test_phase2_idempotent_on_clean_workspace(storage) -> None:
    _seed_session_and_stage1(storage, "eee", "- mem")
    codex = _FakeCodexClient(response_text=json.dumps({
        "memory_md": "# m", "memory_summary_md": "s",
    }))
    worker = Phase2Worker(storage=storage, jobs=JobScheduler(storage),
                          codex=codex)
    # First run: dirty, consolidates
    await worker.run_once_now()
    first_calls = codex.call_count
    # Second run: clean baseline, no codex call
    changed = await worker.run_once_now()
    assert codex.call_count == first_calls
    assert changed is False
