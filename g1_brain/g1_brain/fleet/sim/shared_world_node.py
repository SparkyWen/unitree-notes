"""World Sim: shared MjModel + two RL backends @50 Hz in a dedicated thread,
optional passive viewer. Exposes thread-safe set_nav_goal/set_posture and a
telemetry snapshot. No LLM/HTTP here (the 50 Hz control must not be starved).

  # headless smoke (both walk to the centre, print telemetry):
  conda run -n agi python -m g1_brain.fleet.sim.shared_world_node --seconds 8
  # visual (one window, two G1s meet in the middle):
  conda run -n agi python -m g1_brain.fleet.sim.shared_world_node --viewer
"""
from __future__ import annotations

import argparse
import os
import threading
import time
from typing import Dict

from g1_brain.fleet.sim.shared_world import SharedG1World
from g1_brain.fleet.agent.motion.rl_shared_backend import RlSharedBackend
from g1_brain.fleet.agent.motion.base import Posture


class WorldSim:
    def __init__(self, robot_ids=("g1_a", "g1_b"),
                 spawn=None):
        self.world = SharedG1World(robot_ids=robot_ids, spawn=spawn)
        self.backends: Dict[str, RlSharedBackend] = {
            rid: RlSharedBackend(self.world, rid) for rid in robot_ids}
        self._lock = threading.Lock()
        self._run = False
        self._phys_per_tick = max(1, int(round(0.02 / self.world.m.opt.timestep)))

    def set_nav_goal(self, rid, x, y):
        with self._lock:
            self.backends[rid].set_nav_goal(x, y)

    def set_posture(self, rid, posture: Posture):
        with self._lock:
            self.backends[rid].set_posture(posture)

    def telemetry(self) -> dict:
        with self._lock:
            return {rid: {"pose": self.world.base_pose(rid),
                          "gz": self.world.gravity_proj_z(rid),
                          "neighbors": self.world.neighbors(rid),
                          "posture": be.last_posture.value}
                    for rid, be in self.backends.items()}

    def _control_loop(self):
        dt = 0.02
        while self._run:
            t0 = time.perf_counter()
            with self._lock:
                for be in self.backends.values():
                    be.step()
                self.world.step(self._phys_per_tick)
            slp = dt - (time.perf_counter() - t0)
            if slp > 0:
                time.sleep(slp)

    def start(self):
        self._run = True
        self._t = threading.Thread(target=self._control_loop, daemon=True)
        self._t.start()

    def stop(self):
        self._run = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--viewer", action="store_true")
    ap.add_argument("--seconds", type=float, default=8.0, help="headless run length")
    args = ap.parse_args()
    sim = WorldSim()
    sim.start()
    # demo motion: send both toward the centre so you SEE them meet
    sim.set_nav_goal("g1_a", -0.4, 0.0)
    sim.set_nav_goal("g1_b", 0.4, 0.0)
    if args.viewer:
        os.environ.setdefault("MUJOCO_GL", "glfw")
        import mujoco
        import mujoco.viewer
        with mujoco.viewer.launch_passive(sim.world.m, sim.world.d) as v:
            # cut render cost (per memory: mujoco_viewer_perf / wsl2_gpu_rendering)
            v.opt.flags[mujoco.mjtVisFlag.mjVIS_SHADOW] = False
            v.opt.flags[mujoco.mjtVisFlag.mjVIS_REFLECTION] = False
            while v.is_running():
                v.sync()
                time.sleep(1 / 60)
    else:
        end = time.time() + args.seconds
        while time.time() < end:
            time.sleep(0.5)
        tel = sim.telemetry()
        for rid, t in tel.items():
            px, py, yaw = t["pose"]
            print(f"  {rid}: pose=({px:+.2f},{py:+.2f}) gz={t['gz']:+.3f} "
                  f"posture={t['posture']} sep={t['neighbors'][0]['dist']:.2f}", flush=True)
    sim.stop()


if __name__ == "__main__":
    main()
