"""Shared dataclasses and constants for the memory subsystem.

These types are stable contracts between the workers, storage, and the
SkillServer / agent_main facade. Keep this module dependency-free so it
can be imported by any sibling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# JSONL meta subtypes added by this subsystem. Existing logger already
# uses session_start / turn_start / state_transition / plan_done / error /
# shutdown / wake_event / barge_in / plan_watchdog_timeout / no_speech_idle /
# response_canceled. We extend with three more for memory-relevant events.
META_SUBTYPE_SCENE_SNAPSHOT = "scene_snapshot"
META_SUBTYPE_ACTION_RESULT = "action_result"
META_SUBTYPE_SAFETY_EVENT = "safety_event"

# scene_snapshot.trigger values
SNAPSHOT_TRIGGER_TURN_START = "turn_start"
SNAPSHOT_TRIGGER_PRE_MOTION = "pre_motion"
SNAPSHOT_TRIGGER_POST_MOTION = "post_motion"
SNAPSHOT_TRIGGERS = frozenset({
    SNAPSHOT_TRIGGER_TURN_START,
    SNAPSHOT_TRIGGER_PRE_MOTION,
    SNAPSHOT_TRIGGER_POST_MOTION,
})

# action_result.status values
ACTION_STATUS_OK = "ok"
ACTION_STATUS_BLOCKED_BY_SAFETY = "blocked_by_safety"
ACTION_STATUS_EXEC_ERROR = "exec_error"
ACTION_STATUS_CANCELED = "canceled"
ACTION_STATUSES = frozenset({
    ACTION_STATUS_OK,
    ACTION_STATUS_BLOCKED_BY_SAFETY,
    ACTION_STATUS_EXEC_ERROR,
    ACTION_STATUS_CANCELED,
})

# safety_event.kind values
SAFETY_KIND_TOOL_REJECTED = "tool_rejected"
SAFETY_KIND_FSM_TRANSITION = "fsm_transition"
SAFETY_KIND_VISION_GATE_RISK = "vision_gate_risk"
SAFETY_KIND_ESTOP = "estop"
SAFETY_KINDS = frozenset({
    SAFETY_KIND_TOOL_REJECTED,
    SAFETY_KIND_FSM_TRANSITION,
    SAFETY_KIND_VISION_GATE_RISK,
    SAFETY_KIND_ESTOP,
})

# Job kinds in the jobs table
JOB_KIND_PHASE1 = "phase1"
JOB_KIND_PHASE2 = "phase2"
JOB_KIND_PHASE2_GLOBAL_LOCK = "phase2_global_lock"
PHASE2_GLOBAL_LOCK_KEY = "global"

# Job statuses
JOB_STATUS_PENDING = "pending"
JOB_STATUS_LEASED = "leased"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"


@dataclass
class Stage1Output:
    """Phase1 model output, persisted to stage1_outputs table."""

    raw_memory: str
    rollout_summary: str
    rollout_slug: Optional[str] = None


@dataclass
class AskResult:
    """Return value of CodexDaemon.ask_slow_brain."""

    status: str
    """One of: ok | timeout | canceled | daemon_dead | queue_full
              | quota_exhausted | protocol_error"""
    text: str = ""
    latency_ms: int = 0
    partial: bool = False
    """True if `text` is incomplete due to timeout/cancel/crash."""


# Recall tool result statuses
RECALL_STATUS_OK = "ok"
RECALL_STATUS_MEMORY_DISABLED = "memory_disabled"
RECALL_STATUS_PATH_OUTSIDE_SANDBOX = "path_outside_sandbox"
RECALL_STATUS_FILE_TOO_LARGE = "file_too_large"
RECALL_STATUS_FILE_NOT_FOUND = "file_not_found"
RECALL_STATUS_TOOL_UNAVAILABLE = "tool_unavailable"


class PathSandboxError(Exception):
    """Raised when a path resolves outside any allowed root."""


@dataclass
class MemoryConfig:
    """Effective memory subsystem config (subset of g1_brain.yaml memory:)."""

    enabled: bool = True
    root_dir: str = "~/.unitree/g1_brain"

    phase1_model: str = ""           # "" = subscription default
    phase2_model: str = ""
    phase1_debounce_s: float = 30.0
    phase1_max_jsonl_bytes: int = 80_000
    phase2_max_raw_memories: int = 256
    phase2_max_unused_days: int = 30

    # Resource-contention controls. Phase1/Phase2 run codex (reasoning=high)
    # which, even though the model runs out-of-process, drives enough local
    # GIL/CPU work (JSONL projection, git, file I/O, the codex client read
    # loop) to starve the audio/VAD event loop mid-conversation. When
    # defer_when_conversation_active is on, the workers will not CLAIM new jobs
    # while a turn is in progress (state != IDLE) — an in-flight job still
    # finishes, but nothing new starts until the operator is idle again.
    defer_when_conversation_active: bool = True
    # Historical backfill only enqueues Phase1 jobs, but we still keep it off
    # the synchronous start() path and let startup settle first so it can't
    # pile onto the perception-model-load stall at boot.
    backfill_delay_s: float = 20.0

    slow_brain_model: str = ""
    ask_default_timeout_s: float = 20.0
    ask_queue_max: int = 2
    daemon_ping_interval_s: float = 30.0
    daemon_restart_max_attempts: int = 5

    # Applied to every codex invocation (daemon mcp-server + exec). The user
    # asked for "high + 1.5x speed" by default. service_tier="fast" maps to
    # OpenAI's "Fast" priority tier ("1.5x speed, increased usage" per
    # codex-rs models.json). NB: in TOML config it must be the lowercase
    # serde variant name ("fast" or "flex"), NOT the API request_value
    # ("priority") — codex's TOML deserializer rejects "priority" with
    # "unknown variant". Set to "" / "auto" to fall back to account default.
    # reasoning_summary="concise" keeps progress notifications small so
    # daemon's StreamReader doesn't choke on a single 64 KB+ JSONL line.
    codex_reasoning_effort: str = "high"
    codex_reasoning_summary: str = "concise"
    codex_service_tier: str = "fast"
    # StreamReader buffer for codex stdout. Some notifications carry full
    # tool-call payloads on a single JSONL line; 64KB (asyncio default) is
    # too small and was causing LimitOverrunError → daemon crash.
    daemon_stdout_buffer_bytes: int = 16 * 1024 * 1024

    passive_summary_max_tokens: int = 2500
    passive_agents_md_max_tokens: int = 1500
    recall_grep_default_max_lines: int = 50
    recall_read_max_bytes: int = 4096

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "MemoryConfig":
        d = dict(d or {})
        # Filter to known fields to allow forward-compat extra keys
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)
