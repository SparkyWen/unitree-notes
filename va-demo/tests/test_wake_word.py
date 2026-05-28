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


# ---- peak sub-window RMS gate ----------------------------------------------
#
# Regression for operator-reported "Hi Sparky 偶尔能唤醒，绝大部分时候是无法唤醒".
# Root cause: the raw RMS gate averaged over the FULL rolling_window (e.g. 1.5 s)
# diluted a short utterance ("Hi Sparky" ≈ 500-700 ms) so a conversation-volume
# wake phrase often failed the gate even though its speech segment alone was
# well above threshold. The fix gates on the peak RMS of a short sub-window
# slid across the snapshot — the transcribe input is still the full window
# (so the ASR sees full context), but the gate now answers "is there a chunk
# of real speech anywhere in the buffer?" instead of "is the whole buffer
# averaged loud?".


def conversational_voice_chunk(ms: int = 500, amplitude: int = 565) -> bytes:
    """500 ms of 220 Hz sine — RMS = amplitude/sqrt(2). amplitude=565 → RMS≈400,
    typical desk-mic conversation volume (Hi Sparky said normally).
    """
    n = int(SR * ms / 1000)
    samples = [int(amplitude * math.sin(2 * math.pi * 220 * i / SR)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


def test_short_utterance_at_end_of_window_passes_gate():
    """A 500ms conversation-volume wake phrase preceded by 1s of silence in a
    1.5s window MUST pass a 300-threshold gate. The full-window average is
    diluted (RMS≈400 × sqrt(1/3) ≈ 230 < 300) but the peak sub-window sees the
    real ~400 RMS of the speech. Pre-fix this was the "Hi Sparky 偶尔能唤醒"
    case — operator's normal voice averaged below the gate ~2/3 of the time.
    """
    backend = _CapturingBackend("hi sparky")
    cache = SpokenTranscriptCache()
    received: List[WakeEvent] = []
    silence = quiet_audio_chunk(1000)
    voice = conversational_voice_chunk(500, amplitude=565)  # RMS ≈ 400
    d = WakeWordDetector(
        backend=backend, spoken_cache=cache, on_wake=received.append,
        samplerate=SR, rolling_window_s=1.5, inference_rate_hz=50.0,
        rms_threshold=300, cooldown_s=0.05,
        phrases=["hi sparky"],
    )
    d.start()
    try:
        d.feed(silence)
        d.feed(voice)
        time.sleep(0.3)  # let worker drain
    finally:
        d.stop()
    assert backend.received, (
        "conversation-volume utterance at end of window must clear the gate "
        "(peak sub-window RMS, not full-window average)"
    )
    assert received, "wake should fire on short utterance"


def test_peak_gate_still_rejects_long_low_level_noise():
    """Stationary background noise below threshold (RMS ~150) must NOT pass
    even though it fills the whole window — peak sub-window RMS is also low.
    """
    backend = _CapturingBackend("hi sparky")
    cache = SpokenTranscriptCache()
    received: List[WakeEvent] = []
    # Pure tone at amplitude 200 → RMS = 200/sqrt(2) ≈ 141, well below
    # threshold=300. Fills the whole window so window-RMS and peak-sub-RMS
    # both ≈ 141. Gate must block.
    n = int(SR * 1.5)
    noise = struct.pack(
        f"<{n}h",
        *[int(200 * math.sin(2 * math.pi * 220 * i / SR)) for i in range(n)],
    )
    d = WakeWordDetector(
        backend=backend, spoken_cache=cache, on_wake=received.append,
        samplerate=SR, rolling_window_s=1.5, inference_rate_hz=50.0,
        rms_threshold=300, cooldown_s=0.05,
        phrases=["hi sparky"],
    )
    d.start()
    try:
        d.feed(noise)
        time.sleep(0.3)
    finally:
        d.stop()
    assert backend.received == [], (
        f"low-level stationary noise must NOT trip the gate; got {len(backend.received)} calls"
    )
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


# ---- worker liveness heartbeat --------------------------------------------
#
# agent_main gates the "say Hi Sparky" banner on worker_healthy() so the
# banner never prints while the worker thread is starved of the GIL by the
# boot-time perception/codex load (the reported "stuck at READY, wake does
# nothing"). These lock the heartbeat semantics.


def test_worker_healthy_false_before_start():
    d, _, _, _ = _make_detector(scripted=[])
    assert d.worker_healthy() is False  # no ticks recorded yet


def test_worker_healthy_true_once_thread_runs():
    d, _, _, _ = _make_detector(scripted=[], inference_rate_hz=50.0)
    d.start()
    try:
        time.sleep(0.3)  # ~15 ticks at 50 Hz
        assert d.worker_healthy() is True
    finally:
        d.stop()


def test_worker_healthy_requires_sustained_ticking():
    # At 2 Hz the health window spans a few periods; a worker that ticked only
    # twice (GIL-starved) is below min_ticks and reports unhealthy, while a
    # worker that ticked several times recently reports healthy.
    d, _, _, _ = _make_detector(scripted=[], inference_rate_hz=2.0)
    now = time.monotonic()
    with d._tick_lock:
        d._tick_times.extend([now - 1.0, now - 0.5])
    assert d.worker_healthy() is False
    with d._tick_lock:
        d._tick_times.extend([now - 0.4, now - 0.3, now - 0.2])
    assert d.worker_healthy() is True


# ---- OpenAI backend fail-fast timeout -------------------------------------
#
# Regression for the field-observed "stuck, can't wake up": the wake loop is
# single-threaded and calls backend.transcribe() synchronously. The OpenAI SDK
# default is read=600 s with 2 retries, so ONE hung request (server never sends
# response headers / half-open TCP) freezes wake-word detection for up to ~10
# min. py-spy caught the worker parked in ssl.read inside transcribe() for >9
# min. The backend must construct its client with a small bounded timeout and
# zero retries so a stalled call raises promptly; _loop already catches the
# exception and resumes on the next iteration.


def test_openai_backend_bounds_timeout_and_disables_retries(monkeypatch):
    openai = __import__("pytest").importorskip("openai")
    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", _FakeClient)
    from va_demo.wake_word import OpenAITranscribeBackend

    OpenAITranscribeBackend(timeout_s=5.0)

    # Retries disabled: a hung call must not be multiplied by SDK retries.
    assert captured.get("max_retries") == 0
    # Timeout bounded and small (not the 600 s default) so the single worker
    # thread can't be frozen for minutes on one stalled request.
    assert captured.get("timeout") == 5.0


def test_openai_backend_default_timeout_is_bounded(monkeypatch):
    openai = __import__("pytest").importorskip("openai")
    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", _FakeClient)
    from va_demo.wake_word import OpenAITranscribeBackend

    OpenAITranscribeBackend()  # no explicit timeout

    to = captured.get("timeout")
    assert to is not None, "default must set an explicit (bounded) timeout"
    assert float(to) <= 30.0, f"default timeout {to!r} is too close to the 600 s SDK default"
    assert captured.get("max_retries") == 0


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


# ---- cleaned-RMS gate -----------------------------------------------------
#
# Regression for operator-reported "Hi Sparky misses on the first attempt
# during TTS, second attempt interrupts". Root cause: during SPEAKING the
# raw mic is always above `rms_threshold` (the bot's own echo) so every
# loop iteration sends a synchronous OpenAI transcribe — most return the
# bot's narration and the worker thread is blocked on those when the
# user actually says the wake phrase, dropping the user's voice into the
# NEXT iteration's window. The post-AEC gate skips iterations where the
# cleaned signal is dominated by AEC residual (i.e. no user voice
# survived the subtraction), so each network round-trip lands on a
# snapshot the user actually spoke into.


def test_cleaned_rms_gate_skips_silent_speaker_residual():
    """Cleaned RMS below threshold → no transcribe call.

    Simulates the silent-user-during-SPEAKING case: mic captures only
    the bot's echo (≈ speaker output), AEC subtracts it nearly to zero,
    cleaned signal is small. The gate must skip — otherwise the worker
    thread burns a network round-trip on a bot-only snapshot.

    Note: AEC end-aligns the speaker bytes against the LAST n samples of
    the mic snapshot. The rolling window in this test is 1.0 s so the
    stub speaker pcm must also span that window for the residual to be
    near-zero across the whole snapshot.
    """
    backend = _CapturingBackend("hi sparky")
    cache = SpokenTranscriptCache()
    received: List[WakeEvent] = []
    # Mic == speaker, both spanning the full rolling window — AEC will
    # cancel to near zero everywhere.
    mic_chunk = loud_audio_chunk(500)
    spk_full_window = loud_audio_chunk(1000)
    spk_ref = _StubSpeakerRef(spk_full_window)
    d = WakeWordDetector(
        backend=backend, spoken_cache=cache, on_wake=received.append,
        samplerate=SR, rolling_window_s=1.0, inference_rate_hz=50.0,
        rms_threshold=1000, cooldown_s=0.05,
        phrases=["hi sparky"],
        speaker_ref=spk_ref, aec_gain=1.0, aec_delay_s=0.0,
        cleaned_rms_threshold=500.0,
    )
    _drive(d, n_chunks=5, chunk=mic_chunk)
    # AEC asked for speaker bytes (it ran), but the cleaned signal was
    # near-silence so the gate blocked every transcribe call.
    assert spk_ref.calls, "AEC path should have queried speaker history"
    assert backend.received == [], (
        "cleaned RMS gate should have skipped all transcribes; "
        f"got {len(backend.received)} calls"
    )
    assert received == [], "no wake events should fire"


def test_cleaned_rms_gate_passes_when_user_voice_survives():
    """User voice (uncorrelated with speaker) → gate passes → wake fires.

    The complementary case to the test above: the user is actually
    speaking, so the cleaned signal still has loud audio after AEC
    (user voice doesn't correlate with the speaker bytes). Gate must
    let the transcribe through and the wake event must fire.
    """
    backend = _CapturingBackend("hi sparky")
    cache = SpokenTranscriptCache()
    received: List[WakeEvent] = []
    mic_chunk = loud_audio_chunk(500)
    # Speaker pcm is silent — AEC subtracts ~0, cleaned == mic == loud.
    spk_ref = _StubSpeakerRef(quiet_audio_chunk(500))
    d = WakeWordDetector(
        backend=backend, spoken_cache=cache, on_wake=received.append,
        samplerate=SR, rolling_window_s=1.0, inference_rate_hz=50.0,
        rms_threshold=1000, cooldown_s=0.05,
        phrases=["hi sparky"],
        speaker_ref=spk_ref, aec_gain=1.0, aec_delay_s=0.0,
        cleaned_rms_threshold=500.0,
    )
    _drive(d, n_chunks=5, chunk=mic_chunk)
    assert backend.received, "user-voice case must NOT be gated out"
    assert received, "wake should fire on user-voice case"


def test_cleaned_rms_gate_disabled_by_default():
    """threshold=0 must preserve pre-fix behaviour bit-for-bit.

    Existing call sites that don't opt in to the gate must continue to
    behave exactly as before (every raw-RMS-passing iteration produces
    a transcribe call). This is what keeps `va-demo` (which doesn't
    wire the gate) and the older tests on the same code path.
    """
    backend = _CapturingBackend("hi sparky")
    cache = SpokenTranscriptCache()
    received: List[WakeEvent] = []
    mic_chunk = loud_audio_chunk(500)
    spk_ref = _StubSpeakerRef(mic_chunk)  # perfect echo, would gate at >0
    d = WakeWordDetector(
        backend=backend, spoken_cache=cache, on_wake=received.append,
        samplerate=SR, rolling_window_s=1.0, inference_rate_hz=50.0,
        rms_threshold=1000, cooldown_s=0.05,
        phrases=["hi sparky"],
        speaker_ref=spk_ref, aec_gain=1.0, aec_delay_s=0.0,
        # threshold not passed → defaults to 0 → gate disabled
    )
    _drive(d, n_chunks=5, chunk=mic_chunk)
    assert backend.received, (
        "with gate disabled, every raw-RMS-passing iteration must transcribe"
    )
