"""Operator console: read fleet status + issue dispatch commands.

Pure formatting + thin HTTP calls (a future web UI replaces this; the API is
stable). Subcommands: status | dispatch | sleep | wake | takeover | inject |
explain.
"""
from __future__ import annotations

import argparse
import asyncio
from typing import List, Optional


# ---- pure helpers (unit-tested) ----

def build_command_body(op: str, *, robot: Optional[str] = None,
                       from_robot: Optional[str] = None, to_robot: Optional[str] = None,
                       task: Optional[str] = None, target: Optional[str] = None,
                       **extra) -> dict:
    """Build the JSON body for POST /commands for each operator op."""
    if op in ("sleep", "wake"):
        return {"op": op, "args": {"robot": robot}}
    if op == "takeover":
        return {"op": "takeover", "args": {"from": from_robot, "to": to_robot}}
    if op == "dispatch":
        return {"op": "dispatch", "args": {"task": task or "patrol",
                                           "target": target or "fleet"}}
    if op == "inject":
        body = {"op": "inject", "robot": robot}
        body.update(extra)  # e.g. battery_temperature_c=75.0, fault="battery_hot"
        return body
    if op == "status":
        return {"op": "status", "args": {}}
    return {"op": op, "args": extra}


def format_fleet(robots: List[dict], rollup: dict) -> str:
    lines = ["=== FLEET ==="]
    for r in robots:
        st = r.get("state") or {}
        core = st.get("core") or {}
        batt = core.get("battery") or {}
        temp = batt.get("temperature_c")
        soc = batt.get("soc")
        health = (core.get("health") or {}).get("level", "?")
        posture = ((st.get("extensions") or {}).get("g1_sim") or {}).get("posture", "-")
        temp_s = f"{temp:.0f}C" if isinstance(temp, (int, float)) else "?"
        soc_s = f"{soc*100:.0f}%" if isinstance(soc, (int, float)) else "?"
        lines.append(
            f"  {r.get('robot_id', '?'):<10} {r.get('status', '?'):<7} "
            f"fsm={st.get('fsm_state', '?'):<14} posture={posture:<7} "
            f"batt={temp_s:<5} soc={soc_s:<5} health={health}")
    lines.append("=== PERCEPTION ===")
    lines.append(f"  robots_reporting={rollup.get('robot_count', 0)} "
                 f"path_blocked={rollup.get('robots_path_blocked', 0)} "
                 f"with_humans={rollup.get('robots_with_humans', 0)}")
    return "\n".join(lines)


def format_status(robots: List[dict], rollup: dict, dispatch: dict) -> str:
    parts = [format_fleet(robots, rollup), "=== DISPATCH ==="]
    assignments = dispatch.get("assignments") or {}
    if assignments:
        for task_id, rid in assignments.items():
            parts.append(f"  task {task_id} -> {rid}")
    else:
        parts.append("  (no active assignments)")
    if dispatch.get("needs_operator"):
        parts.append(f"  NEEDS OPERATOR: {', '.join(dispatch['needs_operator'])}")
    anomalies = dispatch.get("anomalies") or []
    parts.append("=== ANOMALIES ===")
    if anomalies:
        for a in anomalies:
            ev = ", ".join(f"{k}={v}" for k, v in (a.get("evidence") or {}).items())
            parts.append(f"  [{a.get('severity', '?')}] {a.get('robot_id')} "
                         f"{a.get('kind')} ({ev})")
    else:
        parts.append("  (none)")
    leases = dispatch.get("leases") or []
    if leases:
        parts.append("=== LEASES ===")
        for l in leases:
            parts.append(f"  {l.get('lease_id')} -> {l.get('robot_id')}")
    return "\n".join(parts)


# ---- HTTP I/O ----

async def _get_status(base: str) -> str:
    import aiohttp
    async with aiohttp.ClientSession() as s:
        robots = await (await s.get(f"{base}/robots")).json()
        perc = await (await s.get(f"{base}/perception")).json()
        dispatch = await (await s.get(f"{base}/dispatch")).json()
    return format_status(robots, perc.get("rollup", {}), dispatch)


async def _post_command(base: str, body: dict) -> str:
    import aiohttp
    import json
    async with aiohttp.ClientSession() as s:
        resp = await s.post(f"{base}/commands", json=body)
        return json.dumps(await resp.json(), ensure_ascii=False, indent=2)


def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser(description="Fleet coordinator console")
    ap.add_argument("--base", default="http://127.0.0.1:8090")
    sub = ap.add_subparsers(dest="cmd", required=False)
    sub.add_parser("status")
    p = sub.add_parser("dispatch"); p.add_argument("task", nargs="?", default="patrol")
    p = sub.add_parser("sleep"); p.add_argument("robot")
    p = sub.add_parser("wake"); p.add_argument("robot")
    p = sub.add_parser("takeover"); p.add_argument("from_robot"); p.add_argument("to_robot")
    p = sub.add_parser("inject"); p.add_argument("robot")
    p.add_argument("--temp", type=float, default=75.0)
    p.add_argument("--fault", default="battery_hot")
    args = ap.parse_args()

    if args.cmd in (None, "status"):
        print(asyncio.run(_get_status(args.base)))
        return
    if args.cmd == "dispatch":
        body = build_command_body("dispatch", task=args.task)
    elif args.cmd in ("sleep", "wake"):
        body = build_command_body(args.cmd, robot=args.robot)
    elif args.cmd == "takeover":
        body = build_command_body("takeover", from_robot=args.from_robot, to_robot=args.to_robot)
    elif args.cmd == "inject":
        body = build_command_body("inject", robot=args.robot,
                                  battery_temperature_c=args.temp, fault=args.fault)
    else:
        ap.error(f"unknown command {args.cmd}")
        return
    print(asyncio.run(_post_command(args.base, body)))


if __name__ == "__main__":  # pragma: no cover
    main()
