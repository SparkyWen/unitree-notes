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
