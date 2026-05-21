"""Tests for memory/recall.py — grep/read/glob + sandbox."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from g1_brain.memory.recall import RecallSearcher
from g1_brain.memory.schemas import (
    RECALL_STATUS_FILE_NOT_FOUND,
    RECALL_STATUS_OK,
    RECALL_STATUS_PATH_OUTSIDE_SANDBOX,
)


@pytest.fixture
def memories_tree(tmp_path: Path):
    mem = tmp_path / "memories"
    mem.mkdir()
    (mem / "MEMORY.md").write_text(
        "# G1 Memory Registry\n\n"
        "## Places\n\n- Kitchen — has a red cup on the table\n"
        "- Living room — couch left of TV\n\n"
        "## Skills learned\n\n- Wave gesture works with right hand\n"
    )
    (mem / "memory_summary.md").write_text(
        "Robot remembers the kitchen and that the red cup is on the table.\n"
    )
    (mem / "raw_memories.md").write_text(
        "## Session abc\n- the red cup on the kitchen table is heavy\n"
        "## Session def\n- coffee machine to the left of the sink\n"
    )
    (mem / "AGENTS.md").write_text(
        "# AGENTS\n\n- recall walks MEMORY first\n"
    )
    summaries = mem / "rollout_summaries"
    summaries.mkdir()
    (summaries / "abc-2026-walk.md").write_text(
        "# walk-test\n\nrobot walked 0.58m forward, saw red cup.\n"
    )
    (summaries / "def-2026-coffee.md").write_text(
        "# coffee-machine-mapping\n\nrobot mapped coffee machine left of sink.\n"
    )

    convs = tmp_path / "conversations"
    convs.mkdir()
    (convs / "2026-05-21T10-00-00Z-abc12345.jsonl").write_text(
        "\n".join([
            json.dumps({"session_id": "abc12345aaaa", "type": "user",
                        "message": {"role": "user",
                                    "content": [{"type": "text",
                                                 "text": "走两步看那个红色杯子"}]}},
                       ensure_ascii=False),
        ]) + "\n",
        encoding="utf-8",
    )
    return mem, convs


@pytest.fixture
def searcher(memories_tree):
    mem, convs = memories_tree
    return RecallSearcher(memories_dir=mem, conversations_dir=convs)


# ---------- grep ----------

@pytest.mark.asyncio
async def test_grep_registry_finds_in_memory_md(searcher) -> None:
    r = await searcher.grep(pattern="red cup", scope="registry")
    assert r["status"] == RECALL_STATUS_OK
    assert any("MEMORY.md" in m and "red cup" in m for m in r["matches"])


@pytest.mark.asyncio
async def test_grep_registry_finds_in_raw_memories(searcher) -> None:
    r = await searcher.grep(pattern="coffee", scope="registry")
    assert r["status"] == RECALL_STATUS_OK
    assert any("raw_memories.md" in m for m in r["matches"])


@pytest.mark.asyncio
async def test_grep_rollouts_finds_only_in_summaries(searcher) -> None:
    r = await searcher.grep(pattern="walked", scope="rollouts")
    assert r["status"] == RECALL_STATUS_OK
    assert all("rollout_summaries" in m for m in r["matches"])
    assert any("walk" in m for m in r["matches"])


@pytest.mark.asyncio
async def test_grep_jsonl_with_session(searcher) -> None:
    r = await searcher.grep(pattern="红色", scope="jsonl",
                            session_id="abc12345")
    assert r["status"] == RECALL_STATUS_OK
    assert any(".jsonl" in m for m in r["matches"])


@pytest.mark.asyncio
async def test_grep_no_match_returns_empty_matches(searcher) -> None:
    r = await searcher.grep(pattern="zzz-nonexistent-zzz", scope="registry")
    assert r["status"] == RECALL_STATUS_OK
    assert r["matches"] == []


@pytest.mark.asyncio
async def test_grep_respects_max_lines(searcher, memories_tree) -> None:
    mem, _ = memories_tree
    # Make a file with many matching lines
    big = mem / "big.md"  # not in registry default globs, so this won't be picked up
    # Instead, append many "match" lines to raw_memories.md
    rm = mem / "raw_memories.md"
    extra = "\n".join([f"- line {i} cup" for i in range(100)])
    rm.write_text(rm.read_text() + "\n" + extra)
    r = await searcher.grep(pattern="cup", scope="registry", max_lines=5)
    assert len(r["matches"]) <= 5


# ---------- read ----------

@pytest.mark.asyncio
async def test_read_relative_to_memories(searcher) -> None:
    r = await searcher.read(path="MEMORY.md")
    assert r["status"] == RECALL_STATUS_OK
    text = "\n".join(r["lines"])
    assert "G1 Memory Registry" in text


@pytest.mark.asyncio
async def test_read_with_line_range(searcher) -> None:
    r = await searcher.read(path="MEMORY.md", start_line=1, end_line=3)
    assert r["status"] == RECALL_STATUS_OK
    assert len(r["lines"]) <= 3


@pytest.mark.asyncio
async def test_read_rejects_absolute_path(searcher) -> None:
    r = await searcher.read(path="/etc/passwd")
    assert r["status"] == RECALL_STATUS_PATH_OUTSIDE_SANDBOX


@pytest.mark.asyncio
async def test_read_rejects_dotdot_escape(searcher) -> None:
    r = await searcher.read(path="../../../../etc/passwd")
    assert r["status"] == RECALL_STATUS_PATH_OUTSIDE_SANDBOX


@pytest.mark.asyncio
async def test_read_missing_file(searcher) -> None:
    r = await searcher.read(path="never-existed.md")
    assert r["status"] == RECALL_STATUS_FILE_NOT_FOUND


@pytest.mark.asyncio
async def test_read_jsonl_with_line_range(searcher, memories_tree) -> None:
    mem, convs = memories_tree
    files = list(convs.glob("*.jsonl"))
    assert files
    # Use path relative to conversations dir
    rel = files[0].name
    # Sandbox allows conversations/ too; recall_read uses relative within either root
    r = await searcher.read(path=rel, start_line=1, end_line=5)
    assert r["status"] == RECALL_STATUS_OK


# ---------- glob ----------

@pytest.mark.asyncio
async def test_glob_lists_rollout_summaries(searcher) -> None:
    r = await searcher.glob(pattern="rollout_summaries/*.md")
    assert r["status"] == RECALL_STATUS_OK
    assert len(r["matches"]) == 2


@pytest.mark.asyncio
async def test_glob_with_limit(searcher) -> None:
    r = await searcher.glob(pattern="rollout_summaries/*.md", limit=1)
    assert r["status"] == RECALL_STATUS_OK
    assert len(r["matches"]) == 1
    assert r["truncated"] is True


@pytest.mark.asyncio
async def test_glob_rejects_absolute_pattern(searcher) -> None:
    r = await searcher.glob(pattern="/etc/*")
    # We allow no results (skipped by leading-slash filter)
    assert r["status"] == RECALL_STATUS_OK
    assert r["matches"] == []


@pytest.mark.asyncio
async def test_glob_rejects_dotdot_pattern(searcher) -> None:
    r = await searcher.glob(pattern="../*.md")
    assert r["status"] == RECALL_STATUS_OK
    assert r["matches"] == []


# ---------- sandbox edge cases ----------

@pytest.mark.asyncio
async def test_symlink_outside_root_is_rejected(searcher, memories_tree, tmp_path) -> None:
    mem, _ = memories_tree
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    link = mem / "evil-link.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this fs")
    r = await searcher.read(path="evil-link.md")
    # After resolve, the symlink target is outside memories/
    assert r["status"] == RECALL_STATUS_PATH_OUTSIDE_SANDBOX
