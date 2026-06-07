import asyncio
import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.bus.ws_server import build_fleet_app
from g1_brain.fleet.bus.ws_client import WsFleetClient
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


@pytest.mark.asyncio
async def test_client_registers_and_publishes(tmp_path):
    reg = FleetRegistry()
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    app = build_fleet_app(registry=reg, event_log=log, perception_agg=agg)
    client = TestClient(TestServer(app))
    await client.start_server()
    url = f"http://{client.host}:{client.port}/fleet"
    try:
        fc = WsFleetClient(url=url, reconnect=False)
        await fc.connect(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
        await fc.heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=1, fsm_state="ENGAGED"))
        await fc.publish(RobotEvent.make(robot_id="r1", type=EventType.SCENE_SNAPSHOT,
                                         ts="t", payload={"clear_path": True}))
        await asyncio.sleep(0.1)  # let server drain
        await fc.close()
    finally:
        await client.close()

    assert reg.status("r1") == "online"
    assert reg.latest_state("r1").fsm_state == "ENGAGED"
    assert len(log.query(robot_id="r1")) == 1
    log.close()
