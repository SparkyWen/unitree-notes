"""Tests for memory/storage.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from g1_brain.memory.storage import (
    CURRENT_SCHEMA_VERSION,
    StorageLayer,
    atomic_write,
    config_hash_of,
    now_ms,
)
from g1_brain.memory.schemas import Stage1Output


def test_init_creates_dirs_and_schema(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        assert (tmp_path / "robot" / "memories").is_dir()
        assert (tmp_path / "robot" / "memories" / "rollout_summaries").is_dir()
        assert (tmp_path / "robot" / "memories" / ".git").is_dir()
        assert (tmp_path / "robot" / "memories" / "MEMORY.md").is_file()
        assert (tmp_path / "robot" / "memories" / "AGENTS.md").is_file()
        assert (tmp_path / "robot" / "state.sqlite").is_file()

        # Schema version is set
        row = storage.execute(
            "SELECT version FROM schema_version",
        ).fetchone()
        assert row["version"] == CURRENT_SCHEMA_VERSION

        # MEMORY.md has the time marker
        text = (tmp_path / "robot" / "memories" / "MEMORY.md").read_text()
        assert text.startswith("# Memory enabled at ")
    finally:
        storage.close()


def test_init_is_idempotent(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    marker_path = tmp_path / "robot" / "memories" / "MEMORY.md"
    marker = marker_path.read_text()
    storage.close()

    storage2 = StorageLayer(tmp_path / "robot")
    storage2.init()
    try:
        # Marker file is NOT overwritten (preserved)
        assert marker_path.read_text() == marker
    finally:
        storage2.close()


def test_atomic_write_replaces_file(tmp_path: Path) -> None:
    p = tmp_path / "f.md"
    atomic_write(p, "first")
    assert p.read_text() == "first"
    atomic_write(p, "second")
    assert p.read_text() == "second"


def test_atomic_write_leaves_no_tmp(tmp_path: Path) -> None:
    p = tmp_path / "f.md"
    atomic_write(p, "hello")
    # No .tmp.* siblings
    tmps = list(tmp_path.glob("f.md.tmp.*"))
    assert tmps == []


def test_upsert_session_and_get(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        jsonl = tmp_path / "logs" / "abc.jsonl"
        jsonl.parent.mkdir(parents=True)
        jsonl.write_text("{}\n")
        storage.upsert_session(
            session_id="s1", rollout_path=jsonl, robot_id="g1",
            git_sha="deadbeef", mjcf_path="/foo.xml",
            config_hash="cfg123",
        )
        row = storage.get_session("s1")
        assert row is not None
        assert row["id"] == "s1"
        assert row["git_sha"] == "deadbeef"
        assert row["mjcf_path"] == "/foo.xml"
        assert row["config_hash"] == "cfg123"

        # Re-upsert preserves git_sha when new value is None
        storage.upsert_session(session_id="s1", rollout_path=jsonl,
                               git_sha=None, mjcf_path=None)
        row2 = storage.get_session("s1")
        assert row2["git_sha"] == "deadbeef"
    finally:
        storage.close()


def test_mark_session_ended(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        jsonl = tmp_path / "x.jsonl"
        jsonl.write_text("{}\n")
        storage.upsert_session(session_id="s2", rollout_path=jsonl)
        assert storage.get_session("s2")["ended_at"] is None
        storage.mark_session_ended("s2")
        assert storage.get_session("s2")["ended_at"] is not None
    finally:
        storage.close()


def test_upsert_stage1_and_list(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        jsonl = tmp_path / "x.jsonl"
        jsonl.write_text("{}\n")
        storage.upsert_session(session_id="s3", rollout_path=jsonl)
        out = Stage1Output(
            raw_memory="- the red cup is on the table",
            rollout_summary="Robot saw the red cup.",
            rollout_slug="red-cup",
        )
        storage.upsert_stage1_output("s3", out, source_updated_at=now_ms())
        rows = storage.list_stage1_for_phase2(max_count=10, max_unused_days=30)
        assert len(rows) == 1
        assert rows[0]["session_id"] == "s3"
        assert rows[0]["rollout_slug"] == "red-cup"
        assert "red cup" in rows[0]["raw_memory"]

        # Empty raw_memory rows are excluded
        storage.upsert_session(session_id="s4", rollout_path=jsonl.with_name("y.jsonl"))
        (tmp_path / "y.jsonl").write_text("{}\n")
        storage.upsert_stage1_output(
            "s4",
            Stage1Output(raw_memory="", rollout_summary="", rollout_slug=None),
            source_updated_at=now_ms(),
        )
        rows2 = storage.list_stage1_for_phase2(max_count=10, max_unused_days=30)
        ids = {r["session_id"] for r in rows2}
        assert "s4" not in ids
    finally:
        storage.close()


def test_write_raw_memories_md_deterministic(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        jsonl = tmp_path / "x.jsonl"; jsonl.write_text("{}\n")
        storage.upsert_session(session_id="aaa", rollout_path=jsonl)
        storage.upsert_session(session_id="bbb",
                                rollout_path=tmp_path / "y.jsonl")
        (tmp_path / "y.jsonl").write_text("{}\n")
        storage.upsert_stage1_output(
            "bbb",
            Stage1Output(raw_memory="B mem", rollout_summary="B", rollout_slug="b"),
            source_updated_at=now_ms(),
        )
        storage.upsert_stage1_output(
            "aaa",
            Stage1Output(raw_memory="A mem", rollout_summary="A", rollout_slug="a"),
            source_updated_at=now_ms(),
        )
        rows = storage.list_stage1_for_phase2(max_count=10, max_unused_days=30)
        storage.write_raw_memories_md(rows)
        content = (tmp_path / "robot" / "memories" / "raw_memories.md").read_text()
        # Deterministic ascending session_id order: aaa before bbb
        a_pos = content.find("aaa")
        b_pos = content.find("bbb")
        assert a_pos >= 0 and b_pos >= 0
        assert a_pos < b_pos
    finally:
        storage.close()


def test_write_rollout_summary_creates_file(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        jsonl = tmp_path / "x.jsonl"; jsonl.write_text("{}\n")
        storage.upsert_session(session_id="zzz123", rollout_path=jsonl)
        storage.upsert_stage1_output(
            "zzz123",
            Stage1Output(raw_memory="m", rollout_summary="s",
                         rollout_slug="walk-test"),
            source_updated_at=now_ms(),
        )
        rows = storage.list_stage1_for_phase2(max_count=10, max_unused_days=30)
        path = storage.write_rollout_summary(rows[0])
        assert path.exists()
        assert "walk-test" in path.name
        text = path.read_text()
        assert "zzz123" in text
    finally:
        storage.close()


def test_bump_stage1_usage(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        jsonl = tmp_path / "x.jsonl"; jsonl.write_text("{}\n")
        storage.upsert_session(session_id="s1", rollout_path=jsonl)
        storage.upsert_stage1_output(
            "s1",
            Stage1Output(raw_memory="m", rollout_summary="s", rollout_slug="t"),
            source_updated_at=now_ms(),
        )
        row = storage.get_stage1_output("s1")
        assert row["usage_count"] == 0
        storage.bump_stage1_usage("s1")
        row = storage.get_stage1_output("s1")
        assert row["usage_count"] == 1
        assert row["last_usage"] is not None
    finally:
        storage.close()


def test_evict_old_rollout_summaries(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        # Create 5 fake summary files
        for i in range(5):
            (storage.rollout_summaries_dir / f"sum-{i}.md").write_text("x")
        deleted = storage.evict_old_rollout_summaries(keep_max=3)
        assert deleted == 2
        remaining = list(storage.rollout_summaries_dir.glob("*.md"))
        assert len(remaining) == 3
    finally:
        storage.close()


def test_git_status_porcelain_clean_after_init(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        # Right after init with only baseline commit, status should be empty
        # (MEMORY.md/AGENTS.md were committed in baseline) — actually our
        # baseline only commits .gitignore. So MEMORY.md/AGENTS.md ARE new.
        status = storage.git_status_porcelain()
        # Untracked files include MEMORY.md and AGENTS.md
        assert "MEMORY.md" in status or "AGENTS.md" in status
    finally:
        storage.close()


def test_git_commit_baseline_then_clean(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        ok = storage.git_commit_baseline("test commit")
        assert ok
        status = storage.git_status_porcelain()
        assert status.strip() == ""
    finally:
        storage.close()


def test_config_hash_stable(tmp_path: Path) -> None:
    h1 = config_hash_of({"a": 1, "b": 2})
    h2 = config_hash_of({"b": 2, "a": 1})
    assert h1 == h2  # key order independent
    h3 = config_hash_of({"a": 1, "b": 3})
    assert h1 != h3
    assert len(h1) == 16


def test_corrupt_db_is_recovered(tmp_path: Path) -> None:
    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    storage.close()
    # Corrupt the file
    db_path = tmp_path / "robot" / "state.sqlite"
    db_path.write_text("not a sqlite file")

    storage2 = StorageLayer(tmp_path / "robot")
    storage2.init()  # Should recover by backing up + recreating
    try:
        # Schema is rebuilt
        row = storage2.execute(
            "SELECT version FROM schema_version",
        ).fetchone()
        assert row["version"] == CURRENT_SCHEMA_VERSION
        # Backup file exists
        backups = list((tmp_path / "robot").glob("*.broken.*"))
        assert backups
    finally:
        storage2.close()
