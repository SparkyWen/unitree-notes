"""Derive a CapabilityDescriptor from the real tool catalog.

Single source of truth = g1_brain.skills.tool_schemas.build_tool_schemas().
Risk levels live here (not in the schema) and are classified per tool name.
"""
from __future__ import annotations

from typing import Literal

from g1_brain.skills.tool_schemas import build_tool_schemas

from .models import CapabilityDescriptor, CapabilityEntry

# Risk classification by tool name. Motion tools carry the highest risk; pure
# information tools are "none". Keep in sync with SafetySupervisor's ALLOWED sets.
_RISK = {
    "walk": "medium", "turn": "medium", "approach": "medium",
    "gesture": "low", "static_pose": "low", "look_at": "low", "mock_imitate": "low",
    "stop": "low", "release_arms": "low",
    "loco_high": "high", "arm_action_high": "high", "audio_tts_robot": "low",
}


def _risk_for(name: str) -> str:
    return _RISK.get(name, "none")


def build_capability_descriptor(
    *, robot_id: str, harness_version: str = "0.1.0",
    trust_level: Literal["sim", "dev", "production_certified"] = "sim", frame_id: str | None = None, sim: bool = True,
) -> CapabilityDescriptor:
    schemas = build_tool_schemas(sim=sim)
    caps = [
        CapabilityEntry(
            name=s["name"],
            risk_level=_risk_for(s["name"]),
            params_schema=f"{s['name']}.v1",
        )
        for s in schemas
    ]
    return CapabilityDescriptor(
        robot_id=robot_id,
        harness_version=harness_version,
        trust_level=trust_level,
        frame_id=frame_id or f"{robot_id}/map",
        capabilities=caps,
    )
