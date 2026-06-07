# Fleet 底座 + 统一感知 (Read-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only fleet command center over N headless `g1_brain` harness cores: typed contracts, a HarnessCore facade (incremental wrap), a WebSocket FleetBus, and a coordinator that aggregates state + semantic perception and serves a read-only API with an append-only event log + replay.

**Architecture:** Each G1 keeps its own DDS domain (robot-internal) and local safety. A new north-bound `FleetBus` (aiohttp WebSocket, separate from DDS) carries `CapabilityDescriptor` registration, `RobotStateMsg` heartbeats, and semantic `RobotEvent`s up to a coordinator. The coordinator never has any path back to a motor in this slice. New code lives under the existing `g1_brain` package as `g1_brain/fleet/`; tests under `g1_brain/tests/fleet/`.

**Tech Stack:** Python ≥3.10, pydantic v2, aiohttp (server + ws client), sqlite3 (WAL), pytest + pytest-asyncio (`asyncio_mode=auto`). All already in `g1_brain/pyproject.toml`.

---

## Conventions (read once)

- **Run all commands from** `/home/helios/unitree/unitree-notes/g1_brain` (the package root with `pyproject.toml`).
- **Run tests with:** `python -m pytest <path> -v`. `conftest.py` already puts the repo root on `sys.path`; no install needed.
- **Name clash warning:** `g1_brain/scene_state/types.py` already defines a dataclass `RobotState` (body-posture, lowstate-derived). The fleet **state message** is a *different* type named **`RobotStateMsg`**. Never confuse them; the fleet contract pulls *from* the scene `RobotState` but is its own pydantic model.
- **Source of truth for capabilities:** `g1_brain/skills/tool_schemas.py::build_tool_schemas(...)`. Do not hand-list tools.
- **Commit after every task** (the final step of each task). Use the message shown.
- Branch is already `feature/coordinator-design`; stay on it.

## File Structure (locked)

```
g1_brain/g1_brain/fleet/
  __init__.py
  contracts/
    __init__.py
    models.py              # CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType + reserved
    capability_export.py   # build_capability_descriptor() from build_tool_schemas
    json_schema_export.py  # dump pydantic models -> JSON Schema files
  harness_core/
    __init__.py
    event_fanout.py        # EventSink: tap ConversationLogger -> async queue of RobotEvent
    core.py                # HarnessCore facade (get_capabilities/get_state/get_safety_state/subscribe_events)
    brain_session.py       # OperatorBrainSession Protocol (interface only, this slice)
  bus/
    __init__.py
    messages.py            # wire envelope: FrameKind + encode/decode
    base.py                # FleetBus Protocol + EventFilter
    ws_server.py           # aiohttp WS server side (coordinator inbound)
    ws_client.py           # robot-agent outbound client w/ reconnect+backoff+heartbeat
  coordinator/
    __init__.py
    event_log.py           # append-only sqlite + jsonl mirror, query + replay
    registry.py            # FleetRegistry + StateAggregator (online/stale/offline)
    perception_agg.py      # PerceptionAggregator (N local semantic views + rollup)
    world_model.py         # FleetWorldModel Protocol + IdentityWorldModel
    app.py                 # aiohttp read-only API wiring server+registry+log+agg
    __main__.py            # python -m g1_brain.fleet.coordinator launcher
  agent/
    __init__.py
    robot_agent.py         # headless entry: HarnessCore (injected) -> ws_client publish loop
  console/
    __init__.py
    cli.py                 # read-only printer hitting the coordinator API

g1_brain/tests/fleet/
  __init__.py
  test_contracts_models.py
  test_json_schema_export.py
  test_capability_export.py
  test_event_fanout.py
  test_harness_core.py
  test_event_builder.py
  test_bus_messages.py
  test_ws_server.py
  test_ws_client.py
  test_event_log.py
  test_registry.py
  test_perception_agg.py
  test_coordinator_app.py
  test_robot_agent.py
  test_e2e_readonly.py
  test_coordinator_main_smoke.py
```

---

## Task 1: Contracts — pydantic models

**Files:**
- Create: `g1_brain/g1_brain/fleet/__init__.py`
- Create: `g1_brain/g1_brain/fleet/contracts/__init__.py`
- Create: `g1_brain/g1_brain/fleet/contracts/models.py`
- Create: `g1_brain/tests/fleet/__init__.py`
- Test: `g1_brain/tests/fleet/test_contracts_models.py`

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_contracts_models.py
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
    CommandEnvelope, TaskSpec, AdmissionDecision,
)


def test_capability_descriptor_roundtrip():
    cap = CapabilityDescriptor(
        robot_id="g1-sim-01",
        harness_version="0.1.0",
        frame_id="g1-sim-01/map",
        capabilities=[{"name": "walk", "risk_level": "medium", "params_schema": "walk.v1"}],
    )
    dumped = cap.model_dump_json()
    back = CapabilityDescriptor.model_validate_json(dumped)
    assert back == cap
    assert back.schema_version == "CapabilityDescriptor.v1"
    assert back.embodiment.type == "humanoid_g1"


def test_robot_state_msg_minimal():
    st = RobotStateMsg(robot_id="g1-sim-01", ts="2026-06-06T08:00:00Z", seq=1,
                       fsm_state="ENGAGED", motion_state="idle")
    assert st.schema_version == "RobotStateMsg.v1"
    assert st.core.safety_state.e_stop is False
    assert st.core.policy_active is False


def test_robot_event_hash_is_deterministic():
    ev1 = RobotEvent.make(robot_id="r", trace_id="t", type=EventType.SCENE_SNAPSHOT,
                          ts="2026-06-06T08:00:00Z", payload={"a": 1, "b": 2})
    ev2 = RobotEvent.make(robot_id="r", trace_id="t", type=EventType.SCENE_SNAPSHOT,
                          ts="2026-06-06T08:00:00Z", payload={"b": 2, "a": 1})
    # event_id differs (ulid), payload_hash is order-independent and equal
    assert ev1.payload_hash == ev2.payload_hash
    assert ev1.event_id != ev2.event_id


def test_reserved_contracts_are_marked():
    assert CommandEnvelope().status == "reserved"
    assert TaskSpec().status == "reserved"
    assert AdmissionDecision().status == "reserved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_contracts_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'g1_brain.fleet'`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/__init__.py
"""Fleet command-center layer (read-only foundation slice).

See docs/superpowers/specs/2026-06-06-fleet-foundation-design.md.
Coordinator -> motor path is deliberately absent in this slice.
"""
```

```python
# g1_brain/g1_brain/fleet/contracts/__init__.py
```

```python
# g1_brain/g1_brain/fleet/contracts/models.py
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


def _ulid_like() -> str:
    # Monotonic-enough unique id without a new dependency.
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
    payload_hash: str
    payload: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def make(cls, *, robot_id: str, type: EventType, ts: str,
             payload: Dict[str, Any], trace_id: Optional[str] = None) -> "RobotEvent":
        # default=str keeps hashing robust even if a stray non-JSON value slips
        # into payload; producers are still expected to pass JSON-safe dicts.
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        digest = "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return cls(event_id=_ulid_like(), trace_id=trace_id, robot_id=robot_id,
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
```

```python
# g1_brain/tests/fleet/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_contracts_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/__init__.py g1_brain/fleet/contracts/ tests/fleet/__init__.py tests/fleet/test_contracts_models.py
git commit -m "feat(fleet): typed contracts (capability/state/event + reserved)"
```

---

## Task 2: JSON Schema export

**Files:**
- Create: `g1_brain/g1_brain/fleet/contracts/json_schema_export.py`
- Test: `g1_brain/tests/fleet/test_json_schema_export.py`

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_json_schema_export.py
import json
from g1_brain.fleet.contracts.json_schema_export import export_schemas


def test_export_writes_one_file_per_model(tmp_path):
    written = export_schemas(tmp_path)
    names = {p.name for p in written}
    assert "CapabilityDescriptor.v1.schema.json" in names
    assert "RobotStateMsg.v1.schema.json" in names
    assert "RobotEvent.v1.schema.json" in names
    # Each file is valid JSON with a title
    for p in written:
        doc = json.loads(p.read_text())
        assert "properties" in doc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_json_schema_export.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/contracts/json_schema_export.py
"""Dump pydantic contract models to JSON Schema files (CI artifact)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .models import CapabilityDescriptor, RobotStateMsg, RobotEvent

_MODELS = {
    "CapabilityDescriptor.v1": CapabilityDescriptor,
    "RobotStateMsg.v1": RobotStateMsg,
    "RobotEvent.v1": RobotEvent,
}


def export_schemas(out_dir: Path) -> List[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for name, model in _MODELS.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False))
        written.append(path)
    return written


if __name__ == "__main__":  # pragma: no cover
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("contracts_schema")
    for p in export_schemas(target):
        print(p)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_json_schema_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/contracts/json_schema_export.py tests/fleet/test_json_schema_export.py
git commit -m "feat(fleet): JSON Schema export for contracts"
```

---

## Task 3: Capability export from tool_schemas

**Files:**
- Create: `g1_brain/g1_brain/fleet/contracts/capability_export.py`
- Test: `g1_brain/tests/fleet/test_capability_export.py`

The function reads `build_tool_schemas(...)` (the real tool catalog) and maps each tool to a `CapabilityEntry`, classifying risk via a local map so the descriptor never drifts from the catalog.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_capability_export.py
from g1_brain.fleet.contracts.capability_export import build_capability_descriptor


def test_descriptor_covers_real_tool_catalog():
    cap = build_capability_descriptor(robot_id="g1-sim-02", harness_version="9.9.9")
    names = {c.name for c in cap.capabilities}
    # Tools that must always be present in sim mode:
    assert {"walk", "turn", "gesture", "say", "ask_slow_brain"} <= names
    # Real-robot-only tools are excluded in sim mode:
    assert "loco_high" not in names
    assert cap.robot_id == "g1-sim-02"
    assert cap.harness_version == "9.9.9"


def test_risk_levels_assigned():
    cap = build_capability_descriptor(robot_id="r")
    by_name = {c.name: c.risk_level for c in cap.capabilities}
    assert by_name["walk"] == "medium"
    assert by_name["gesture"] == "low"
    assert by_name["say"] == "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_capability_export.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/contracts/capability_export.py
"""Derive a CapabilityDescriptor from the real tool catalog.

Single source of truth = g1_brain.skills.tool_schemas.build_tool_schemas().
Risk levels live here (not in the schema) and are classified per tool name.
"""
from __future__ import annotations

from g1_brain.skills.tool_schemas import build_tool_schemas

from .models import CapabilityDescriptor, CapabilityEntry

# Risk classification by tool name. Motion tools carry the highest risk; pure
# information tools are "none". Keep in sync with SafetySupervisor's ALLOWED sets.
_RISK = {
    "walk": "medium", "turn": "medium", "approach": "medium",
    "gesture": "low", "static_pose": "low", "look_at": "low", "mock_imitate": "low",
    "stop": "low", "release_arms": "low",
    "loco_high": "high", "arm_action_high": "high", "audio_tts_robot": "low",
}


def _risk_for(name: str) -> str:
    return _RISK.get(name, "none")


def build_capability_descriptor(
    *, robot_id: str, harness_version: str = "0.1.0",
    trust_level: str = "sim", frame_id: str | None = None, sim: bool = True,
) -> CapabilityDescriptor:
    schemas = build_tool_schemas(sim=sim)
    caps = [
        CapabilityEntry(
            name=s["name"],
            risk_level=_risk_for(s["name"]),
            params_schema=f"{s['name']}.v1",
        )
        for s in schemas
    ]
    return CapabilityDescriptor(
        robot_id=robot_id,
        harness_version=harness_version,
        trust_level=trust_level,            # type: ignore[arg-type]
        frame_id=frame_id or f"{robot_id}/map",
        capabilities=caps,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_capability_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/contracts/capability_export.py tests/fleet/test_capability_export.py
git commit -m "feat(fleet): capability descriptor auto-export from tool catalog"
```

---

## Task 4: Event fan-out tap on ConversationLogger

**Files:**
- Create: `g1_brain/g1_brain/fleet/harness_core/__init__.py`
- Create: `g1_brain/g1_brain/fleet/harness_core/event_fanout.py`
- Test: `g1_brain/tests/fleet/test_event_fanout.py`

`EventSink` is a thin, zero-config buffer. `attach_to_logger()` monkey-wraps the
two meta loggers whose kwargs are JSON-safe (`log_safety_event`, `log_action_result`),
converting each call into a `RobotEvent` pushed into a bounded `asyncio.Queue`. The
original logger behavior is preserved (we call through), so this is zero-impact on
existing logging.

**Why not tap `log_scene_snapshot`:** its `scene_state=` kwarg is a live
`SceneState` object (not JSON-safe), and tapping at the method boundary would push
that object into a `RobotEvent` payload. Perception events are produced separately
by the robot-agent's perception loop (Task 6 + Task 14), which snapshots the scene
bus and emits compact semantic dicts. So the logger tap covers safety + action only.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_event_fanout.py
import asyncio
import pytest

from g1_brain.fleet.harness_core.event_fanout import EventSink, attach_to_logger
from g1_brain.fleet.contracts.models import EventType


class _FakeLogger:
    """Minimal stand-in exposing the methods EventSink taps."""
    def __init__(self):
        self.calls = []

    def log_safety_event(self, **kw):
        self.calls.append(("safety", kw))

    def log_action_result(self, **kw):
        self.calls.append(("action", kw))


@pytest.mark.asyncio
async def test_safety_event_is_fanned_out_and_original_called():
    logger = _FakeLogger()
    sink = EventSink(robot_id="r1", maxsize=8)
    attach_to_logger(logger, sink)

    logger.log_safety_event(kind="reject", rule="RULE-9", details="too close")

    # original behavior preserved
    assert logger.calls == [("safety", {"kind": "reject", "rule": "RULE-9",
                                        "details": "too close"})]
    ev = await asyncio.wait_for(sink.queue.get(), timeout=1.0)
    assert ev.type == EventType.SAFETY_EVENT
    assert ev.robot_id == "r1"
    assert ev.payload["rule"] == "RULE-9"


@pytest.mark.asyncio
async def test_action_result_is_fanned_out():
    logger = _FakeLogger()
    sink = EventSink(robot_id="r1", maxsize=8)
    attach_to_logger(logger, sink)
    logger.log_action_result(tool_use_id="c1", tool_name="walk", args={"vx": 0.1},
                             status="ok", outcome_metrics={"displacement_m": 0.2})
    ev = await asyncio.wait_for(sink.queue.get(), timeout=1.0)
    assert ev.type == EventType.ACTION_RESULT
    assert ev.payload["tool_name"] == "walk"


@pytest.mark.asyncio
async def test_queue_drops_oldest_when_full():
    logger = _FakeLogger()
    sink = EventSink(robot_id="r1", maxsize=2)
    attach_to_logger(logger, sink)
    for i in range(5):
        logger.log_safety_event(kind="warn", rule=f"RULE-{i}")
    # bounded; never blocks; keeps most recent 2
    assert sink.queue.qsize() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_event_fanout.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/harness_core/__init__.py
```

```python
# g1_brain/g1_brain/fleet/harness_core/event_fanout.py
"""Tap ConversationLogger's meta loggers and fan out as RobotEvent.

Zero-impact: each wrapper calls the original method first, then enqueues a
RobotEvent. The queue is bounded; on overflow we drop the OLDEST scene_snapshot
to protect safety/action events (best-effort, never blocks the caller).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from g1_brain.fleet.contracts.models import EventType, RobotEvent

log = logging.getLogger(__name__)


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class EventSink:
    def __init__(self, *, robot_id: str, maxsize: int = 256):
        self.robot_id = robot_id
        self.queue: "asyncio.Queue[RobotEvent]" = asyncio.Queue(maxsize=maxsize)

    def emit(self, type_: EventType, payload: Dict[str, Any],
             trace_id: str | None = None) -> None:
        ev = RobotEvent.make(robot_id=self.robot_id, type=type_, ts=_iso_now(),
                             payload=payload, trace_id=trace_id)
        try:
            self.queue.put_nowait(ev)
        except asyncio.QueueFull:
            # Drop oldest to make room; protects newest safety/action events.
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(ev)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                log.warning("event fan-out dropped %s", type_)


def attach_to_logger(logger: Any, sink: EventSink) -> None:
    """Wrap logger.log_* so each call also enqueues a RobotEvent."""

    def _wrap(method_name: str, ev_type: EventType):
        original = getattr(logger, method_name, None)
        if original is None:
            return

        def wrapped(**kw):
            original(**kw)
            sink.emit(ev_type, dict(kw))

        setattr(logger, method_name, wrapped)

    # Only JSON-safe loggers are tapped. Perception/scene events are produced by
    # the robot-agent's perception loop (Task 6 + Task 14), not here.
    _wrap("log_safety_event", EventType.SAFETY_EVENT)
    _wrap("log_action_result", EventType.ACTION_RESULT)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_event_fanout.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/harness_core/__init__.py g1_brain/fleet/harness_core/event_fanout.py tests/fleet/test_event_fanout.py
git commit -m "feat(fleet): event fan-out tap on ConversationLogger"
```

---

## Task 5: HarnessCore facade + state builder

**Files:**
- Create: `g1_brain/g1_brain/fleet/harness_core/core.py`
- Create: `g1_brain/g1_brain/fleet/harness_core/brain_session.py`
- Test: `g1_brain/tests/fleet/test_harness_core.py`

`HarnessCore` wraps the already-built objects (`RobotFsm`, `SceneStateBus`,
`RobotStateBus`) and exposes the read-only contract surface. It builds a
`RobotStateMsg` from the scene `RobotState` + FSM + bus snapshots, and exposes
`subscribe_events()` over the `EventSink` queue. `admit()` is reserved.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_harness_core.py
import asyncio
import pytest

from g1_brain.safety.state_machine import RobotFsm, RobotFsmState
from g1_brain.scene_state.fusion import SceneStateBus, RobotStateBus
from g1_brain.scene_state.types import RobotState as BodyState, GroundConstraint
from g1_brain.fleet.harness_core.core import HarnessCore
from g1_brain.fleet.harness_core.event_fanout import EventSink, attach_to_logger
from g1_brain.fleet.contracts.models import EventType


class _FakeLogger:
    def log_safety_event(self, **kw): pass
    def log_action_result(self, **kw): pass
    def log_scene_snapshot(self, **kw): pass


def _make_core():
    fsm = RobotFsm(initial=RobotFsmState.STANDING)
    fsm.transition(RobotFsmState.ENGAGED, "test")
    scene = SceneStateBus()
    scene.update_ground(GroundConstraint(clear_path=True, nearest_obstacle_m=2.0,
                                         nearest_person_m=float("inf"),
                                         floor_visible_ratio=0.9, surface_tilt_deg=1.0))
    robot = RobotStateBus()
    robot.update(BodyState(standing=True, gravity_proj_z=-0.98,
                           base_ang_vel_xyz=(0, 0, 0), rl_policy_active=True,
                           last_lowstate_age_s=0.01, mode_machine=1))
    sink = EventSink(robot_id="g1-sim-01")
    core = HarnessCore(robot_id="g1-sim-01", fsm=fsm, scene_bus=scene,
                       robot_bus=robot, event_sink=sink, harness_version="0.1.0")
    return core, sink


def test_get_capabilities():
    core, _ = _make_core()
    cap = core.get_capabilities()
    assert cap.robot_id == "g1-sim-01"
    assert any(c.name == "walk" for c in cap.capabilities)


def test_get_state_maps_fsm_and_body():
    core, _ = _make_core()
    st = core.get_state(seq=7)
    assert st.robot_id == "g1-sim-01"
    assert st.fsm_state == "ENGAGED"
    assert st.seq == 7
    assert st.core.policy_active is True
    assert st.core.safety_state.gravity_proj_z == -0.98
    assert st.core.safety_state.watchdog_ok.lowstate is True


def test_snapshot_scene_returns_bus_snapshot():
    core, _ = _make_core()
    scene = core.snapshot_scene()
    assert scene.ground is not None
    assert scene.ground.clear_path is True


@pytest.mark.asyncio
async def test_subscribe_events_yields_fanned_out_event():
    core, sink = _make_core()
    logger = _FakeLogger()
    attach_to_logger(logger, sink)
    logger.log_safety_event(kind="reject", rule="RULE-9")
    agen = core.subscribe_events()
    ev = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    assert ev.type == EventType.SAFETY_EVENT


def test_admit_is_reserved():
    core, _ = _make_core()
    with pytest.raises(NotImplementedError):
        core.admit(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_harness_core.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/harness_core/brain_session.py
"""OperatorBrainSession — attachable fast/slow brain interface (this slice: stub).

The voice app attaches a concrete session to a local HarnessCore. Multi-robot
focus switching is a later slice; here we only fix the interface.
"""
from __future__ import annotations

from typing import Protocol


class OperatorBrainSession(Protocol):
    async def attach(self, core: "object") -> None: ...
    async def detach(self) -> None: ...
```

```python
# g1_brain/g1_brain/fleet/harness_core/core.py
"""HarnessCore — thin read-only facade over existing per-robot subsystems.

Incremental wrap: it does NOT own or restart anything. It is constructed with
already-built objects (RobotFsm, SceneStateBus, RobotStateBus, EventSink) and
exposes the fleet contract surface. No control path exists here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

from g1_brain.safety.state_machine import RobotFsm
from g1_brain.scene_state.fusion import SceneStateBus, RobotStateBus
from g1_brain.scene_state.types import SceneState
from g1_brain.fleet.contracts.capability_export import build_capability_descriptor
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, CoreState, SafetyStateMsg,
    WatchdogOk,
)
from g1_brain.fleet.harness_core.event_fanout import EventSink


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class HarnessCore:
    def __init__(self, *, robot_id: str, fsm: RobotFsm,
                 scene_bus: SceneStateBus, robot_bus: RobotStateBus,
                 event_sink: EventSink, harness_version: str = "0.1.0",
                 lowstate_max_age_s: float = 0.5, head_max_age_s: float = 2.0):
        self.robot_id = robot_id
        self._fsm = fsm
        self._scene = scene_bus
        self._robot = robot_bus
        self._sink = event_sink
        self._harness_version = harness_version
        self._lowstate_max_age = lowstate_max_age_s
        self._head_max_age = head_max_age_s

    def get_capabilities(self) -> CapabilityDescriptor:
        return build_capability_descriptor(
            robot_id=self.robot_id, harness_version=self._harness_version,
            frame_id=f"{self.robot_id}/map",
        )

    def get_state(self, *, seq: int = 0) -> RobotStateMsg:
        body = self._robot.snapshot()
        scene = self._scene.snapshot()
        lowstate_ok = self._robot.lowstate_age_s() <= self._lowstate_max_age
        head_ok = self._scene.head_frame_age_s() <= self._head_max_age
        grav = body.gravity_proj_z if body else -1.0
        pose_ok = grav <= -0.85
        policy = bool(body.rl_policy_active) if body else False
        motion = "moving" if self._fsm.state.value == "ACTING" else "idle"
        core = CoreState(
            pose=None,
            safety_state=SafetyStateMsg(
                e_stop=False,
                geofence_ok=True,
                gravity_proj_z=grav,
                watchdog_ok=WatchdogOk(lowstate=lowstate_ok, head_frame=head_ok,
                                       pose=pose_ok),
            ),
            policy_active=policy,
            battery=None,
        )
        ext = {}
        if body is not None:
            ext = {"g1_sim": {"mode_machine": body.mode_machine}}
        return RobotStateMsg(
            robot_id=self.robot_id, ts=_iso_now(), seq=seq,
            fsm_state=self._fsm.state.value, motion_state=motion,
            core=core, extensions=ext,
        )

    def get_safety_state(self) -> SafetyStateMsg:
        return self.get_state().core.safety_state

    async def subscribe_events(self) -> AsyncIterator[RobotEvent]:
        while True:
            yield await self._sink.queue.get()

    def snapshot_scene(self) -> SceneState:
        """Latest fused perception snapshot; the agent perception loop turns this
        into semantic RobotEvents (see fleet/agent/event_builder.py)."""
        return self._scene.snapshot()

    def admit(self, envelope) -> None:  # reserved this slice
        raise NotImplementedError("admit() is reserved; no control path in read-only slice")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_harness_core.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/harness_core/core.py g1_brain/fleet/harness_core/brain_session.py tests/fleet/test_harness_core.py
git commit -m "feat(fleet): HarnessCore read-only facade + state mapping"
```

---

## Task 6: Semantic perception event builder

**Files:**
- Create: `g1_brain/g1_brain/fleet/agent/__init__.py`
- Create: `g1_brain/g1_brain/fleet/agent/event_builder.py`
- Test: `g1_brain/tests/fleet/test_event_builder.py`

Converts a `SceneState` snapshot into compact semantic events: always a
`scene_snapshot` (using the existing `summary_for_llm()` dict), plus threshold
`human_detected` / `obstacle_detected`. No raw frames ever leave the robot.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_event_builder.py
from g1_brain.scene_state.types import SceneState, GroundConstraint
from g1_brain.fleet.agent.event_builder import build_perception_events
from g1_brain.fleet.contracts.models import EventType


def _scene(nearest_person, nearest_obstacle, clear_path):
    s = SceneState()
    s.ground = GroundConstraint(clear_path=clear_path, nearest_obstacle_m=nearest_obstacle,
                                nearest_person_m=nearest_person, floor_visible_ratio=0.8,
                                surface_tilt_deg=2.0)
    return s


def test_always_emits_scene_snapshot_with_summary():
    evs = build_perception_events("r1", _scene(float("inf"), 3.0, True),
                                  person_thresh_m=0.8, obstacle_thresh_m=0.6)
    types = [e.type for e in evs]
    assert EventType.SCENE_SNAPSHOT in types
    snap = next(e for e in evs if e.type == EventType.SCENE_SNAPSHOT)
    assert snap.payload["clear_path"] is True
    assert snap.robot_id == "r1"


def test_emits_human_and_obstacle_when_thresholds_crossed():
    evs = build_perception_events("r1", _scene(0.5, 0.4, False),
                                  person_thresh_m=0.8, obstacle_thresh_m=0.6)
    types = {e.type for e in evs}
    assert EventType.HUMAN_DETECTED in types
    assert EventType.OBSTACLE_DETECTED in types


def test_no_threshold_events_when_clear():
    evs = build_perception_events("r1", _scene(float("inf"), 5.0, True),
                                  person_thresh_m=0.8, obstacle_thresh_m=0.6)
    types = {e.type for e in evs}
    assert EventType.HUMAN_DETECTED not in types
    assert EventType.OBSTACLE_DETECTED not in types
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_event_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/agent/__init__.py
```

```python
# g1_brain/g1_brain/fleet/agent/event_builder.py
"""Build compact, semantic RobotEvents from a SceneState snapshot.

Doc principle: the center receives semantic events, never raw video/point clouds.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List

from g1_brain.scene_state.types import SceneState
from g1_brain.fleet.contracts.models import EventType, RobotEvent


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def build_perception_events(
    robot_id: str, scene: SceneState, *,
    person_thresh_m: float = 0.8, obstacle_thresh_m: float = 0.6,
) -> List[RobotEvent]:
    ts = _iso_now()
    summary = scene.summary_for_llm()
    events = [RobotEvent.make(robot_id=robot_id, type=EventType.SCENE_SNAPSHOT,
                              ts=ts, payload=summary)]
    g = scene.ground
    if g is not None:
        if math.isfinite(g.nearest_person_m) and g.nearest_person_m <= person_thresh_m:
            events.append(RobotEvent.make(
                robot_id=robot_id, type=EventType.HUMAN_DETECTED, ts=ts,
                payload={"nearest_person_m": round(g.nearest_person_m, 2)}))
        if (not g.clear_path) or (
            math.isfinite(g.nearest_obstacle_m) and g.nearest_obstacle_m <= obstacle_thresh_m
        ):
            events.append(RobotEvent.make(
                robot_id=robot_id, type=EventType.OBSTACLE_DETECTED, ts=ts,
                payload={"nearest_obstacle_m": (round(g.nearest_obstacle_m, 2)
                         if math.isfinite(g.nearest_obstacle_m) else None),
                         "clear_path": g.clear_path}))
    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_event_builder.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/agent/__init__.py g1_brain/fleet/agent/event_builder.py tests/fleet/test_event_builder.py
git commit -m "feat(fleet): semantic perception event builder"
```

---

## Task 7: FleetBus wire messages

**Files:**
- Create: `g1_brain/g1_brain/fleet/bus/__init__.py`
- Create: `g1_brain/g1_brain/fleet/bus/messages.py`
- Create: `g1_brain/g1_brain/fleet/bus/base.py`
- Test: `g1_brain/tests/fleet/test_bus_messages.py`

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_bus_messages.py
from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


def test_register_frame_roundtrip():
    cap = CapabilityDescriptor(robot_id="r", frame_id="r/map")
    raw = encode_frame(FrameKind.REGISTER, cap)
    kind, model = decode_frame(raw)
    assert kind == FrameKind.REGISTER
    assert isinstance(model, CapabilityDescriptor)
    assert model.robot_id == "r"


def test_heartbeat_and_event_roundtrip():
    st = RobotStateMsg(robot_id="r", ts="t", seq=3)
    kind, model = decode_frame(encode_frame(FrameKind.HEARTBEAT, st))
    assert kind == FrameKind.HEARTBEAT and model.seq == 3

    ev = RobotEvent.make(robot_id="r", type=EventType.SCENE_SNAPSHOT, ts="t", payload={})
    kind, model = decode_frame(encode_frame(FrameKind.EVENT, ev))
    assert kind == FrameKind.EVENT and model.type == EventType.SCENE_SNAPSHOT


def test_ping_frame_has_no_model():
    kind, model = decode_frame(encode_frame(FrameKind.PING, None))
    assert kind == FrameKind.PING and model is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_bus_messages.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/bus/__init__.py
```

```python
# g1_brain/g1_brain/fleet/bus/messages.py
"""Wire envelope for the FleetBus: a JSON frame with a kind discriminator."""
from __future__ import annotations

import enum
import json
from typing import Optional, Tuple

from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent,
)


class FrameKind(str, enum.Enum):
    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    EVENT = "event"
    PING = "ping"
    PONG = "pong"


_MODEL_FOR = {
    FrameKind.REGISTER: CapabilityDescriptor,
    FrameKind.HEARTBEAT: RobotStateMsg,
    FrameKind.EVENT: RobotEvent,
}


def encode_frame(kind: FrameKind, model: Optional[object]) -> str:
    body = model.model_dump(mode="json") if model is not None else None
    return json.dumps({"kind": kind.value, "body": body}, ensure_ascii=False)


def decode_frame(raw: str) -> Tuple[FrameKind, Optional[object]]:
    obj = json.loads(raw)
    kind = FrameKind(obj["kind"])
    model_cls = _MODEL_FOR.get(kind)
    if model_cls is None or obj.get("body") is None:
        return kind, None
    return kind, model_cls.model_validate(obj["body"])
```

```python
# g1_brain/g1_brain/fleet/bus/base.py
"""FleetBus abstraction. The WS implementation (Task 8/9) satisfies this."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional, Protocol

from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent,
)


@dataclass
class EventFilter:
    robot_ids: Optional[List[str]] = None
    types: Optional[List[str]] = field(default=None)


class FleetBus(Protocol):
    async def register(self, cap: CapabilityDescriptor) -> None: ...
    async def heartbeat(self, st: RobotStateMsg) -> None: ...
    async def publish(self, ev: RobotEvent) -> None: ...
    def subscribe(self, flt: EventFilter) -> AsyncIterator[RobotEvent]: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_bus_messages.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/bus/__init__.py g1_brain/fleet/bus/messages.py g1_brain/fleet/bus/base.py tests/fleet/test_bus_messages.py
git commit -m "feat(fleet): FleetBus wire frames + abstract interface"
```

---

## Task 8: Coordinator EventLog (append-only sqlite + jsonl)

**Files:**
- Create: `g1_brain/g1_brain/fleet/coordinator/__init__.py`
- Create: `g1_brain/g1_brain/fleet/coordinator/event_log.py`
- Test: `g1_brain/tests/fleet/test_event_log.py`

Mirrors `memory/storage.py` sqlite pattern (WAL, busy_timeout). Append-only
`events` table + a `.jsonl` mirror. Query by robot/trace/time + `replay(trace_id)`.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_event_log.py
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.contracts.models import RobotEvent, EventType


def _ev(robot, trace, t):
    return RobotEvent.make(robot_id=robot, trace_id=trace, type=EventType.ACTION_RESULT,
                           ts=t, payload={"k": t})


def test_append_and_query_by_robot(tmp_path):
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    log.append(_ev("r1", "trace-a", "2026-06-06T00:00:01Z"))
    log.append(_ev("r2", "trace-a", "2026-06-06T00:00:02Z"))
    rows = log.query(robot_id="r1")
    assert len(rows) == 1 and rows[0].robot_id == "r1"
    log.close()


def test_replay_returns_trace_in_order(tmp_path):
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    log.append(_ev("r1", "trace-x", "2026-06-06T00:00:03Z"))
    log.append(_ev("r1", "trace-x", "2026-06-06T00:00:01Z"))
    log.append(_ev("r1", "trace-y", "2026-06-06T00:00:02Z"))
    out = log.replay("trace-x")
    assert [e.ts for e in out] == ["2026-06-06T00:00:01Z", "2026-06-06T00:00:03Z"]
    log.close()


def test_append_is_idempotent_on_event_id(tmp_path):
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    ev = _ev("r1", "trace-a", "2026-06-06T00:00:01Z")
    log.append(ev); log.append(ev)  # same event_id twice
    assert len(log.query(robot_id="r1")) == 1
    log.close()


def test_jsonl_mirror_written(tmp_path):
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    log.append(_ev("r1", "trace-a", "2026-06-06T00:00:01Z"))
    mirror = tmp_path / "fleet.jsonl"
    assert mirror.exists() and mirror.read_text().strip() != ""
    log.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_event_log.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/coordinator/__init__.py
```

```python
# g1_brain/g1_brain/fleet/coordinator/event_log.py
"""Append-only event store (sqlite WAL + jsonl mirror) with replay.

Pattern mirrors g1_brain/memory/storage.py. INSERT OR IGNORE on event_id makes
append idempotent (re-delivered events do not duplicate).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

from g1_brain.fleet.contracts.models import RobotEvent

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    trace_id     TEXT,
    robot_id     TEXT NOT NULL,
    type         TEXT NOT NULL,
    ts           TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    ingest_seq   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_robot ON events(robot_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id, ts, ingest_seq);
"""


class EventLog:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.jsonl_path = self.db_path.with_suffix(".jsonl")
        self._conn: Optional[sqlite3.Connection] = None
        self._seq = 0

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None,
                                     check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        row = self._conn.execute("SELECT MAX(ingest_seq) AS m FROM events").fetchone()
        self._seq = int(row["m"]) if row and row["m"] is not None else 0

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def append(self, ev: RobotEvent) -> None:
        assert self._conn is not None
        self._seq += 1
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO events
               (event_id, trace_id, robot_id, type, ts, payload_hash, payload_json, ingest_seq)
               VALUES (?,?,?,?,?,?,?,?)""",
            (ev.event_id, ev.trace_id, ev.robot_id, ev.type.value, ev.ts,
             ev.payload_hash, json.dumps(ev.payload, ensure_ascii=False), self._seq),
        )
        if cur.rowcount:
            with open(self.jsonl_path, "a", encoding="utf-8") as fh:
                fh.write(ev.model_dump_json() + "\n")

    def _rows_to_events(self, rows) -> List[RobotEvent]:
        out = []
        for r in rows:
            out.append(RobotEvent(event_id=r["event_id"], trace_id=r["trace_id"],
                                  robot_id=r["robot_id"], type=r["type"], ts=r["ts"],
                                  payload_hash=r["payload_hash"],
                                  payload=json.loads(r["payload_json"])))
        return out

    def query(self, *, robot_id: Optional[str] = None, trace_id: Optional[str] = None,
              since: Optional[str] = None, until: Optional[str] = None,
              limit: int = 500) -> List[RobotEvent]:
        assert self._conn is not None
        clauses, params = [], []
        if robot_id: clauses.append("robot_id = ?"); params.append(robot_id)
        if trace_id: clauses.append("trace_id = ?"); params.append(trace_id)
        if since: clauses.append("ts >= ?"); params.append(since)
        if until: clauses.append("ts <= ?"); params.append(until)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM events {where} ORDER BY ts ASC, ingest_seq ASC LIMIT ?", params,
        ).fetchall()
        return self._rows_to_events(rows)

    def replay(self, trace_id: str) -> List[RobotEvent]:
        return self.query(trace_id=trace_id, limit=100000)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_event_log.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/coordinator/__init__.py g1_brain/fleet/coordinator/event_log.py tests/fleet/test_event_log.py
git commit -m "feat(fleet): append-only event log with replay"
```

---

## Task 9: FleetRegistry + StateAggregator

**Files:**
- Create: `g1_brain/g1_brain/fleet/coordinator/registry.py`
- Test: `g1_brain/tests/fleet/test_registry.py`

Tracks each robot's descriptor + latest state + `last_seen`, and derives
`online | stale | offline` from a monotonic clock injected for testability.
Drops out-of-order states by `seq`.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_registry.py
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.contracts.models import CapabilityDescriptor, RobotStateMsg


def _clock():
    box = {"t": 1000.0}
    return box, (lambda: box["t"])


def test_register_then_heartbeat_online():
    box, now = _clock()
    reg = FleetRegistry(stale_after_s=5.0, offline_after_s=15.0, now=now)
    reg.register(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
    reg.on_heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=1))
    assert reg.status("r1") == "online"


def test_transitions_to_stale_then_offline():
    box, now = _clock()
    reg = FleetRegistry(stale_after_s=5.0, offline_after_s=15.0, now=now)
    reg.register(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
    reg.on_heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=1))
    box["t"] = 1008.0
    assert reg.status("r1") == "stale"
    box["t"] = 1020.0
    assert reg.status("r1") == "offline"


def test_out_of_order_seq_dropped():
    box, now = _clock()
    reg = FleetRegistry(stale_after_s=5.0, offline_after_s=15.0, now=now)
    reg.register(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
    reg.on_heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=5, fsm_state="ENGAGED"))
    reg.on_heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=2, fsm_state="ACTING"))
    assert reg.latest_state("r1").fsm_state == "ENGAGED"


def test_list_robots():
    box, now = _clock()
    reg = FleetRegistry(stale_after_s=5.0, offline_after_s=15.0, now=now)
    reg.register(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
    reg.register(CapabilityDescriptor(robot_id="r2", frame_id="r2/map"))
    assert {r["robot_id"] for r in reg.list_robots()} == {"r1", "r2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/coordinator/registry.py
"""In-memory fleet registry + staleness. Persistence not needed read-only slice."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from g1_brain.fleet.contracts.models import CapabilityDescriptor, RobotStateMsg


@dataclass
class _Entry:
    cap: CapabilityDescriptor
    last_state: Optional[RobotStateMsg] = None
    last_seen: float = 0.0
    last_seq: int = -1


class FleetRegistry:
    def __init__(self, *, stale_after_s: float = 5.0, offline_after_s: float = 15.0,
                 now: Callable[[], float] = time.monotonic):
        self._stale = stale_after_s
        self._offline = offline_after_s
        self._now = now
        self._robots: Dict[str, _Entry] = {}

    def register(self, cap: CapabilityDescriptor) -> None:
        e = self._robots.get(cap.robot_id)
        if e is None:
            self._robots[cap.robot_id] = _Entry(cap=cap, last_seen=self._now())
        else:
            e.cap = cap
            e.last_seen = self._now()

    def on_heartbeat(self, st: RobotStateMsg) -> None:
        e = self._robots.get(st.robot_id)
        if e is None:
            return  # heartbeat before register: ignore until registered
        if st.seq < e.last_seq:
            return  # out of order
        e.last_seq = st.seq
        e.last_state = st
        e.last_seen = self._now()

    def status(self, robot_id: str) -> str:
        e = self._robots.get(robot_id)
        if e is None:
            return "unknown"
        age = self._now() - e.last_seen
        if age >= self._offline:
            return "offline"
        if age >= self._stale:
            return "stale"
        return "online"

    def latest_state(self, robot_id: str) -> Optional[RobotStateMsg]:
        e = self._robots.get(robot_id)
        return e.last_state if e else None

    def list_robots(self) -> List[dict]:
        out = []
        for rid, e in self._robots.items():
            out.append({
                "robot_id": rid,
                "status": self.status(rid),
                "capabilities": [c.name for c in e.cap.capabilities],
                "state": e.last_state.model_dump(mode="json") if e.last_state else None,
            })
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_registry.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/coordinator/registry.py tests/fleet/test_registry.py
git commit -m "feat(fleet): fleet registry + staleness aggregator"
```

---

## Task 10: PerceptionAggregator + FleetWorldModel

**Files:**
- Create: `g1_brain/g1_brain/fleet/coordinator/world_model.py`
- Create: `g1_brain/g1_brain/fleet/coordinator/perception_agg.py`
- Test: `g1_brain/tests/fleet/test_perception_agg.py`

Keeps the latest `scene_snapshot` payload per robot and computes a fleet roll-up.
`IdentityWorldModel` satisfies the `FleetWorldModel` seam (independent frames now;
shared-frame fusion is a later slice).

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_perception_agg.py
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel
from g1_brain.fleet.contracts.models import RobotEvent, EventType


def _snap(robot, clear_path, persons):
    return RobotEvent.make(robot_id=robot, type=EventType.SCENE_SNAPSHOT, ts="t",
                           payload={"clear_path": clear_path, "persons_visible": persons,
                                    "nearest_person_m": 0.5 if persons else None})


def test_latest_snapshot_per_robot():
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    agg.ingest(_snap("r1", True, 0))
    agg.ingest(_snap("r1", False, 1))  # newer wins
    assert agg.latest("r1")["clear_path"] is False


def test_rollup_counts():
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    agg.ingest(_snap("r1", False, 1))
    agg.ingest(_snap("r2", True, 0))
    agg.ingest(_snap("r3", False, 2))
    roll = agg.rollup()
    assert roll["robots_path_blocked"] == 2
    assert roll["robots_with_humans"] == 2
    assert roll["robot_count"] == 3


def test_non_scene_events_ignored():
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    ev = RobotEvent.make(robot_id="r1", type=EventType.ACTION_RESULT, ts="t", payload={})
    agg.ingest(ev)
    assert agg.latest("r1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_perception_agg.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/coordinator/world_model.py
"""FleetWorldModel seam. Identity now; shared-frame fusion is a later slice."""
from __future__ import annotations

from typing import Dict, List, Protocol


class FleetWorldModel(Protocol):
    def to_global(self, robot_id: str, pose: dict) -> dict: ...
    def fuse_detections(self, per_robot: Dict[str, dict]) -> List[dict]: ...


class IdentityWorldModel:
    """Each robot lives in its own frame; no cross-robot fusion."""
    def to_global(self, robot_id: str, pose: dict) -> dict:
        return pose

    def fuse_detections(self, per_robot: Dict[str, dict]) -> List[dict]:
        return [{"robot_id": rid, **snap} for rid, snap in per_robot.items()]
```

```python
# g1_brain/g1_brain/fleet/coordinator/perception_agg.py
"""Aggregate N per-robot semantic scene snapshots + fleet roll-up."""
from __future__ import annotations

from typing import Dict, Optional

from g1_brain.fleet.contracts.models import RobotEvent, EventType
from g1_brain.fleet.coordinator.world_model import FleetWorldModel


class PerceptionAggregator:
    def __init__(self, *, world_model: FleetWorldModel):
        self._wm = world_model
        self._latest: Dict[str, dict] = {}

    def ingest(self, ev: RobotEvent) -> None:
        if ev.type != EventType.SCENE_SNAPSHOT:
            return
        self._latest[ev.robot_id] = ev.payload

    def latest(self, robot_id: str) -> Optional[dict]:
        return self._latest.get(robot_id)

    def rollup(self) -> dict:
        blocked = sum(1 for s in self._latest.values() if s.get("clear_path") is False)
        humans = sum(1 for s in self._latest.values() if (s.get("persons_visible") or 0) > 0)
        return {
            "robot_count": len(self._latest),
            "robots_path_blocked": blocked,
            "robots_with_humans": humans,
            "fused": self._wm.fuse_detections(self._latest),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_perception_agg.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/coordinator/world_model.py g1_brain/fleet/coordinator/perception_agg.py tests/fleet/test_perception_agg.py
git commit -m "feat(fleet): perception aggregator + identity world-model seam"
```

---

## Task 11: FleetBus WS server (coordinator inbound)

**Files:**
- Create: `g1_brain/g1_brain/fleet/bus/ws_server.py`
- Test: `g1_brain/tests/fleet/test_ws_server.py`

aiohttp WS endpoint `/fleet` (mirrors `phone/bridge_server.py`). On each frame it
routes REGISTER→registry, HEARTBEAT→registry, EVENT→(event_log + perception_agg),
PING→PONG. A `+GET /robots` JSON route is added in Task 13's app; here we only test
the WS routing via aiohttp's test client.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_ws_server.py
import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.bus.ws_server import build_fleet_app
from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


@pytest.fixture
def deps(tmp_path):
    reg = FleetRegistry()
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    yield reg, log, agg
    log.close()


@pytest.mark.asyncio
async def test_register_heartbeat_event_routed(deps):
    reg, log, agg = deps
    app = build_fleet_app(registry=reg, event_log=log, perception_agg=agg)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/fleet")
        await ws.send_str(encode_frame(FrameKind.REGISTER,
                          CapabilityDescriptor(robot_id="r1", frame_id="r1/map")))
        await ws.send_str(encode_frame(FrameKind.HEARTBEAT,
                          RobotStateMsg(robot_id="r1", ts="t", seq=1, fsm_state="ENGAGED")))
        await ws.send_str(encode_frame(FrameKind.EVENT,
                          RobotEvent.make(robot_id="r1", type=EventType.SCENE_SNAPSHOT,
                                          ts="t", payload={"clear_path": False,
                                                           "persons_visible": 1})))
        await ws.send_str(encode_frame(FrameKind.PING, None))
        reply = await ws.receive_str()
        kind, _ = decode_frame(reply)
        assert kind == FrameKind.PONG
        await ws.close()
    finally:
        await client.close()

    assert reg.latest_state("r1").fsm_state == "ENGAGED"
    assert reg.status("r1") == "online"
    assert len(log.query(robot_id="r1")) == 1
    assert agg.latest("r1")["clear_path"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_ws_server.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/bus/ws_server.py
"""aiohttp WebSocket server: ingest fleet frames into coordinator services.

Mirrors the structure of g1_brain/phone/bridge_server.py. No control path back
to robots exists; this endpoint is strictly inbound (telemetry up).
"""
from __future__ import annotations

import logging

from aiohttp import web

from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent,
)

log = logging.getLogger(__name__)


def build_fleet_app(*, registry, event_log, perception_agg) -> web.Application:
    app = web.Application()
    app["registry"] = registry
    app["event_log"] = event_log
    app["perception_agg"] = perception_agg
    app.router.add_get("/fleet", _fleet_ws)
    return app


async def _fleet_ws(request: web.Request) -> web.WebSocketResponse:
    registry = request.app["registry"]
    event_log = request.app["event_log"]
    perception_agg = request.app["perception_agg"]

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    async for msg in ws:
        if msg.type != web.WSMsgType.TEXT:
            continue
        try:
            kind, model = decode_frame(msg.data)
        except Exception:
            log.warning("fleet: undecodable frame")
            continue
        if kind == FrameKind.REGISTER and isinstance(model, CapabilityDescriptor):
            registry.register(model)
        elif kind == FrameKind.HEARTBEAT and isinstance(model, RobotStateMsg):
            registry.on_heartbeat(model)
        elif kind == FrameKind.EVENT and isinstance(model, RobotEvent):
            event_log.append(model)
            perception_agg.ingest(model)
        elif kind == FrameKind.PING:
            await ws.send_str(encode_frame(FrameKind.PONG, None))
    return ws
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_ws_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/bus/ws_server.py tests/fleet/test_ws_server.py
git commit -m "feat(fleet): WebSocket fleet ingest server"
```

---

## Task 12: FleetBus WS client (robot-agent outbound)

**Files:**
- Create: `g1_brain/g1_brain/fleet/bus/ws_client.py`
- Test: `g1_brain/tests/fleet/test_ws_client.py`

Outbound client implementing `FleetBus`: connects to the coordinator with
exponential backoff (mirrors `brain/realtime_agent.py`), sends REGISTER on connect,
exposes `heartbeat()` / `publish()`. Tested against the real Task-11 server in-process.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_ws_client.py
import asyncio
import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.bus.ws_server import build_fleet_app
from g1_brain.fleet.bus.ws_client import WsFleetClient
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


@pytest.mark.asyncio
async def test_client_registers_and_publishes(tmp_path):
    reg = FleetRegistry()
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    app = build_fleet_app(registry=reg, event_log=log, perception_agg=agg)
    client = TestClient(TestServer(app))
    await client.start_server()
    url = f"http://{client.host}:{client.port}/fleet"
    try:
        fc = WsFleetClient(url=url, reconnect=False)
        await fc.connect(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
        await fc.heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=1, fsm_state="ENGAGED"))
        await fc.publish(RobotEvent.make(robot_id="r1", type=EventType.SCENE_SNAPSHOT,
                                         ts="t", payload={"clear_path": True}))
        await asyncio.sleep(0.1)  # let server drain
        await fc.close()
    finally:
        await client.close()
        log.close()

    assert reg.status("r1") == "online"
    assert reg.latest_state("r1").fsm_state == "ENGAGED"
    assert len(log.query(robot_id="r1")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_ws_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/bus/ws_client.py
"""Outbound FleetBus client (robot-agent side) with reconnect + backoff.

Backoff schedule mirrors brain/realtime_agent.py (1s -> 15s capped). The client
re-sends REGISTER on every (re)connect so a coordinator restart re-learns the
robot. heartbeat()/publish() no-op silently while disconnected (telemetry is
best-effort; local safety is unaffected).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from g1_brain.fleet.bus.messages import encode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent,
)

log = logging.getLogger(__name__)


class WsFleetClient:
    def __init__(self, *, url: str, reconnect: bool = True,
                 backoff_start: float = 1.0, backoff_max: float = 15.0):
        self._url = url
        self._reconnect = reconnect
        self._backoff_start = backoff_start
        self._backoff_max = backoff_max
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._cap: Optional[CapabilityDescriptor] = None
        self._lock = asyncio.Lock()

    async def connect(self, cap: CapabilityDescriptor) -> None:
        self._cap = cap
        self._session = aiohttp.ClientSession()
        await self._open_once()

    async def _open_once(self) -> bool:
        try:
            self._ws = await self._session.ws_connect(self._url, heartbeat=30)
            await self._ws.send_str(encode_frame(FrameKind.REGISTER, self._cap))
            log.info("fleet client connected to %s", self._url)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("fleet client connect failed: %s", e)
            self._ws = None
            return False

    async def _send(self, kind: FrameKind, model) -> None:
        async with self._lock:
            if self._ws is None or self._ws.closed:
                if not self._reconnect:
                    return
                await self._reconnect_loop()
                if self._ws is None:
                    return
            try:
                await self._ws.send_str(encode_frame(kind, model))
            except Exception as e:  # noqa: BLE001
                log.warning("fleet client send failed: %s", e)
                self._ws = None

    async def _reconnect_loop(self) -> None:
        delay = self._backoff_start
        for _ in range(6):
            if await self._open_once():
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._backoff_max)

    async def heartbeat(self, st: RobotStateMsg) -> None:
        await self._send(FrameKind.HEARTBEAT, st)

    async def publish(self, ev: RobotEvent) -> None:
        await self._send(FrameKind.EVENT, ev)

    async def register(self, cap: CapabilityDescriptor) -> None:
        self._cap = cap
        await self._send(FrameKind.REGISTER, cap)

    async def close(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_ws_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/bus/ws_client.py tests/fleet/test_ws_client.py
git commit -m "feat(fleet): WebSocket fleet client with reconnect/backoff"
```

---

## Task 13: Coordinator read-only HTTP API

**Files:**
- Create: `g1_brain/g1_brain/fleet/coordinator/app.py`
- Test: `g1_brain/tests/fleet/test_coordinator_app.py`

Adds read-only JSON routes onto the same aiohttp app that hosts `/fleet`:
`GET /robots`, `GET /robots/{id}`, `GET /events`, `GET /replay/{trace_id}`,
`GET /perception`. One `build_coordinator_app()` composes server + routes.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_coordinator_app.py
import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.coordinator.app import build_coordinator_app
from g1_brain.fleet.bus.messages import encode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


@pytest.mark.asyncio
async def test_readonly_routes(tmp_path):
    app = build_coordinator_app(db_path=tmp_path / "fleet.sqlite")
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/fleet")
        await ws.send_str(encode_frame(FrameKind.REGISTER,
                          CapabilityDescriptor(robot_id="r1", frame_id="r1/map")))
        await ws.send_str(encode_frame(FrameKind.HEARTBEAT,
                          RobotStateMsg(robot_id="r1", ts="t", seq=1, fsm_state="ENGAGED")))
        await ws.send_str(encode_frame(FrameKind.EVENT,
                          RobotEvent.make(robot_id="r1", trace_id="trace-1",
                                          type=EventType.SCENE_SNAPSHOT, ts="t",
                                          payload={"clear_path": False, "persons_visible": 1})))
        await ws.close()

        robots = await (await client.get("/robots")).json()
        assert robots[0]["robot_id"] == "r1" and robots[0]["status"] == "online"

        one = await (await client.get("/robots/r1")).json()
        assert one["state"]["fsm_state"] == "ENGAGED"

        events = await (await client.get("/events?robot_id=r1")).json()
        assert len(events) == 1

        replay = await (await client.get("/replay/trace-1")).json()
        assert replay[0]["trace_id"] == "trace-1"

        perc = await (await client.get("/perception")).json()
        assert perc["rollup"]["robots_path_blocked"] == 1
    finally:
        await client.close()
        app["event_log"].close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_coordinator_app.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/coordinator/app.py
"""Compose the coordinator: WS ingest (/fleet) + read-only JSON API."""
from __future__ import annotations

from pathlib import Path

from aiohttp import web

from g1_brain.fleet.bus.ws_server import build_fleet_app
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel


def build_coordinator_app(*, db_path: Path) -> web.Application:
    registry = FleetRegistry()
    event_log = EventLog(Path(db_path)); event_log.init()
    perception_agg = PerceptionAggregator(world_model=IdentityWorldModel())

    app = build_fleet_app(registry=registry, event_log=event_log,
                          perception_agg=perception_agg)
    app.router.add_get("/robots", _robots)
    app.router.add_get("/robots/{rid}", _robot)
    app.router.add_get("/events", _events)
    app.router.add_get("/replay/{trace_id}", _replay)
    app.router.add_get("/perception", _perception)
    return app


async def _robots(request: web.Request) -> web.Response:
    return web.json_response(request.app["registry"].list_robots())


async def _robot(request: web.Request) -> web.Response:
    rid = request.match_info["rid"]
    for r in request.app["registry"].list_robots():
        if r["robot_id"] == rid:
            return web.json_response(r)
    return web.json_response({"error": "unknown robot"}, status=404)


async def _events(request: web.Request) -> web.Response:
    q = request.query
    rows = request.app["event_log"].query(
        robot_id=q.get("robot_id"), trace_id=q.get("trace_id"),
        since=q.get("since"), until=q.get("until"),
        limit=int(q.get("limit", "500")),
    )
    return web.json_response([e.model_dump(mode="json") for e in rows])


async def _replay(request: web.Request) -> web.Response:
    rows = request.app["event_log"].replay(request.match_info["trace_id"])
    return web.json_response([e.model_dump(mode="json") for e in rows])


async def _perception(request: web.Request) -> web.Response:
    agg = request.app["perception_agg"]
    return web.json_response({"rollup": agg.rollup()})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_coordinator_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/coordinator/app.py tests/fleet/test_coordinator_app.py
git commit -m "feat(fleet): coordinator read-only HTTP API"
```

---

## Task 14: Robot-agent publish loop (headless)

**Files:**
- Create: `g1_brain/g1_brain/fleet/agent/robot_agent.py`
- Test: `g1_brain/tests/fleet/test_robot_agent.py`

`RobotAgent` ties a `HarnessCore` to a `FleetBus` client: on `start()` it registers,
then runs three background loops — a heartbeat loop (`core.get_state` every N s), an
event-forward loop (`core.subscribe_events` → `bus.publish` for safety/action events),
and a perception loop (`core.snapshot_scene()` → `build_perception_events` →
`bus.publish` every M s; disabled when `perception_interval_s is None`). It takes an
injected `core` and `bus` so it is unit-testable without DDS/aiohttp. (The real headless
process wiring — building a `HarnessCore` from the existing `agent_main` DDS/combo/
perception init minus the brain — is integration glue documented in the module
docstring and exercised manually in sim; it is intentionally out of the unit test.)

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_robot_agent.py
import asyncio
import pytest

from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.scene_state.types import SceneState, GroundConstraint
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


class _FakeBus:
    def __init__(self):
        self.registered = None
        self.heartbeats = []
        self.events = []
    async def connect(self, cap): self.registered = cap
    async def heartbeat(self, st): self.heartbeats.append(st)
    async def publish(self, ev): self.events.append(ev)
    async def close(self): pass


class _FakeCore:
    robot_id = "r1"
    def __init__(self):
        self._q = asyncio.Queue()
    def get_capabilities(self):
        return CapabilityDescriptor(robot_id="r1", frame_id="r1/map")
    def get_state(self, *, seq=0):
        return RobotStateMsg(robot_id="r1", ts="t", seq=seq, fsm_state="ENGAGED")
    async def subscribe_events(self):
        while True:
            yield await self._q.get()
    def snapshot_scene(self):
        s = SceneState()
        s.ground = GroundConstraint(clear_path=True, nearest_obstacle_m=3.0,
                                    nearest_person_m=float("inf"),
                                    floor_visible_ratio=0.9, surface_tilt_deg=1.0)
        return s
    def push(self, ev):
        self._q.put_nowait(ev)


@pytest.mark.asyncio
async def test_agent_registers_heartbeats_forwards_and_perceives():
    bus, core = _FakeBus(), _FakeCore()
    agent = RobotAgent(core=core, bus=bus, heartbeat_interval_s=0.05,
                       perception_interval_s=0.05)
    await agent.start()
    core.push(RobotEvent.make(robot_id="r1", type=EventType.SAFETY_EVENT, ts="t", payload={}))
    await asyncio.sleep(0.16)
    await agent.stop()

    assert bus.registered.robot_id == "r1"
    assert len(bus.heartbeats) >= 2
    assert bus.heartbeats[0].seq == 1  # seq increments from 1
    assert any(e.type == EventType.SAFETY_EVENT for e in bus.events)
    # perception loop emits scene snapshots from snapshot_scene()
    assert any(e.type == EventType.SCENE_SNAPSHOT for e in bus.events)


@pytest.mark.asyncio
async def test_perception_loop_disabled_when_interval_none():
    bus, core = _FakeBus(), _FakeCore()
    agent = RobotAgent(core=core, bus=bus, heartbeat_interval_s=0.05,
                       perception_interval_s=None)
    await agent.start()
    await asyncio.sleep(0.16)
    await agent.stop()
    assert not any(e.type == EventType.SCENE_SNAPSHOT for e in bus.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_robot_agent.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/agent/robot_agent.py
"""Headless robot-agent: bridges a HarnessCore to a FleetBus client.

Read-only slice: it ONLY reports (register + heartbeat + forward events). It does
not accept commands; there is no path from the bus into the SkillServer.

Real-process wiring (not unit-tested here): a headless HarnessCore is built by
reusing agent_main's DDS/combo/perception/safety init while SKIPPING the Realtime
brain, codex memory, and phone subsystems. That assembly is exercised in sim via
`python -m g1_brain.fleet.agent.robot_agent --config <cfg> --coordinator <url>`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from g1_brain.fleet.agent.event_builder import build_perception_events

log = logging.getLogger(__name__)


class RobotAgent:
    def __init__(self, *, core, bus, heartbeat_interval_s: float = 2.0,
                 perception_interval_s: Optional[float] = 1.0):
        self._core = core
        self._bus = bus
        self._hb_interval = heartbeat_interval_s
        self._perc_interval = perception_interval_s
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._seq = 0

    async def start(self) -> None:
        await self._bus.connect(self._core.get_capabilities())
        self._tasks = [
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._event_loop()),
        ]
        if self._perc_interval is not None:
            self._tasks.append(asyncio.create_task(self._perception_loop()))

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            self._seq += 1
            try:
                await self._bus.heartbeat(self._core.get_state(seq=self._seq))
            except Exception:  # noqa: BLE001
                log.exception("heartbeat failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._hb_interval)
            except asyncio.TimeoutError:
                pass

    async def _event_loop(self) -> None:
        async for ev in self._core.subscribe_events():
            if self._stop.is_set():
                break
            try:
                await self._bus.publish(ev)
            except Exception:  # noqa: BLE001
                log.exception("event publish failed")

    async def _perception_loop(self) -> None:
        while not self._stop.is_set():
            try:
                scene = self._core.snapshot_scene()
                for ev in build_perception_events(self._core.robot_id, scene):
                    await self._bus.publish(ev)
            except Exception:  # noqa: BLE001
                log.exception("perception publish failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._perc_interval)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self._bus.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_robot_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add g1_brain/fleet/agent/robot_agent.py tests/fleet/test_robot_agent.py
git commit -m "feat(fleet): headless robot-agent publish loop"
```

---

## Task 15: Read-only console + end-to-end test

**Files:**
- Create: `g1_brain/g1_brain/fleet/console/__init__.py`
- Create: `g1_brain/g1_brain/fleet/console/cli.py`
- Test: `g1_brain/tests/fleet/test_e2e_readonly.py`

The console is a thin formatter over the API JSON (no new logic). The e2e test
wires the REAL coordinator app + REAL ws client + two REAL `RobotAgent`s driven by
`_FakeCore`s, proving registration → heartbeat → perception event → API visibility
→ replay, end to end.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_e2e_readonly.py
import asyncio
import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.coordinator.app import build_coordinator_app
from g1_brain.fleet.bus.ws_client import WsFleetClient
from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.fleet.console.cli import format_fleet
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


class _Core:
    def __init__(self, rid): self.robot_id = rid; self._q = asyncio.Queue()
    def get_capabilities(self): return CapabilityDescriptor(robot_id=self.robot_id,
                                                            frame_id=f"{self.robot_id}/map")
    def get_state(self, *, seq=0): return RobotStateMsg(robot_id=self.robot_id, ts="t",
                                                        seq=seq, fsm_state="ENGAGED")
    async def subscribe_events(self):
        while True: yield await self._q.get()
    def push(self, ev): self._q.put_nowait(ev)


@pytest.mark.asyncio
async def test_two_robots_visible_end_to_end(tmp_path):
    app = build_coordinator_app(db_path=tmp_path / "fleet.sqlite")
    client = TestClient(TestServer(app))
    await client.start_server()
    url = f"http://{client.host}:{client.port}/fleet"
    agents = []
    try:
        cores = [_Core("g1-sim-01"), _Core("g1-sim-02")]
        for c in cores:
            # perception loop disabled here so the only scene snapshot is the
            # manual push below (keeps the rollup assertions deterministic).
            a = RobotAgent(core=c, bus=WsFleetClient(url=url, reconnect=False),
                           heartbeat_interval_s=0.05, perception_interval_s=None)
            await a.start()
            agents.append(a)
        cores[0].push(RobotEvent.make(robot_id="g1-sim-01", trace_id="tr-1",
                                      type=EventType.SCENE_SNAPSHOT, ts="t",
                                      payload={"clear_path": False, "persons_visible": 1}))
        await asyncio.sleep(0.2)

        robots = await (await client.get("/robots")).json()
        ids = {r["robot_id"] for r in robots}
        assert ids == {"g1-sim-01", "g1-sim-02"}
        assert all(r["status"] == "online" for r in robots)

        perc = await (await client.get("/perception")).json()
        assert perc["rollup"]["robot_count"] == 1  # only sim-01 sent a scene snapshot
        assert perc["rollup"]["robots_path_blocked"] == 1

        replay = await (await client.get("/replay/tr-1")).json()
        assert len(replay) == 1

        # console formatter renders without error
        text = format_fleet(robots, perc["rollup"])
        assert "g1-sim-01" in text and "g1-sim-02" in text
    finally:
        for a in agents:
            await a.stop()
        await client.close()
        app["event_log"].close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_e2e_readonly.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/console/__init__.py
```

```python
# g1_brain/g1_brain/fleet/console/cli.py
"""Read-only console: format coordinator API JSON for a terminal.

Pure formatting — no new logic. A future web UI replaces this; the API is stable.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import List


def format_fleet(robots: List[dict], rollup: dict) -> str:
    lines = ["=== FLEET ==="]
    for r in robots:
        st = r.get("state") or {}
        lines.append(f"  {r['robot_id']:<12} {r['status']:<8} "
                     f"fsm={st.get('fsm_state', '?')} "
                     f"caps={len(r.get('capabilities', []))}")
    lines.append("=== PERCEPTION ===")
    lines.append(f"  robots_reporting={rollup.get('robot_count', 0)} "
                 f"path_blocked={rollup.get('robots_path_blocked', 0)} "
                 f"with_humans={rollup.get('robots_with_humans', 0)}")
    return "\n".join(lines)


async def _fetch(base: str) -> str:
    import aiohttp
    async with aiohttp.ClientSession() as s:
        robots = await (await s.get(f"{base}/robots")).json()
        perc = await (await s.get(f"{base}/perception")).json()
    return format_fleet(robots, perc.get("rollup", {}))


def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8090")
    args = ap.parse_args()
    print(asyncio.run(_fetch(args.base)))


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_e2e_readonly.py -v`
Expected: PASS

- [ ] **Step 5: Run the full fleet suite**

Run: `python -m pytest tests/fleet/ -v`
Expected: all green

- [ ] **Step 6: Commit**

```bash
git add g1_brain/fleet/console/ tests/fleet/test_e2e_readonly.py
git commit -m "feat(fleet): read-only console + end-to-end test"
```

---

## Task 16: Coordinator runnable entry + docs

**Files:**
- Create: `g1_brain/g1_brain/fleet/coordinator/__main__.py`
- Modify: `g1_brain/g1_brain/fleet/__init__.py` (add module docstring pointer — already created in Task 1; append the run note)
- Test: `g1_brain/tests/fleet/test_coordinator_main_smoke.py`

Gives an explicit `python -m g1_brain.fleet.coordinator` launcher so the slice is
runnable in sim, and a smoke test that the app builds.

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_coordinator_main_smoke.py
from g1_brain.fleet.coordinator.__main__ import build_default_app


def test_build_default_app(tmp_path):
    app = build_default_app(db_path=tmp_path / "fleet.sqlite")
    paths = {r.resource.canonical for r in app.router.routes() if r.resource}
    assert "/fleet" in paths
    assert "/robots" in paths
    app["event_log"].close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fleet/test_coordinator_main_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/coordinator/__main__.py
"""Run the read-only coordinator: python -m g1_brain.fleet.coordinator"""
from __future__ import annotations

import argparse
from pathlib import Path

from aiohttp import web

from g1_brain.fleet.coordinator.app import build_coordinator_app


def build_default_app(*, db_path: Path) -> web.Application:
    return build_coordinator_app(db_path=Path(db_path))


def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--db", default="logs/fleet/fleet.sqlite")
    args = ap.parse_args()
    app = build_default_app(db_path=Path(args.db))
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/fleet/test_coordinator_main_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Run full repo suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: existing suites + new `tests/fleet/` all pass

- [ ] **Step 6: Commit**

```bash
git add g1_brain/fleet/coordinator/__main__.py tests/fleet/test_coordinator_main_smoke.py
git commit -m "feat(fleet): runnable coordinator entrypoint + smoke test"
```

---

## Done criteria (verify before finishing)

- [ ] `python -m pytest tests/fleet/ -v` all green (16 test files).
- [ ] `python -m pytest -q` shows no regressions in existing suites.
- [ ] Manual sim sanity (optional, documented): start `python -m g1_brain.fleet.coordinator --port 8090`, then point `format_fleet` console at it; confirm robots appear/disappear as agents start/stop.
- [ ] Grep check: no import path from `fleet/coordinator/` or `fleet/bus/ws_server.py` into `SkillServer`/`combo`/DDS publish — the read-only invariant holds.

## Notes for the executor

- **Do not** add any command/dispatch route to `ws_server.py` or the coordinator app — that is the next slice (`CommandEnvelope`), deliberately deferred.
- The `RobotAgent` real-process wiring (building a headless `HarnessCore` from `agent_main` init minus brain) is integration glue; keep it injected/testable. If you build the real launcher, reuse `agent_main`'s DDS/combo/perception setup and SKIP Realtime/codex/phone — do not duplicate those subsystems.
- Keep `RobotStateMsg` and `scene_state.types.RobotState` distinct at all times.
