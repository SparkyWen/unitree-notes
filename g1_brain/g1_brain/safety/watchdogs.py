"""Watchdog daemons that catch staleness/failure independent of skill calls.

Each watchdog runs in its own daemon thread on the period from §3.4 of the
design doc. On trip a watchdog:

  * logs at WARNING (recoverable) or ERROR (unrecoverable);
  * sets a latched flag in the SafetySupervisor so any in-flight call is
    rejected immediately on next ``validate``;
  * optionally calls ``fsm.transition(EMERGENCY_STOP, …)`` once the trip
    persists past the documented hold-down (e.g. 2 s for lowstate, 5 s for
    head frame; pose / RL trip immediately).

The combo controller is optional; when None the RL-policy watchdog is
silently skipped so this module can be unit-tested without hardware.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from ..scene_state.fusion import RobotStateBus, SceneStateBus
from .pose_check import gravity_proj_z_from_quat
from .state_machine import IllegalTransitionError, RobotFsm, RobotFsmState

log = logging.getLogger(__name__)


class _WatchdogThread(threading.Thread):
    """Tiny periodic worker; reads `interval`/`tick` and exits on `stop`."""

    def __init__(self, name: str, interval_s: float, tick) -> None:
        super().__init__(name=name, daemon=True)
        self.interval_s = interval_s
        self._tick = tick
        # NOTE: do NOT name this attribute `_stop`; threading.Thread already
        # uses `_stop` internally as a private method.
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            t0 = time.monotonic()
            try:
                self._tick()
            except Exception:  # noqa: BLE001 — watchdogs must not die
                log.exception("watchdog %s tick raised", self.name)
            dt = time.monotonic() - t0
            wait = max(0.0, self.interval_s - dt)
            if self._stop_evt.wait(wait):
                return


class WatchdogManager:
    """Owns 5 watchdog threads + an auto-recovery thread.

    Trip semantics:
      * lowstate / head-frame trips set a supervisor flag immediately and
        promote to EMERGENCY_STOP after a hold-down (`hold_down_s`).
      * pose / RL-policy trips go EMERGENCY_STOP after their hold-down too
        (pose has a small hold-down so a single transient IMU sample at
        startup does not emergency the robot).
      * USB-frame trip is informational (sets a flag but does not promote).

    Boot grace:
      For ``boot_grace_s`` after :meth:`start`, watchdogs still set/clear
      their local + supervisor flags but DO NOT promote to EMERGENCY_STOP.
      This prevents false trips while the combo controller is ramping the
      robot to its default pose (~5 s) and while camera frames are still
      flowing.

    Auto-recovery:
      When the FSM is in EMERGENCY_STOP and all motion-blocking watchdogs
      (lowstate, head_frame, pose) have been continuously clear for
      ``recovery_hold_s``, walk EMERGENCY_STOP → RECOVERING → STANDING so
      the operator does not need to manually reset the system.
    """

    def __init__(
        self,
        cfg: Dict[str, Any],
        scene_bus: SceneStateBus,
        robot_bus: RobotStateBus,
        fsm: RobotFsm,
        combo_ctl: Optional[Any] = None,
        supervisor: Optional[Any] = None,
    ) -> None:
        self.cfg = cfg
        self.scene_bus = scene_bus
        self.robot_bus = robot_bus
        self.fsm = fsm
        self.combo = combo_ctl
        self.supervisor = supervisor

        wd = dict((cfg.get("safety") or {}).get("watchdog") or {})
        self.lowstate_max_age = float(wd.get("lowstate_max_age_s", 0.5))
        self.head_max_age = float(wd.get("head_frame_max_age_s", 2.0))
        self.usb_max_age = float(wd.get("usb_frame_max_age_s", 3.0))
        self.gravity_z_min = float(
            ((cfg.get("safety") or {}).get("pose") or {}).get("gravity_z_min", -0.85)
        )
        # Grace window (after start) during which trips never promote to
        # EMERGENCY_STOP. Default 5 s covers combo's "ramping to default
        # pose over 5.0 s" startup transient.
        self.boot_grace_s = float(wd.get("boot_grace_s", 5.0))
        # How long all motion-blocking watchdogs must be clear before we
        # auto-recover from EMERGENCY_STOP back to STANDING.
        self.recovery_hold_s = float(wd.get("recovery_hold_s", 2.0))

        # When a trip first appeared (monotonic). None == not currently tripped.
        self._trip_since: Dict[str, Optional[float]] = {
            "lowstate": None,
            "head_frame": None,
            "usb_frame": None,
            "pose": None,
            "rl_policy": None,
        }
        # How long a trip must persist before promoting to EMERGENCY_STOP.
        self._hold_down_s: Dict[str, float] = {
            "lowstate": 2.0,
            "head_frame": 5.0,
            "usb_frame": float("inf"),  # never auto-emergency
            # Pose: 0.5 s hold-down avoids tripping on a single transient
            # IMU sample (e.g. during the combo pose ramp) while still
            # catching real falls — those produce sustained bad readings.
            "pose": 0.5,
            "rl_policy": 0.0,
        }
        # Monotonic timestamp at which all motion-blocking watchdogs have
        # been clear continuously (None == something is tripped right now).
        self._all_clear_since: Optional[float] = None
        # Set in start() so the boot-grace window is measured from there.
        self._started_at: float = 0.0
        self._threads: Dict[str, _WatchdogThread] = {}
        self._started = False
        self._lock = threading.RLock()

    # ----- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started_at = time.monotonic()
        # Re-arm the boot-grace window every time auto-recovery completes a
        # RECOVERING -> STANDING transition. Without this, the policy's first
        # ~1 s after re-engagement (where it's still settling and gravity_z
        # noisily flirts with the threshold) was tripping the pose watchdog
        # again immediately, producing the ENGAGED <-> EMERGENCY_STOP flap
        # we saw in 2026-05-05 logs (a 90 s loop at one trip every 100 ms).
        self.fsm.subscribe(self._on_fsm_transition)
        self._threads["lowstate"] = _WatchdogThread(
            "wd_lowstate", 0.1, self._tick_lowstate
        )
        self._threads["head_frame"] = _WatchdogThread(
            "wd_head_frame", 0.5, self._tick_head_frame
        )
        self._threads["usb_frame"] = _WatchdogThread(
            "wd_usb_frame", 0.5, self._tick_usb_frame
        )
        self._threads["pose"] = _WatchdogThread("wd_pose", 0.1, self._tick_pose)
        self._threads["rl_policy"] = _WatchdogThread(
            "wd_rl_policy", 0.1, self._tick_rl_policy
        )
        self._threads["recovery"] = _WatchdogThread(
            "wd_recovery", 0.2, self._tick_recovery
        )
        for t in self._threads.values():
            t.start()
        self._started = True
        log.info(
            "watchdogs: started %d threads (boot_grace=%.1fs, recovery_hold=%.1fs)",
            len(self._threads), self.boot_grace_s, self.recovery_hold_s,
        )

    def stop(self) -> None:
        try:
            self.fsm.unsubscribe(self._on_fsm_transition)
        except Exception:  # noqa: BLE001 — best effort
            pass
        for t in self._threads.values():
            t.stop()
        for t in self._threads.values():
            t.join(timeout=1.0)
        self._threads.clear()
        self._started = False

    def _on_fsm_transition(
        self,
        old: RobotFsmState,
        new: RobotFsmState,
        reason: str,  # noqa: ARG002 — required by FSM subscriber signature
    ) -> None:
        """React to FSM transitions: re-arm boot-grace and toggle safe-hold.

        Auto-recovery jumps EMERGENCY_STOP -> RECOVERING -> STANDING in
        rapid succession, and STANDING -> ENGAGED follows ~0.3 s later.
        That gives the RL policy almost no time to settle before pose ticks
        start judging it again. Resetting `_started_at` here applies the
        same grace window we use at boot so the policy has a fair chance
        to stabilize before any single transient sample re-promotes us
        back to EMERGENCY_STOP.

        On entering EMERGENCY_STOP we also call ``combo.set_safe_hold(True)``
        if the controller exposes it. Without this the FSM transition is
        bookkeeping only — the combo's _tick keeps running the policy and
        publishing lowcmd, so the robot keeps falling regardless of how the
        FSM thinks of it. With it, the controller switches to a default_q
        hold (matching the bridge's STANDBY behaviour) and gives the robot
        a chance to actually stand back up. We release the hold whenever
        the FSM leaves EMERGENCY_STOP so the next walk command works.
        """
        if old == RobotFsmState.RECOVERING and new == RobotFsmState.STANDING:
            self._started_at = time.monotonic()
            log.info(
                "watchdogs: re-armed boot-grace (%.1fs) after auto-recovery",
                self.boot_grace_s,
            )
        if self.combo is not None and hasattr(self.combo, "set_safe_hold"):
            try:
                if new == RobotFsmState.EMERGENCY_STOP:
                    self.combo.set_safe_hold(True)
                    log.info(
                        "watchdogs: combo safe-hold engaged (FSM -> EMERGENCY_STOP)"
                    )
                elif old == RobotFsmState.EMERGENCY_STOP:
                    self.combo.set_safe_hold(False)
                    log.info(
                        "watchdogs: combo safe-hold released "
                        "(FSM EMERGENCY_STOP -> %s)", new.name,
                    )
            except Exception:  # noqa: BLE001 — never let a hook kill the FSM
                log.exception("watchdogs: combo.set_safe_hold raised")

    # ----- helpers ----------------------------------------------------------

    def _in_boot_grace(self, now: float) -> bool:
        """True while we are inside the post-start grace window."""
        return (now - self._started_at) < self.boot_grace_s

    def _set_trip(self, name: str, reason: str, *, emergency: bool) -> None:
        with self._lock:
            now = time.monotonic()
            if self._trip_since[name] is None:
                self._trip_since[name] = now
                log.warning("watchdog %s tripped: %s", name, reason)
            elapsed = now - self._trip_since[name]
            in_grace = self._in_boot_grace(now)
        # Only emergency-class (motion-blocking) trips propagate to the
        # supervisor. ``emergency=False`` trips (currently usb_frame) are
        # informational: they get logged + tracked locally for recovery
        # bookkeeping, but they MUST NOT block motion calls. usb_frame
        # gates user-gesture detection (the laptop webcam fed via
        # teleimager) — losing it should not stop the robot from waving,
        # walking, or otherwise running, since none of those skills read
        # the USB stream.
        if self.supervisor is not None and emergency:
            try:
                self.supervisor.set_watchdog_trip(name, reason)
            except Exception:  # noqa: BLE001
                log.exception("watchdog: supervisor set_watchdog_trip raised")
        hold = self._hold_down_s.get(name, 0.0)
        if emergency and elapsed >= hold and not in_grace:
            try:
                self.fsm.transition(
                    RobotFsmState.EMERGENCY_STOP,
                    f"watchdog {name}: {reason}",
                )
            except IllegalTransitionError:
                pass

    def _clear_trip(self, name: str) -> None:
        with self._lock:
            if self._trip_since[name] is not None:
                self._trip_since[name] = None
                log.info("watchdog %s cleared", name)
        # Always best-effort clear; idempotent if the trip was never set
        # on the supervisor in the first place (informational trips).
        if self.supervisor is not None:
            try:
                self.supervisor.set_watchdog_trip(name, None)
            except Exception:  # noqa: BLE001
                log.exception("watchdog: supervisor clear raised")

    # ----- ticks ------------------------------------------------------------

    def _tick_lowstate(self) -> None:
        age = self.robot_bus.lowstate_age_s()
        if age > self.lowstate_max_age:
            self._set_trip("lowstate", f"age={age:.2f}s", emergency=True)
        else:
            self._clear_trip("lowstate")

    def _tick_head_frame(self) -> None:
        age = self.scene_bus.head_frame_age_s()
        if age > self.head_max_age:
            self._set_trip("head_frame", f"age={age:.2f}s", emergency=True)
        else:
            self._clear_trip("head_frame")

    def _tick_usb_frame(self) -> None:
        age = self.scene_bus.usb_frame_age_s()
        if age > self.usb_max_age:
            self._set_trip("usb_frame", f"age={age:.2f}s", emergency=False)
        else:
            self._clear_trip("usb_frame")

    def _tick_pose(self) -> None:
        rs = self.robot_bus.snapshot()
        if rs is None:
            return  # no data yet, lowstate watchdog will catch it
        gz = float(rs.gravity_proj_z)
        if gz > self.gravity_z_min:
            self._set_trip("pose", f"gravity_z={gz:.2f}", emergency=True)
        else:
            self._clear_trip("pose")

    def _tick_rl_policy(self) -> None:
        rs = self.robot_bus.snapshot()
        if rs is None:
            return
        # Only enforce when we are in a state that NEEDS the policy.
        cur = self.fsm.state
        needs_policy = cur in (RobotFsmState.ENGAGED, RobotFsmState.ACTING)
        if needs_policy and not rs.rl_policy_active:
            self._set_trip("rl_policy", "policy_active=False", emergency=True)
        else:
            self._clear_trip("rl_policy")

    # Watchdogs that, when clear, indicate the robot is safe to leave
    # EMERGENCY_STOP. usb_frame is informational; rl_policy is only enforced
    # while ENGAGED/ACTING (which we can't be in EMERGENCY_STOP anyway).
    _MOTION_BLOCKING_TRIPS = ("lowstate", "head_frame", "pose")

    def _tick_recovery(self) -> None:
        """Auto-recover EMERGENCY_STOP → RECOVERING → STANDING when safe.

        We only attempt the transition when:
          * the FSM is in EMERGENCY_STOP (and not in BOOT or FAULT);
          * every motion-blocking watchdog has been clear continuously
            for at least ``recovery_hold_s``.

        FAULT is terminal so we never try to leave it. RECOVERING is
        transient: we hop straight through it to STANDING.
        """
        if self.fsm.state != RobotFsmState.EMERGENCY_STOP:
            # Reset the timer whenever we are not in EMERGENCY_STOP — we
            # only count "all-clear time" toward recovery while stopped.
            self._all_clear_since = None
            return
        with self._lock:
            now = time.monotonic()
            any_tripped = any(
                self._trip_since.get(name) is not None
                for name in self._MOTION_BLOCKING_TRIPS
            )
            if any_tripped:
                self._all_clear_since = None
                return
            if self._all_clear_since is None:
                self._all_clear_since = now
                return
            elapsed = now - self._all_clear_since
        if elapsed < self.recovery_hold_s:
            return
        # All clear long enough — attempt the recovery walk.
        try:
            self.fsm.transition(
                RobotFsmState.RECOVERING,
                f"watchdogs clear for {elapsed:.1f}s",
            )
        except IllegalTransitionError:
            return
        try:
            self.fsm.transition(
                RobotFsmState.STANDING,
                "auto-recovery complete",
            )
        except IllegalTransitionError:
            log.warning(
                "auto-recovery: RECOVERING -> STANDING refused; "
                "leaving FSM in RECOVERING for caller to resolve"
            )
        finally:
            with self._lock:
                self._all_clear_since = None


__all__ = ["WatchdogManager"]
