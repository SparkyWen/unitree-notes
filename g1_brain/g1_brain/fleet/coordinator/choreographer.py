"""Choreographer — free-form NL -> per-robot op sequences (the rich vocabulary).

The command center's simple grammar (FleetCommander: rendezvous/relay/patrol)
can't express "circle CW for 30 s, line up facing each other, raise arms". This
module adds that: a deterministic keyword choreographer (so the demo runs offline
and reliably) plus a codex path (CodexFleetLLM.plan_choreography emits op
sequences for arbitrary commands). plan_mission() routes a command:

  codex available -> let codex compose the ops (general NL control)
  else            -> deterministic choreography for circle/face/arms commands,
                     else fall back to the FleetCommander for plain rendezvous/relay.

Ops are validated against VALID_OPS + the known robot ids before anything runs."""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set

from g1_brain.fleet.coordinator.fleet_plan import (
    Coordination, FleetPlan, SubAgentOp)

log = logging.getLogger(__name__)

VALID_OPS = {"navigate", "await_barrier", "patrol", "idle", "sleep", "wake",
             "circle", "face", "arms_up", "hold"}

_CW = ("顺时针", "cw", "clockwise")
_CCW = ("逆时针", "ccw", "counter", "anticlock")
_CIRCLE = ("绕圈", "转圈", "走圈", "circle", "顺时针", "逆时针", "兜圈")
_ROW = ("横排", "并排", "一排", "一行", "排成", "站成", "row", "line up", "line-up")
_FACE = ("面对面", "面朝", "相对", "对视", "面向", "对着", "face each", "facing")
_ARMS = ("抬手", "举手", "抬起", "举起", "双手", "胳膊", "arms up", "raise arm",
         "raise both", "hands up", "举双手")

_ROW_HALF = 0.6      # half the side-by-side spacing for the row (m)
_ARMS_HOLD = 3.0     # seconds the arms_up op blocks before completing (arms keep up)


def parse_ops(raw: Dict[str, list], known_ids: Set[str]) -> Dict[str, List[SubAgentOp]]:
    """Validate a {robot_id: [{op,args}]} mapping into SubAgentOps. Raises
    ValueError on an unknown robot id or an op outside VALID_OPS."""
    out: Dict[str, List[SubAgentOp]] = {}
    for rid, ops in raw.items():
        if rid not in known_ids:
            raise ValueError(f"unknown robot {rid!r}")
        seq = []
        for o in ops or []:
            so = o if isinstance(o, SubAgentOp) else SubAgentOp.model_validate(o)
            if so.op not in VALID_OPS:
                raise ValueError(f"unknown op {so.op!r}")
            seq.append(so)
        out[rid] = seq
    return out


def _centroid(robots):
    if not robots:
        return (0.0, 0.0)
    return (sum(r["x"] for r in robots) / len(robots),
            sum(r["y"] for r in robots) / len(robots))


def _duration(text: str, default: float) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|s\b|sec|seconds?)", text)
    return float(m.group(1)) if m else default


def deterministic_choreography(nl: str, snapshot: dict) -> Optional[dict]:
    """Keyword choreographer. Returns {"summary", "ops"} or None if the command
    isn't a recognizable choreography (so the caller can fall back)."""
    text = nl.lower()
    want_circle = any(k in text for k in _CIRCLE)
    want_row = any(k in text for k in _ROW)
    want_face = any(k in text for k in _FACE)
    want_arms = any(k in text for k in _ARMS)
    if not (want_circle or want_face or want_arms):
        return None

    robots = sorted(snapshot.get("robots", []), key=lambda r: r["robot_id"])
    if len(robots) < 1:
        return None
    ids = [r["robot_id"] for r in robots]
    cx, cy = _centroid(robots)
    secs = _duration(text, 30.0)

    # row spots: spread the team along y at the centroid x, evenly around centre
    n = len(ids)
    spots = {rid: (cx, cy + (i - (n - 1) / 2.0) * (2 * _ROW_HALF))
             for i, rid in enumerate(ids)}
    # opposite circle directions; if the text names both, first id = cw
    has_cw, has_ccw = any(k in text for k in _CW), any(k in text for k in _CCW)
    base = "cw" if (has_cw and not has_ccw) or (has_cw and has_ccw) else "ccw"

    ops: Dict[str, List[SubAgentOp]] = {rid: [] for rid in ids}
    phases: List[str] = []
    if want_circle:
        phases.append("绕圈")
        for i, rid in enumerate(ids):
            d = base if i % 2 == 0 else ("ccw" if base == "cw" else "cw")
            ops[rid].append(SubAgentOp(op="circle", args={"dir": d, "seconds": secs}))
    if want_row or want_face:
        phases.append("列队" + ("面对面" if want_face else ""))
        for rid in ids:
            sx, sy = spots[rid]
            ops[rid].append(SubAgentOp(op="navigate", args={"x": sx, "y": sy}))
        if want_face:
            # each robot faces the team's mirror spot (the peer across the row)
            for i, rid in enumerate(ids):
                peer = ids[-1 - i]
                tx, ty = spots[peer]
                ops[rid].append(SubAgentOp(op="face", args={"x": tx, "y": ty}))
    if want_arms:
        phases.append("抬双手")
        for rid in ids:
            ops[rid].append(SubAgentOp(op="arms_up", args={"seconds": _ARMS_HOLD}))

    summary = " → ".join(phases) if phases else "编排动作"
    return {"summary": summary, "ops": ops}


def plan_mission(nl: str, snapshot: dict, *, llm=None, sub_llm=None) -> dict:
    """Route a command to per-robot ops. Returns
    {ok, plan(FleetPlan), ops({rid:[SubAgentOp]}), needs_clarification, reason}."""
    known = {r["robot_id"] for r in snapshot.get("robots", [])}

    # 1) codex composes the op sequences directly (general NL control)
    if llm is not None and hasattr(llm, "plan_choreography"):
        try:
            d = llm.plan_choreography(nl, snapshot)
            if d and d.get("ops"):
                ops = parse_ops(d["ops"], known)
                if any(ops.values()):
                    plan = FleetPlan(summary=d.get("summary", "编排动作"),
                                     coordination=Coordination(type="choreography"))
                    return {"ok": True, "plan": plan, "ops": ops,
                            "needs_clarification": None, "reason": None}
        except Exception:  # noqa: BLE001
            log.warning("codex choreography failed; deterministic fallback", exc_info=True)

    # 1.5) deterministic offline position parser (coords/landmark/relative/multi)
    #      — makes NL position control work WITHOUT codex.
    from g1_brain.fleet.coordinator.nl_position import parse_position_command
    pos = parse_position_command(nl, snapshot)
    if pos is not None and pos.get("ops"):
        try:
            ops = parse_ops(pos["ops"], known)
            if any(ops.values()):
                plan = FleetPlan(summary=pos["summary"],
                                 coordination=Coordination(type="navigate"))
                return {"ok": True, "plan": plan, "ops": ops,
                        "needs_clarification": None, "reason": None}
        except ValueError as e:
            return {"ok": False, "plan": None, "ops": {},
                    "needs_clarification": None, "reason": str(e)}

    # 2) deterministic choreography for circle/face/arms commands
    det = deterministic_choreography(nl, snapshot)
    if det is not None:
        try:
            ops = parse_ops(det["ops"], known)
            plan = FleetPlan(summary=det["summary"],
                             coordination=Coordination(type="choreography"))
            return {"ok": True, "plan": plan, "ops": ops,
                    "needs_clarification": None, "reason": None}
        except ValueError as e:
            return {"ok": False, "plan": None, "ops": {},
                    "needs_clarification": None, "reason": str(e)}

    # 3) fall back to the rendezvous/relay commander (unchanged behaviour)
    return _commander_mission(nl, snapshot, known, llm, sub_llm)


def _commander_mission(nl, snapshot, known, llm, sub_llm) -> dict:
    from g1_brain.fleet.coordinator.fleet_commander import FleetCommander
    from g1_brain.fleet.coordinator.robot_subagent import RobotSubAgent
    commander = FleetCommander(llm=llm)
    plan = commander.plan(nl, snapshot)
    if plan.needs_clarification:
        return {"ok": False, "plan": plan, "ops": {},
                "needs_clarification": plan.needs_clarification, "reason": None}
    ok, reason = commander.validate(plan, known)
    if not ok:
        return {"ok": False, "plan": plan, "ops": {},
                "needs_clarification": None, "reason": reason}
    ops = {a.robot_id: RobotSubAgent(a.robot_id, llm=sub_llm).plan_ops(a, plan.coordination)
           for a in plan.assignments}
    return {"ok": True, "plan": plan, "ops": ops,
            "needs_clarification": None, "reason": None}
