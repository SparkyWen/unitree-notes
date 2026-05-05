"""FSM transition table + thread-safety tests."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from g1_brain.safety.state_machine import (
    IllegalTransitionError,
    RobotFsm,
    RobotFsmState,
    _ALLOWED,
)


# Build legal/illegal pair lists from the canonical _ALLOWED table itself,
# so the tests stay in sync if the table grows.
_ALL_STATES = list(RobotFsmState)
_LEGAL_PAIRS = [
    (src, dst)
    for src, allowed in _ALLOWED.items()
    for dst in allowed
]
_ILLEGAL_PAIRS = [
    (src, dst)
    for src in _ALL_STATES
    for dst in _ALL_STATES
    if dst not in _ALLOWED.get(src, set()) and dst != src
]


def test_default_starts_at_boot():
    fsm = RobotFsm()
    assert fsm.state == RobotFsmState.BOOT


def test_no_op_transition_is_silent():
    fsm = RobotFsm()
    # BOOT -> BOOT is a no-op, must not raise.
    assert fsm.transition(RobotFsmState.BOOT) == RobotFsmState.BOOT


@pytest.mark.parametrize("src,dst", _LEGAL_PAIRS)
def test_every_legal_transition_allowed(src, dst):
    fsm = RobotFsm(initial=src)
    assert fsm.transition(dst, "test") == dst
    assert fsm.state == dst


@pytest.mark.parametrize("src,dst", _ILLEGAL_PAIRS)
def test_every_illegal_transition_raises(src, dst):
    fsm = RobotFsm(initial=src)
    with pytest.raises(IllegalTransitionError):
        fsm.transition(dst, "test")
    assert fsm.state == src


def test_subscriber_notified_on_transition():
    fsm = RobotFsm()
    events = []
    fsm.subscribe(lambda old, new, reason: events.append((old, new, reason)))
    fsm.transition(RobotFsmState.STANDING, "ready")
    fsm.transition(RobotFsmState.ENGAGED, "wake")
    assert events == [
        (RobotFsmState.BOOT, RobotFsmState.STANDING, "ready"),
        (RobotFsmState.STANDING, RobotFsmState.ENGAGED, "wake"),
    ]


def test_subscriber_exception_does_not_break_fsm():
    fsm = RobotFsm()
    fsm.subscribe(lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    fsm.transition(RobotFsmState.STANDING, "ok")
    assert fsm.state == RobotFsmState.STANDING


def test_unsubscribe():
    fsm = RobotFsm()
    events = []
    cb = lambda *a: events.append(a)  # noqa: E731
    fsm.subscribe(cb)
    fsm.transition(RobotFsmState.STANDING)
    fsm.unsubscribe(cb)
    fsm.transition(RobotFsmState.ENGAGED)
    assert len(events) == 1


def test_fault_is_terminal():
    fsm = RobotFsm(initial=RobotFsmState.FAULT)
    for dst in RobotFsmState:
        if dst == RobotFsmState.FAULT:
            continue
        with pytest.raises(IllegalTransitionError):
            fsm.transition(dst, "try")


def test_thread_safety_concurrent_transitions():
    """Hammer the FSM from many threads; only legal transitions succeed and
    state remains internally consistent."""
    fsm = RobotFsm()
    fsm.transition(RobotFsmState.STANDING)

    def worker(tag):
        successes = 0
        failures = 0
        for _ in range(50):
            for dst in (
                RobotFsmState.ENGAGED,
                RobotFsmState.STANDING,
                RobotFsmState.ACTING,
            ):
                try:
                    fsm.transition(dst, f"thread{tag}")
                    successes += 1
                except IllegalTransitionError:
                    failures += 1
        return successes, failures

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(worker, range(8)))
    # Some attempts must have succeeded across the threads.
    total_succ = sum(r[0] for r in results)
    assert total_succ > 0
    # Final state must be one of the targets we tried (i.e. valid enum value).
    assert fsm.state in {
        RobotFsmState.ENGAGED,
        RobotFsmState.STANDING,
        RobotFsmState.ACTING,
    }


def test_transition_rejects_non_enum_input():
    fsm = RobotFsm()
    with pytest.raises(TypeError):
        fsm.transition("STANDING")  # type: ignore[arg-type]
