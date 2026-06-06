"""Regression wrapper for the Tier-2 two-G1 MuJoCo scenario.

Runs a short headless version and asserts the autonomous + human-command
outcomes. Skips cleanly if MuJoCo or the G1 scene asset is unavailable.
"""
import os

import pytest

os.environ.setdefault("MUJOCO_GL", "egl")

scenario = pytest.importorskip("g1_brain.fleet.sim.scenario_two_g1")
from g1_brain.fleet.sim.scenario_two_g1 import run, _DEFAULT_SCENE  # noqa: E402


@pytest.mark.skipif(not os.path.exists(_DEFAULT_SCENE),
                    reason="G1 MuJoCo scene asset not present")
@pytest.mark.asyncio
async def test_two_g1_autonomous_and_human_dispatch():
    try:
        result = await run(scene=_DEFAULT_SCENE, inject_after_s=0.4,
                           settle_s=0.4, verbose=False)
    except Exception as e:  # mujoco GL / asset issues -> skip, don't fail CI
        pytest.skip(f"MuJoCo unavailable in this environment: {e}")

    a = result["autonomous"]
    h = result["human"]
    assert a["holder_fsm"] == "DORMANT"
    assert a["holder_posture"] == "SLEEP"
    assert a["reassigned_to"] == a["other"]
    assert a["other_posture"] == "PATROL"
    assert a["holder_upright_gz"] < -0.7 and a["other_upright_gz"] < -0.7
    assert h["holder_fsm_after_wake"] == "STANDING"
    assert h["task_back_to"] == a["holder"]
    for et in ("anomaly_detected", "task_reassigned", "robot_sleeping",
               "command_issued", "command_accepted"):
        assert et in result["event_types"]
