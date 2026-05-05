"""MediaPipe BlazePose 后台线程：USB 相机 → HumanPose + 手势标签。"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Deque, Optional, Tuple

import numpy as np

from ..scene_state.fusion import SceneStateBus
from ..scene_state.types import HumanPose
from .cameras import CameraHub
from .derivations import classify_gesture

log = logging.getLogger(__name__)


class PoseDetector:
    """MediaPipe Pose worker; consumes USB camera only."""

    def __init__(
        self,
        cameras: CameraHub,
        scene_bus: SceneStateBus,
        inference_hz: float = 15.0,
        min_visibility: float = 0.5,
        gesture_persist_frames: int = 3,
        gesture_min_confidence: float = 0.7,
        model_complexity: int = 1,
    ):
        self._cams = cameras
        self._bus = scene_bus
        self._interval = 1.0 / inference_hz if inference_hz > 0 else 0.066
        self._min_vis = float(min_visibility)
        self._persist = max(1, int(gesture_persist_frames))
        self._gate_conf = float(gesture_min_confidence)
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._history: Deque[Tuple[Optional[str], float]] = deque(maxlen=self._persist)

        try:
            import mediapipe as mp
        except Exception as e:
            log.error("mediapipe not available: %s", e)
            raise
        self._mp = mp
        # Build Pose lazily once; the model is process-internal so we keep it
        # alive for the lifetime of the detector.
        self._pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=model_complexity,
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def start(self) -> None:
        self._worker = threading.Thread(target=self._loop, name="mediapipe-pose", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            try:
                self._worker.join(timeout=1.0)
            except Exception:
                pass
        try:
            self._pose.close()
        except Exception:
            pass

    # ---------------- gesture persistence ----------------

    def _persistent_gesture(self, label: Optional[str], conf: float) -> Tuple[Optional[str], float]:
        """Return (gesture, confidence) only when the last `persist` frames
        all agree on the same label with conf >= gating threshold."""
        self._history.append((label, conf))
        if len(self._history) < self._persist:
            return None, conf
        labels = [l for l, _ in self._history]
        if labels[0] is None:
            return None, conf
        if any(l != labels[0] for l in labels):
            return None, conf
        confs = [c for _, c in self._history]
        if min(confs) < self._gate_conf:
            return None, conf
        return labels[0], float(np.mean(confs))

    # ---------------- inference loop ----------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            bgr = self._cams.latest_usb_bgr()
            if bgr is not None:
                try:
                    self._infer_one(bgr)
                except Exception as e:
                    log.debug("pose infer error: %s", e)
            elapsed = time.monotonic() - t0
            self._stop.wait(max(0.0, self._interval - elapsed))

    def _infer_one(self, bgr: np.ndarray) -> None:
        # MediaPipe wants RGB.
        rgb = bgr[..., ::-1]
        result = self._pose.process(rgb)
        if not result.pose_landmarks:
            self._history.clear()
            self._bus.update_user_pose(None, ts=time.monotonic())
            return
        lm = result.pose_landmarks.landmark
        xy = np.array([[p.x, p.y] for p in lm], dtype=np.float32)
        z = np.array([p.z for p in lm], dtype=np.float32)
        vis = np.array([p.visibility for p in lm], dtype=np.float32)
        raw_label, raw_conf = classify_gesture(xy, vis, min_confidence=0.0)
        label, conf = self._persistent_gesture(raw_label, raw_conf)
        pose = HumanPose(
            landmarks_xy=xy,
            landmarks_z=z,
            visibility=vis,
            gesture=label,
            gesture_confidence=conf,
            source="usb",
        )
        self._bus.update_user_pose(pose, ts=time.monotonic())
