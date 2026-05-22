"""YOLO11 物体检测：每路相机独立后台线程，结果写入 SceneStateBus。"""
from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional

import numpy as np

from ..scene_state.fusion import SceneStateBus
from ..scene_state.types import Detection
from .cameras import CameraHub
from .derivations import bbox_to_bearing_pitch

log = logging.getLogger(__name__)


# Default horizontal FoV for an unknown USB camera. Most consumer webcams
# sit between 60° and 78°; we pick the conservative 60° so bearings tend to
# be slight underestimates rather than overshoots into reject territory.
DEFAULT_USB_HFOV_DEG = 60.0
DEFAULT_USB_VFOV_DEG = 45.0


class ObjectDetector:
    """One YOLO model shared across both source threads."""

    def __init__(
        self,
        cameras: CameraHub,
        scene_bus: SceneStateBus,
        weights: str = "yolo11s.pt",
        conf: float = 0.4,
        inference_hz: float = 15.0,
        sources: Optional[List[str]] = None,
        device: str = "auto",
        usb_hfov_deg: float = DEFAULT_USB_HFOV_DEG,
        usb_vfov_deg: float = DEFAULT_USB_VFOV_DEG,
    ):
        self._cams = cameras
        self._bus = scene_bus
        self._conf = float(conf)
        self._interval = 1.0 / inference_hz if inference_hz > 0 else 0.066
        self._sources = list(sources or ["head", "usb"])
        self._stop = threading.Event()
        self._workers: List[threading.Thread] = []
        self._usb_hfov_deg = usb_hfov_deg
        self._usb_vfov_deg = usb_vfov_deg

        # Heavy import isolated to construction.
        try:
            from ultralytics import YOLO
        except Exception as e:
            log.error("ultralytics not available: %s", e)
            raise

        self._model = YOLO(weights)
        # Resolve "auto" -> actual device. The previous code only called
        # .to(device) for non-"auto" values, which left YOLO sitting on CPU
        # forever — ~8x slower than CUDA on this box (99 ms vs 13 ms per
        # inference at 640x480), saturating one core per source thread.
        resolved = device
        if not device or device == "auto":
            try:
                import torch
                resolved = "cuda:0" if torch.cuda.is_available() else "cpu"
            except Exception:  # noqa: BLE001
                resolved = "cpu"
        try:
            self._model.to(resolved)
        except Exception as e:  # noqa: BLE001
            log.warning("YOLO.to(%s) failed: %s; staying on default device", resolved, e)
            resolved = "cpu"
        self._device = resolved
        log.info("yolo device: %s", resolved)

    def start(self) -> None:
        for src in self._sources:
            t = threading.Thread(
                target=self._loop, args=(src,), name=f"yolo-{src}", daemon=True
            )
            t.start()
            self._workers.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._workers:
            try:
                t.join(timeout=1.0)
            except Exception:
                pass

    # ---------------- inference loop ----------------

    def _grab(self, src: str):
        if src == "usb":
            return self._cams.latest_usb_bgr()
        if src == "head":
            return self._cams.latest_head_bgr()
        return None

    def _depth(self, src: str) -> Optional[np.ndarray]:
        if src == "head":
            return self._cams.latest_head_depth_meters()
        return None

    def _fov(self, src: str):
        if src == "head":
            return self._cams.head_hfov_deg(), self._cams.head_vfov_deg()
        return self._usb_hfov_deg, self._usb_vfov_deg

    def _loop(self, src: str) -> None:
        log.info("yolo worker started: source=%s", src)
        while not self._stop.is_set():
            t0 = time.monotonic()
            bgr = self._grab(src)
            if bgr is not None:
                try:
                    dets = self._infer(bgr, src)
                    if src == "usb":
                        self._bus.update_user_detections(dets, ts=time.monotonic())
                    else:
                        self._bus.update_head_detections(dets, ts=time.monotonic())
                except Exception as e:
                    log.debug("yolo infer error (%s): %s", src, e)
            elapsed = time.monotonic() - t0
            self._stop.wait(max(0.0, self._interval - elapsed))

    def _infer(self, bgr: np.ndarray, src: str) -> List[Detection]:
        # YOLO accepts BGR np arrays directly; verbose=False keeps logs clean.
        # Pass device explicitly: ultralytics' predict() otherwise re-runs its
        # own auto-detect each call and can drift back to CPU.
        results = self._model(bgr, conf=self._conf, verbose=False, device=self._device)
        if not results:
            return []
        r0 = results[0]
        names = r0.names if hasattr(r0, "names") else self._model.names
        if r0.boxes is None or len(r0.boxes) == 0:
            return []
        xyxy = r0.boxes.xyxy.cpu().numpy() if hasattr(r0.boxes.xyxy, "cpu") else np.asarray(r0.boxes.xyxy)
        confs = r0.boxes.conf.cpu().numpy() if hasattr(r0.boxes.conf, "cpu") else np.asarray(r0.boxes.conf)
        classes = r0.boxes.cls.cpu().numpy() if hasattr(r0.boxes.cls, "cpu") else np.asarray(r0.boxes.cls)

        depth = self._depth(src)
        hfov, vfov = self._fov(src)
        h, w = bgr.shape[:2]
        out: List[Detection] = []
        for box, score, cls in zip(xyxy, confs, classes):
            x1, y1, x2, y2 = (float(v) for v in box)
            class_name = str(names.get(int(cls), str(int(cls)))) if isinstance(names, dict) else str(names[int(cls)])
            distance = None
            if depth is not None and depth.shape[:2] == (h, w):
                cx = int(np.clip(0.5 * (x1 + x2), 0, w - 1))
                cy = int(np.clip(0.5 * (y1 + y2), 0, h - 1))
                d = float(depth[cy, cx])
                if np.isfinite(d) and d > 0:
                    distance = d
            bearing, pitch = bbox_to_bearing_pitch((x1, y1, x2, y2), (h, w), hfov, vfov)
            out.append(
                Detection(
                    class_name=class_name,
                    bbox_xyxy=(x1, y1, x2, y2),
                    score=float(score),
                    distance_m=distance,
                    bearing_deg=bearing,
                    pitch_deg=pitch,
                    source=src,
                )
            )
        return out
