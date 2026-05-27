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


START_PHONE_CALL_SCHEMA = {
    "type": "function",
    "name": "start_phone_call",
    "description": (
        "Place an outbound phone call so the operator can talk to Sparky "
        "from anywhere. Returns when the call is dialled (not when answered). "
        "IMPORTANT: when the operator asks you to call THEM ('call me', 'call "
        "my number', 'call my phone', '给我打电话', '打我的号码'), call this "
        "tool with NO arguments — that dials the pre-configured operator "
        "number and is immune to mishearing digits. Do NOT transcribe a "
        "spoken phone number into `to`; only pass `to` for a different, "
        "explicitly dictated destination, and expect it to be rejected unless "
        "it is on the saved allow-list."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "E.164 number (e.g. +14155550199). OMIT THIS to dial the configured operator number — the correct choice whenever the operator asks to be called.",
            }
        },
    },
}


# ---------- Public builder --------------------------------------------------

def build_tool_schemas(
    *, sim: bool = True, vision_only: bool = False,
    mock_imitate_enabled: bool = True, phone_enabled: bool = False,
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
    phone_enabled : bool
        When True, appends ``START_PHONE_CALL_SCHEMA`` so the LLM can
        initiate outbound calls via the Twilio bridge. Defaults to False so
        existing callers see no change.
    """
    # L1 first (the LLM should prefer these), then L2 primitives.
    l1 = [
        _say(), _describe_scene(), _query_scene_state(), _recall_history(),
        _look_at(), _approach(), _mock_imitate(), _ask_human(),
    ]
    memory_tools = [
        _recall_grep(), _recall_read(), _recall_glob(), _ask_slow_brain(),
    ]
    l2 = [
        _walk(), _turn(), _gesture(), _static_pose(),
        _stop(), _release_arms(),
    ]
    real_only = [_loco_high(), _arm_action_high(), _audio_tts_robot()]

    schemas = l1 + memory_tools + l2
    if not sim:
        schemas = schemas + real_only

    if not mock_imitate_enabled:
        schemas = [s for s in schemas if s["name"] != "mock_imitate"]

    if vision_only:
        keep = {"say", "describe_scene", "query_scene_state", "recall_history",
                "recall_grep", "recall_read", "recall_glob", "ask_slow_brain"}
        schemas = [s for s in schemas if s["name"] in keep]

    if phone_enabled:
        schemas.append(START_PHONE_CALL_SCHEMA)

    return schemas


def _recall_grep() -> dict:
    return {
        "type": "function",
        "name": "recall_grep",
        "description": (
            "Search the robot's long-term memory files with ripgrep. "
            "Returns matching lines with file path and line number, capped "
            "at max_lines. Use this FIRST when you suspect prior-session "
            "knowledge is relevant. Start with scope='registry' (MEMORY.md "
            "+ raw_memories.md + AGENTS.md); escalate to 'rollouts' for "
            "narrative detail; only fall back to 'jsonl' when you need "
            "exact tool args or transcript text. Stop within 4-6 searches."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "ripgrep regex. Word boundaries (\\b) only work for "
                        "ASCII — for Chinese terms use the bare literal "
                        "(e.g. '圆柱体|长方体', NOT '\\b(圆柱体|长方体)\\b' "
                        "— that never matches because CJK chars aren't "
                        "word chars in rg's default engine). For short "
                        "English terms, \\b is fine (e.g. '\\bcup\\b'). "
                        "If unsure, drop \\b and rely on the keyword being "
                        "specific enough."
                    ),
                },
                "scope": {
                    "type": "string",
                    "enum": ["registry", "rollouts", "jsonl", "all"],
                    "description": "registry=MEMORY.md + raw_memories.md + "
                                   "AGENTS.md; rollouts=rollout_summaries/*.md; "
                                   "jsonl=raw transcripts (slow, use last); "
                                   "all=combination of registry+rollouts.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional: restrict jsonl scope to one "
                                   "session's transcript file (first 8 hex chars).",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Cap on returned matches (default 50, max 100).",
                },
            },
            "required": ["pattern"],
        },
    }


def _recall_read() -> dict:
    return {
        "type": "function",
        "name": "recall_read",
        "description": (
            "Read a memory file. Use after recall_grep finds a relevant entry "
            "and you want full context. The path is a BARE filename relative "
            "to one of two sandbox roots (memories/ or logs/conversations/) — "
            "do NOT include 'logs/conversations/' or 'memories/' as a prefix; "
            "they are the roots, not directories inside the path. Returns up "
            "to 4 KB; for larger files specify start_line / end_line."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Bare filename relative to a sandbox root. Examples: "
                        "'MEMORY.md', 'raw_memories.md', "
                        "'rollout_summaries/abc-walk.md', "
                        "'2026-05-22T03-04-43Z-6da3f1a0.jsonl' (NOT "
                        "'logs/conversations/2026-05-22T...jsonl'). Use "
                        "exactly the filename recall_grep returned."
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "description": "1-indexed start line (default 1).",
                },
                "end_line": {
                    "type": "integer",
                    "description": "1-indexed end line (inclusive). Omit to "
                                   "read until budget exhausted.",
                },
            },
            "required": ["path"],
        },
    }


def _recall_glob() -> dict:
    return {
        "type": "function",
        "name": "recall_glob",
        "description": (
            "List memory files matching a glob pattern. Use to discover what "
            "rollout_summaries exist or find files by name. Patterns are "
            "evaluated under the allowed memory roots; absolute paths and "
            "'..' escapes are rejected."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "e.g. 'rollout_summaries/*walk*.md' or "
                                   "'rollout_summaries/2026-05*.md'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 50, max 200).",
                },
            },
            "required": ["pattern"],
        },
    }


def _ask_slow_brain() -> dict:
    return {
        "type": "function",
        "name": "ask_slow_brain",
        "description": (
            "Consult the slow deliberative brain (Codex, xhigh reasoning) for "
            "queries that need multi-step reasoning, planning, or deep recall "
            "over many past sessions. SLOW: 10-60 seconds on a warm daemon, up "
            "to 90s for deep cross-session searches. Use SPARINGLY. Good cases: "
            "(1) user asks for a multi-step plan; (2) recall_grep returned "
            "nothing useful and you suspect rare historical knowledge "
            "buried in jsonl transcripts; (3) deep think about a non-obvious "
            "safety implication. NEVER use for any reflex or motion "
            "decision — those stay on the fast path."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Full question for the slow brain. Be "
                                   "specific and self-contained; the slow "
                                   "brain doesn't see live conversation.",
                },
                "timeout_s": {
                    "type": "number",
                    "description": "Wait budget in seconds (3-90, default 90). "
                                   "Keep near 90 when asking the slow brain "
                                   "to grep many old sessions; lower for "
                                   "quick plan-style queries.",
                },
            },
            "required": ["query"],
        },
    }


__all__ = [
    "GESTURE_NAMES",
    "STATIC_POSE_NAMES",
    "LOOK_AT_TARGETS",
    "MIRRORABLE_GESTURES",
    "build_tool_schemas",
]
