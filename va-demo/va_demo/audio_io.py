"""sounddevice mic capture and speaker playback for the Realtime audio loop.

PCM16 mono at 24 kHz to match OpenAI Realtime + TTS pcm output.

MicStream supports a fan-out: multiple consumers can subscribe() to get
their own asyncio.Queue. The legacy `mic.queue` attribute is an alias for
the first subscriber so existing single-consumer code keeps working.
"""
from __future__ import annotations

import asyncio
import ctypes
import logging
import sys
import threading
from typing import List, Optional

import numpy as np

log = logging.getLogger(__name__)


# --- ALSA stderr silencer ----------------------------------------------------
#
# libasound prints "ALSA lib pcm.c:NNNN:(snd_pcm_recover) [error.pcm] underrun
# occurred" directly to stderr through snd_lib_error_default. On WSL2 +
# PulseAudio those auto-recovered cosmetic warnings spam the agent's terminal
# at 5–20 Hz and bury actual log output. snd_lib_error_set_handler() lets us
# replace the default handler with a no-op while leaving recovery itself
# untouched. Held at module scope because libasound stores a raw pointer.
_ALSA_ERROR_HANDLER = None


def _silence_libasound_errors() -> None:
    global _ALSA_ERROR_HANDLER
    if _ALSA_ERROR_HANDLER is not None or not sys.platform.startswith("linux"):
        return
    try:
        proto = ctypes.CFUNCTYPE(
            None,
            ctypes.c_char_p,  # filename
            ctypes.c_int,     # line
            ctypes.c_char_p,  # function
            ctypes.c_int,     # err
            ctypes.c_char_p,  # fmt
        )

        def _noop(*_args, **_kwargs):
            return

        handler = proto(_noop)
        for libname in ("libasound.so.2", "libasound.so"):
            try:
                lib = ctypes.cdll.LoadLibrary(libname)
            except OSError:
                continue
            try:
                lib.snd_lib_error_set_handler(handler)
            except (AttributeError, OSError):
                continue
            _ALSA_ERROR_HANDLER = handler
            return
    except Exception:
        # Silencing is best-effort; never break process startup.
        return


_silence_libasound_errors()


class MicStream:
    """Captures PCM16 mono frames; supports multiple async listeners (fan-out)."""

    # Same rationale as SpeakerStream.DEFAULT_LATENCY_S: the WSL2 ALSA-pulse
    # plugin is happier when both directions request a generous buffer.
    DEFAULT_LATENCY_S = 0.10

    def __init__(
        self,
        samplerate: int = 24000,
        block_ms: int = 50,
        device: Optional[int] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        max_queue: int = 32,
        latency_s: Optional[float] = None,
    ):
        import sounddevice as sd

        self._sd = sd
        self.samplerate = samplerate
        self.block_frames = int(samplerate * block_ms / 1000)
        self.device = device
        self.loop = loop
        self._max_queue = max_queue
        self._latency = (
            self.DEFAULT_LATENCY_S if latency_s is None else float(latency_s)
        )
        self._listeners: List[asyncio.Queue[bytes]] = []
        self._listeners_lock = threading.Lock()
        self._stream: Optional["sd.RawInputStream"] = None
        self._closed = False
        # Eager first listener so existing code that uses mic.queue keeps working.
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max_queue)
        self._listeners.append(self.queue)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=self._max_queue)
        with self._listeners_lock:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._listeners_lock:
            try:
                self._listeners.remove(q)
            except ValueError:
                pass

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
        with self._listeners_lock:
            listeners = list(self._listeners)
        for q in listeners:
            try:
                q.put_nowait(chunk)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(chunk)
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
            latency=self._latency,
        )
        self._stream.start()
        log.info(
            "mic started: samplerate=%d, block_frames=%d, device=%s, latency=%.3fs",
            self.samplerate,
            self.block_frames,
            self.device,
            self._latency,
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

    The producer (OpenAI Realtime WS or TTS HTTP stream) typically delivers
    audio FASTER than realtime, so the buffer grows during a response and
    drains as the playback callback consumes it at the device sample rate.
    Use `clear()` to interrupt playback (e.g. on wake-word barge-in) — that
    is the correct way to stop unwanted audio, NOT capping the buffer.

    A loose sanity cap (~60 s of audio) is kept so a runaway producer can't
    grow memory without bound, but it's far above any real response length
    and is never hit in normal operation.
    """

    SANITY_CAP_SECONDS = 60

    # WSL2's PulseAudio bridge underruns aggressively when the Python
    # callback is delayed by GIL contention from perception/DDS/ML threads
    # in the same process. A non-trivial requested latency gives the
    # ALSA-pulse plugin a buffer big enough to hide those stalls so the
    # user actually hears a clean reply instead of a stuttering one.
    DEFAULT_LATENCY_S = 0.20

    # 20 ms blocks: a fixed blocksize gives PortAudio a predictable
    # callback cadence (a stark improvement over blocksize=0 on PulseAudio,
    # which produced highly variable callback intervals on WSL2). 20 ms is
    # short enough that `clear()` for barge-in still feels instant.
    DEFAULT_BLOCKSIZE_MS = 20

    def __init__(
        self,
        samplerate: int = 24000,
        device: Optional[int] = None,
        buffer_ms: int = 200,  # accepted for back-compat; not used as a hard cap
        latency_s: Optional[float] = None,
        blocksize_frames: Optional[int] = None,
    ):
        import sounddevice as sd

        self._sd = sd
        self.samplerate = samplerate
        self.device = device
        self.bytes_per_sample = 2
        self._sanity_cap_bytes = self.SANITY_CAP_SECONDS * samplerate * self.bytes_per_sample
        self._lock = threading.Lock()
        self._buf = bytearray()
        self._stream: Optional["sd.RawOutputStream"] = None
        self._latency = (
            self.DEFAULT_LATENCY_S if latency_s is None else float(latency_s)
        )
        self._blocksize = (
            int(samplerate * self.DEFAULT_BLOCKSIZE_MS / 1000)
            if blocksize_frames is None
            else int(blocksize_frames)
        )

    def pending_bytes(self) -> int:
        """How many bytes of audio are still queued to play out."""
        with self._lock:
            return len(self._buf)

    def pending_seconds(self) -> float:
        denom = max(1, self.samplerate * self.bytes_per_sample)
        return self.pending_bytes() / float(denom)

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
            blocksize=self._blocksize,
            dtype="int16",
            channels=1,
            device=self.device,
            callback=self._callback,
            latency=self._latency,
        )
        self._stream.start()
        log.info(
            "speaker started: samplerate=%d, device=%s, latency=%.3fs, blocksize=%d",
            self.samplerate, self.device, self._latency, self._blocksize,
        )

    def write(self, pcm_bytes: bytes):
        if not pcm_bytes:
            return
        with self._lock:
            self._buf.extend(pcm_bytes)
            if len(self._buf) > self._sanity_cap_bytes:
                drop = len(self._buf) - self._sanity_cap_bytes
                del self._buf[:drop]
                log.warning(
                    "speaker buffer exceeded sanity cap (%d s); dropped %d bytes — "
                    "this should not happen in normal operation",
                    self.SANITY_CAP_SECONDS, drop,
                )

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
