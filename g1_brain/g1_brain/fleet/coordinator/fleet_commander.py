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
    """Best-effort OpenAI adapter producing a FleetPlan dict + per-robot ops."""

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

    def plan_robot(self, robot_id: str, assignment: dict, coordination: dict) -> Optional[list]:
        sys = (
            "You are the on-robot sub-agent for a single robot in a fleet. Given your "
            "assignment and the shared coordination contract, output a JSON list of ops to "
            "execute in order. Each op is {op, args}. Valid ops: navigate{x,y}, await_barrier, "
            "patrol, idle, sleep, wake. Navigate to your goal first; if coordination is "
            "rendezvous/relay, await_barrier after arriving; if relay and you are handoff_to, "
            "end with the handoff_task; if you are handoff_from, end with idle. Reply with a JSON list only.")
        resp = self._client.chat.completions.create(
            model=self._model, temperature=0,
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content":
                       f"robot_id: {robot_id}\nassignment: {json.dumps(assignment)}\n"
                       f"coordination: {json.dumps(coordination)}"}])
        txt = resp.choices[0].message.content.strip()
        if txt.startswith("```"):
            txt = txt.strip("`").split("\n", 1)[-1]
        return json.loads(txt)
