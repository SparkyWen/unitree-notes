"""BrainRealtimeAgent — extends va_demo.realtime_agent.RealtimeAgent.

We do not modify va-demo. We subclass and:

- override ``_resolve_instructions`` / ``_resolve_tool_schemas`` /
  ``_execute_tool`` (parent contract), and
- intercept the WS event stream so we can emit a small set of higher-level
  callbacks the BrainConversationStateMachine and ConversationLogger
  consume:

  * ``on_user_transcript(text)`` — when the user's audio is transcribed
  * ``on_assistant_transcript_done(text)`` — when the model's audio reply
    has a final transcript
  * ``on_tool_use(call_id, name, args)`` — model has emitted a tool call
  * ``on_tool_result(call_id, name, result)`` — client has executed it
  * ``on_response_canceled(reason)`` — we sent ``response.cancel`` (barge-in)
  * ``on_plan_done()`` — the WHOLE turn (possibly multi-response, multi-tool
    plan) has completed: leaf ``response.done`` arrived with no function-call
    output items still pending. This is the signal the state machine uses
    to transition from SPEAKING → drain wait → IDLE.

We also expose two control methods used by the state machine for barge-in:

- ``cancel_in_flight()`` — sends ``response.cancel`` + ``input_audio_buffer.clear``
- ``input_audio_buffer_clear()`` — drops uncommitted user audio (used for
  CAPTURING-to-CAPTURING restart on a second wake within the same turn)

va-demo is unchanged. See docs/audio-control-update01.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

import websockets

from va_demo.realtime_agent import REALTIME_URL, RealtimeAgent  # type: ignore

from ..scene_state.fusion import SceneStateBus
from .prompts import (
    PHONE_DIAL_GUIDANCE,
    REALTIME_SYSTEM_PROMPT_BRAIN,
    REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY,
    language_directive,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- keepalive --
#
# va-demo opens the Realtime WS with the websockets-library defaults
# (ping_interval=20s, ping_timeout=20s). That is far too tight for the brain:
# a SINGLE tool dispatch runs *inline* in the downlink coroutine and can
# legitimately take tens of seconds — the vision-risk gate (up to its ~30s
# budget) + an operator y/N confirm (up to 60s) + a turn/walk (up to 14s).
# On top of that, in-process perception (CPU MuJoCo head-cam render on Mesa
# llvmpipe + dual YOLO + MediaPipe) periodically starves the asyncio loop
# thread of the GIL for multiple seconds at a time (boot logs: "a 1.0s sleep
# took 5.69s"). Either way the keepalive pong is not serviced within 20s,
# websockets closes the socket with `1011 keepalive ping timeout`, the
# downlink re-raises, and — because nothing above it reconnects — the whole
# agent shut down mid-conversation (field log 2026-05-27 17:14:04).
#
# We keep a 20s ping_interval (cheap NAT/proxy keepalive) but widen the pong
# budget well past the worst-case dispatch so a healthy-but-slow turn can't
# trip it, while still keeping a finite ceiling so a genuinely dead peer is
# eventually detected and triggers a reconnect.
_PING_INTERVAL_S: float = 20.0
_PING_TIMEOUT_S: float = 180.0

# Reconnect policy for a genuine drop (network blip, server-side 1011, or a
# stall beyond _PING_TIMEOUT_S). Rather than tear the whole robot session
# down, run() re-opens the Realtime session in place — mic/speaker/perception/
# robot all stay up. The in-session conversation history is lost (a new WS is
# a new server-side session), but the developer instructions (incl. the
# long-term memory addendum) are re-sent on every connect, so Sparky keeps its
# persistent context. Exponential backoff caps the retry rate; a session that
# stays up at least _HEALTHY_SESSION_S resets the failure budget so each
# independent drop gets a full set of retries, while a connection that drops
# immediately on open accumulates failures and — after _MAX_RECONNECT_ATTEMPTS
# in a row — gives up and lets run() raise (falling through to normal shutdown).
_RECONNECT_BACKOFF_S: float = 1.0
_RECONNECT_BACKOFF_MAX_S: float = 15.0
_MAX_RECONNECT_ATTEMPTS: int = 6
_HEALTHY_SESSION_S: float = 30.0


# Type-only; the concrete SkillServer class is built by the skills agent and
# must conform to:
#   class SkillServer:
#       async def execute(self, tool: str, args: dict) -> dict: ...
SkillServer = Any  # noqa: N816 — kept loose so we don't import the real class
                   # (avoids a circular import in the apps wiring layer).


@dataclass
class BrainRealtimeAgent(RealtimeAgent):
    """Slow Brain: va-demo's Realtime client wired to the new SkillServer."""

    # New required boundaries. Default to None so the dataclass can extend its
    # parent without breaking field-order rules; the apps wiring is expected to
    # always pass a real SkillServer + SceneStateBus.
    skill_server: Optional[SkillServer] = None
    scene_bus: Optional[SceneStateBus] = None
    mock_imitate_trigger: Optional[Callable[[str], Awaitable[None]]] = None
    # Whether to expose mock_imitate to the LLM. Set False from the apps wiring
    # when mock_imitation.enabled is false in the YAML config so the brain
    # cannot call mock_imitate spontaneously when it sees the user wave.
    mock_imitate_enabled: bool = True
    # Whether to expose start_phone_call to the LLM. Set True from the apps
    # wiring when --enable-phone is on (or cfg.phone.enabled=true) so the
    # local Realtime model can dial out via Twilio.
    phone_enabled: bool = False
    # ISO-639-1 reply-language lock (default English). The Realtime model
    # otherwise mirrors whatever language it (mis)hears (Korean/Chinese drift);
    # we append a hard language_directive() to the instructions so every reply
    # stays in this language. Configurable via openai.language in the YAML.
    response_language: str = "en"

    # ---- new hooks consumed by ConversationStateMachine + Logger ----
    # Each is invoked from the asyncio loop thread (we are already inside the
    # downlink coroutine). All are sync callables; if the consumer needs to
    # do async work they should schedule it themselves.
    on_user_transcript: Optional[Callable[[str], None]] = None
    on_assistant_transcript_done: Optional[Callable[[str], None]] = None
    on_tool_use: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
    on_tool_result: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
    on_response_canceled: Optional[Callable[[str], None]] = None
    on_plan_done: Optional[Callable[[], None]] = None
    # Fired once, the first time the Realtime session is up (session.created).
    # agent_main uses it to print a loud "now listening" banner so the operator
    # knows when "Hi Sparky" will actually be heard — startup buries that
    # moment ~60-70 s deep under DDS / perception / OpenAI log noise.
    on_session_ready: Optional[Callable[[], None]] = None
    # Fired after a *reconnect* (not the first connect) re-establishes the
    # Realtime session. The previous turn's state died with the old socket, so
    # agent_main wires this to ConversationStateMachine.force_idle() to land
    # the SM back in a clean wake-ready IDLE state.
    on_reconnect: Optional[Callable[[], None]] = None

    def __post_init__(self):
        super().__post_init__()
        self._session_ready_fired: bool = False
        if self.skill_server is None:
            log.warning(
                "BrainRealtimeAgent created without skill_server; tool calls "
                "will all fail with ok=false. Wire one before calling run()."
            )
        # Plan-level tracking. A "plan" is one user turn — possibly N model
        # responses chained by tool calls. plan_done fires when the leaf
        # response.done arrives with no function_call output items.
        self._plan_active: bool = False

        # In-flight response tracking for clean barge-in. The Realtime server
        # keeps emitting events (audio.delta, audio_transcript.delta,
        # function_call_arguments.done, response.done) for a response that
        # was already finalized server-side by the time response.cancel
        # arrived — the cancel returns response_cancel_not_active but the
        # event stream continues. Without filtering, those late events:
        #   - write OLD response audio to the speaker AFTER speaker.clear(),
        #     so the user keeps hearing the robot talk after their barge-in;
        #   - dispatch OLD tool calls AFTER the user issued a new command,
        #     causing skill_server to execute stale walks/turns;
        #   - each tool dispatch sends a new response.create that collides
        #     with the new turn's response.create
        #     ('conversation_already_has_active_response'), stalling the
        #     plan watchdog into a 30 s timeout and finally a WS keepalive
        #     close.
        # We track which response_id is currently in flight (set by
        # response.created) and on cancel_in_flight() add it to the
        # cancelled set; subsequent events carrying that response_id are
        # silently dropped. Set is capped to the last 16 ids so it cannot
        # grow without bound across a long session.
        self._current_response_id: Optional[str] = None
        self._cancelled_response_ids: List[str] = []
        self._cancelled_response_id_cap: int = 16

        # Last connection-level error, kept so run()'s give-up path can
        # re-raise the actual cause into the logs rather than a generic one.
        self._last_conn_exc: Optional[BaseException] = None

    # ------------------------------------------------------------------ hooks

    # Additional developer-instructions text appended at session open time.
    # The memory subsystem fills this with curated long-term context
    # (memory_summary.md + AGENTS.md) so the Realtime model starts each
    # session knowing what was learned in prior ones.
    _instructions_addendum: str = ""

    def append_developer_instructions(self, addendum: str) -> None:
        """Append text to the developer instructions before the session opens.

        Must be called BEFORE .run(). After that, instructions are baked
        into the Realtime session and a session.update would be required
        to change them mid-session (we intentionally do not do that for
        latency reasons).
        """
        if not addendum:
            return
        if self._instructions_addendum:
            self._instructions_addendum = self._instructions_addendum + "\n\n" + addendum
        else:
            self._instructions_addendum = addendum

    # ------------------------------------------------------------- run loop --

    async def run(self):
        """Open the Realtime session and keep it alive across transient drops.

        Override of ``va_demo.RealtimeAgent.run()`` (va-demo is intentionally
        left unmodified — see the module docstring). Two behavioural changes,
        both motivated by the 2026-05-27 field crash:

        1. **Keepalive.** Open the WS with ``ping_timeout`` widened from the
           websockets default 20 s to ``_PING_TIMEOUT_S`` so a long-but-healthy
           tool dispatch (vision gate + operator confirm + walk) or a GIL stall
           from in-process perception cannot trip a spurious
           ``1011 keepalive ping timeout``.
        2. **Resilience.** A genuine connection drop reconnects the session in
           place instead of propagating out of ``run()`` and tearing down the
           whole agent (mic/speaker/robot). ``on_reconnect`` fires after each
           successful re-open so the state machine can reset to IDLE.

        The orchestration (connect → session.update → uplink/downlink tasks →
        wait FIRST_COMPLETED) mirrors the parent; we wrap it in a reconnect
        loop. ``CancelledError`` (shutdown) is never swallowed.
        """
        url = REALTIME_URL.format(model=self.model)
        headers = [("Authorization", f"Bearer {self.api_key}")]
        connect_kwargs = {
            "max_size": 16 * 1024 * 1024,
            "ping_interval": _PING_INTERVAL_S,
            "ping_timeout": _PING_TIMEOUT_S,
        }

        connected_once = False
        failures = 0
        while True:
            # Back off before a retry (never before the first attempt).
            if failures:
                if failures > _MAX_RECONNECT_ATTEMPTS:
                    log.error(
                        "Realtime session failed %d consecutive times; giving "
                        "up (agent will shut down)", failures,
                    )
                    raise self._last_conn_exc or RuntimeError(
                        "Realtime session unrecoverable"
                    )
                backoff = min(
                    _RECONNECT_BACKOFF_S * (2 ** (failures - 1)),
                    _RECONNECT_BACKOFF_MAX_S,
                )
                log.warning(
                    "reconnecting Realtime session in %.1fs (failure %d/%d)",
                    backoff, failures, _MAX_RECONNECT_ATTEMPTS,
                )
                await asyncio.sleep(backoff)

            # ---- connect ----
            try:
                try:
                    ws = await websockets.connect(
                        url, additional_headers=headers, **connect_kwargs
                    )
                except TypeError:
                    # Older websockets used extra_headers= instead.
                    ws = await websockets.connect(
                        url, extra_headers=headers, **connect_kwargs
                    )
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
                self._last_conn_exc = e
                failures += 1
                log.warning("Realtime connect failed: %s", e)
                continue

            # ---- run one session ----
            session_start = time.monotonic()
            drop_exc: Optional[BaseException] = None
            async with ws:
                self._ws = ws
                try:
                    await self._session_update(ws)
                    if connected_once:
                        # This is a reconnect: the prior turn's server-side
                        # state is gone. Let the app reset the SM to IDLE.
                        self._emit_reconnect()
                    connected_once = True
                    uplink = asyncio.create_task(self._uplink(ws), name="rt-uplink")
                    downlink = asyncio.create_task(self._downlink(ws), name="rt-downlink")
                    try:
                        done, pending = await asyncio.wait(
                            {uplink, downlink}, return_when=asyncio.FIRST_COMPLETED
                        )
                        for t in pending:
                            t.cancel()
                        for t in done:
                            exc = t.exception()
                            if exc is not None:
                                drop_exc = exc
                    finally:
                        uplink.cancel()
                        downlink.cancel()
                finally:
                    self._ws = None

            # ---- decide: return, reconnect, or propagate ----
            if drop_exc is None:
                # Both tasks ended without error (e.g. the server closed the
                # stream cleanly). The session is genuinely over.
                return
            if isinstance(drop_exc, (websockets.WebSocketException, OSError, asyncio.TimeoutError)):
                session_dur = time.monotonic() - session_start
                self._last_conn_exc = drop_exc
                if session_dur >= _HEALTHY_SESSION_S:
                    # A session that stayed up a healthy while resets the budget
                    # so this independent drop gets a fresh set of retries.
                    failures = 1
                else:
                    # Dropped almost immediately — accumulate so we can't
                    # hot-loop against a hard failure.
                    failures += 1
                log.warning(
                    "Realtime session dropped after %.0fs: %s — reconnecting",
                    session_dur, drop_exc,
                )
                continue
            # Not a connection error — a real bug in event handling. Propagate
            # so it isn't silently retried forever.
            raise drop_exc

    def _emit_reconnect(self) -> None:
        if self.on_reconnect is None:
            return
        try:
            self.on_reconnect()
        except Exception:
            log.exception("on_reconnect raised")

    def _resolve_instructions(self) -> str:
        base = (
            REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY
            if self.vision_only
            else REALTIME_SYSTEM_PROMPT_BRAIN
        )
        # When this agent can actually place calls (start_phone_call is in its
        # tool list), teach it the "omit `to` to call the operator" rule so a
        # misheard digit can't derail "call me". The phone-side session filters
        # start_phone_call out, so it never needs this.
        if self.phone_enabled and not self.vision_only:
            base = base + "\n\n" + PHONE_DIAL_GUIDANCE
        if self._instructions_addendum:
            base = base + "\n\n" + self._instructions_addendum
        # Append the language lock LAST so its recency overrides any persona /
        # memory-addendum text that might otherwise invite a language switch.
        return base + "\n\n" + language_directive(self.response_language)

    def _resolve_tool_schemas(self) -> List[Dict[str, Any]]:
        # Lazy import so `g1_brain.brain` can be imported in tests that don't
        # care about the skills package layout.
        from ..skills.tool_schemas import build_tool_schemas  # type: ignore

        return build_tool_schemas(
            sim=True,
            vision_only=self.vision_only,
            mock_imitate_enabled=self.mock_imitate_enabled,
            phone_enabled=self.phone_enabled,
        )

    async def _execute_tool(self, name: str, args: Dict[str, Any], *, call_id: str = "") -> Dict[str, Any]:
        """Route every tool call to the SkillServer.

        We intentionally do NOT pre-validate here — the SkillServer runs its
        own SafetySupervisor pass internally (per the contract in
        skills/skill_server.py). Adding a second validation here would
        double-log and could disagree with the server-side decision.
        """
        if self.skill_server is None:
            return {"ok": False, "reason": "skill_server not wired"}
        try:
            # call_id is propagated as a keyword for action_result logging
            # and ask_slow_brain cancel-token tracking; older skill servers
            # without the kwarg fall back transparently.
            return await self.skill_server.execute(name, args, call_id=call_id)
        except TypeError:
            return await self.skill_server.execute(name, args)
        except Exception as e:  # noqa: BLE001 — we want to surface anything
            log.exception("skill_server.execute(%s) raised", name)
            return {"ok": False, "reason": f"exception: {e!s}"}

    # ------------------------------------------------ event-stream interception

    async def _handle_event(self, ws, evt: Dict[str, Any]):
        """Mirror va-demo's dispatcher but emit higher-level callbacks.

        Re-implemented (rather than super().handle_event() + before/after
        hooks) because we need to intercept ``response.done`` and decide
        plan-end *before* the parent's on_response_done callback fires —
        otherwise the state machine sees response.done before it knows
        whether more responses are coming.
        """
        import base64

        t = evt.get("type", "")

        # ---- response_id tracking + cancelled-response drop -----------------
        # Maintain `_current_response_id` for the cancel path, and silently
        # drop events that belong to a response the operator already
        # cancelled (barge-in). See __post_init__ for the rationale.
        if t == "response.created":
            rid = (evt.get("response") or {}).get("id")
            if rid:
                self._current_response_id = rid
        rid = self._event_response_id(evt)
        if rid is not None and rid in self._cancelled_response_ids:
            log.debug("dropping event %s for cancelled response %s", t, rid)
            return

        # GA renamed the streaming audio + transcript events (see va_demo
        # for the migration note).
        if t == "response.output_audio.delta":
            b64 = evt.get("delta", "")
            if b64:
                self.speaker.write(base64.b64decode(b64))
                if self.on_response_audio_delta is not None:
                    try:
                        self.on_response_audio_delta()
                    except Exception:
                        log.exception("on_response_audio_delta raised")
        elif t == "response.output_audio.done":
            pass
        elif t == "response.output_audio_transcript.delta":
            piece = evt.get("delta", "")
            if piece:
                print(piece, end="", flush=True)
                if self.spoken_cache is not None:
                    self.spoken_cache.add(piece)
        elif t == "response.output_audio_transcript.done":
            print()  # newline
            transcript = evt.get("transcript", "")
            if transcript:
                if self.spoken_cache is not None:
                    self.spoken_cache.add(transcript)
                self._emit_assistant_transcript_done(transcript)
        elif t == "conversation.item.input_audio_transcription.completed":
            transcript = evt.get("transcript", "")
            if transcript:
                print(f"\n[user] {transcript}", flush=True)
                self._emit_user_transcript(transcript)
        elif t == "input_audio_buffer.speech_started":
            log.debug("user speech started")
        elif t == "response.done":
            # Decide plan-end BEFORE notifying the state machine.
            had_fcall = self._response_had_function_call(evt)
            if self.on_response_done is not None:
                try:
                    self.on_response_done()
                except Exception:
                    log.exception("on_response_done raised")
            if not had_fcall:
                # Leaf response. The whole plan is done.
                self._emit_plan_done()
            # else: a function_call_output + new response.create will follow
            # (handled in _dispatch_tool); plan stays active.
            # Clear current response id once it's truly done.
            done_rid = (evt.get("response") or {}).get("id")
            if done_rid and self._current_response_id == done_rid:
                self._current_response_id = None
        elif t == "response.function_call_arguments.done":
            await self._dispatch_tool(ws, evt)
        elif t == "error":
            log.error("realtime error: %s", evt.get("error"))
        elif t in ("session.created", "session.updated", "response.created",
                   "rate_limits.updated", "response.output_item.added",
                   "response.output_item.done", "response.content_part.added",
                   "response.content_part.done", "input_audio_buffer.committed",
                   "input_audio_buffer.speech_stopped",
                   # GA split conversation.item.created into added + done.
                   "conversation.item.added", "conversation.item.done",
                   "conversation.item.created"):
            if t == "session.created" and not self._session_ready_fired:
                self._session_ready_fired = True
                if self.on_session_ready is not None:
                    try:
                        self.on_session_ready()
                    except Exception:
                        log.exception("on_session_ready raised")
            log.debug("rt event: %s", t)
        else:
            log.debug("rt event (unhandled): %s", t)

    @staticmethod
    def _event_response_id(evt: Dict[str, Any]) -> Optional[str]:
        """Pull the response.id off a Realtime event regardless of shape.

        Most response.* events carry a top-level ``response_id`` string.
        ``response.created`` / ``response.done`` instead nest the id under
        ``response.id``. We probe both so the cancelled-response filter
        works on every event class.
        """
        rid = evt.get("response_id")
        if rid:
            return rid
        resp = evt.get("response")
        if isinstance(resp, dict):
            inner = resp.get("id")
            if inner:
                return inner
        return None

    @staticmethod
    def _response_had_function_call(response_done_evt: Dict[str, Any]) -> bool:
        """True iff the response payload contains any function_call output item.

        Realtime's response.done event has shape:
          {"type": "response.done", "response": {"id": ...,
            "output": [{"type": "function_call" | "message" | ...}, ...]}}
        We look for any function_call entry. If even one is present, the
        client is responsible for executing it and sending response.create
        for the continuation, so this is NOT plan-end.
        """
        try:
            output = response_done_evt.get("response", {}).get("output", []) or []
        except AttributeError:
            return False
        for item in output:
            if isinstance(item, dict) and item.get("type") == "function_call":
                return True
        return False

    async def _dispatch_tool(self, ws, evt: Dict[str, Any]):
        """Execute a tool call, emit callbacks, send result + next response.create.

        Reimplemented from va-demo (rather than super-call) so we can fire
        on_tool_use / on_tool_result around the execution. Behaviour matches
        the parent: validate via self.safety, execute via self._execute_tool,
        send function_call_output, then response.create to continue the turn.
        """
        call_id = evt.get("call_id") or ""
        name = evt.get("name") or ""
        rid = self._event_response_id(evt)
        try:
            args = json.loads(evt.get("arguments", "") or "{}")
        except json.JSONDecodeError:
            args = {}

        log.info("tool call: %s(%s)", name, args)
        self._emit_tool_use(call_id, name, args)

        # Single validation point: skill_server.execute() runs the
        # SafetySupervisor pass (incl. the vision-risk gate AND the operator
        # confirm prompt) internally and sanitizes the args. We must NOT
        # pre-validate here too — doing so gated every motion call twice: two
        # vision evaluations and, on a RISK verdict, TWO terminal y/N prompts
        # for a single walk (field log 2026-05-26: one walk → confirm 'y' →
        # confirm 'y' → execute). _execute_tool's own docstring already
        # documents this contract; _dispatch_tool used to violate it.
        try:
            result = await self._execute_tool(name, args, call_id=call_id)
        except Exception as e:  # noqa: BLE001
            log.exception("tool exception: %s", e)
            result = {"ok": False, "reason": f"exception: {e!s}"}

        self._emit_tool_result(call_id, name, result)

        # If the response that triggered this tool call was cancelled
        # DURING execution (operator barged in mid-walk), do not send the
        # function_call_output + response.create. That stack would land a
        # fresh response on top of the just-cancelled one and the user's
        # next turn would hit
        # ``conversation_already_has_active_response`` — the exact failure
        # mode reproduced in the field log around 20:00:59 (a 50 s walk
        # completes long after the user has barged in, the late
        # response.create races the new turn's response.create, and the
        # plan watchdog eventually times the session out at 30 s).
        if rid is not None and rid in self._cancelled_response_ids:
            log.debug(
                "skipping ws send for tool %s (call_id=%s response_id=%s "
                "cancelled mid-flight)",
                name, call_id, rid,
            )
            # Fire plan_done so the state machine doesn't wait for a leaf
            # response.done that will never arrive on the cancelled
            # response. _handle_plan_done is a no-op when the SM already
            # transitioned to CAPTURING via barge-in.
            self._emit_plan_done()
            return

        try:
            await ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                },
            }))
            # Ask the model to continue (turn the tool result into a spoken
            # reply, or chain another tool call).
            await ws.send(json.dumps({"type": "response.create"}))
        except Exception:  # noqa: BLE001
            # WS may have been closed under us (e.g. shutdown); the plan is
            # effectively done from the state machine's point of view.
            log.exception("failed to send tool result / response.create")
            self._emit_plan_done()

    # ------------------------------------------------ control: barge-in helpers

    async def cancel_in_flight(self) -> None:
        """Cancel any in-flight response and drop uncommitted input audio.

        Best-effort: each WS send is wrapped because either may fail when
        there is no active response or no buffered input. The state machine
        calls this in the barge-in path; it should never raise.

        Also mark the currently-tracked ``response_id`` as cancelled so the
        downlink event handler drops any audio.delta /
        audio_transcript.delta / function_call_arguments.done /
        response.done events that the server emits AFTER the cancel arrives
        (the server keeps streaming a response that was already finalized
        before our cancel reached it; without filtering, those late events
        write old TTS to the speaker, dispatch stale tool calls, and stack
        a parallel response.create on the still-active old response — the
        chain that produced the 'I've moved forward 10 m' echo and the
        ``conversation_already_has_active_response`` errors in the field).
        """
        # Mark the in-flight response cancelled BEFORE the WS send so a
        # late audio.delta racing the cancel can still be dropped.
        self._mark_current_response_cancelled()

        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps({"type": "response.cancel"}))
        except Exception:  # noqa: BLE001
            log.debug("response.cancel send failed", exc_info=True)
        try:
            await ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
        except Exception:  # noqa: BLE001
            log.debug("input_audio_buffer.clear send failed", exc_info=True)
        # Local: drop any TTS audio queued for playback so the user hears
        # silence immediately, not the tail of the cancelled reply.
        try:
            self.speaker.clear()
        except Exception:  # noqa: BLE001
            log.debug("speaker.clear failed", exc_info=True)
        # Tell consumers (logger) we cancelled. State machine drives its own
        # transition; this hook is informational only.
        if self.on_response_canceled is not None:
            try:
                self.on_response_canceled("barge_in")
            except Exception:
                log.exception("on_response_canceled raised")
        # Plan is no longer in flight.
        self._plan_active = False

    def _mark_current_response_cancelled(self) -> None:
        """Add the currently-tracked response_id to the cancelled set.

        Bounded LRU: never grows past ``_cancelled_response_id_cap`` so a
        long session of barge-ins doesn't leak memory. We append to the
        end and drop from the front when full — `in` membership tests on
        a small list of strings are O(n) but n ≤ 16 so this is negligible
        relative to a websocket round-trip.
        """
        rid = self._current_response_id
        if not rid:
            return
        if rid in self._cancelled_response_ids:
            return
        self._cancelled_response_ids.append(rid)
        if len(self._cancelled_response_ids) > self._cancelled_response_id_cap:
            del self._cancelled_response_ids[0]
        # Forget the now-cancelled in-flight id so a future response.created
        # for a brand-new response cleanly takes its place.
        self._current_response_id = None

    async def input_audio_buffer_clear(self) -> None:
        """Drop server-side uncommitted user audio (mid-capture restart)."""
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
        except Exception:  # noqa: BLE001
            log.debug("input_audio_buffer.clear send failed", exc_info=True)

    def reset_plan_tracker(self) -> None:
        """Mark the current plan as no-longer-active (barge-in side effect)."""
        self._plan_active = False

    async def commit_and_respond(self):
        """Override parent's commit_and_respond to mark plan_active."""
        if self._ws is None:
            return
        self._plan_active = True
        await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await self._ws.send(json.dumps({"type": "response.create"}))

    # ------------------------------------------------ callback emitters

    def _emit_user_transcript(self, text: str) -> None:
        if self.on_user_transcript is None:
            return
        try:
            self.on_user_transcript(text)
        except Exception:
            log.exception("on_user_transcript raised")

    def _emit_assistant_transcript_done(self, text: str) -> None:
        if self.on_assistant_transcript_done is None:
            return
        try:
            self.on_assistant_transcript_done(text)
        except Exception:
            log.exception("on_assistant_transcript_done raised")

    def _emit_tool_use(self, call_id: str, name: str, args: Dict[str, Any]) -> None:
        if self.on_tool_use is None:
            return
        try:
            self.on_tool_use(call_id, name, args)
        except Exception:
            log.exception("on_tool_use raised")

    def _emit_tool_result(self, call_id: str, name: str, result: Dict[str, Any]) -> None:
        if self.on_tool_result is None:
            return
        try:
            self.on_tool_result(call_id, name, result)
        except Exception:
            log.exception("on_tool_result raised")

    def _emit_plan_done(self) -> None:
        # Idempotency: only fire once per plan.
        if not self._plan_active:
            return
        self._plan_active = False
        if self.on_plan_done is None:
            return
        try:
            self.on_plan_done()
        except Exception:
            log.exception("on_plan_done raised")

    # ---------------------------------------------------- perception → brain

    async def inject_perception_event(self, event_text: str) -> None:
        """Push a synthetic conversation item so the brain hears about a
        perception event mid-turn.

        We wrap it as a ``conversation.item.create`` with role="system"
        (Realtime accepts system items inside the conversation). The brain
        decides on its own whether to respond — we deliberately do NOT issue a
        ``response.create``: the on-going Realtime session will pick the item
        up at its next response window. If the brain is idle and you want it
        to act immediately, the apps wiring can follow up with its own
        ``response.create`` send.
        """
        if self._ws is None:
            log.debug("inject_perception_event: no ws yet, dropping: %s", event_text)
            return
        evt = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [
                    {"type": "input_text", "text": event_text},
                ],
            },
        }
        try:
            await self._ws.send(json.dumps(evt))
        except Exception:  # noqa: BLE001
            log.exception("failed to inject perception event")
