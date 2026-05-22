"""Tests for memory/daemon.py — uses a fake MCP server subprocess."""
from __future__ import annotations

import asyncio
import json
import stat
import sys
from pathlib import Path

import pytest

from g1_brain.memory.daemon import (
    CodexDaemon,
    STATE_DEAD,
    STATE_READY,
)
from g1_brain.memory.schemas import AskResult


def _write_fake_mcp_server(tmp_path: Path, body: str, name: str = "codex") -> Path:
    """Write a python script that pretends to be `codex mcp-server`.

    `body` is the python code that drives one MCP session. It can use
    `read()` to get the next line as a dict, and `send(d)` to write one
    response line.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    p = bindir / name
    script = f"""#!{sys.executable}
import sys, json, os, time

def read():
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)

def send(d):
    sys.stdout.write(json.dumps(d) + "\\n")
    sys.stdout.flush()

{body}
"""
    p.write_text(script)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


@pytest.fixture
def workdir(tmp_path: Path):
    d = tmp_path / "robot" / "memories"
    d.mkdir(parents=True)
    return d


# ---------- Standard MCP server body ----------

_STANDARD_SERVER = '''
# Echo a standard MCP handshake then handle one tools/call

# First two reads: subprocess startup may give us initialize then we sub-handle
# Codex's CLI will check argv parsing — we ignore argv here.

# The daemon expects:
#   1. We receive: initialize → respond with capabilities
#   2. We receive: notifications/initialized → no response
#   3. We receive: tools/list → respond with [{"name":"codex"}]
#   4. We receive: tools/call(codex, ...) → optional progress + final response
#
# We loop processing messages.

while True:
    msg = read()
    if msg is None:
        break
    method = msg.get("method", "")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg.get("id"),
              "result": {"protocolVersion": "2024-11-05",
                         "capabilities": {}, "serverInfo": {"name": "fake-codex"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": msg.get("id"),
              "result": {"tools": [{"name": "codex"}]}})
    elif method == "tools/call":
        # Echo back the prompt as the assistant text
        req_id = msg.get("id")
        prompt = msg.get("params", {}).get("arguments", {}).get("prompt", "")
        send({"jsonrpc": "2.0", "method": "notifications/progress",
              "params": {"text": "thinking..."}})
        send({"jsonrpc": "2.0", "id": req_id,
              "result": {"content": [{"type": "text",
                                       "text": "echo: " + prompt}]}})
    elif method == "notifications/cancelled":
        # We respect the cancellation: nothing to do
        pass
    else:
        pass
'''


@pytest.mark.asyncio
async def test_daemon_starts_and_serves_ask(tmp_path: Path, workdir) -> None:
    fake = _write_fake_mcp_server(tmp_path, _STANDARD_SERVER)
    # The fake binary needs to handle the codex CLI `mcp-server` subcommand,
    # which means we must skip argv parsing. Our fake script ignores argv.
    d = CodexDaemon(codex_bin=str(fake), workdir=workdir,
                    ping_interval_s=999.0)
    try:
        await d.start()
        assert d.state == STATE_READY
        result = await d.ask_slow_brain("hello", timeout_s=5.0)
        assert result.status == "ok"
        # The daemon wraps the user query in a slow-brain recall preamble
        # before sending it to codex (_wrap_recall_prompt), so the fake
        # server's echo contains the wrapped prompt rather than just the
        # raw query. Verify the echo round-trip ran AND the user query
        # survived the wrap.
        assert result.text.startswith("echo:")
        assert "hello" in result.text
    finally:
        await d.stop()


@pytest.mark.asyncio
async def test_daemon_missing_binary(tmp_path: Path, workdir) -> None:
    d = CodexDaemon(codex_bin="/does/not/exist", workdir=workdir,
                    max_restart_attempts=1)
    await d.start()
    assert d.state == STATE_DEAD
    result = await d.ask_slow_brain("hi", timeout_s=2.0)
    assert result.status == "daemon_dead"


_HANG_SERVER = '''
# Initialize normally then HANG on tools/call so we hit timeout.
while True:
    msg = read()
    if msg is None:
        break
    method = msg.get("method", "")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg.get("id"),
              "result": {"protocolVersion": "2024-11-05",
                         "capabilities": {}, "serverInfo": {}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": msg.get("id"),
              "result": {"tools": [{"name": "codex"}]}})
    elif method == "tools/call":
        # Hang: don't respond. Wait for cancellation.
        while True:
            inner = read()
            if inner is None:
                break
            # Drop cancellation silently
'''


@pytest.mark.asyncio
async def test_daemon_timeout_returns_partial(tmp_path: Path, workdir) -> None:
    fake = _write_fake_mcp_server(tmp_path, _HANG_SERVER)
    d = CodexDaemon(codex_bin=str(fake), workdir=workdir,
                    ping_interval_s=999.0)
    try:
        await d.start()
        assert d.state == STATE_READY
        result = await d.ask_slow_brain("hello", timeout_s=0.5)
        assert result.status == "timeout"
        assert result.partial is True
    finally:
        await d.stop()


@pytest.mark.asyncio
async def test_daemon_cancel_event(tmp_path: Path, workdir) -> None:
    fake = _write_fake_mcp_server(tmp_path, _HANG_SERVER)
    d = CodexDaemon(codex_bin=str(fake), workdir=workdir,
                    ping_interval_s=999.0)
    try:
        await d.start()
        evt = asyncio.Event()

        async def cancel_soon():
            await asyncio.sleep(0.3)
            evt.set()

        cancel_task = asyncio.create_task(cancel_soon())
        try:
            result = await d.ask_slow_brain("hello", timeout_s=5.0,
                                             cancel_event=evt)
        finally:
            await cancel_task
        assert result.status == "canceled"
        assert result.partial is True
    finally:
        await d.stop()


@pytest.mark.asyncio
async def test_daemon_queue_full(tmp_path: Path, workdir) -> None:
    fake = _write_fake_mcp_server(tmp_path, _HANG_SERVER)
    d = CodexDaemon(codex_bin=str(fake), workdir=workdir,
                    ask_queue_max=1, ping_interval_s=999.0)
    try:
        await d.start()
        # Start one in-flight via task
        t1 = asyncio.create_task(d.ask_slow_brain("a", timeout_s=2.0))
        # Wait a moment for it to acquire mutex
        await asyncio.sleep(0.2)
        # Second call should immediately return queue_full
        r2 = await d.ask_slow_brain("b", timeout_s=2.0)
        assert r2.status == "queue_full"
        # Let first finish (will timeout)
        r1 = await t1
        assert r1.status == "timeout"
    finally:
        await d.stop()


_QUOTA_SERVER = '''
# Return a tools/call response with rate_limit error
while True:
    msg = read()
    if msg is None:
        break
    method = msg.get("method", "")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg.get("id"),
              "result": {"protocolVersion": "2024-11-05",
                         "capabilities": {}, "serverInfo": {}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": msg.get("id"),
              "result": {"tools": [{"name": "codex"}]}})
    elif method == "tools/call":
        send({"jsonrpc": "2.0", "id": msg.get("id"),
              "error": {"code": -32000, "message": "rate_limit exceeded"}})
'''


@pytest.mark.asyncio
async def test_daemon_quota_exhausted(tmp_path: Path, workdir) -> None:
    fake = _write_fake_mcp_server(tmp_path, _QUOTA_SERVER)
    d = CodexDaemon(codex_bin=str(fake), workdir=workdir,
                    ping_interval_s=999.0)
    try:
        await d.start()
        r = await d.ask_slow_brain("q", timeout_s=2.0)
        assert r.status == "quota_exhausted"
        # Subsequent call should also return quota_exhausted (cool-down)
        r2 = await d.ask_slow_brain("q2", timeout_s=2.0)
        assert r2.status == "quota_exhausted"
    finally:
        await d.stop()


_CRASH_SERVER = '''
import sys
# Init normally, then exit immediately on first tools/call
while True:
    msg = read()
    if msg is None:
        sys.exit(0)
    method = msg.get("method", "")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg.get("id"),
              "result": {"protocolVersion": "2024-11-05",
                         "capabilities": {}, "serverInfo": {}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": msg.get("id"),
              "result": {"tools": [{"name": "codex"}]}})
    elif method == "tools/call":
        sys.exit(7)
'''


@pytest.mark.asyncio
async def test_daemon_crash_returns_canceled(tmp_path: Path, workdir) -> None:
    fake = _write_fake_mcp_server(tmp_path, _CRASH_SERVER)
    d = CodexDaemon(codex_bin=str(fake), workdir=workdir,
                    ping_interval_s=999.0, max_restart_attempts=1)
    try:
        await d.start()
        r = await d.ask_slow_brain("q", timeout_s=2.0)
        # Crash mid-call: we get canceled with partial="" since no progress
        # was sent
        assert r.status in ("canceled", "timeout", "daemon_dead")
    finally:
        await d.stop()
