"""OpenAI Audio Speech (TTS) -> SpeakerStream.

Streams PCM16 24 kHz directly into the speaker so the demo can speak canned
strings without going through a Realtime turn.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .audio_io import SpeakerStream

log = logging.getLogger(__name__)


class TTSClient:
    def __init__(
        self,
        client,
        speaker: "SpeakerStream",
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
    ):
        self._client = client
        self._speaker = speaker
        self._model = model
        self._voice = voice

    async def speak(self, text: str, voice: str | None = None):
        if not text:
            return
        loop = asyncio.get_event_loop()
        voice_id = voice or self._voice

        def _stream():
            try:
                with self._client.audio.speech.with_streaming_response.create(
                    model=self._model,
                    voice=voice_id,
                    input=text,
                    response_format="pcm",
                ) as resp:
                    for chunk in resp.iter_bytes(chunk_size=4096):
                        if chunk:
                            self._speaker.write(chunk)
            except AttributeError:
                # Older SDK fallback: get the bytes in one shot.
                audio = self._client.audio.speech.create(
                    model=self._model,
                    voice=voice_id,
                    input=text,
                    response_format="pcm",
                )
                self._speaker.write(audio.read())
            except Exception as e:
                log.exception("tts failed: %s", e)

        await loop.run_in_executor(None, _stream)
