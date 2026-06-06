"""aiohttp WebSocket server: ingest fleet frames + route down-bound commands.

Mirrors g1_brain/phone/bridge_server.py. The endpoint is bidirectional:
  up   : REGISTER / HEARTBEAT / EVENT / ADMISSION / PING
  down : COMMAND (coordinator -> robot, via send_command())

A per-robot connection registry (app["fleet_conns"]) lets the coordinator push
a CommandEnvelope to a specific robot. ADMISSION frames returned by the robot
are handed to app["admission_sink"]. There is still no center->motor path: the
robot's local AdmissionGate decides what to do with each command.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from aiohttp import web

from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    AdmissionDecision, CapabilityDescriptor, RobotStateMsg, RobotEvent,
)

log = logging.getLogger(__name__)

AdmissionSink = Callable[[AdmissionDecision], None]


def build_fleet_app(*, registry, event_log, perception_agg,
                    admission_sink: Optional[AdmissionSink] = None) -> web.Application:
    app = web.Application()
    app["registry"] = registry
    app["event_log"] = event_log
    app["perception_agg"] = perception_agg
    app["admission_sink"] = admission_sink
    app["fleet_conns"] = {}  # robot_id -> WebSocketResponse
    app.router.add_get("/fleet", _fleet_ws)
    return app


async def send_command(app: web.Application, robot_id: str, env) -> None:
    """Coordinator-side: push a CommandEnvelope to a connected robot.

    Raises KeyError if the robot has no live connection (caller decides policy,
    e.g. mark stale / skip dispatch).
    """
    ws = app["fleet_conns"].get(robot_id)
    if ws is None or ws.closed:
        raise KeyError(f"no connected robot {robot_id!r}")
    await ws.send_str(encode_frame(FrameKind.COMMAND, env))


async def _fleet_ws(request: web.Request) -> web.WebSocketResponse:
    registry = request.app["registry"]
    event_log = request.app["event_log"]
    perception_agg = request.app["perception_agg"]
    admission_sink = request.app["admission_sink"]
    conns = request.app["fleet_conns"]

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    robot_id: Optional[str] = None
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.ERROR:
                log.warning("fleet: ws error: %s", ws.exception())
                break
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                kind, model = decode_frame(msg.data)
            except Exception:
                log.warning("fleet: undecodable frame: %r", msg.data[:120], exc_info=True)
                continue
            if kind == FrameKind.REGISTER and isinstance(model, CapabilityDescriptor):
                registry.register(model)
                robot_id = model.robot_id
                conns[robot_id] = ws  # learn/refresh this robot's live connection
            elif kind == FrameKind.HEARTBEAT and isinstance(model, RobotStateMsg):
                registry.on_heartbeat(model)
            elif kind == FrameKind.EVENT and isinstance(model, RobotEvent):
                event_log.append(model)
                perception_agg.ingest(model)
            elif kind == FrameKind.ADMISSION and isinstance(model, AdmissionDecision):
                if admission_sink is not None:
                    admission_sink(model)
            elif kind == FrameKind.PING:
                await ws.send_str(encode_frame(FrameKind.PONG, None))
    finally:
        if robot_id is not None and conns.get(robot_id) is ws:
            conns.pop(robot_id, None)
    return ws
