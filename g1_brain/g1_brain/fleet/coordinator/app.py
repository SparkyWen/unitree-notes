"""Compose the coordinator: WS ingest (/fleet) + read-only API + dispatch.

Read-only routes (unchanged): /robots, /events, /replay, /perception.
Dispatch routes (closed-loop slice): POST /missions, POST /commands,
GET /anomalies, GET /dispatch. A background task ticks the DispatchController
so anomalies are perceived + acted on autonomously.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable, Optional

from aiohttp import web

from g1_brain.fleet.bus.ws_server import build_fleet_app, send_command
from g1_brain.fleet.coordinator.agent_llm import CoordinatorAgent, StructuredOp
from g1_brain.fleet.coordinator.anomaly import AnomalyDetector
from g1_brain.fleet.coordinator.controller import DispatchController
from g1_brain.fleet.coordinator.dashboard import INDEX_HTML
from g1_brain.fleet.coordinator.dispatch import DispatchEngine
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.coordinator.gateway import CommandGateway
from g1_brain.fleet.coordinator.lease import LeaseManager
from g1_brain.fleet.coordinator.perception_agg import PerceptionAggregator
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.coordinator.world_model import IdentityWorldModel
from g1_brain.fleet.contracts.models import Mission

log = logging.getLogger(__name__)


def _build_llm() -> Optional[object]:
    """Best-effort LLM adapter; None (degrade to grammar) if no key/SDK."""
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        from g1_brain.fleet.coordinator.agent_llm import OpenAIChatLLM
        return OpenAIChatLLM()
    except Exception:  # noqa: BLE001
        log.warning("LLM adapter unavailable; using command grammar", exc_info=True)
        return None


def build_coordinator_app(*, db_path: Path, tick_interval_s: float = 1.0,
                          inject_hook: Optional[Callable[..., None]] = None,
                          llm: Optional[object] = "auto") -> web.Application:
    registry = FleetRegistry()
    event_log = EventLog(db_path)
    event_log.init()
    perception_agg = PerceptionAggregator(world_model=IdentityWorldModel())

    app = build_fleet_app(registry=registry, event_log=event_log,
                          perception_agg=perception_agg)

    # Dispatch brain. The gateway sends down-bound commands via the WS server's
    # per-robot routing; admission replies flow back into gateway.record_admission.
    async def _send(robot_id, env):
        await send_command(app, robot_id, env)

    gateway = CommandGateway(send_command=_send, event_log=event_log)
    app["admission_sink"] = gateway.record_admission  # ws_server reads this live

    agent = CoordinatorAgent(llm=(_build_llm() if llm == "auto" else llm))
    # Anomaly thresholds are env-overridable. A band-suspended sim rig (no
    # balance policy) legitimately tilts during posture changes, so the GUI/DDS
    # demo relaxes the fall threshold via FLEET_FALL_GZ; a real free-standing
    # robot keeps the default and relies on fall detection.
    detector = AnomalyDetector(
        battery_hot_c=float(os.environ.get("FLEET_BATTERY_HOT_C", "70.0")),
        motor_hot_c=float(os.environ.get("FLEET_MOTOR_HOT_C", "80.0")),
        soc_min=float(os.environ.get("FLEET_SOC_MIN", "0.15")),
        fall_gz=float(os.environ.get("FLEET_FALL_GZ", "-0.85")))
    controller = DispatchController(
        registry=registry, detector=detector,
        engine=DispatchEngine(registry), gateway=gateway, event_log=event_log,
        lease=LeaseManager(), agent=agent, inject_hook=inject_hook)
    app["controller"] = controller
    app["gateway"] = gateway

    # web dashboard (browser view) + read-only routes
    app.router.add_get("/", _index)
    app.router.add_get("/robots", _robots)
    app.router.add_get("/robots/{rid}", _robot)
    app.router.add_get("/events", _events)
    app.router.add_get("/replay/{trace_id}", _replay)
    app.router.add_get("/perception", _perception)
    # dispatch routes
    app.router.add_post("/missions", _missions)
    app.router.add_post("/commands", _commands)
    app.router.add_get("/anomalies", _anomalies)
    app.router.add_get("/dispatch", _dispatch)

    async def _close_event_log(_app: web.Application) -> None:
        event_log.close()

    async def _start_tick(_app: web.Application) -> None:
        if tick_interval_s and tick_interval_s > 0:
            _app["tick_task"] = asyncio.create_task(_tick_loop(controller, tick_interval_s))

    async def _stop_tick(_app: web.Application) -> None:
        t = _app.get("tick_task")
        if t is not None:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    app.on_startup.append(_start_tick)
    app.on_cleanup.append(_stop_tick)
    app.on_cleanup.append(_close_event_log)
    return app


async def _tick_loop(controller: DispatchController, interval: float) -> None:
    while True:
        try:
            await controller.tick()
        except Exception:  # noqa: BLE001
            log.exception("dispatch tick failed")
        await asyncio.sleep(interval)


# ---- web dashboard ----

async def _index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html")


# ---- read-only handlers ----

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
        since=q.get("since"), until=q.get("until"), limit=limit)
    return web.json_response([e.model_dump(mode="json") for e in rows])


async def _replay(request: web.Request) -> web.Response:
    rows = request.app["event_log"].replay(request.match_info["trace_id"])
    return web.json_response([e.model_dump(mode="json") for e in rows])


async def _perception(request: web.Request) -> web.Response:
    return web.json_response({"rollup": request.app["perception_agg"].rollup()})


# ---- dispatch handlers ----

async def _missions(request: web.Request) -> web.Response:
    body = await request.json()
    mission = Mission.model_validate(body)
    result = await request.app["controller"].dispatch_mission(mission)
    return web.json_response(result)


async def _commands(request: web.Request) -> web.Response:
    body = await request.json()
    controller: DispatchController = request.app["controller"]
    op_kind = body.get("op")
    # debug/sim affordance: inject synthesized telemetry into a robot
    if op_kind == "inject":
        robot = body.get("robot") or (body.get("args") or {}).get("robot")
        kw = {k: v for k, v in body.items() if k not in ("op", "robot", "args")}
        kw.update({k: v for k, v in (body.get("args") or {}).items() if k != "robot"})
        controller.inject(robot, **kw)
        return web.json_response({"ok": True, "injected": robot})
    if "nl" in body:
        op = controller.agent.parse(body["nl"])
        if op is None:
            return web.json_response({"ok": False, "reason": "unparseable"}, status=200)
    else:
        op = StructuredOp(kind=op_kind, args=body.get("args", {}))
    result = await controller.run_op(op)
    return web.json_response(result)


async def _anomalies(request: web.Request) -> web.Response:
    return web.json_response({"anomalies": request.app["controller"].snapshot()["anomalies"]})


async def _dispatch(request: web.Request) -> web.Response:
    return web.json_response(request.app["controller"].snapshot())
