"""PhoneRealtimeSession — BrainRealtimeAgent over a Twilio Media Streams call.

Inherits 95% of behaviour from BrainRealtimeAgent (which itself subclasses
va-demo's RealtimeAgent). We override only:

  - audio sink (response.output_audio.delta → transport, not self.speaker)
  - audio source (uplink reads from transport, not self.mic)
  - instructions (prepend PHONE_CALL_PREAMBLE)
  - tool schemas (drop start_phone_call, add end_call)
  - _execute_tool (handle end_call locally; everything else → super)
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from ..brain.realtime_agent import BrainRealtimeAgent
from ..brain.prompts import PHONE_CALL_PREAMBLE


log = logging.getLogger(__name__)


END_CALL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "name": "end_call",
    "description": (
        "Hang up the current phone call. ONLY call this when the operator "
        "EXPLICITLY asks to end the call (e.g. 'hang up', '挂断', or a clear "
        "sign-off: 'bye' / 'goodbye' / '再见' / '拜拜'). Do NOT hang up just "
        "because a task finished or the operator said 'thanks'/'谢谢' — keep "
        "the line open and wait for the next instruction. When unsure, ask "
        "'Should I hang up now?' instead of calling this."
    ),
    "parameters": {"type": "object", "properties": {}},
}


@dataclass
class PhoneRealtimeSession(BrainRealtimeAgent):
    """Realtime session whose audio I/O is a Twilio Media Stream."""

    # Required at construction. Defaulted to None for dataclass-extension safety.
    transport: Any = None         # TwilioMediaStreamTransport
    dialer: Any = None            # TwilioDialer (for end_call hangup)
    call_sid: str = ""

    # ----- prompts / tools ------------------------------------------------

    def _resolve_instructions(self) -> str:
        base = super()._resolve_instructions()
        return PHONE_CALL_PREAMBLE + "\n\n" + base

    def _resolve_tool_schemas(self) -> List[Dict[str, Any]]:
        base = super()._resolve_tool_schemas()
        filtered = [s for s in base if s.get("name") != "start_phone_call"]
        return filtered + [END_CALL_SCHEMA]

    # ----- tool dispatch --------------------------------------------------

    async def _execute_tool(
        self, name: str, args: Dict[str, Any], *, call_id: str = ""
    ) -> Dict[str, Any]:
        if name == "end_call":
            if self.dialer is None or not self.call_sid:
                return {"ok": False, "reason": "no dialer or call_sid"}
            try:
                await self.dialer.hangup(self.call_sid)
                return {"ok": True, "summary": "call ending"}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "reason": f"hangup failed: {e!s}"}
        return await super()._execute_tool(name, args, call_id=call_id)

    # ----- audio sink override --------------------------------------------
    # Parent's _handle_event writes response audio to self.speaker.write().
    # We intercept BEFORE super by handling the event ourselves; for every
    # other event type we delegate to super.

    async def _handle_event(self, ws, evt: Dict[str, Any]) -> None:
        t = evt.get("type", "")
        if t == "response.output_audio.delta" and self.transport is not None:
            b64 = evt.get("delta", "")
            if b64:
                pcm = base64.b64decode(b64)
                try:
                    await self.transport.send_outbound_pcm24k(pcm)
                except Exception:
                    log.exception("transport.send_outbound_pcm24k raised")
            # Notify any listeners (parent does this too — keep parity)
            if self.on_response_audio_delta is not None:
                try:
                    self.on_response_audio_delta()
                except Exception:
                    log.exception("on_response_audio_delta raised")
            return
        if t == "input_audio_buffer.speech_started" and self.transport is not None:
            # Barge-in: flush queued outbound audio on Twilio side
            try:
                await self.transport.clear_outbound()
            except Exception:
                log.exception("transport.clear_outbound raised")
            # Cancel any in-flight slow-brain ask FIRST, independent of whether
            # an OpenAI response is active. A long ask_slow_brain runs AFTER its
            # response.done (so _current_response_id is already None), which is
            # exactly the "long planning" case the caller wants to interrupt —
            # gating this on _current_response_id meant it could never be
            # cancelled and the caller couldn't stop a long plan over the phone.
            if self.on_response_canceled is not None:
                try:
                    self.on_response_canceled("phone_barge_in")
                except Exception:
                    log.exception("on_response_canceled raised")
            # Only send response.cancel when a response is actually active —
            # otherwise OpenAI returns a 400 response_cancel_not_active (noisy).
            if getattr(self, "_current_response_id", None):
                try:
                    await self.cancel_in_flight()
                except Exception:
                    log.exception("cancel_in_flight raised")
            # fall through to super for any remaining event handling
        await super()._handle_event(ws, evt)

    # ----- session config override ----------------------------------------
    # Parent sends turn_detection: None (client drives turns via state
    # machine). For phone mode the caller's voice IS the turn signal, so
    # we must enable server VAD.

    async def _session_update(self, ws) -> None:
        """Same as parent's GA-shape session.update but with server VAD on.

        Phone mode has no client state machine to drive turns — the caller's
        voice IS the turn signal — so server_vad must be enabled.
        """
        evt = {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": self.model,
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "transcription": {"model": "gpt-4o-mini-transcribe"},
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 700,
                        },
                    },
                    "output": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "voice": self.voice,
                    },
                },
                "instructions": self._resolve_instructions(),
                "tools": self._resolve_tool_schemas(),
                "tool_choice": "auto",
            },
        }
        await ws.send(json.dumps(evt))

    # ----- audio source override ------------------------------------------
    # Parent's uplink loop reads from self.mic.queue. We provide our own
    # uplink task that reads from the transport instead.

    async def _uplink(self, ws) -> None:
        """Forward Twilio inbound audio to OpenAI input_audio_buffer.append.

        Overrides RealtimeAgent._uplink so that parent's run() picks up this
        implementation instead of the default mic.queue reader.
        """
        async for pcm24k in self.transport.iter_inbound_pcm24k():
            payload = base64.b64encode(pcm24k).decode("ascii")
            try:
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": payload,
                }))
            except Exception:
                log.exception("ws.send raised; ending uplink")
                return
