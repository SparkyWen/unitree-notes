"""Tests for brain prompts — sanity-check the literal-word constraints
(vision-only must not contain ``walk`` or ``gesture`` to keep Sparky's TTS
from echoing into the wake/keyword detector) and verify the brain prompt
mentions every tool exposed by the SkillServer.
"""
from __future__ import annotations

import re

import pytest

from g1_brain.brain.prompts import (
    REALTIME_SYSTEM_PROMPT_BRAIN,
    REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY,
    VISION_SCENE_PROMPT_BRAIN,
)


# Canonical tool list per design doc §4.1 / spec
ALL_TOOL_NAMES = [
    # L1
    "say", "describe_scene", "query_scene_state", "look_at", "approach",
    "mock_imitate", "ask_human",
    # L2
    "walk", "turn", "gesture", "static_pose", "stop", "release_arms",
    # real-only
    "loco_high", "arm_action_high", "audio_tts_robot",
]


def test_vision_only_has_no_walk_or_gesture_word():
    """Defensive: Sparky's TTS could trip wake/keyword if these words echo back."""
    walks = re.findall(r"\bwalk\b", REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY, re.IGNORECASE)
    gests = re.findall(r"\bgesture\b", REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY, re.IGNORECASE)
    assert walks == [], f"vision-only prompt contains literal 'walk': {walks}"
    assert gests == [], f"vision-only prompt contains literal 'gesture': {gests}"


def test_vision_only_still_mentions_query_scene_state():
    """Users may ask 'what hand sign am I doing?' even in vision-only mode."""
    assert "query_scene_state" in REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY


def test_vision_only_mentions_describe_scene_and_say():
    p = REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY
    assert "describe_scene" in p
    assert "say" in p


@pytest.mark.parametrize("tool_name", ALL_TOOL_NAMES)
def test_brain_prompt_mentions_each_tool(tool_name):
    """Every canonical tool name must appear at least once in the brain prompt."""
    assert tool_name in REALTIME_SYSTEM_PROMPT_BRAIN, (
        f"REALTIME_SYSTEM_PROMPT_BRAIN does not mention tool '{tool_name}'"
    )


def test_brain_prompt_warns_about_real_only_tools():
    """The prompt must tell the LLM that loco_high / arm_action_high /
    audio_tts_robot will be rejected in sim, otherwise it will keep retrying."""
    p = REALTIME_SYSTEM_PROMPT_BRAIN
    assert "sim" in p.lower()
    assert "loco_high" in p
    assert "arm_action_high" in p
    assert "audio_tts_robot" in p


def test_brain_prompt_forbids_self_naming_sparky():
    """Same anti-echo defense as va-demo's prompt."""
    assert "Sparky" in REALTIME_SYSTEM_PROMPT_BRAIN
    assert "never refer to yourself as \"Sparky\"" in REALTIME_SYSTEM_PROMPT_BRAIN


def test_vision_scene_prompt_mentions_head_camera():
    """The added head-camera sentence is what differentiates this from va-demo's."""
    p = VISION_SCENE_PROMPT_BRAIN
    assert "head camera" in p
    assert "obstacle" in p.lower() or "free space" in p.lower() or "terrain" in p.lower()


def test_brain_realtime_agent_uses_vision_only_prompt_when_flagged(monkeypatch):
    """BrainRealtimeAgent._resolve_instructions must switch on vision_only."""
    # Stub va_demo so importing the agent doesn't require its real deps.
    import sys
    import types

    if "va_demo" not in sys.modules:
        va_demo = types.ModuleType("va_demo")
        va_demo_rt = types.ModuleType("va_demo.realtime_agent")

        class _StubRT:
            def __init__(self, *a, **k):
                self.vision_only = k.get("vision_only", False)

            def __post_init__(self):
                pass

        va_demo_rt.RealtimeAgent = _StubRT
        monkeypatch.setitem(sys.modules, "va_demo", va_demo)
        monkeypatch.setitem(sys.modules, "va_demo.realtime_agent", va_demo_rt)

    # Reload the module so it picks up the stub.
    import importlib
    import g1_brain.brain.realtime_agent as ra_mod
    importlib.reload(ra_mod)

    # Bypass the dataclass-on-stub mismatch by constructing manually.
    agent = ra_mod.BrainRealtimeAgent.__new__(ra_mod.BrainRealtimeAgent)
    agent.vision_only = True
    assert agent._resolve_instructions() == REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY
    agent.vision_only = False
    assert agent._resolve_instructions() == REALTIME_SYSTEM_PROMPT_BRAIN
