"""command_center web app — the operator-facing control center. POST /command
runs the (deterministic, here) commander, expands sub-agents, and *submits* a
mission to the LiveExecutor (preempting any running one). GET /world streams
live poses; GET /events streams the commander's decisions. Tested with aiohttp's
TestClient + a fake world + no LLM (so it's fast and offline)."""
import math

import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.sim.command_center import build_command_center_app


class FakeWorld:
    def __init__(self, poses):
        self._pose = {rid: (x, y, 0.0) for rid, (x, y) in poses.items()}
        self._goal = {}
        self._posture = {rid: "IDLE" for rid in poses}

    def set_nav_goal(self, rid, x, y):
        self._goal[rid] = (x, y)

    def set_posture(self, rid, posture):
        self._posture[rid] = getattr(posture, "value", str(posture))

    def telemetry(self):
        out = {}
        for rid, (x, y, yaw) in self._pose.items():
            nb = [{"peer": o, "dist": math.hypot(self._pose[o][0] - x,
                                                 self._pose[o][1] - y)}
                  for o in self._pose if o != rid]
            out[rid] = {"pose": (x, y, yaw), "neighbors": nb,
                        "posture": self._posture[rid], "gz": -1.0}
        return out


@pytest.fixture
async def client():
    world = FakeWorld({"g1_a": (-1.5, 0.0), "g1_b": (1.5, 0.0)})
    app = build_command_center_app(world, llm=None, start_loop=False)
    async with TestClient(TestServer(app)) as c:
        c.app["world"] = world
        yield c


async def test_index_served(client):
    r = await client.get("/")
    assert r.status == 200
    body = await r.text()
    assert "指挥" in body          # the control-center page


async def test_world_endpoint_returns_robot_poses(client):
    r = await client.get("/world")
    body = await r.json()
    ids = {b["robot_id"] for b in body["robots"]}
    assert ids == {"g1_a", "g1_b"}
    a = next(b for b in body["robots"] if b["robot_id"] == "g1_a")
    assert a["x"] == pytest.approx(-1.5)


async def test_command_submits_mission_and_returns_plan(client):
    r = await client.post("/command",
                          json={"nl": "两机到中间会合，然后 g1_a 把巡逻交给 g1_b"})
    body = await r.json()
    assert body["ok"] is True
    assert body["plan"]["coordination"]["type"] == "relay"
    assert set(body["ops"]) == {"g1_a", "g1_b"}
    assert client.app["executor"].mission is not None


async def test_second_command_preempts_first(client):
    await client.post("/command", json={"nl": "两机到中间会合"})
    gen1 = client.app["executor"].mission.gen
    await client.post("/command", json={"nl": "两机到中间会合，然后 g1_a 把巡逻交给 g1_b"})
    gen2 = client.app["executor"].mission.gen
    assert gen2 > gen1                      # newest command preempted the prior one


async def test_unparseable_command_needs_clarification(client):
    r = await client.post("/command", json={"nl": "make me a sandwich"})
    body = await r.json()
    assert body["ok"] is False and body["needs_clarification"]


async def test_events_endpoint_streams_decisions(client):
    await client.post("/command", json={"nl": "两机到中间会合，然后 g1_a 把巡逻交给 g1_b"})
    r = await client.get("/events")
    body = await r.json()
    text = " ".join(e["msg"] for e in body["events"])
    assert "指挥官" in text                  # the commander's decision was logged
