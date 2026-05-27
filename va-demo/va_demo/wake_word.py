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
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional, Protocol

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


class OpenAITranscribeBackend:
    """Cloud backend using OpenAI's audio.transcriptions API.

    Each transcribe() call is a network round-trip (~200-500ms) and bills per
    audio second. With WakeWordDetector at inference_rate_hz=2.0 you submit a
    1.5 s window twice a second whenever RMS gates open, so idle cost is bounded
    by how often you cross rms_threshold. Use only with OPENAI_API_KEY exported.

    `prompt` biases the model toward proper-noun phrases like "Sparky" that
    Whisper-class models otherwise garble; pass the wake phrase here.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini-transcribe",
        prompt: Optional[str] = "Sparky",
        language: Optional[str] = None,
    ):
        from openai import OpenAI

        self._client = OpenAI()
        self._model = model
        self._prompt = prompt
        self._language = language
        log.info(
            "OpenAITranscribeBackend ready: model=%s prompt=%r language=%s",
            model, prompt, language,
        )

    def transcribe(self, pcm: bytes, samplerate: int) -> str:
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)  # int16
            w.setframerate(samplerate)
            w.writeframes(pcm)
        wav_bytes = buf.getvalue()
        kwargs: dict = {
            "model": self._model,
            "file": ("audio.wav", wav_bytes, "audio/wav"),
        }
        if self._prompt:
            kwargs["prompt"] = self._prompt
        if self._language:
            kwargs["language"] = self._language
        result = self._client.audio.transcriptions.create(**kwargs)
        return (result.text or "").strip()


class WakeWordDetector:
    def __init__(
        self,
        backend: TranscriptionBackend,
        spoken_cache,
        on_wake: Callable[[WakeEvent], None],
        samplerate: int = 24000,
        rolling_window_s: float = 1.5,
        inference_rate_hz: float = 2.0,
        rms_threshold: int = 100,
        cooldown_s: float = 2.0,
        phrases: Optional[List[str]] = None,
        selfecho_window_s: float = 6.0,
        speaker_ref: Optional[object] = None,
        aec_gain: float = 0.0,
        aec_delay_s: float = 0.2,
        cleaned_rms_threshold: float = 0.0,
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
        # Post-AEC RMS gate. Raw mic RMS is dominated by the bot's speaker
        # echo during SPEAKING, so the raw `rms_threshold` is permanently
        # tripped open while TTS plays — every loop iteration sends a
        # transcribe call to the network even when the user is silent. The
        # synchronous transcribe (200–500 ms per call on the OpenAI route)
        # holds the worker thread, so by the time the user actually says
        # "Hi Sparky" the loop is mid-call on a bot-only snapshot and the
        # NEXT iteration is the one that finally looks at the user's audio.
        # That race is the bulk of the operator-reported "first miss,
        # second hit" pattern.
        #
        # The fix: after AEC subtracts the speaker bytes, gate the
        # transcribe call by the *cleaned* signal's RMS. When the user is
        # silent the cleaned signal is just AEC residual (small); when the
        # user is talking it spikes (user voice survives the subtraction
        # because it's uncorrelated with the bot's output). Skipping the
        # silent-user transcribes keeps the worker thread responsive and
        # focuses each network call on a snapshot likely to contain real
        # user speech — both of which directly raise first-attempt hit
        # rate during TTS playback.
        #
        # Default 0 disables the gate (preserves bit-for-bit behaviour on
        # call sites that don't opt in, including the existing test
        # suite). The yaml config sets a meaningful production value.
        self._cleaned_rms_threshold = float(cleaned_rms_threshold)
        # ---- echo subtraction ------------------------------------------
        # When the bot is talking, the mic captures speaker output much
        # louder than the user's "Hi Sparky"; the transcribe call returns
        # mostly the bot's narration and the wake phrase never matches.
        # If a speaker reference is wired in, we subtract a time-aligned,
        # scaled copy of the recently-played speaker bytes from the mic
        # snapshot before transcribing. Gain of 0.0 disables this path
        # (default — preserves pre-fix behaviour bit-for-bit on call sites
        # that don't pass a speaker_ref). Gain of ~0.5-1.0 is typical for
        # a laptop with mic + speaker close together; tune per rig.
        self._speaker_ref = speaker_ref
        self._aec_gain = float(aec_gain)
        self._aec_delay_s = float(aec_delay_s)

        self._buf = bytearray()
        self._buf_lock = threading.Lock()
        self._paused = threading.Event()
        self._stopped = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_fire = 0.0

        # Worker-thread liveness heartbeat. Each loop iteration appends a
        # monotonic timestamp; worker_healthy() reports whether the thread is
        # cycling near its configured rate. A worker starved of the GIL/CPU by
        # the boot-time perception + codex load ticks far slower than
        # ``period_s`` — agent_main gates the "say Hi Sparky" banner on this so
        # it is never printed while the detector physically cannot run.
        self._tick_times: Deque[float] = deque()
        self._tick_lock = threading.Lock()

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

    def _record_tick(self) -> None:
        """Heartbeat: one timestamp per worker-loop iteration (post-sleep)."""
        now = time.monotonic()
        with self._tick_lock:
            self._tick_times.append(now)
            cutoff = now - 30.0
            while self._tick_times and self._tick_times[0] < cutoff:
                self._tick_times.popleft()

    def worker_healthy(self, min_ticks: int = 3, max_factor: float = 3.0) -> bool:
        """True once the worker thread is cycling near its configured rate.

        The worker sleeps ``period_s`` then needs the GIL to continue; when
        perception/codex saturate the box at boot it cannot re-acquire the GIL
        promptly, so it ticks far slower than ``inference_rate_hz``. We count
        ticks over a span of a few healthy periods and return False until the
        thread catches up — letting the caller hold the "say Hi Sparky" banner
        until the detector can actually hear the operator. Returns False before
        the worker has started (no ticks yet).
        """
        window_s = max(1.0, max_factor * self._period_s * min_ticks)
        now = time.monotonic()
        with self._tick_lock:
            recent = sum(1 for t in self._tick_times if t >= now - window_s)
        return recent >= min_ticks

    def _loop(self) -> None:
        while not self._stopped.is_set():
            time.sleep(self._period_s)
            self._record_tick()
            if self._paused.is_set():
                continue
            with self._buf_lock:
                if len(self._buf) < self._window_bytes // 2:
                    log.debug("buf too small: %d < %d", len(self._buf), self._window_bytes // 2)
                    continue
                snapshot = bytes(self._buf)
            rms_val = self._rms(snapshot)
            if rms_val < self._rms_threshold:
                log.debug("rms gate: %.0f < %d (skip)", rms_val, self._rms_threshold)
                continue
            log.debug("rms gate: %.0f >= %d (transcribe)", rms_val, self._rms_threshold)
            transcribe_input = self._aec_subtract(snapshot)
            # Post-AEC gate: if the cleaned signal is below threshold the
            # snapshot is bot-residual only (or silence); transcribing it
            # just burns network round-trip on a result that can't match
            # the wake phrase and starves the next snapshot — which is the
            # one that finally has the user's voice. Skip and loop again.
            # Only applied when the threshold is configured AND AEC is
            # actually active; otherwise the cleaned signal equals the raw
            # mic and the gate would be redundant with the raw RMS gate.
            if (
                self._cleaned_rms_threshold > 0.0
                and self._speaker_ref is not None
                and self._aec_gain > 0.0
                and transcribe_input is not snapshot
            ):
                cleaned_rms = self._rms(transcribe_input)
                if cleaned_rms < self._cleaned_rms_threshold:
                    log.debug(
                        "cleaned rms gate: %.0f < %.0f (skip; raw was %.0f)",
                        cleaned_rms, self._cleaned_rms_threshold, rms_val,
                    )
                    continue
                log.debug(
                    "cleaned rms gate: %.0f >= %.0f (transcribe; raw %.0f)",
                    cleaned_rms, self._cleaned_rms_threshold, rms_val,
                )
            try:
                text = self._backend.transcribe(transcribe_input, self._samplerate)
            except Exception as e:
                log.warning("wake-word backend error: %s", e)
                continue
            log.debug("transcript: %r", text)
            if not text:
                continue
            normalized = self._normalize(text)
            if not any(p in normalized for p in self._phrases):
                log.debug("no phrase match in normalized=%r (phrases=%r)", normalized, self._phrases)
                continue
            cache_text = self._cache.recent_text(self._selfecho_window_s)
            if any(p in cache_text for p in self._phrases):
                log.debug("wake suppressed by self-echo dedup: %r", text)
                continue
            now = time.monotonic()
            if now - self._last_fire < self._cooldown_s:
                log.debug("wake suppressed by cooldown")
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

    def _aec_subtract(self, mic_pcm: bytes) -> bytes:
        """Subtract time-aligned speaker output from the mic snapshot.

        Returns ``mic_pcm`` unchanged when no speaker reference is wired
        (gain stays at 0, or recent_played_pcm is unavailable) — so call
        sites that don't opt in see no behavioural change.

        When wired and active, retrieves the speaker bytes that drove the
        device ``aec_delay_s`` seconds ago, end-aligns them with the mic
        snapshot, and subtracts ``gain * speaker`` sample-by-sample. The
        intent is to make the bot's own voice quiet enough in the
        transcribe input that the user's "Hi Sparky" survives — a perfect
        AEC would need an adaptive filter, but a fixed-delay subtraction
        is enough for the laptop-mic case where speaker and mic are
        electrically dry-coupled by the WSL2 PulseAudio bridge.

        Defensive: any exception is logged and the original mic snapshot
        is returned unchanged so a numeric edge case can never silence
        wake-word detection entirely.
        """
        if self._speaker_ref is None or self._aec_gain <= 0.0:
            return mic_pcm
        getter = getattr(self._speaker_ref, "recent_played_pcm", None)
        if getter is None:
            return mic_pcm
        try:
            window_s = len(mic_pcm) / 2.0 / float(self._samplerate)
            spk_pcm = getter(window_s, delay_s=self._aec_delay_s)
            if not spk_pcm:
                return mic_pcm
            mic_arr = np.frombuffer(mic_pcm, dtype=np.int16).astype(np.int32)
            spk_arr = np.frombuffer(spk_pcm, dtype=np.int16).astype(np.int32)
            n = min(mic_arr.size, spk_arr.size)
            if n <= 0:
                return mic_pcm
            mic_tail = mic_arr[-n:]
            spk_tail = spk_arr[-n:]
            cleaned_tail = mic_tail - (self._aec_gain * spk_tail).astype(np.int32)
            np.clip(cleaned_tail, -32768, 32767, out=cleaned_tail)
            cleaned_tail = cleaned_tail.astype(np.int16)
            if mic_arr.size > n:
                prefix = mic_arr[:-n].astype(np.int16)
                return prefix.tobytes() + cleaned_tail.tobytes()
            return cleaned_tail.tobytes()
        except Exception:  # noqa: BLE001 — never break the wake path
            log.debug("AEC subtract failed; using raw mic snapshot", exc_info=True)
            return mic_pcm
