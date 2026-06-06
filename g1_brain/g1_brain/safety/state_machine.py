"""7-state finite state machine for the G1 robot brain.

The transition table mirrors the diagram in `docs/g1_plan.md` §3.1.
All state mutations go through :meth:`RobotFsm.transition`; external code
is the only thing that can drive transitions (the supervisor only triggers
EMERGENCY transitions on watchdog trips, never the recovery path).
"""
from __future__ import annotations

import enum
import logging
import threading
from typing import Callable, Dict, List, Set

log = logging.getLogger(__name__)


class RobotFsmState(str, enum.Enum):
    """States of the high-level robot FSM (string-valued for easy logging/JSON)."""
    BOOT = "BOOT"
    STANDING = "STANDING"
    ENGAGED = "ENGAGED"
    ACTING = "ACTING"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    FAULT = "FAULT"
    RECOVERING = "RECOVERING"
    # Deliberate low-power quiescent state used by the fleet "safe sleep"
    # capability. Unlike EMERGENCY_STOP it does not auto-recover; the robot
    # leaves it only on an explicit wake. Additive: pre-existing transitions
    # are unchanged.
    DORMANT = "DORMANT"


# Allowed transitions. Any state may go to EMERGENCY_STOP or FAULT (the
# universal "something went wrong" exits). Recovery from EMERGENCY_STOP
# enters RECOVERING and from there back to STANDING.
_ALLOWED: Dict[RobotFsmState, Set[RobotFsmState]] = {
    RobotFsmState.BOOT: {
        RobotFsmState.STANDING,
        RobotFsmState.EMERGENCY_STOP,
        RobotFsmState.FAULT,
    },
    RobotFsmState.STANDING: {
        RobotFsmState.ENGAGED,
        RobotFsmState.ACTING,
        RobotFsmState.DORMANT,
        RobotFsmState.EMERGENCY_STOP,
        RobotFsmState.FAULT,
    },
    RobotFsmState.ENGAGED: {
        RobotFsmState.STANDING,
        RobotFsmState.ACTING,
        RobotFsmState.EMERGENCY_STOP,
        RobotFsmState.FAULT,
    },
    RobotFsmState.ACTING: {
        RobotFsmState.ENGAGED,
        RobotFsmState.STANDING,
        RobotFsmState.EMERGENCY_STOP,
        RobotFsmState.FAULT,
    },
    RobotFsmState.EMERGENCY_STOP: {
        RobotFsmState.RECOVERING,
        RobotFsmState.FAULT,
    },
    RobotFsmState.RECOVERING: {
        RobotFsmState.STANDING,
        RobotFsmState.EMERGENCY_STOP,
        RobotFsmState.FAULT,
    },
    RobotFsmState.DORMANT: {
        RobotFsmState.STANDING,        # wake
        RobotFsmState.EMERGENCY_STOP,
        RobotFsmState.FAULT,
    },
    # FAULT is terminal (no outgoing transitions in the spec).
    RobotFsmState.FAULT: set(),
}


class IllegalTransitionError(RuntimeError):
    """Raised when :meth:`RobotFsm.transition` is called with an illegal target."""


SubscriberCallback = Callable[[RobotFsmState, RobotFsmState, str], None]


class RobotFsm:
    """Thread-safe FSM with subscribe/transition API.

    Default starts at BOOT. Subscribers are notified *outside* the lock
    so they can call back into ``state`` without deadlock.
    """

    def __init__(self, initial: RobotFsmState = RobotFsmState.BOOT) -> None:
        self._state = initial
        self._lock = threading.RLock()
        self._subs: List[SubscriberCallback] = []

    @property
    def state(self) -> RobotFsmState:
        with self._lock:
            return self._state

    def subscribe(self, callback: SubscriberCallback) -> None:
        """Register a callback called with (old_state, new_state, reason)
        on every successful transition."""
        with self._lock:
            self._subs.append(callback)

    def unsubscribe(self, callback: SubscriberCallback) -> None:
        with self._lock:
            try:
                self._subs.remove(callback)
            except ValueError:
                pass

    def transition(self, new_state: RobotFsmState, reason: str = "") -> RobotFsmState:
        """Move to ``new_state`` if legal; else raise IllegalTransitionError.

        A no-op transition (already in target state) is allowed and silently
        ignored — convenient for watchdogs that may fire repeatedly.
        """
        if not isinstance(new_state, RobotFsmState):
            raise TypeError(f"new_state must be RobotFsmState, got {type(new_state)!r}")
        with self._lock:
            old = self._state
            if old == new_state:
                return old
            allowed = _ALLOWED.get(old, set())
            if new_state not in allowed:
                raise IllegalTransitionError(
                    f"illegal transition {old.value} -> {new_state.value} "
                    f"(reason={reason!r}); allowed: "
                    f"{sorted(s.value for s in allowed)}"
                )
            self._state = new_state
            subs = list(self._subs)
        log.info("fsm: %s -> %s (%s)", old.value, new_state.value, reason)
        for cb in subs:
            try:
                cb(old, new_state, reason)
            except Exception:  # noqa: BLE001 - subscriber must not break FSM
                log.exception("fsm subscriber raised; ignoring")
        return new_state


__all__ = [
    "RobotFsmState",
    "RobotFsm",
    "IllegalTransitionError",
]
