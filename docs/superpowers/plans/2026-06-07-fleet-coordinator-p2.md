# Phase 2 Implementation Plan — Hierarchical OpenAI Dispatch

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox steps for tracking.

**Goal:** Type natural language → a coordinator OpenAI brain decomposes it into a multi-robot `FleetPlan` → one OpenAI sub-agent per robot turns its objective into a validated op sequence → a deterministic rendezvous barrier sequences cooperation. Served via `POST /chat` + a dashboard chat card.

**Architecture:** Pure decision layer on top of P1. `FleetCommander` (NL+snapshot→`FleetPlan`) and `RobotSubAgent` (objective→ops) each have an OpenAI path AND a deterministic fallback, so the whole thing runs and is unit-testable with NO `OPENAI_API_KEY`. Every LLM output is re-validated against the live registry before anything is dispatched (LLM proposes, deterministic disposes). The live "robots actually walk to the meeting point and hand off" integration is P3.

**Tech Stack:** Python 3.11 (env `agi`), pydantic v2, aiohttp (existing coordinator app + test client), openai SDK (optional). Reuse `coordinator/{app,controller,agent_llm,registry}.py`, `contracts/models.py`.

**Test cmd:** from `g1_brain`: `conda run -n agi --no-capture-output python -m pytest tests/fleet/<f>::<t> -v`

---

## File Structure

**Create:**
- `fleet/coordinator/fleet_plan.py` — `RobotAssignment`, `Coordination`, `FleetPlan`, `SubAgentOp` (pydantic)
- `fleet/coordinator/fleet_commander.py` — `FleetCommander` (deterministic + OpenAI)
- `fleet/coordinator/robot_subagent.py` — `RobotSubAgent` (deterministic + OpenAI)
- `fleet/coordinator/barrier.py` — `RendezvousBarrier`
- Tests: `tests/fleet/test_fleet_plan.py`, `test_fleet_commander.py`, `test_robot_subagent.py`, `test_barrier.py`, `test_chat_route.py`

**Modify:**
- `fleet/coordinator/app.py` — `POST /chat`, build `FleetCommander`, expose snapshot helper
- `fleet/coordinator/dashboard.py` — chat card (input + transcript)

---

## Task 1: Plan/op data models

**Files:** Create `fleet/coordinator/fleet_plan.py`; Test `tests/fleet/test_fleet_plan.py`

- [ ] **Step 1: failing test**

```python
# tests/fleet/test_fleet_plan.py
from g1_brain.fleet.coordinator.fleet_plan import (
    FleetPlan, Coordination, RobotAssignment, SubAgentOp)


def test_fleetplan_roundtrip():
    p = FleetPlan(
        summary="meet in the middle then hand off patrol",
        coordination=Coordination(type="relay", point=(0.0, 0.0),
                                  handoff_task="patrol", handoff_from="g1_a", handoff_to="g1_b"),
        assignments=[RobotAssignment(robot_id="g1_a", role="hander", objective="go to centre", goal=(-0.4, 0.0)),
                     RobotAssignment(robot_id="g1_b", role="receiver", objective="go to centre", goal=(0.4, 0.0))],
        risk="low")
    d = p.model_dump()
    assert FleetPlan.model_validate(d).coordination.type == "relay"


def test_subagentop():
    op = SubAgentOp(op="navigate", args={"x": 1.0, "y": 2.0})
    assert op.op == "navigate" and op.args["x"] == 1.0
```

- [ ] **Step 2: run → FAIL** `pytest tests/fleet/test_fleet_plan.py -v` (ModuleNotFoundError)

- [ ] **Step 3: implement**

```python
# fleet/coordinator/fleet_plan.py
"""Typed plan/op contracts for the hierarchical dispatch layer (P2)."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class RobotAssignment(BaseModel):
    robot_id: str
    role: str = ""
    objective: str = ""
    goal: Optional[Tuple[float, float]] = None   # nav target if applicable


class Coordination(BaseModel):
    type: str = "none"   # rendezvous | relay | cover | patrol | none
    point: Optional[Tuple[float, float]] = None
    handoff_task: Optional[str] = None
    handoff_from: Optional[str] = None
    handoff_to: Optional[str] = None


class FleetPlan(BaseModel):
    summary: str = ""
    coordination: Coordination = Field(default_factory=Coordination)
    assignments: List[RobotAssignment] = Field(default_factory=list)
    needs_clarification: Optional[str] = None
    risk: str = "low"


class SubAgentOp(BaseModel):
    op: str                       # navigate | await_barrier | patrol | idle | sleep | wake
    args: Dict = Field(default_factory=dict)
```

- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** `feat(fleet): P2 plan/op data models`

---

## Task 2: FleetCommander deterministic planner

**Files:** Create `fleet/coordinator/fleet_commander.py`; Test `tests/fleet/test_fleet_commander.py`

The deterministic planner makes the demo work with NO key. It reads intent keywords (English + 中文) and the live snapshot (robot positions) to build a `FleetPlan`. Midpoint rendezvous: meet near the centroid of current robot xy; assign each robot an adjacent point offset along the line between them (so they stop at a safe gap, not on top of each other).

- [ ] **Step 1: failing test**

```python
# tests/fleet/test_fleet_commander.py
from g1_brain.fleet.coordinator.fleet_commander import FleetCommander

SNAP = {"robots": [{"robot_id": "g1_a", "x": -1.5, "y": 0.0},
                   {"robot_id": "g1_b", "x": 1.5, "y": 0.0}]}


def test_rendezvous_intent_builds_two_goals():
    fc = FleetCommander(llm=None)
    plan = fc.plan("两个机器人到中间会合", SNAP)
    assert plan.coordination.type in ("rendezvous", "relay")
    assert {a.robot_id for a in plan.assignments} == {"g1_a", "g1_b"}
    assert all(a.goal is not None for a in plan.assignments)
    # goals are between the two robots and offset apart
    ga = next(a.goal for a in plan.assignments if a.robot_id == "g1_a")
    gb = next(a.goal for a in plan.assignments if a.robot_id == "g1_b")
    assert -1.0 < ga[0] < gb[0] < 1.0


def test_relay_intent_sets_handoff():
    fc = FleetCommander(llm=None)
    plan = fc.plan("让 g1_a 和 g1_b 会合，然后 a 把巡逻交给 b", SNAP)
    assert plan.coordination.type == "relay"
    assert plan.coordination.handoff_from == "g1_a"
    assert plan.coordination.handoff_to == "g1_b"
    assert plan.coordination.handoff_task == "patrol"


def test_unknown_intent_needs_clarification():
    fc = FleetCommander(llm=None)
    plan = fc.plan("make me a sandwich", SNAP)
    assert plan.needs_clarification


def test_validate_rejects_unknown_robot():
    fc = FleetCommander(llm=None)
    plan = fc.plan("rendezvous", SNAP)
    ok, _ = fc.validate(plan, known_ids={"g1_a", "g1_b"})
    assert ok
    plan.assignments[0].robot_id = "ghost"
    ok, reason = fc.validate(plan, known_ids={"g1_a", "g1_b"})
    assert not ok and "ghost" in reason
```

- [ ] **Step 2: run → FAIL**

- [ ] **Step 3: implement**

```python
# fleet/coordinator/fleet_commander.py
"""FleetCommander — NL intent -> FleetPlan. OpenAI path with a deterministic
fallback so the demo runs (and tests pass) with no API key. The LLM only
proposes; validate() + the downstream gateway/admission dispose."""
from __future__ import annotations

import json
import logging
from typing import Optional, Set, Tuple

from g1_brain.fleet.coordinator.fleet_plan import (
    Coordination, FleetPlan, RobotAssignment)

log = logging.getLogger(__name__)

_RENDEZVOUS_KW = ("rendezvous", "meet", "会合", "中间", "汇合", "集合")
_RELAY_KW = ("relay", "hand off", "handoff", "hand over", "接力", "交给", "移交")
_PATROL_KW = ("patrol", "巡逻")


def _centroid(robots):
    if not robots:
        return (0.0, 0.0)
    return (sum(r["x"] for r in robots) / len(robots),
            sum(r["y"] for r in robots) / len(robots))


class FleetCommander:
    def __init__(self, llm=None):
        self._llm = llm

    def plan(self, nl: str, snapshot: dict) -> FleetPlan:
        if self._llm is not None:
            try:
                d = self._llm.plan_fleet(nl, snapshot)
                if d:
                    return FleetPlan.model_validate(d)
            except Exception:  # noqa: BLE001
                log.warning("llm plan failed; deterministic fallback", exc_info=True)
        return self._deterministic(nl, snapshot)

    def _deterministic(self, nl: str, snapshot: dict) -> FleetPlan:
        text = nl.lower()
        robots = list(snapshot.get("robots", []))
        ids = [r["robot_id"] for r in robots]
        is_rdv = any(k in text for k in _RENDEZVOUS_KW)
        is_relay = any(k in text for k in _RELAY_KW)
        if not (is_rdv or is_relay) and not any(k in text for k in _PATROL_KW):
            return FleetPlan(summary="unrecognized intent",
                             needs_clarification="我没听懂这条指令。试试：'两机到中间会合，然后 a 把巡逻交给 b'。")
        if len(robots) < 2:
            return FleetPlan(summary="need two robots",
                             needs_clarification="需要至少两台机器人在线才能会合/接力。")
        cx, cy = _centroid(robots)
        # order robots left->right so goals are offset symmetrically about centre
        ordered = sorted(robots, key=lambda r: r["x"])
        gap = 0.4
        assignments = []
        for i, r in enumerate(ordered):
            side = -1 if i == 0 else 1
            assignments.append(RobotAssignment(
                robot_id=r["robot_id"], role=("hander" if i == 0 else "receiver"),
                objective="go to the rendezvous point",
                goal=(cx + side * gap, cy)))
        coord = Coordination(type="relay" if is_relay else "rendezvous", point=(cx, cy))
        if is_relay:
            frm, to = self._handoff_dirs(text, ids, ordered)
            coord.handoff_task = "patrol"
            coord.handoff_from = frm
            coord.handoff_to = to
        return FleetPlan(
            summary=("会合后交接巡逻" if is_relay else "两机到中间会合"),
            coordination=coord, assignments=assignments, risk="low")

    @staticmethod
    def _handoff_dirs(text, ids, ordered):
        # if the text names "<id> ... 交给/hand off ... <id>" honour the order;
        # else default first->second (left->right).
        found = [rid for rid in ids if rid.lower() in text]
        if len(found) >= 2:
            return found[0], found[1]
        return ordered[0]["robot_id"], ordered[1]["robot_id"]

    def validate(self, plan: FleetPlan, known_ids: Set[str]) -> Tuple[bool, str]:
        for a in plan.assignments:
            if a.robot_id not in known_ids:
                return False, f"unknown robot {a.robot_id!r}"
        c = plan.coordination
        for who in (c.handoff_from, c.handoff_to):
            if who is not None and who not in known_ids:
                return False, f"unknown robot {who!r}"
        return True, "ok"


class OpenAIFleetLLM:  # pragma: no cover - needs network/key
    """Best-effort OpenAI adapter producing a FleetPlan dict."""

    def __init__(self, *, model: str = "gpt-4o-mini", api_key: Optional[str] = None):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self._model = model

    def plan_fleet(self, nl: str, snapshot: dict) -> Optional[dict]:
        sys = (
            "You are a multi-robot fleet coordinator. Given the operator command "
            "and the fleet snapshot (robot_id + x,y), output JSON for a FleetPlan with keys: "
            "summary; coordination{type:rendezvous|relay|cover|patrol|none, point:[x,y], "
            "handoff_task, handoff_from, handoff_to}; assignments[{robot_id, role, objective, goal:[x,y]}]; "
            "needs_clarification (string or null); risk:low|medium|high. "
            "Only use robot_ids present in the snapshot. For a rendezvous put each robot's goal "
            "near the centroid, offset so they stop ~0.8m apart. Reply with JSON only.")
        resp = self._client.chat.completions.create(
            model=self._model, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content": f"command: {nl}\nsnapshot: {json.dumps(snapshot)}"}])
        return json.loads(resp.choices[0].message.content)
```

- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** `feat(fleet): FleetCommander NL->FleetPlan (deterministic + OpenAI) (P2)`

---

## Task 3: RobotSubAgent

**Files:** Create `fleet/coordinator/robot_subagent.py`; Test `tests/fleet/test_robot_subagent.py`

Each sub-agent turns its assignment + the shared coordination contract into an ordered op list. Deterministic logic:
- always start with `navigate` to its goal;
- if coordination is rendezvous/relay → append `await_barrier`;
- if relay and this robot is `handoff_to` → append `patrol` (it picks up the task);
- if relay and this robot is `handoff_from` → append `idle` (it gives it up).

- [ ] **Step 1: failing test**

```python
# tests/fleet/test_robot_subagent.py
from g1_brain.fleet.coordinator.fleet_plan import Coordination, RobotAssignment
from g1_brain.fleet.coordinator.robot_subagent import RobotSubAgent


def _coord():
    return Coordination(type="relay", point=(0.0, 0.0), handoff_task="patrol",
                        handoff_from="g1_a", handoff_to="g1_b")


def test_receiver_navigates_waits_then_patrols():
    sa = RobotSubAgent("g1_b", llm=None)
    ops = sa.plan_ops(RobotAssignment(robot_id="g1_b", goal=(0.4, 0.0)), _coord())
    kinds = [o.op for o in ops]
    assert kinds == ["navigate", "await_barrier", "patrol"]
    assert ops[0].args == {"x": 0.4, "y": 0.0}


def test_hander_navigates_waits_then_idles():
    sa = RobotSubAgent("g1_a", llm=None)
    ops = sa.plan_ops(RobotAssignment(robot_id="g1_a", goal=(-0.4, 0.0)), _coord())
    assert [o.op for o in ops] == ["navigate", "await_barrier", "idle"]


def test_plain_rendezvous_just_navigates_and_waits():
    sa = RobotSubAgent("g1_a", llm=None)
    c = Coordination(type="rendezvous", point=(0.0, 0.0))
    ops = sa.plan_ops(RobotAssignment(robot_id="g1_a", goal=(-0.4, 0.0)), c)
    assert [o.op for o in ops] == ["navigate", "await_barrier"]
```

- [ ] **Step 2: run → FAIL**

- [ ] **Step 3: implement**

```python
# fleet/coordinator/robot_subagent.py
"""RobotSubAgent — one per robot. Turns its assignment + the shared
coordination contract into a validated op sequence. OpenAI path optional;
deterministic fallback keeps it usable/testable with no key."""
from __future__ import annotations

import logging
from typing import List, Optional

from g1_brain.fleet.coordinator.fleet_plan import (
    Coordination, RobotAssignment, SubAgentOp)

log = logging.getLogger(__name__)
_VALID = {"navigate", "await_barrier", "patrol", "idle", "sleep", "wake"}


class RobotSubAgent:
    def __init__(self, robot_id: str, llm=None):
        self.robot_id = robot_id
        self._llm = llm

    def plan_ops(self, assignment: RobotAssignment,
                 coordination: Coordination) -> List[SubAgentOp]:
        if self._llm is not None:
            try:
                raw = self._llm.plan_robot(self.robot_id, assignment.model_dump(),
                                           coordination.model_dump())
                ops = [SubAgentOp.model_validate(o) for o in (raw or [])]
                ops = [o for o in ops if o.op in _VALID]
                if ops:
                    return ops
            except Exception:  # noqa: BLE001
                log.warning("llm subagent failed; deterministic fallback", exc_info=True)
        return self._deterministic(assignment, coordination)

    def _deterministic(self, assignment: RobotAssignment,
                       coordination: Coordination) -> List[SubAgentOp]:
        ops: List[SubAgentOp] = []
        if assignment.goal is not None:
            ops.append(SubAgentOp(op="navigate",
                                  args={"x": assignment.goal[0], "y": assignment.goal[1]}))
        if coordination.type in ("rendezvous", "relay"):
            ops.append(SubAgentOp(op="await_barrier",
                                  args={"point": list(coordination.point or (0.0, 0.0))}))
        if coordination.type == "relay":
            if self.robot_id == coordination.handoff_to:
                ops.append(SubAgentOp(op=coordination.handoff_task or "patrol"))
            elif self.robot_id == coordination.handoff_from:
                ops.append(SubAgentOp(op="idle"))
        return ops
```

- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** `feat(fleet): RobotSubAgent objective->ops (deterministic + OpenAI) (P2)`

---

## Task 4: RendezvousBarrier

**Files:** Create `fleet/coordinator/barrier.py`; Test `tests/fleet/test_barrier.py`

- [ ] **Step 1: failing test**

```python
# tests/fleet/test_barrier.py
from g1_brain.fleet.coordinator.barrier import RendezvousBarrier


def test_releases_when_all_arrived():
    b = RendezvousBarrier({"g1_a", "g1_b"})
    assert not b.is_released()
    b.mark_arrived("g1_a")
    assert not b.is_released()
    b.mark_arrived("g1_b")
    assert b.is_released()


def test_arrived_by_position_within_radius():
    b = RendezvousBarrier({"g1_a", "g1_b"}, point=(0.0, 0.0), radius=0.6)
    b.update_position("g1_a", (0.4, 0.0))   # within 0.6
    b.update_position("g1_b", (2.0, 0.0))   # too far
    assert not b.is_released()
    b.update_position("g1_b", (-0.5, 0.0))  # now within
    assert b.is_released()
```

- [ ] **Step 2: run → FAIL**

- [ ] **Step 3: implement**

```python
# fleet/coordinator/barrier.py
"""Deterministic rendezvous barrier: cooperation timing is NOT left to the LLM.
A handoff step is released only once every participant has arrived (marked
explicitly, or detected within `radius` of the meeting point from telemetry)."""
from __future__ import annotations

import math
from typing import Optional, Set, Tuple


class RendezvousBarrier:
    def __init__(self, participants: Set[str], *,
                 point: Optional[Tuple[float, float]] = None, radius: float = 0.6):
        self.participants = set(participants)
        self.point = point
        self.radius = radius
        self._arrived: Set[str] = set()

    def mark_arrived(self, robot_id: str) -> None:
        if robot_id in self.participants:
            self._arrived.add(robot_id)

    def update_position(self, robot_id: str, xy: Tuple[float, float]) -> None:
        if self.point is None or robot_id not in self.participants:
            return
        if math.hypot(xy[0] - self.point[0], xy[1] - self.point[1]) <= self.radius:
            self._arrived.add(robot_id)

    def arrived(self) -> Set[str]:
        return set(self._arrived)

    def is_released(self) -> bool:
        return self.participants.issubset(self._arrived)
```

- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** `feat(fleet): deterministic RendezvousBarrier (P2)`

---

## Task 5: POST /chat route + app wiring

**Files:** Modify `fleet/coordinator/app.py`; Test `tests/fleet/test_chat_route.py`

`/chat` builds a snapshot from the registry, runs the commander (validated), runs a sub-agent per assigned robot, and returns a transcript. With no key the deterministic path is exercised end-to-end.

- [ ] **Step 1: failing test**

```python
# tests/fleet/test_chat_route.py
import pytest
from aiohttp.test_utils import TestClient, TestServer
from g1_brain.fleet.coordinator.app import build_coordinator_app


@pytest.fixture
async def client(tmp_path):
    app = build_coordinator_app(db_path=tmp_path / "c.sqlite", tick_interval_s=0.0, llm=None)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_chat_rendezvous_returns_plan_and_ops(client):
    # seed two robots into the registry with positions
    reg = client.app["registry"]
    from g1_brain.fleet.contracts.models import RobotStateMsg, CoreState, Pose
    for rid, x in (("g1_a", -1.5), ("g1_b", 1.5)):
        reg.upsert(RobotStateMsg(robot_id=rid, ts="t",
                   core=CoreState(pose=Pose(frame_id=f"{rid}/map", x=x, y=0.0))))
    r = await client.post("/chat", json={"nl": "两机到中间会合，然后 g1_a 把巡逻交给 g1_b"})
    body = await r.json()
    assert body["ok"] is True
    assert body["plan"]["coordination"]["type"] == "relay"
    assert set(body["ops"]) == {"g1_a", "g1_b"}
    assert body["ops"]["g1_b"][-1]["op"] == "patrol"


async def test_chat_unparseable_needs_clarification(client):
    r = await client.post("/chat", json={"nl": "make me a sandwich"})
    body = await r.json()
    assert body["ok"] is False and body["needs_clarification"]
```

- [ ] **Step 2: run → FAIL** (no `/chat`; maybe no `registry.upsert` — check the real method name in `registry.py` and adjust the test to it.)

- [ ] **Step 3: implement** — in `app.py`:
  1. import `FleetCommander`, `OpenAIFleetLLM`, `RobotSubAgent`.
  2. build `commander = FleetCommander(llm=_build_fleet_llm() if llm=="auto" else llm)` where `_build_fleet_llm` mirrors `_build_llm` but constructs `OpenAIFleetLLM`. Store `app["commander"] = commander`.
  3. add route `app.router.add_post("/chat", _chat)`.
  4. handler:

```python
def _snapshot(registry) -> dict:
    robots = []
    for r in registry.list_robots():
        core = (r.get("state") or {}).get("core") or {}
        pose = core.get("pose") or {}
        robots.append({"robot_id": r["robot_id"],
                       "x": float(pose.get("x", 0.0)), "y": float(pose.get("y", 0.0))})
    return {"robots": robots}


async def _chat(request):
    body = await request.json()
    nl = body.get("nl", "")
    registry = request.app["registry"]
    commander = request.app["commander"]
    snap = _snapshot(registry)
    plan = commander.plan(nl, snap)
    if plan.needs_clarification:
        return web.json_response({"ok": False, "needs_clarification": plan.needs_clarification,
                                  "summary": plan.summary})
    known = {r["robot_id"] for r in registry.list_robots()}
    ok, reason = commander.validate(plan, known)
    if not ok:
        return web.json_response({"ok": False, "reason": reason}, status=200)
    from g1_brain.fleet.coordinator.robot_subagent import RobotSubAgent
    sub_llm = getattr(request.app.get("commander"), "_llm", None)
    ops = {}
    for a in plan.assignments:
        sa = RobotSubAgent(a.robot_id, llm=sub_llm)
        ops[a.robot_id] = [o.model_dump() for o in sa.plan_ops(a, plan.coordination)]
    return web.json_response({"ok": True, "plan": plan.model_dump(), "ops": ops,
                              "explanation": plan.summary})
```

  Adjust `_snapshot`/seed to the registry's real API (check `registry.list_robots()` item shape and the upsert/ingest method name in `registry.py`).

- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** `feat(fleet): POST /chat hierarchical dispatch endpoint (P2)`

---

## Task 6: Dashboard chat card

**Files:** Modify `fleet/coordinator/dashboard.py`

- [ ] **Step 1:** Add a chat card to `INDEX_HTML` (after the Fleet card): a text input `#chatin`, a Send button calling `chat()`, and a `#chatlog` transcript div. `chat()` POSTs `{nl}` to `/chat` and renders `plan.summary`, per-robot `ops`, or `needs_clarification`.

```html
  <div class="card">
    <h2>AI 指挥官 — 自然语言调度 (OpenAI)</h2>
    <div class="row">
      <input id="chatin" style="flex:1;background:#0e1116;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 9px"
             placeholder="例: 两机到中间会合，然后 g1_a 把巡逻交给 g1_b" onkeydown="if(event.key==='Enter')chat()">
      <button class="primary" onclick="chat()">发送</button>
    </div>
    <div id="chatlog" style="margin-top:10px;font-size:13px;max-height:240px;overflow:auto"></div>
  </div>
```

```javascript
async function chat(){
  const el=$('chatin'); const nl=el.value.trim(); if(!nl) return; el.value='';
  add('<b>你</b> '+nl);
  try{
    const r=await fetch('/chat',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({nl})});
    const b=await r.json();
    if(!b.ok){ add('<span class="warn">指挥官</span> '+(b.needs_clarification||b.reason||'无法执行')); return; }
    let s='<span style="color:#3fb950">指挥官</span> '+b.plan.summary+' <span class="muted">['+b.plan.coordination.type+']</span>';
    for(const rid in b.ops){ s+='<br>&nbsp;&nbsp;<b>'+rid+'</b>: '+b.ops[rid].map(o=>o.op).join(' → '); }
    add(s);
  }catch(e){ add('<span class="warn">指挥官</span> 错误 '+e); }
}
function add(html){ const e=$('chatlog'); e.innerHTML='<div style="padding:3px 0;border-bottom:1px solid #1b2027">'+html+'</div>'+e.innerHTML; }
```

- [ ] **Step 2:** Smoke: `test_chat_route.py` already covers `/chat`; verify the dashboard still serves: `pytest tests/fleet/test_coordinator_dispatch_app.py::test_dashboard_served_at_root` (existing) stays green.
- [ ] **Step 3: commit** `feat(fleet): dashboard AI commander chat card (P2)`

---

## Self-Review
- Spec coverage: §5.1 FleetCommander→T2; §5.2 RobotSubAgent→T3; §5.3 barrier→T4; §5.4 /chat+UI→T5,T6; models→T1. ✓
- No-key path is the tested default; OpenAI adapters are `# pragma: no cover` (network).
- Type consistency: `FleetPlan/Coordination/RobotAssignment/SubAgentOp` field names match across commander, subagent, route, tests. ✓
- Deferred to P3: actually issuing ops to the live WorldSim, polling the barrier from telemetry, and the visible rendezvous/relay (the scenario test + viewer).
```
