"""CameraHub: 单一对象统一管理 USB 相机和 MuJoCo 头摄。

Composes `UsbCamera` and `MuJoCoHeadCamera`. The rest of perception
(YOLO, MediaPipe, depth) only ever talks to this hub.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class CameraHub:
    """Owns both the USB and MuJoCo head camera; either may be disabled."""

    def __init__(self, cameras_cfg: dict):
        self._cfg = cameras_cfg or {}
        usb_cfg = self._cfg.get("usb", {}) or {}
        head_cfg = self._cfg.get("head", {}) or {}

        self._usb = None
        self._head = None
        self._usb_resolution = (0, 0)
        self._head_resolution = (0, 0)

        if usb_cfg.get("enabled", True):
            self._usb = self._build_usb(usb_cfg)
        if head_cfg.get("enabled", True):
            self._head = self._build_head(head_cfg)
            if self._head is not None:
                self._head_resolution = (
                    int(head_cfg.get("height", 480)),
                    int(head_cfg.get("width", 640)),
                )

    # ---------------- builders ----------------

    def _build_usb(self, cfg: dict):
        from .usb_camera import UsbCamera

        try:
            return UsbCamera(
                source=cfg.get("source", "teleimager"),
                teleimager_host=cfg.get("teleimager_host", "127.0.0.1"),
                teleimager_request_port=int(cfg.get("teleimager_request_port", 60000)),
                cv2_index=int(cfg.get("cv2_index", 0)),
                poll_hz=float(cfg.get("poll_hz", 20.0)),
            )
        except Exception as e:
            log.warning("USB camera init failed: %s", e)
            return None

    def _build_head(self, cfg: dict):
        from .mujoco_head_cam import MuJoCoHeadCamera

        mjcf = cfg.get("mjcf_path") or os.path.expanduser(
            os.environ.get(
                "G1_MJCF_PATH",
                "~/unitree/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_29dof.xml",
            )
        )
        try:
            return MuJoCoHeadCamera(
                mjcf_path=os.path.expanduser(os.path.expandvars(mjcf)),
                camera_name=cfg.get("camera_name", "head_camera"),
                width=int(cfg.get("width", 640)),
                height=int(cfg.get("height", 480)),
                poll_hz=float(cfg.get("poll_hz", 20.0)),
                subscribe_dds=bool(cfg.get("subscribe_dds", True)),
            )
        except Exception as e:
            log.warning("MuJoCo head camera init failed: %s", e)
            return None

    # ---------------- public accessors ----------------

    def latest_usb_bgr(self) -> Optional[np.ndarray]:
        if self._usb is None:
            return None
        bgr = self._usb.latest_bgr()
        if bgr is not None:
            self._usb_resolution = (int(bgr.shape[0]), int(bgr.shape[1]))
        return bgr

    def latest_usb_jpeg_b64(self, width: int = 1024, jpeg_quality: int = 85) -> Optional[str]:
        if self._usb is None:
            return None
        return self._usb.latest_jpeg_b64(width=width, jpeg_quality=jpeg_quality)

    def latest_head_bgr(self) -> Optional[np.ndarray]:
        if self._head is None:
            return None
        bgr = self._head.latest_bgr()
        if bgr is not None:
            self._head_resolution = (int(bgr.shape[0]), int(bgr.shape[1]))
        return bgr

    def latest_head_depth_meters(self) -> Optional[np.ndarray]:
        if self._head is None:
            return None
        return self._head.latest_depth_meters()

    def latest_head_jpeg_b64(self, width: int = 1024, jpeg_quality: int = 85) -> Optional[str]:
        if self._head is None:
            return None
        return self._head.latest_jpeg_b64(width=width, jpeg_quality=jpeg_quality)

    def usb_frame_age_seconds(self) -> float:
        if self._usb is None:
            return float("inf")
        return self._usb.frame_age_seconds()

    def head_frame_age_seconds(self) -> float:
        if self._head is None:
            return float("inf")
        return self._head.frame_age_seconds()

    def usb_resolution(self) -> tuple:
        return self._usb_resolution

    def head_resolution(self) -> tuple:
        return self._head_resolution

    def head_hfov_deg(self) -> float:
        if self._head is None:
            return 60.0
        return float(getattr(self._head, "hfov_deg", 60.0))

    def head_vfov_deg(self) -> float:
        if self._head is None:
            return 45.0
        return float(getattr(self._head, "vfov_deg", 45.0))

    @property
    def has_usb(self) -> bool:
        return self._usb is not None

    @property
    def has_head(self) -> bool:
        return self._head is not None

    def close(self) -> None:
        if self._usb is not None:
            try:
                self._usb.close()
            except Exception as e:
                log.debug("usb close: %s", e)
        if self._head is not None:
            try:
                self._head.close()
            except Exception as e:
                log.debug("head close: %s", e)
