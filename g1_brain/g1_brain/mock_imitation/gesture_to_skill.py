"""Pure mapping: detected user gesture → SkillServer call dict.

We deliberately keep this module side-effect-free so it can be unit-tested
without the SkillServer / DDS / OpenAI present.

Mirrorability source-of-truth is ``GestureLabel.MIRRORABLE`` in
``scene_state.types``; we re-export it here as ``MIRRORABLE_GESTURES`` for
convenience and to keep import sites short.
"""
from __future__ import annotations

from typing import Optional, Dict

from ..scene_state.types import GestureLabel


MIRRORABLE_GESTURES = tuple(GestureLabel.MIRRORABLE)


# Polite acknowledgement phrases per mirrorable gesture, per language.
# Spoken before the actual mock_imitate call so the user understands why
# the robot is moving.
_ACK_ZH: Dict[str, str] = {
    GestureLabel.WAVE_RIGHT: "我看到你在挥手, 我也挥一下。",
    GestureLabel.WAVE_LEFT: "我看到你用左手挥手, 我也挥一下。",
    GestureLabel.HANDS_UP: "我看到你举起双手, 我也举一下。",
    GestureLabel.T_POSE: "我看到你摆出 T-pose, 我也摆一下。",
}

_ACK_EN: Dict[str, str] = {
    GestureLabel.WAVE_RIGHT: "I see you waving, let me wave back.",
    GestureLabel.WAVE_LEFT: "I see your left-hand wave, let me mirror it.",
    GestureLabel.HANDS_UP: "I see your hands up, let me raise mine too.",
    GestureLabel.T_POSE: "I see your T-pose, let me match it.",
}


def map_user_gesture_to_skill_call(gesture: str) -> Optional[dict]:
    """Map a user gesture label to a SkillServer call dict.

    Returns ``{"tool": "gesture", "args": {"name": <gesture>}}`` if the
    gesture is mirrorable; ``None`` otherwise.

    Note: the brain prefers calling ``mock_imitate(gesture=...)`` (an L1
    high-level intent) rather than ``gesture(name=...)`` directly. Both work;
    this helper returns the L2 form because the GestureAutoTrigger uses it
    only as a *suggestion* embedded in the perception event text — the actual
    tool dispatch is the LLM's choice.
    """
    if gesture in MIRRORABLE_GESTURES:
        return {"tool": "gesture", "args": {"name": gesture}}
    return None


def build_acknowledgment_phrase(gesture: str, lang: str = "zh") -> str:
    """Polite sentence the brain can ``say`` before calling mock_imitate.

    Falls back to a generic English template if the gesture or language is
    unknown. The returned text always mentions the gesture name (verbatim
    or via a natural-language synonym) so prompt-style assertions can match.
    """
    table = _ACK_EN if lang == "en" else _ACK_ZH
    if gesture in table:
        return table[gesture]
    # Fallback: still reference the gesture explicitly so the LLM / tests can
    # tell which one we are acknowledging.
    if lang == "en":
        return f"I see your {gesture}, let me mirror it."
    return f"我看到你做了 {gesture}, 我也来一下。"


__all__ = [
    "MIRRORABLE_GESTURES",
    "map_user_gesture_to_skill_call",
    "build_acknowledgment_phrase",
]
