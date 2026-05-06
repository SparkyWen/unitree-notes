"""State machine tests with mocked components."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from va_demo.conversation_state import (
    ConversationConfig,
    ConversationStateMachine,
    State,
)
from va_demo.wake_word import WakeEvent


class FakeWake:
    def __init__(self):
        self.paused = False
        self.fed = bytearray()
        self.started = 0
        self.stopped = 0

    def start(self): self.started += 1
    def stop(self): self.stopped += 1
    def pause(self): self.paused = True
    def resume(self): self.paused = False
    def feed(self, b): self.fed.extend(b)


class FakeVAD:
    def __init__(self, scripted_returns):
        self.scripted = list(scripted_returns)
        self.had_voice_value = True
        self.reset_calls = 0
        # Optional script of had_voice_value to apply after each .process(),
        # so tests can model "voice arrives mid-window" without monkey-patching.
        self.voice_after_process: list[bool] = []

    def reset(self):
        self.reset_calls += 1

    def had_any_voice(self):
        return self.had_voice_value

    def process(self, chunk):
        ret = "continue"
        if self.scripted:
            ret = self.scripted.pop(0)
        if self.voice_after_process:
            self.had_voice_value = self.voice_after_process.pop(0)
        return ret


class FakeAgent:
    def __init__(self):
        self.commit_calls = 0
        self.cancel_calls = 0
        self.uplink_states: list[bool] = []

    async def commit_and_respond(self):
        self.commit_calls += 1

    async def cancel_response(self):
        self.cancel_calls += 1

    def set_uplink_enabled(self, b: bool):
        self.uplink_states.append(b)


class FakeSpeaker:
    """Minimal speaker stub: lets tests script when the buffer is "drained"."""
    def __init__(self, pending: int = 0):
        self.pending = pending

    def pending_bytes(self) -> int:
        return self.pending


def _make_sm(vad_returns=None, speaker=None, **cfg_overrides):
    cfg = ConversationConfig(
        listening_window_s=cfg_overrides.get("listening_window_s", 0.2),
        no_speech_timeout_s=cfg_overrides.get("no_speech_timeout_s", 0.2),
        lw_drain_threshold_bytes=cfg_overrides.get("lw_drain_threshold_bytes", 2400),
        lw_drain_max_wait_s=cfg_overrides.get("lw_drain_max_wait_s", 1.0),
    )
    wake = FakeWake()
    vad = FakeVAD(vad_returns or [])
    agent = FakeAgent()
    sm = ConversationStateMachine(
        cfg=cfg,
        wake_word=wake,
        utterance_vad=vad,
        realtime_agent=agent,
        speaker=speaker,
    )
    return sm, wake, vad, agent


async def test_starts_in_idle_with_uplink_off():
    sm, wake, vad, agent = _make_sm()
    await sm.start()
    try:
        assert sm.state == State.IDLE
        assert agent.uplink_states[-1] is False
        assert wake.started == 1
        assert wake.paused is False
    finally:
        await sm.stop()


async def test_wake_transitions_to_capturing():
    sm, wake, vad, agent = _make_sm(vad_returns=["continue"])
    await sm.start()
    try:
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.05)
        assert sm.state == State.CAPTURING
        assert agent.uplink_states[-1] is True
        assert wake.paused
        assert vad.reset_calls >= 1
    finally:
        await sm.stop()


async def test_silence_commits_and_goes_to_thinking():
    sm, wake, vad, agent = _make_sm(vad_returns=["continue", "commit_silence"])
    await sm.start()
    try:
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.02)
        sm._on_audio_chunk(b"\x00\x01" * 240)
        sm._on_audio_chunk(b"\x00\x01" * 240)
        await asyncio.sleep(0.05)
        assert agent.commit_calls == 1
        assert sm.state == State.THINKING
        assert agent.uplink_states[-1] is False
        # Wake stays paused through THINKING/SPEAKING so the model's own
        # speaker output cannot be misheard as the wake phrase mid-reply.
        assert wake.paused is True
    finally:
        await sm.stop()


async def test_no_speech_after_wake_returns_to_idle():
    sm, wake, vad, agent = _make_sm(
        vad_returns=["continue"] * 50, no_speech_timeout_s=0.15
    )
    vad.had_voice_value = False
    await sm.start()
    try:
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.4)  # > no_speech_timeout_s
        assert sm.state == State.IDLE
        assert agent.commit_calls == 0
        assert not wake.paused
    finally:
        await sm.stop()


async def test_response_done_enters_listening_window_then_idle():
    sm, wake, vad, agent = _make_sm(listening_window_s=0.15)
    await sm.start()
    try:
        sm._force_state(State.SPEAKING)
        wake.paused = True  # mirror real flow: paused since CAPTURING/THINKING
        sm.handle_response_done()
        await asyncio.sleep(0.02)
        assert sm.state == State.LISTENING_WINDOW
        # Detector must be active again so the user can wake on the next turn.
        assert wake.paused is False
        await asyncio.sleep(0.3)
        assert sm.state == State.IDLE
    finally:
        await sm.stop()


async def test_wake_during_speaking_is_ignored():
    """Barge-in via wake word is disabled by design: model speech plays through."""
    sm, wake, vad, agent = _make_sm()
    await sm.start()
    try:
        sm._force_state(State.SPEAKING)
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.05)
        assert agent.cancel_calls == 0
        assert sm.state == State.SPEAKING
    finally:
        await sm.stop()


async def test_wake_during_thinking_is_ignored():
    sm, wake, vad, agent = _make_sm()
    await sm.start()
    try:
        sm._force_state(State.THINKING)
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.05)
        assert agent.cancel_calls == 0
        assert sm.state == State.THINKING
    finally:
        await sm.stop()


async def test_audio_delta_in_thinking_flips_to_speaking():
    sm, wake, vad, agent = _make_sm()
    await sm.start()
    try:
        sm._force_state(State.THINKING)
        sm.handle_response_audio_delta()
        await asyncio.sleep(0.02)
        assert sm.state == State.SPEAKING
    finally:
        await sm.stop()


async def test_listening_window_voice_engages_capturing_without_wake():
    """Follow-up speech in LISTENING_WINDOW must transition straight to CAPTURING.

    This is the user-visible fix: after the model finishes replying, the user
    should be able to keep talking without re-saying "Hi Sparky".
    """
    sm, wake, vad, agent = _make_sm(listening_window_s=2.0)
    vad.had_voice_value = False
    vad.voice_after_process = [True]  # first chunk: voice detected
    await sm.start()
    try:
        sm._force_state(State.SPEAKING)
        sm.handle_response_done()
        # No speaker injected → arm task skips drain wait and arms immediately.
        await asyncio.sleep(0.05)
        assert sm._lw_followup_armed
        sm._on_audio_chunk(b"\x01\x02" * 100)
        await asyncio.sleep(0.02)
        assert sm.state == State.CAPTURING
        assert agent.uplink_states[-1] is True
        assert wake.paused
    finally:
        await sm.stop()


async def test_listening_window_waits_for_speaker_drain_before_arming():
    """While the speaker is still draining the model's TTS audio, follow-up
    VAD must NOT be armed — otherwise the model's own voice echoes back into
    the mic and re-triggers CAPTURING immediately.
    """
    speaker = FakeSpeaker(pending=100_000)  # ≈2 s of 24 kHz int16 mono
    sm, wake, vad, agent = _make_sm(
        listening_window_s=5.0,
        lw_drain_threshold_bytes=2400,
        lw_drain_max_wait_s=2.0,
        speaker=speaker,
    )
    vad.had_voice_value = False
    await sm.start()
    try:
        sm._force_state(State.SPEAKING)
        sm.handle_response_done()
        await asyncio.sleep(0.15)
        assert sm.state == State.LISTENING_WINDOW
        assert not sm._lw_followup_armed  # speaker still has audio
        speaker.pending = 0
        await asyncio.sleep(0.15)
        assert sm._lw_followup_armed
    finally:
        await sm.stop()


async def test_listening_window_falls_back_to_idle_without_followup():
    """If no follow-up voice arrives, LISTENING_WINDOW still times out to IDLE."""
    sm, wake, vad, agent = _make_sm(listening_window_s=0.15)
    vad.had_voice_value = False
    await sm.start()
    try:
        sm._force_state(State.SPEAKING)
        sm.handle_response_done()
        await asyncio.sleep(0.3)
        assert sm.state == State.IDLE
        assert not sm._lw_followup_armed  # cleared on timeout
    finally:
        await sm.stop()


async def test_wake_in_listening_window_cancels_arm_task():
    """A wake-word fire while LISTENING_WINDOW is still waiting for drain
    should still drop us into CAPTURING and abandon the arm task cleanly.
    """
    speaker = FakeSpeaker(pending=100_000)  # never drains in this test
    sm, wake, vad, agent = _make_sm(
        listening_window_s=5.0, lw_drain_max_wait_s=5.0, speaker=speaker,
    )
    await sm.start()
    try:
        sm._force_state(State.SPEAKING)
        sm.handle_response_done()
        await asyncio.sleep(0.05)
        assert sm.state == State.LISTENING_WINDOW
        assert not sm._lw_followup_armed
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.05)
        assert sm.state == State.CAPTURING
        assert sm._lw_arm_task is None
        assert not sm._lw_followup_armed
    finally:
        await sm.stop()
