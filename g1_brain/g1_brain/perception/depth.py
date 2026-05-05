"""深度后端：MuJoCo native depth（仿真默认）+ DepthAnythingV2（可选）。"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class MuJoCoNativeDepth:
    """Pass-through to MuJoCoHeadCamera's depth buffer.

    The MJCF renderer already returns depth in meters when configured with
    `enable_depth_rendering()`, so we don't rescale.
    """

    def __init__(self, head_cam):
        self._head_cam = head_cam

    def latest_depth_meters(self, _bgr: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        if self._head_cam is None:
            return None
        return self._head_cam.latest_depth_meters()


class MonoDepthAnythingV2:
    """Lazy wrapper around HuggingFace DepthAnythingV2 pipeline.

    Only imports `transformers` on first use; perception works fine without
    it as long as `enabled=False`. Used as a sim2real fallback when no native
    or RealSense depth is available.
    """

    def __init__(
        self,
        model: str = "depth-anything/Depth-Anything-V2-Small-hf",
        device: str = "cuda:0",
    ):
        self._model_name = model
        self._device = device
        self._pipe = None
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        if self._pipe is not None:
            return
        with self._lock:
            if self._pipe is not None:
                return
            try:
                from transformers import pipeline
            except Exception as e:
                log.error("transformers not installed; cannot use mono depth: %s", e)
                raise
            try:
                self._pipe = pipeline(
                    "depth-estimation", model=self._model_name, device=self._device
                )
            except Exception as e:
                log.error("DepthAnythingV2 init failed: %s", e)
                raise

    def latest_depth_meters(self, bgr: Optional[np.ndarray]) -> Optional[np.ndarray]:
        if bgr is None:
            return None
        self._ensure()
        # Convert BGR -> RGB PIL-like array; the HF pipeline accepts numpy.
        try:
            from PIL import Image

            rgb = bgr[..., ::-1]
            img = Image.fromarray(rgb)
            out = self._pipe(img)
            depth = out.get("predicted_depth")
            if depth is None:
                return None
            depth_np = depth.detach().cpu().numpy().astype(np.float32)
            if depth_np.ndim == 3:
                depth_np = depth_np[0]
            return depth_np
        except Exception as e:
            log.debug("mono depth infer error: %s", e)
            return None
