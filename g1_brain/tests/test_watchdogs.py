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


class _CaptureSupervisor:
    """Records calls to set_watchdog_trip so we can assert on them."""

    def __init__(self) -> None:
        self.trips: dict = {}

    def set_watchdog_trip(self, name: str, reason):
        if reason is None:
            self.trips.pop(name, None)
        else:
            self.trips[name] = reason


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


def test_informational_trip_does_not_propagate_to_supervisor():
    """Regression: a tripped usb_frame watchdog must NOT push a flag to the
    supervisor (which would block ALL motion calls).

    usb_frame gates only the laptop webcam used to detect the *user's*
    gestures for mock_imitate auto-trigger. Losing it should not prevent
    the robot from waving, walking, or otherwise responding to direct
    voice commands. Before this fix, a missing teleimager turned every
    motion call into "watchdog tripped: usb_frame=age=infs".
    """
    fsm = RobotFsm()
    sup = _CaptureSupervisor()
    wd = WatchdogManager(
        cfg={"safety": {"watchdog": {"boot_grace_s": 0.0}}},
        scene_bus=SceneStateBus(),
        robot_bus=RobotStateBus(),
        fsm=fsm,
        combo_ctl=None,
        supervisor=sup,
    )
    # Trip the informational watchdog directly (no thread needed).
    wd._set_trip("usb_frame", "age=infs", emergency=False)
    assert "usb_frame" not in sup.trips, (
        "informational trip leaked into supervisor; this would block motion"
    )
    # Sanity: emergency-class trips must still propagate.
    wd._set_trip("lowstate", "age=1.5s", emergency=True)
    assert "lowstate" in sup.trips


def test_emergency_clear_propagates_to_supervisor():
    """Even after an emergency-class trip is cleared, the supervisor flag
    must drop too; otherwise motion would stay blocked indefinitely."""
    fsm = RobotFsm()
    sup = _CaptureSupervisor()
    wd = WatchdogManager(
        cfg={"safety": {"watchdog": {"boot_grace_s": 0.0}}},
        scene_bus=SceneStateBus(),
        robot_bus=RobotStateBus(),
        fsm=fsm,
        combo_ctl=None,
        supervisor=sup,
    )
    wd._set_trip("lowstate", "age=1.5s", emergency=True)
    wd._clear_trip("lowstate")
    assert "lowstate" not in sup.trips


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


def test_head_frame_inf_age_does_not_emergency():
    """Regression: head_frame watchdog must NOT promote to EMERGENCY_STOP
    while the camera is still warming up (age == inf, no frame ever seen).

    Production logs (2026-05-06) show MuJoCo head camera + perception
    pipeline take ~30 s to produce the first frame, while boot_grace_s is
    only 5 s. Before this fix, head_frame promoted at t≈boot_grace+head_max_age
    and the FSM stayed in EMERGENCY_STOP for ~25 s of pure startup transient
    — flapping ENGAGED <-> EMERGENCY_STOP for no actual safety benefit.
    """
    fsm = RobotFsm()
    sup = _CaptureSupervisor()
    wd = WatchdogManager(
        cfg={
            "safety": {
                "watchdog": {
                    "boot_grace_s": 0.0,         # disable boot grace
                    "head_frame_max_age_s": 0.5,
                    "usb_frame_max_age_s": 0.5,
                }
            }
        },
        scene_bus=SceneStateBus(),
        robot_bus=RobotStateBus(),
        fsm=fsm,
        combo_ctl=None,
        supervisor=sup,
    )
    fsm.transition(RobotFsmState.STANDING, "boot")
    fsm.transition(RobotFsmState.ENGAGED, "policy active")
    # head_frame_age_s() returns inf when no frame has ever arrived. Tick
    # the watchdog directly — no boot grace, so any emergency=True trip
    # would promote.
    wd._tick_head_frame()
    wd._tick_usb_frame()
    # head_frame age==inf must NOT propagate to supervisor (would block motion)
    # and must NOT drive the FSM into EMERGENCY_STOP.
    assert "head_frame" not in sup.trips, (
        "head_frame age=inf leaked into supervisor; would block motion"
    )
    assert "usb_frame" not in sup.trips
    assert fsm.state == RobotFsmState.ENGAGED, (
        f"head_frame age=inf promoted to {fsm.state}; "
        "should stay ENGAGED until first frame is received"
    )


def test_head_frame_finite_stale_still_emergencies():
    """After at least one head frame has arrived, staleness must still trip
    the watchdog and (after hold-down) promote EMERGENCY_STOP. The inf-age
    short-circuit only applies to startup, not to a camera that died
    mid-flight.
    """
    fsm = RobotFsm()
    sup = _CaptureSupervisor()
    scene_bus = SceneStateBus()
    wd = WatchdogManager(
        cfg={
            "safety": {
                "watchdog": {
                    "boot_grace_s": 0.0,
                    "head_frame_max_age_s": 0.1,
                }
            }
        },
        scene_bus=scene_bus,
        robot_bus=RobotStateBus(),
        fsm=fsm,
        combo_ctl=None,
        supervisor=sup,
    )
    # Mark "first frame received" by stamping a recent timestamp. Then age
    # forward by sleeping a hair past head_frame_max_age_s.
    scene_bus._ts_head = time.monotonic() - 0.5
    fsm.transition(RobotFsmState.STANDING, "boot")
    fsm.transition(RobotFsmState.ENGAGED, "policy active")
    wd._tick_head_frame()
    # First call sets the local trip; supervisor has the flag.
    assert "head_frame" in sup.trips, (
        "stale (finite) head_frame age must still propagate as emergency"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
