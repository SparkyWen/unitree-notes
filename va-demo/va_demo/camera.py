"""TeleImager image-server client wrapper.

Pulls the head-camera latest frame from the existing
`teleimager.image_server` running on 127.0.0.1:55555 (config request on 60000).

A background daemon thread polls teleimager at `poll_hz` and refreshes
`_last_bgr` / `_last_bgr_t`. This keeps `frame_age_seconds()` honest even
when no consumer has pulled a frame recently — without it, the safety
watchdog would always see `frame_age == inf` on the first describe_scene
call (chicken-and-egg: the watchdog runs before the dispatcher would have
called latest_jpeg_b64()).
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


class Camera:
    def __init__(
        self,
        host: str = "127.0.0.1",
        request_port: int = 60000,
        request_bgr: bool = True,
        poll_hz: float = 20.0,
    ):
        from teleimager.image_client import ImageClient

        self._client = ImageClient(host=host, request_port=request_port, request_bgr=request_bgr)
        self._last_bgr: Optional[np.ndarray] = None
        self._last_bgr_t: float = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._poll_interval_s = 1.0 / poll_hz if poll_hz > 0 else 0.05
        self._poller = threading.Thread(
            target=self._poll_loop, name="va-demo-camera-poll", daemon=True
        )
        self._poller.start()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                img = self._client.get_head_frame()
                if img is not None:
                    bgr = img.bgr
                    if bgr is not None:
                        with self._lock:
                            self._last_bgr = bgr
                            self._last_bgr_t = time.monotonic()
            except Exception as e:
                log.debug("camera poll error: %s", e)
            self._stop.wait(self._poll_interval_s)

    def latest_bgr(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._last_bgr

    def latest_jpeg_b64(self, width: int = 1024, jpeg_quality: int = 85) -> Optional[str]:
        bgr = self.latest_bgr()
        if bgr is None:
            return None
        h, w = bgr.shape[:2]
        if w > width:
            new_h = int(h * width / w)
            bgr = cv2.resize(bgr, (width, new_h), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
        if not ok:
            log.warning("jpeg encode failed")
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")

    def frame_age_seconds(self) -> float:
        with self._lock:
            if self._last_bgr_t <= 0:
                return float("inf")
            return time.monotonic() - self._last_bgr_t

    def close(self):
        self._stop.set()
        try:
            self._poller.join(timeout=1.0)
        except Exception:
            pass
        try:
            self._client.close()
        except Exception as e:
            log.warning("error closing image client: %s", e)
