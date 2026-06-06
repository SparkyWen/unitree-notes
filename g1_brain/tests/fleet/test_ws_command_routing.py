"""WS server: per-robot command routing (down) + admission routing (up)."""
import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.fleet.bus.ws_server import build_fleet_app, send_command
from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, CommandEnvelope, AdmissionDecision,
)


@pytest.fixture
def deps(tmp_path):
    reg = FleetRegistry()
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    yield reg, log, agg
    log.close()


async def _wait(pred, tries=200):
    for _ in range(tries):
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.mark.asyncio
async def test_command_routed_to_robot_and_admission_back(deps):
    reg, log, agg = deps
    admissions = []
    app = build_fleet_app(registry=reg, event_log=log, perception_agg=agg,
                          admission_sink=admissions.append)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/fleet")
        await ws.send_str(encode_frame(FrameKind.REGISTER,
                          CapabilityDescriptor(robot_id="r1", frame_id="r1/map")))
        assert await _wait(lambda: "r1" in app["fleet_conns"]), "robot conn not registered"

        env = CommandEnvelope.make(issued_by="coord", issued_to="r1",
                                   capability="sleep", payload={"reason": "overheat"})
        await send_command(app, "r1", env)
        frame = await ws.receive_str()
        kind, model = decode_frame(frame)
        assert kind == FrameKind.COMMAND and model.command_id == env.command_id

        dec = AdmissionDecision(command_id=env.command_id, robot_id="r1",
                                decision="accepted", reason_code="OK",
                                ts="2026-06-06T00:00:00Z")
        await ws.send_str(encode_frame(FrameKind.ADMISSION, dec))
        assert await _wait(lambda: len(admissions) == 1), "admission not routed"
        assert admissions[0].decision == "accepted"
        await ws.close()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_send_command_unknown_robot_raises(deps):
    reg, log, agg = deps
    app = build_fleet_app(registry=reg, event_log=log, perception_agg=agg)
    with pytest.raises(KeyError):
        await send_command(app, "ghost", CommandEnvelope.make(
            issued_by="c", issued_to="ghost", capability="wake", payload={}))


@pytest.mark.asyncio
async def test_disconnect_removes_conn(deps):
    reg, log, agg = deps
    app = build_fleet_app(registry=reg, event_log=log, perception_agg=agg)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        ws = await client.ws_connect("/fleet")
        await ws.send_str(encode_frame(FrameKind.REGISTER,
                          CapabilityDescriptor(robot_id="r2", frame_id="r2/map")))
        assert await _wait(lambda: "r2" in app["fleet_conns"])
        await ws.close()
        assert await _wait(lambda: "r2" not in app["fleet_conns"]), "conn not cleaned up"
    finally:
        await client.close()
