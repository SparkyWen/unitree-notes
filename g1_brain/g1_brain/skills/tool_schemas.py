"""OpenAI Realtime function-call schemas for the g1_brain skill catalog.

This is the single source of truth for what the LLM is allowed to call.
The Brain layer (`g1_brain/brain/realtime_agent.py`) attaches these schemas
to the Realtime session; the SkillServer (`skill_server.py`) implements the
matching ``_skill_<name>`` methods.

Invariants:
- Naming and enums here MUST match the SkillServer dispatch keys verbatim.
- Numeric bounds here are the *advertised* limits to the model; the
  SafetySupervisor still clamps a second time before motion executes.
- Real-robot-only tools (loco_high / arm_action_high / audio_tts_robot)
  appear in schema for documentation but the sim backend rejects them.

Mirrors the style of `va_demo.realtime_agent._build_tool_schemas`.
"""
from __future__ import annotations

from typing import Any, Dict, List


# ---------- Enum constants exposed to the LLM ------------------------------

# 8 RL-safe gestures from g1_sim_rl_combo.build_arm_actions() + the 2 extras
# (salute, hug) injected by keyframe_extras.
GESTURE_NAMES: List[str] = [
    "wave_right", "wave_left", "hands_up", "t_pose",
    "salute", "clap", "guard", "punch_combo", "hug",
]
# Note: "salute" comes from build_arm_actions (key "5"); "hug" is added by
# keyframe_extras. Both are exposed as gestures so the LLM only needs to
# remember one verb. STATIC_POSE_NAMES below intentionally exposes only the
# subset that is *not* already a gesture.

# `static_pose` is a hold-then-release motion; only the 2 keyframe-extras
# poses are exposed. The other 7 overlap with `gesture` (which has nicer
# return-to-rest behavior already wired).
STATIC_POSE_NAMES: List[str] = ["salute", "hug"]

LOOK_AT_TARGETS: List[str] = ["person", "ahead", "left", "right", "ground"]

# Subset of gestures that mock_imitate is allowed to mirror back. Matches
# scene_state.types.GestureLabel.MIRRORABLE so perception and skills agree.
MIRRORABLE_GESTURES: List[str] = ["wave_right", "wave_left", "hands_up", "t_pose"]


# ---------- Tool schema builders -------------------------------------------

def _say() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "say",
        "description": (
            "Speak a short message to the user via OpenAI TTS. Prefer this for "
            "canned/short replies; the Realtime audio reply is usually better "
            "for conversational content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": 200},
            },
            "required": ["text"],
        },
    }


def _describe_scene() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "describe_scene",
        "description": (
            "Take one snapshot from the head camera (robot's first-person view) "
            "and ask the vision model to describe what it sees. Use this whenever "
            "the user asks a visual question."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Optional specific question to answer about the scene.",
                },
                "detail": {"type": "string", "enum": ["low", "medium", "high"]},
            },
        },
    }


def _query_scene_state() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "query_scene_state",
        "description": (
            "Return a compact summary of the latest fused perception state "
            "(persons visible, nearest obstacle, clear_path, last user gesture, "
            "warnings). Cheap; call before every motion you're unsure about."
        ),
        "parameters": {"type": "object", "properties": {}},
    }


def _recall_history() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "recall_history",
        "description": (
            "Read the persistent per-session jsonl transcript and return the "
            "OLDEST-first list of past events. Use this whenever the user "
            "asks 'what did I do', 'what was my first command', 'what motion "
            "did you run earlier' — your in-context memory may have lost or "
            "reordered older turns, but the jsonl always has the truth. "
            "kind='actions' returns every motion/skill the robot executed, "
            "kind='user_turns' returns every user utterance, kind='all' "
            "interleaves user/assistant/tool_use entries."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["actions", "user_turns", "all"],
                    "description": "Which event class to return.",
                },
                "limit": {
                    "type": "integer", "minimum": 1, "maximum": 200,
                    "description": "Cap on returned events; default 20.",
                },
            },
        },
    }


def _look_at() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "look_at",
        "description": (
            "Turn the body in place to face a target. Bounded to ±25° per call; "
            "for larger turns chain multiple calls."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": LOOK_AT_TARGETS},
            },
            "required": ["target"],
        },
    }


def _approach() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "approach",
        "description": (
            "Walk forward in slow steps until the nearest person is within "
            "`target_distance_m`. Aborts if the path becomes blocked. Capped "
            "at ~6 short steps; call again to continue."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_distance_m": {
                    "type": "number", "minimum": 0.5, "maximum": 3.0,
                    "description": "Stop when nearest person is closer than this.",
                },
            },
            "required": ["target_distance_m"],
        },
    }


def _mock_imitate() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "mock_imitate",
        "description": (
            "Mirror back a gesture you saw the user perform. Only the gestures "
            "in the enum are mirrorable; for others, say something instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "gesture": {"type": "string", "enum": MIRRORABLE_GESTURES},
            },
            "required": ["gesture"],
        },
    }


def _ask_human() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "ask_human",
        "description": (
            "Speak a question and wait briefly (~5s) for the user's verbal "
            "answer through the normal Realtime channel. Use when you need a "
            "decision (yes/no/direction)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "maxLength": 200},
            },
            "required": ["question"],
        },
    }


def _walk() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "walk",
        "description": (
            "Walk at velocity (vx, vy, wz) for `duration_s` seconds. The skill "
            "polls perception every 0.2 s and aborts early if the path becomes "
            "blocked or an obstacle gets within 0.5 m. Use ONE long call for "
            "multi-meter requests (e.g. for '10 meters forward' set "
            "vx=0.2 and duration_s=50) — never chain many short walks; in "
            "confirm-mode each call costs one operator y/N. Max single call: "
            "60 s (12 m at 0.2 m/s)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "vx": {"type": "number", "minimum": -0.3, "maximum": 0.3,
                       "description": "forward velocity m/s"},
                "vy": {"type": "number", "minimum": -0.1, "maximum": 0.1,
                       "description": "lateral velocity m/s"},
                "wz": {"type": "number", "minimum": -0.4, "maximum": 0.4,
                       "description": "yaw rate rad/s"},
                "duration_s": {"type": "number", "minimum": 0.2, "maximum": 60.0},
            },
            "required": ["duration_s"],
        },
    }


def _turn() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "turn",
        "description": (
            "Rotate in place by `yaw_deg`. Positive = counter-clockwise (left); "
            "negative = clockwise (right). Use ONE call for the full requested "
            "angle (up to ±180°). The skill turns at ~14°/s and aborts early if "
            "the path becomes unsafe. Operator confirmation in confirm-mode is "
            "per-call, so chaining many small turns for one verbal command "
            "(e.g. 7 × turn(-25) for 'turn 180') produces 7 y/N prompts and is "
            "forbidden — emit a single turn(-180) instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "yaw_deg": {"type": "number", "minimum": -180.0, "maximum": 180.0},
            },
            "required": ["yaw_deg"],
        },
    }


def _gesture() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "gesture",
        "description": (
            "Play one prevalidated arm gesture. The robot keeps walking "
            "unaffected; the RL controller plays the gesture asynchronously "
            "and hands arms back to itself when done."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": GESTURE_NAMES},
            },
            "required": ["name"],
        },
    }


def _static_pose() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "static_pose",
        "description": (
            "Hold a static keyframe pose for a moment then release. Currently "
            "limited to {salute, hug}; everything else is exposed via `gesture`."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": STATIC_POSE_NAMES},
            },
            "required": ["name"],
        },
    }


def _stop() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "stop",
        "description": "Immediately stop walking and release any active arm gesture.",
        "parameters": {"type": "object", "properties": {}},
    }


def _release_arms() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "release_arms",
        "description": "Hand the arms back to the locomotion policy (no walking change).",
        "parameters": {"type": "object", "properties": {}},
    }


# ---- real-robot-only tools (rejected in sim mode) ----

def _loco_high() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "loco_high",
        "description": (
            "Real-robot only: invoke a built-in LocoClient action "
            "(WaveHand / ShakeHand / Squat / StandUp). Rejected in sim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["wave_hand", "shake_hand", "squat", "stand_up"],
                },
            },
            "required": ["action"],
        },
    }


def _arm_action_high() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "arm_action_high",
        "description": (
            "Real-robot only: trigger a G1ArmActionClient preset action. "
            "Rejected in sim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action_id": {"type": "integer", "minimum": 0, "maximum": 99},
            },
            "required": ["action_id"],
        },
    }


def _audio_tts_robot() -> Dict[str, Any]:
    return {
        "type": "function",
        "name": "audio_tts_robot",
        "description": (
            "Real-robot only: speak via the on-board AudioClient.TtsMaker "
            "(robot's local speakers instead of host TTS). Rejected in sim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": 200},
            },
            "required": ["text"],
        },
    }


# ---------- Public builder --------------------------------------------------

def build_tool_schemas(
    *, sim: bool = True, vision_only: bool = False,
    mock_imitate_enabled: bool = True,
) -> List[Dict[str, Any]]:
    """Return the OpenAI Realtime function schemas for the g1_brain catalog.

    Parameters
    ----------
    sim : bool
        If True (default), the 3 real-robot-only tools are omitted. Set False
        when wiring up the real-robot adapters.
    vision_only : bool
        Smoke-test mode for the brain layer with no motion. Returns only
        ``say``, ``describe_scene``, ``query_scene_state``.
    mock_imitate_enabled : bool
        Whether to expose the ``mock_imitate`` tool to the LLM. When False
        (set by ``mock_imitation.enabled: false`` in the YAML config), the
        tool is dropped from the schema so the LLM cannot call it
        spontaneously when it sees the user wave on camera. Other gesture
        skills (``gesture``, ``static_pose``) remain available for explicit
        voice commands like "wave at me".
    """
    # L1 first (the LLM should prefer these), then L2 primitives.
    l1 = [
        _say(), _describe_scene(), _query_scene_state(), _recall_history(),
        _look_at(), _approach(), _mock_imitate(), _ask_human(),
    ]
    l2 = [
        _walk(), _turn(), _gesture(), _static_pose(),
        _stop(), _release_arms(),
    ]
    real_only = [_loco_high(), _arm_action_high(), _audio_tts_robot()]

    schemas = l1 + l2
    if not sim:
        schemas = schemas + real_only

    if not mock_imitate_enabled:
        schemas = [s for s in schemas if s["name"] != "mock_imitate"]

    if vision_only:
        keep = {"say", "describe_scene", "query_scene_state", "recall_history"}
        schemas = [s for s in schemas if s["name"] in keep]

    return schemas


__all__ = [
    "GESTURE_NAMES",
    "STATIC_POSE_NAMES",
    "LOOK_AT_TARGETS",
    "MIRRORABLE_GESTURES",
    "build_tool_schemas",
]
