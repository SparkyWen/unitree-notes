"""Pretty-print SceneState for the brain.

Two helpers:

- ``scene_state_to_text(scene)`` → one-line English sentence, used as the
  ``query_scene_state`` tool reply pretty-print. The brain prompt is English;
  OpenAI translates the spoken reply into the user's language as needed.

- ``attach_scene_to_result(result, scene)`` → returns a copy of ``result`` with
  a ``scene_after`` key containing ``scene.summary_for_llm()``. Motion-skill
  returns can use this so the brain has fresh perception context attached to
  every tool reply, without the brain having to call ``query_scene_state``
  after every move.
"""
from __future__ import annotations

from typing import Optional

from ..scene_state.types import SceneState


def scene_state_to_text(scene: Optional[SceneState]) -> str:
    """Render a SceneState as a single English sentence."""
    if scene is None:
        return "Scene: no perception data yet."
    s = scene.summary_for_llm()
    parts = []
    persons = s.get("persons_visible") or 0
    parts.append(f"{persons} person(s) visible")
    no = s.get("nearest_obstacle_m")
    if no is None:
        parts.append("no obstacle in the forward cone")
    else:
        parts.append(f"nearest obstacle ahead {no:.2f} m")
    np_ = s.get("nearest_person_m")
    if np_ is not None:
        parts.append(f"nearest person {np_:.2f} m")
    cp = s.get("clear_path")
    if cp is True:
        parts.append("path clear")
    elif cp is False:
        parts.append("path blocked")
    tilt = s.get("surface_tilt_deg")
    if tilt is not None:
        parts.append(f"floor tilt {tilt:.1f} deg")
    g = s.get("user_gesture")
    if g:
        conf = s.get("user_gesture_confidence", 0.0) or 0.0
        parts.append(f"user gesture {g} (conf {conf:.2f})")
    warns = s.get("warnings") or []
    if warns:
        parts.append("warnings: " + ", ".join(warns))
    return "Scene: " + "; ".join(parts) + "."


def attach_scene_to_result(result: dict, scene: Optional[SceneState]) -> dict:
    """Return a shallow copy of ``result`` with ``scene_after`` attached.

    ``scene_after`` is the dict from ``SceneState.summary_for_llm()``. If
    ``scene`` is None we still attach an empty dict so the LLM sees the field
    consistently (and knows perception has nothing to report).
    """
    out = dict(result) if result else {}
    out["scene_after"] = scene.summary_for_llm() if scene is not None else {}
    return out


__all__ = ["scene_state_to_text", "attach_scene_to_result"]
