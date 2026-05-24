"""Twilio Media Streams WebSocket protocol adapter.

Wraps an aiohttp WebSocketResponse and presents:
  - await start() -> StartEvent      (after consuming connected + start)
  - async for chunk in iter_inbound_pcm24k(): ...
  - await send_outbound_pcm24k(pcm)
  - await clear_outbound()
  - await close()

Audio is transcoded through StreamingResampler — Twilio sees μ-law/8k,
the rest of the brain sees PCM16/24k.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from .audio_codec import StreamingResampler


log = logging.getLogger(__name__)


@dataclass
class StartEvent:
    stream_sid: str
    call_sid: str
    brain_session_id: str
    from_number: Optional[str] = None
    to_number: Optional[str] = None


class TwilioMediaStreamTransport:
    """One instance per WS connection / one phone call."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._stream_sid: Optional[str] = None
        self._inbound_resampler = StreamingResampler()
        self._outbound_resampler = StreamingResampler()
        self._closed = False

    async def start(self) -> StartEvent:
        # The first two events from Twilio are 'connected' then 'start'.
        connected = await self._ws.receive_json()
        if connected.get("event") != "connected":
            raise RuntimeError(f"expected connected, got {connected!r}")
        start = await self._ws.receive_json()
        if start.get("event") != "start":
            raise RuntimeError(f"expected start, got {start!r}")
        s = start["start"]
        self._stream_sid = s["streamSid"]
        custom = s.get("customParameters") or {}
        return StartEvent(
            stream_sid=s["streamSid"],
            call_sid=s["callSid"],
            brain_session_id=custom.get("brain_session_id", ""),
            from_number=custom.get("from") or s.get("from"),
            to_number=custom.get("to") or s.get("to"),
        )

    async def iter_inbound_pcm24k(self) -> AsyncIterator[bytes]:
        """Yield PCM16-24k chunks decoded from Twilio media events.

        Terminates when Twilio sends 'stop' or the WS closes.
        """
        while not self._closed:
            try:
                evt = await self._ws.receive_json()
            except (asyncio.CancelledError, ConnectionResetError):
                return
            t = evt.get("event")
            if t == "media":
                payload = evt.get("media", {}).get("payload", "")
                for chunk in self._inbound_resampler.feed_mulaw8k(payload):
                    yield chunk
            elif t == "stop":
                log.info("twilio.stop received")
                return
            elif t == "mark":
                pass
            else:
                log.debug("twilio.event unknown: %s", t)

    async def send_outbound_pcm24k(self, pcm: bytes) -> None:
        if self._stream_sid is None:
            raise RuntimeError("transport.start() must be awaited first")
        for mu_b64 in self._outbound_resampler.feed_pcm24k(pcm):
            await self._ws.send_str(json.dumps({
                "event": "media",
                "streamSid": self._stream_sid,
                "media": {"payload": mu_b64},
            }))

    async def clear_outbound(self) -> None:
        if self._stream_sid is None:
            return
        await self._ws.send_str(json.dumps({
            "event": "clear",
            "streamSid": self._stream_sid,
        }))
        self._outbound_resampler.reset()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._ws.close()
        except Exception:
            pass
