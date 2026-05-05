"""OpenAI Responses API vision call (single frame -> short text).

Used as the `describe_scene` tool of the Realtime agent.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

log = logging.getLogger(__name__)


class VisionClient:
    def __init__(
        self,
        client,
        model: str = "gpt-5.5",
        default_detail: str = "auto",
        timeout_s: float = 15.0,
    ):
        self._client = client
        self._model = model
        self._default_detail = default_detail
        self._timeout_s = timeout_s

    async def describe(
        self,
        image_jpeg_b64: str,
        prompt: str,
        detail: Optional[str] = None,
    ) -> str:
        """Run one vision call; returns the model's text response."""

        detail = detail or self._default_detail
        loop = asyncio.get_event_loop()

        def _call() -> str:
            data_url = f"data:image/jpeg;base64,{image_jpeg_b64}"
            inputs = [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url, "detail": detail},
                    ],
                }
            ]
            try:
                resp = self._client.responses.create(model=self._model, input=inputs)
                text = getattr(resp, "output_text", None)
                if text:
                    return text
                # Fall back to walking the structured output if needed.
                output = getattr(resp, "output", None) or []
                pieces = []
                for item in output:
                    contents = getattr(item, "content", None) or []
                    for c in contents:
                        t = getattr(c, "text", None)
                        if t:
                            pieces.append(t)
                return "\n".join(pieces) if pieces else ""
            except AttributeError:
                # Older SDK: fall back to chat.completions.
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": data_url,
                                        "detail": detail,
                                    },
                                },
                            ],
                        }
                    ],
                )
                return resp.choices[0].message.content or ""

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _call), timeout=self._timeout_s
            )
        except asyncio.TimeoutError:
            log.warning("vision request timed out after %.1fs", self._timeout_s)
            return "(vision request timed out)"
        except Exception as e:
            log.exception("vision request failed: %s", e)
            return f"(vision request failed: {e!s})"
