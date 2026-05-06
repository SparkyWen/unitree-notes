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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
