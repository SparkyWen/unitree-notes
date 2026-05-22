"""Tests for memory/codex_client.py — mocking subprocess behavior."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from g1_brain.memory.codex_client import (
    CodexClient,
    CodexExecError,
    CodexQuotaExhausted,
    _looks_like_quota,
)


def test_looks_like_quota() -> None:
    assert _looks_like_quota("rate_limit exceeded")
    assert _looks_like_quota("Quota exceeded for project")
    assert _looks_like_quota("Rate Limit")
    assert not _looks_like_quota("everything is fine")


# Build a fake codex binary that we control via env vars.
# It must be a script that's executable. We write it under tmp_path/bin/codex.
def _make_fake_codex_bin(
    tmp_path: Path,
    *,
    stdout_lines: list[str],
    stderr_text: str = "",
    exit_code: int = 0,
    delay_s: float = 0.0,
) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    codex = bindir / "codex"
    # Write a python script that emits the requested lines
    script = f"""#!{sys.executable}
import sys, time, os
time.sleep({delay_s})
for line in {stdout_lines!r}:
    print(line)
    sys.stdout.flush()
sys.stderr.write({stderr_text!r})
sys.stderr.flush()
sys.exit({exit_code})
"""
    codex.write_text(script)
    codex.chmod(codex.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return codex


@pytest.fixture
def workdir(tmp_path: Path):
    d = tmp_path / "robot" / "memories"
    d.mkdir(parents=True)
    return d


@pytest.mark.asyncio
async def test_exec_once_extracts_agent_message(tmp_path: Path, workdir) -> None:
    events = [
        json.dumps({"type": "agent_message", "message": "Hello from codex"}),
        json.dumps({"type": "task_complete"}),
    ]
    fake = _make_fake_codex_bin(tmp_path, stdout_lines=events)
    client = CodexClient(codex_bin=str(fake), workdir=workdir)
    result = await client.exec_once("test prompt", timeout_s=10)
    assert "Hello from codex" in result.text
    assert result.returncode == 0


@pytest.mark.asyncio
async def test_exec_once_extracts_task_complete_last_message(
    tmp_path: Path, workdir,
) -> None:
    events = [
        json.dumps({"type": "task_complete",
                    "last_agent_message": "final answer"}),
    ]
    fake = _make_fake_codex_bin(tmp_path, stdout_lines=events)
    client = CodexClient(codex_bin=str(fake), workdir=workdir)
    result = await client.exec_once("p", timeout_s=10)
    assert "final answer" in result.text


@pytest.mark.asyncio
async def test_exec_once_extracts_message_role_assistant(
    tmp_path: Path, workdir,
) -> None:
    events = [
        json.dumps({
            "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "part1"},
                        {"type": "text", "text": "part2"}],
        }),
    ]
    fake = _make_fake_codex_bin(tmp_path, stdout_lines=events)
    client = CodexClient(codex_bin=str(fake), workdir=workdir)
    result = await client.exec_once("p", timeout_s=10)
    assert result.text == "part1part2"


@pytest.mark.asyncio
async def test_exec_once_takes_last_message_when_multiple(
    tmp_path: Path, workdir,
) -> None:
    events = [
        json.dumps({"type": "agent_message", "message": "first"}),
        json.dumps({"type": "agent_message", "message": "second"}),
    ]
    fake = _make_fake_codex_bin(tmp_path, stdout_lines=events)
    client = CodexClient(codex_bin=str(fake), workdir=workdir)
    result = await client.exec_once("p", timeout_s=10)
    assert result.text == "second"


@pytest.mark.asyncio
async def test_exec_once_extracts_codex_0128_item_completed_envelope(
    tmp_path: Path, workdir,
) -> None:
    """codex-cli 0.128 wraps agent_message inside an item.completed envelope.

    Real event observed from codex-cli 0.128.0:
      {"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"4"}}

    Before the fix the parser only knew the old {"type":"agent_message",
    "message":"..."} shape and Phase1 failed on every session with
    "produced no assistant text".
    """
    events = [
        json.dumps({"type": "thread.started",
                    "thread_id": "019e4e27-d5fd-7193-8506-711aebbaf2a4"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({
            "type": "item.completed",
            "item": {"id": "item_0", "type": "agent_message", "text": "4"},
        }),
        json.dumps({"type": "turn.completed",
                    "usage": {"input_tokens": 13748, "output_tokens": 5}}),
    ]
    fake = _make_fake_codex_bin(tmp_path, stdout_lines=events)
    client = CodexClient(codex_bin=str(fake), workdir=workdir)
    result = await client.exec_once("p", timeout_s=10)
    assert result.text == "4"


@pytest.mark.asyncio
async def test_exec_once_extracts_codex_0128_item_completed_message_role(
    tmp_path: Path, workdir,
) -> None:
    """Some codex 0.128 builds nest a role=assistant message inside item.completed."""
    events = [
        json.dumps({
            "type": "item.completed",
            "item": {
                "id": "item_0", "type": "message", "role": "assistant",
                "content": [{"type": "text", "text": "hello "},
                            {"type": "text", "text": "world"}],
            },
        }),
    ]
    fake = _make_fake_codex_bin(tmp_path, stdout_lines=events)
    client = CodexClient(codex_bin=str(fake), workdir=workdir)
    result = await client.exec_once("p", timeout_s=10)
    assert result.text == "hello world"


@pytest.mark.asyncio
async def test_exec_once_quota_detection_in_stderr(
    tmp_path: Path, workdir,
) -> None:
    events = [json.dumps({"type": "agent_message", "message": "ok"})]
    fake = _make_fake_codex_bin(
        tmp_path, stdout_lines=events,
        stderr_text="error: rate_limit exceeded for plan",
        exit_code=1,
    )
    client = CodexClient(codex_bin=str(fake), workdir=workdir)
    with pytest.raises(CodexQuotaExhausted):
        await client.exec_once("p", timeout_s=10)


@pytest.mark.asyncio
async def test_exec_once_no_text_raises(tmp_path: Path, workdir) -> None:
    fake = _make_fake_codex_bin(tmp_path, stdout_lines=[], exit_code=1,
                                  stderr_text="boom")
    client = CodexClient(codex_bin=str(fake), workdir=workdir)
    with pytest.raises(CodexExecError):
        await client.exec_once("p", timeout_s=10)


@pytest.mark.asyncio
async def test_exec_once_binary_missing(tmp_path: Path, workdir) -> None:
    client = CodexClient(codex_bin="/does/not/exist/codex", workdir=workdir)
    assert client.is_available() is False
    with pytest.raises(CodexExecError):
        await client.exec_once("p", timeout_s=5)


@pytest.mark.asyncio
async def test_exec_once_timeout_kills_process(tmp_path: Path, workdir) -> None:
    # Fake codex sleeps 5s before responding
    events = [json.dumps({"type": "agent_message", "message": "late"})]
    fake = _make_fake_codex_bin(tmp_path, stdout_lines=events, delay_s=5.0)
    client = CodexClient(codex_bin=str(fake), workdir=workdir)
    with pytest.raises(CodexExecError, match="timeout"):
        await client.exec_once("p", timeout_s=0.5)


@pytest.mark.asyncio
async def test_exec_once_with_codex_home_env(tmp_path: Path, workdir) -> None:
    # Use a fake codex that writes its env to stderr so we can check
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    codex = bindir / "codex"
    script = f"""#!{sys.executable}
import os, sys, json
sys.stderr.write("CODEX_HOME=" + os.environ.get("CODEX_HOME", "MISSING") + "\\n")
print(json.dumps({{"type": "agent_message", "message": "ok"}}))
"""
    codex.write_text(script)
    codex.chmod(codex.stat().st_mode | stat.S_IXUSR)

    home = tmp_path / "custom_home"
    home.mkdir()
    client = CodexClient(
        codex_bin=str(codex), workdir=workdir, codex_home=home,
    )
    result = await client.exec_once("p", timeout_s=10)
    assert str(home) in result.stderr_tail
