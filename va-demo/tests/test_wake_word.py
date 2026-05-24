"""Unit tests for WakeWordDetector with a fake whisper backend."""
from __future__ import annotations

import math
import struct
import sys
import time
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.spoken_cache import SpokenTranscriptCache
from va_demo.wake_word import WakeEvent, WakeWordDetector

SR = 24000


def loud_audio_chunk(ms: int = 500) -> bytes:
    n = int(SR * ms / 1000)
    samples = [int(8000 * math.sin(2 * math.pi * 220 * i / SR)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


def quiet_audio_chunk(ms: int = 500) -> bytes:
    n = int(SR * ms / 1000)
    return b"\x00\x00" * n


class FakeBackend:
    """Returns scripted transcripts in order; one per transcribe() call."""

    def __init__(self, scripted: List[str]):
        self._scripted = list(scripted)
        self.calls = 0

    def transcribe(self, pcm: bytes, samplerate: int) -> str:
        self.calls += 1
        if self._scripted:
            return self._scripted.pop(0)
        return ""


def _make_detector(scripted, **overrides):
    cache = overrides.pop("cache", SpokenTranscriptCache())
    received: List[WakeEvent] = []
    backend = FakeBackend(scripted)
    detector = WakeWordDetector(
        backend=backend,
        spoken_cache=cache,
        on_wake=received.append,
        samplerate=SR,
        rolling_window_s=overrides.get("rolling_window_s", 1.0),
        inference_rate_hz=overrides.get("inference_rate_hz", 50.0),
        rms_threshold=overrides.get("rms_threshold", 1000),
        cooldown_s=overrides.get("cooldown_s", 0.05),
        phrases=overrides.get("phrases", ["hi sparky", "hey sparky"]),
        selfecho_window_s=overrides.get("selfecho_window_s", 6.0),
    )
    return detector, backend, received, cache


def _drive(detector, n_chunks: int = 5, chunk: bytes | None = None):
    chunk = chunk if chunk is not None else loud_audio_chunk(500)
    detector.start()
    try:
        for _ in range(n_chunks):
            detector.feed(chunk)
            time.sleep(0.05)
        time.sleep(0.3)  # let worker drain
    finally:
        detector.stop()


def test_match_fires_on_phrase():
    d, _, received, _ = _make_detector(scripted=["hi sparky"])
    _drive(d)
    assert len(received) >= 1
    assert "hi sparky" in received[0].text.lower()


def test_no_match_does_not_fire():
    d, _, received, _ = _make_detector(scripted=["the weather is nice"])
    _drive(d)
    assert received == []


def test_rms_gate_blocks_quiet_audio():
    d, _, received, _ = _make_detector(scripted=["hi sparky"], rms_threshold=10000)
    _drive(d, chunk=quiet_audio_chunk(500))
    assert received == []


def test_cooldown_throttles_repeats():
    d, _, received, _ = _make_detector(
        scripted=["hi sparky", "hi sparky", "hi sparky"], cooldown_s=10.0
    )
    _drive(d, n_chunks=8)
    assert len(received) == 1


def test_selfecho_dedup_blocks_match():
    cache = SpokenTranscriptCache()
    cache.add("Hi Sparky here, how can I help?")
    d, _, received, _ = _make_detector(scripted=["hi sparky"], cache=cache)
    _drive(d)
    assert received == []


def test_pause_resume_skips_inference():
    d, backend, received, _ = _make_detector(scripted=["hi sparky", "hi sparky"])
    d.start()
    try:
        d.pause()
        for _ in range(5):
            d.feed(loud_audio_chunk(500))
            time.sleep(0.05)
        time.sleep(0.3)
        calls_paused = backend.calls
        d.resume()
        for _ in range(5):
            d.feed(loud_audio_chunk(500))
            time.sleep(0.05)
        time.sleep(0.3)
    finally:
        d.stop()
    assert calls_paused == 0
    assert backend.calls > 0


def test_phrase_match_normalizes_punctuation():
    d, _, received, _ = _make_detector(scripted=["Hi, Sparky!"])
    _drive(d)
    assert len(received) >= 1


# ---- AEC subtraction ------------------------------------------------------
#
# These exercise the path that fixes operator-reported "Hi Sparky can't
# interrupt during long replies". Without AEC, the wake-word transcribe
# during SPEAKING returns the bot's own narration (echoed via the mic)
# and the user's "Hi Sparky" never matches. With AEC, the speaker bytes
# are subtracted from the mic snapshot before transcribe — we can verify
# the subtraction by capturing whatever bytes the backend actually sees.


class _CapturingBackend:
    """Records every (pcm, samplerate) the wake loop passes to transcribe."""

    def __init__(self, transcript: str = "hi sparky"):
        self._transcript = transcript
        self.received: List[bytes] = []

    def transcribe(self, pcm: bytes, samplerate: int) -> str:
        self.received.append(pcm)
        return self._transcript


class _StubSpeakerRef:
    """Minimal stand-in for audio_io.SpeakerStream.recent_played_pcm.

    Always returns the same bytes regardless of window_s/delay_s. That
    matches how the real SpeakerStream behaves once steady-state playback
    fills its 3 s pcm history; tests don't need the timing nuance.
    """

    def __init__(self, pcm: bytes):
        self._pcm = pcm
        self.calls: List[float] = []

    def recent_played_pcm(self, window_s: float, *, delay_s: float = 0.0) -> bytes:
        self.calls.append(window_s)
        return self._pcm


def test_aec_subtract_no_op_without_speaker_ref():
    """gain=0 OR speaker_ref=None must pass mic bytes through unchanged."""
    backend = _CapturingBackend("hi sparky")
    cache = SpokenTranscriptCache()
    received: List[WakeEvent] = []
    d = WakeWordDetector(
        backend=backend, spoken_cache=cache, on_wake=received.append,
        samplerate=SR, rolling_window_s=1.0, inference_rate_hz=50.0,
        rms_threshold=1000, cooldown_s=0.05,
        phrases=["hi sparky"],
        speaker_ref=None, aec_gain=0.8, aec_delay_s=0.2,
    )
    chunk = loud_audio_chunk(500)
    _drive(d, n_chunks=5, chunk=chunk)
    assert backend.received, "expected at least one transcribe call"
    # No speaker_ref → snapshot passed through verbatim.
    assert backend.received[0][:200] == chunk[:200]


def test_aec_subtract_runs_when_wired():
    """Speaker pcm gets subtracted from mic snapshot; cleaned bytes differ."""
    backend = _CapturingBackend("hi sparky")
    cache = SpokenTranscriptCache()
    received: List[WakeEvent] = []
    # Speaker plays a different waveform from the mic; subtraction should
    # change the bytes the backend sees.
    mic_chunk = loud_audio_chunk(500)
    spk_pcm = struct.pack(
        f"<{len(mic_chunk)//2}h",
        *[int(7000 * math.sin(2 * math.pi * 440 * i / SR))
          for i in range(len(mic_chunk)//2)],
    )
    spk_ref = _StubSpeakerRef(spk_pcm)
    d = WakeWordDetector(
        backend=backend, spoken_cache=cache, on_wake=received.append,
        samplerate=SR, rolling_window_s=1.0, inference_rate_hz=50.0,
        rms_threshold=1000, cooldown_s=0.05,
        phrases=["hi sparky"],
        speaker_ref=spk_ref, aec_gain=1.0, aec_delay_s=0.0,
    )
    _drive(d, n_chunks=5, chunk=mic_chunk)
    assert backend.received, "expected at least one transcribe call"
    cleaned = backend.received[0]
    # End-aligned subtraction: tail bytes must differ from the raw mic.
    # (Front may or may not — depends on whether the speaker pcm covered
    # the full snapshot. With our stub it does, so the whole snapshot
    # differs.)
    assert cleaned != mic_chunk
    assert spk_ref.calls, "AEC path didn't query recent_played_pcm"


def test_aec_robust_to_speaker_ref_exception():
    """Backend.transcribe must still see SOME bytes if AEC blows up."""
    backend = _CapturingBackend("hi sparky")

    class _BrokenRef:
        def recent_played_pcm(self, window_s, *, delay_s=0.0):
            raise RuntimeError("boom")

    cache = SpokenTranscriptCache()
    received: List[WakeEvent] = []
    d = WakeWordDetector(
        backend=backend, spoken_cache=cache, on_wake=received.append,
        samplerate=SR, rolling_window_s=1.0, inference_rate_hz=50.0,
        rms_threshold=1000, cooldown_s=0.05,
        phrases=["hi sparky"],
        speaker_ref=_BrokenRef(), aec_gain=1.0, aec_delay_s=0.0,
    )
    chunk = loud_audio_chunk(500)
    _drive(d, n_chunks=5, chunk=chunk)
    assert backend.received, "AEC exception must NOT silence the wake path"
    # Falls back to raw mic on exception.
    assert backend.received[0][:200] == chunk[:200]
