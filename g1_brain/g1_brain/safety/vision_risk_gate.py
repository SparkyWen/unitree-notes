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
