"""Camera background-poll regression tests.

These tests pin the contract that `Camera.frame_age_seconds()` must reflect
the time of the latest received frame from teleimager, even when no consumer
has called `latest_bgr()` / `latest_jpeg_b64()` yet.

Before the fix in this commit, the wrapper only refreshed `_last_bgr_t`
inside `latest_bgr()`, so the very first `describe_scene` tool call (which is
gated by `safety.SafetySupervisor.validate` -> `cam.frame_age_seconds() >
max_frame_age_s`) always saw `frame_age = inf` and was rejected with
"no recent frame (age=inf)" before ever touching the camera. The Realtime
model then verbalised that reason as "I cannot access the camera stream",
which was the user-visible bug.
"""
from __future__ import annotations

import sys
import time
import types

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Stub `teleimager.image_client.ImageClient` so we don't need a real teleimager
# server running on 127.0.0.1:60000. The va_demo.camera module imports it
# lazily inside __init__, so we install the stub before constructing Camera.
# ---------------------------------------------------------------------------

class _FakeTeleImage:
    def __init__(self, bgr):
        self.bgr = bgr
        self.jpg = b""
        self.fps = 30.0


class _FakeImageClient:
    """Mimics teleimager.ImageClient.get_head_frame(): always returns a fresh
    1x1 BGR frame, like a teleimager server that's pushing frames steadily.
    """

    def __init__(self, host="127.0.0.1", request_port=60000, request_bgr=True):
        self.host = host
        self.request_port = request_port
        self._request_bgr = request_bgr
        self._frame = np.zeros((1, 1, 3), dtype=np.uint8)
        self.calls = 0

    def get_head_frame(self):
        self.calls += 1
        return _FakeTeleImage(self._frame.copy())

    def close(self):
        pass


@pytest.fixture
def stubbed_teleimager(monkeypatch):
    """Inject a fake teleimager.image_client module into sys.modules."""
    fake_pkg = types.ModuleType("teleimager")
    fake_mod = types.ModuleType("teleimager.image_client")
    fake_mod.ImageClient = _FakeImageClient
    fake_pkg.image_client = fake_mod
    monkeypatch.setitem(sys.modules, "teleimager", fake_pkg)
    monkeypatch.setitem(sys.modules, "teleimager.image_client", fake_mod)
    yield fake_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_frame_age_is_finite_shortly_after_construction(stubbed_teleimager):
    """REGRESSION: with the bug, frame_age_seconds() == inf until someone
    actively calls latest_bgr(). The watchdog therefore always rejected the
    first describe_scene call. After the fix, the background poller refreshes
    the timestamp on its own, so a brief sleep is enough.
    """
    from va_demo.camera import Camera

    cam = Camera(host="127.0.0.1", request_port=60000, request_bgr=True)
    try:
        # Give the background poller a few cycles. With a 20 Hz poll this is
        # plenty; with the bug, frame_age() would still be inf no matter how
        # long we wait.
        deadline = time.monotonic() + 1.0
        age = float("inf")
        while time.monotonic() < deadline:
            age = cam.frame_age_seconds()
            if age < float("inf"):
                break
            time.sleep(0.02)
        assert age < float("inf"), (
            "frame_age_seconds() never went below inf — the background "
            "camera poller is not running, so the safety watchdog will "
            "always reject describe_scene with 'no recent frame'."
        )
        # And it should be very fresh (< 1 s in any case).
        assert age < 1.0, f"frame_age={age:.2f}s is suspiciously stale"
    finally:
        cam.close()


def test_frame_age_passes_default_watchdog_threshold(stubbed_teleimager):
    """End-to-end: the value `cam.frame_age_seconds()` returns must be below
    the default safety.watchdog.max_frame_age_s = 2.0 within a reasonable
    startup window, otherwise SafetySupervisor will reject describe_scene.
    """
    from va_demo.camera import Camera

    cam = Camera(host="127.0.0.1", request_port=60000, request_bgr=True)
    try:
        # Allow up to 0.5 s for the first poll to land. In practice it should
        # be < 100 ms.
        time.sleep(0.5)
        age = cam.frame_age_seconds()
        assert age < 2.0, (
            f"frame_age={age:.2f}s exceeds the 2.0 s watchdog threshold; "
            "the watchdog would reject describe_scene."
        )
    finally:
        cam.close()


def test_close_stops_background_poller(stubbed_teleimager):
    """`Camera.close()` must terminate the polling thread so the process can
    exit cleanly.
    """
    from va_demo.camera import Camera

    cam = Camera(host="127.0.0.1", request_port=60000, request_bgr=True)
    time.sleep(0.1)
    cam.close()
    # After close, the poller thread should be done.
    poller = getattr(cam, "_poller", None)
    if poller is not None:
        poller.join(timeout=1.0)
        assert not poller.is_alive(), "background poller did not stop on close()"
