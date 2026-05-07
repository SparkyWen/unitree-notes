# Vision Risk Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a vision-based risk gate (Rule 12) inside `SafetySupervisor` so that motion calls auto-execute when GPT-5.5 declares the head-cam scene SAFE, and fall through to the existing terminal y/N when GPT-5.5 declares RISK or any check fails.

**Architecture:** New `g1_brain/safety/vision_risk_gate.py` exposes `VisionRiskGate.evaluate(tool, sanitized) -> RiskVerdict`. `SafetySupervisor.validate()` accepts an optional `vision_gate` and inserts the gate after Rule 10 (scene checks) but before the legacy confirm prompt. `_confirm_in_terminal` learns to print a `[RISK] {reason}` hint. `agent_main` builds the gate after `vision_client` and passes it to the supervisor. Spec: `docs/g1_v1.md`.

**Tech Stack:** Python 3.11, `asyncio`, `pytest` (unit + async), existing `va_demo.VisionClient` (OpenAI Responses API, model `gpt-5.5`), existing `g1_brain.perception.cameras.CameraHub`.

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `g1_brain/safety/vision_risk_gate.py` | `RiskVerdict` dataclass, `VisionRiskGate` class, prompt template, action-sentence rendering, output parsing. |
| Modify | `g1_brain/safety/supervisor.py` | Inject `vision_gate`, insert Rule 12, thread `risk_reason` into the existing confirm-prompt step. |
| Modify | `g1_brain/apps/agent_main.py` | Build `VisionRiskGate` between `vision_client` and `SafetySupervisor`; emit a startup line. |
| Modify | `configs/g1_brain.yaml` | Add `safety.vision_gate.*` block with documented defaults. |
| Modify | `g1_brain/brain/prompts.py` | Note that motion calls are vetted by a vision gate so `describe_scene` is no longer mandatory before every `walk` (downgrade to a soft preference). |
| Create | `tests/test_vision_risk_gate.py` | Unit tests for `VisionRiskGate` against a stub `vision_client` and stub `camera_hub`. |
| Modify | `tests/test_safety_supervisor.py` | Add three integration tests for the supervisor + gate interaction; existing tests already pass `vision_gate=None` implicitly. |

---

## Task 1: `RiskVerdict` dataclass + `VisionRiskGate` skeleton (bypass paths, no LLM call yet)

**Files:**
- Create: `g1_brain/safety/vision_risk_gate.py`
- Test: `tests/test_vision_risk_gate.py`

- [ ] **Step 1.1: Write the failing test for `RiskVerdict` shape and bypass paths**

Create `tests/test_vision_risk_gate.py`:

```python
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
```

- [ ] **Step 1.2: Run the failing test**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_vision_risk_gate.py -x -q`

Expected: `ImportError: cannot import name 'VisionRiskGate' from 'g1_brain.safety.vision_risk_gate'` (module does not exist).

- [ ] **Step 1.3: Create the module with bypass logic only**

Create `g1_brain/safety/vision_risk_gate.py`:

```python
"""Vision-based risk gate (spec: docs/g1_v1.md).

Sits inside SafetySupervisor as Rule 12: take the latest head-cam JPEG,
ask GPT-5.5 whether the upcoming action is safe, and either short-circuit
to "auto-execute" or fall through to the existing terminal y/N confirm.

This module is independent of run_mode and the 11 existing rules — it is
a horizontal capability the operator turns on via
`safety.vision_gate.enabled` in the YAML config.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Set

log = logging.getLogger(__name__)


# Tools that do not consume the gate (they auto-pass without a GPT call).
# describe_scene / query_scene_state / recall_history never reach the gate
# in supervisor.validate (they take the non-motion early-return), but we
# include them here defensively so the gate is correct in isolation.
_BYPASS_SAFE: Set[str] = {
    "say",
    "stop",
    "release_arms",
    "describe_scene",
    "query_scene_state",
    "recall_history",
}


VerdictSource = Literal[
    "bypass",
    "vision_llm",
    "frame_fail",
    "parse_fail",
    "timeout",
    "api_error",
]


@dataclass(frozen=True)
class RiskVerdict:
    """Outcome of a single VisionRiskGate.evaluate() call.

    `reason` is capped at 120 chars so the terminal y/N prompt fits on one
    line. `source` lets logs / tests distinguish the path that produced
    the verdict.
    """
    safe: bool
    reason: str
    source: VerdictSource


class VisionRiskGate:
    def __init__(self, *, vision_client, camera_hub, cfg: Dict[str, Any]) -> None:
        self._vision = vision_client
        self._cam = camera_hub
        gate_cfg = (cfg.get("safety", {}) or {}).get("vision_gate", {}) or {}
        self._timeout_s = float(gate_cfg.get("timeout_s", 5.0))
        self._max_age_s = float(gate_cfg.get("max_frame_age_s", 2.0))
        self._min_b = int(gate_cfg.get("min_brightness", 30))
        self._max_b = int(gate_cfg.get("max_brightness", 235))
        self._detail = str(gate_cfg.get("detail", "auto"))

    async def evaluate(self, tool: str, sanitized: Dict[str, Any]) -> RiskVerdict:
        # 1. bypass short-circuit (no LLM call).
        if tool in _BYPASS_SAFE:
            return RiskVerdict(True, f"bypass: {tool} never gated", "bypass")
        if tool == "walk":
            try:
                vx = float(sanitized.get("vx", 0.0))
            except (TypeError, ValueError):
                vx = 0.0
            if vx < 0.0:
                return RiskVerdict(
                    False,
                    "backward walk — head cam blind to behind",
                    "bypass",
                )
        # Frame health + GPT call land in subsequent tasks.
        return RiskVerdict(False, "not implemented yet", "frame_fail")
```

- [ ] **Step 1.4: Re-run tests, verify the three bypass tests pass**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_vision_risk_gate.py -x -q`

Expected: 7 tests pass (1 + 5 parametrized + 1).

- [ ] **Step 1.5: Commit**

```bash
cd /home/helios/unitree/unitree-notes/g1_brain
git add g1_brain/safety/vision_risk_gate.py tests/test_vision_risk_gate.py
git commit -m "feat(safety): VisionRiskGate skeleton + bypass paths"
```

---

## Task 2: Frame health checks (no GPT call yet)

**Files:**
- Modify: `g1_brain/safety/vision_risk_gate.py`
- Modify: `tests/test_vision_risk_gate.py`

- [ ] **Step 2.1: Add failing tests for frame health**

Append to `tests/test_vision_risk_gate.py`:

```python
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
```

- [ ] **Step 2.2: Run, see 4 new failures**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_vision_risk_gate.py -x -q`

Expected: each frame-health test fails because the stub returns `RiskVerdict("not implemented yet", "frame_fail")` — the `reason` does not match the assertions.

- [ ] **Step 2.3: Implement frame health in `evaluate()`**

In `g1_brain/safety/vision_risk_gate.py`, replace the placeholder return at the bottom of `evaluate()` with:

```python
        # 2. Frame fetch + health check (no LLM call).
        jpeg_b64 = self._cam.latest_head_jpeg_b64()
        if jpeg_b64 is None:
            return RiskVerdict(False, "no head-cam jpeg available", "frame_fail")

        age_s = self._cam.head_frame_age_seconds()
        if age_s > self._max_age_s:
            return RiskVerdict(
                False,
                f"head-cam frame stale: age {age_s:.2f}s > {self._max_age_s:.2f}s",
                "frame_fail",
            )

        mean = self._mean_luminance()
        if mean is not None:
            if mean < self._min_b:
                return RiskVerdict(
                    False,
                    f"head-cam frame too dark (mean {mean:.0f} < {self._min_b})",
                    "frame_fail",
                )
            if mean > self._max_b:
                return RiskVerdict(
                    False,
                    f"head-cam frame too bright (mean {mean:.0f} > {self._max_b})",
                    "frame_fail",
                )

        # 3. GPT-5.5 call lands in Task 3.
        return RiskVerdict(False, "not implemented yet", "frame_fail")
```

Add the helper just above `evaluate()`:

```python
    def _mean_luminance(self) -> Optional[float]:
        """Mean of the BGR head frame, or None if not retrievable.

        We use the latest_head_bgr() ndarray rather than decoding the JPEG
        again — CameraHub already keeps the array around.
        """
        getter = getattr(self._cam, "latest_head_bgr", None)
        if not callable(getter):
            return None
        try:
            arr = getter()
        except Exception:
            log.debug("latest_head_bgr raised", exc_info=True)
            return None
        if arr is None:
            return None
        try:
            return float(arr.mean())
        except Exception:
            log.debug("ndarray .mean() failed", exc_info=True)
            return None
```

- [ ] **Step 2.4: Run, all frame-health tests pass**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_vision_risk_gate.py -x -q`

Expected: 11 tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add g1_brain/safety/vision_risk_gate.py tests/test_vision_risk_gate.py
git commit -m "feat(safety): vision_risk_gate frame health checks"
```

---

## Task 3: GPT-5.5 call + parsing + timeout + api_error

**Files:**
- Modify: `g1_brain/safety/vision_risk_gate.py`
- Modify: `tests/test_vision_risk_gate.py`

- [ ] **Step 3.1: Add failing tests for the LLM path**

Append to `tests/test_vision_risk_gate.py`:

```python
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
```

- [ ] **Step 3.2: Run, see 6 new failures**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_vision_risk_gate.py -x -q`

Expected: 6 failures with `source == 'frame_fail'` for the LLM-path tests.

- [ ] **Step 3.3: Implement the LLM path + parser + prompt**

In `g1_brain/safety/vision_risk_gate.py`, add the module-level prompt template and helpers below the `_BYPASS_SAFE` definition:

```python
_VERDICT_RE = re.compile(r"^(SAFE|RISK)\s*:\s*(.+?)\s*$", re.IGNORECASE)


_PROMPT_TEMPLATE = """\
You are the safety reviewer for a Unitree G1 humanoid robot operating in
autonomous mode. The robot is about to execute the action below. The image
is the robot's first-person head-camera frame, taken < 2 s ago.

Decide whether to let the robot proceed without operator approval.

### Action
{action_sentence}

### RISK if any of the following is visible in the frame
A. Humans
   A1. Any person within ~1.5 m in the direction of motion (standing/sitting/squatting).
   A2. A child (estimated height < 1.2 m) anywhere in frame.
   A3. An elderly person or anyone with cane/walker/wheelchair anywhere in frame.
   A4. A person with their back turned to the robot.
   A5. A person doing fine-motor tasks (writing, typing, holding a cup, using a knife)
       within the action's reach (1.5 m for walk, 0.6 m for arm motions).
   A6. A person lying or seated on the floor.
   A7. For arm motions (gesture/static_pose/mock_imitate): any person within 0.6 m.

B. Animals
   B1. Any pet/animal anywhere in frame -- reactions are unpredictable.

C. Fragile / valuable items along the path (1.5 m forward) or arm sweep (0.6 m)
   C1. Glassware (cups, bottles, vases, fish tanks).
   C2. Electronics (laptop, phone, tablet, monitor, headphones).
   C3. Camera gear (cameras, tripods).
   C4. Musical instruments.
   C5. Art / decor (frames, sculptures) within arm sweep.
   C6. Filled liquid containers on tables that the arm sweep would pass over.

D. Dangerous items (RISK at any distance -- proximity itself is wrong)
   D1. Knives, scissors, broken glass, sharp tool tips.
   D2. Open flame, candles, stoves, heaters, irons.
   D3. Liquid spills, water/oil puddles (slip risk).
   D4. Exposed power outlets, loose cables on the floor.
   D5. Chemical containers (cleaners, paint, lab bottles).
   D6. Food spills / grease patches.

E. Surfaces / terrain
   E1. Stairs going down OR up.
   E2. Floor height-step > 5 cm (cliff edge, platform edge, balcony threshold).
   E3. Visible dark hole (drain, manhole).
   E4. Polished/reflective floor (slip risk).
   E5. Rumpled rug, raised cable, lip on the floor.
   E6. Floor not visible (camera obstructed, pointed at ceiling/wall).
   E7. Wet/oily-looking patch.

F. Spatial / geometry
   F1. Corridor or wall-gap < 1.2 m wide AND action is turn(>60 deg) or wide gesture.
   F2. Low ceiling / overhead obstacle within ~1.6 m of robot's head height.
   F3. Doorway directly ahead (frame may scrape even with clear path).
   F4. Stairwell drop / open-railing edge.

G. Robot self state visible in frame
   G1. Robot's own arm already touching/near an object.
   G2. Horizon tilted > 15 deg (already unstable).
   G3. Severe motion blur in current frame (slipping or shaking).

### SAFE only if ALL of these hold
S1. No item in A--G applies.
S2. The 1.5 m corridor in front of the robot (for walks) or the 0.6 m arm
    sweep zone (for arm motions) is clearly empty floor / empty space.
S3. The image is well-lit and you can see the floor clearly.
S4. Action parameters are reasonable for the visible space (not asked to walk
    further than you can see, not asked to turn into a wall, etc.).

### Output schema (STRICT -- any deviation will be treated as RISK)
Return EXACTLY one line in this format and NOTHING ELSE:

  SAFE: <<=15-word reason>
or
  RISK: <<=15-word reason>

Examples:
  SAFE: clear empty floor for 3 m, no people, no fragile items
  RISK: person sitting 0.7 m ahead facing left, walk would intrude
  RISK: glass coffee cup on path within 1 m
  RISK: descending stairs 1 m ahead

When in doubt -> RISK. Never elaborate, never ask, never explain. One line.
"""


def _describe_action(tool: str, sanitized: Dict[str, Any]) -> str:
    """Render tool+args as a single English sentence for the LLM."""
    if tool == "walk":
        vx = float(sanitized.get("vx", 0.0))
        vy = float(sanitized.get("vy", 0.0))
        wz = float(sanitized.get("wz", 0.0))
        dur = float(sanitized.get("duration_s", 0.0))
        if abs(vy) < 1e-3 and abs(wz) < 1e-3 and vx > 0:
            dist = vx * dur
            return (
                f"walk forward at {vx:.2f} m/s for {dur:.1f} s "
                f"(~{dist:.1f} m total)"
            )
        return (
            f"walk with vx={vx:.2f} vy={vy:.2f} wz={wz:.2f} for {dur:.1f} s"
        )
    if tool == "turn":
        yaw = float(sanitized.get("yaw_deg", 0.0))
        dur = abs(yaw) * (3.14159 / (180.0 * 0.25))  # mirrors skill_server
        return f"turn {yaw:+.0f} degrees in place at ~14 deg/s (~{dur:.1f} s)"
    if tool == "gesture":
        return (
            f"perform arm gesture \"{sanitized.get('name', '?')}\"; "
            "arm sweep radius ~0.6 m"
        )
    if tool == "static_pose":
        return (
            f"change body pose to \"{sanitized.get('name', '?')}\"; "
            "arms move to a fixed position"
        )
    if tool == "look_at":
        return (
            f"aim head/torso toward \"{sanitized.get('target', '?')}\" "
            "-- minimal locomotion"
        )
    if tool == "approach":
        return (
            f"walk forward to ~{float(sanitized.get('target_distance_m', 1.0)):.1f} m "
            f"from \"{sanitized.get('target_name', '?')}\""
        )
    if tool == "mock_imitate":
        return (
            f"mirror the user's \"{sanitized.get('gesture', '?')}\" gesture; "
            "large arm sweep"
        )
    return f"execute tool {tool!r} with args {sanitized!r}"
```

Then replace the placeholder return at the bottom of `evaluate()` with:

```python
        # 3. GPT-5.5 call.
        prompt = _PROMPT_TEMPLATE.format(
            action_sentence=_describe_action(tool, sanitized)
        )
        try:
            text = await asyncio.wait_for(
                self._vision.describe(
                    image_jpeg_b64=jpeg_b64,
                    prompt=prompt,
                    detail=self._detail,
                ),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            return RiskVerdict(
                False,
                f"vision call timed out after {self._timeout_s:.1f}s",
                "timeout",
            )
        except Exception as e:  # noqa: BLE001
            log.warning("vision_gate api error: %s", e)
            return RiskVerdict(False, f"vision api error: {e!s}"[:120], "api_error")

        return _parse_verdict(text)
```

Add the parser at module bottom:

```python
def _parse_verdict(text: str) -> RiskVerdict:
    s = (text or "").strip()
    if not s:
        return RiskVerdict(False, "vision returned empty text", "parse_fail")
    first = s.splitlines()[0].strip()
    m = _VERDICT_RE.match(first)
    if not m:
        snippet = s[:60].replace("\n", " ")
        return RiskVerdict(
            False,
            f"vision returned malformed text: {snippet}",
            "parse_fail",
        )
    verdict, reason = m.group(1).upper(), m.group(2).strip()
    return RiskVerdict(
        verdict == "SAFE",
        reason[:120],
        "vision_llm",
    )


__all__ = ["RiskVerdict", "VisionRiskGate"]
```

- [ ] **Step 3.4: Run, all 17 tests pass**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_vision_risk_gate.py -x -q`

Expected: 17 tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add g1_brain/safety/vision_risk_gate.py tests/test_vision_risk_gate.py
git commit -m "feat(safety): VisionRiskGate GPT-5.5 call + parsing"
```

---

## Task 4: Wire `vision_gate` into `SafetySupervisor` (Rule 12)

**Files:**
- Modify: `g1_brain/safety/supervisor.py`
- Modify: `tests/test_safety_supervisor.py`

- [ ] **Step 4.1: Add failing supervisor-integration tests**

Append to `tests/test_safety_supervisor.py`:

```python
# Rule 12: vision risk gate ----------------------------------------------

class _StubGate:
    """Stand-in for VisionRiskGate.evaluate."""

    def __init__(self, verdict_safe: bool, reason: str = "stub") -> None:
        from g1_brain.safety.vision_risk_gate import RiskVerdict
        self._verdict = RiskVerdict(verdict_safe, reason, "vision_llm")
        self.calls = 0

    async def evaluate(self, tool, sanitized):
        self.calls += 1
        return self._verdict


async def test_active_with_safe_gate_skips_confirm(env):
    gate = _StubGate(verdict_safe=True, reason="clear floor")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "active"
    fn = AsyncMock(return_value=True)
    env["sup"]._confirm_fn = fn
    ok, _, sanitized = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True
    assert sanitized["vx"] == pytest.approx(0.1)
    assert gate.calls == 1
    fn.assert_not_called()


async def test_active_with_risk_gate_calls_confirm_with_reason(env):
    gate = _StubGate(verdict_safe=False, reason="person 0.5 m ahead")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "active"
    received = {}

    async def fn(tool, sanitized, risk_reason=None):
        received["tool"] = tool
        received["risk_reason"] = risk_reason
        return True

    env["sup"]._confirm_fn = fn
    ok, _, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True
    assert gate.calls == 1
    assert received["risk_reason"] == "person 0.5 m ahead"
    assert received["tool"] == "walk"


async def test_confirm_with_safe_gate_skips_confirm(env):
    """The biggest UX win: confirm-mode operator stops being asked
    when the vision gate already said SAFE."""
    gate = _StubGate(verdict_safe=True, reason="empty hallway")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "confirm"
    fn = AsyncMock(return_value=True)
    env["sup"]._confirm_fn = fn
    ok, _, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True
    assert gate.calls == 1
    fn.assert_not_called()


async def test_confirm_with_risk_gate_calls_confirm_with_reason(env):
    gate = _StubGate(verdict_safe=False, reason="glass cup on path")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "confirm"
    received = {}

    async def fn(tool, sanitized, risk_reason=None):
        received["risk_reason"] = risk_reason
        return False

    env["sup"]._confirm_fn = fn
    ok, reason, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is False
    assert "declined" in reason
    assert received["risk_reason"] == "glass cup on path"


async def test_no_gate_preserves_old_behaviour_active(env):
    env["sup"].vision_gate = None
    env["sup"].run_mode = "active"
    ok, _, _ = await env["sup"].validate(
        "walk", {"vx": 0.1, "duration_s": 0.5}
    )
    assert ok is True


async def test_gate_skipped_for_non_motion_tools(env):
    """Non-motion tools take the early `is_motion=False` return — they
    must not consume the gate even when one is wired in."""
    gate = _StubGate(verdict_safe=False, reason="should never be called")
    env["sup"].vision_gate = gate
    env["sup"].run_mode = "active"
    ok, _, _ = await env["sup"].validate("say", {"text": "hi"})
    assert ok is True
    assert gate.calls == 0
```

- [ ] **Step 4.2: Update existing `test_confirm_calls_confirm_fn_*` tests to accept the new keyword arg**

In `tests/test_safety_supervisor.py`, the two existing tests `test_confirm_calls_confirm_fn_yes` and `test_confirm_calls_confirm_fn_no` use `AsyncMock(return_value=...)`. `AsyncMock` already accepts arbitrary kwargs, so they keep passing — but the supervisor will now call them with `risk_reason=None`. We must update the asserts not to use `assert_awaited_once()` against a positional-only signature; they currently say `fn.assert_awaited_once()` which is signature-agnostic. **No change needed** — confirm by reading them.

- [ ] **Step 4.3: Run the new tests, confirm failures**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_safety_supervisor.py -x -q -k "gate"`

Expected: every new test errors with `AttributeError: 'SafetySupervisor' object has no attribute 'vision_gate'` or similar.

- [ ] **Step 4.4: Modify `SafetySupervisor` to accept and use the gate**

In `g1_brain/safety/supervisor.py`:

1. Update the `ConfirmFn` type and `_confirm_in_terminal` signature to accept the optional `risk_reason`:

   Replace:
   ```python
   ConfirmFn = Callable[[str, Dict[str, Any]], Awaitable[bool]]
   ```
   with:
   ```python
   ConfirmFn = Callable[..., Awaitable[bool]]   # (tool, sanitized, risk_reason=None) -> bool
   ```

2. Update `_confirm_in_terminal`:

   Replace its signature:
   ```python
   async def _confirm_in_terminal(tool: str, sanitized: Dict[str, Any]) -> bool:
   ```
   with:
   ```python
   async def _confirm_in_terminal(
       tool: str,
       sanitized: Dict[str, Any],
       risk_reason: Optional[str] = None,
   ) -> bool:
   ```

   And replace the `msg = (...)` line with:
   ```python
       header = f"\n[g1_brain confirm] execute {tool}({sanitized}) ?\n"
       if risk_reason:
           header += f"[RISK] {risk_reason}\n"
       msg = header + "press y to accept, any other key to decline: "
   ```

3. Update `SafetySupervisor.__init__` to accept and store `vision_gate`:

   Add to the constructor signature:
   ```python
       vision_gate: Optional["VisionRiskGate"] = None,
   ```
   (Use `from .vision_risk_gate import VisionRiskGate` at module top, or use a string annotation to dodge the circular risk.)

   Add inside `__init__`:
   ```python
       self.vision_gate = vision_gate
   ```

4. Insert the new gate step in `validate()`. Find the comment block that currently reads `# --- Rule 3 (continued): confirm prompt ------------------------------` and the `if self.run_mode == "confirm":` line. Replace both with:

   ```python
       # --- Rule 12: vision risk gate -------------------------------------
       risk_reason: Optional[str] = None
       if self.vision_gate is not None:
           verdict = await self.vision_gate.evaluate(tool, sanitized)
           log.info(
               "[vision_gate] tool=%s verdict=%s source=%s reason=%s",
               tool,
               "SAFE" if verdict.safe else "RISK",
               verdict.source,
               verdict.reason,
           )
           if verdict.safe:
               return True, "", sanitized
           risk_reason = verdict.reason

       # --- Rule 3 (continued): confirm prompt ----------------------------
       if self.run_mode == "confirm" or risk_reason is not None:
           ok = await self._confirm_fn(tool, sanitized, risk_reason=risk_reason)
           if not ok:
               return False, "operator declined in confirm mode", {}
   ```

   Note: pass `risk_reason=risk_reason` so custom `confirm_fn`s that ignore the kwarg (e.g., `AsyncMock`) keep working — `AsyncMock` accepts arbitrary kwargs silently.

- [ ] **Step 4.5: Run all supervisor tests, confirm green**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_safety_supervisor.py -x -q`

Expected: all existing 39 tests + 6 new tests pass = 45 tests pass.

- [ ] **Step 4.6: Commit**

```bash
git add g1_brain/safety/supervisor.py tests/test_safety_supervisor.py
git commit -m "feat(safety): supervisor consumes vision gate as Rule 12"
```

---

## Task 5: Build the gate in `agent_main` + add config defaults

**Files:**
- Modify: `g1_brain/apps/agent_main.py`
- Modify: `configs/g1_brain.yaml`

- [ ] **Step 5.1: Add the YAML config block**

In `configs/g1_brain.yaml`, locate the `safety:` block and append (under `safety:`, after the `estop:` subblock):

```yaml
  vision_gate:
    # New: GPT-5.5 vision-based risk gate (spec docs/g1_v1.md). When enabled,
    # every motion tool call gets a "is this safe to do unattended?" review
    # against the latest head-cam JPEG. SAFE -> auto-execute regardless of
    # run_mode. RISK -> fall through to the existing terminal y/N. With this
    # off, behaviour reverts bit-for-bit to the pre-design build.
    enabled: true
    timeout_s: 5.0          # GPT-5.5 hard timeout; on timeout -> RISK
    max_frame_age_s: 2.0    # head-cam JPEG older than this -> RISK
    min_brightness: 30      # 0-255 mean luminance; below -> RISK (too dark)
    max_brightness: 235     # 0-255 mean luminance; above -> RISK (white-out)
    detail: "auto"          # OpenAI image detail: low / high / auto / original
```

- [ ] **Step 5.2: Build the gate after `vision_client` in `agent_main`**

In `g1_brain/apps/agent_main.py`, find the lines that construct `vision_client` (around line 933) — they look like:

```python
    vision_client = va_vision.VisionClient(
        openai_client,
        model=os.environ.get("OPENAI_VISION_MODEL", cfg["openai"]["vision_model"]),
        default_detail=cfg["openai"]["vision_detail"],
    )
```

Insert directly after, before the `# ---- conversation logger ----` block:

```python
    # ---- vision risk gate (Rule 12) ----
    vision_gate = None
    vg_cfg = (cfg.get("safety", {}) or {}).get("vision_gate", {}) or {}
    if vg_cfg.get("enabled", True):
        from ..safety.vision_risk_gate import VisionRiskGate  # noqa: WPS433
        vision_gate = VisionRiskGate(
            vision_client=vision_client,
            camera_hub=camera_hub,
            cfg=cfg,
        )
        log.info(
            "vision_gate enabled (timeout=%.1fs, max_frame_age=%.1fs, detail=%s)",
            float(vg_cfg.get("timeout_s", 5.0)),
            float(vg_cfg.get("max_frame_age_s", 2.0)),
            vg_cfg.get("detail", "auto"),
        )
    else:
        log.info(
            "vision_gate DISABLED -- RISK fallthrough off; "
            "active mode is fully autonomous"
        )
```

- [ ] **Step 5.3: Pass the gate to `SafetySupervisor`**

In the same file, find the `SafetySupervisor(...)` constructor call (it currently ends with `perception_enabled=not args.no_perception,`). Move the gate construction so that it lives *before* the supervisor is built (we need to reorder if `vision_client` is built after the supervisor — check first).

Read the file to confirm the ordering. If `vision_client` is currently built **after** `SafetySupervisor`, move the gate construction up to a point **after** `vision_client` is created and **before** `SafetySupervisor(...)`. The gate needs both `vision_client` and `camera_hub`; `camera_hub` is already built earlier than the supervisor.

Then add the new kwarg to the `SafetySupervisor(...)` call:

```python
    safety = SafetySupervisor(
        cfg=cfg,
        scene_bus=scene_bus,
        robot_bus=robot_bus,
        fsm=fsm,
        estop=estop,
        run_mode=run_mode,
        perception_enabled=not args.no_perception,
        vision_gate=vision_gate,
    )
```

- [ ] **Step 5.4: Manual smoke check — module imports cleanly**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -c "from g1_brain.apps import agent_main; print('ok')"`

Expected: `ok` (no import errors).

- [ ] **Step 5.5: Run the apps smoke test**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_apps_smoke.py -x -q`

Expected: pass (test exists and exercises agent_main wiring).

- [ ] **Step 5.6: Run full test suite to catch regressions**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest -x -q`

Expected: all green.

- [ ] **Step 5.7: Commit**

```bash
git add g1_brain/apps/agent_main.py configs/g1_brain.yaml
git commit -m "feat(agent): build VisionRiskGate, wire into SafetySupervisor"
```

---

## Task 6: Soften "always describe_scene before walk" rule in brain prompt

**Files:**
- Modify: `g1_brain/brain/prompts.py`

- [ ] **Step 6.1: Update REALTIME_SYSTEM_PROMPT_BRAIN**

In `g1_brain/brain/prompts.py`, find the rule that currently reads:

```
- Before you walk forward, ALWAYS call describe_scene or query_scene_state
  to confirm the path is clear. Never walk based on memory of an older frame.
  Backward walks (vx<0) do NOT need a pre-call to describe_scene/look_at —
  the head camera does not see behind, and the walk skill aborts on its own
  if its forward perception trips. For "step back N meters" issue ONE walk
  call with vx=-0.2 and duration_s=N/0.2.
```

Replace with:

```
- A vision-risk gate vets every motion call against the head-camera image
  before it runs. You do NOT need to chain a describe_scene immediately
  before a walk for safety reasons — the gate will either auto-approve
  (clear path), or fall through to a terminal y/N if it sees a person,
  fragile item, stairs, etc. Only call describe_scene when the user
  explicitly asks "what do you see" or you genuinely need to plan a
  multi-step approach. Backward walks (vx<0) always trigger the gate's
  human-confirm path because the head camera cannot see behind — issue
  ONE walk(vx=-0.2, duration_s=N/0.2) call for "step back N meters" and
  expect a single confirm prompt.
```

- [ ] **Step 6.2: Run prompt tests**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest tests/test_brain_prompts.py -x -q`

Expected: pass. If a test asserts on the literal old string, update it to the new wording.

- [ ] **Step 6.3: Commit**

```bash
git add g1_brain/brain/prompts.py
git commit -m "docs(brain): soften pre-walk describe_scene rule (gate handles it)"
```

---

## Task 7: Final integration sweep

**Files:**
- (no source changes; verification + small follow-ups)

- [ ] **Step 7.1: Run the full test suite end-to-end**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && python -m pytest -q`

Expected: all green. If any test fails because it constructed `SafetySupervisor` with positional args that no longer match the new constructor, fix the test by switching to kwargs or by passing `vision_gate=None` explicitly.

- [ ] **Step 7.2: Confirm log lines render correctly**

Run a tiny inline smoke (no DDS, no real OpenAI):

```bash
cd /home/helios/unitree/unitree-notes/g1_brain
python -c "
import logging, asyncio
logging.basicConfig(level=logging.INFO, format='%(message)s')
from unittest.mock import AsyncMock, MagicMock
from g1_brain.safety.vision_risk_gate import VisionRiskGate

vision = MagicMock()
async def _ok(*a, **k): return 'SAFE: clear hallway'
vision.describe = _ok

class _Cam:
    def latest_head_jpeg_b64(self, *a, **k): return 'ZmFrZQ=='
    def latest_head_bgr(self):
        import numpy as np
        return np.full((4,4,3), 128, dtype='uint8')
    def head_frame_age_seconds(self): return 0.1

cfg = {'safety': {'vision_gate': {'enabled': True}}}
gate = VisionRiskGate(vision_client=vision, camera_hub=_Cam(), cfg=cfg)
v = asyncio.run(gate.evaluate('walk', {'vx': 0.2, 'duration_s': 5.0}))
print('VERDICT:', v)
"
```

Expected: prints `VERDICT: RiskVerdict(safe=True, reason='clear hallway', source='vision_llm')`.

- [ ] **Step 7.3: Final commit (housekeeping only if anything was patched)**

If Step 7.1 required fixes:

```bash
git add <fixed files>
git commit -m "test: align supervisor constructions with new vision_gate kwarg"
```

If nothing needed fixing, skip this step.

---

## Self-review checklist (run after writing the plan)

- [x] Spec coverage:
  - Approach C orthogonal flag → Tasks 4 + 5 (`enabled`, supervisor optional kwarg).
  - Bypass rules (P1 backward, P2 say/static_pose) → Task 1.
  - Frame health checks → Task 2.
  - GPT-5.5 prompt + parse + timeout + api_error → Task 3.
  - Supervisor Rule 12 + risk_reason in y/N → Task 4.
  - Config defaults → Task 5.
  - agent_main startup log line → Task 5.
  - Brain-prompt update → Task 6.
- [x] Placeholders: every code step has full code; no "TBD"; no "implement appropriate".
- [x] Type consistency: `RiskVerdict(safe, reason, source)` consistent across Tasks 1–4. `vision_gate` kwarg name consistent. `VerdictSource` enum names consistent.
