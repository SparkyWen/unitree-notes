from g1_brain.fleet.sim.shared_world import SharedG1World
from g1_brain.fleet.agent.motion.rl_shared_backend import RlSharedBackend
from g1_brain.fleet.agent.motion.base import Posture, MotionBackend


def test_is_motion_backend():
    w = SharedG1World()
    be = RlSharedBackend(w, "g1_a")
    assert isinstance(be, MotionBackend)


def test_nav_goal_sets_walk():
    w = SharedG1World()
    be = RlSharedBackend(w, "g1_a")
    be.set_nav_goal(5.0, 0.0)  # far -> should command a walk
    be.step()
    assert be.last_posture in (Posture.WALK, Posture.ACTIVE)
    ls = be.read_lowstate()
    assert len(ls.tau_est()) == 29


def test_patrol_issues_walk_command_idle_stops():
    import numpy as np
    w = SharedG1World()
    be = RlSharedBackend(w, "g1_a")
    be.set_posture(Posture.PATROL)
    be.step()
    assert np.linalg.norm(be.ctl.ctl.get_command()) > 0.1   # patrolling = moving
    be.set_posture(Posture.IDLE)
    be.step()
    assert np.linalg.norm(be.ctl.ctl.get_command()) < 1e-6   # idle = stopped
