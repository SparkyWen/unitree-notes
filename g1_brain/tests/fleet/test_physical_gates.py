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
