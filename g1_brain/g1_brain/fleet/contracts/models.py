"""Typed fleet contracts (pydantic v2). Authoritative source for JSON Schema.

NOTE: `RobotStateMsg` here is the *fleet north-bound state message*. It is a
different type from `g1_brain.scene_state.types.RobotState` (the body-posture
dataclass); the agent builder maps the latter into the former.
"""
from __future__ import annotations

import enum
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _new_event_id() -> str:
    # Random unique id (uuid4 hex); not time-ordered.
    return uuid.uuid4().hex


def _iso_from_epoch(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class EventType(str, enum.Enum):
    FSM_TRANSITION = "fsm_transition"
    SAFETY_EVENT = "safety_event"
    ACTION_RESULT = "action_result"
    SCENE_SNAPSHOT = "scene_snapshot"
    HUMAN_DETECTED = "perception.human_detected"
    OBSTACLE_DETECTED = "perception.obstacle_detected"
    # ---- dispatch lifecycle (closed-loop slice) ----
    ANOMALY_DETECTED = "anomaly_detected"
    COMMAND_ISSUED = "command_issued"
    COMMAND_ACCEPTED = "command_accepted"
    COMMAND_REFUSED = "command_refused"
    TASK_ASSIGNED = "task_assigned"
    TASK_REASSIGNED = "task_reassigned"
    ROBOT_SLEEPING = "robot_sleeping"
    ROBOT_RESUMED = "robot_resumed"
    LEASE_EXPIRED = "lease_expired"


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


class Battery(BaseModel):
    soc: float = 1.0  # state of charge, 0..1
    temperature_c: float = 25.0
    charging: bool = False


class Health(BaseModel):
    level: Literal["ok", "warning", "fault"] = "ok"
    faults: List[str] = Field(default_factory=list)


class CoreState(BaseModel):
    pose: Optional[Pose] = None
    safety_state: SafetyStateMsg = Field(default_factory=SafetyStateMsg)
    policy_active: bool = False
    battery: Optional[Battery] = None
    health: Health = Field(default_factory=Health)


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


# ---------- Command path (down-bound; closed-loop slice) ----------

# Capabilities the coordinator may request. The robot's CapabilityDescriptor
# still gates which it actually supports; this just bounds the wire vocabulary.
# "inject" is a sim/debug telemetry override (battery temp etc.), handled at the
# harness before the admission gate — it never touches motion.
Capability = Literal["sleep", "wake", "patrol", "idle", "resume_task", "stop", "inject"]


class Lease(BaseModel):
    lease_id: str
    heartbeat_interval_s: float = 2.0
    ttl_s: float = 30.0
    on_expire: Literal["safe_pause", "sleep"] = "safe_pause"


class SafetyEnvelope(BaseModel):
    max_speed_mps: float = 0.3
    allowed_capabilities: List[str] = Field(default_factory=list)
    human_approval_id: Optional[str] = None


class CommandEnvelope(BaseModel):
    schema_version: Literal["CommandEnvelope.v1"] = "CommandEnvelope.v1"
    command_id: str
    trace_id: Optional[str] = None
    issued_by: str
    issued_to: str  # robot_id
    issued_at: str  # ISO 8601
    issued_at_epoch: float
    expires_at: float  # epoch seconds; admission gate rejects when now > expires_at
    idempotency_key: str
    capability: Capability
    payload: Dict[str, Any] = Field(default_factory=dict)
    payload_hash: str
    safety_envelope: SafetyEnvelope = Field(default_factory=SafetyEnvelope)
    lease: Optional[Lease] = None

    @classmethod
    def make(cls, *, issued_by: str, issued_to: str, capability: str,
             payload: Dict[str, Any], ttl_s: float = 30.0,
             trace_id: Optional[str] = None, idempotency_key: Optional[str] = None,
             safety_envelope: Optional["SafetyEnvelope"] = None,
             lease: Optional["Lease"] = None,
             now: Optional[float] = None) -> "CommandEnvelope":
        now_epoch = float(now if now is not None else time.time())
        cid = uuid.uuid4().hex
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        digest = "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return cls(
            command_id=cid, trace_id=trace_id, issued_by=issued_by,
            issued_to=issued_to, issued_at=_iso_from_epoch(now_epoch),
            issued_at_epoch=now_epoch, expires_at=now_epoch + float(ttl_s),
            idempotency_key=idempotency_key or cid, capability=capability,
            payload=payload, payload_hash=digest,
            safety_envelope=safety_envelope or SafetyEnvelope(), lease=lease,
        )


class AdmissionDecision(BaseModel):
    schema_version: Literal["AdmissionDecision.v1"] = "AdmissionDecision.v1"
    command_id: str
    robot_id: str
    decision: Literal["accepted", "refused", "deferred"]
    reason_code: str
    reason_detail: str = ""
    ts: str


# ---------- Task / mission / replan ----------

class TaskSpec(BaseModel):
    schema_version: Literal["TaskSpec.v1"] = "TaskSpec.v1"
    task_id: str
    mission_id: Optional[str] = None
    type: Literal["patrol", "idle", "charge"] = "patrol"
    required_capabilities: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    success_criteria: List[str] = Field(default_factory=list)
    cancel_policy: Dict[str, Any] = Field(default_factory=dict)


class Mission(BaseModel):
    schema_version: Literal["Mission.v1"] = "Mission.v1"
    mission_id: str
    created_by: str
    intent_text: str = ""
    priority: Literal["low", "normal", "high"] = "normal"
    tasks: List[TaskSpec] = Field(default_factory=list)


class ReplanProposal(BaseModel):
    schema_version: Literal["ReplanProposal.v1"] = "ReplanProposal.v1"
    trigger: str
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_human_approval: bool = False
    explanation: Optional[str] = None
