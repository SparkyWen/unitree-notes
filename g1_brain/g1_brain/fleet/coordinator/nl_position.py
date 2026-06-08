"""Deterministic offline NL -> position parser. Lets the command center drive
robot positions WITHOUT codex: absolute coords, named landmarks, relative moves,
and multi-robot ("all") targeting. Returns navigate ops or None if the command
isn't a position command (so plan_mission can fall through to choreography /
the commander). Choreography verbs (circle/face/arms) are deliberately NOT
handled here -> returns None so they reach the choreographer."""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

from g1_brain.fleet.coordinator.fleet_plan import SubAgentOp
from g1_brain.fleet.sim.scene import resolve_landmark

_RID_RE = re.compile(r"(g1_[a-z])", re.I)
_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[,，\s]\s*(-?\d+(?:\.\d+)?)")
_DIST_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:米|m\b|metre|meter)")
_FWD = ("前进", "向前", "forward", "advance")
_BACK = ("后退", "向后", "backward", "retreat")
_ALL = ("两机", "所有", "都去", "全部", "all ", "both", "everyone")
_CHOREO = ("绕圈", "转圈", "走圈", "circle", "面对面", "面朝", "对视", "face",
           "抬手", "举手", "双手", "arms", "hands up", "排成", "列队")


def parse_position_command(nl: str, snapshot: dict) -> Optional[dict]:
    text = (nl or "").strip()
    if not text:
        return None
    low = text.lower()
    if any(k in low for k in _CHOREO):
        return None

    robots = snapshot.get("robots", [])
    ids = [r["robot_id"] for r in robots]
    if not ids:
        return None
    pose = {r["robot_id"]: (float(r.get("x", 0.0)), float(r.get("y", 0.0)),
                            float(r.get("yaw", 0.0))) for r in robots}
    landmarks = snapshot.get("landmarks", {}) or {}

    lid = {i.lower(): i for i in ids}
    named = [lid[m.lower()] for m in _RID_RE.findall(text) if m.lower() in lid]
    if any(k in low for k in _ALL):
        targets = list(ids)
    elif named:
        targets = named
    elif len(ids) == 1:
        targets = list(ids)
    else:
        return None

    if not targets:
        return None

    if any(k in low for k in _FWD + _BACK):
        m = _DIST_RE.search(low)
        d = float(m.group(1)) if m else 1.0
        sign = -1.0 if any(k in low for k in _BACK) else 1.0
        ops: Dict[str, List[SubAgentOp]] = {}
        for rid in targets:
            px, py, yaw = pose[rid]
            gx = round(px + sign * d * math.cos(yaw), 3)
            gy = round(py + sign * d * math.sin(yaw), 3)
            ops[rid] = [SubAgentOp(op="navigate", args={"x": gx, "y": gy})]
        return {"summary": f"相对移动 {sign * d:+.1f}m", "ops": ops}

    goal = resolve_landmark(landmarks, text)
    if goal is None:
        mm = _COORD_RE.search(text)
        if mm:
            goal = (float(mm.group(1)), float(mm.group(2)))
    if goal is None:
        return None
    gx, gy = goal
    ops = {rid: [SubAgentOp(op="navigate", args={"x": gx, "y": gy})]
           for rid in targets}
    return {"summary": f"前往 ({gx:.1f}, {gy:.1f})", "ops": ops}
