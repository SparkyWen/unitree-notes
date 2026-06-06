"""aiohttp WebSocket server: ingest fleet frames into coordinator services.

Mirrors the structure of g1_brain/phone/bridge_server.py. No control path back
to robots exists; this endpoint is strictly inbound (telemetry up).
"""
from __future__ import annotations

import logging

from aiohttp import web

from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent,
)

log = logging.getLogger(__name__)


def build_fleet_app(*, registry, event_log, perception_agg) -> web.Application:
    app = web.Application()
    app["registry"] = registry
    app["event_log"] = event_log
    app["perception_agg"] = perception_agg
    app.router.add_get("/fleet", _fleet_ws)
    return app


async def _fleet_ws(request: web.Request) -> web.WebSocketResponse:
    registry = request.app["registry"]
    event_log = request.app["event_log"]
    perception_agg = request.app["perception_agg"]

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
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
        elif kind == FrameKind.HEARTBEAT and isinstance(model, RobotStateMsg):
            registry.on_heartbeat(model)
        elif kind == FrameKind.EVENT and isinstance(model, RobotEvent):
            event_log.append(model)
            perception_agg.ingest(model)
        elif kind == FrameKind.PING:
            await ws.send_str(encode_frame(FrameKind.PONG, None))
    return ws
