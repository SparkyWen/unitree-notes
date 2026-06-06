"""Coordinator app: dispatch routes wired (no WS clients needed for these)."""
import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.coordinator.app import build_coordinator_app


@pytest.fixture
async def client(tmp_path):
    app = build_coordinator_app(db_path=tmp_path / "fleet.sqlite", tick_interval_s=0.0)
    c = TestClient(TestServer(app))
    await c.start_server()
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_dispatch_routes_exist(client):
    r = await client.get("/dispatch")
    assert r.status == 200
    body = await r.json()
    assert "assignments" in body and "needs_operator" in body

    r = await client.get("/anomalies")
    assert r.status == 200
    assert "anomalies" in await r.json()


@pytest.mark.asyncio
async def test_command_unknown_robot_rejected(client):
    r = await client.post("/commands", json={"op": "sleep", "args": {"robot": "ghost"}})
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is False


@pytest.mark.asyncio
async def test_command_via_natural_language_grammar(client):
    # no robots registered -> dispatch finds no candidate but the route works
    r = await client.post("/commands", json={"nl": "status"})
    assert r.status == 200
    assert (await r.json())["ok"] is True


@pytest.mark.asyncio
async def test_readonly_routes_still_work(client):
    r = await client.get("/robots")
    assert r.status == 200
    assert await r.json() == []
