"""Compose the coordinator: WS ingest (/fleet) + read-only JSON API."""
from __future__ import annotations

from pathlib import Path

from aiohttp import web

from g1_brain.fleet.bus.ws_server import build_fleet_app
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel


def build_coordinator_app(*, db_path: Path) -> web.Application:
    registry = FleetRegistry()
    event_log = EventLog(db_path)
    event_log.init()
    perception_agg = PerceptionAggregator(world_model=IdentityWorldModel())

    app = build_fleet_app(registry=registry, event_log=event_log,
                          perception_agg=perception_agg)

    async def _close_event_log(_app: web.Application) -> None:
        event_log.close()  # idempotent

    app.on_cleanup.append(_close_event_log)

    app.router.add_get("/robots", _robots)
    app.router.add_get("/robots/{rid}", _robot)
    app.router.add_get("/events", _events)
    app.router.add_get("/replay/{trace_id}", _replay)
    app.router.add_get("/perception", _perception)
    return app


async def _robots(request: web.Request) -> web.Response:
    return web.json_response(request.app["registry"].list_robots())


async def _robot(request: web.Request) -> web.Response:
    rid = request.match_info["rid"]
    for r in request.app["registry"].list_robots():
        if r["robot_id"] == rid:
            return web.json_response(r)
    return web.json_response({"error": "unknown robot"}, status=404)


async def _events(request: web.Request) -> web.Response:
    q = request.query
    try:
        limit = int(q.get("limit", "500"))
    except ValueError:
        raise web.HTTPBadRequest(reason="limit must be an integer")
    rows = request.app["event_log"].query(
        robot_id=q.get("robot_id"), trace_id=q.get("trace_id"),
        since=q.get("since"), until=q.get("until"),
        limit=limit,
    )
    return web.json_response([e.model_dump(mode="json") for e in rows])


async def _replay(request: web.Request) -> web.Response:
    rows = request.app["event_log"].replay(request.match_info["trace_id"])
    return web.json_response([e.model_dump(mode="json") for e in rows])


async def _perception(request: web.Request) -> web.Response:
    agg = request.app["perception_agg"]
    return web.json_response({"rollup": agg.rollup()})
