"""Audio codec bridge between Twilio Media Streams and OpenAI Realtime.

Twilio side:  G.711 μ-law, 8 kHz, mono, 160 B per 20 ms frame, base64-encoded
              inside `media` events.
OpenAI side:  PCM16 LE, 24 kHz, mono, base64 inside input_audio_buffer.append
              and response.output_audio.delta events.

Resampling uses scipy.signal.resample_poly (up=3, down=1 or up=1, down=3 —
integer ratios both ways).

`StreamingResampler` is a stateful wrapper that buffers residual samples
across calls, so we can hand it OpenAI's arbitrarily-chunked output deltas
and get whole-frame μ-law back to feed Twilio.
"""
from __future__ import annotations

import audioop
import base64
from typing import Iterator

import numpy as np
from scipy.signal import resample_poly


_MULAW_FRAME_BYTES = 160          # 8000 Hz × 1 byte × 20 ms
_PCM24K_FRAME_BYTES = 960         # 24000 Hz × 2 bytes × 20 ms
_PCM8K_FRAME_BYTES = 320          # 8000 Hz × 2 bytes × 20 ms


def mulaw8k_to_pcm24k(payload_b64: str) -> bytes:
    """Decode base64 μ-law 8k → bytes PCM16-LE 24k (3x upsample).

    Input typically 160 B μ-law (20 ms) → 960 B PCM (still 20 ms wall).
    """
    raw_mulaw = base64.b64decode(payload_b64)
    pcm8k = audioop.ulaw2lin(raw_mulaw, 2)          # 2 bytes/sample
    arr8k = np.frombuffer(pcm8k, dtype=np.int16)
    arr24k = resample_poly(arr8k, up=3, down=1).astype(np.int16)
    return arr24k.tobytes()


def pcm24k_to_mulaw8k(pcm: bytes) -> str:
    """Encode bytes PCM16-LE 24k → base64 μ-law 8k (3x downsample).

    pcm must be a whole number of int16 samples (even length).
    Caller's responsibility to chunk for 20 ms framing; this is stateless.
    """
    arr24k = np.frombuffer(pcm, dtype=np.int16)
    arr8k = resample_poly(arr24k, up=1, down=3).astype(np.int16)
    pcm8k = arr8k.tobytes()
    raw_mulaw = audioop.lin2ulaw(pcm8k, 2)
    return base64.b64encode(raw_mulaw).decode("ascii")


class StreamingResampler:
    """Stateful bidirectional resampler that retains < 1 frame of residual.

    Use one instance per call (it holds per-direction byte buffers).

    Outbound side (PCM24k → μ-law/8k):
      feed_pcm24k(pcm) yields zero or more base64 μ-law strings, each
      exactly 160 B (20 ms). Residual samples (< 960 B) are held until the
      next call. Useful because OpenAI deltas are arbitrarily sized.

    Inbound side (μ-law/8k → PCM24k):
      feed_mulaw8k(payload_b64) yields zero or more bytes chunks; in
      practice each Twilio `media` event is exactly one 20 ms frame, so
      each call yields exactly one 960 B chunk. Symmetric for safety.
    """

    def __init__(self) -> None:
        self._pcm_buf = bytearray()
        self._mulaw_buf = bytearray()

    # ---- outbound (us → Twilio) -----------------------------------------

    def feed_pcm24k(self, pcm: bytes) -> Iterator[str]:
        self._pcm_buf.extend(pcm)
        while len(self._pcm_buf) >= _PCM24K_FRAME_BYTES:
            chunk = bytes(self._pcm_buf[:_PCM24K_FRAME_BYTES])
            del self._pcm_buf[:_PCM24K_FRAME_BYTES]
            yield pcm24k_to_mulaw8k(chunk)

    # ---- inbound (Twilio → us) ------------------------------------------

    def feed_mulaw8k(self, payload_b64: str) -> Iterator[bytes]:
        raw = base64.b64decode(payload_b64)
        self._mulaw_buf.extend(raw)
        while len(self._mulaw_buf) >= _MULAW_FRAME_BYTES:
            frame = bytes(self._mulaw_buf[:_MULAW_FRAME_BYTES])
            del self._mulaw_buf[:_MULAW_FRAME_BYTES]
            yield mulaw8k_to_pcm24k(base64.b64encode(frame).decode("ascii"))

    # ---- maintenance ----------------------------------------------------

    def reset(self) -> None:
        self._pcm_buf.clear()
        self._mulaw_buf.clear()
