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
import time
from collections import deque
from typing import Deque, List, Optional, Tuple

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

    A loose sanity cap (~10 min of audio) is kept so a runaway producer can't
    grow memory without bound. The cap used to be 60 s, but long bilingual
    Realtime replies (Chinese narration of a recall result is ~1 min of TTS,
    streamed from the API in <1 s) routinely exceeded that, and the drop-
    from-front behaviour produced audible audio jumps mid-sentence ("声音
    说话不清晰"). 10 min × 24 kHz × 2 B ≈ 29 MB — fine to keep resident.
    """

    SANITY_CAP_SECONDS = 600

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
        # Rolling (timestamp, rms) of chunks actually shipped to the device
        # in the playback callback. Consumers (echo-aware barge-in detector)
        # ask "how loud is the speaker right now?" — and the right answer is
        # the chunk PortAudio just consumed, not the chunk that just got
        # write()'d (which may be tens of seconds ahead of the playhead when
        # the Realtime API streams faster than realtime).
        self._played_rms_history: Deque[Tuple[float, float]] = deque()
        self._played_rms_lock = threading.Lock()
        self._played_rms_window_s = 1.0
        # Rolling (timestamp, bytes) of raw PCM chunks shipped to the device.
        # The wake-word detector reads this through ``recent_played_pcm`` to
        # perform a simple time-domain echo subtraction on the mic snapshot
        # before transcribing during SPEAKING — without that subtraction the
        # mic is dominated by the bot's own narration and the user saying
        # "Hi Sparky" never makes it into the transcript, so wake-word
        # barge-in fails for the entire duration of a long reply.
        # Window cap is conservative; long enough to cover the wake-word's
        # 1.5 s rolling buffer plus alignment slack.
        self._played_pcm_history: Deque[Tuple[float, bytes]] = deque()
        self._played_pcm_lock = threading.Lock()
        self._played_pcm_window_s = 3.0

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
        # Record what the device just received so an echo-aware mic
        # consumer can ask "is the speaker hot right now?". Keep it cheap:
        # one np.frombuffer + one sqrt per ~20 ms block, evicting older
        # than _played_rms_window_s. The lock guards the deque only.
        try:
            arr = np.frombuffer(chunk, dtype=np.int16)
            if arr.size:
                arrf = arr.astype(np.float32, copy=False)
                rms_val = float(np.sqrt(float(np.mean(arrf * arrf))))
            else:
                rms_val = 0.0
            now = time.monotonic()
            cutoff = now - self._played_rms_window_s
            with self._played_rms_lock:
                self._played_rms_history.append((now, rms_val))
                while (
                    self._played_rms_history
                    and self._played_rms_history[0][0] < cutoff
                ):
                    self._played_rms_history.popleft()
            # Also record the raw bytes for the wake-word AEC path. Same
            # cadence as RMS (one entry per device callback) so the two
            # histories stay in lock-step on the timeline. We store a copy
            # because PortAudio reuses the outdata buffer between callbacks.
            pcm_cutoff = now - self._played_pcm_window_s
            with self._played_pcm_lock:
                self._played_pcm_history.append((now, bytes(chunk)))
                while (
                    self._played_pcm_history
                    and self._played_pcm_history[0][0] < pcm_cutoff
                ):
                    self._played_pcm_history.popleft()
        except Exception:  # noqa: BLE001 — must never raise from audio cb
            pass

    def recent_played_pcm(
        self,
        window_s: float,
        *,
        delay_s: float = 0.0,
    ) -> bytes:
        """Last ``window_s`` seconds of raw PCM shipped to the device.

        Returns the bytes that were emitted in the time interval
        ``[now - delay_s - window_s, now - delay_s]``, concatenated in
        order. ``delay_s`` shifts the window backward in time to compensate
        for the speaker→air→mic propagation delay; the caller picks the
        value that matches their pipeline (typical: speaker_latency +
        mic_latency, ~0.2 s on this rig).

        Returned bytes are int16 mono at ``self.samplerate``. The result
        may be shorter than ``window_s * samplerate * 2`` when the speaker
        has not been running long enough to fill the requested window;
        callers should align against the *end* of the buffer (most recent
        sample) and treat any missing bytes as leading silence.

        Cheap: deque scan + bytes.join — no copying of the underlying
        chunks. Safe to call from any thread.
        """
        if window_s <= 0:
            return b""
        now = time.monotonic()
        hi = now - max(delay_s, 0.0)
        lo = hi - window_s
        with self._played_pcm_lock:
            chunks = [b for t, b in self._played_pcm_history if lo <= t <= hi]
        if not chunks:
            return b""
        # Concatenate, then truncate from the front if the deque happened
        # to span more than `window_s` (defensive — eviction handles the
        # common case but a long-deferred eviction during a hot loop could
        # leave extras).
        out = b"".join(chunks)
        max_bytes = int(window_s * self.samplerate) * self.bytes_per_sample
        if len(out) > max_bytes:
            out = out[-max_bytes:]
        return out

    def recent_played_rms(self, window_s: float = 0.2) -> float:
        """RMS of audio shipped to the device in the last ``window_s`` s.

        Reflects what the speaker is *actually* playing right now (modulo
        PortAudio's ~20–200 ms output latency), not what was written into
        ``self._buf`` — the buffer may be many seconds ahead of the playhead
        when the producer streams faster than realtime. Used by the brain's
        echo-aware barge-in: predict how loud the mic should be picking up
        the speaker, compare to actual mic RMS, fire if user voice clearly
        rides above the echo.
        """
        now = time.monotonic()
        cutoff = now - max(window_s, 0.0)
        with self._played_rms_lock:
            recent = [r for t, r in self._played_rms_history if t >= cutoff]
        if not recent:
            return 0.0
        arr = np.asarray(recent, dtype=np.float32)
        return float(np.sqrt(float(np.mean(arr * arr))))

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
