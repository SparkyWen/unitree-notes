"""g1_brain skill catalog: tool schemas + dispatcher for the LLM.

See `docs/g1_plan.md` §4. Top-level entry points:

    from g1_brain.skills.tool_schemas import build_tool_schemas
    from g1_brain.skills.skill_server import SkillServer
"""
from .tool_schemas import (
    build_tool_schemas,
    GESTURE_NAMES,
    STATIC_POSE_NAMES,
    LOOK_AT_TARGETS,
    MIRRORABLE_GESTURES,
)
from .skill_server import SkillServer
from .keyframe_extras import build_extra_arm_actions, ArmAction

__all__ = [
    "build_tool_schemas",
    "GESTURE_NAMES",
    "STATIC_POSE_NAMES",
    "LOOK_AT_TARGETS",
    "MIRRORABLE_GESTURES",
    "SkillServer",
    "build_extra_arm_actions",
    "ArmAction",
]
