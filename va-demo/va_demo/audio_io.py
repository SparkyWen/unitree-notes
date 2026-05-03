"""sounddevice mic capture and speaker playback for the Realtime audio loop.

PCM16 mono at 24 kHz to match OpenAI Realtime + TTS pcm output.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class MicStream:
    """Captures PCM16 mono frames from the default input device into an asyncio queue."""

    def __init__(
        self,
        samplerate: int = 24000,
        block_ms: int = 50,
        device: Optional[int] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        max_queue: int = 32,
    ):
        import sounddevice as sd

        self._sd = sd
        self.samplerate = samplerate
        self.block_frames = int(samplerate * block_ms / 1000)
        self.device = device
        # Resolve the loop lazily so MicStream can be constructed before the loop runs.
        self.loop = loop
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max_queue)
        self._stream: Optional["sd.RawInputStream"] = None
        self._closed = False

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.debug("mic status: %s", status)
        chunk = bytes(indata)
        try:
            self.loop.call_soon_threadsafe(self._enqueue_nowait, chunk)
        except RuntimeError:
            pass

    def _enqueue_nowait(self, chunk: bytes):
        if self._closed:
            return
        try:
            self.queue.put_nowait(chunk)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.queue.put_nowait(chunk)
            except asyncio.QueueFull:
                pass

    def start(self):
        if self.loop is None:
            self.loop = asyncio.get_event_loop()
        self._stream = self._sd.RawInputStream(
            samplerate=self.samplerate,
            blocksize=self.block_frames,
            dtype="int16",
            channels=1,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        log.info(
            "mic started: samplerate=%d, block_frames=%d, device=%s",
            self.samplerate,
            self.block_frames,
            self.device,
        )

    def close(self):
        self._closed = True
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                log.warning("error closing mic: %s", e)
            self._stream = None


class SpeakerStream:
    """Plays PCM16 mono bytes pushed via `write()`. Thread-safe.

    Uses a ring queue so a slow producer doesn't block; a fast producer
    just builds backlog up to ~speaker_buffer_ms then drops oldest.
    """

    def __init__(
        self,
        samplerate: int = 24000,
        device: Optional[int] = None,
        buffer_ms: int = 200,
    ):
        import sounddevice as sd

        self._sd = sd
        self.samplerate = samplerate
        self.device = device
        self.bytes_per_sample = 2
        self.max_bytes = int(samplerate * buffer_ms / 1000) * self.bytes_per_sample * 4
        self._lock = threading.Lock()
        self._buf = bytearray()
        self._stream: Optional["sd.RawOutputStream"] = None

    def _callback(self, outdata, frames, time_info, status):
        if status:
            log.debug("speaker status: %s", status)
        need = frames * self.bytes_per_sample
        with self._lock:
            avail = len(self._buf)
            if avail >= need:
                chunk = bytes(self._buf[:need])
                del self._buf[:need]
            else:
                chunk = bytes(self._buf) + b"\x00" * (need - avail)
                self._buf.clear()
        outdata[:] = chunk

    def start(self):
        self._stream = self._sd.RawOutputStream(
            samplerate=self.samplerate,
            blocksize=0,
            dtype="int16",
            channels=1,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        log.info("speaker started: samplerate=%d, device=%s", self.samplerate, self.device)

    def write(self, pcm_bytes: bytes):
        if not pcm_bytes:
            return
        with self._lock:
            self._buf.extend(pcm_bytes)
            if len(self._buf) > self.max_bytes:
                drop = len(self._buf) - self.max_bytes
                del self._buf[:drop]

    def clear(self):
        with self._lock:
            self._buf.clear()

    def close(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                log.warning("error closing speaker: %s", e)
            self._stream = None


def rms(pcm16: bytes) -> float:
    """RMS of a PCM16 mono buffer; useful for the audio_loopback debug script."""
    if not pcm16:
        return 0.0
    arr = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(arr * arr)))
