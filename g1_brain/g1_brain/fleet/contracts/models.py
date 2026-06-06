"""Typed fleet contracts (pydantic v2). Authoritative source for JSON Schema.

NOTE: `RobotStateMsg` here is the *fleet north-bound state message*. It is a
different type from `g1_brain.scene_state.types.RobotState` (the body-posture
dataclass); the agent builder maps the latter into the former.
"""
from __future__ import annotations

import enum
import hashlib
import json
import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _new_event_id() -> str:
    # Random unique id (uuid4 hex); not time-ordered.
    return uuid.uuid4().hex


class EventType(str, enum.Enum):
    FSM_TRANSITION = "fsm_transition"
    SAFETY_EVENT = "safety_event"
    ACTION_RESULT = "action_result"
    SCENE_SNAPSHOT = "scene_snapshot"
    HUMAN_DETECTED = "perception.human_detected"
    OBSTACLE_DETECTED = "perception.obstacle_detected"


# ---------- CapabilityDescriptor ----------

class Embodiment(BaseModel):
    type: Literal["humanoid_g1"] = "humanoid_g1"


class CapabilityEntry(BaseModel):
    name: str
    risk_level: Literal["none", "low", "medium", "high"] = "low"
    params_schema: Optional[str] = None


class CapabilitySafety(BaseModel):
    e_stop: bool = True
    local_obstacle_avoidance: bool = True
    watchdogs: List[str] = Field(default_factory=lambda: ["lowstate", "head_frame", "pose"])


class BrainInfo(BaseModel):
    attachable: bool = True
    attached: bool = False


class CapabilityDescriptor(BaseModel):
    schema_version: Literal["CapabilityDescriptor.v1"] = "CapabilityDescriptor.v1"
    robot_id: str
    embodiment: Embodiment = Field(default_factory=Embodiment)
    harness_version: str = "0.0.0"
    trust_level: Literal["sim", "dev", "production_certified"] = "sim"
    frame_id: str
    capabilities: List[CapabilityEntry] = Field(default_factory=list)
    safety: CapabilitySafety = Field(default_factory=CapabilitySafety)
    brain: BrainInfo = Field(default_factory=BrainInfo)


# ---------- RobotStateMsg ----------

class Pose(BaseModel):
    frame_id: str
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0


class WatchdogOk(BaseModel):
    lowstate: bool = True
    head_frame: bool = True
    pose: bool = True


class SafetyStateMsg(BaseModel):
    e_stop: bool = False
    geofence_ok: bool = True
    gravity_proj_z: float = -1.0
    watchdog_ok: WatchdogOk = Field(default_factory=WatchdogOk)


class CoreState(BaseModel):
    pose: Optional[Pose] = None
    safety_state: SafetyStateMsg = Field(default_factory=SafetyStateMsg)
    policy_active: bool = False
    battery: Optional[float] = None


class RobotStateMsg(BaseModel):
    schema_version: Literal["RobotStateMsg.v1"] = "RobotStateMsg.v1"
    robot_id: str
    ts: str
    seq: int = 0
    fsm_state: str = "BOOT"
    motion_state: Literal["idle", "moving"] = "idle"
    core: CoreState = Field(default_factory=CoreState)
    extensions: Dict[str, Any] = Field(default_factory=dict)


# ---------- RobotEvent ----------

class RobotEvent(BaseModel):
    schema_version: Literal["RobotEvent.v1"] = "RobotEvent.v1"
    event_id: str
    trace_id: Optional[str] = None
    robot_id: str
    type: EventType
    ts: str
    # Set by producer via make(). Stored for traceability/integrity; receiver-side
    # verification is deferred to a later slice (not performed in the read-only slice).
    payload_hash: str
    payload: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def make(cls, *, robot_id: str, type: EventType, ts: str,
             payload: Dict[str, Any], trace_id: Optional[str] = None) -> "RobotEvent":
        # default=str keeps hashing robust even if a stray non-JSON value slips
        # into payload; producers are still expected to pass JSON-safe dicts.
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        digest = "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return cls(event_id=_new_event_id(), trace_id=trace_id, robot_id=robot_id,
                   type=type, ts=ts, payload_hash=digest, payload=payload)


# ---------- Reserved (schema only; no execution path this slice) ----------

class CommandEnvelope(BaseModel):
    schema_version: Literal["CommandEnvelope.v1"] = "CommandEnvelope.v1"
    status: Literal["reserved"] = "reserved"


class TaskSpec(BaseModel):
    schema_version: Literal["TaskSpec.v1"] = "TaskSpec.v1"
    status: Literal["reserved"] = "reserved"


class AdmissionDecision(BaseModel):
    schema_version: Literal["AdmissionDecision.v1"] = "AdmissionDecision.v1"
    status: Literal["reserved"] = "reserved"
