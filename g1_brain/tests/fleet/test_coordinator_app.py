import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.coordinator.app import build_coordinator_app
from g1_brain.fleet.bus.messages import encode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


@pytest.mark.asyncio
async def test_readonly_routes(tmp_path):
    app = build_coordinator_app(db_path=tmp_path / "fleet.sqlite")
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/fleet")
        await ws.send_str(encode_frame(FrameKind.REGISTER,
                          CapabilityDescriptor(robot_id="r1", frame_id="r1/map")))
        await ws.send_str(encode_frame(FrameKind.HEARTBEAT,
                          RobotStateMsg(robot_id="r1", ts="t", seq=1, fsm_state="ENGAGED")))
        await ws.send_str(encode_frame(FrameKind.EVENT,
                          RobotEvent.make(robot_id="r1", trace_id="trace-1",
                                          type=EventType.SCENE_SNAPSHOT, ts="t",
                                          payload={"clear_path": False, "persons_visible": 1})))
        await ws.close()
        await asyncio.sleep(0.05)

        robots = await (await client.get("/robots")).json()
        assert robots[0]["robot_id"] == "r1" and robots[0]["status"] == "online"

        one = await (await client.get("/robots/r1")).json()
        assert one["state"]["fsm_state"] == "ENGAGED"

        events = await (await client.get("/events?robot_id=r1")).json()
        assert len(events) == 1

        replay = await (await client.get("/replay/trace-1")).json()
        assert replay[0]["trace_id"] == "trace-1"

        perc = await (await client.get("/perception")).json()
        assert perc["rollup"]["robots_path_blocked"] == 1
    finally:
        await client.close()
        app["event_log"].close()
