"""Conversation state machine: gates Realtime input by a wake word.

States:
  IDLE              wake-word detector active; uplink disabled.
  AWAKE             transient (next async tick); wake just fired and we
                    are about to start capturing.
  CAPTURING         uplink enabled; utterance VAD running on each chunk;
                    wake detector paused (we already know we're talking).
  THINKING          utterance committed; waiting for first audio delta.
                    Wake detector stays paused.
  SPEAKING          model is replying. Wake detector stays paused so the
                    model's own speaker output (and any room echo) cannot
                    be misheard as a wake phrase mid-reply. The reply is
                    delivered fully; barge-in via wake-word is disabled.
  LISTENING_WINDOW  short post-reply follow-up window. Once the speaker
                    buffer drains (so the model's own TTS audio stops
                    bleeding into the mic), follow-up is "armed":
                      * the wake detector stays resumed (a fresh
                        "Hi Sparky" still works as a fast path), AND
                      * the utterance VAD watches incoming chunks for
                        any voice burst — first voice transitions back
                        to CAPTURING so the user can simply keep talking
                        without re-saying the wake phrase.
                    On no follow-up within listening_window_s, falls
                    back to IDLE.
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
    # While in LISTENING_WINDOW, the model's TTS may still be draining
    # through the speaker. We refuse to arm follow-up VAD until the
    # speaker buffer is below this many bytes — otherwise the model's own
    # audio echoes through the mic and re-engages CAPTURING immediately.
    # ~24 kHz * 2 byte * 0.05 s ≈ 50 ms of residual audio is fine to ignore.
    lw_drain_threshold_bytes: int = 2400
    # Hard cap on how long we'll wait for the speaker to drain before we
    # arm follow-up regardless. Protects against a pathological speaker
    # buffer (or a missing speaker reference) blocking follow-up forever.
    lw_drain_max_wait_s: float = 6.0


class ConversationStateMachine:
    def __init__(
        self,
        cfg: ConversationConfig,
        wake_word,
        utterance_vad,
        realtime_agent,
        mic=None,
        speaker=None,
    ):
        self.cfg = cfg
        self.wake_word = wake_word
        self.vad = utterance_vad
        self.agent = realtime_agent
        self.mic = mic
        self.speaker = speaker
        self._state = State.IDLE
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._mic_queue: Optional[asyncio.Queue] = None
        self._mic_task: Optional[asyncio.Task] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._lw_arm_task: Optional[asyncio.Task] = None
        self._lw_followup_armed: bool = False
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
        if self._lw_arm_task is not None:
            self._lw_arm_task.cancel()
            self._lw_arm_task = None
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
            # Defense in depth: the detector should be paused in these states
            # (see _enter_thinking / _enter_listening_window) but a transcribe
            # already in flight when we paused can still deliver one event.
            # Drop it — barge-in via wake-word is disabled by design now.
            log.debug("ignoring wake during %s (barge-in disabled)", self._state.value)
            return
        if self._state in (State.IDLE, State.LISTENING_WINDOW):
            self._enter_capturing()
            return
        # CAPTURING / AWAKE: ignore (already / about to be capturing).

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
            return
        if self._state == State.LISTENING_WINDOW and self._lw_followup_armed:
            # Watch for follow-up speech so the user can keep talking
            # without re-saying the wake phrase. On the first voiced frame
            # we transition straight to CAPTURING, keeping the VAD context
            # so the silence-commit path still works once the user stops.
            had_voice_before = self.vad.had_any_voice()
            self.vad.process(chunk)
            if not had_voice_before and self.vad.had_any_voice():
                log.info("[lw] follow-up speech detected; engaging CAPTURING")
                self._lw_to_capturing()

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
        self._cancel_lw_arm()
        self._set_state(State.CAPTURING)
        self.wake_word.pause()
        self.vad.reset()
        self.agent.set_uplink_enabled(True)
        self._capture_started_at = time.monotonic()
        self._reset_timer(self.cfg.no_speech_timeout_s, self._no_speech_timeout_cb)

    def _lw_to_capturing(self) -> None:
        """Engage CAPTURING from a follow-up voice burst inside LISTENING_WINDOW.

        Differs from `_enter_capturing` in that the VAD already has accumulated
        voice — we keep its state instead of resetting, so the silence-commit
        path counts elapsed silence from the actual end of the user's speech
        rather than from this transition.
        """
        self._cancel_lw_arm()
        self._cancel_timer()
        self.wake_word.pause()
        self.agent.set_uplink_enabled(True)
        self._set_state(State.CAPTURING)
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
        # Keep wake_word paused through THINKING and SPEAKING so the model's
        # own speaker output cannot be misheard as the wake phrase. The
        # detector resumes when we enter LISTENING_WINDOW.
        self.wake_word.pause()
        self._set_state(State.THINKING)
        asyncio.create_task(self.agent.commit_and_respond())

    def _enter_listening_window(self) -> None:
        self.wake_word.resume()
        self._set_state(State.LISTENING_WINDOW)
        self._lw_followup_armed = False
        # Schedule the follow-up arm task. It waits until the speaker has
        # finished playing the model's reply, then enables the VAD-based
        # follow-up path. Doing it inside an async task (rather than
        # synchronously here) is what lets us drain-wait without blocking
        # the asyncio loop.
        if self._lw_arm_task is not None:
            self._lw_arm_task.cancel()
        self._lw_arm_task = asyncio.create_task(
            self._arm_lw_followup_when_drained(), name="sm-lw-arm"
        )
        self._reset_timer(self.cfg.listening_window_s, self._listening_window_cb)

    async def _arm_lw_followup_when_drained(self) -> None:
        """Wait for the speaker buffer to drain, then arm follow-up VAD.

        Without this gate, the still-playing TTS audio would echo back into
        the mic and re-trigger CAPTURING immediately after the model
        finished speaking. We poll `speaker.pending_bytes()` until it
        drops below `lw_drain_threshold_bytes`, capped by
        `lw_drain_max_wait_s`.
        """
        deadline = time.monotonic() + self.cfg.lw_drain_max_wait_s
        if self.speaker is not None:
            while time.monotonic() < deadline:
                if self._state != State.LISTENING_WINDOW:
                    return  # left LW already (e.g. wake-word fired)
                try:
                    pending = self.speaker.pending_bytes()
                except Exception:
                    pending = 0
                if pending <= self.cfg.lw_drain_threshold_bytes:
                    break
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    return
        if self._state != State.LISTENING_WINDOW:
            return
        # Reset VAD so accumulated silence/echo doesn't immediately
        # commit; from now on the next voiced frame engages CAPTURING.
        self.vad.reset()
        self._lw_followup_armed = True
        log.debug("[lw] follow-up VAD armed")

    def _cancel_lw_arm(self) -> None:
        self._lw_followup_armed = False
        if self._lw_arm_task is not None:
            self._lw_arm_task.cancel()
            self._lw_arm_task = None

    def _listening_window_cb(self) -> None:
        if self._state == State.LISTENING_WINDOW:
            self._cancel_lw_arm()
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
