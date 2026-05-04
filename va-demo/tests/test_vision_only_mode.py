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
