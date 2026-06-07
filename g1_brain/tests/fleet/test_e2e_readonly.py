import asyncio
import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.coordinator.app import build_coordinator_app
from g1_brain.fleet.bus.ws_client import WsFleetClient
from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.fleet.console.cli import format_fleet
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


class _Core:
    def __init__(self, rid): self.robot_id = rid; self._q = asyncio.Queue()
    def get_capabilities(self): return CapabilityDescriptor(robot_id=self.robot_id,
                                                            frame_id=f"{self.robot_id}/map")
    def get_state(self, *, seq=0): return RobotStateMsg(robot_id=self.robot_id, ts="t",
                                                        seq=seq, fsm_state="ENGAGED")
    async def subscribe_events(self):
        while True: yield await self._q.get()
    def push(self, ev): self._q.put_nowait(ev)


@pytest.mark.asyncio
async def test_two_robots_visible_end_to_end(tmp_path):
    app = build_coordinator_app(db_path=tmp_path / "fleet.sqlite")
    client = TestClient(TestServer(app))
    await client.start_server()
    url = f"http://{client.host}:{client.port}/fleet"
    agents = []
    try:
        cores = [_Core("g1-sim-01"), _Core("g1-sim-02")]
        for c in cores:
            # perception loop disabled here so the only scene snapshot is the
            # manual push below (keeps the rollup assertions deterministic).
            a = RobotAgent(core=c, bus=WsFleetClient(url=url, reconnect=False),
                           heartbeat_interval_s=0.05, perception_interval_s=None)
            await a.start()
            agents.append(a)
        cores[0].push(RobotEvent.make(robot_id="g1-sim-01", trace_id="tr-1",
                                      type=EventType.SCENE_SNAPSHOT, ts="t",
                                      payload={"clear_path": False, "persons_visible": 1}))
        await asyncio.sleep(0.2)

        robots = await (await client.get("/robots")).json()
        ids = {r["robot_id"] for r in robots}
        assert ids == {"g1-sim-01", "g1-sim-02"}
        assert all(r["status"] == "online" for r in robots)

        perc = await (await client.get("/perception")).json()
        assert perc["rollup"]["robot_count"] == 1  # only sim-01 sent a scene snapshot
        assert perc["rollup"]["robots_path_blocked"] == 1
        assert perc["rollup"]["robots_with_humans"] == 1

        replay = await (await client.get("/replay/tr-1")).json()
        assert len(replay) == 1

        text = format_fleet(robots, perc["rollup"])
        assert "g1-sim-01" in text and "g1-sim-02" in text
    finally:
        for a in agents:
            await a.stop()
        await client.close()
        app["event_log"].close()
