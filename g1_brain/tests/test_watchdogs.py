"""Tests for WatchdogManager auto-recovery / re-arm behavior.

Specifically verifies the regression fix for the 2026-05-05 ENGAGED <->
EMERGENCY_STOP flap loop: after RECOVERING -> STANDING, the boot-grace
window must be re-armed so the policy's first ~1s of unstable settling
does not immediately re-promote us back to EMERGENCY_STOP.
"""
from __future__ import annotations

import time

import pytest

from g1_brain.safety.state_machine import RobotFsm, RobotFsmState
from g1_brain.safety.watchdogs import WatchdogManager
from g1_brain.scene_state.fusion import RobotStateBus, SceneStateBus


def _make_wd(boot_grace_s: float = 5.0):
    fsm = RobotFsm()
    wd = WatchdogManager(
        cfg={"safety": {"watchdog": {"boot_grace_s": boot_grace_s}}},
        scene_bus=SceneStateBus(),
        robot_bus=RobotStateBus(),
        fsm=fsm,
        combo_ctl=None,
        supervisor=None,
    )
    return fsm, wd


def test_recovery_to_standing_rearms_boot_grace():
    fsm, wd = _make_wd(boot_grace_s=5.0)
    fsm.transition(RobotFsmState.STANDING, "boot")
    fsm.transition(RobotFsmState.ENGAGED, "policy active")
    fsm.transition(RobotFsmState.EMERGENCY_STOP, "simulated fall")
    wd.start()
    try:
        # Simulate enough wall-clock time that the original boot grace would
        # have already expired if not re-armed.
        original_started_at = wd._started_at
        time.sleep(0.05)  # tiny but >0
        fsm.transition(RobotFsmState.RECOVERING, "watchdogs clear")
        fsm.transition(RobotFsmState.STANDING, "auto-recovery complete")
        # The transition listener must have bumped _started_at forward.
        assert wd._started_at > original_started_at
        # And we must be back inside the boot-grace window.
        assert wd._in_boot_grace(time.monotonic())
    finally:
        wd.stop()


def test_other_transitions_do_not_rearm_grace():
    """Only the specific RECOVERING -> STANDING edge re-arms the grace window."""
    fsm, wd = _make_wd(boot_grace_s=5.0)
    fsm.transition(RobotFsmState.STANDING, "boot")
    wd.start()
    try:
        snapshot = wd._started_at
        # STANDING -> ENGAGED: ordinary engagement, must NOT re-arm.
        fsm.transition(RobotFsmState.ENGAGED, "policy active")
        assert wd._started_at == snapshot
        # ENGAGED -> EMERGENCY_STOP: must NOT re-arm.
        fsm.transition(RobotFsmState.EMERGENCY_STOP, "fall")
        assert wd._started_at == snapshot
        # EMERGENCY_STOP -> RECOVERING: must NOT re-arm yet.
        fsm.transition(RobotFsmState.RECOVERING, "clear")
        assert wd._started_at == snapshot
        # Only RECOVERING -> STANDING re-arms.
        fsm.transition(RobotFsmState.STANDING, "auto-recovery complete")
        assert wd._started_at > snapshot
    finally:
        wd.stop()


def test_unsubscribe_on_stop():
    """stop() must detach the FSM subscriber so a stopped watchdog
    cannot still mutate _started_at on background transitions."""
    fsm, wd = _make_wd(boot_grace_s=5.0)
    fsm.transition(RobotFsmState.STANDING, "boot")
    wd.start()
    wd.stop()
    snapshot = wd._started_at
    # Run RECOVERING -> STANDING through the FSM after stop(); subscriber
    # should be detached, so _started_at must not change.
    fsm.transition(RobotFsmState.ENGAGED, "x")
    fsm.transition(RobotFsmState.EMERGENCY_STOP, "x")
    fsm.transition(RobotFsmState.RECOVERING, "x")
    fsm.transition(RobotFsmState.STANDING, "x")
    assert wd._started_at == snapshot


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
