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


def test_speaker_recent_played_rms_reflects_callback(monkeypatch):
    """SpeakerStream.recent_played_rms must read from the playback callback,
    not from the write buffer — that's the contract the brain's echo-aware
    barge-in relies on. With a 24 kHz int16 mono signal of amplitude A, the
    RMS of a chunk shipped to the device should be ≈ A."""
    import numpy as np

    fake_sd = types.SimpleNamespace(
        RawInputStream=lambda **kw: types.SimpleNamespace(
            start=lambda: None, stop=lambda: None, close=lambda: None
        ),
        RawOutputStream=lambda **kw: types.SimpleNamespace(
            start=lambda: None, stop=lambda: None, close=lambda: None
        ),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    from va_demo.audio_io import SpeakerStream

    sp = SpeakerStream(samplerate=24000)
    # Before any callback fires, RMS is 0.
    assert sp.recent_played_rms(0.2) == 0.0

    # Synthesise a 20 ms block (default blocksize) of amplitude 2000.
    n = sp._blocksize
    sig = np.full(n, 2000, dtype=np.int16)
    out_buf = bytearray(n * sp.bytes_per_sample)
    # Pre-fill the playback buffer with the signal, then ask the callback
    # to consume it — the callback writes into outdata AND updates the
    # played-RMS history.
    sp.write(sig.tobytes())
    sp._callback(out_buf, n, time_info=None, status=None)

    # The played RMS should be the signal RMS (≈ 2000 for constant amp).
    measured = sp.recent_played_rms(0.5)
    assert 1900 <= measured <= 2100

    # Drop the rolling window below the chunk's age — RMS should reset to 0.
    sp._played_rms_window_s = 0.0
    sp._callback(out_buf, n, time_info=None, status=None)
    # Force-flush via a zero-window query.
    import time as _t
    _t.sleep(0.001)
    assert sp.recent_played_rms(0.0) == 0.0


def test_speaker_sanity_cap_not_hit_for_long_normal_responses(monkeypatch):
    """Long Realtime replies (Chinese narration, ~60 s of TTS streamed
    in <1 s) used to trip the 60 s SANITY_CAP and produce audible drops.
    The cap is now 600 s; queueing 90 s of audio must NOT drop a byte."""
    fake_sd = types.SimpleNamespace(
        RawOutputStream=lambda **kw: types.SimpleNamespace(
            start=lambda: None, stop=lambda: None, close=lambda: None
        ),
        RawInputStream=lambda **kw: types.SimpleNamespace(
            start=lambda: None, stop=lambda: None, close=lambda: None
        ),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    from va_demo.audio_io import SpeakerStream

    sp = SpeakerStream(samplerate=24000)
    # 90 seconds of audio queued in one shot.
    ninety_seconds = b"\x01\x00" * (24000 * 90)
    sp.write(ninety_seconds)
    assert sp.pending_bytes() == len(ninety_seconds)
    assert sp.pending_seconds() == 90.0
