"""Slow Brain layer — extends va-demo's Realtime agent with the new
SkillServer + SceneState wiring.

Public surface:
- ``BrainRealtimeAgent`` — subclass of ``va_demo.realtime_agent.RealtimeAgent``
- ``REALTIME_SYSTEM_PROMPT_BRAIN`` / ``..._VISION_ONLY`` / ``VISION_SCENE_PROMPT_BRAIN``
- ``scene_state_to_text`` / ``attach_scene_to_result``

The realtime agent depends on ``va_demo`` being importable; the apps entry
point (``g1_brain.apps.agent_main``) is responsible for adding the va-demo
clone to ``sys.path``. We therefore lazy-import the agent here so importing
``g1_brain.brain.prompts`` or ``g1_brain.brain.scene_summary`` works in tests
without pulling in va-demo.
"""
from .prompts import (
    REALTIME_SYSTEM_PROMPT_BRAIN,
    REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY,
    VISION_SCENE_PROMPT_BRAIN,
)
from .scene_summary import scene_state_to_text, attach_scene_to_result

__all__ = [
    "REALTIME_SYSTEM_PROMPT_BRAIN",
    "REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY",
    "VISION_SCENE_PROMPT_BRAIN",
    "scene_state_to_text",
    "attach_scene_to_result",
    "BrainRealtimeAgent",
]


def __getattr__(name):  # pragma: no cover — trivial passthrough
    if name == "BrainRealtimeAgent":
        from .realtime_agent import BrainRealtimeAgent
        return BrainRealtimeAgent
    raise AttributeError(name)
