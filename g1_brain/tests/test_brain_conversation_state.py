"""Tests for BrainConversationStateMachine.

We don't run real wake-word inference, real audio, or a real Realtime WS.
All collaborators are stubbed. The state machine itself owns the
transition logic, so these tests exercise the §2 transition table from
docs/audio-control-update01.md directly.
"""
from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Any, List, Optional

import pytest

# va-demo not strictly required (BrainConversationStateMachine doesn't
# import from it), but keep the path consistent with the rest of g1_brain.
_VA = "/home/helios/unitree/unitree-notes/va-demo"
if _VA not in sys.path:
    sys.path.insert(0, _VA)

from g1_brain.brain.conversation_state import (
    BrainConversationConfig,
    BrainConversationStateMachine,
    State,
)


# ----------------------------------------------------------------- stubs ----

@dataclass
class _StubWakeEvent:
    text: str
    t: float = 0.0


class _StubWakeWord:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.paused = 0
        self.resumed = 0
        self.fed = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def pause(self):
        self.paused += 1

    def resume(self):
        self.resumed += 1

    def feed(self, chunk):
        self.fed += 1


class _StubVAD:
    def __init__(self):
        self._next_status = None
        self._has_voice = False
        self.reset_count = 0
        self.process_count = 0

    def process(self, chunk):
        self.process_count += 1
        s = self._next_status
        self._next_status = None
        return s

    def reset(self):
        self.reset_count += 1
        self._has_voice = False

    def had_any_voice(self):
        return self._has_voice

    # test helpers
    def set_next_status(self, status):
        self._next_status = status


class _StubSpeaker:
    def __init__(self):
        self.cleared = 0
        self._pending = 0
        self._played_rms = 0.0

    def clear(self):
        self.cleared += 1
        self._pending = 0

    def pending_bytes(self):
        return self._pending

    def set_pending(self, n):
        self._pending = n

    # Used by the echo-aware voice-onset barge-in. Tests inject the value
    # they want the predicted-echo subtraction to use.
    def recent_played_rms(self, window_s: float = 0.2) -> float:
        return float(self._played_rms)

    def set_played_rms(self, rms: float) -> None:
        self._played_rms = float(rms)


class _StubMic:
    def __init__(self):
        self.q: asyncio.Queue = asyncio.Queue()

    def subscribe(self):
        return self.q


class _StubAgent:
    """Replaces BrainRealtimeAgent for state-machine tests."""

    def __init__(self):
        self.uplink_enabled: bool = False
        self.uplink_calls: List[bool] = []
        self.commit_calls: int = 0
        self.cancel_calls: int = 0
        self.input_clear_calls: int = 0
        self.reset_plan_calls: int = 0

        # The BrainConversationStateMachine assigns these; we record values so
        # tests can verify wiring (and so simulating events is easy).
        self.on_response_audio_delta = None
        self.on_response_done = None
        self.on_plan_done = None
        self.on_user_transcript = None
        self.on_assistant_transcript_done = None
        self.on_tool_use = None
        self.on_tool_result = None
        self.on_response_canceled = None

    def set_uplink_enabled(self, enabled: bool):
        self.uplink_enabled = enabled
        self.uplink_calls.append(enabled)

    async def commit_and_respond(self):
        self.commit_calls += 1

    async def cancel_in_flight(self):
        self.cancel_calls += 1

    async def input_audio_buffer_clear(self):
        self.input_clear_calls += 1

    def reset_plan_tracker(self):
        self.reset_plan_calls += 1


class _StubLogger:
    """Records every call without writing to disk."""

    def __init__(self):
        self.calls: List[tuple] = []

    def __getattr__(self, name):
        # Return a recorder for any attribute starting with `log_` /
        # `begin_turn` / etc. Tests can introspect self.calls.
        if name.startswith("_"):
            raise AttributeError(name)

        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return _rec

    def names(self):
        return [c[0] for c in self.calls]


# ------------------------------------------------------------- helpers ----

def _make_sm(*, cfg: Optional[BrainConversationConfig] = None,
             stop_skill_callable=None,
             logger=None):
    cfg = cfg or BrainConversationConfig(
        no_speech_timeout_s=0.05,  # short for tests
        barge_in_min_capture_age_s=0.0,  # don't suppress in tests by default
        idle_after_plan_enabled=True,
        drain_threshold_bytes=0,
        drain_max_wait_s=0.2,
        plan_watchdog_s=10.0,
        # Production default is False (operator wants Hi-Sparky-only
        # interrupts); the test suite still needs the path on by default
        # so the voice_barge_in_* tests exercise it. Tests that need it
        # off pass their own cfg with voice_barge_in_enabled=False.
        voice_barge_in_enabled=True,
    )
    sm = BrainConversationStateMachine(
        cfg=cfg,
        wake_word=_StubWakeWord(),
        utterance_vad=_StubVAD(),
        realtime_agent=_StubAgent(),
        mic=_StubMic(),
        speaker=_StubSpeaker(),
        stop_skill_callable=stop_skill_callable,
        logger=logger,
    )
    return sm


async def _start_no_mic_loop(sm):
    """Start sm without spinning up the mic-consume task (we drive
    transitions directly in tests)."""
    sm._loop = asyncio.get_event_loop()
    sm.agent.set_uplink_enabled(False)
    # Replicate start() wiring without launching the mic-consume coroutine.
    sm.agent.on_response_audio_delta = sm._handle_response_audio_delta
    sm.agent.on_response_done = sm._handle_response_done
    sm.agent.on_plan_done = sm._handle_plan_done
    if sm.logger is not None:
        sm.agent.on_user_transcript = sm.logger.log_user_transcript
        sm.agent.on_assistant_transcript_done = sm.logger.log_assistant_transcript
        sm.agent.on_tool_use = sm.logger.log_tool_use
        sm.agent.on_tool_result = sm.logger.log_tool_result
    sm.wake_word.resume()
    sm.wake_word.start()
    sm._set_state(State.IDLE, reason="start")


# ---------------------------------------------------------------- tests ----

@pytest.mark.asyncio
async def test_idle_to_capturing_on_wake():
    sm = _make_sm()
    await _start_no_mic_loop(sm)
    assert sm.state == State.IDLE

    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)  # let call_soon_threadsafe run

    assert sm.state == State.CAPTURING
    assert sm.agent.uplink_enabled is True
    assert sm.vad.reset_count >= 1
    assert sm.agent.reset_plan_calls >= 1


@pytest.mark.asyncio
async def test_capturing_to_thinking_on_vad_commit():
    sm = _make_sm()
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    assert sm.state == State.CAPTURING

    # Simulate the mic feeding a chunk that VAD says completes the utterance.
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)

    assert sm.state == State.THINKING
    assert sm.agent.uplink_enabled is False
    # Allow the commit_and_respond task to run.
    await asyncio.sleep(0)
    assert sm.agent.commit_calls == 1


@pytest.mark.asyncio
async def test_capturing_to_idle_on_no_speech_timeout():
    sm = _make_sm()
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    assert sm.state == State.CAPTURING

    # Wait long enough for the timer (configured to 50 ms in _make_sm).
    await asyncio.sleep(0.2)

    assert sm.state == State.IDLE
    assert sm.agent.uplink_enabled is False


@pytest.mark.asyncio
async def test_thinking_audio_delta_promotes_to_speaking():
    sm = _make_sm()
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    assert sm.state == State.THINKING

    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING


@pytest.mark.asyncio
async def test_plan_done_triggers_drain_then_idle():
    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        idle_after_plan_enabled=True,
        drain_threshold_bytes=10,
        drain_max_wait_s=1.0,
        plan_watchdog_s=10.0,
        barge_in_min_capture_age_s=0.0,
    )
    sm = _make_sm(cfg=cfg)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm.speaker.set_pending(5)  # already below threshold of 10
    sm._handle_plan_done()
    # Give the drain task time to run.
    await asyncio.sleep(0.1)
    assert sm.state == State.IDLE
    assert sm.agent.uplink_enabled is False


@pytest.mark.asyncio
async def test_drain_respects_max_wait_cap():
    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        idle_after_plan_enabled=True,
        drain_threshold_bytes=0,        # would never drain naturally
        drain_max_wait_s=0.1,
        plan_watchdog_s=10.0,
        barge_in_min_capture_age_s=0.0,
    )
    sm = _make_sm(cfg=cfg)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm.speaker.set_pending(99999)  # never drains
    sm._handle_plan_done()
    # After max_wait_s + slack we should still transition.
    await asyncio.sleep(0.3)
    assert sm.state == State.IDLE


@pytest.mark.asyncio
async def test_barge_in_from_speaking_calls_cancel_clear_stop():
    stop_calls = []

    async def stop_fn():
        stop_calls.append(time.monotonic())

    sm = _make_sm(stop_skill_callable=stop_fn)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    # Let the barge-in task finish.
    for _ in range(20):
        await asyncio.sleep(0.01)
        if sm.state == State.CAPTURING:
            break

    assert sm.state == State.CAPTURING
    assert sm.agent.cancel_calls == 1
    assert sm.speaker.cleared >= 1
    assert len(stop_calls) == 1
    assert sm.agent.uplink_enabled is True


@pytest.mark.asyncio
async def test_barge_in_disabled_keeps_state():
    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        barge_in_enabled=False,
        idle_after_plan_enabled=False,
        plan_watchdog_s=10.0,
        barge_in_min_capture_age_s=0.0,
    )
    sm = _make_sm(cfg=cfg)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0.05)

    assert sm.state == State.SPEAKING
    assert sm.agent.cancel_calls == 0


@pytest.mark.asyncio
async def test_barge_in_without_stop_skill_when_flag_off():
    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        barge_in_enabled=True,
        barge_in_also_stop_skills=False,
        idle_after_plan_enabled=False,
        plan_watchdog_s=10.0,
        barge_in_min_capture_age_s=0.0,
    )
    stop_calls = []

    async def stop_fn():
        stop_calls.append(1)

    sm = _make_sm(cfg=cfg, stop_skill_callable=stop_fn)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    for _ in range(20):
        await asyncio.sleep(0.01)
        if sm.state == State.CAPTURING:
            break

    assert sm.state == State.CAPTURING
    assert sm.agent.cancel_calls == 1
    # stop skill flag is off → no stop call.
    assert stop_calls == []


@pytest.mark.asyncio
async def test_capturing_to_capturing_on_mid_utterance_wake():
    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        barge_in_min_capture_age_s=0.0,  # allow immediate restart in test
        idle_after_plan_enabled=False,
        plan_watchdog_s=10.0,
    )
    sm = _make_sm(cfg=cfg)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    initial_capture_started = sm._capture_started_at
    initial_reset_count = sm.vad.reset_count

    # Need a tiny sleep so capture_started_at advances meaningfully.
    await asyncio.sleep(0.01)

    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    for _ in range(20):
        await asyncio.sleep(0.01)
        if sm.agent.input_clear_calls >= 1:
            break

    assert sm.state == State.CAPTURING
    # Mid-capture wake clears server audio buffer + resets VAD.
    assert sm.agent.input_clear_calls == 1
    assert sm.vad.reset_count > initial_reset_count
    # capture timer reset
    assert sm._capture_started_at > initial_capture_started
    # Must NOT call cancel_in_flight or stop_skill (no plan in flight).
    assert sm.agent.cancel_calls == 0


@pytest.mark.asyncio
async def test_wake_within_min_capture_age_is_suppressed():
    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        barge_in_min_capture_age_s=0.5,  # half-second cooldown
        idle_after_plan_enabled=False,
        plan_watchdog_s=10.0,
    )
    sm = _make_sm(cfg=cfg)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    assert sm.state == State.CAPTURING

    # Immediately fire another wake — should be suppressed.
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0.05)

    assert sm.agent.input_clear_calls == 0


@pytest.mark.asyncio
async def test_wake_during_stopped_is_dropped():
    sm = _make_sm()
    await _start_no_mic_loop(sm)
    await sm.stop()
    # After stop, _stopped is True. Further wakes should be no-ops.
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    assert sm.state == State.IDLE


@pytest.mark.asyncio
async def test_wake_during_drain_routes_to_barge_in():
    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        barge_in_min_capture_age_s=0.0,
        idle_after_plan_enabled=True,
        drain_threshold_bytes=0,
        drain_max_wait_s=2.0,  # long enough we can interrupt mid-drain
        plan_watchdog_s=10.0,
    )
    stop_calls = []
    async def stop_fn():
        stop_calls.append(1)

    sm = _make_sm(cfg=cfg, stop_skill_callable=stop_fn)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm.speaker.set_pending(99999)  # never drains
    sm._handle_plan_done()
    await asyncio.sleep(0.05)  # drain task is now in its sleep loop

    # Wake mid-drain — should cancel drain + barge in.
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    for _ in range(40):
        await asyncio.sleep(0.01)
        if sm.state == State.CAPTURING:
            break

    assert sm.state == State.CAPTURING
    assert sm.agent.cancel_calls == 1
    assert len(stop_calls) == 1


@pytest.mark.asyncio
async def test_idle_after_plan_disabled_stays_in_speaking():
    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        barge_in_min_capture_age_s=0.0,
        idle_after_plan_enabled=False,
        plan_watchdog_s=10.0,
    )
    sm = _make_sm(cfg=cfg)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm._handle_plan_done()
    await asyncio.sleep(0.05)
    # Old behaviour: stay in SPEAKING.
    assert sm.state == State.SPEAKING


@pytest.mark.asyncio
async def test_logger_receives_lifecycle_events():
    logger = _StubLogger()
    sm = _make_sm(logger=logger)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    sm._handle_plan_done()
    await asyncio.sleep(0.2)

    names = logger.names()
    assert "log_wake_event" in names
    assert "begin_turn" in names
    assert "log_state_transition" in names
    assert "log_plan_done" in names


@pytest.mark.asyncio
async def test_concurrent_barge_in_serialised():
    """Two wake events fired ~simultaneously while SPEAKING should not
    cause two stop-skill calls. The lock serialises them; the second
    runs after state is already CAPTURING and is treated as
    capture-restart (input_clear) instead."""
    stop_calls = []
    async def stop_fn():
        # slight delay so the second wake can stack up while we're
        # still in the lock-protected path.
        await asyncio.sleep(0.05)
        stop_calls.append(1)

    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        barge_in_min_capture_age_s=0.0,
        idle_after_plan_enabled=False,
        plan_watchdog_s=10.0,
    )
    sm = _make_sm(cfg=cfg, stop_skill_callable=stop_fn)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))

    for _ in range(40):
        await asyncio.sleep(0.01)
        if sm.state == State.CAPTURING and len(stop_calls) >= 1:
            break

    assert sm.state == State.CAPTURING
    # Exactly one barge-in path executed; second wake collapses into
    # capture-restart at most.
    assert len(stop_calls) == 1


# ------------------------- voice-onset barge-in (SPEAKING) ----------------

def _pcm16_chunk(rms_target: float, n_samples: int = 1200) -> bytes:
    """Build a PCM16 mono chunk whose RMS ≈ `rms_target`.

    n_samples=1200 → 50 ms at 24 kHz, matching MicStream block_ms default.
    """
    import numpy as np

    # Constant-amplitude signal: RMS == |A|.
    amp = max(1, int(round(rms_target)))
    arr = np.full(n_samples, amp, dtype=np.int16)
    return arr.tobytes()


@pytest.mark.asyncio
async def test_voice_barge_in_fires_when_user_overrides_echo():
    """Mic clearly louder than predicted speaker echo for a streak fires
    the same barge-in path the wake-word would have."""
    stop_calls = []

    async def stop_fn():
        stop_calls.append(time.monotonic())

    sm = _make_sm(stop_skill_callable=stop_fn)
    await _start_no_mic_loop(sm)
    # Move to SPEAKING.
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    # Predict echo at ~800; user voice rides above echo + margin (350)
    # comfortably. 4 chunks satisfies the default streak.
    sm.speaker.set_played_rms(800.0)
    loud_chunk = _pcm16_chunk(2500.0)
    for _ in range(sm.cfg.voice_barge_in_streak_chunks):
        sm._on_audio_chunk(loud_chunk)

    for _ in range(20):
        await asyncio.sleep(0.01)
        if sm.state == State.CAPTURING:
            break

    assert sm.state == State.CAPTURING
    assert sm.agent.cancel_calls == 1
    assert sm.speaker.cleared >= 1
    assert len(stop_calls) == 1


@pytest.mark.asyncio
async def test_voice_barge_in_silent_under_echo():
    """When the mic only hears the speaker echo (mic_rms ≈ echo_predicted)
    the barge-in must NOT fire, even with a long stream of chunks."""
    sm = _make_sm()
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    # Speaker is loud; mic only catches the echo at roughly the same level.
    sm.speaker.set_played_rms(2000.0)
    echo_only = _pcm16_chunk(2000.0)
    for _ in range(20):
        sm._on_audio_chunk(echo_only)

    await asyncio.sleep(0.02)
    assert sm.state == State.SPEAKING
    assert sm.agent.cancel_calls == 0
    assert sm.speaker.cleared == 0


@pytest.mark.asyncio
async def test_voice_barge_in_requires_streak():
    """A single loud chunk (cough / desk thump / button click) must not
    fire the barge-in — the streak guard exists for exactly this case."""
    sm = _make_sm()
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm.speaker.set_played_rms(0.0)
    loud_chunk = _pcm16_chunk(3000.0)
    # 1 < default streak (4).
    sm._on_audio_chunk(loud_chunk)
    # Quiet again — streak resets.
    quiet_chunk = _pcm16_chunk(100.0)
    sm._on_audio_chunk(quiet_chunk)

    await asyncio.sleep(0.02)
    assert sm.state == State.SPEAKING
    assert sm.agent.cancel_calls == 0


@pytest.mark.asyncio
async def test_voice_barge_in_disabled_by_config():
    """Operator can turn the new path off via config; behaviour collapses
    back to the old wake-word-only barge-in path."""
    cfg = BrainConversationConfig(
        no_speech_timeout_s=10.0,
        barge_in_min_capture_age_s=0.0,
        idle_after_plan_enabled=False,
        plan_watchdog_s=10.0,
        voice_barge_in_enabled=False,
    )
    sm = _make_sm(cfg=cfg)
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    sm.vad.set_next_status("commit_silence")
    sm._on_audio_chunk(b"\x00" * 16)
    sm._handle_response_audio_delta()
    assert sm.state == State.SPEAKING

    sm.speaker.set_played_rms(0.0)
    loud_chunk = _pcm16_chunk(4000.0)
    for _ in range(20):
        sm._on_audio_chunk(loud_chunk)

    await asyncio.sleep(0.02)
    assert sm.state == State.SPEAKING
    assert sm.agent.cancel_calls == 0


@pytest.mark.asyncio
async def test_voice_barge_in_inactive_outside_speaking():
    """Loud mic chunks in CAPTURING must not be routed through the new
    barge-in path (the user is already being captured; nothing to drop)."""
    sm = _make_sm()
    await _start_no_mic_loop(sm)
    sm.handle_wake(_StubWakeEvent(text="hi sparky"))
    await asyncio.sleep(0)
    assert sm.state == State.CAPTURING

    sm.speaker.set_played_rms(0.0)
    loud_chunk = _pcm16_chunk(4000.0)
    # No VAD commit, so we stay in CAPTURING.
    for _ in range(20):
        sm._on_audio_chunk(loud_chunk)

    await asyncio.sleep(0.02)
    assert sm.state == State.CAPTURING
    assert sm.agent.cancel_calls == 0
    assert sm.speaker.cleared == 0
