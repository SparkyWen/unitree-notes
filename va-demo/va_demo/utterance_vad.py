"""End-of-utterance detector built on webrtcvad.

Caller feeds 24 kHz PCM16 mono chunks (same format as MicStream). We
resample to 16 kHz (linear stride decimation; precision is fine for VAD),
slice into 30 ms frames, and track:
  - consecutive_silence_ms (reset on voiced frame)
  - total_duration_ms (wall-clock since first chunk after reset)
  - had_any_voice flag (so a wake fire with zero speech can time out
    instead of committing pure silence)
"""
from __future__ import annotations

import logging
from typing import Literal

import numpy as np

log = logging.getLogger(__name__)

Status = Literal["continue", "commit_silence", "commit_max"]

VAD_SR = 16000  # webrtcvad supports 8/16/32/48 kHz
VAD_FRAME_MS = 30
VAD_FRAME_SAMPLES = VAD_SR * VAD_FRAME_MS // 1000  # 480


class UtteranceVAD:
    def __init__(
        self,
        samplerate: int = 24000,
        silence_threshold_ms: int = 1500,
        max_duration_s: float = 30.0,
        aggressiveness: int = 2,
        vad=None,
    ):
        if vad is None:
            import webrtcvad

            vad = webrtcvad.Vad(aggressiveness)
        self._vad = vad
        self.samplerate = samplerate
        self.silence_threshold_ms = silence_threshold_ms
        self.max_duration_ms = int(max_duration_s * 1000)
        self._consecutive_silence_ms = 0
        self._total_ms = 0
        self._had_voice = False
        self._leftover_24k = b""
        self._leftover_16k = b""

    def reset(self) -> None:
        self._consecutive_silence_ms = 0
        self._total_ms = 0
        self._had_voice = False
        self._leftover_24k = b""
        self._leftover_16k = b""

    def had_any_voice(self) -> bool:
        return self._had_voice

    def process(self, pcm24k: bytes) -> Status:
        # Stage 1: resample 24 kHz -> 16 kHz, preserving any tail samples
        # that didn't form a complete input triple.
        combined = self._leftover_24k + pcm24k
        n_bytes_24 = (len(combined) // 2) * 2
        usable = combined[:n_bytes_24]
        new_resampled_bytes = b""
        if usable:
            arr = np.frombuffer(usable, dtype=np.int16)
            cut = (len(arr) // 3) * 3
            if cut > 0:
                # 3 input samples -> 2 output samples (avg of adjacent pairs).
                a3 = arr[:cut].reshape(-1, 3).astype(np.int32)
                out0 = ((a3[:, 0] + a3[:, 1]) // 2).astype(np.int16)
                out1 = ((a3[:, 1] + a3[:, 2]) // 2).astype(np.int16)
                resampled = np.empty(len(a3) * 2, dtype=np.int16)
                resampled[0::2] = out0
                resampled[1::2] = out1
                new_resampled_bytes = resampled.tobytes()
            self._leftover_24k = arr[cut:].tobytes() + combined[n_bytes_24:]
        else:
            self._leftover_24k = combined

        # Stage 2: combine fresh 16 kHz audio with any prior 16 kHz tail,
        # then slice into 30 ms frames. Preserve fractional-frame tails for
        # the next call so we never silently drop audio.
        pcm16k = self._leftover_16k + new_resampled_bytes
        frame_bytes = VAD_FRAME_SAMPLES * 2  # int16 mono
        n_frames = len(pcm16k) // frame_bytes
        used = n_frames * frame_bytes
        self._leftover_16k = pcm16k[used:]

        for i in range(n_frames):
            frame = pcm16k[i * frame_bytes : (i + 1) * frame_bytes]
            is_speech = self._vad.is_speech(frame, VAD_SR)
            self._total_ms += VAD_FRAME_MS
            if is_speech:
                self._had_voice = True
                self._consecutive_silence_ms = 0
            else:
                self._consecutive_silence_ms += VAD_FRAME_MS

            if self._total_ms >= self.max_duration_ms:
                return "commit_max"
            if (
                self._had_voice
                and self._consecutive_silence_ms >= self.silence_threshold_ms
            ):
                return "commit_silence"

        return "continue"
