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
import inspect
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
        # Mirrors skill_server: ~14 deg/s.
        dur = abs(yaw) * (3.14159 / (180.0 * 0.25))
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

        # 3. GPT-5.5 call.
        prompt = _PROMPT_TEMPLATE.format(
            action_sentence=_describe_action(tool, sanitized)
        )
        # Plumb an HTTP-level timeout slightly looser than our outer
        # wait_for so the OpenAI SDK aborts cleanly *after* we have already
        # returned a "timeout" verdict — otherwise the synchronous SDK
        # call sits in a leaked executor thread until the SDK's default
        # ~10-minute timeout fires, and subsequent gate calls fight for
        # thread-pool slots.
        describe_kwargs: Dict[str, Any] = dict(
            image_jpeg_b64=jpeg_b64,
            prompt=prompt,
            detail=self._detail,
        )
        # `request_timeout_s` was added to va_demo.vision.VisionClient.describe
        # alongside this change. Test stubs and older VisionClient versions
        # may not accept the kwarg, so probe the signature before passing it.
        if self._describe_accepts_request_timeout_s():
            describe_kwargs["request_timeout_s"] = self._timeout_s + 1.0
        t0 = time.monotonic()
        try:
            text = await asyncio.wait_for(
                self._vision.describe(**describe_kwargs),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            dt = time.monotonic() - t0
            log.warning(
                "[vision_gate] vision call timed out after %.2fs (budget=%.1fs)",
                dt,
                self._timeout_s,
            )
            return RiskVerdict(
                False,
                f"vision call timed out after {self._timeout_s:.1f}s",
                "timeout",
            )
        except Exception as e:  # noqa: BLE001
            dt = time.monotonic() - t0
            log.warning("[vision_gate] api error after %.2fs: %s", dt, e)
            return RiskVerdict(False, f"vision api error: {e!s}"[:120], "api_error")

        dt = time.monotonic() - t0
        log.info(
            "[vision_gate] vision call returned in %.2fs (budget=%.1fs)",
            dt,
            self._timeout_s,
        )
        return _parse_verdict(text)

    def _describe_accepts_request_timeout_s(self) -> bool:
        """Whether the wrapped vision client's describe() accepts ``request_timeout_s``.

        Cached on first call. Older VisionClient versions and many test stubs
        do not advertise this kwarg; passing it unconditionally would TypeError.
        Inspecting the signature lets us stay compatible with both.
        """
        cached = getattr(self, "_accepts_rt_cache", None)
        if cached is not None:
            return cached
        try:
            sig = inspect.signature(self._vision.describe)
            params = sig.parameters
            accepts = (
                "request_timeout_s" in params
                or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
            )
        except (TypeError, ValueError):
            accepts = False
        self._accepts_rt_cache = accepts
        return accepts

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
        except Exception:  # noqa: BLE001
            log.debug("latest_head_bgr raised", exc_info=True)
            return None
        if arr is None:
            return None
        try:
            return float(arr.mean())
        except Exception:  # noqa: BLE001
            log.debug("ndarray .mean() failed", exc_info=True)
            return None


__all__ = ["RiskVerdict", "VisionRiskGate"]
