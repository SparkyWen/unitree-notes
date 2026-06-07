"""Headless robot-agent: bridges a HarnessCore to a FleetBus client.

Read-only slice: it ONLY reports (register + heartbeat + forward events). It does
not accept commands; there is no path from the bus into the SkillServer.

Real-process wiring (not unit-tested here): a headless HarnessCore is built by
reusing agent_main's DDS/combo/perception/safety init while SKIPPING the Realtime
brain, codex memory, and phone subsystems. That assembly is exercised in sim via
`python -m g1_brain.fleet.agent.robot_agent --config <cfg> --coordinator <url>`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from g1_brain.fleet.agent.event_builder import build_perception_events

log = logging.getLogger(__name__)


class RobotAgent:
    def __init__(self, *, core, bus, heartbeat_interval_s: float = 2.0,
                 perception_interval_s: Optional[float] = 1.0,
                 tick_interval_s: Optional[float] = None):
        self._core = core
        self._bus = bus
        self._hb_interval = heartbeat_interval_s
        self._perc_interval = perception_interval_s
        self._tick_interval = tick_interval_s
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._seq = 0

    async def start(self) -> None:
        # Wire the down-bound command path: the bus hands inbound CommandEnvelopes
        # to the harness's local AdmissionGate (the robot's final authority).
        if hasattr(self._bus, "on_command") and hasattr(self._core, "on_command"):
            self._bus.on_command = self._core.on_command
        await self._bus.connect(self._core.get_capabilities())
        self._tasks = [
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._event_loop()),
        ]
        if self._perc_interval is not None:
            self._tasks.append(asyncio.create_task(self._perception_loop()))
        if self._tick_interval is not None and hasattr(self._core, "tick"):
            self._tasks.append(asyncio.create_task(self._tick_loop()))

    async def _tick_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._core.tick()
            except Exception:  # noqa: BLE001
                log.exception("core tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_interval)
            except asyncio.TimeoutError:
                pass

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            self._seq += 1
            try:
                await self._bus.heartbeat(self._core.get_state(seq=self._seq))
            except Exception:  # noqa: BLE001
                log.exception("heartbeat failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._hb_interval)
            except asyncio.TimeoutError:
                pass

    async def _event_loop(self) -> None:
        async for ev in self._core.subscribe_events():
            if self._stop.is_set():
                break
            try:
                await self._bus.publish(ev)
            except Exception:  # noqa: BLE001
                log.exception("event publish failed")

    async def _perception_loop(self) -> None:
        while not self._stop.is_set():
            try:
                scene = self._core.snapshot_scene()
                for ev in build_perception_events(self._core.robot_id, scene):
                    await self._bus.publish(ev)
            except Exception:  # noqa: BLE001
                log.exception("perception publish failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._perc_interval)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass  # expected: we explicitly cancelled this task
            except Exception:  # noqa: BLE001
                log.exception("robot-agent task exited with error")
        await self._bus.close()
