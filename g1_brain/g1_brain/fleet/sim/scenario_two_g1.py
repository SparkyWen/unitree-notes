"""Tier-2 verification: two real MuJoCo G1s under unified intelligent dispatch.

Runs entirely headless in one process: two independent MujocoG1 physics worlds,
each driven by a SimRobotHarness (fast/slow brain) over an in-process bus, with
the full coordinator dispatch brain. Demonstrates both:

  1. Autonomous: a battery overheat on the patrolling robot is perceived from
     real telemetry, the robot is safely put to sleep, and its task is
     reassigned to the healthy robot.
  2. Human command: an operator wakes the cooled robot and hands the task back.

Run:  conda run -n agi python -m g1_brain.fleet.sim.scenario_two_g1
Env:  MUJOCO_GL=egl (headless GL). Optional --scene, --inject-after.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Dict

from g1_brain.fleet.agent.motion.mujoco_backend import MujocoBackend
from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.fleet.agent.sim_harness import SimRobotHarness
from g1_brain.fleet.bus.loopback import LoopbackHub
from g1_brain.fleet.console.cli import format_status
from g1_brain.fleet.coordinator.agent_llm import CoordinatorAgent, StructuredOp
from g1_brain.fleet.coordinator.anomaly import AnomalyDetector
from g1_brain.fleet.coordinator.controller import DispatchController
from g1_brain.fleet.coordinator.dispatch import DispatchEngine
from g1_brain.fleet.coordinator.gateway import CommandGateway
from g1_brain.fleet.coordinator.lease import LeaseManager
from g1_brain.fleet.contracts.models import Mission, TaskSpec
from g1_brain.fleet.sim.mujoco_world import MujocoG1

# Workspace root = .../unitree-notes (parents: sim,fleet,pkg,repo,workspace).
_WORKSPACE = Path(__file__).resolve().parents[4]
_DEFAULT_SCENE = str(_WORKSPACE / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml")


def _telemetry(controller: DispatchController) -> str:
    robots = controller.registry.list_robots()
    return format_status(robots, {"robot_count": len(robots)}, controller.snapshot())


async def run(*, scene: str, robot_ids=("g1_a", "g1_b"), inject_after_s: float = 1.0,
              settle_s: float = 0.6, verbose: bool = True) -> Dict:
    def say(msg):
        if verbose:
            print(msg, flush=True)

    hub = LoopbackHub()
    gateway = CommandGateway(send_command=hub.send_command, event_log=hub.event_log)
    hub.admission_sink = gateway.record_admission
    harnesses: Dict[str, SimRobotHarness] = {}
    worlds: Dict[str, MujocoG1] = {}
    controller = DispatchController(
        registry=hub.registry, detector=AnomalyDetector(),
        engine=DispatchEngine(hub.registry), gateway=gateway, event_log=hub.event_log,
        lease=LeaseManager(), agent=CoordinatorAgent(),
        inject_hook=lambda rid, **kw: harnesses[rid].inject(**kw))

    agents = []
    say(f"[setup] loading two MuJoCo G1 worlds from {scene}")
    for rid in robot_ids:
        world = MujocoG1(scene)
        worlds[rid] = world
        backend = MujocoBackend(world, steps_per_tick=8)
        # Mild, clipped thermal gains: real MuJoCo holding torques are large
        # and saturate a few joints, so we clip tau and keep emergent heating
        # realistic (~25-40C). The deterministic overheat comes from inject(),
        # so only the targeted robot trips the anomaly threshold.
        harness = SimRobotHarness.from_backend(
            rid, backend, n_joints=world.nu,
            thermal_kwargs=dict(ambient_c=25.0, k=0.0003, cooling=0.5,
                                battery_alpha=0.5, tau_clip=40.0))
        harnesses[rid] = harness
        agent = RobotAgent(core=harness, bus=hub.client(), heartbeat_interval_s=0.03,
                           perception_interval_s=None, tick_interval_s=0.01)
        await agent.start()
        agents.append(agent)

    try:
        await asyncio.sleep(settle_s)  # let physics settle + heartbeats register
        say("[setup] both G1s standing in MuJoCo, telemetry flowing:\n" + _telemetry(controller))

        # --- assign a patrol mission ---
        say("\n[operator] dispatch patrol mission -> fleet")
        await controller.dispatch_mission(Mission(
            mission_id="m1", created_by="op:li", intent_text="patrol zone A",
            tasks=[TaskSpec(task_id="t1", type="patrol", required_capabilities=["patrol"])]))
        await asyncio.sleep(settle_s)
        holder = controller.engine.assignments["t1"]
        other = next(r for r in robot_ids if r != holder)
        say(f"[dispatch] {holder} assigned patrol t1; {other} available")

        # --- AUTONOMOUS: overheat -> safe sleep -> reassign ---
        await asyncio.sleep(inject_after_s)
        say(f"\n[fault] battery overheat injected on {holder} (75.0C)")
        controller.inject(holder, battery_temperature_c=75.0, fault="battery_hot")
        await asyncio.sleep(0.3)  # heartbeats carry the new temperature up
        hot_temp = controller.registry.latest_state(holder).core.battery.temperature_c
        say(f"[coordinator] perceived {holder} battery {hot_temp:.1f}C -> scanning")
        anomalies = await controller.tick()
        await asyncio.sleep(0.3)
        for a in anomalies:
            say(f"[coordinator] ANOMALY {a.robot_id} {a.kind} ({a.severity})")
        say(f"[coordinator] explain: " + controller.agent.explain(
            decision=f"sleep {holder}, reassign t1 -> {other}",
            evidence={"robot": holder, "battery_c": hot_temp, "candidate": other}))
        say("[result] after autonomous dispatch:\n" + _telemetry(controller))

        auto = {
            "holder": holder, "other": other,
            "holder_fsm": harnesses[holder].fsm.state.value,
            "holder_posture": harnesses[holder].backend.last_posture.value,
            "other_posture": harnesses[other].backend.last_posture.value,
            "reassigned_to": controller.engine.assignments.get("t1"),
            "holder_upright_gz": worlds[holder].gravity_proj_z(),
            "other_upright_gz": worlds[other].gravity_proj_z(),
        }

        # --- HUMAN COMMAND: wake the cooled robot, hand the task back ---
        say(f"\n[operator] (cool down) clear {holder} fault, then: wake {holder}; takeover {other}->{holder}")
        harnesses[holder].thermal.clear_injection()  # fault cleared -> health ok
        await asyncio.sleep(0.2)
        await controller.run_op(StructuredOp("wake", {"robot": holder}))
        await asyncio.sleep(0.3)
        await controller.run_op(StructuredOp("takeover", {"from": other, "to": holder}))
        await asyncio.sleep(0.3)
        say("[result] after human handoff:\n" + _telemetry(controller))

        human = {
            "holder_fsm_after_wake": harnesses[holder].fsm.state.value,
            "task_back_to": controller.engine.assignments.get("t1"),
            "holder_posture": harnesses[holder].backend.last_posture.value,
        }

        event_types = [e.type.value for e in hub.event_log.query(limit=5000)]
        return {"autonomous": auto, "human": human, "event_types": event_types}
    finally:
        for agent in agents:
            await agent.stop()


def _check(result: Dict) -> bool:
    a = result["autonomous"]
    h = result["human"]
    ok = True

    def need(cond, label):
        nonlocal ok
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {label}", flush=True)
        ok = ok and cond

    print("\n=== VERIFICATION ===", flush=True)
    need(a["holder_fsm"] == "DORMANT", f"overheated {a['holder']} put to sleep (DORMANT)")
    need(a["holder_posture"] == "SLEEP", f"{a['holder']} in SLEEP posture")
    need(a["reassigned_to"] == a["other"], f"task t1 reassigned to {a['other']}")
    need(a["other_posture"] == "PATROL", f"{a['other']} now patrolling")
    need(a["holder_upright_gz"] < -0.7 and a["other_upright_gz"] < -0.7,
         "both G1s upright in MuJoCo throughout")
    need(h["holder_fsm_after_wake"] == "STANDING", f"{a['holder']} woke on human command")
    need(h["task_back_to"] == a["holder"], "task handed back to original robot")
    need("anomaly_detected" in result["event_types"], "anomaly_detected event logged")
    need("task_reassigned" in result["event_types"], "task_reassigned event logged")
    need("robot_sleeping" in result["event_types"], "robot_sleeping event logged")
    print("=== {} ===".format("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"), flush=True)
    return ok


def main() -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default=_DEFAULT_SCENE)
    ap.add_argument("--inject-after", type=float, default=1.0)
    args = ap.parse_args()
    os.environ.setdefault("MUJOCO_GL", "egl")
    scene = args.scene if os.path.isabs(args.scene) else str((_WORKSPACE / args.scene).resolve())
    if not os.path.exists(scene):
        scene = str(Path(args.scene).resolve())
    result = asyncio.run(run(scene=scene, inject_after_s=args.inject_after))
    return 0 if _check(result) else 1


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
