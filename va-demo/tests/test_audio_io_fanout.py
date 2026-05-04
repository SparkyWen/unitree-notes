"""Smoke test for MicStream subscribe() / unsubscribe() fan-out (no real device)."""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_subscribe_returns_independent_queues(monkeypatch):
    fake_sd = types.SimpleNamespace(
        RawInputStream=lambda **kw: types.SimpleNamespace(
            start=lambda: None, stop=lambda: None, close=lambda: None
        ),
        RawOutputStream=lambda **kw: types.SimpleNamespace(
            start=lambda: None, stop=lambda: None, close=lambda: None
        ),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    from va_demo.audio_io import MicStream

    async def go():
        mic = MicStream(samplerate=24000, block_ms=50)
        mic.loop = asyncio.get_event_loop()
        q1 = mic.queue  # legacy alias = first listener
        q2 = mic.subscribe()
        mic._enqueue_nowait(b"\x00\x01" * 240)
        c1 = await asyncio.wait_for(q1.get(), timeout=0.5)
        c2 = await asyncio.wait_for(q2.get(), timeout=0.5)
        assert c1 == c2 == b"\x00\x01" * 240
        mic.unsubscribe(q2)
        mic._enqueue_nowait(b"\x02\x02" * 240)
        c1 = await asyncio.wait_for(q1.get(), timeout=0.5)
        assert c1 == b"\x02\x02" * 240
        assert q2.qsize() == 0

    asyncio.run(go())
