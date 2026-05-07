"""Coverage of g1_brain.safety.vision_risk_gate.VisionRiskGate."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from g1_brain.safety.vision_risk_gate import RiskVerdict, VisionRiskGate


def _cfg(**overrides: Any) -> Dict[str, Any]:
    base = {
        "enabled": True,
        "timeout_s": 5.0,
        "max_frame_age_s": 2.0,
        "min_brightness": 30,
        "max_brightness": 235,
        "detail": "auto",
    }
    base.update(overrides)
    return {"safety": {"vision_gate": base}}


class _StubCam:
    """Just enough of CameraHub for the gate."""

    def __init__(
        self,
        *,
        jpeg_b64: Optional[str] = "ZmFrZQ==",
        bgr_mean: Optional[float] = 128.0,
        head_age_s: float = 0.1,
    ) -> None:
        self._jpeg = jpeg_b64
        self._mean = bgr_mean
        self._age = head_age_s

    def latest_head_jpeg_b64(self, *_a, **_k) -> Optional[str]:
        return self._jpeg

    def latest_head_bgr(self):
        if self._mean is None:
            return None
        import numpy as np
        # uniform luminance ~ self._mean
        return np.full((4, 4, 3), int(self._mean), dtype=np.uint8)

    def head_frame_age_seconds(self) -> float:
        return self._age


# ---------- bypass paths --------------------------------------------------

@pytest.mark.asyncio
async def test_say_bypassed_safe():
    vision = AsyncMock()
    cam = _StubCam()
    gate = VisionRiskGate(vision_client=vision, camera_hub=cam, cfg=_cfg())
    v = await gate.evaluate("say", {"text": "hi"})
    assert v.safe is True
    assert v.source == "bypass"
    vision.describe.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["stop", "release_arms", "describe_scene",
                                   "query_scene_state", "recall_history"])
async def test_other_non_motion_bypassed_safe(tool):
    vision = AsyncMock()
    gate = VisionRiskGate(vision_client=vision, camera_hub=_StubCam(), cfg=_cfg())
    v = await gate.evaluate(tool, {})
    assert v.safe is True
    assert v.source == "bypass"
    vision.describe.assert_not_called()


@pytest.mark.asyncio
async def test_backward_walk_bypassed_risk():
    vision = AsyncMock()
    gate = VisionRiskGate(vision_client=vision, camera_hub=_StubCam(), cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": -0.1, "vy": 0.0, "wz": 0.0, "duration_s": 1.0})
    assert v.safe is False
    assert v.source == "bypass"
    assert "backward" in v.reason.lower()
    vision.describe.assert_not_called()


# ---------- frame health -------------------------------------------------

@pytest.mark.asyncio
async def test_no_jpeg_is_risk():
    vision = AsyncMock()
    cam = _StubCam(jpeg_b64=None)
    gate = VisionRiskGate(vision_client=vision, camera_hub=cam, cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert v.safe is False
    assert v.source == "frame_fail"
    assert "no head-cam jpeg" in v.reason.lower()
    vision.describe.assert_not_called()


@pytest.mark.asyncio
async def test_stale_frame_is_risk():
    vision = AsyncMock()
    cam = _StubCam(head_age_s=5.0)
    gate = VisionRiskGate(vision_client=vision, camera_hub=cam, cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert v.safe is False
    assert v.source == "frame_fail"
    assert "stale" in v.reason.lower() or "age" in v.reason.lower()
    vision.describe.assert_not_called()


@pytest.mark.asyncio
async def test_too_dark_frame_is_risk():
    vision = AsyncMock()
    cam = _StubCam(bgr_mean=10.0)
    gate = VisionRiskGate(vision_client=vision, camera_hub=cam, cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert v.safe is False
    assert v.source == "frame_fail"
    assert "dark" in v.reason.lower()
    vision.describe.assert_not_called()


@pytest.mark.asyncio
async def test_too_bright_frame_is_risk():
    vision = AsyncMock()
    cam = _StubCam(bgr_mean=250.0)
    gate = VisionRiskGate(vision_client=vision, camera_hub=cam, cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": 0.1, "duration_s": 0.5})
    assert v.safe is False
    assert v.source == "frame_fail"
    assert "bright" in v.reason.lower() or "white" in v.reason.lower()
    vision.describe.assert_not_called()
