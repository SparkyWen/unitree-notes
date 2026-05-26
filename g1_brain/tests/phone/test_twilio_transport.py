"""Tests for phone.twilio_transport — Twilio Media Streams protocol adapter.

We don't run a real Twilio. We pretend to be Twilio by feeding the
transport synthesized events through a FakeWS.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest

from g1_brain.phone.twilio_transport import (
    TwilioMediaStreamTransport,
    StartEvent,
    TwilioStreamClosed,
)


class FakeWS:
    """Mimics the slice of aiohttp.WebSocketResponse the transport uses."""
    def __init__(self, inbound: list[str]):
        self._inbound = list(inbound)
        self.outbound: list[str] = []
        self.closed = False

    async def receive_json(self):
        if not self._inbound:
            # mimic ws.receive() returning a close
            raise asyncio.CancelledError()
        return json.loads(self._inbound.pop(0))

    async def send_str(self, s: str):
        self.outbound.append(s)

    async def close(self):
        self.closed = True


def _media_event(stream_sid: str, payload_b64: str) -> str:
    return json.dumps({
        "event": "media",
        "media": {"track": "inbound", "payload": payload_b64},
        "streamSid": stream_sid,
    })


@pytest.mark.asyncio
async def test_start_returns_parsed_start_event():
    start = {
        "event": "start",
        "streamSid": "MZ1",
        "start": {
            "streamSid": "MZ1", "callSid": "CA1",
            "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            "customParameters": {"brain_session_id": "bsid-1"},
        },
    }
    inbound_event = {
        "event": "start", "start": start["start"], "streamSid": "MZ1",
    }
    # Twilio always sends "connected" first
    connected = {"event": "connected", "protocol": "Call", "version": "1.0.0"}
    ws = FakeWS([json.dumps(connected), json.dumps(inbound_event)])
    transport = TwilioMediaStreamTransport(ws)
    se = await transport.start()
    assert isinstance(se, StartEvent)
    assert se.stream_sid == "MZ1"
    assert se.call_sid == "CA1"
    assert se.brain_session_id == "bsid-1"
    assert se.from_number is None or se.from_number == ""  # may not be in customParameters


@pytest.mark.asyncio
async def test_iter_inbound_yields_pcm24k_chunks():
    # 160 B μ-law (20 ms) per frame, three frames
    mu = base64.b64encode(b"\x7f" * 160).decode()
    events = [
        json.dumps({"event": "connected"}),
        json.dumps({"event": "start", "streamSid": "MZ1",
                    "start": {"streamSid": "MZ1", "callSid": "CA1",
                              "tracks": ["inbound"],
                              "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                              "customParameters": {"brain_session_id": "x"}}}),
        _media_event("MZ1", mu),
        _media_event("MZ1", mu),
        _media_event("MZ1", mu),
    ]
    ws = FakeWS(events)
    transport = TwilioMediaStreamTransport(ws)
    await transport.start()

    chunks = []
    async def collect():
        async for chunk in transport.iter_inbound_pcm24k():
            chunks.append(chunk)
    try:
        await asyncio.wait_for(collect(), timeout=0.5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    # 3 inbound frames × 960 B PCM24k each
    assert sum(len(c) for c in chunks) == 3 * 960


class ClosingWS:
    """Mimics aiohttp: receive_json() raises TypeError on a CLOSE frame.

    aiohttp's WebSocketResponse.receive_json -> receive_str raises
    `TypeError("Received message 257:None is not WSMsgType.TEXT")` when the
    peer closed (257 == WSMsgType.CLOSED). We reproduce that exact behaviour.
    """
    def __init__(self, frames_before_close: list[str] | None = None):
        self._frames = list(frames_before_close or [])
        self.closed = False

    async def receive_json(self):
        if self._frames:
            return json.loads(self._frames.pop(0))
        raise TypeError("Received message 257:None is not WSMsgType.TEXT")

    async def send_str(self, s: str):
        pass

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_start_raises_typed_error_when_twilio_closes_immediately():
    # Twilio upgraded then dropped the WS before sending 'connected' (31901).
    ws = ClosingWS([])
    transport = TwilioMediaStreamTransport(ws)
    with pytest.raises(TwilioStreamClosed):
        await transport.start()


@pytest.mark.asyncio
async def test_start_raises_typed_error_when_closed_after_connected():
    ws = ClosingWS([json.dumps({"event": "connected"})])
    transport = TwilioMediaStreamTransport(ws)
    with pytest.raises(TwilioStreamClosed):
        await transport.start()


@pytest.mark.asyncio
async def test_iter_inbound_ends_cleanly_on_midcall_close():
    # 'connected' + 'start', one media frame, then a CLOSE frame.
    mu = base64.b64encode(b"\x7f" * 160).decode()
    frames = [
        json.dumps({"event": "connected"}),
        json.dumps({"event": "start", "streamSid": "MZ1",
                    "start": {"streamSid": "MZ1", "callSid": "CA1",
                              "customParameters": {}}}),
        _media_event("MZ1", mu),
    ]
    ws = ClosingWS(frames)
    transport = TwilioMediaStreamTransport(ws)
    await transport.start()
    chunks = []
    # Must return (not raise) when the CLOSE frame arrives after the media.
    async for chunk in transport.iter_inbound_pcm24k():
        chunks.append(chunk)
    assert sum(len(c) for c in chunks) == 960  # one 20 ms frame decoded


@pytest.mark.asyncio
async def test_send_outbound_pcm24k_emits_media_events():
    ws = FakeWS([])
    transport = TwilioMediaStreamTransport(ws)
    transport._stream_sid = "MZ1"   # bypass start for this test
    # 250 ms PCM24k = 12 000 B → ~12 frames of μ-law (160 B each)
    pcm = b"\x00\x10" * 6000  # 12 000 bytes
    await transport.send_outbound_pcm24k(pcm)
    # outbound events
    assert len(ws.outbound) >= 11
    for s in ws.outbound:
        evt = json.loads(s)
        assert evt["event"] == "media"
        assert evt["streamSid"] == "MZ1"
        assert "payload" in evt["media"]
        assert len(base64.b64decode(evt["media"]["payload"])) == 160


@pytest.mark.asyncio
async def test_clear_outbound_sends_clear_event():
    ws = FakeWS([])
    transport = TwilioMediaStreamTransport(ws)
    transport._stream_sid = "MZ1"
    await transport.clear_outbound()
    assert len(ws.outbound) == 1
    evt = json.loads(ws.outbound[0])
    assert evt == {"event": "clear", "streamSid": "MZ1"}
