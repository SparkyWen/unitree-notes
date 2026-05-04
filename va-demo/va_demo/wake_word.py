"""Local wake-word detector using a pluggable transcription backend.

Default backend is faster-whisper tiny on CPU int8. Tests inject a fake
backend that returns scripted transcripts, so the matching / RMS-gate /
cooldown / dedup logic can be unit-tested without a model.

The detector owns a worker thread. The state machine feeds it raw mic
PCM via .feed(); the worker batches it into a rolling window and runs
the backend at most inference_rate_hz times per second. On a positive
match (after gates), it calls on_wake(WakeEvent(...)) from the worker
thread — caller is responsible for marshaling to the asyncio loop.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class WakeEvent:
    text: str
    t: float


class TranscriptionBackend(Protocol):
    def transcribe(self, pcm: bytes, samplerate: int) -> str:
        ...


class FasterWhisperBackend:
    """Real backend wrapping faster-whisper. Loads the model in __init__."""

    def __init__(
        self,
        model_size: str = "tiny",
        compute_type: str = "int8",
        device: str = "cpu",
        language: Optional[str] = None,
    ):
        from faster_whisper import WhisperModel

        log.info(
            "loading faster-whisper model_size=%s compute_type=%s device=%s",
            model_size, compute_type, device,
        )
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._language = language

    def transcribe(self, pcm: bytes, samplerate: int) -> str:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if samplerate != 16000:
            ratio = 16000 / samplerate
            new_len = int(len(audio) * ratio)
            if new_len <= 0:
                return ""
            idx = (np.arange(new_len) / ratio).astype(np.int64)
            idx = np.clip(idx, 0, len(audio) - 1)
            audio = audio[idx]
        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=1,
            vad_filter=True,
            no_speech_threshold=0.6,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text for seg in segments).strip()


class WakeWordDetector:
    def __init__(
        self,
        backend: TranscriptionBackend,
        spoken_cache,
        on_wake: Callable[[WakeEvent], None],
        samplerate: int = 24000,
        rolling_window_s: float = 1.5,
        inference_rate_hz: float = 2.0,
        rms_threshold: int = 1500,
        cooldown_s: float = 2.0,
        phrases: Optional[List[str]] = None,
        selfecho_window_s: float = 6.0,
    ):
        self._backend = backend
        self._cache = spoken_cache
        self._on_wake = on_wake
        self._samplerate = samplerate
        self._window_bytes = int(samplerate * rolling_window_s) * 2  # int16 mono
        self._period_s = 1.0 / max(0.5, inference_rate_hz)
        self._rms_threshold = rms_threshold
        self._cooldown_s = cooldown_s
        self._phrases = [self._normalize(p) for p in (phrases or ["hi sparky"])]
        self._selfecho_window_s = selfecho_window_s

        self._buf = bytearray()
        self._buf_lock = threading.Lock()
        self._paused = threading.Event()
        self._stopped = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_fire = 0.0

    @staticmethod
    def _normalize(s: str) -> str:
        s = s.lower()
        # Keep ASCII letters/digits, spaces, and CJK unified ideographs.
        s = re.sub(r"[^a-z0-9一-鿿 ]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._loop, name="wake-word", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()
        with self._buf_lock:
            self._buf.clear()  # discard stale audio so we don't re-trigger

    def feed(self, pcm: bytes) -> None:
        if not pcm:
            return
        with self._buf_lock:
            self._buf.extend(pcm)
            if len(self._buf) > self._window_bytes:
                drop = len(self._buf) - self._window_bytes
                del self._buf[:drop]

    def _loop(self) -> None:
        while not self._stopped.is_set():
            time.sleep(self._period_s)
            if self._paused.is_set():
                continue
            with self._buf_lock:
                if len(self._buf) < self._window_bytes // 2:
                    continue
                snapshot = bytes(self._buf)
            if self._rms(snapshot) < self._rms_threshold:
                continue
            try:
                text = self._backend.transcribe(snapshot, self._samplerate)
            except Exception as e:
                log.warning("wake-word backend error: %s", e)
                continue
            if not text:
                continue
            normalized = self._normalize(text)
            if not any(p in normalized for p in self._phrases):
                continue
            cache_text = self._cache.recent_text(self._selfecho_window_s)
            if any(p in cache_text for p in self._phrases):
                log.debug("wake suppressed by self-echo dedup: %r", text)
                continue
            now = time.monotonic()
            if now - self._last_fire < self._cooldown_s:
                continue
            self._last_fire = now
            try:
                self._on_wake(WakeEvent(text=text, t=now))
            except Exception as e:
                log.exception("on_wake handler raised: %s", e)

    @staticmethod
    def _rms(pcm: bytes) -> float:
        if not pcm:
            return 0.0
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(arr * arr)))
