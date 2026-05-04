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
    text = c.recent_text(window_s=10.0)
    assert "old" not in text
    assert "new" in text
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
