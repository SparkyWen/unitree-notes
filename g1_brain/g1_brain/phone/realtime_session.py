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

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..brain.realtime_agent import BrainRealtimeAgent
from ..brain.prompts import PHONE_CALL_PREAMBLE


log = logging.getLogger(__name__)


END_CALL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "name": "end_call",
    "description": (
        "Hang up the current phone call. Use after a clear goodbye or when "
        "the operator clearly wants to end the conversation."
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
            # fall through to super for cancel handling
        await super()._handle_event(ws, evt)

    # ----- audio source override ------------------------------------------
    # Parent's uplink loop reads from self.mic.queue. We provide our own
    # uplink task that reads from the transport instead.

    async def _phone_uplink_loop(self, ws) -> None:
        """Forward Twilio inbound audio to OpenAI input_audio_buffer.append."""
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
