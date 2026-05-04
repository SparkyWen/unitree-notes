"""Conversation state machine: gates Realtime input by a wake word.

States:
  IDLE              wake-word detector active; uplink disabled.
  AWAKE             transient (next async tick); wake just fired and we
                    are about to start capturing.
  CAPTURING         uplink enabled; utterance VAD running on each chunk;
                    wake detector paused (we already know we're talking).
  THINKING          utterance committed; waiting for first audio delta.
  SPEAKING          model is replying. Wake-word match is the only thing
                    that can interrupt.
  LISTENING_WINDOW  short post-reply window where speaking again does not
                    require a wake word.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "IDLE"
    AWAKE = "AWAKE"
    CAPTURING = "CAPTURING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    LISTENING_WINDOW = "LISTENING_WINDOW"


@dataclass
class ConversationConfig:
    listening_window_s: float = 8.0
    no_speech_timeout_s: float = 4.0


class ConversationStateMachine:
    def __init__(
        self,
        cfg: ConversationConfig,
        wake_word,
        utterance_vad,
        realtime_agent,
        mic=None,
    ):
        self.cfg = cfg
        self.wake_word = wake_word
        self.vad = utterance_vad
        self.agent = realtime_agent
        self.mic = mic
        self._state = State.IDLE
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._mic_queue: Optional[asyncio.Queue] = None
        self._mic_task: Optional[asyncio.Task] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._capture_started_at: float = 0.0
        self._stopped = False

    # ---- public lifecycle ---------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self.agent.set_uplink_enabled(False)
        if self.mic is not None:
            self._mic_queue = self.mic.subscribe()
            self._mic_task = asyncio.create_task(self._consume_mic(), name="sm-mic")
        self.wake_word.resume()
        self.wake_word.start()

    async def stop(self) -> None:
        self._stopped = True
        if self._timer_task is not None:
            self._timer_task.cancel()
        if self._mic_task is not None:
            self._mic_task.cancel()
            try:
                await self._mic_task
            except (asyncio.CancelledError, BaseException):
                pass
        try:
            self.wake_word.stop()
        except Exception:
            pass

    @property
    def state(self) -> State:
        return self._state

    # ---- callbacks ----------------------------------------------------------

    def handle_wake(self, evt) -> None:
        """Called by WakeWordDetector from its worker thread."""
        if self._loop is None or self._stopped:
            return
        self._loop.call_soon_threadsafe(self._on_wake_in_loop, evt)

    def handle_response_done(self) -> None:
        if self._loop is None or self._stopped:
            return
        self._loop.call_soon_threadsafe(self._on_response_done_in_loop)

    def handle_response_audio_delta(self) -> None:
        if self._loop is None or self._stopped:
            return
        self._loop.call_soon_threadsafe(self._on_response_audio_delta_in_loop)

    # ---- in-loop handlers ---------------------------------------------------

    def _on_wake_in_loop(self, evt) -> None:
        log.info("[wake] %s (state=%s)", evt.text, self._state.value)
        if self._state in (State.SPEAKING, State.THINKING):
            asyncio.create_task(self._cancel_then_capture())
            return
        if self._state in (State.IDLE, State.LISTENING_WINDOW):
            self._enter_capturing()
            return
        # CAPTURING / AWAKE: ignore (already / about to be capturing).

    async def _cancel_then_capture(self) -> None:
        try:
            await self.agent.cancel_response()
        finally:
            self._enter_capturing()

    def _on_response_audio_delta_in_loop(self) -> None:
        if self._state == State.THINKING:
            self._set_state(State.SPEAKING)

    def _on_response_done_in_loop(self) -> None:
        if self._state in (State.SPEAKING, State.THINKING):
            self._enter_listening_window()

    # ---- audio path ---------------------------------------------------------

    async def _consume_mic(self) -> None:
        while not self._stopped:
            try:
                chunk = await self._mic_queue.get()
            except asyncio.CancelledError:
                return
            self._on_audio_chunk(chunk)

    def _on_audio_chunk(self, chunk: bytes) -> None:
        try:
            self.wake_word.feed(chunk)
        except Exception:
            log.exception("wake_word.feed raised")
        if self._state == State.CAPTURING:
            status = self.vad.process(chunk)
            if status in ("commit_silence", "commit_max"):
                log.info("[utterance] %s after %.2fs",
                         status, time.monotonic() - self._capture_started_at)
                self._enter_thinking()

    # ---- transitions --------------------------------------------------------

    def _set_state(self, new: State) -> None:
        if self._state == new:
            return
        log.info("[state] %s -> %s", self._state.value, new.value)
        self._state = new

    def _force_state(self, new: State) -> None:
        """Test-only hook to drop into a state without going through the graph."""
        self._set_state(new)

    def _enter_capturing(self) -> None:
        self._set_state(State.CAPTURING)
        self.wake_word.pause()
        self.vad.reset()
        self.agent.set_uplink_enabled(True)
        self._capture_started_at = time.monotonic()
        self._reset_timer(self.cfg.no_speech_timeout_s, self._no_speech_timeout_cb)

    def _no_speech_timeout_cb(self) -> None:
        if self._state != State.CAPTURING:
            return
        if self.vad.had_any_voice():
            return  # voice was heard; the silence-commit path will handle it
        log.info("[capture] no speech for %.1fs after wake; aborting",
                 self.cfg.no_speech_timeout_s)
        self.agent.set_uplink_enabled(False)
        self.wake_word.resume()
        self._set_state(State.IDLE)

    def _enter_thinking(self) -> None:
        self._cancel_timer()
        self.agent.set_uplink_enabled(False)
        self.wake_word.resume()
        self._set_state(State.THINKING)
        asyncio.create_task(self.agent.commit_and_respond())

    def _enter_listening_window(self) -> None:
        self._set_state(State.LISTENING_WINDOW)
        self._reset_timer(self.cfg.listening_window_s, self._listening_window_cb)

    def _listening_window_cb(self) -> None:
        if self._state == State.LISTENING_WINDOW:
            self._set_state(State.IDLE)

    def _reset_timer(self, delay_s: float, cb) -> None:
        self._cancel_timer()

        async def _runner():
            try:
                await asyncio.sleep(delay_s)
                cb()
            except asyncio.CancelledError:
                pass

        self._timer_task = asyncio.create_task(_runner(), name="sm-timer")

    def _cancel_timer(self) -> None:
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None
