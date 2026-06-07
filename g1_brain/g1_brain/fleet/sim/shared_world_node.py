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


def trim_render_cost(m) -> None:
    """Make the passive viewer cheap on WSL2/llvmpipe (memory: mujoco_viewer_perf).

    Render-only — never touches physics. The big per-frame win here is killing
    MSAA (offsamples 4 -> 0); shadow/reflection passes are also disabled at the
    *model* level (the proper levers — `mjtVisFlag.mjVIS_SHADOW`/`mjVIS_REFLECTION`
    do NOT exist; those are `mjtRndFlag` render flags, which is what crashed the
    old code). Shadow/reflection trims are no-ops while the shared world has no
    lights/materials, but stay correct if any are added later. Call BEFORE
    launch_passive so the GL context is built without MSAA."""
    m.vis.quality.offsamples = 0      # MSAA 4x -> off: the real cost on llvmpipe
    m.vis.quality.shadowsize = 0      # don't allocate a shadow map
    if m.nlight:
        m.light_castshadow[:] = 0     # no light casts a shadow -> no shadow pass
    if m.nmat:
        m.mat_reflectance[:] = 0      # no mirror floor/material reflections


class WorldSim:
    def __init__(self, robot_ids=("g1_a", "g1_b"),
                 spawn=None):
        self.world = SharedG1World(robot_ids=robot_ids, spawn=spawn)
        self.backends: Dict[str, RlSharedBackend] = {
            rid: RlSharedBackend(self.world, rid) for rid in robot_ids}
        self._lock = threading.Lock()
        self._run = False
        self._render_lock = None
        self._phys_per_tick = max(1, int(round(0.02 / self.world.m.opt.timestep)))

    def set_render_lock(self, lock) -> None:
        """Serialize physics stepping with an external mutex. Pass a passive
        MuJoCo viewer's ``viewer.lock()`` so the viewer can copy mjData for
        rendering without racing ``mj_step`` (otherwise: 'mj_copyDataVisual:
        attempting to copy mjData while stack is in use'). Set this BEFORE
        start() — and only start the control loop once the viewer exists — so
        the loop never steps unguarded while the viewer is reading mjData."""
        self._render_lock = lock

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

    def _step_once(self):
        with self._lock:
            for be in self.backends.values():
                be.step()
            self.world.step(self._phys_per_tick)

    def _control_loop(self):
        dt = 0.02
        while self._run:
            t0 = time.perf_counter()
            rl = self._render_lock
            if rl is not None:
                # hold the viewer's mutex across the step so its render-thread
                # mjData copy can't land mid-mj_step ("stack is in use").
                with rl:
                    self._step_once()
            else:
                self._step_once()
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
    sim = WorldSim()  # control loop started below (after the viewer, if any)
    if args.viewer:
        os.environ.setdefault("MUJOCO_GL", "glfw")
        import mujoco
        import mujoco.viewer
        trim_render_cost(sim.world.m)  # cut render cost BEFORE the GL context is built
        with mujoco.viewer.launch_passive(sim.world.m, sim.world.d) as v:
            # step physics under the viewer's lock, started only after the viewer
            # exists, so its render-thread mjData copy never races mj_step.
            sim.set_render_lock(v.lock())
            sim.start()
            sim.set_nav_goal("g1_a", -0.4, 0.0)  # send both toward the centre
            sim.set_nav_goal("g1_b", 0.4, 0.0)
            while v.is_running():
                v.sync()
                time.sleep(1 / 60)
    else:
        sim.start()
        sim.set_nav_goal("g1_a", -0.4, 0.0)  # send both toward the centre so you SEE them meet
        sim.set_nav_goal("g1_b", 0.4, 0.0)
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
