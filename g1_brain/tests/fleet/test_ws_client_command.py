"""WS client: inbound COMMAND -> on_command -> ADMISSION reply (full path)."""
import asyncio

import pytest
from aiohttp.test_utils import TestServer

from g1_brain.fleet.bus.ws_server import build_fleet_app, send_command
from g1_brain.fleet.bus.ws_client import WsFleetClient
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, CommandEnvelope, AdmissionDecision,
)


async def _wait(pred, tries=300):
    for _ in range(tries):
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.mark.asyncio
async def test_client_receives_command_and_replies_admission(tmp_path):
    reg = FleetRegistry()
    log = EventLog(tmp_path / "f.sqlite"); log.init()
    agg = PerceptionAggregator(world_model=IdentityWorldModel())
    admissions = []
    app = build_fleet_app(registry=reg, event_log=log, perception_agg=agg,
                          admission_sink=admissions.append)
    server = TestServer(app)
    await server.start_server()
    try:
        url = str(server.make_url("/fleet"))
        seen = []
        client = WsFleetClient(url=url)

        async def on_command(env: CommandEnvelope) -> AdmissionDecision:
            seen.append(env)
            return AdmissionDecision(command_id=env.command_id, robot_id=env.issued_to,
                                     decision="accepted", reason_code="OK",
                                     ts="2026-06-06T00:00:00Z")
        client.on_command = on_command

        await client.connect(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
        assert await _wait(lambda: "r1" in app["fleet_conns"])

        env = CommandEnvelope.make(issued_by="coord", issued_to="r1",
                                   capability="sleep", payload={})
        await send_command(app, "r1", env)

        assert await _wait(lambda: seen and admissions), "command not handled round-trip"
        assert seen[0].command_id == env.command_id
        assert admissions[0].decision == "accepted"
        await client.close()
    finally:
        await server.close()
        log.close()
