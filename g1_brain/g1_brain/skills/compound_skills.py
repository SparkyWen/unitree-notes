"""L1 compound skills implemented in terms of L2 primitives on the SkillServer.

These are pure async functions taking ``(skill_server, args)`` so they're
easy to unit-test (just mock the server). Each one returns the same
``{ok, ...}`` dict shape SkillServer uses so the brain's tool dispatcher
sees a uniform response.

Where the spec says "delegate to L2", we always go through
``skill_server.execute(...)`` — that re-runs the safety validate path so a
compound skill can never sneak past a wall the operator put up.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Dict

log = logging.getLogger(__name__)


# ---- Constants ------------------------------------------------------------

# look_at: yaws (degrees, +ve = left) for fixed targets. Bounded to ±25°
# per call so a single look_at never violates the per-turn cap; for larger
# rotations the LLM should chain multiple calls.
_LOOK_AT_FIXED_YAW: Dict[str, float] = {
    "ahead":  0.0,
    "left":  25.0,
    "right": -25.0,
    "ground": 0.0,   # no head pitch on G1 in v1; treat as a no-op forward look
}
_LOOK_AT_MAX_DEG = 25.0

# approach: per-step velocity, step duration, and hard step cap. Tuned to
# stay well inside the safety envelope (vx_max=0.2 m/s in cfg).
_APPROACH_VX = 0.15
_APPROACH_STEP_S = 0.5
_APPROACH_MAX_STEPS = 6
_APPROACH_DIST_TOLERANCE_M = 0.1

# mock_imitate: subset that maps 1:1 onto a `gesture` skill. Must match
# scene_state.types.GestureLabel.MIRRORABLE and tool_schemas.MIRRORABLE_GESTURES.
MIRRORABLE_GESTURES = frozenset({"wave_right", "wave_left", "hands_up", "t_pose"})

# ask_human: how long we pause after speaking before yielding back. The
# user's actual answer flows through the normal Realtime audio channel;
# this skill is just "speak and wait a beat".
_ASK_HUMAN_LISTEN_S = 5.0


# ---- look_at --------------------------------------------------------------

async def look_at(skill_server, args: Dict[str, Any]) -> Dict[str, Any]:
    """Pick a yaw based on `target` and call the underlying `turn` skill.

    For `person`: use the latest scene snapshot to find the user's bearing
    (head_detections first, then user_pose midpoint). For fixed targets
    (left/right/ahead/ground) use the fixed yaw table.
    """
    target = args.get("target")
    if target not in {"person", "ahead", "left", "right", "ground"}:
        return {"ok": False, "skill": "look_at", "reason": f"unknown target: {target!r}"}

    yaw_deg: float
    if target == "person":
        scene = skill_server.scene.snapshot()
        bearing = _person_bearing_deg(scene)
        if bearing is None:
            return {
                "ok": False, "skill": "look_at",
                "reason": "no person visible in current scene",
            }
        yaw_deg = max(-_LOOK_AT_MAX_DEG, min(_LOOK_AT_MAX_DEG, bearing))
    else:
        yaw_deg = _LOOK_AT_FIXED_YAW[target]

    # No-op short-circuit: ahead/ground with zero yaw shouldn't bother turn.
    if abs(yaw_deg) < 1.0:
        return {"ok": True, "skill": "look_at", "target": target, "yaw_deg": yaw_deg}

    inner = await skill_server.execute("turn", {"yaw_deg": float(yaw_deg)})
    inner.setdefault("skill", "look_at")
    inner["target"] = target
    inner["yaw_deg"] = yaw_deg
    return inner


def _person_bearing_deg(scene) -> float | None:
    """Pick a person bearing from the scene snapshot. Prefers head_detections
    (which are world-relative bearings); falls back to user_pose midpoint
    converted from normalized x to a coarse degrees estimate (assumes ~60° HFoV).
    """
    for det in scene.head_detections or []:
        if det.class_name == "person" and det.bearing_deg is not None:
            return float(det.bearing_deg)
    pose = getattr(scene, "user_pose", None)
    if pose is not None:
        try:
            xs = pose.landmarks_xy[:, 0]
            mid_x = float(xs.mean())   # 0..1
        except Exception:
            return None
        # Coarse: assume horizontal FoV ~60°; map mid_x to ±30°.
        # Sign convention: image right = +x in MediaPipe, but bearing_deg
        # is left-negative/right-positive, so positive bearing means turn
        # right. In `turn(yaw_deg)`, positive yaw means counter-clockwise
        # (left), so we negate.
        return -((mid_x - 0.5) * 60.0)
    return None


# ---- approach -------------------------------------------------------------

async def approach(skill_server, args: Dict[str, Any]) -> Dict[str, Any]:
    """Multi-step walk loop until the nearest person is within
    ``target_distance_m`` (or the path becomes blocked, or we hit the cap).
    """
    target_d = float(args.get("target_distance_m", 1.0))
    steps_taken = 0
    last_nearest: float | None = None
    abort_reason: str | None = None

    for i in range(_APPROACH_MAX_STEPS):
        scene = skill_server.scene.snapshot()
        ground = getattr(scene, "ground", None)
        if ground is not None and not ground.clear_path:
            abort_reason = "path blocked"
            break
        nearest = ground.nearest_person_m if ground is not None else math.inf
        last_nearest = nearest if math.isfinite(nearest) else None
        if math.isfinite(nearest) and nearest <= target_d + _APPROACH_DIST_TOLERANCE_M:
            break

        step_result = await skill_server.execute(
            "walk",
            {"vx": _APPROACH_VX, "vy": 0.0, "wz": 0.0, "duration_s": _APPROACH_STEP_S},
        )
        steps_taken += 1
        if not step_result.get("ok", False):
            abort_reason = step_result.get("reason", "walk step rejected")
            break

    return {
        "ok": abort_reason is None,
        "skill": "approach",
        "steps_taken": steps_taken,
        "target_distance_m": target_d,
        "nearest_person_m_after": last_nearest,
        **({"reason": abort_reason} if abort_reason else {}),
    }


# ---- mock_imitate ---------------------------------------------------------

async def mock_imitate(skill_server, args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate against MIRRORABLE_GESTURES then delegate to `gesture`."""
    gesture_name = args.get("gesture")
    if gesture_name not in MIRRORABLE_GESTURES:
        return {
            "ok": False, "skill": "mock_imitate",
            "reason": f"gesture {gesture_name!r} is not mirrorable; "
                      f"allowed: {sorted(MIRRORABLE_GESTURES)}",
        }
    inner = await skill_server.execute("gesture", {"name": gesture_name})
    inner.setdefault("skill", "mock_imitate")
    inner["mirrored_gesture"] = gesture_name
    return inner


# ---- ask_human ------------------------------------------------------------

async def ask_human(skill_server, args: Dict[str, Any]) -> Dict[str, Any]:
    """Speak the question, then sleep ~5s so the user has space to reply
    through the normal Realtime audio channel.

    In v1 this is essentially "say + wait"; the actual user reply arrives
    asynchronously through the Realtime websocket and is dispatched to
    a fresh tool call by the brain, so we don't try to capture it here.
    """
    question = args.get("question") or ""
    if not question.strip():
        return {"ok": False, "skill": "ask_human", "reason": "empty question"}

    say_result = await skill_server.execute("say", {"text": question})
    if not say_result.get("ok", False):
        return {
            "ok": False, "skill": "ask_human",
            "reason": say_result.get("reason", "say failed"),
        }
    await asyncio.sleep(_ASK_HUMAN_LISTEN_S)
    return {
        "ok": True, "skill": "ask_human",
        "question": question, "listened_s": _ASK_HUMAN_LISTEN_S,
    }


__all__ = [
    "look_at",
    "approach",
    "mock_imitate",
    "ask_human",
    "MIRRORABLE_GESTURES",
]
