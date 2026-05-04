# Wake-Word + Barge-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Hi, Sparky" wake-word gate to va-demo so OpenAI Realtime stops cutting itself off, only the wake word interrupts mid-reply, and complete user utterances are committed in one shot.

**Architecture:** Insert a state machine (`IDLE → AWAKE → CAPTURING → THINKING → SPEAKING → LISTENING_WINDOW`) between the mic and the existing Realtime client. Two new audio listeners share the mic via a fan-out: a `faster-whisper`-tiny wake-word detector and a `webrtcvad`-based end-of-utterance detector. The Realtime session switches off `server_vad`; commits and `response.create` are now driven by the state machine.

**Tech Stack:** Python 3.11 (`agi` conda env), `faster-whisper>=1.0.3`, `webrtcvad-wheels>=2.0.14`, existing `openai`, `sounddevice`, `websockets`, `pyyaml`, `numpy`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-05-04-wake-word-design.md`.

**Working directory for all commands below:** `/home/helios/unitree/unitree-notes/va-demo` (run `cd ~/unitree/unitree-notes/va-demo` once at session start).

**Conda env:** `conda activate agi` before running anything Python.

---

## File Structure

**New (in order they appear in tasks):**

| Path | Purpose |
|---|---|
| `va_demo/spoken_cache.py` | Thread-safe rolling text buffer of what Sparky just said; used to suppress wake-word self-triggers. |
| `va_demo/utterance_vad.py` | Wraps `webrtcvad`; reports `commit_silence` / `commit_max` / `continue` from PCM frames. |
| `va_demo/wake_word.py` | Background thread running faster-whisper on a rolling 1.5 s buffer; emits wake events through a callback. |
| `va_demo/conversation_state.py` | The five-state machine; subscribes to mic, drives wake/utterance/realtime. |
| `tests/test_spoken_cache.py` | Unit tests for the cache. |
| `tests/test_utterance_vad.py` | Unit tests with synthesized PCM. |
| `tests/test_wake_word.py` | Unit tests with a fake whisper backend (DI). |
| `tests/test_conversation_state.py` | State machine tests with mocked components. |
| `scripts/wake_word_debug.py` | Live mic → wake-word detector only; prints matches. |

**Modified:**

| Path | What changes |
|---|---|
| `requirements.txt` | Add `faster-whisper`, `webrtcvad-wheels`. |
| `configs/va_demo.yaml` | Add `wakeword:`, `utterance:`, `conversation:` sections. |
| `va_demo/audio_io.py` | Add `MicStream.subscribe()` / `unsubscribe()` fan-out. |
| `va_demo/prompts.py` | Append "do not refer to yourself as Sparky" rule. |
| `va_demo/tts.py` | Push spoken text into `SpokenTranscriptCache` before streaming. |
| `va_demo/realtime_agent.py` | `turn_detection: null`, expose `commit_and_respond` / `cancel_response` / `set_uplink_enabled`, drop auto barge-in `speaker.clear()`, write transcripts into spoken cache. |
| `va_demo/main.py` | Build cache, wake-word, vad, state machine; pass `--no-wakeword` flag through. |
| `README.md` | New "Wake-word usage" section + first-run model download note. |

---

## Task 1: Add new dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Edit requirements.txt**

Replace existing content (`openai>=1.55.0`, `sounddevice>=0.4.7`, `websockets>=12`, `pyyaml`, `numpy`, `opencv-python`, `pyzmq`) with:

```
openai>=1.55.0
sounddevice>=0.4.7
websockets>=12
pyyaml
numpy
opencv-python
pyzmq
faster-whisper>=1.0.3
webrtcvad-wheels>=2.0.14
```

- [ ] **Step 2: Install into the agi env**

Run:
```bash
conda activate agi
pip install -r requirements.txt
```

Expected: faster-whisper resolves (it pulls ctranslate2, onnxruntime, tokenizers); webrtcvad-wheels installs as a single wheel. No build step needed on Linux.

- [ ] **Step 3: Verify imports work**

Run:
```bash
python -c "from faster_whisper import WhisperModel; import webrtcvad; print('ok')"
```

Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore(va-demo): add faster-whisper + webrtcvad deps"
```

---

## Task 2: SpokenTranscriptCache (TDD)

A small thread-safe ring buffer of `(text, timestamp)` segments, with one read method that joins recent segments inside a time window. Used by:
- `tts.py` (writer) — pushes the canned text it's about to speak
- `realtime_agent.py` (writer) — pushes each `response.audio_transcript.delta`
- `wake_word.py` (reader) — checks if the matched phrase appears in the recent window before firing

**Files:**
- Create: `va_demo/spoken_cache.py`
- Test: `tests/test_spoken_cache.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_spoken_cache.py`:

```python
"""Unit tests for SpokenTranscriptCache."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.spoken_cache import SpokenTranscriptCache


def test_write_and_recent_text_concatenates():
    c = SpokenTranscriptCache()
    c.add("Hello ")
    c.add("world.")
    assert "hello world." in c.recent_text(window_s=10.0)


def test_recent_text_lowercases():
    c = SpokenTranscriptCache()
    c.add("Hi There")
    assert c.recent_text(window_s=10.0) == "hi there"


def test_recent_text_drops_old_entries():
    c = SpokenTranscriptCache()
    c.add("ancient", t=time.monotonic() - 60.0)
    c.add("fresh")
    text = c.recent_text(window_s=5.0)
    assert "ancient" not in text
    assert "fresh" in text


def test_eviction_caps_size():
    c = SpokenTranscriptCache(max_age_s=1.0)
    c.add("old", t=time.monotonic() - 10.0)
    c.add("new")
    # Force eviction by reading.
    text = c.recent_text(window_s=10.0)
    assert "old" not in text
    assert "new" in text
    # Internal storage should also have shrunk.
    assert len(c._items) == 1


def test_thread_safety_smoke():
    c = SpokenTranscriptCache()
    stop = threading.Event()

    def writer():
        while not stop.is_set():
            c.add("x")

    def reader():
        while not stop.is_set():
            c.recent_text(window_s=1.0)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    stop.set()
    for t in threads:
        t.join(timeout=1.0)
        assert not t.is_alive()
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
python -m pytest tests/test_spoken_cache.py -v
```

Expected: ImportError or ModuleNotFoundError on `va_demo.spoken_cache`.

- [ ] **Step 3: Implement the cache**

Create `va_demo/spoken_cache.py`:

```python
"""Rolling buffer of recent text Sparky has spoken (TTS or Realtime).

Used to dedup wake-word self-triggers: if Sparky said "hi sparky" in its
own audio output and that audio leaked into the mic, we want to ignore it.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Tuple


class SpokenTranscriptCache:
    """Thread-safe ring of (text, monotonic_timestamp) segments."""

    def __init__(self, max_age_s: float = 30.0):
        self._items: Deque[Tuple[str, float]] = deque()
        self._lock = threading.Lock()
        self._max_age_s = max_age_s

    def add(self, text: str, t: float | None = None) -> None:
        if not text:
            return
        ts = t if t is not None else time.monotonic()
        with self._lock:
            self._items.append((text, ts))
            self._evict_locked()

    def recent_text(self, window_s: float) -> str:
        cutoff = time.monotonic() - window_s
        with self._lock:
            self._evict_locked()
            parts = [s for s, ts in self._items if ts >= cutoff]
        return "".join(parts).lower()

    def _evict_locked(self) -> None:
        cutoff = time.monotonic() - self._max_age_s
        while self._items and self._items[0][1] < cutoff:
            self._items.popleft()
```

- [ ] **Step 4: Run tests, verify they pass**

Run:
```bash
python -m pytest tests/test_spoken_cache.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add va_demo/spoken_cache.py tests/test_spoken_cache.py
git commit -m "feat(va-demo): add SpokenTranscriptCache for self-echo dedup"
```

---

## Task 3: UtteranceVAD (TDD)

Wraps `webrtcvad`. Caller feeds raw 24 kHz PCM16 chunks (matching `MicStream` output); the VAD resamples to 16 kHz internally and reports per-call whether to keep recording, commit because of silence, or commit because of max length.

**Files:**
- Create: `va_demo/utterance_vad.py`
- Test: `tests/test_utterance_vad.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_utterance_vad.py`:

```python
"""Unit tests for UtteranceVAD with synthesized PCM."""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.utterance_vad import UtteranceVAD

SR = 24000


def silence_chunk(ms: int) -> bytes:
    n = int(SR * ms / 1000)
    return b"\x00\x00" * n


def tone_chunk(ms: int, freq: int = 440, amp: int = 12000) -> bytes:
    n = int(SR * ms / 1000)
    samples = []
    for i in range(n):
        v = int(amp * math.sin(2 * math.pi * freq * i / SR))
        samples.append(v)
    return struct.pack(f"<{n}h", *samples)


def test_continue_when_only_silence_no_voice_yet():
    vad = UtteranceVAD(samplerate=SR, silence_threshold_ms=500, max_duration_s=10.0)
    # Pure silence — we have not yet heard any voice; must not commit on silence.
    for _ in range(20):
        assert vad.process(silence_chunk(50)) == "continue"


def test_commit_silence_after_voice_then_silence():
    vad = UtteranceVAD(samplerate=SR, silence_threshold_ms=500, max_duration_s=10.0)
    # 200 ms of voice, then 600 ms of silence — should commit_silence.
    for _ in range(4):
        vad.process(tone_chunk(50))
    statuses = [vad.process(silence_chunk(50)) for _ in range(15)]
    assert "commit_silence" in statuses


def test_commit_max_after_long_voice():
    vad = UtteranceVAD(samplerate=SR, silence_threshold_ms=10000, max_duration_s=0.5)
    statuses = [vad.process(tone_chunk(50)) for _ in range(20)]
    assert "commit_max" in statuses


def test_had_any_voice_starts_false_then_true():
    vad = UtteranceVAD(samplerate=SR, silence_threshold_ms=500, max_duration_s=10.0)
    assert not vad.had_any_voice()
    vad.process(tone_chunk(100))
    assert vad.had_any_voice()


def test_reset_clears_counters():
    vad = UtteranceVAD(samplerate=SR, silence_threshold_ms=500, max_duration_s=10.0)
    vad.process(tone_chunk(200))
    for _ in range(15):
        vad.process(silence_chunk(50))
    vad.reset()
    assert not vad.had_any_voice()
    # After reset, pure silence again shouldn't commit.
    for _ in range(15):
        assert vad.process(silence_chunk(50)) == "continue"
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
python -m pytest tests/test_utterance_vad.py -v
```

Expected: ImportError on `va_demo.utterance_vad`.

- [ ] **Step 3: Implement the VAD**

Create `va_demo/utterance_vad.py`:

```python
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
    ):
        import webrtcvad

        self._vad = webrtcvad.Vad(aggressiveness)
        self.samplerate = samplerate
        self.silence_threshold_ms = silence_threshold_ms
        self.max_duration_ms = int(max_duration_s * 1000)
        self._consecutive_silence_ms = 0
        self._total_ms = 0
        self._had_voice = False
        self._leftover = b""

    def reset(self) -> None:
        self._consecutive_silence_ms = 0
        self._total_ms = 0
        self._had_voice = False
        self._leftover = b""

    def had_any_voice(self) -> bool:
        return self._had_voice

    def process(self, pcm24k: bytes) -> Status:
        # Combine leftover + new audio, then resample 24k -> 16k.
        combined = self._leftover + pcm24k
        # Split into whole 24k samples (2 bytes each).
        n_bytes = (len(combined) // 2) * 2
        usable = combined[:n_bytes]
        self._leftover = combined[n_bytes:]
        if not usable:
            return "continue"

        arr = np.frombuffer(usable, dtype=np.int16)
        # Resample 24k -> 16k by stride: pick 2 of every 3 samples.
        # Length safety: only operate on a length that's a multiple of 3.
        cut = (len(arr) // 3) * 3
        if cut == 0:
            self._leftover = usable
            return "continue"
        a3 = arr[:cut].reshape(-1, 3).astype(np.int32)
        # Average pairs to avoid sharp aliasing — cheap.
        resampled = ((a3[:, 0] + a3[:, 1]) // 2).astype(np.int16)
        # Keep any remainder for next call.
        leftover_samples = arr[cut:]
        self._leftover = leftover_samples.tobytes() + self._leftover

        # Frame into 30 ms @ 16k = 480 samples.
        n_frames = len(resampled) // VAD_FRAME_SAMPLES
        for i in range(n_frames):
            frame = resampled[i * VAD_FRAME_SAMPLES : (i + 1) * VAD_FRAME_SAMPLES]
            is_speech = self._vad.is_speech(frame.tobytes(), VAD_SR)
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
```

- [ ] **Step 4: Run tests, verify they pass**

Run:
```bash
python -m pytest tests/test_utterance_vad.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add va_demo/utterance_vad.py tests/test_utterance_vad.py
git commit -m "feat(va-demo): add UtteranceVAD (webrtcvad end-of-utterance)"
```

---

## Task 4: WakeWordDetector with injected backend (TDD)

Background thread running `faster-whisper` on a rolling 1.5 s of mic audio. Emits `WakeEvent` callbacks. Backend is injected so tests use a fake one.

**Files:**
- Create: `va_demo/wake_word.py`
- Test: `tests/test_wake_word.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wake_word.py`:

```python
"""Unit tests for WakeWordDetector with a fake whisper backend."""
from __future__ import annotations

import math
import struct
import sys
import threading
import time
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.spoken_cache import SpokenTranscriptCache
from va_demo.wake_word import WakeEvent, WakeWordDetector

SR = 24000


def loud_audio_chunk(ms: int = 500) -> bytes:
    n = int(SR * ms / 1000)
    samples = [int(8000 * math.sin(2 * math.pi * 220 * i / SR)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


def quiet_audio_chunk(ms: int = 500) -> bytes:
    n = int(SR * ms / 1000)
    return b"\x00\x00" * n


class FakeBackend:
    """Returns scripted transcripts in order; one per transcribe() call."""

    def __init__(self, scripted: List[str]):
        self._scripted = list(scripted)
        self.calls = 0

    def transcribe(self, pcm: bytes, samplerate: int) -> str:
        self.calls += 1
        if self._scripted:
            return self._scripted.pop(0)
        return ""


def _make_detector(scripted, **overrides):
    cache = overrides.pop("cache", SpokenTranscriptCache())
    received: List[WakeEvent] = []
    backend = FakeBackend(scripted)
    detector = WakeWordDetector(
        backend=backend,
        spoken_cache=cache,
        on_wake=received.append,
        samplerate=SR,
        rolling_window_s=overrides.get("rolling_window_s", 1.0),
        inference_rate_hz=overrides.get("inference_rate_hz", 50.0),  # fast for tests
        rms_threshold=overrides.get("rms_threshold", 1000),
        cooldown_s=overrides.get("cooldown_s", 0.05),
        phrases=overrides.get("phrases", ["hi sparky", "hey sparky"]),
        selfecho_window_s=overrides.get("selfecho_window_s", 6.0),
    )
    return detector, backend, received, cache


def _drive(detector, n_chunks: int = 5, chunk: bytes | None = None):
    chunk = chunk if chunk is not None else loud_audio_chunk(500)
    detector.start()
    try:
        for _ in range(n_chunks):
            detector.feed(chunk)
            time.sleep(0.05)
        time.sleep(0.2)  # let worker drain
    finally:
        detector.stop()


def test_match_fires_on_phrase():
    d, _, received, _ = _make_detector(scripted=["hi sparky"])
    _drive(d)
    assert len(received) >= 1
    assert "hi sparky" in received[0].text.lower()


def test_no_match_does_not_fire():
    d, _, received, _ = _make_detector(scripted=["the weather is nice"])
    _drive(d)
    assert received == []


def test_rms_gate_blocks_quiet_audio():
    d, _, received, _ = _make_detector(scripted=["hi sparky"], rms_threshold=10000)
    _drive(d, chunk=quiet_audio_chunk(500))
    assert received == []


def test_cooldown_throttles_repeats():
    d, _, received, _ = _make_detector(
        scripted=["hi sparky", "hi sparky", "hi sparky"], cooldown_s=10.0
    )
    _drive(d, n_chunks=8)
    assert len(received) == 1


def test_selfecho_dedup_blocks_match():
    cache = SpokenTranscriptCache()
    cache.add("Hi Sparky here, how can I help?")
    d, _, received, _ = _make_detector(scripted=["hi sparky"], cache=cache)
    _drive(d)
    assert received == []


def test_pause_resume_skips_inference():
    d, backend, received, _ = _make_detector(scripted=["hi sparky", "hi sparky"])
    d.start()
    try:
        d.pause()
        for _ in range(5):
            d.feed(loud_audio_chunk(500))
            time.sleep(0.05)
        time.sleep(0.2)
        calls_paused = backend.calls
        d.resume()
        for _ in range(5):
            d.feed(loud_audio_chunk(500))
            time.sleep(0.05)
        time.sleep(0.2)
    finally:
        d.stop()
    assert calls_paused == 0
    assert backend.calls > 0


def test_phrase_match_normalizes_punctuation():
    d, _, received, _ = _make_detector(scripted=["Hi, Sparky!"])
    _drive(d)
    assert len(received) >= 1
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
python -m pytest tests/test_wake_word.py -v
```

Expected: ImportError on `va_demo.wake_word`.

- [ ] **Step 3: Implement the detector**

Create `va_demo/wake_word.py`:

```python
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
    """Real backend wrapping faster-whisper. Loads model lazily."""

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
        # faster-whisper accepts a numpy float32 array.
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if samplerate != 16000:
            # Stride-resample to 16 kHz; precision adequate for short rolling windows.
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
```

- [ ] **Step 4: Run tests, verify they pass**

Run:
```bash
python -m pytest tests/test_wake_word.py -v
```

Expected: all 7 tests PASS. (If a test is timing-flaky, increase the `time.sleep(0.2)` in `_drive` to 0.4 — the worker is real-thread so we depend on schedule.)

- [ ] **Step 5: Commit**

```bash
git add va_demo/wake_word.py tests/test_wake_word.py
git commit -m "feat(va-demo): add WakeWordDetector with pluggable backend"
```

---

## Task 5: MicStream fan-out

Add `subscribe()` / `unsubscribe()` so multiple consumers can share one mic capture (Realtime uplink + wake-word + utterance-vad). Keep the existing `mic.queue` working as a back-compat alias for the first subscriber.

**Files:**
- Modify: `va_demo/audio_io.py`
- Test: `tests/test_audio_io_fanout.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_audio_io_fanout.py`:

```python
"""Smoke test for MicStream subscribe() / unsubscribe() fan-out (no real device)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_subscribe_returns_independent_queues(monkeypatch):
    # Avoid importing sounddevice (it may not have a usable device in CI).
    import types
    fake_sd = types.SimpleNamespace(
        RawInputStream=lambda **kw: types.SimpleNamespace(start=lambda: None, stop=lambda: None, close=lambda: None),
        RawOutputStream=lambda **kw: types.SimpleNamespace(start=lambda: None, stop=lambda: None, close=lambda: None),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    from va_demo.audio_io import MicStream

    async def go():
        mic = MicStream(samplerate=24000, block_ms=50)
        mic.loop = asyncio.get_event_loop()
        q1 = mic.subscribe()
        q2 = mic.subscribe()
        # Simulate a callback chunk.
        mic._enqueue_nowait(b"\x00\x01" * 240)
        # Both subscribers should see it.
        c1 = await asyncio.wait_for(q1.get(), timeout=0.5)
        c2 = await asyncio.wait_for(q2.get(), timeout=0.5)
        assert c1 == c2 == b"\x00\x01" * 240
        # legacy .queue alias should also see it.
        # (The legacy alias points to the first subscribed queue.)
        assert mic.queue is q1
        mic.unsubscribe(q2)
        # Legacy alias still works.
        mic._enqueue_nowait(b"\x02\x02" * 240)
        c1 = await asyncio.wait_for(q1.get(), timeout=0.5)
        assert c1 == b"\x02\x02" * 240
        # q2 should not have received it.
        assert q2.qsize() == 0

    asyncio.run(go())
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
python -m pytest tests/test_audio_io_fanout.py -v
```

Expected: AttributeError on `MicStream.subscribe`.

- [ ] **Step 3: Modify MicStream**

Edit `va_demo/audio_io.py`. Replace the `MicStream` class (lines 18–92 currently — keep the `import sounddevice` pattern, the callback signature, and `start()` / `close()` shape) with this version:

```python
class MicStream:
    """Captures PCM16 mono frames; supports multiple async listeners (fan-out)."""

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
        self.loop = loop
        self._max_queue = max_queue
        self._listeners: list[asyncio.Queue[bytes]] = []
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
```

(SpeakerStream and the `rms()` helper are unchanged.)

- [ ] **Step 4: Run tests, verify they pass**

Run:
```bash
python -m pytest tests/test_audio_io_fanout.py -v
```

Expected: PASS.

Also re-run the rest:
```bash
python -m pytest tests/ -v
```
All 4 test files (safety, skills_mock, spoken_cache, utterance_vad, wake_word, audio_io_fanout) should pass.

- [ ] **Step 5: Commit**

```bash
git add va_demo/audio_io.py tests/test_audio_io_fanout.py
git commit -m "feat(va-demo): MicStream subscribe() fan-out for multi-listener audio"
```

---

## Task 6: Update prompts

Add the no-self-name rule so Sparky stops saying its own name (which would feedback into the wake-word detector).

**Files:**
- Modify: `va_demo/prompts.py`

- [ ] **Step 1: Edit prompts.py**

Replace `REALTIME_SYSTEM_PROMPT` (lines 1–17) with:

```python
REALTIME_SYSTEM_PROMPT = """\
You are the voice agent of a Unitree G1 humanoid robot running in a MuJoCo
simulator. The user calls you "Sparky". You can speak with the user, look at
the camera (via the describe_scene tool), and request small motion primitives
(walk, gesture, stop).

Rules:
- You DO NOT have direct motor control. You can only call the tools provided.
- Be conservative. Walk durations should be <= 1.0 s and speeds <= 0.2 m/s
  unless the user explicitly insists.
- When the user asks anything about what's around you, what's in front of you,
  what you see, who's there, or any visual question, ALWAYS call describe_scene
  first. Do not guess.
- If a tool returns ok=false, briefly explain the reason and propose a safer
  alternative. Do not retry the same call.
- Speak in the user's language (Chinese or English). Keep replies short and
  natural. Do not narrate every tool call.
- IMPORTANT: never refer to yourself as "Sparky" in your replies. Say "I" or
  "the robot" instead. The wake-word detector listens for "Sparky", and if
  you say it yourself you will accidentally interrupt your own answer.
"""
```

- [ ] **Step 2: Verify import still works**

Run:
```bash
python -c "from va_demo.prompts import REALTIME_SYSTEM_PROMPT; assert 'Sparky' in REALTIME_SYSTEM_PROMPT and 'never refer' in REALTIME_SYSTEM_PROMPT; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add va_demo/prompts.py
git commit -m "feat(va-demo): add no-self-name rule to system prompt"
```

---

## Task 7: TTSClient writes to spoken cache

When `tts.say` is invoked, push the text into the spoken cache so the wake-word detector can dedup.

**Files:**
- Modify: `va_demo/tts.py`

- [ ] **Step 1: Edit tts.py**

Change the constructor signature to accept an optional cache and write to it inside `speak()`. Replace the `TTSClient` class with:

```python
class TTSClient:
    def __init__(
        self,
        client,
        speaker: "SpeakerStream",
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        spoken_cache=None,
    ):
        self._client = client
        self._speaker = speaker
        self._model = model
        self._voice = voice
        self._cache = spoken_cache

    async def speak(self, text: str, voice: str | None = None):
        if not text:
            return
        if self._cache is not None:
            self._cache.add(text)
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
```

- [ ] **Step 2: Verify import**

Run:
```bash
python -c "from va_demo.tts import TTSClient; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add va_demo/tts.py
git commit -m "feat(va-demo): TTSClient writes spoken text into SpokenTranscriptCache"
```

---

## Task 8: RealtimeAgent — manual turn control + spoken-cache hookup

Take Realtime out of `server_vad`, expose hooks the state machine will call, drop the auto barge-in, and write transcript deltas into the spoken cache.

**Files:**
- Modify: `va_demo/realtime_agent.py`

- [ ] **Step 1: Add fields and constructor parameters**

Edit the `RealtimeAgent` dataclass (around line 129) to add `spoken_cache` and `on_response_audio_delta` / `on_response_done` callback fields, plus an internal `_uplink_enabled`. Replace the dataclass header with:

```python
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
        self._ws = None  # set in run()
```

Add `Any` to the existing `from typing import Any, Awaitable, Callable, Dict, List, Optional` import.

- [ ] **Step 2: Switch session to manual turn control**

Replace `_session_update`'s `turn_detection` block. The full method becomes:

```python
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
```

- [ ] **Step 3: Gate the uplink on _uplink_enabled**

Replace `_uplink`:

```python
    async def _uplink(self, ws):
        try:
            while True:
                chunk = await self.mic.queue.get()
                if not chunk:
                    continue
                if not self._uplink_enabled.is_set():
                    continue  # discard mic audio when state machine has us muted
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
```

- [ ] **Step 4: Drop auto barge-in; write transcripts into spoken cache; raise audio-delta callback**

In `_handle_event`, replace the relevant branches:

```python
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
            print()
            transcript = evt.get("transcript", "")
            if transcript and self.spoken_cache is not None:
                self.spoken_cache.add(transcript)
        elif t == "conversation.item.input_audio_transcription.completed":
            transcript = evt.get("transcript", "")
            if transcript:
                print(f"\n[user] {transcript}", flush=True)
        elif t == "input_audio_buffer.speech_started":
            log.debug("user speech started")
            # NOTE: do NOT clear the speaker here. The state machine controls
            # barge-in via the wake-word detector. server_vad is off anyway.
        elif t == "response.done":
            if self.on_response_done is not None:
                try:
                    self.on_response_done()
                except Exception:
                    log.exception("on_response_done raised")
        elif t == "response.function_call_arguments.done":
            await self._dispatch_tool(ws, evt)
```

(Keep the `error` branch and the catch-all `log.debug` branch unchanged — but remove `response.done` from the "known but ignored" list since we now actually handle it.)

- [ ] **Step 5: Add public control methods**

Add these methods at the bottom of the `RealtimeAgent` class (after `_execute_tool`):

```python
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
```

- [ ] **Step 6: Stash ws on the agent so external callers can use it**

Inside `run()`, after `async with ws:` and before `await self._session_update(ws)`, add:

```python
            self._ws = ws
```

And in the `finally` block (before `uplink.cancel()`), add:

```python
                self._ws = None
```

- [ ] **Step 7: Don't auto-create a response after a tool result if the state machine asks not to**

Leave `_dispatch_tool` mostly intact; it currently sends `response.create` after a tool result. That's still correct — when the model decides to tool-call mid-turn, we want the model to continue and produce an audio reply. (No change needed.)

- [ ] **Step 8: Sanity import**

Run:
```bash
python -c "from va_demo.realtime_agent import RealtimeAgent; print('ok')"
```

Expected: `ok`

- [ ] **Step 9: Commit**

```bash
git add va_demo/realtime_agent.py
git commit -m "feat(va-demo): manual turn control in RealtimeAgent (commit/cancel/uplink toggle)"
```

---

## Task 9: ConversationStateMachine (TDD)

The orchestration layer. Subscribes to mic, drives the wake-word detector, the utterance VAD, and the Realtime agent. Five states, transitions per the spec.

**Files:**
- Create: `va_demo/conversation_state.py`
- Test: `tests/test_conversation_state.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_conversation_state.py`:

```python
"""State machine tests with mocked components."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from va_demo.conversation_state import (
    ConversationConfig,
    ConversationStateMachine,
    State,
)
from va_demo.utterance_vad import UtteranceVAD
from va_demo.wake_word import WakeEvent


class FakeWake:
    def __init__(self):
        self.paused = False
        self.fed = bytearray()
        self.on_wake = None

    def start(self): pass
    def stop(self): pass
    def pause(self): self.paused = True
    def resume(self): self.paused = False
    def feed(self, b): self.fed.extend(b)


class FakeVAD:
    def __init__(self, scripted_returns):
        self.scripted = list(scripted_returns)
        self.had_voice_value = True
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1

    def had_any_voice(self):
        return self.had_voice_value

    def process(self, chunk):
        if self.scripted:
            return self.scripted.pop(0)
        return "continue"


class FakeAgent:
    def __init__(self):
        self.commit_calls = 0
        self.cancel_calls = 0
        self.uplink_states: list[bool] = []

    async def commit_and_respond(self):
        self.commit_calls += 1

    async def cancel_response(self):
        self.cancel_calls += 1

    def set_uplink_enabled(self, b: bool):
        self.uplink_states.append(b)


def _make_sm(vad_returns=None):
    cfg = ConversationConfig(
        listening_window_s=0.2,
        no_speech_timeout_s=0.2,
    )
    wake = FakeWake()
    vad = FakeVAD(vad_returns or [])
    agent = FakeAgent()
    sm = ConversationStateMachine(
        cfg=cfg,
        wake_word=wake,
        utterance_vad=vad,
        realtime_agent=agent,
    )
    # Capture the wake callback that the SM hands to the wake_word component:
    wake.on_wake = sm.handle_wake
    return sm, wake, vad, agent


@pytest.mark.asyncio
async def test_starts_in_idle_with_uplink_off():
    sm, wake, vad, agent = _make_sm()
    await sm.start()
    try:
        assert sm.state == State.IDLE
        # Uplink must be disabled initially.
        assert agent.uplink_states[-1] is False
    finally:
        await sm.stop()


@pytest.mark.asyncio
async def test_wake_transitions_to_capturing():
    sm, wake, vad, agent = _make_sm(vad_returns=["continue"])
    await sm.start()
    try:
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.05)
        assert sm.state == State.CAPTURING
        # Uplink turned on.
        assert agent.uplink_states[-1] is True
        # Wake detector paused while capturing.
        assert wake.paused
        # VAD reset.
        assert vad.reset_calls >= 1
    finally:
        await sm.stop()


@pytest.mark.asyncio
async def test_silence_commits_and_goes_to_thinking():
    sm, wake, vad, agent = _make_sm(vad_returns=["continue", "commit_silence"])
    await sm.start()
    try:
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.02)
        # Feed two mic chunks to the SM (it normally subscribes to MicStream;
        # here we call its private feeder to keep the test deterministic).
        sm._on_audio_chunk(b"\x00\x01" * 240)
        sm._on_audio_chunk(b"\x00\x01" * 240)
        await asyncio.sleep(0.05)
        assert agent.commit_calls == 1
        assert sm.state == State.THINKING
        # Uplink off again.
        assert agent.uplink_states[-1] is False
    finally:
        await sm.stop()


@pytest.mark.asyncio
async def test_no_speech_after_wake_returns_to_idle():
    sm, wake, vad, agent = _make_sm(vad_returns=["continue"] * 50)
    vad.had_voice_value = False  # nothing detected
    await sm.start()
    try:
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.4)  # > no_speech_timeout_s (0.2 in this test)
        assert sm.state == State.IDLE
        assert agent.commit_calls == 0
        assert not wake.paused  # wake detector resumed
    finally:
        await sm.stop()


@pytest.mark.asyncio
async def test_response_done_enters_listening_window_then_idle():
    sm, wake, vad, agent = _make_sm()
    await sm.start()
    try:
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.02)
        # Pretend the SM was in THINKING then SPEAKING.
        sm._force_state(State.SPEAKING)
        sm.handle_response_done()
        await asyncio.sleep(0.02)
        assert sm.state == State.LISTENING_WINDOW
        # After listening_window_s (0.2 in this test) should drop back to IDLE.
        await asyncio.sleep(0.3)
        assert sm.state == State.IDLE
    finally:
        await sm.stop()


@pytest.mark.asyncio
async def test_wake_during_speaking_cancels_and_recaptures():
    sm, wake, vad, agent = _make_sm()
    await sm.start()
    try:
        sm._force_state(State.SPEAKING)
        sm.handle_wake(WakeEvent(text="hi sparky", t=time.monotonic()))
        await asyncio.sleep(0.05)
        assert agent.cancel_calls == 1
        assert sm.state == State.CAPTURING
    finally:
        await sm.stop()
```

Add `pytest-asyncio` to test deps if not already available:

```bash
pip install pytest-asyncio
```

And ensure `tests/__init__.py` (or a `conftest.py`) enables async mode. Create `tests/conftest.py`:

```python
import pytest

# Allow @pytest.mark.asyncio without per-test event-loop boilerplate.
pytest_plugins = ("pytest_asyncio",)
```

And add to `tests/conftest.py`:

```python
def pytest_collection_modifyitems(config, items):
    for item in items:
        if "asyncio" in item.keywords:
            item.add_marker(pytest.mark.asyncio)
```

(Or just configure `asyncio_mode = "auto"` in `pytest.ini`. Skip that — the explicit marker above is enough.)

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
python -m pytest tests/test_conversation_state.py -v
```

Expected: ImportError on `va_demo.conversation_state`.

- [ ] **Step 3: Implement the state machine**

Create `va_demo/conversation_state.py`:

```python
"""Conversation state machine: gates Realtime input by a wake-word.

States:
  IDLE              — wake-word detector active; uplink disabled.
  AWAKE             — transient (next async tick); we just heard the wake word
                      and are about to start capturing.
  CAPTURING         — uplink enabled; utterance VAD running on each chunk;
                      wake detector paused (we already know we're talking).
  THINKING          — utterance committed; waiting for first audio delta.
  SPEAKING          — model is talking back. Wake-word detector is the only
                      thing that can interrupt.
  LISTENING_WINDOW  — short post-reply window where speaking again does not
                      need a wake word.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "IDLE"
    AWAKE = "AWAKE"
    CAPTURING = "CAPTURING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    LISTENING_WINDOW = "LISTENING_WINDOW"


@dataclass
class ConversationConfig:
    listening_window_s: float = 8.0
    no_speech_timeout_s: float = 4.0


class ConversationStateMachine:
    def __init__(
        self,
        cfg: ConversationConfig,
        wake_word,
        utterance_vad,
        realtime_agent,
        mic=None,
    ):
        self.cfg = cfg
        self.wake_word = wake_word
        self.vad = utterance_vad
        self.agent = realtime_agent
        self.mic = mic
        self._state = State.IDLE
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._mic_queue: Optional[asyncio.Queue] = None
        self._mic_task: Optional[asyncio.Task] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._capture_started_at: float = 0.0
        self._stopped = False

    # ---- public lifecycle ---------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        # Initial state: IDLE — uplink off, wake detector running.
        self.agent.set_uplink_enabled(False)
        if self.mic is not None:
            self._mic_queue = self.mic.subscribe()
            self._mic_task = asyncio.create_task(self._consume_mic(), name="sm-mic")
        # Start the wake-word detector. It is unpaused (IDLE listens).
        self.wake_word.resume()
        self.wake_word.start()

    async def stop(self) -> None:
        self._stopped = True
        if self._timer_task is not None:
            self._timer_task.cancel()
        if self._mic_task is not None:
            self._mic_task.cancel()
            try:
                await self._mic_task
            except (asyncio.CancelledError, BaseException):
                pass
        try:
            self.wake_word.stop()
        except Exception:
            pass

    @property
    def state(self) -> State:
        return self._state

    # ---- callbacks the outer world calls into us ----------------------------

    def handle_wake(self, evt) -> None:
        """Called by WakeWordDetector from its worker thread."""
        if self._loop is None or self._stopped:
            return
        self._loop.call_soon_threadsafe(self._on_wake_in_loop, evt)

    def handle_response_done(self) -> None:
        if self._loop is None or self._stopped:
            return
        self._loop.call_soon_threadsafe(self._on_response_done_in_loop)

    def handle_response_audio_delta(self) -> None:
        if self._loop is None or self._stopped:
            return
        self._loop.call_soon_threadsafe(self._on_response_audio_delta_in_loop)

    # ---- internal: state-changing handlers (run on the loop) ----------------

    def _on_wake_in_loop(self, evt) -> None:
        log.info("[wake] %s (state=%s)", evt.text, self._state.value)
        if self._state in (State.SPEAKING, State.THINKING):
            asyncio.create_task(self._cancel_then_capture())
            return
        if self._state in (State.IDLE, State.LISTENING_WINDOW):
            self._enter_capturing()
            return
        # CAPTURING / AWAKE: ignore (already / about to be capturing).

    async def _cancel_then_capture(self) -> None:
        try:
            await self.agent.cancel_response()
        finally:
            self._enter_capturing()

    def _on_response_audio_delta_in_loop(self) -> None:
        if self._state == State.THINKING:
            self._set_state(State.SPEAKING)

    def _on_response_done_in_loop(self) -> None:
        if self._state in (State.SPEAKING, State.THINKING):
            self._enter_listening_window()

    # ---- audio path ---------------------------------------------------------

    async def _consume_mic(self) -> None:
        while not self._stopped:
            try:
                chunk = await self._mic_queue.get()
            except asyncio.CancelledError:
                return
            self._on_audio_chunk(chunk)

    def _on_audio_chunk(self, chunk: bytes) -> None:
        # Always feed the wake-word detector — it manages its own pause flag.
        try:
            self.wake_word.feed(chunk)
        except Exception:
            log.exception("wake_word.feed raised")
        if self._state == State.CAPTURING:
            status = self.vad.process(chunk)
            if status == "commit_silence" or status == "commit_max":
                log.info("[utterance] %s after %.2fs",
                         status, time.monotonic() - self._capture_started_at)
                self._enter_thinking()

    # ---- transitions --------------------------------------------------------

    def _set_state(self, new: State) -> None:
        if self._state == new:
            return
        log.info("[state] %s -> %s", self._state.value, new.value)
        self._state = new

    def _force_state(self, new: State) -> None:
        """Test-only hook to drop into a state without going through the graph."""
        self._set_state(new)

    def _enter_capturing(self) -> None:
        self._set_state(State.CAPTURING)
        self.wake_word.pause()
        self.vad.reset()
        self.agent.set_uplink_enabled(True)
        self._capture_started_at = time.monotonic()
        # Schedule the no-speech watchdog.
        self._reset_timer(self.cfg.no_speech_timeout_s, self._no_speech_timeout_cb)

    def _no_speech_timeout_cb(self) -> None:
        if self._state != State.CAPTURING:
            return
        if self.vad.had_any_voice():
            return  # voice was heard; the silence-commit path will handle it
        log.info("[capture] no speech for %.1fs after wake; aborting",
                 self.cfg.no_speech_timeout_s)
        self.agent.set_uplink_enabled(False)
        self.wake_word.resume()
        self._set_state(State.IDLE)

    def _enter_thinking(self) -> None:
        self._cancel_timer()
        self.agent.set_uplink_enabled(False)
        self.wake_word.resume()
        self._set_state(State.THINKING)
        asyncio.create_task(self.agent.commit_and_respond())

    def _enter_listening_window(self) -> None:
        self._set_state(State.LISTENING_WINDOW)
        self._reset_timer(self.cfg.listening_window_s, self._listening_window_cb)

    def _listening_window_cb(self) -> None:
        if self._state == State.LISTENING_WINDOW:
            self._set_state(State.IDLE)

    def _reset_timer(self, delay_s: float, cb) -> None:
        self._cancel_timer()

        async def _runner():
            try:
                await asyncio.sleep(delay_s)
                cb()
            except asyncio.CancelledError:
                pass

        self._timer_task = asyncio.create_task(_runner(), name="sm-timer")

    def _cancel_timer(self) -> None:
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None
```

- [ ] **Step 4: Run tests, verify they pass**

Run:
```bash
pip install pytest-asyncio  # one-time
python -m pytest tests/test_conversation_state.py -v
```

Expected: 6 tests PASS. (If pytest-asyncio complains about mode, add `asyncio_mode = auto` to a `pytest.ini` at the repo root: create `pytest.ini` with `[pytest]\nasyncio_mode = auto\n`.)

- [ ] **Step 5: Commit**

```bash
git add va_demo/conversation_state.py tests/test_conversation_state.py tests/conftest.py
git commit -m "feat(va-demo): add ConversationStateMachine (5-state wake/capture/respond)"
```

---

## Task 10: Wire it all up in `main.py`

Build the cache, vad, wake-word backend (real or fake-with-warning), state machine, and pass them to the agent.

**Files:**
- Modify: `va_demo/main.py`

- [ ] **Step 1: Add the new imports + CLI flag**

Edit `main.py`. Replace the imports block (lines 1–17) with:

```python
"""va-demo entrypoint: wire up audio, camera, skills, vision, tts, Realtime."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import yaml

from . import audio_io, camera, safety, skills, tts, vision
from .conversation_state import ConversationConfig, ConversationStateMachine
from .realtime_agent import RealtimeAgent
from .spoken_cache import SpokenTranscriptCache
from .utterance_vad import UtteranceVAD
from .wake_word import FasterWhisperBackend, WakeWordDetector
```

In `parse_args()` add the flag (after `--no-skills`):

```python
    p.add_argument("--no-wakeword", action="store_true",
                   help="disable wake-word gating; mic always streams to Realtime "
                        "(use to A/B against the original behavior)")
```

- [ ] **Step 2: Build the cache + agent with new fields**

Find the `# ---- openai clients ----` section in `_run`. After `tts_client = tts.TTSClient(...)`, replace the rest of `_run` (from there through the agent construction) with:

```python
    spoken_cache = SpokenTranscriptCache()
    tts_client = tts.TTSClient(
        openai_client,
        speaker,
        model=os.environ.get("OPENAI_TTS_MODEL", cfg["openai"]["tts_model"]),
        voice=cfg["openai"]["tts_voice"],
        spoken_cache=spoken_cache,
    )

    # ---- realtime ----
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and not args.no_realtime:
        log.error("OPENAI_API_KEY is not set; either export it or pass --no-realtime")
        sys.exit(2)

    if args.no_realtime:
        log.info("realtime disabled; idling — useful with debug scripts. Press Ctrl-C to exit.")
        try:
            while True:
                await asyncio.sleep(1.0)
        finally:
            pass
        # ---- shutdown ----
        if skill_backend is not None:
            skill_backend.shutdown()
        cam.close()
        mic.close()
        speaker.close()
        return

    agent = RealtimeAgent(
        api_key=api_key,
        model=os.environ.get("OPENAI_REALTIME_MODEL", cfg["openai"]["realtime_model"]),
        voice=cfg["openai"]["realtime_voice"],
        mic=mic,
        speaker=speaker,
        camera=cam,
        vision=vision_client,
        tts=tts_client,
        skills=skill_backend,
        safety=sup,
        vision_resize_width=cfg["camera"]["vision_resize_width"],
        vision_jpeg_quality=cfg["camera"]["vision_jpeg_quality"],
        spoken_cache=spoken_cache,
    )

    sm: Optional[ConversationStateMachine] = None
    if not args.no_wakeword and cfg.get("wakeword", {}).get("enabled", True):
        wake_cfg = cfg.get("wakeword", {})
        utt_cfg = cfg.get("utterance", {})
        conv_cfg = cfg.get("conversation", {})
        try:
            backend = FasterWhisperBackend(
                model_size=wake_cfg.get("model_size", "tiny"),
                compute_type=wake_cfg.get("compute_type", "int8"),
                device=wake_cfg.get("device", "cpu"),
                language=wake_cfg.get("language") or None,
            )
        except Exception as e:
            log.error(
                "wake-word backend failed to load (%s). "
                "Re-run with --no-wakeword to fall back to always-on Realtime.",
                e,
            )
            sys.exit(3)
        utt_vad = UtteranceVAD(
            samplerate=cfg["audio"]["samplerate"],
            silence_threshold_ms=utt_cfg.get("silence_threshold_ms", 1500),
            max_duration_s=utt_cfg.get("max_duration_s", 30.0),
            aggressiveness=utt_cfg.get("vad_aggressiveness", 2),
        )
        wake = WakeWordDetector(
            backend=backend,
            spoken_cache=spoken_cache,
            on_wake=lambda evt: sm.handle_wake(evt) if sm else None,
            samplerate=cfg["audio"]["samplerate"],
            rolling_window_s=wake_cfg.get("rolling_window_s", 1.5),
            inference_rate_hz=wake_cfg.get("inference_rate_hz", 2.0),
            rms_threshold=wake_cfg.get("rms_threshold", 1500),
            cooldown_s=wake_cfg.get("cooldown_s", 2.0),
            phrases=wake_cfg.get("phrases") or ["hi sparky"],
            selfecho_window_s=conv_cfg.get("selfecho_dedup_window_s", 6.0),
        )
        sm = ConversationStateMachine(
            cfg=ConversationConfig(
                listening_window_s=conv_cfg.get("listening_window_s", 8.0),
                no_speech_timeout_s=utt_cfg.get("no_speech_timeout_s", 4.0),
            ),
            wake_word=wake,
            utterance_vad=utt_vad,
            realtime_agent=agent,
            mic=mic,
        )
        agent.on_response_audio_delta = sm.handle_response_audio_delta
        agent.on_response_done = sm.handle_response_done
        log.info("wake-word enabled: phrases=%s", wake_cfg.get("phrases"))
    else:
        # No wake-word gating: always allow uplink (legacy behavior).
        agent.on_response_audio_delta = None
        agent.on_response_done = None

    try:
        if sm is not None:
            await sm.start()
        if sm is None:
            # Legacy mode: open the uplink immediately.
            agent.set_uplink_enabled(True)
        await agent.run()
    finally:
        log.info("shutting down ...")
        if sm is not None:
            await sm.stop()

    # ---- shutdown ----
    if skill_backend is not None:
        skill_backend.shutdown()
    cam.close()
    mic.close()
    speaker.close()
```

(You may need to delete the previous block from `# ---- realtime ----` through the end of `_run` first; this replaces all of it.)

- [ ] **Step 3: Sanity import + help**

Run:
```bash
python -c "import va_demo.main; print('ok')"
python -m va_demo.main --help
```

Expected: `ok`, then a `--no-wakeword` line in the help output.

- [ ] **Step 4: Commit**

```bash
git add va_demo/main.py
git commit -m "feat(va-demo): wire wake-word + state machine into main entrypoint"
```

---

## Task 11: Configuration

Add the three new YAML sections.

**Files:**
- Modify: `configs/va_demo.yaml`

- [ ] **Step 1: Append the new sections**

After the existing `safety:` block in `configs/va_demo.yaml`, before `run_mode: "confirm"`, insert:

```yaml
wakeword:
  enabled: true
  model_size: tiny
  compute_type: int8
  device: cpu
  rolling_window_s: 1.5
  inference_rate_hz: 2.0
  rms_threshold: 1500
  cooldown_s: 2.0
  language: null
  phrases:
    - "hi sparky"
    - "hey sparky"
    - "hi sparkie"
    - "嗨 sparky"
    - "你好 sparky"

utterance:
  silence_threshold_ms: 1500
  max_duration_s: 30.0
  vad_aggressiveness: 2
  no_speech_timeout_s: 4.0

conversation:
  listening_window_s: 8.0
  selfecho_dedup_window_s: 6.0
```

- [ ] **Step 2: Verify yaml parses**

Run:
```bash
python -c "import yaml; cfg=yaml.safe_load(open('configs/va_demo.yaml')); print(list(cfg))"
```

Expected output includes `wakeword`, `utterance`, `conversation`.

- [ ] **Step 3: Commit**

```bash
git add configs/va_demo.yaml
git commit -m "feat(va-demo): config sections for wakeword/utterance/conversation"
```

---

## Task 12: wake_word_debug.py (live mic check, no Realtime)

A small script for the operator to verify the model loaded, the mic levels are right, and the wake phrase actually fires before plumbing it through Realtime.

**Files:**
- Create: `scripts/wake_word_debug.py`

- [ ] **Step 1: Write the script**

Create `scripts/wake_word_debug.py`:

```python
#!/usr/bin/env python3
"""Listen on the mic and print 'WAKE' every time the wake word fires.

Use to tune rms_threshold and confirm the faster-whisper model loaded.

Usage:
    conda activate agi
    cd ~/unitree/unitree-notes/va-demo
    python scripts/wake_word_debug.py [--rms 1500] [--phrase "hi sparky"]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.audio_io import MicStream
from va_demo.spoken_cache import SpokenTranscriptCache
from va_demo.wake_word import FasterWhisperBackend, WakeWordDetector


async def amain(args):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mic = MicStream(samplerate=24000, block_ms=50)
    mic.loop = asyncio.get_event_loop()
    mic.start()
    cache = SpokenTranscriptCache()
    backend = FasterWhisperBackend(
        model_size=args.model_size, compute_type=args.compute_type, device=args.device,
    )

    def _on_wake(evt):
        print(f"WAKE @ {evt.t:.2f}: {evt.text!r}", flush=True)

    detector = WakeWordDetector(
        backend=backend,
        spoken_cache=cache,
        on_wake=_on_wake,
        samplerate=24000,
        rolling_window_s=1.5,
        inference_rate_hz=2.0,
        rms_threshold=args.rms,
        cooldown_s=1.0,
        phrases=[args.phrase] if args.phrase else None,
    )
    detector.start()
    q = mic.queue
    print("listening; press Ctrl-C to stop")
    try:
        while True:
            chunk = await q.get()
            detector.feed(chunk)
    except KeyboardInterrupt:
        pass
    finally:
        detector.stop()
        mic.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rms", type=int, default=1500)
    p.add_argument("--phrase", type=str, default=None)
    p.add_argument("--model-size", default="tiny")
    p.add_argument("--compute-type", default="int8")
    p.add_argument("--device", default="cpu")
    args = p.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make it executable**

Run:
```bash
chmod +x scripts/wake_word_debug.py
```

- [ ] **Step 3: Smoke-test (no audio device required for help)**

Run:
```bash
python scripts/wake_word_debug.py --help
```

Expected: usage text, no errors.

- [ ] **Step 4: Commit**

```bash
git add scripts/wake_word_debug.py
git commit -m "feat(va-demo): add wake_word_debug.py live-mic verification script"
```

---

## Task 13: README — wake-word usage

Document model download, the new CLI flag, and the live debug script.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Insert a new section**

Insert this section in `README.md` immediately after the `## What it does` section and before `## Run order`:

```markdown
## Wake word

The agent does **not** stream mic audio to OpenAI Realtime until you say
"**Hi, Sparky**". This solves two problems:

1. The Realtime API was so eager that any cough committed a turn.
2. Sparky's own TTS playback bled into the mic and Sparky kept cutting
   itself off mid-reply.

After the wake word fires, you speak your request normally. When you stop
talking for ~1.5 s the whole utterance is committed in one shot. After
Sparky replies, you have an 8 s "listening window" where you can speak
again **without** re-saying the wake word — useful for follow-ups like
"那再向前走两步".

The wake-word detector is `faster-whisper` `tiny` running locally on CPU.
First launch downloads the model (~75 MB) into `~/.cache/huggingface`.

Tuning lives in `configs/va_demo.yaml::wakeword`. The two values you most
often want to touch:

- `wakeword.rms_threshold` — minimum mic loudness for the matcher to even
  consider firing. Raise if the detector triggers on background sound;
  lower if it doesn't fire when you talk normally.
- `wakeword.phrases` — substring list. Add variants ("hi sparkie",
  "嗨 spark") if your accent doesn't match the defaults.

To verify the model and mic before plumbing through Realtime:

```bash
python scripts/wake_word_debug.py
# say "Hi Sparky" — you should see a WAKE line print.
```

To bypass the wake word entirely (legacy, hair-trigger Realtime
behavior — only useful for A/B debugging):

```bash
python -m va_demo.main --no-wakeword
```
```

Also add a row to the CLI flags table:

| Flag | Default | Effect |
|---|---|---|
| `--no-wakeword` | off | bypass wake-word gate; mic streams continuously to Realtime |

(Insert this row in the existing CLI flags table between `--no-skills` and `-v / --verbose`.)

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(va-demo): document wake-word usage and tuning"
```

---

## Task 14: Full test sweep

- [ ] **Step 1: Run the entire test suite**

Run:
```bash
cd ~/unitree/unitree-notes/va-demo
python -m pytest tests/ -v
```

Expected: every test in `test_safety.py`, `test_skills_mock.py`, `test_spoken_cache.py`, `test_utterance_vad.py`, `test_wake_word.py`, `test_audio_io_fanout.py`, `test_conversation_state.py` passes.

- [ ] **Step 2: Static import check**

Run:
```bash
python -c "import va_demo.audio_io, va_demo.camera, va_demo.vision, va_demo.tts, va_demo.skills, va_demo.safety, va_demo.realtime_agent, va_demo.spoken_cache, va_demo.utterance_vad, va_demo.wake_word, va_demo.conversation_state, va_demo.main"
```

Expected: no errors.

- [ ] **Step 3: Help output**

Run:
```bash
python -m va_demo.main --help
```

Expected: includes `--no-wakeword`.

- [ ] **Step 4: If any test failed, fix it before continuing**

Re-read the failing test, the implementation, and the spec. The most likely categories:

* Async timing flakes (`test_conversation_state.py`): bump the `asyncio.sleep` numbers up by 2× and re-run.
* faster-whisper download failure: confirm internet access; rerun once. If model download is impossible, mark `wakeword.enabled: false` in config and continue plan; fix later.

---

## Task 15: Live MuJoCo smoke test (operator-driven)

This is a manual test, not automated. Run it to confirm the demo actually works on the robot sim before declaring done.

**Three terminals; each first runs `conda activate agi`.**

- [ ] **Step 1: T1 — MuJoCo simulator**

```bash
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

In the viewer, press `8` a few times to lower the elastic band; `9` to disable.

- [ ] **Step 2: T2 — TeleImager image server**

```bash
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

- [ ] **Step 3: T3a — verify wake-word in isolation first**

```bash
cd ~/unitree/unitree-notes/va-demo
python scripts/wake_word_debug.py
```

Say "Hi Sparky" several times in your normal speaking tone.

Expected: at least one `WAKE @ ...: 'hi sparky'` line per utterance. If nothing fires, lower `--rms` (try 800, then 500). If it fires constantly on silence, raise it (try 2500).

Note the working `--rms` value; update `configs/va_demo.yaml::wakeword.rms_threshold` to match.

- [ ] **Step 4: T3b — full demo, observe mode (no motion)**

```bash
python -m va_demo.main --mode observe -v
```

Expected logs in order:
```
mic started: ...
loading faster-whisper model_size=tiny ...
wake-word enabled: phrases=['hi sparky', ...]
connecting Realtime: wss://...
[state] IDLE -> IDLE  (or no state log at boot)
```

- [ ] **Step 5: T3b — wake + ask a vision question**

Speak: "Hi Sparky." (pause for state log), then: "你看到什么？"

Expected:
```
[wake] hi sparky (state=IDLE)
[state] IDLE -> CAPTURING
[user] 你看到什么？
[utterance] commit_silence after ~2.5s
[state] CAPTURING -> THINKING
[state] THINKING -> SPEAKING
... Sparky speaks the vision answer ...
[state] SPEAKING -> LISTENING_WINDOW
[state] LISTENING_WINDOW -> IDLE   (after 8s)
```

If `describe_scene` was tool-called, you'll also see a tool-call log.

- [ ] **Step 6: T3b — self-interrupt regression check**

Ask Sparky a question with a long answer ("讲个长一点的笑话"). While it is speaking, **stay silent** (don't say anything, don't type, don't move closer to the mic).

Expected: Sparky finishes its reply without cutting itself off. This is the original bug.

- [ ] **Step 7: T3b — wake-while-speaking interrupt**

Ask another long-answer question. While Sparky is mid-reply, say "Hi Sparky stop."

Expected:
```
[wake] hi sparky stop (state=SPEAKING)
[state] SPEAKING -> CAPTURING   (after cancel_response)
... your follow-up gets captured ...
```

The speaker cuts off immediately on `cancel_response`. (Slight buffered audio may play out — the speaker buffer is ~200 ms.)

- [ ] **Step 8: T3b — confirm-mode motion in MuJoCo**

Restart with `--mode confirm`. Say "Hi Sparky, 走两步".

Expected: a `walk` tool call printed with a `[y/N]` prompt. Press `y`. Watch the MuJoCo viewer — the robot takes a small step.

- [ ] **Step 9: Stop, summarize, push branch**

If all six manual checks pass:

```bash
git push -u origin feature/audio-fix
```

If anything failed, revert/fix and re-run the failing step before pushing.

---

## Self-Review Notes (already applied while writing this plan)

1. **Spec coverage:** every section of the spec maps to one or more tasks (Task 2 = §8, Task 3 = §7, Task 4 = §6, Task 5 = §9, Task 6 = §12, Task 7 = §8, Task 8 = §10, Task 9 = §5, Task 10 = §15 wiring, Task 11 = §11, Task 13 = README, Task 15 = §14 manual). §13 error handling is covered piecemeal across Task 4 (wake fail) and Task 10 (load fail with sys.exit).
2. **Placeholder scan:** no TBD / TODO / "implement later" / "add validation"; every code step shows the actual code; every command shows actual expected output.
3. **Type consistency:** `WakeEvent.text/t`, `UtteranceVAD.process` returning `Status` literal, `SpokenTranscriptCache.add(text, t)` and `recent_text(window_s)`, `RealtimeAgent.commit_and_respond/cancel_response/set_uplink_enabled`, `ConversationStateMachine.handle_wake/handle_response_done/handle_response_audio_delta` all match across tasks.
