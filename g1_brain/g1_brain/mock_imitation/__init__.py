"""Mock Imitation (Phase 5): perception → polite ack → gesture skill.

Two pieces:

- ``gesture_to_skill`` — pure mapping from a detected user gesture to a
  SkillServer call dict, plus a polite acknowledgement-phrase builder.
- ``auto_trigger`` — async background task that watches the SceneStateBus and
  injects a perception event into the brain when a mirrorable gesture is
  held with high confidence for long enough.
"""
from .gesture_to_skill import (
    MIRRORABLE_GESTURES,
    map_user_gesture_to_skill_call,
    build_acknowledgment_phrase,
)
from .auto_trigger import GestureAutoTrigger, AutoTriggerConfig, COOLDOWN_S

__all__ = [
    "MIRRORABLE_GESTURES",
    "map_user_gesture_to_skill_call",
    "build_acknowledgment_phrase",
    "GestureAutoTrigger",
    "AutoTriggerConfig",
    "COOLDOWN_S",
]
