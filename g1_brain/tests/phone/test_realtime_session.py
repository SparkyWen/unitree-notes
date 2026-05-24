"""Tests for PhoneRealtimeSession — audio source/sink override + end_call tool.

We don't talk to real OpenAI Realtime. We construct the session with
a fake `mic` / `speaker` / `transport` and exercise the override
methods directly.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# va-demo must be on sys.path before importing BrainRealtimeAgent (it
# subclasses va-demo's RealtimeAgent).
_VA = "/home/helios/unitree/unitree-notes/va-demo"
if _VA not in sys.path:
    sys.path.insert(0, _VA)

from g1_brain.phone.realtime_session import PhoneRealtimeSession, END_CALL_SCHEMA


def _make_session(*, transport=None, dialer=None, skill_server=None):
    transport = transport or MagicMock()
    dialer = dialer or MagicMock()
    skill_server = skill_server or MagicMock()
    skill_server.execute = AsyncMock(return_value={"ok": True, "summary": "x"})
    # We need to pass parent-required fields; use bare MagicMocks for the
    # speaker/mic since we override the loops that use them.

    # Safety stub: always approve
    safety = MagicMock()
    safety.validate = AsyncMock(return_value=(True, "", {}))

    return PhoneRealtimeSession(
        api_key="sk-test",
        model="test-model",
        voice="verse",
        mic=MagicMock(),
        speaker=MagicMock(),
        camera=MagicMock(),
        vision=None,
        tts=None,
        skills=None,
        safety=safety,
        skill_server=skill_server,
        scene_bus=MagicMock(),
        transport=transport,
        dialer=dialer,
        call_sid="CA00000000000000000000000000000000",
    )


def test_resolve_instructions_prepends_phone_preamble():
    s = _make_session()
    out = s._resolve_instructions()
    assert "phone call" in out.lower()
    # also contains base brain prompt (asserted by presence of any brain-specific phrase)
    assert "robot" in out.lower() or "sparky" in out.lower()


def test_resolve_tool_schemas_filters_start_phone_call_adds_end_call():
    s = _make_session()
    schemas = s._resolve_tool_schemas()
    names = [t.get("name") for t in schemas]
    assert "end_call" in names
    assert "start_phone_call" not in names


@pytest.mark.asyncio
async def test_execute_tool_end_call_invokes_dialer_hangup():
    dialer = MagicMock()
    dialer.hangup = AsyncMock()
    s = _make_session(dialer=dialer)
    s.call_sid = "CA" + "1" * 32
    result = await s._execute_tool("end_call", {}, call_id="cid")
    assert result["ok"] is True
    dialer.hangup.assert_awaited_once_with("CA" + "1" * 32)


@pytest.mark.asyncio
async def test_execute_tool_routes_other_tools_to_skill_server():
    s = _make_session()
    result = await s._execute_tool("gesture", {"name": "wave_right"}, call_id="cid")
    assert result["ok"] is True
    s.skill_server.execute.assert_awaited()


def test_end_call_schema_shape():
    assert END_CALL_SCHEMA["name"] == "end_call"
    assert END_CALL_SCHEMA["type"] == "function"
    assert "description" in END_CALL_SCHEMA


@pytest.mark.asyncio
async def test_handle_event_audio_delta_routes_to_transport():
    transport = MagicMock()
    transport.send_outbound_pcm24k = AsyncMock()
    s = _make_session(transport=transport)
    # We must call _handle_event with a ws (any object; not used in this branch)
    # The audio delta event carries base64 audio:
    import base64
    payload = base64.b64encode(b"\x00\x01" * 10).decode()
    await s._handle_event(MagicMock(), {"type": "response.output_audio.delta", "delta": payload})
    transport.send_outbound_pcm24k.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_event_speech_started_clears_outbound_and_cancels():
    transport = MagicMock()
    transport.clear_outbound = AsyncMock()
    s = _make_session(transport=transport)
    # patch cancel_in_flight on the instance
    s.cancel_in_flight = AsyncMock()
    # super._handle_event may need a real ws to send to. Stub super's handler:
    import g1_brain.phone.realtime_session as rs_mod
    # Just verify our override side-effects regardless of super
    await s._handle_event(MagicMock(), {"type": "input_audio_buffer.speech_started"})
    transport.clear_outbound.assert_awaited()
    s.cancel_in_flight.assert_awaited()


@pytest.mark.asyncio
async def test_handle_event_unrelated_event_delegates_to_super(monkeypatch):
    s = _make_session()
    super_called = {"yes": False}
    async def fake_super(self_arg, ws, evt):
        super_called["yes"] = True
    # patch parent's _handle_event in the class
    import g1_brain.brain.realtime_agent as bra
    monkeypatch.setattr(bra.BrainRealtimeAgent, "_handle_event", fake_super)
    await s._handle_event(MagicMock(), {"type": "rate_limits.updated"})
    assert super_called["yes"] is True
