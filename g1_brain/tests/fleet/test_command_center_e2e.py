"""End-to-end gate for the command center: an operator NL request, sent over
HTTP, plans (deterministic — no codex/key) and drives the REAL shared MuJoCo
world (two RL G1s @50 Hz) through the LiveExecutor until the relay completes.
Empirical (real physics); paced ~real time. The codex path is unit-tested
separately (test_codex_fleet_llm) so this stays offline + deterministic."""
import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.sim.command_center import build_command_center_app
from g1_brain.fleet.sim.shared_world_node import WorldSim


@pytest.fixture
async def sim_client():
    sim = WorldSim()
    sim.start()
    app = build_command_center_app(sim, llm=None, start_loop=True)
    try:
        async with TestClient(TestServer(app)) as c:
            yield c
    finally:
        sim.stop()


@pytest.mark.slow
async def test_command_drives_real_world_to_relay(sim_client):
    r = await sim_client.post(
        "/command", json={"nl": "让 g1_a 和 g1_b 到中间会合，然后 g1_a 把巡逻交给 g1_b"})
    body = await r.json()
    assert body["ok"] is True and body["plan"]["coordination"]["type"] == "relay"

    # poll the live world until the mission completes (or time out)
    mission = None
    for _ in range(600):                      # ~30 s budget
        w = await (await sim_client.get("/world")).json()
        mission = w["mission"]
        if mission and mission["complete"]:
            break
        await asyncio.sleep(0.05)

    assert mission is not None and mission["complete"], "relay mission never completed"
    assert mission["min_sep"] is None or mission["min_sep"] > 0.3, "robots collided"

    # the receiver (g1_b) is patrolling, the hander (g1_a) is idle — read live telemetry
    tele = {b["robot_id"]: b for b in w["robots"]}
    assert tele["g1_b"]["posture"] == "PATROL"
    assert tele["g1_a"]["posture"] == "IDLE"
