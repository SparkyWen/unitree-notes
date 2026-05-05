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
    """Owns 5 watchdog threads.

    Trip semantics:
      * lowstate / head-frame trips set a supervisor flag immediately and
        promote to EMERGENCY_STOP after a hold-down (`hold_down_s`).
      * pose / RL-policy trips go EMERGENCY_STOP immediately.
      * USB-frame trip is informational (sets a flag but does not promote).
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
            "pose": 0.0,
            "rl_policy": 0.0,
        }
        self._threads: Dict[str, _WatchdogThread] = {}
        self._started = False
        self._lock = threading.RLock()

    # ----- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
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
        for t in self._threads.values():
            t.start()
        self._started = True
        log.info("watchdogs: started %d threads", len(self._threads))

    def stop(self) -> None:
        for t in self._threads.values():
            t.stop()
        for t in self._threads.values():
            t.join(timeout=1.0)
        self._threads.clear()
        self._started = False

    # ----- helpers ----------------------------------------------------------

    def _set_trip(self, name: str, reason: str, *, emergency: bool) -> None:
        with self._lock:
            now = time.monotonic()
            if self._trip_since[name] is None:
                self._trip_since[name] = now
                log.warning("watchdog %s tripped: %s", name, reason)
            elapsed = now - self._trip_since[name]
        if self.supervisor is not None:
            try:
                self.supervisor.set_watchdog_trip(name, reason)
            except Exception:  # noqa: BLE001
                log.exception("watchdog: supervisor set_watchdog_trip raised")
        hold = self._hold_down_s.get(name, 0.0)
        if emergency and elapsed >= hold:
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


__all__ = ["WatchdogManager"]
