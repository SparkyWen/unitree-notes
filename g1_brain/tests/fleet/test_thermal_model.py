"""tau-driven thermal/battery model with a deterministic injection hook."""
from g1_brain.fleet.agent.thermal_model import ThermalModel


def test_load_raises_temp():
    tm = ThermalModel(n_joints=4, ambient_c=25.0, k=0.5, cooling=0.1)
    for _ in range(50):
        tm.update(tau=[10.0] * 4, dt=0.1)
    s = tm.snapshot()
    assert s.hottest_motor_c > 25.0
    assert s.battery_temperature_c > 25.0
    assert 0 <= s.hottest_motor_idx < 4


def test_cooling_decays_temp():
    tm = ThermalModel(n_joints=2, ambient_c=25.0, k=0.5, cooling=0.5)
    for _ in range(20):
        tm.update(tau=[20.0] * 2, dt=0.1)
    hot = tm.snapshot().hottest_motor_c
    for _ in range(400):
        tm.update(tau=[0.0] * 2, dt=0.1)
    assert tm.snapshot().hottest_motor_c < hot


def test_soc_drains_under_load():
    tm = ThermalModel(n_joints=2, ambient_c=25.0)
    start = tm.snapshot().soc
    for _ in range(100):
        tm.update(tau=[15.0] * 2, dt=0.1)
    assert tm.snapshot().soc < start


def test_inject_overrides_and_is_sticky():
    tm = ThermalModel(n_joints=2)
    tm.inject(battery_temperature_c=75.0, soc=0.3, fault="battery_hot")
    s = tm.snapshot()
    assert s.battery_temperature_c == 75.0
    assert s.soc == 0.3
    assert "battery_hot" in s.faults
    # sticky: survives further physics updates (the robot "is" overheating)
    for _ in range(10):
        tm.update(tau=[0.0] * 2, dt=0.1)
    assert tm.snapshot().battery_temperature_c == 75.0


def test_clear_injection_restores_model():
    tm = ThermalModel(n_joints=2, ambient_c=25.0)
    tm.inject(battery_temperature_c=75.0)
    assert tm.snapshot().battery_temperature_c == 75.0
    tm.clear_injection()
    assert tm.snapshot().battery_temperature_c < 75.0
