"""COMMAND/ADMISSION wire frames + in-process LoopbackBus for Tier-1 tests."""
import asyncio

import pytest

from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.bus.loopback import LoopbackHub
from g1_brain.fleet.contracts.models import (
    CommandEnvelope, AdmissionDecision, CapabilityDescriptor, RobotStateMsg,
)


def test_command_frame_roundtrip():
    env = CommandEnvelope.make(issued_by="c", issued_to="r", capability="wake", payload={})
    kind, model = decode_frame(encode_frame(FrameKind.COMMAND, env))
    assert kind == FrameKind.COMMAND
    assert model == env


def test_admission_frame_roundtrip():
    d = AdmissionDecision(command_id="c1", robot_id="r", decision="accepted",
                          reason_code="OK", reason_detail="", ts="2026-06-06T00:00:00Z")
    kind, model = decode_frame(encode_frame(FrameKind.ADMISSION, d))
    assert kind == FrameKind.ADMISSION
    assert model == d


@pytest.mark.asyncio
async def test_loopback_register_heartbeat_publish():
    hub = LoopbackHub()
    bus = hub.client()
    cap = CapabilityDescriptor(robot_id="g1_a", harness_version="0.1.0", frame_id="g1_a/map")
    await bus.connect(cap)
    assert any(r["robot_id"] == "g1_a" for r in hub.registry.list_robots())
    await bus.heartbeat(RobotStateMsg(robot_id="g1_a", ts="2026-06-06T00:00:00Z", seq=1))
    assert hub.registry.latest_state("g1_a").seq == 1


@pytest.mark.asyncio
async def test_loopback_send_command_routes_to_robot_and_back():
    hub = LoopbackHub()
    seen = []
    decisions = []
    hub.admission_sink = decisions.append

    bus = hub.client()
    cap = CapabilityDescriptor(robot_id="g1_a", harness_version="0.1.0", frame_id="g1_a/map")
    await bus.connect(cap)

    async def on_command(env: CommandEnvelope) -> AdmissionDecision:
        seen.append(env)
        return AdmissionDecision(command_id=env.command_id, robot_id=env.issued_to,
                                 decision="accepted", reason_code="OK",
                                 ts="2026-06-06T00:00:00Z")
    bus.on_command = on_command

    env = CommandEnvelope.make(issued_by="coord", issued_to="g1_a", capability="sleep", payload={})
    await hub.send_command("g1_a", env)
    await asyncio.sleep(0)  # let delivery settle

    assert len(seen) == 1 and seen[0].capability == "sleep"
    assert len(decisions) == 1 and decisions[0].decision == "accepted"


@pytest.mark.asyncio
async def test_loopback_send_to_unknown_robot_raises():
    hub = LoopbackHub()
    env = CommandEnvelope.make(issued_by="coord", issued_to="ghost", capability="wake", payload={})
    with pytest.raises(KeyError):
        await hub.send_command("ghost", env)
