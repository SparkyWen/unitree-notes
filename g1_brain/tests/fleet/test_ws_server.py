import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.bus.ws_server import build_fleet_app
from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


@pytest.fixture
def deps(tmp_path):
    reg = FleetRegistry()
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    yield reg, log, agg
    log.close()


@pytest.mark.asyncio
async def test_register_heartbeat_event_routed(deps):
    reg, log, agg = deps
    app = build_fleet_app(registry=reg, event_log=log, perception_agg=agg)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/fleet")
        await ws.send_str(encode_frame(FrameKind.REGISTER,
                          CapabilityDescriptor(robot_id="r1", frame_id="r1/map")))
        await ws.send_str(encode_frame(FrameKind.HEARTBEAT,
                          RobotStateMsg(robot_id="r1", ts="t", seq=1, fsm_state="ENGAGED")))
        await ws.send_str(encode_frame(FrameKind.EVENT,
                          RobotEvent.make(robot_id="r1", type=EventType.SCENE_SNAPSHOT,
                                          ts="t", payload={"clear_path": False,
                                                           "persons_visible": 1})))
        await ws.send_str(encode_frame(FrameKind.PING, None))
        reply = await ws.receive_str()
        kind, _ = decode_frame(reply)
        assert kind == FrameKind.PONG
        await ws.close()
    finally:
        await client.close()

    assert reg.latest_state("r1").fsm_state == "ENGAGED"
    assert reg.status("r1") == "online"
    assert len(log.query(robot_id="r1")) == 1
    assert agg.latest("r1")["clear_path"] is False


@pytest.mark.asyncio
async def test_malformed_frame_does_not_crash(deps):
    reg, log, agg = deps
    app = build_fleet_app(registry=reg, event_log=log, perception_agg=agg)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/fleet")
        await ws.send_str("not-json-at-all")          # undecodable; must be skipped
        await ws.send_str(encode_frame(FrameKind.PING, None))
        reply = await ws.receive_str()                # PONG proves handler still alive
        kind, _ = decode_frame(reply)
        assert kind == FrameKind.PONG
        await ws.close()
    finally:
        await client.close()
