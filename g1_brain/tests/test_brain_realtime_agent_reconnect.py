"""Tests for BrainRealtimeAgent.run() keepalive tuning + auto-reconnect.

Regression for the 2026-05-27 field crash. A single ~30 s tool dispatch
(vision-risk gate ~18 s + operator y/N confirm + walk ~6 s) runs *inline* in
the downlink coroutine while the WS used the websockets-library default 20 s
ping_timeout. The keepalive pong was not serviced within 20 s (long dispatch
+ GIL starvation from in-process perception), so websockets closed the socket
with ``1011 keepalive ping timeout``. The unhandled re-raise in
_downlink → run() then propagated out of ``brain_agent.run()`` and the WHOLE
agent shut down mid-conversation ("shutting down ...").

The fix lives in BrainRealtimeAgent.run() (va-demo is intentionally left
unmodified — we override):
  1. open the WS with a generous ping_timeout so a long-but-healthy dispatch
     can't trip a spurious keepalive close, and
  2. reconnect the Realtime session in place on a transient drop instead of
     letting it tear the agent down; fire on_reconnect so the state machine
     can reset to IDLE.
"""
from __future__ import annotations

import asyncio
import sys

import pytest

_VA = "/home/helios/unitree/unitree-notes/va-demo"
if _VA not in sys.path:
    sys.path.insert(0, _VA)

import websockets  # noqa: E402
from websockets.exceptions import WebSocketException  # noqa: E402

import g1_brain.brain.realtime_agent as ra  # noqa: E402
from g1_brain.brain.realtime_agent import BrainRealtimeAgent  # noqa: E402


# ----------------------------------------------------------------- stubs ----

class _StubSpeaker:
    def write(self, data):
        pass

    def clear(self):
        pass


class _StubMic:
    queue = None

    def subscribe(self):
        return asyncio.Queue()


class _StubSafety:
    async def validate(self, name, args):
        return True, "", args


class _StubSkillServer:
    async def execute(self, name, args, *, call_id: str = ""):
        return {"ok": True}


class _FakeWS:
    """Stands in for a websockets connection: awaitable-returned object that
    is also an async context manager and accepts .send()."""

    def __init__(self):
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, raw):
        self.sent.append(raw)

    async def close(self):
        pass


def _make_agent():
    return BrainRealtimeAgent(
        api_key="sk-test",
        model="test-model",
        voice="verse",
        mic=_StubMic(),
        speaker=_StubSpeaker(),
        camera=None,
        vision=None,
        tts=None,
        skills=None,
        safety=_StubSafety(),
        skill_server=_StubSkillServer(),
    )


def _patch_connect(monkeypatch):
    """Patch websockets.connect to capture kwargs and hand back a fresh FakeWS.

    Returns the list that accumulates the per-connect kwargs dicts.
    """
    seen = []

    async def _fake_connect(url, **kwargs):
        seen.append(kwargs)
        return _FakeWS()

    monkeypatch.setattr(websockets, "connect", _fake_connect)
    return seen


# ---------------------------------------------------------------- tests ----

@pytest.mark.asyncio
async def test_connect_uses_generous_ping_timeout(monkeypatch):
    """The WS must be opened with a ping_timeout far larger than the
    websockets default 20 s, so a long tool dispatch can't trip a spurious
    keepalive close."""
    seen = _patch_connect(monkeypatch)
    agent = _make_agent()

    # First (and only) session ends gracefully so run() returns.
    async def _uplink(ws):
        await asyncio.sleep(3600)

    async def _downlink(ws):
        return

    agent._uplink = _uplink
    agent._downlink = _downlink

    await asyncio.wait_for(agent.run(), timeout=5.0)

    assert seen, "websockets.connect was never called"
    kwargs = seen[0]
    assert "ping_timeout" in kwargs
    # Comfortably beyond the worst-case dispatch (vision ~30 s + confirm 60 s
    # + turn 14 s ≈ 104 s). The exact value is a knob, but it must be >> 20 s.
    assert kwargs["ping_timeout"] is None or kwargs["ping_timeout"] >= 120.0


@pytest.mark.asyncio
async def test_transient_drop_reconnects_and_fires_on_reconnect(monkeypatch):
    """A WebSocket drop must reconnect in place (not propagate) and fire
    on_reconnect exactly once so the state machine can reset to IDLE."""
    monkeypatch.setattr(ra, "_RECONNECT_BACKOFF_S", 0.0)
    seen = _patch_connect(monkeypatch)
    agent = _make_agent()

    reconnects = []
    agent.on_reconnect = lambda: reconnects.append(1)

    sessions = {"n": 0}

    async def _uplink(ws):
        await asyncio.sleep(3600)

    async def _downlink(ws):
        sessions["n"] += 1
        if sessions["n"] == 1:
            # First session: simulate the keepalive close.
            raise WebSocketException("simulated 1011 keepalive ping timeout")
        # Second session: graceful end so run() returns.
        return

    agent._uplink = _uplink
    agent._downlink = _downlink

    await asyncio.wait_for(agent.run(), timeout=5.0)

    assert len(seen) == 2, f"expected 2 connects (initial + reconnect), got {len(seen)}"
    # on_reconnect fires on the SECOND session only — not the first connect.
    assert reconnects == [1]


@pytest.mark.asyncio
async def test_gives_up_after_max_consecutive_failures(monkeypatch):
    """If every session drops immediately, run() must eventually give up and
    re-raise (falling through to the normal shutdown) rather than reconnect
    forever."""
    monkeypatch.setattr(ra, "_RECONNECT_BACKOFF_S", 0.0)
    monkeypatch.setattr(ra, "_MAX_RECONNECT_ATTEMPTS", 3)
    seen = _patch_connect(monkeypatch)
    agent = _make_agent()

    async def _uplink(ws):
        await asyncio.sleep(3600)

    async def _downlink(ws):
        raise WebSocketException("always drops")

    agent._uplink = _uplink
    agent._downlink = _downlink

    with pytest.raises(WebSocketException):
        await asyncio.wait_for(agent.run(), timeout=5.0)

    # initial attempt + _MAX_RECONNECT_ATTEMPTS retries.
    assert len(seen) == 1 + 3


@pytest.mark.asyncio
async def test_cancellation_propagates_cleanly(monkeypatch):
    """Shutdown cancels run(); CancelledError must propagate (not be swallowed
    into a reconnect) so the agent exits cleanly on Ctrl-C / signal."""
    _patch_connect(monkeypatch)
    agent = _make_agent()

    async def _uplink(ws):
        await asyncio.sleep(3600)

    async def _downlink(ws):
        await asyncio.sleep(3600)

    agent._uplink = _uplink
    agent._downlink = _downlink

    task = asyncio.create_task(agent.run())
    await asyncio.sleep(0.05)  # let it connect and start the session
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
