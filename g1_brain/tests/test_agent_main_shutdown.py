"""Unit tests for agent_main's force-quit signal escalation.

Regression for the "^C^C^C and it just keeps logging" wedge: Ctrl-C must
always be able to bring the process down. We test the escalation state machine
directly (without delivering real signals or actually exiting) by injecting a
fake loop and a fake exit function.
"""
from __future__ import annotations

import asyncio

import g1_brain.apps.agent_main as am


def test_first_signal_requests_graceful_then_second_force_exits():
    scheduled = []

    class _FakeLoop:
        def call_soon_threadsafe(self, fn, *a):
            scheduled.append((fn, a))

    stop_evt = asyncio.Event()
    exits = []

    handler, state = am._install_shutdown_signals(
        _FakeLoop(),
        stop_evt,
        exit_fn=lambda code: exits.append(code),
        spawn_watchdog=False,
        install=False,
    )

    # First press: graceful shutdown requested (stop_evt.set scheduled on the
    # loop), no exit yet.
    handler()
    assert state["count"] == 1
    assert len(scheduled) == 1
    assert scheduled[0][0] == stop_evt.set
    assert exits == []

    # Second press: immediate force-exit with conventional SIGINT code.
    handler()
    assert state["count"] == 2
    assert exits == [130]


def test_first_signal_force_exits_when_loop_already_closed():
    """If the loop can't accept work (closed/closing), even the FIRST signal
    must hard-exit rather than silently do nothing."""

    class _ClosedLoop:
        def call_soon_threadsafe(self, fn, *a):
            raise RuntimeError("Event loop is closed")

    exits = []
    handler, _ = am._install_shutdown_signals(
        _ClosedLoop(),
        asyncio.Event(),
        exit_fn=lambda code: exits.append(code),
        spawn_watchdog=False,
        install=False,
    )
    handler()
    assert exits == [130]


def test_watchdog_thread_armed_on_first_signal():
    """The graceful path must arm a daemon watchdog so a wedged shutdown still
    dies on its own."""
    import threading

    before = {t.name for t in threading.enumerate()}

    class _FakeLoop:
        def call_soon_threadsafe(self, fn, *a):
            pass

    handler, _ = am._install_shutdown_signals(
        _FakeLoop(),
        asyncio.Event(),
        # Long grace so the watchdog is still alive when we inspect threads;
        # it is a daemon thread so it never blocks the test process exit.
        grace_s=60.0,
        exit_fn=lambda code: None,
        spawn_watchdog=True,
        install=False,
    )
    handler()
    names = {t.name for t in threading.enumerate()}
    assert "g1-force-exit-watchdog" in (names - before)
    wd = next(t for t in threading.enumerate() if t.name == "g1-force-exit-watchdog")
    assert wd.daemon is True
