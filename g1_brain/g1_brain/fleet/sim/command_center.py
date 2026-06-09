"""AI 指挥调度中心 — live command center for the shared-world G1 fleet.

One launcher wires four things together so you can *watch the robots and command
them in real time*:

  • a live shared MuJoCo world (two RL G1s @50 Hz)            — WorldSim
  • a MuJoCo 3D passive viewer (--viewer)                     — 你实时看到的3D
  • a web control center (top-down 2D map + chat + events)    — 网页控制台
  • the codex brain as the fleet commander                    — 你的AI在调度

Flow per operator request: 浏览器 POST /command → FleetCommander(codex) 规划 →
RobotSubAgent 展开 ops → LiveExecutor 抢占式驱动 WorldSim → 机器人在3D窗口里动，
俯视图与事件流实时更新。

  # headless (deterministic planner, no codex, no window):
  conda run -n agi python -m g1_brain.fleet.sim.command_center --no-codex
  # full experience (codex brain + 3D window + web console):
  conda run -n agi python -m g1_brain.fleet.sim.command_center --viewer
  then open http://127.0.0.1:8787/
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

from aiohttp import web

from g1_brain.fleet.coordinator.choreographer import plan_mission
from g1_brain.fleet.sim.command_center_ui import INDEX_HTML
from g1_brain.fleet.sim.live_executor import LiveExecutor


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _world_snapshot(world) -> dict:
    """Commander's fleet snapshot: robot poses (x,y,yaw) + named landmarks."""
    snap = {"robots": [{"robot_id": rid, "x": t["pose"][0], "y": t["pose"][1],
                        "yaw": t["pose"][2]}
                       for rid, t in world.telemetry().items()]}
    if hasattr(world, "landmarks"):
        snap["landmarks"] = world.landmarks()
    return snap


def build_command_center_app(world, *, llm=None, subagent_llm=None,
                             start_loop: bool = True) -> web.Application:
    """Wire the control-center HTTP app around a live ``world``.

    ``llm`` is the FleetCommander brain (CodexFleetLLM in production, None =
    deterministic). Sub-agents default to deterministic op expansion. With
    ``start_loop`` the LiveExecutor's control loop runs as a background task that
    drives the current mission (and is preempted whenever /command submits)."""
    app = web.Application()
    app["world"] = world
    app["commander_llm"] = llm           # codex (or None) — plan_mission drives it
    app["subagent_llm"] = subagent_llm
    events: deque = deque(maxlen=300)
    app["events"] = events
    executor = LiveExecutor(world, on_event=lambda msg: events.append(
        {"ts": _now(), "msg": msg}))
    app["executor"] = executor

    app.router.add_get("/", _index)
    app.router.add_get("/world", _world)
    app.router.add_get("/events", _events)
    app.router.add_get("/scene", _scene)
    app.router.add_post("/command", _command)

    if start_loop:
        async def _start(_app: web.Application) -> None:
            _app["loop_task"] = asyncio.create_task(executor.run())

        async def _stop(_app: web.Application) -> None:
            t = _app.get("loop_task")
            if t is not None:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

        app.on_startup.append(_start)
        app.on_cleanup.append(_stop)
    return app


# ---- handlers ----

async def _index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def _world(request: web.Request) -> web.Response:
    tel = request.app["world"].telemetry()
    robots = []
    for rid, t in tel.items():
        x, y, yaw = t["pose"]
        robots.append({"robot_id": rid, "x": float(x), "y": float(y),
                       "yaw": float(yaw), "posture": t.get("posture"),
                       "activity": t.get("activity"), "gz": t.get("gz")})
    m = request.app["executor"].mission
    mission = None
    if m is not None:
        c = m.plan.coordination
        mission = {"summary": m.plan.summary, "type": c.type,
                   "point": list(c.point) if c.point else None,
                   "complete": m.complete,
                   "min_sep": (None if m.min_sep >= 99 else round(m.min_sep, 2)),
                   "ops": {rid: [o.op for o in ops] for rid, ops in m.ops.items()},
                   "cur": {rid: m.current_op(rid) for rid in m.ops}}
    return web.json_response({"robots": robots, "mission": mission})


async def _scene(request: web.Request) -> web.Response:
    world = request.app["world"]
    geoms = world.scene_render() if hasattr(world, "scene_render") else []
    lms = world.landmarks() if hasattr(world, "landmarks") else {}
    return web.json_response({"geoms": geoms,
                              "landmarks": {k: list(v) for k, v in lms.items()}})


async def _events(request: web.Request) -> web.Response:
    return web.json_response({"events": list(request.app["events"])})


async def _command(request: web.Request) -> web.Response:
    body = await request.json()
    nl = (body.get("nl") or "").strip()
    if not nl:
        return web.json_response({"ok": False, "reason": "empty command"}, status=400)
    app = request.app
    snapshot = _world_snapshot(app["world"])
    llm, sub_llm = app["commander_llm"], app["subagent_llm"]
    # codex planning can take seconds (xhigh reasoning); never block the event
    # loop — run the (sync) planner, which may call codex, in a thread.
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(
        None, lambda: plan_mission(nl, snapshot, llm=llm, sub_llm=sub_llm))
    if not res["ok"]:
        msg = res.get("needs_clarification") or res.get("reason") or "无法执行"
        app["events"].append({"ts": _now(), "msg": f"指挥官: {msg}"})
        return web.json_response({"ok": False, "needs_clarification": res.get("needs_clarification"),
                                  "reason": res.get("reason")})
    plan, ops = res["plan"], res["ops"]
    app["executor"].submit(plan, ops)   # preempts any running mission
    return web.json_response({
        "ok": True, "summary": plan.summary, "plan": plan.model_dump(),
        "ops": {rid: [o.model_dump() for o in ol] for rid, ol in ops.items()}})


# ---- launcher ----

def _build_codex_llm(model: str, reasoning: str, workdir: Path):
    from g1_brain.fleet.coordinator.codex_fleet_llm import CodexFleetLLM
    llm = CodexFleetLLM(model=model, reasoning=reasoning, workdir=workdir)
    if not llm.is_available():
        print("[command-center] codex 未找到，退回确定性规划 (--no-codex)", flush=True)
        return None
    print(f"[command-center] AI 大脑: codex {model} (reasoning={reasoning})", flush=True)
    return llm


def _serve_in_thread(app: web.Application, host: str, port: int) -> dict:
    """Run the aiohttp app on its own event loop in a daemon thread (the main
    thread is reserved for the MuJoCo viewer). Returns once the site is up."""
    ready = threading.Event()
    state: dict = {}

    def serve():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, host, port)
        loop.run_until_complete(site.start())
        state.update(loop=loop, runner=runner)
        ready.set()
        loop.run_forever()

    threading.Thread(target=serve, daemon=True).start()
    ready.wait(15)
    return state


def run(*, viewer: bool = False, host: str = "127.0.0.1", port: int = 8787,
        use_codex: bool = True, model: str = "gpt-5.5", reasoning: str = "xhigh",
        scene: str = "demo", solo: bool = False) -> None:
    import webbrowser
    from g1_brain.fleet.sim.shared_world_node import WorldSim, trim_render_cost

    robot_ids = ("g1_a",) if solo else ("g1_a", "g1_b")
    sim = WorldSim(robot_ids=robot_ids, scene=scene)  # control loop not started yet
    llm = _build_codex_llm(model, reasoning, Path.cwd()) if use_codex else None
    app = build_command_center_app(sim, llm=llm)
    state = _serve_in_thread(app, host, port)
    url = f"http://{host}:{port}/"
    print("\n" + "=" * 60, flush=True)
    print(f"[command-center] 控制台 / console:  {url}", flush=True)
    print(f"[command-center] 场景 scene={scene}  机器人 {list(robot_ids)}"
          + ("  (solo)" if solo else ""), flush=True)
    print("[command-center] 试试 / try:  g1_a 走到 2,1 · 去红色柱子 · "
          "两机都去集合点 · 顺时针绕圈", flush=True)
    print("=" * 60 + "\n", flush=True)
    try:
        webbrowser.open(url)               # best-effort; harmless if headless
    except Exception:                       # noqa: BLE001
        pass
    try:
        if viewer:
            os.environ.setdefault("MUJOCO_GL", "glfw")
            import mujoco
            import mujoco.viewer
            trim_render_cost(sim.world.m)  # cut render cost BEFORE the GL context is built
            with mujoco.viewer.launch_passive(sim.world.m, sim.world.d) as v:
                # step physics under the viewer's lock, and only AFTER the viewer
                # exists, so the render-thread mjData copy never races mj_step.
                sim.set_render_lock(v.lock())
                sim.start()
                while v.is_running():
                    v.sync()
                    time.sleep(1 / 60)
        else:
            sim.start()
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
        loop = state.get("loop")
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)


def main() -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description="AI 指挥调度中心 (live command center)")
    ap.add_argument("--viewer", action="store_true", help="open the MuJoCo 3D window")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-codex", action="store_true",
                    help="use the deterministic planner instead of the codex brain")
    ap.add_argument("--model", default="gpt-5.5", help="codex model (account's working model)")
    ap.add_argument("--reasoning", default="xhigh",
                    help="codex reasoning effort: minimal|low|medium|high|xhigh")
    ap.add_argument("--scene", default="demo", choices=["bare", "demo"],
                    help="arena scene (demo = props + terrain; bare = flat)")
    ap.add_argument("--solo", action="store_true",
                    help="single robot (g1_a) for solo performance testing")
    args = ap.parse_args()
    run(viewer=args.viewer, host=args.host, port=args.port,
        use_codex=not args.no_codex, model=args.model, reasoning=args.reasoning,
        scene=args.scene, solo=args.solo)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
