import numpy as np
from g1_brain.fleet.sim.shared_world import SharedG1World
from g1_brain.fleet.sim.rl_adapter import SharedWorldController


def test_controller_produces_pd_targets():
    w = SharedG1World()
    ctl = SharedWorldController(w, "g1_a")
    ctl.set_command(0.0, 0.0, 0.0)
    q_target, kp, kd = ctl.compute()  # one tick of the reused ComboController
    assert q_target.shape == (29,) and kp.shape == (29,) and kd.shape == (29,)
    # during BOOT the reused controller blends toward default_q
    assert np.allclose(q_target, ctl.cfg.default_q, atol=0.3)
