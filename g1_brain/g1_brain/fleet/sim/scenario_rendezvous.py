"""P3 capstone — rendezvous / relay cooperation demo, end to end.

Ties P1 (shared-world two RL G1s) + P2 (OpenAI hierarchical dispatch) together:
an operator NL command is decomposed by the FleetCommander into a multi-robot
plan, each robot's RobotSubAgent emits an op sequence, and a deterministic
RendezvousBarrier sequences the cooperation while a small executor drives the
live WorldSim. Both robots walk to the meeting point; once both have arrived the
barrier releases and the patrol task is handed off (receiver patrols, hander
idles).

  # headless verification (CI):
  conda run -n agi python -m g1_brain.fleet.sim.scenario_rendezvous
  # watch it in one MuJoCo window:
  conda run -n agi python -m g1_brain.fleet.sim.scenario_rendezvous --viewer

Runs with NO OpenAI key (deterministic planner). Set OPENAI_API_KEY to route
planning through the LLM (same op grammar, validated identically)."""
from __future__ import annotations

import argparse
import math
import os
import sys
import threading
import time
from typing import Optional

from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.coordinator.barrier import RendezvousBarrier
from g1_brain.fleet.coordinator.fleet_commander import FleetCommander
from g1_brain.fleet.coordinator.robot_subagent import RobotSubAgent
from g1_brain.fleet.sim.shared_world_node import WorldSim, trim_render_cost

_DEFAULT_NL = "让 g1_a 和 g1_b 到中间会合，然后 g1_a 把巡逻交给 g1_b"


def _snapshot(sim: WorldSim) -> dict:
    tel = sim.telemetry()
    return {"robots": [{"robot_id": rid, "x": t["pose"][0], "y": t["pose"][1]}
                       for rid, t in tel.items()]}


def orchestrate(sim: WorldSim, nl: str, *, llm=None, timeout_s: float = 22.0,
                patrol_s: float = 5.0, log=print) -> dict:
    commander = FleetCommander(llm=llm)
    plan = commander.plan(nl, _snapshot(sim))
    if plan.needs_clarification:
        log(f"[commander] needs clarification: {plan.needs_clarification}")
        return {"ok": False, "needs_clarification": plan.needs_clarification}
    c = plan.coordination
    log(f"[commander] {plan.summary} [{c.type}] handoff {c.handoff_from} -> {c.handoff_to}")
    subagents = {a.robot_id: RobotSubAgent(a.robot_id, llm=llm) for a in plan.assignments}
    ops = {a.robot_id: subagents[a.robot_id].plan_ops(a, c) for a in plan.assignments}
    for rid, ol in ops.items():
        log(f"[subagent {rid}] " + " -> ".join(o.op for o in ol))

    barrier = RendezvousBarrier(set(ops), point=c.point, radius=0.7)
    ptr = {rid: 0 for rid in ops}
    start_pose = {}
    events = []
    barrier_fired = False
    min_sep = 99.0

    def done():
        return all(ptr[r] >= len(ops[r]) for r in ops)

    t0 = time.time()
    while not done() and time.time() - t0 < timeout_s:
        tel = sim.telemetry()
        for rid in ops:
            min_sep = min(min_sep, tel[rid]["neighbors"][0]["dist"]) if tel[rid]["neighbors"] else min_sep
            if ptr[rid] >= len(ops[rid]):
                continue
            op = ops[rid][ptr[rid]]
            px, py, _ = tel[rid]["pose"]
            if op.op == "navigate":
                gx, gy = op.args["x"], op.args["y"]
                sim.set_nav_goal(rid, gx, gy)
                if math.hypot(px - gx, py - gy) < 0.45:
                    ptr[rid] += 1
                    events.append(f"{rid} arrived")
            elif op.op == "await_barrier":
                barrier.update_position(rid, (px, py))
                if barrier.is_released():
                    if not barrier_fired:
                        barrier_fired = True
                        events.append("barrier released — both at rendezvous")
                    ptr[rid] += 1
            elif op.op == "patrol":
                sim.set_posture(rid, Posture.PATROL)
                start_pose[rid] = (px, py)
                ptr[rid] += 1
                events.append(f"{rid} picks up patrol")
            elif op.op == "idle":
                sim.set_posture(rid, Posture.IDLE)
                ptr[rid] += 1
                events.append(f"{rid} idle (handed off)")
            else:
                ptr[rid] += 1
        time.sleep(0.05)

    # let the handoff play out (receiver patrols, hander idles)
    pend = time.time() + patrol_s
    while time.time() < pend:
        tel = sim.telemetry()
        for rid in ops:
            if tel[rid]["neighbors"]:
                min_sep = min(min_sep, tel[rid]["neighbors"][0]["dist"])
        time.sleep(0.05)

    tel = sim.telemetry()
    to, frm = c.handoff_to, c.handoff_from
    result = {
        "ok": True, "plan_type": c.type, "handoff_from": frm, "handoff_to": to,
        "barrier_fired": barrier_fired, "completed": done(), "events": events,
        "upright": all(tel[r]["gz"] < -0.7 for r in ops),
        "min_sep": min_sep,
    }
    if to:
        bx, by, _ = tel[to]["pose"]
        sx, sy = start_pose.get(to, (bx, by))
        result["receiver_posture"] = tel[to]["posture"]
        result["receiver_moved"] = math.hypot(bx - sx, by - sy)
    if frm:
        result["hander_posture"] = tel[frm]["posture"]
    return result


def run(nl: str = _DEFAULT_NL, *, viewer: bool = False, llm=None) -> dict:
    sim = WorldSim()  # control loop started below (after the viewer, if any)
    try:
        if not viewer:
            sim.start()
            return orchestrate(sim, nl, llm=llm)
        os.environ.setdefault("MUJOCO_GL", "glfw")
        import mujoco
        import mujoco.viewer
        trim_render_cost(sim.world.m)  # cut render cost BEFORE the GL context is built
        box: dict = {}
        with mujoco.viewer.launch_passive(sim.world.m, sim.world.d) as v:
            # step physics under the viewer's lock, started only after the viewer
            # exists, so its render-thread mjData copy never races mj_step.
            sim.set_render_lock(v.lock())
            sim.start()
            th = threading.Thread(target=lambda: box.update(orchestrate(sim, nl, llm=llm)),
                                  daemon=True)
            th.start()
            while v.is_running():
                v.sync()
                time.sleep(1 / 60)
        return box
    finally:
        sim.stop()


def _check(r: dict) -> bool:
    ok = True

    def need(cond, label):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}", flush=True)
        ok = ok and bool(cond)

    print("\n=== VERIFICATION (rendezvous / relay) ===", flush=True)
    need(r.get("ok"), "commander produced a plan (no clarification needed)")
    need(r.get("plan_type") == "relay", "coordination type = relay")
    need(r.get("barrier_fired"), "rendezvous barrier fired (both arrived)")
    need(r.get("completed"), "all sub-agent op sequences completed")
    need(r.get("upright"), "both robots upright throughout")
    need(r.get("receiver_posture") == "PATROL",
         f"{r.get('handoff_to')} patrolling after handoff")
    need(r.get("receiver_moved", 0) > 0.12,
         f"{r.get('handoff_to')} actually moving on patrol")
    need(r.get("hander_posture") == "IDLE",
         f"{r.get('handoff_from')} idle after handing off")
    need(r.get("min_sep", 9) > 0.3, "no collision (min separation > 0.3 m)")
    print("=== {} ===".format("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"), flush=True)
    return ok


def main() -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--viewer", action="store_true")
    ap.add_argument("--nl", default=_DEFAULT_NL)
    args = ap.parse_args()
    result = run(args.nl, viewer=args.viewer)
    if args.viewer:
        return 0
    for e in result.get("events", []):
        print(f"  · {e}", flush=True)
    return 0 if _check(result) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
