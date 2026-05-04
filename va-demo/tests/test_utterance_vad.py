"""Unit tests for UtteranceVAD with synthesized PCM and an injected fake VAD.

webrtcvad won't classify pure sine waves as speech (it's tuned for voice
spectra), so we inject a controllable fake. We still smoke-test that real
webrtcvad initializes and accepts our resampled frames at the bottom.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.utterance_vad import UtteranceVAD

SR = 24000


def silence_chunk(ms: int) -> bytes:
    n = int(SR * ms / 1000)
    return b"\x00\x00" * n


def loud_chunk(ms: int) -> bytes:
    n = int(SR * ms / 1000)
    return struct.pack(f"<{n}h", *([12000] * n))


class FakeVad:
    """Records every is_speech call; returns True iff the frame energy is non-zero."""

    def __init__(self):
        self.calls: List[tuple] = []

    def is_speech(self, frame_bytes: bytes, sr: int) -> bool:
        self.calls.append((len(frame_bytes), sr))
        # crude: any non-zero byte → "voice"
        return any(b != 0 for b in frame_bytes)


def _vad(**kw):
    fake = FakeVad()
    inst = UtteranceVAD(samplerate=SR, vad=fake, **kw)
    return inst, fake


def test_continue_when_only_silence_no_voice_yet():
    vad, _ = _vad(silence_threshold_ms=500, max_duration_s=10.0)
    for _ in range(20):
        assert vad.process(silence_chunk(50)) == "continue"


def test_commit_silence_after_voice_then_silence():
    vad, _ = _vad(silence_threshold_ms=500, max_duration_s=10.0)
    for _ in range(4):
        vad.process(loud_chunk(50))
    statuses = [vad.process(silence_chunk(50)) for _ in range(15)]
    assert "commit_silence" in statuses


def test_commit_max_after_long_voice():
    vad, _ = _vad(silence_threshold_ms=10000, max_duration_s=0.5)
    statuses = [vad.process(loud_chunk(50)) for _ in range(20)]
    assert "commit_max" in statuses


def test_had_any_voice_starts_false_then_true():
    vad, _ = _vad(silence_threshold_ms=500, max_duration_s=10.0)
    assert not vad.had_any_voice()
    vad.process(loud_chunk(100))
    assert vad.had_any_voice()


def test_reset_clears_counters():
    vad, _ = _vad(silence_threshold_ms=500, max_duration_s=10.0)
    vad.process(loud_chunk(200))
    for _ in range(15):
        vad.process(silence_chunk(50))
    vad.reset()
    assert not vad.had_any_voice()
    for _ in range(15):
        assert vad.process(silence_chunk(50)) == "continue"


def test_real_webrtcvad_constructs_and_consumes_frames():
    """Smoke test: real webrtcvad processes our resampled frames without raising."""
    real = UtteranceVAD(samplerate=SR, silence_threshold_ms=1500, max_duration_s=30.0)
    # Feed a few hundred ms of silence; should not raise, should report "continue".
    for _ in range(20):
        result = real.process(silence_chunk(50))
        assert result == "continue"


def test_fake_vad_called_with_30ms_16k_frames():
    vad, fake = _vad(silence_threshold_ms=10000, max_duration_s=10.0)
    # Feed 100 ms of audio. Resampled to 16 kHz that's 1600 samples = 3 full
    # 30 ms frames (480 samples each) with a remainder.
    vad.process(loud_chunk(100))
    assert len(fake.calls) >= 3
    for n_bytes, sr in fake.calls:
        assert sr == 16000
        assert n_bytes == 480 * 2  # int16 mono
