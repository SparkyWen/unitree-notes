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


# ---------- vision_llm path ----------------------------------------------

@pytest.mark.asyncio
async def test_llm_safe_verdict():
    vision = AsyncMock()
    vision.describe = AsyncMock(return_value="SAFE: clear empty floor for 3 m")
    gate = VisionRiskGate(vision_client=vision, camera_hub=_StubCam(), cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": 0.2, "duration_s": 5.0})
    assert v.safe is True
    assert v.source == "vision_llm"
    assert "clear empty floor" in v.reason
    vision.describe.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_risk_verdict():
    vision = AsyncMock()
    vision.describe = AsyncMock(return_value="RISK: person sitting 0.7 m ahead")
    gate = VisionRiskGate(vision_client=vision, camera_hub=_StubCam(), cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": 0.2, "duration_s": 5.0})
    assert v.safe is False
    assert v.source == "vision_llm"
    assert "person" in v.reason


@pytest.mark.asyncio
async def test_llm_takes_only_first_line():
    vision = AsyncMock()
    vision.describe = AsyncMock(return_value="SAFE: ok\nRISK: also there is a thing")
    gate = VisionRiskGate(vision_client=vision, camera_hub=_StubCam(), cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": 0.2, "duration_s": 5.0})
    assert v.safe is True
    assert v.source == "vision_llm"


@pytest.mark.asyncio
async def test_llm_garbage_is_parse_fail_and_risk():
    vision = AsyncMock()
    vision.describe = AsyncMock(return_value="I think it might be fine actually")
    gate = VisionRiskGate(vision_client=vision, camera_hub=_StubCam(), cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": 0.2, "duration_s": 5.0})
    assert v.safe is False
    assert v.source == "parse_fail"


@pytest.mark.asyncio
async def test_llm_timeout_is_risk():
    async def _slow(*_a, **_k):
        await asyncio.sleep(10.0)
        return "SAFE: never returned"

    vision = MagicMock()
    vision.describe = _slow
    gate = VisionRiskGate(
        vision_client=vision, camera_hub=_StubCam(),
        cfg=_cfg(timeout_s=0.05),
    )
    v = await gate.evaluate("walk", {"vx": 0.2, "duration_s": 5.0})
    assert v.safe is False
    assert v.source == "timeout"


@pytest.mark.asyncio
async def test_llm_exception_is_api_error():
    async def _boom(*_a, **_k):
        raise RuntimeError("rate limit")

    vision = MagicMock()
    vision.describe = _boom
    gate = VisionRiskGate(vision_client=vision, camera_hub=_StubCam(), cfg=_cfg())
    v = await gate.evaluate("walk", {"vx": 0.2, "duration_s": 5.0})
    assert v.safe is False
    assert v.source == "api_error"
    assert "rate limit" in v.reason


# ---------- request_timeout_s plumbing -----------------------------------


@pytest.mark.asyncio
async def test_request_timeout_s_forwarded_when_supported():
    """When describe() advertises ``request_timeout_s``, the gate passes
    (timeout_s + 1.0) so the OpenAI SDK's HTTP-level timeout fires a
    fraction after our outer wait_for, freeing the executor thread.
    """
    captured: Dict[str, Any] = {}

    async def _describe(*, image_jpeg_b64, prompt, detail, request_timeout_s):
        captured["request_timeout_s"] = request_timeout_s
        return "SAFE: clear"

    vision = MagicMock()
    vision.describe = _describe
    gate = VisionRiskGate(
        vision_client=vision, camera_hub=_StubCam(),
        cfg=_cfg(timeout_s=12.0),
    )
    v = await gate.evaluate("walk", {"vx": 0.2, "duration_s": 5.0})
    assert v.safe is True
    assert captured["request_timeout_s"] == pytest.approx(13.0)


@pytest.mark.asyncio
async def test_request_timeout_s_omitted_for_legacy_describe_signature():
    """An older VisionClient (or a test stub) whose describe() does NOT
    accept ``request_timeout_s`` must not get the kwarg — otherwise the
    gate would raise TypeError on every motion call.
    """
    captured: Dict[str, Any] = {}

    async def _legacy_describe(*, image_jpeg_b64, prompt, detail):
        captured["called"] = True
        return "SAFE: clear"

    vision = MagicMock()
    vision.describe = _legacy_describe
    gate = VisionRiskGate(
        vision_client=vision, camera_hub=_StubCam(),
        cfg=_cfg(timeout_s=12.0),
    )
    v = await gate.evaluate("walk", {"vx": 0.2, "duration_s": 5.0})
    assert v.safe is True
    assert captured.get("called") is True


@pytest.mark.asyncio
async def test_low_detail_is_passed_to_describe():
    """detail config flows through to the vision client unchanged."""
    captured: Dict[str, Any] = {}

    async def _describe(*, image_jpeg_b64, prompt, detail, request_timeout_s=None):
        captured["detail"] = detail
        return "SAFE: clear"

    vision = MagicMock()
    vision.describe = _describe
    gate = VisionRiskGate(
        vision_client=vision, camera_hub=_StubCam(),
        cfg=_cfg(detail="low"),
    )
    await gate.evaluate("walk", {"vx": 0.2, "duration_s": 5.0})
    assert captured["detail"] == "low"
