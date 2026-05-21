"""Tests for memory/context.py."""
from __future__ import annotations

from pathlib import Path

from g1_brain.memory.context import ContextBuilder


def test_build_returns_empty_when_no_files(tmp_path: Path) -> None:
    mem = tmp_path / "memories"
    mem.mkdir()
    cb = ContextBuilder(memories_dir=mem)
    assert cb.build() == ""


def test_build_with_only_agents_md(tmp_path: Path) -> None:
    mem = tmp_path / "memories"
    mem.mkdir()
    (mem / "AGENTS.md").write_text("# rules\nfollow X")
    cb = ContextBuilder(memories_dir=mem)
    text = cb.build()
    assert "Project rules (AGENTS.md)" in text
    assert "follow X" in text
    assert "Long-term memory" not in text


def test_build_with_only_summary(tmp_path: Path) -> None:
    mem = tmp_path / "memories"
    mem.mkdir()
    (mem / "memory_summary.md").write_text("robot remembers stuff")
    cb = ContextBuilder(memories_dir=mem)
    text = cb.build()
    assert "Long-term memory" in text
    assert "robot remembers stuff" in text
    assert "AGENTS.md" not in text


def test_build_with_both(tmp_path: Path) -> None:
    mem = tmp_path / "memories"
    mem.mkdir()
    (mem / "AGENTS.md").write_text("AGENTS RULES HERE")
    (mem / "memory_summary.md").write_text("SUMMARY HERE")
    cb = ContextBuilder(memories_dir=mem)
    text = cb.build()
    assert "Robot long-term context" in text
    assert "AGENTS RULES HERE" in text
    assert "SUMMARY HERE" in text


def test_build_truncates_oversize_agents(tmp_path: Path) -> None:
    mem = tmp_path / "memories"
    mem.mkdir()
    # 50_000 chars ≈ way more than 1500 tokens
    (mem / "AGENTS.md").write_text("x " * 50_000)
    (mem / "memory_summary.md").write_text("short")
    cb = ContextBuilder(memories_dir=mem,
                        passive_agents_md_max_tokens=100,
                        passive_summary_max_tokens=100)
    text = cb.build()
    assert "[truncated to fit token budget]" in text


def test_empty_file_is_skipped(tmp_path: Path) -> None:
    mem = tmp_path / "memories"
    mem.mkdir()
    (mem / "AGENTS.md").write_text("")
    (mem / "memory_summary.md").write_text("   \n  ")
    cb = ContextBuilder(memories_dir=mem)
    # Both files exist but have only whitespace → builder returns ""
    assert cb.build() == ""
