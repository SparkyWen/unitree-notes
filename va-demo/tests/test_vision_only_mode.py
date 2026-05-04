"""Unit tests for vision-only mode tool schema + prompt selection."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.realtime_agent import _build_tool_schemas


def test_tool_schemas_default_keeps_all_tools():
    schemas = _build_tool_schemas()  # default vision_only=False
    names = {s["name"] for s in schemas}
    assert names == {"say", "stop", "release_arms", "walk", "gesture", "describe_scene"}


def test_tool_schemas_vision_only_excludes_motion_tools():
    schemas = _build_tool_schemas(vision_only=True)
    names = {s["name"] for s in schemas}
    assert names == {"say", "describe_scene"}


def test_tool_schemas_vision_only_keeps_describe_scene_shape():
    """The describe_scene schema in vision-only mode is identical to default."""
    full = {s["name"]: s for s in _build_tool_schemas(vision_only=False)}
    vis = {s["name"]: s for s in _build_tool_schemas(vision_only=True)}
    assert vis["describe_scene"] == full["describe_scene"]
    assert vis["say"] == full["say"]


def test_vision_only_prompt_exists_and_excludes_motion_words():
    from va_demo.prompts import REALTIME_SYSTEM_PROMPT, REALTIME_SYSTEM_PROMPT_VISION_ONLY

    p = REALTIME_SYSTEM_PROMPT_VISION_ONLY
    assert p, "vision-only prompt is empty"
    # Must NOT advertise motion tools
    assert "walk" not in p.lower()
    assert "gesture" not in p.lower()
    # Must still mention describe_scene and the self-name rule (carried over)
    assert "describe_scene" in p
    assert "Sparky" in p
    # Must be a different string from the default (sanity)
    assert p != REALTIME_SYSTEM_PROMPT


def test_realtime_agent_vision_only_resolves_to_vision_prompt_and_schemas():
    """RealtimeAgent.vision_only=True must select the vision prompt and
    the trimmed schema set. We construct the agent with stub deps so we
    can read its resolved values without going async."""
    from unittest.mock import MagicMock

    from va_demo.prompts import REALTIME_SYSTEM_PROMPT, REALTIME_SYSTEM_PROMPT_VISION_ONLY
    from va_demo.realtime_agent import RealtimeAgent

    stub = MagicMock()
    common = dict(
        api_key="sk-test",
        model="gpt-realtime",
        voice="alloy",
        mic=stub,
        speaker=stub,
        camera=stub,
        vision=stub,
        tts=stub,
        skills=None,
        safety=stub,
    )

    a_default = RealtimeAgent(**common)  # vision_only defaults to False
    assert a_default.vision_only is False
    assert a_default._resolve_instructions() == REALTIME_SYSTEM_PROMPT
    names = {s["name"] for s in a_default._resolve_tool_schemas()}
    assert "walk" in names and "describe_scene" in names

    a_vision = RealtimeAgent(vision_only=True, **common)
    assert a_vision.vision_only is True
    assert a_vision._resolve_instructions() == REALTIME_SYSTEM_PROMPT_VISION_ONLY
    names = {s["name"] for s in a_vision._resolve_tool_schemas()}
    assert names == {"say", "describe_scene"}
