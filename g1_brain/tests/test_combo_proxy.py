"""Smoke tests for ComboProxy.

Full end-to-end test would require a live MuJoCo simulator + DDS, so we
only test the parts that don't need a child process: import, construction,
and the read-side properties before ``start()`` (they should default
sensibly so anything reading them during startup races doesn't crash).
The ``start()`` -> child-process path is exercised manually with
``python -m g1_brain.apps.agent_main`` against the running simulator;
unit tests for the IPC protocol would need a fake combo, which is out of
scope.
"""
from __future__ import annotations

import numpy as np
import pytest


def test_combo_proxy_imports():
    from g1_brain.safety.combo_proxy import ComboProxy  # noqa: F401


def test_combo_proxy_constructs_without_starting():
    """We must be able to construct a proxy without spawning the child;
    callers (skill_server, watchdogs) only need the constants after
    start(), but unit tests / debug tooling may want to introspect the
    object earlier."""
    from g1_brain.safety.combo_proxy import ComboProxy
    cp = ComboProxy(domain_id=1, interface="lo")
    # Arm-related constants default to zero arrays of the right shape so
    # any premature read doesn't blow up on an AttributeError.
    assert isinstance(cp.arm_rest, np.ndarray)
    assert cp.arm_rest.shape == (14,)
    assert cp.arm_scale.shape == (14,)
    assert cp.arm_offset.shape == (14,)
    # Liveness mirrors default to "not ready" before start().
    assert cp.policy_active is False
    assert cp.first_state_received is False
    assert cp.last_state_time == 0.0
    # low_state is intentionally always None — the brain is expected to
    # subscribe to rt/lowstate independently when using ComboProxy. This
    # is a contract ``_RobotStateProducer`` relies on.
    assert cp.low_state is None


def test_combo_proxy_send_before_start_does_not_crash():
    """If something fires set_command before start() / after stop(),
    ComboProxy logs a warning instead of raising. This protects shutdown
    paths (skill_server's `finally: combo.set_command(0,0,0)`) from
    crashing when the worker has already exited."""
    from g1_brain.safety.combo_proxy import ComboProxy
    cp = ComboProxy(domain_id=1, interface="lo")
    # No subprocess spawned yet; these must not raise.
    cp.set_command(0.1, 0.0, 0.0)
    cp.release_arms()
    cp.set_safe_hold(False)
    cp.push_arm_action([(1.0, np.zeros(14, dtype=np.float64))])


# ----------------------------------------------------------------------------
# End-to-end subprocess lifecycle tests — these actually spawn a child
# process using the test-only stub entry point in combo_proxy.py. They catch
# mechanical IPC bugs (Pipe direction, forgotten close, missing fields)
# that the construction-only smoke tests above miss.
#
# Lesson from 2026-05-06: an earlier iteration used `Pipe(duplex=False)` and
# accidentally swapped the reader/writer ends. Construction tests passed but
# the real subprocess immediately died with `OSError: connection is
# write-only`. That hit the operator on first try. These tests now spawn a
# real child to make sure the wiring works end-to-end.
# ----------------------------------------------------------------------------
def test_combo_proxy_full_lifecycle_with_stub_subprocess():
    """Spawn the child via the stub entry point, send commands across the
    pipe, read shared-memory mirrors, then stop cleanly."""
    import time
    from g1_brain.safety.combo_proxy import ComboProxy, _test_stub_combo_main

    cp = ComboProxy(domain_id=99, interface="lo")
    try:
        cp.start(target=_test_stub_combo_main, ready_timeout_s=10.0)
        # Constants must have arrived through the constants pipe.
        assert cp.arm_rest.shape == (14,)
        assert cp.arm_scale.shape == (14,)
        assert float(cp.arm_scale[0]) == pytest.approx(0.44)
        assert cp.mode_machine == 7  # the stub's sentinel
        # Wait briefly for the stub's status thread to flip flags.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not cp.policy_active:
            time.sleep(0.05)
        assert cp.policy_active is True
        assert cp.first_state_received is True
        assert cp.last_state_time > 0.0

        # Send a command across the pipe. The stub encodes "received N commands"
        # into mode_machine_v as 100 + N so we can assert delivery.
        cp.set_command(0.2, 0.0, 0.0)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with cp._mode_machine_v.get_lock():
                v = int(cp._mode_machine_v.value)
            if v >= 101:
                break
            time.sleep(0.02)
        assert v == 101, f"stub did not receive set_command (mode_machine={v})"

        # Send three more commands and confirm cumulative count.
        cp.push_arm_action([(0.5, np.zeros(14))])
        cp.release_arms()
        cp.set_safe_hold(True)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with cp._mode_machine_v.get_lock():
                v = int(cp._mode_machine_v.value)
            if v >= 104:
                break
            time.sleep(0.02)
        assert v == 104, f"stub missed commands (mode_machine={v})"
    finally:
        cp.stop_and_settle()
    # After stop the worker must have exited.
    assert cp._proc is None or cp._proc.exitcode is not None


def test_combo_proxy_detects_subprocess_early_death():
    """If the subprocess crashes before signalling ready, start() must raise
    RuntimeError instead of blocking until the timeout. Otherwise agent_main
    silently continues without a controller and the robot collapses.

    The crashing target lives at module level (combo_proxy._test_crashing_combo_main)
    because the ``spawn`` start method requires pickling the target function.
    """
    from g1_brain.safety.combo_proxy import (
        ComboProxy,
        _test_crashing_combo_main,
    )

    cp = ComboProxy(domain_id=99, interface="lo")
    try:
        with pytest.raises(RuntimeError, match="exited unexpectedly"):
            cp.start(target=_test_crashing_combo_main, ready_timeout_s=5.0)
    finally:
        cp.stop_and_settle()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
