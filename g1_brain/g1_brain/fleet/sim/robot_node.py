"""Headless robot node — one G1's fast/slow brain bridged to a unitree_mujoco
sim (over DDS) and to the coordinator (over WebSocket).

One process per robot (one DDS domain per process). It does NOT step physics —
the sim process does. It reads rt/lowstate (real tau -> thermal model), sends
rt/lowcmd (posture -> PD targets via the AdmissionGate/LocalPlanner), and
reports/accepts commands to/from the coordinator.

  python -m g1_brain.fleet.sim.robot_node --robot-id g1_a --domain 1 \
      --coordinator ws://127.0.0.1:8090/fleet [--inject-overheat-after 8]
"""
from __future__ import annotations

import argparse
import asyncio

from g1_brain.fleet.agent.motion.dds_backend import DdsMujocoBackend
from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.fleet.agent.sim_harness import SimRobotHarness
from g1_brain.fleet.bus.ws_client import WsFleetClient

_THERMAL = dict(ambient_c=25.0, k=0.0003, cooling=0.5, battery_alpha=0.5, tau_clip=40.0)


async def run(*, robot_id: str, domain: int, interface: str, coordinator: str,
              inject_after: float, tick_interval: float) -> None:
    backend = DdsMujocoBackend(domain_id=domain, interface=interface, n_joints=29)
    harness = SimRobotHarness.from_backend(robot_id, backend, n_joints=29,
                                           thermal_kwargs=dict(_THERMAL))
    bus = WsFleetClient(url=coordinator)
    agent = RobotAgent(core=harness, bus=bus, heartbeat_interval_s=0.5,
                       perception_interval_s=None, tick_interval_s=tick_interval)
    await agent.start()
    print(f"[robot_node] {robot_id} domain={domain} -> {coordinator}", flush=True)

    if inject_after and inject_after > 0:
        async def _inject():
            await asyncio.sleep(inject_after)
            harness.inject(battery_temperature_c=75.0, fault="battery_hot")
            print(f"[robot_node] {robot_id} self-injected battery overheat 75C", flush=True)
        asyncio.create_task(_inject())

    try:
        await asyncio.Event().wait()  # run until killed
    finally:
        await agent.stop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--robot-id", required=True)
    ap.add_argument("--domain", type=int, required=True)
    ap.add_argument("--interface", default="lo")
    ap.add_argument("--coordinator", default="ws://127.0.0.1:8090/fleet")
    ap.add_argument("--inject-overheat-after", type=float, default=0.0)
    ap.add_argument("--tick-interval", type=float, default=0.05)
    args = ap.parse_args()
    try:
        asyncio.run(run(robot_id=args.robot_id, domain=args.domain,
                        interface=args.interface, coordinator=args.coordinator,
                        inject_after=args.inject_overheat_after,
                        tick_interval=args.tick_interval))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
