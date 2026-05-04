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

    def reset(self):
        self.reset_calls += 1

    def had_any_voice(self):
        return self.had_voice_value

    def process(self, chunk):
        if self.scripted:
            return self.scripted.pop(0)
        return "continue"


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


def _make_sm(vad_returns=None, **cfg_overrides):
    cfg = ConversationConfig(
        listening_window_s=cfg_overrides.get("listening_window_s", 0.2),
        no_speech_timeout_s=cfg_overrides.get("no_speech_timeout_s", 0.2),
    )
    wake = FakeWake()
    vad = FakeVAD(vad_returns or [])
    agent = FakeAgent()
    sm = ConversationStateMachine(
        cfg=cfg,
        wake_word=wake,
        utterance_vad=vad,
        realtime_agent=agent,
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
        assert wake.paused is False  # resumed when entering THINKING
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
        sm.handle_response_done()
        await asyncio.sleep(0.02)
        assert sm.state == State.LISTENING_WINDOW
        await asyncio.sleep(0.3)
        assert sm.state == State.IDLE
    finally:
        await sm.stop()


async def test_wake_during_speaking_cancels_and_recaptures():
    sm, wake, vad, agent = _make_sm()
    await sm.start()
    try:
        sm._force_state(State.SPEAKING)
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.05)
        assert agent.cancel_calls == 1
        assert sm.state == State.CAPTURING
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
