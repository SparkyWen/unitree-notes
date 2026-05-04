"""OpenAI Realtime API client over raw WebSocket.

Two concurrent tasks:
  - uplink:   MicStream queue -> input_audio_buffer.append (gated by an
              asyncio.Event so the state machine can mute when idle)
  - downlink: server events -> SpeakerStream + tool dispatcher

Tool dispatcher routes to SkillBackend / VisionClient / TTSClient through the
SafetySupervisor.

Turn-taking is OFF on the server (turn_detection: null). The
ConversationStateMachine drives commits and response.create through
commit_and_respond() / cancel_response() / set_uplink_enabled().
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

import websockets

from .audio_io import MicStream, SpeakerStream
from .camera import Camera
from .prompts import REALTIME_SYSTEM_PROMPT, VISION_SCENE_PROMPT
from .safety import SafetySupervisor
from .skills import SkillBackend
from .tts import TTSClient
from .vision import VisionClient

log = logging.getLogger(__name__)


REALTIME_URL = "wss://api.openai.com/v1/realtime?model={model}"


# ---------- Tool schemas exposed to the Realtime model -----------------------

def _build_tool_schemas() -> List[Dict[str, Any]]:
    gesture_enum = [
        "wave_right", "wave_left", "hands_up", "t_pose",
        "salute", "clap", "guard", "punch_combo",
    ]
    return [
        {
            "type": "function",
            "name": "say",
            "description": (
                "Speak a short message to the user via OpenAI TTS. Prefer this "
                "for canned/short replies; the Realtime audio reply is usually "
                "better for conversational content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": 200},
                },
                "required": ["text"],
            },
        },
        {
            "type": "function",
            "name": "stop",
            "description": "Immediately stop walking and release any active arm gesture.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "release_arms",
            "description": "Hand the arms back to the locomotion policy (no walking change).",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "walk",
            "description": (
                "Walk for a short duration. Conservative bounds; do not exceed "
                "0.2 m/s unless the user insists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vx": {"type": "number", "minimum": -0.3, "maximum": 0.3,
                            "description": "forward velocity m/s"},
                    "vy": {"type": "number", "minimum": -0.1, "maximum": 0.1,
                            "description": "lateral velocity m/s"},
                    "wz": {"type": "number", "minimum": -0.4, "maximum": 0.4,
                            "description": "yaw rate rad/s"},
                    "duration_s": {"type": "number", "minimum": 0.2, "maximum": 1.5},
                },
                "required": ["duration_s"],
            },
        },
        {
            "type": "function",
            "name": "gesture",
            "description": "Play one prevalidated arm gesture. The robot keeps walking unaffected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": gesture_enum},
                },
                "required": ["name"],
            },
        },
        {
            "type": "function",
            "name": "describe_scene",
            "description": (
                "Take one snapshot from the front camera and ask the vision "
                "model to describe what it sees. Use this whenever the user "
                "asks any visual question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Optional specific question to answer about the scene.",
                    },
                    "detail": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
    ]


# ---------- Tool dispatcher --------------------------------------------------

@dataclass
class RealtimeAgent:
    api_key: str
    model: str
    voice: str
    mic: MicStream
    speaker: SpeakerStream
    camera: Camera
    vision: VisionClient
    tts: TTSClient
    skills: Optional[SkillBackend]
    safety: SafetySupervisor
    vision_resize_width: int = 1024
    vision_jpeg_quality: int = 85
    spoken_cache: Optional[Any] = None
    on_response_audio_delta: Optional[Callable[[], None]] = None
    on_response_done: Optional[Callable[[], None]] = None

    def __post_init__(self):
        self._uplink_enabled = asyncio.Event()
        self._ws = None

    async def run(self):
        url = REALTIME_URL.format(model=self.model)
        headers = [
            ("Authorization", f"Bearer {self.api_key}"),
            ("OpenAI-Beta", "realtime=v1"),
        ]
        log.info("connecting Realtime: %s", url)
        connect_kwargs = {"max_size": 16 * 1024 * 1024}
        try:
            ws = await websockets.connect(url, additional_headers=headers, **connect_kwargs)
        except TypeError:
            ws = await websockets.connect(url, extra_headers=headers, **connect_kwargs)

        async with ws:
            self._ws = ws
            try:
                await self._session_update(ws)
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
                        if exc:
                            raise exc
                finally:
                    uplink.cancel()
                    downlink.cancel()
            finally:
                self._ws = None

    async def _session_update(self, ws):
        evt = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "voice": self.voice,
                "instructions": REALTIME_SYSTEM_PROMPT,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"},
                "turn_detection": None,
                "tools": _build_tool_schemas(),
                "tool_choice": "auto",
            },
        }
        await ws.send(json.dumps(evt))

    async def _uplink(self, ws):
        try:
            while True:
                chunk = await self.mic.queue.get()
                if not chunk:
                    continue
                if not self._uplink_enabled.is_set():
                    continue  # state machine has us muted; discard the chunk
                evt = {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode("ascii"),
                }
                await ws.send(json.dumps(evt))
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.exception("uplink error: %s", e)
            raise

    async def _downlink(self, ws):
        try:
            async for raw in ws:
                try:
                    evt = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("non-json frame: %r", raw[:120])
                    continue
                await self._handle_event(ws, evt)
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.exception("downlink error: %s", e)
            raise

    async def _handle_event(self, ws, evt: Dict[str, Any]):
        t = evt.get("type", "")
        if t == "response.audio.delta":
            b64 = evt.get("delta", "")
            if b64:
                self.speaker.write(base64.b64decode(b64))
                if self.on_response_audio_delta is not None:
                    try:
                        self.on_response_audio_delta()
                    except Exception:
                        log.exception("on_response_audio_delta raised")
        elif t == "response.audio.done":
            pass
        elif t == "response.audio_transcript.delta":
            piece = evt.get("delta", "")
            if piece:
                print(piece, end="", flush=True)
                if self.spoken_cache is not None:
                    self.spoken_cache.add(piece)
        elif t == "response.audio_transcript.done":
            print()  # newline
            transcript = evt.get("transcript", "")
            if transcript and self.spoken_cache is not None:
                self.spoken_cache.add(transcript)
        elif t == "conversation.item.input_audio_transcription.completed":
            transcript = evt.get("transcript", "")
            if transcript:
                print(f"\n[user] {transcript}", flush=True)
        elif t == "input_audio_buffer.speech_started":
            log.debug("user speech started")
            # NOTE: do NOT clear the speaker here. The state machine drives
            # barge-in via the wake-word detector. server_vad is off anyway.
        elif t == "response.done":
            if self.on_response_done is not None:
                try:
                    self.on_response_done()
                except Exception:
                    log.exception("on_response_done raised")
        elif t == "response.function_call_arguments.done":
            await self._dispatch_tool(ws, evt)
        elif t == "error":
            log.error("realtime error: %s", evt.get("error"))
        elif t in ("session.created", "session.updated", "response.created",
                   "rate_limits.updated", "response.output_item.added",
                   "response.output_item.done", "response.content_part.added",
                   "response.content_part.done", "input_audio_buffer.committed",
                   "input_audio_buffer.speech_stopped", "conversation.item.created"):
            log.debug("rt event: %s", t)
        else:
            log.debug("rt event (unhandled): %s", t)

    async def _dispatch_tool(self, ws, evt: Dict[str, Any]):
        call_id = evt.get("call_id")
        name = evt.get("name")
        try:
            args = json.loads(evt.get("arguments", "") or "{}")
        except json.JSONDecodeError:
            args = {}

        log.info("tool call: %s(%s)", name, args)
        ok, reason, sanitized = await self.safety.validate(name, args)
        if not ok:
            result = {"ok": False, "reason": reason}
        else:
            try:
                result = await self._execute_tool(name, sanitized)
            except Exception as e:
                log.exception("tool exception: %s", e)
                result = {"ok": False, "reason": f"exception: {e!s}"}

        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result, ensure_ascii=False),
            },
        }))
        # Ask the model to continue (turn the tool result into a spoken reply).
        await ws.send(json.dumps({"type": "response.create"}))

    async def _execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "say":
            await self.tts.speak(args["text"])
            return {"ok": True}
        if name == "describe_scene":
            jpeg_b64 = self.camera.latest_jpeg_b64(
                width=self.vision_resize_width,
                jpeg_quality=self.vision_jpeg_quality,
            )
            if jpeg_b64 is None:
                return {"ok": False, "reason": "no frame available"}
            user_q = args.get("question") or ""
            prompt = VISION_SCENE_PROMPT
            if user_q:
                prompt = prompt + f"\nUser question: {user_q}"
            text = await self.vision.describe(
                image_jpeg_b64=jpeg_b64,
                prompt=prompt,
                detail=args.get("detail", "medium"),
            )
            return {"ok": True, "description": text}
        if self.skills is None:
            return {"ok": False, "reason": "skills disabled (--no-skills)"}
        if name == "stop":
            return await self.skills.stop()
        if name == "release_arms":
            return await self.skills.release_arms()
        if name == "walk":
            return await self.skills.walk(
                vx=args.get("vx", 0.0),
                vy=args.get("vy", 0.0),
                wz=args.get("wz", 0.0),
                duration_s=args["duration_s"],
            )
        if name == "gesture":
            return await self.skills.gesture(args["name"])
        return {"ok": False, "reason": f"unknown tool: {name}"}

    # ---------- public hooks for the ConversationStateMachine ----------

    async def commit_and_respond(self):
        if self._ws is None:
            return
        await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await self._ws.send(json.dumps({"type": "response.create"}))

    async def cancel_response(self):
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "response.cancel"}))
        except Exception as e:
            log.debug("response.cancel send failed (likely no active response): %s", e)
        self.speaker.clear()

    def set_uplink_enabled(self, enabled: bool):
        if enabled:
            self._uplink_enabled.set()
        else:
            self._uplink_enabled.clear()
