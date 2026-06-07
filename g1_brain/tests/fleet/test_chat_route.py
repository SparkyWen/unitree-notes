import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.coordinator.app import build_coordinator_app
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, CoreState, Pose, RobotStateMsg)


def _seed(reg, rid, x):
    reg.register(CapabilityDescriptor(robot_id=rid, frame_id=f"{rid}/map"))
    reg.on_heartbeat(RobotStateMsg(
        robot_id=rid, ts="t", seq=0,
        core=CoreState(pose=Pose(frame_id=f"{rid}/map", x=x, y=0.0))))


@pytest.fixture
async def client(tmp_path):
    app = build_coordinator_app(db_path=tmp_path / "c.sqlite", tick_interval_s=0.0, llm=None)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_chat_relay_returns_plan_and_ops(client):
    reg = client.app["registry"]
    _seed(reg, "g1_a", -1.5)
    _seed(reg, "g1_b", 1.5)
    r = await client.post("/chat", json={"nl": "两机到中间会合，然后 g1_a 把巡逻交给 g1_b"})
    body = await r.json()
    assert body["ok"] is True
    assert body["plan"]["coordination"]["type"] == "relay"
    assert set(body["ops"]) == {"g1_a", "g1_b"}
    assert body["ops"]["g1_b"][-1]["op"] == "patrol"
    assert body["ops"]["g1_a"][-1]["op"] == "idle"


async def test_chat_unparseable_needs_clarification(client):
    r = await client.post("/chat", json={"nl": "make me a sandwich"})
    body = await r.json()
    assert body["ok"] is False and body["needs_clarification"]
