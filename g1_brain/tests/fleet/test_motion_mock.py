"""MotionBackend protocol + the CI MockBackend."""
from g1_brain.fleet.agent.motion.base import MotionBackend, Posture
from g1_brain.fleet.agent.motion.mock import MockBackend


def test_posture_values():
    assert {p.value for p in Posture} >= {
        "ACTIVE", "PATROL", "SLEEP", "WAKE", "IDLE", "STOP"}


def test_mock_backend_is_a_motion_backend():
    b = MockBackend(n_joints=4)
    assert isinstance(b, MotionBackend)


def test_set_posture_records_and_affects_load():
    b = MockBackend(n_joints=4)
    b.set_posture(Posture.PATROL)
    b.step()
    patrol_tau = max(b.read_lowstate().tau_est())
    b.set_posture(Posture.SLEEP)
    b.step()
    sleep_tau = max(b.read_lowstate().tau_est())
    assert b.last_posture == Posture.SLEEP
    assert sleep_tau < patrol_tau  # a sleeping robot draws less effort


def test_read_lowstate_exposes_tau_and_gravity():
    b = MockBackend(n_joints=3)
    ls = b.read_lowstate()
    assert len(ls.tau_est()) == 3
    assert ls.gravity_proj_z <= -0.85  # upright by default


def test_set_load_override():
    b = MockBackend(n_joints=2)
    b.set_load(40.0)
    b.step()
    assert min(b.read_lowstate().tau_est()) >= 40.0
