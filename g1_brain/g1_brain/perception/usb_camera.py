"""USB 摄像头薄包装：默认走 va-demo 的 teleimager 客户端，可选 cv2 后端。

Public surface mirrors `va_demo.camera.Camera` so the rest of g1_brain can
treat both backends identically.
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class UsbCamera:
    """Background-polled USB camera with two interchangeable backends."""

    def __init__(
        self,
        source: str = "teleimager",
        teleimager_host: str = "127.0.0.1",
        teleimager_request_port: int = 60000,
        cv2_index: int = 0,
        poll_hz: float = 20.0,
        request_bgr: bool = True,
    ):
        self._source = source
        self._poll_interval_s = 1.0 / poll_hz if poll_hz > 0 else 0.05
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_bgr: Optional[np.ndarray] = None
        self._last_bgr_t: float = 0.0

        if source == "teleimager":
            from va_demo.camera import Camera as _VaCam

            self._impl = _VaCam(
                host=teleimager_host,
                request_port=teleimager_request_port,
                request_bgr=request_bgr,
                poll_hz=poll_hz,
            )
            self._poller = None
        elif source == "cv2":
            import cv2  # noqa: F401  (loaded lazily so derivation tests stay slim)

            self._cv2_index = cv2_index
            self._cap = None
            self._impl = None
            self._poller = threading.Thread(
                target=self._cv2_poll_loop, name="g1-brain-usb-poll", daemon=True
            )
            self._poller.start()
        else:
            raise ValueError(f"unknown usb camera source: {source!r}")

    # -------- cv2 backend --------

    def _cv2_poll_loop(self) -> None:
        import cv2

        try:
            self._cap = cv2.VideoCapture(self._cv2_index)
        except Exception as e:
            log.error("cv2.VideoCapture(%s) failed: %s", self._cv2_index, e)
            self._cap = None
        while not self._stop.is_set():
            if self._cap is not None:
                try:
                    ok, frame = self._cap.read()
                    if ok and frame is not None:
                        with self._lock:
                            self._last_bgr = frame
                            self._last_bgr_t = time.monotonic()
                except Exception as e:
                    log.debug("cv2 read error: %s", e)
            self._stop.wait(self._poll_interval_s)
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass

    # -------- public API (mirrors va_demo.camera.Camera) --------

    def latest_bgr(self) -> Optional[np.ndarray]:
        if self._impl is not None:
            return self._impl.latest_bgr()
        with self._lock:
            return self._last_bgr

    def latest_jpeg_b64(self, width: int = 1024, jpeg_quality: int = 85) -> Optional[str]:
        if self._impl is not None:
            return self._impl.latest_jpeg_b64(width=width, jpeg_quality=jpeg_quality)
        import cv2

        bgr = self.latest_bgr()
        if bgr is None:
            return None
        h, w = bgr.shape[:2]
        if w > width:
            new_h = int(h * width / w)
            bgr = cv2.resize(bgr, (width, new_h), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")

    def frame_age_seconds(self) -> float:
        if self._impl is not None:
            return self._impl.frame_age_seconds()
        with self._lock:
            if self._last_bgr_t <= 0:
                return float("inf")
            return time.monotonic() - self._last_bgr_t

    def close(self) -> None:
        self._stop.set()
        if self._impl is not None:
            try:
                self._impl.close()
            except Exception as e:
                log.debug("usb close error: %s", e)
        if self._poller is not None:
            try:
                self._poller.join(timeout=1.0)
            except Exception:
                pass
