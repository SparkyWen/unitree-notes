"""Physical gates for the shared-world RL locomotion (P1).

These are empirical run-and-observe tests, not cheap unit asserts. They step
real MuJoCo physics with the reused RL controller and assert the robots stay
upright / reach goals. Paced at ~50 Hz real time so the controller's
wall-clock POLICY_WARMUP_S completes (see rl_adapter)."""
import time

import pytest

from g1_brain.fleet.sim.shared_world import SharedG1World
from g1_brain.fleet.sim.rl_adapter import SharedWorldController
from g1_brain.fleet.sim.nav import nav_command


def _drive(world, ctls, secs, *, paced=True):
    nsub = max(1, int(round(0.02 / world.m.opt.timestep)))
    for _ in range(int(secs / 0.02)):
        t0 = time.perf_counter()
        for c in ctls:
            qt, kp, kd = c.compute()
            world.set_pd(c.rid, qt, kp, kd)
        world.step(nsub)
        if paced:
            slp = 0.02 - (time.perf_counter() - t0)
            if slp > 0:
                time.sleep(slp)


@pytest.mark.slow
def test_one_robot_stands_then_walks():
    w = SharedG1World()
    a = SharedWorldController(w, "g1_a")
    b = SharedWorldController(w, "g1_b")
    a.set_command(0.0, 0.0, 0.0)
    b.set_command(0.0, 0.0, 0.0)
    _drive(w, (a, b), 2.5)
    assert w.gravity_proj_z("g1_a") < -0.85, "g1_a fell while standing"
    assert w.gravity_proj_z("g1_b") < -0.85, "g1_b fell while standing"
    x0 = w.base_pose("g1_a")[0]
    a.set_command(0.6, 0.0, 0.0)
    _drive(w, (a, b), 3.5)
    assert w.gravity_proj_z("g1_a") < -0.7, "g1_a fell while walking"
    assert w.base_pose("g1_a")[0] - x0 > 0.3, "g1_a did not walk forward"


@pytest.mark.slow
def test_two_robots_rendezvous_no_collision():
    w = SharedG1World(spawn={"g1_a": (-1.5, 0.0), "g1_b": (1.5, 0.0)})
    a, b = SharedWorldController(w, "g1_a"), SharedWorldController(w, "g1_b")
    ctls = {"g1_a": a, "g1_b": b}
    goals = {"g1_a": (-0.4, 0.0), "g1_b": (0.4, 0.0)}  # adjacent, NOT overlapping
    nsub = max(1, int(round(0.02 / w.m.opt.timestep)))
    min_sep = 99.0
    for _ in range(int(11.0 / 0.02)):
        t0 = time.perf_counter()
        for rid, c in ctls.items():
            vx, vy, wz = nav_command(w.base_pose(rid), goals[rid], stop_radius=0.25)
            if w.neighbors(rid)[0]["dist"] < 0.5:   # simple avoidance
                vx, vy, wz = 0.0, 0.0, 0.0
            c.set_command(vx, vy, wz)
            qt, kp, kd = c.compute()
            w.set_pd(rid, qt, kp, kd)
        w.step(nsub)
        min_sep = min(min_sep, w.neighbors("g1_a")[0]["dist"])
        slp = 0.02 - (time.perf_counter() - t0)
        if slp > 0:
            time.sleep(slp)
    assert w.gravity_proj_z("g1_a") < -0.7 and w.gravity_proj_z("g1_b") < -0.7, "a robot fell"
    assert abs(w.base_pose("g1_a")[0] - (-0.4)) < 0.4, "g1_a missed its rendezvous point"
    assert abs(w.base_pose("g1_b")[0] - 0.4) < 0.4, "g1_b missed its rendezvous point"
    assert min_sep > 0.3, "robots collided"
