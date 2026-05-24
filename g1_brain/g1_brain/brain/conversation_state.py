"""BrainConversationStateMachine — g1_brain's own conversation state machine.

Intentionally separate from va_demo.conversation_state.ConversationStateMachine.
Three behaviours we need that the va-demo CSM does not provide:

1. **Wake-word barge-in works in any state** (SPEAKING, THINKING, even
   mid-CAPTURING). va-demo deliberately disables barge-in during
   SPEAKING/THINKING and pauses the wake detector during CAPTURING.

2. **No mic listening between turns.** va-demo enters a LISTENING_WINDOW
   after each response and arms a follow-up VAD so the user can keep
   talking without saying the wake word again. We drop that entirely:
   plan-end → drain → IDLE; the only re-entry is wake.

3. **Plan-level idle.** A user turn may produce N model responses
   chained by tool calls. We transition out of SPEAKING only after the
   *whole plan* is done (signalled by BrainRealtimeAgent.on_plan_done),
   not after the first response.done.

States: IDLE, CAPTURING, THINKING, SPEAKING. Drain-to-IDLE is an inline
asyncio task, not a separate state.

See docs/audio-control-update01.md.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import numpy as np

log = logging.getLogger(__name__)


def _chunk_rms_int16(chunk: bytes) -> float:
    if not chunk:
        return 0.0
    arr = np.frombuffer(chunk, dtype=np.int16)
    if not arr.size:
        return 0.0
    arrf = arr.astype(np.float32, copy=False)
    return float(np.sqrt(float(np.mean(arrf * arrf))))


class State(enum.Enum):
    IDLE = "IDLE"
    CAPTURING = "CAPTURING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


@dataclass
class BrainConversationConfig:
    # CAPTURING: cap how long we wait without any voice before giving up.
    no_speech_timeout_s: float = 4.0
    # Barge-in
    barge_in_enabled: bool = True
    barge_in_also_stop_skills: bool = True
    # Suppress wake events fired within this many seconds of entering
    # CAPTURING — they are usually echoes of the model's last word
    # bleeding into the new capture window before the wake detector's
    # rolling buffer flushes.
    barge_in_min_capture_age_s: float = 0.4
    # Drain wait after plan_done.
    idle_after_plan_enabled: bool = True
    drain_threshold_bytes: int = 2400
    drain_max_wait_s: float = 6.0
    # Force plan_done if a tool call never resolves.
    plan_watchdog_s: float = 30.0
    # ---- echo-aware voice-onset barge-in (SPEAKING-only) -------------------
    # The wake-word ASR window during SPEAKING is dominated by the bot's own
    # TTS leaking into the mic; "Hi Sparky" rarely survives that. This second
    # barge-in path watches mic RMS, subtracts a prediction of the speaker
    # echo (from SpeakerStream.recent_played_rms), and fires the standard
    # barge-in when user voice clearly rides above the echo for a short
    # streak. Active only in SPEAKING; THINKING/CAPTURING/IDLE still use the
    # regular wake-word path.
    # Off by default: operator wants "Hi Sparky" to be the sole interrupt
    # trigger. An envelope-only path fires on any sustained mic loudness
    # (cough, desk thump, ambient speech), which is exactly the
    # over-sensitive behaviour we are trying to remove. See the
    # `audio_control.voice_barge_in` block in g1_brain.yaml for full
    # rationale and the conditions under which re-enabling makes sense.
    voice_barge_in_enabled: bool = False
    voice_barge_in_echo_gain: float = 1.0          # echo_rms ≈ speaker_rms × this
    voice_barge_in_margin_rms: float = 350.0       # user must exceed echo + margin
    voice_barge_in_min_rms: float = 500.0          # absolute mic floor (silence guard)
    voice_barge_in_streak_chunks: int = 4          # consecutive chunks needed (~200 ms at 50 ms blocks)
    voice_barge_in_speaker_window_s: float = 0.2   # window used to estimate speaker RMS


# Type aliases for clarity.
StopSkillCallable = Callable[[], Awaitable[None]]
LoggerLike = Any  # ConversationLogger; loose to avoid import cycle in tests.


class BrainConversationStateMachine:
    """Drives the voice loop. Talks to BrainRealtimeAgent + WakeWord + VAD.

    The state machine is the single decision point for the audio control
    behaviour described in docs/audio-control-update01.md. It owns the
    transitions; the agent owns plan-tracking and WS control; the wake
    detector + VAD report observations. Logger is informed about anything
    user-visible.
    """

    def __init__(
        self,
        cfg: BrainConversationConfig,
        wake_word,
        utterance_vad,
        realtime_agent,
        mic=None,
        speaker=None,
        stop_skill_callable: Optional[StopSkillCallable] = None,
        logger: Optional[LoggerLike] = None,
    ):
        self.cfg = cfg
        self.wake_word = wake_word
        self.vad = utterance_vad
        self.agent = realtime_agent
        self.mic = mic
        self.speaker = speaker
        self.stop_skill_callable = stop_skill_callable
        self.logger = logger

        self._state = State.IDLE
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._mic_queue: Optional[asyncio.Queue] = None
        self._mic_task: Optional[asyncio.Task] = None

        self._no_speech_timer: Optional[asyncio.Task] = None
        self._drain_task: Optional[asyncio.Task] = None
        self._plan_watchdog_task: Optional[asyncio.Task] = None

        self._capture_started_at: float = 0.0
        self._barge_in_lock = asyncio.Lock()
        self._stopped = False

        # Echo-aware voice-onset barge-in streak counter. Counted in mic
        # chunks; reset to 0 on any state transition out of SPEAKING (so a
        # half-finished streak from the previous turn can't fire mid-IDLE).
        self._voice_bi_streak: int = 0
        self._voice_bi_pending: bool = False

    # ---- public lifecycle ---------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self.agent.set_uplink_enabled(False)
        # Wire ourselves to the agent's plan-tracking + transcript hooks.
        # We do not overwrite on_response_audio_delta/on_response_done
        # because we want to use them for THINKING→SPEAKING transitions.
        self.agent.on_response_audio_delta = self._handle_response_audio_delta
        self.agent.on_response_done = self._handle_response_done
        self.agent.on_plan_done = self._handle_plan_done
        # Logger hooks — only set if a logger is wired.
        if self.logger is not None:
            self.agent.on_user_transcript = self.logger.log_user_transcript
            self.agent.on_assistant_transcript_done = self.logger.log_assistant_transcript
            self.agent.on_tool_use = self.logger.log_tool_use
            self.agent.on_tool_result = self.logger.log_tool_result
            self.agent.on_response_canceled = (
                lambda reason: self.logger.log_response_canceled(reason=reason)
            )

        if self.mic is not None:
            self._mic_queue = self.mic.subscribe()
            self._mic_task = asyncio.create_task(self._consume_mic(), name="bcsm-mic")
        # Wake-word stays on at all times (including CAPTURING) so barge-in
        # works mid-utterance. va-demo paused it in CAPTURING; we don't.
        self.wake_word.resume()
        self.wake_word.start()
        self._set_state(State.IDLE, reason="start")

    async def stop(self) -> None:
        self._stopped = True
        for t in (self._no_speech_timer, self._drain_task, self._plan_watchdog_task):
            if t is not None:
                t.cancel()
        if self._mic_task is not None:
            self._mic_task.cancel()
            try:
                await self._mic_task
            except (asyncio.CancelledError, BaseException):
                pass
        try:
            self.wake_word.stop()
        except Exception:  # noqa: BLE001
            pass

    @property
    def state(self) -> State:
        return self._state

    # ---- callbacks (thread-safe entrypoints) --------------------------------

    def handle_wake(self, evt) -> None:
        """Called by WakeWordDetector from its worker thread."""
        if self._loop is None or self._stopped:
            return
        self._loop.call_soon_threadsafe(self._on_wake_in_loop, evt)

    def _handle_response_audio_delta(self) -> None:
        """Called by BrainRealtimeAgent from the asyncio loop thread."""
        if self._stopped:
            return
        if self._state == State.THINKING:
            self._set_state(State.SPEAKING, reason="audio.delta")

    def _handle_response_done(self) -> None:
        """Called on every response.done, including intermediate ones.

        We deliberately do NOT transition to IDLE here — only on plan_done.
        Kept as a hook for symmetry with va-demo's parent contract; we
        could log it but agent.log already covers this.
        """
        # No state action. The plan may still continue with another response.
        pass

    def _handle_plan_done(self) -> None:
        """Called by BrainRealtimeAgent when the WHOLE turn finishes.

        We transition through the drain-wait task into IDLE.
        """
        if self._stopped:
            return
        if self._state not in (State.THINKING, State.SPEAKING):
            return
        if self.logger is not None:
            try:
                self.logger.log_plan_done()
            except Exception:
                log.exception("logger.log_plan_done raised")
        self._cancel_plan_watchdog()
        if not self.cfg.idle_after_plan_enabled:
            # Operator opted out: stay in SPEAKING; equivalent to old behaviour.
            return
        if self._drain_task is not None:
            self._drain_task.cancel()
        self._drain_task = asyncio.create_task(
            self._drain_to_idle(), name="bcsm-drain",
        )

    # ---- audio path ---------------------------------------------------------

    async def _consume_mic(self) -> None:
        """Forward every mic chunk to wake_word + (in CAPTURING) the VAD."""
        while not self._stopped:
            try:
                chunk = await self._mic_queue.get()
            except asyncio.CancelledError:
                return
            self._on_audio_chunk(chunk)

    def _on_audio_chunk(self, chunk: bytes) -> None:
        # Wake-word always sees the chunk, regardless of state. The cost is a
        # rolling buffer + occasional transcribe call; the upside is wake
        # works in CAPTURING / THINKING / SPEAKING for barge-in.
        try:
            self.wake_word.feed(chunk)
        except Exception:
            log.exception("wake_word.feed raised")
        if self._state == State.CAPTURING:
            status = self.vad.process(chunk)
            if status in ("commit_silence", "commit_max"):
                log.info(
                    "[utterance] %s after %.2fs",
                    status, time.monotonic() - self._capture_started_at,
                )
                self._enter_thinking()
        elif self._state == State.SPEAKING:
            # Echo-aware barge-in. Cheap (one np.frombuffer + one sqrt per
            # ~50 ms mic chunk). See BrainConversationConfig for tunables.
            self._maybe_voice_barge_in(chunk)

    # ---- in-loop wake handler -----------------------------------------------

    def _on_wake_in_loop(self, evt) -> None:
        log.info("[wake] %r (state=%s)", evt.text, self._state.value)
        # Operator-facing print on stdout (the log line above goes to stderr
        # via the StreamHandler and gets buried under DDS / perception /
        # OpenAI INFO noise — operators were reporting the terminal felt
        # "stuck" because there was no clear ack that wake fired). flush=True
        # so the line lands the moment wake is detected, not when the next
        # stdio buffer flush happens.
        print(
            f"\n[g1_brain] wake heard: {evt.text!r} — listening, speak now",
            flush=True,
        )
        if self.logger is not None:
            try:
                self.logger.log_wake_event(evt.text)
            except Exception:
                log.exception("logger.log_wake_event raised")

        if self._state == State.IDLE:
            self._enter_capturing(reason="wake_from_idle")
            return

        if self._state == State.CAPTURING:
            # Mid-utterance "hi sparky" — user wants to redo their input.
            # Suppress if we just entered CAPTURING (echo of model's tail).
            age = time.monotonic() - self._capture_started_at
            if age < self.cfg.barge_in_min_capture_age_s:
                log.debug(
                    "[wake] suppressed (capture_age=%.2fs < %.2fs)",
                    age, self.cfg.barge_in_min_capture_age_s,
                )
                return
            asyncio.create_task(
                self._handle_capture_restart(evt), name="bcsm-cap-restart",
            )
            return

        if self._state in (State.THINKING, State.SPEAKING):
            if not self.cfg.barge_in_enabled:
                log.debug("[wake] barge-in disabled by config; ignoring")
                return
            asyncio.create_task(
                self._handle_barge_in(evt, was_state=self._state),
                name="bcsm-barge-in",
            )
            return

    # ---- transitions --------------------------------------------------------

    def _set_state(self, new: State, *, reason: str = "") -> None:
        if self._state == new:
            return
        log.info("[state] %s -> %s (%s)", self._state.value, new.value, reason)
        if self.logger is not None:
            try:
                self.logger.log_state_transition(
                    from_state=self._state.value, to_state=new.value,
                    reason=reason or None,
                )
            except Exception:
                log.exception("logger.log_state_transition raised")
        self._state = new
        # Voice-onset barge-in streak only makes sense while SPEAKING. Any
        # transition (into SPEAKING from THINKING, or out of SPEAKING) resets
        # it so a leftover partial streak can't fire across boundaries.
        if new != State.SPEAKING:
            self._voice_bi_streak = 0
            self._voice_bi_pending = False
        else:
            # Fresh SPEAKING window — start clean.
            self._voice_bi_streak = 0
            self._voice_bi_pending = False

    def _enter_capturing(self, *, reason: str) -> None:
        # Cancel any pending drain task — wake takes priority.
        self._cancel_drain()
        self._cancel_plan_watchdog()
        self.vad.reset()
        # Reset agent's plan tracker so the next plan starts cleanly.
        try:
            self.agent.reset_plan_tracker()
        except AttributeError:
            pass
        self.agent.set_uplink_enabled(True)
        self._capture_started_at = time.monotonic()
        if self.logger is not None:
            try:
                self.logger.begin_turn()
            except Exception:
                log.exception("logger.begin_turn raised")
            # Memory: capture a turn_start scene snapshot as a keyframe for
            # the memory pipeline. Best-effort; never raise.
            scene_bus = getattr(self.agent, "scene_bus", None)
            if scene_bus is not None and hasattr(self.logger, "log_scene_snapshot"):
                try:
                    self.logger.log_scene_snapshot(
                        trigger="turn_start",
                        scene_state=scene_bus.snapshot(),
                    )
                except Exception:
                    log.exception("logger.log_scene_snapshot raised")
        self._set_state(State.CAPTURING, reason=reason)
        self._reset_no_speech_timer()

    def _enter_thinking(self) -> None:
        self._cancel_no_speech_timer()
        self.agent.set_uplink_enabled(False)
        self._set_state(State.THINKING, reason="vad_commit")
        # Stdout ack so the operator sees the system *did* hear them and is
        # working on a response — without this the terminal sits silent for
        # the full LLM + vision-gate latency window (often >5 s).
        print("[g1_brain] thinking…", flush=True)
        # Arm the plan watchdog so a stuck tool call doesn't trap us in
        # SPEAKING forever.
        self._reset_plan_watchdog()
        asyncio.create_task(self.agent.commit_and_respond(), name="bcsm-commit")

    async def _handle_capture_restart(self, evt) -> None:
        """Mid-capture wake: drop server-side audio, reset VAD, keep CAPTURING."""
        if self._state != State.CAPTURING:
            return
        try:
            await self.agent.input_audio_buffer_clear()
        except Exception:
            log.exception("input_audio_buffer_clear raised")
        self.vad.reset()
        self._capture_started_at = time.monotonic()
        self._reset_no_speech_timer()
        if self.logger is not None:
            try:
                self.logger.log_barge_in(
                    from_state=State.CAPTURING.value, wake_text=evt.text,
                )
            except Exception:
                log.exception("logger.log_barge_in raised")

    async def _handle_barge_in(self, evt, *, was_state: State) -> None:
        """Hard interrupt path: cancel response, stop motion, → CAPTURING."""
        async with self._barge_in_lock:
            # Re-check under lock — a second wake racing this one would have
            # already been consumed when we transitioned to CAPTURING.
            if self._state not in (State.THINKING, State.SPEAKING):
                return

            self._cancel_drain()
            self._cancel_plan_watchdog()

            # 1. tell server to drop in-flight response + uncommitted audio.
            try:
                await self.agent.cancel_in_flight()
            except Exception:
                log.exception("agent.cancel_in_flight raised")

            # 2. drop residual TTS in the local playback buffer.
            try:
                if self.speaker is not None:
                    self.speaker.clear()
            except Exception:
                log.debug("speaker.clear raised", exc_info=True)

            # 3. stop the robot if we asked it to do something.
            if self.cfg.barge_in_also_stop_skills and self.stop_skill_callable is not None:
                try:
                    await asyncio.wait_for(
                        self.stop_skill_callable(), timeout=2.0,
                    )
                except asyncio.TimeoutError:
                    log.warning("stop skill on barge-in timed out")
                except Exception:
                    log.exception("stop skill on barge-in failed")

            # 4. logger.
            if self.logger is not None:
                try:
                    self.logger.log_barge_in(
                        from_state=was_state.value, wake_text=evt.text,
                    )
                except Exception:
                    log.exception("logger.log_barge_in raised")

            # 5. transition into CAPTURING for the new turn.
            self._enter_capturing(reason="barge_in")

    def _maybe_voice_barge_in(self, chunk: bytes) -> None:
        """Echo-aware barge-in trigger that runs only in SPEAKING.

        Why this exists: the wake-word's 1.5 s ASR window is fed every mic
        chunk in all states, but during SPEAKING it is dominated by the
        bot's own TTS leaking back through the mic. The OpenAI transcribe
        call almost always returns the bot's narration text and "hi sparky"
        never appears, so the regular wake path silently fails — exactly
        the user-reported "can't interrupt the robot mid-speech" bug.

        Instead of relying on ASR through the echo, watch the mic RMS
        envelope and subtract a prediction of the speaker echo derived
        from ``SpeakerStream.recent_played_rms`` (RMS of bytes the device
        callback just consumed — that's the audio currently coming out,
        modulo PortAudio's small output latency). If the user's voice is
        clearly louder than the predicted echo for a short streak, fire
        the same barge-in path the wake-word would have taken.

        Safety:
          * Active ONLY in SPEAKING — never CAPTURING / THINKING / IDLE.
          * ``barge_in_enabled`` config still gates this.
          * Requires a sustained streak (default ~200 ms) so single coughs
            and one-block transients don't trigger barge-in.
          * Once fired, ``_voice_bi_pending`` blocks re-fire until the
            state machine transitions out of SPEAKING.
        """
        if not self.cfg.voice_barge_in_enabled:
            return
        if not self.cfg.barge_in_enabled:
            return
        if self._voice_bi_pending:
            return
        try:
            mic_rms = _chunk_rms_int16(chunk)
        except Exception:
            log.exception("voice_barge_in: mic RMS failed")
            return
        # Speaker echo prediction. If no speaker is wired (e.g. tests), the
        # predicted echo is 0 — the threshold then collapses to min_rms.
        speaker_rms = 0.0
        if self.speaker is not None:
            try:
                speaker_rms = self.speaker.recent_played_rms(
                    self.cfg.voice_barge_in_speaker_window_s,
                )
            except Exception:
                speaker_rms = 0.0
        echo_predicted = speaker_rms * self.cfg.voice_barge_in_echo_gain
        threshold = max(
            echo_predicted + self.cfg.voice_barge_in_margin_rms,
            self.cfg.voice_barge_in_min_rms,
        )
        if mic_rms > threshold:
            self._voice_bi_streak += 1
        else:
            self._voice_bi_streak = 0
            return
        if self._voice_bi_streak < self.cfg.voice_barge_in_streak_chunks:
            return
        # Fire. Build a synthetic WakeEvent so the logger / barge-in path
        # see a uniform shape regardless of trigger source.
        log.info(
            "[voice_barge_in] mic_rms=%.0f speaker_rms=%.0f "
            "echo_pred=%.0f thr=%.0f streak=%d — firing barge-in",
            mic_rms, speaker_rms, echo_predicted, threshold,
            self._voice_bi_streak,
        )
        print(
            "\n[g1_brain] heard you speaking — interrupting reply",
            flush=True,
        )
        self._voice_bi_pending = True
        self._voice_bi_streak = 0
        try:
            from va_demo.wake_word import WakeEvent  # local import; sibling pkg
            evt = WakeEvent(text="<voice-barge-in>", t=time.monotonic())
        except Exception:
            # Fallback minimal shape: anything with .text and .t is enough
            # for the barge-in path (only logging uses these fields).
            class _FallbackEvt:  # noqa: D401
                text = "<voice-barge-in>"
                t = time.monotonic()
            evt = _FallbackEvt()
        asyncio.create_task(
            self._handle_barge_in(evt, was_state=State.SPEAKING),
            name="bcsm-voice-barge-in",
        )

    def _no_speech_timeout_cb(self) -> None:
        if self._state != State.CAPTURING:
            return
        if self.vad.had_any_voice():
            return  # voice was heard; the silence-commit path will handle it
        log.info(
            "[capture] no speech for %.1fs after wake; aborting",
            self.cfg.no_speech_timeout_s,
        )
        print(
            f"[g1_brain] heard no speech in {self.cfg.no_speech_timeout_s:.0f}s "
            "— back to idle (say 'Hi Sparky' to try again)",
            flush=True,
        )
        self.agent.set_uplink_enabled(False)
        # Best-effort drop of any partial server-side audio.
        if self.agent is not None:
            try:
                asyncio.create_task(self.agent.input_audio_buffer_clear())
            except Exception:
                log.debug("input_audio_buffer_clear schedule failed", exc_info=True)
        if self.logger is not None:
            try:
                self.logger.log_no_speech_idle(timeout_s=self.cfg.no_speech_timeout_s)
            except Exception:
                log.exception("logger.log_no_speech_idle raised")
        self._set_state(State.IDLE, reason="no_speech_timeout")

    async def _drain_to_idle(self) -> None:
        """Wait for speaker to drain, then transition to IDLE."""
        deadline = time.monotonic() + self.cfg.drain_max_wait_s
        if self.speaker is not None:
            while time.monotonic() < deadline:
                if self._stopped or self._state not in (State.THINKING, State.SPEAKING):
                    return
                try:
                    pending = self.speaker.pending_bytes()
                except Exception:
                    pending = 0
                if pending <= self.cfg.drain_threshold_bytes:
                    break
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    return
        if self._stopped or self._state not in (State.THINKING, State.SPEAKING):
            return
        self.agent.set_uplink_enabled(False)
        self._set_state(State.IDLE, reason="plan_done_drained")
        # Stdout ack so the operator knows the agent is back to listening
        # for the next wake — without this the prompt looks "stuck" again
        # because the spoken reply ended but nothing said the turn is over.
        print(
            "[g1_brain] idle — say 'Hi Sparky' to start the next turn",
            flush=True,
        )

    def _cancel_drain(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            self._drain_task = None

    # ---- timers -------------------------------------------------------------

    def _reset_no_speech_timer(self) -> None:
        self._cancel_no_speech_timer()

        async def _runner():
            try:
                await asyncio.sleep(self.cfg.no_speech_timeout_s)
                self._no_speech_timeout_cb()
            except asyncio.CancelledError:
                pass

        self._no_speech_timer = asyncio.create_task(_runner(), name="bcsm-no-speech")

    def _cancel_no_speech_timer(self) -> None:
        if self._no_speech_timer is not None:
            self._no_speech_timer.cancel()
            self._no_speech_timer = None

    def _reset_plan_watchdog(self) -> None:
        self._cancel_plan_watchdog()

        async def _runner():
            try:
                await asyncio.sleep(self.cfg.plan_watchdog_s)
                self._plan_watchdog_fire()
            except asyncio.CancelledError:
                pass

        self._plan_watchdog_task = asyncio.create_task(
            _runner(), name="bcsm-plan-watchdog",
        )

    def _cancel_plan_watchdog(self) -> None:
        if self._plan_watchdog_task is not None:
            self._plan_watchdog_task.cancel()
            self._plan_watchdog_task = None

    def _plan_watchdog_fire(self) -> None:
        if self._stopped:
            return
        if self._state not in (State.THINKING, State.SPEAKING):
            return
        log.warning(
            "[plan_watchdog] forcing plan_done after %.1fs (state=%s)",
            self.cfg.plan_watchdog_s, self._state.value,
        )
        if self.logger is not None:
            try:
                self.logger.log_plan_watchdog_timeout(pending=[])
            except Exception:
                log.exception("logger.log_plan_watchdog_timeout raised")
        self._handle_plan_done()
