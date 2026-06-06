"""Outbound FleetBus client (robot-agent side) with reconnect + backoff.

Backoff schedule mirrors brain/realtime_agent.py (1s -> 15s capped). The client
re-sends REGISTER on every (re)connect so a coordinator restart re-learns the
robot. heartbeat()/publish() no-op silently while disconnected (telemetry is
best-effort; local safety is unaffected).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from g1_brain.fleet.bus.messages import encode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent,
)

log = logging.getLogger(__name__)


class WsFleetClient:
    def __init__(self, *, url: str, reconnect: bool = True,
                 backoff_start: float = 1.0, backoff_max: float = 15.0):
        self._url = url
        self._reconnect = reconnect
        self._backoff_start = backoff_start
        self._backoff_max = backoff_max
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._cap: Optional[CapabilityDescriptor] = None
        self._lock = asyncio.Lock()

    async def connect(self, cap: CapabilityDescriptor) -> None:
        self._cap = cap
        if self._session is not None:
            await self._session.close()
        self._session = aiohttp.ClientSession()
        await self._open_once()

    async def _open_once(self) -> bool:
        try:
            self._ws = await self._session.ws_connect(self._url, heartbeat=30)
            await self._ws.send_str(encode_frame(FrameKind.REGISTER, self._cap))
            log.info("fleet client connected to %s", self._url)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("fleet client connect failed: %s", e)
            self._ws = None
            return False

    async def _send(self, kind: FrameKind, model) -> None:
        async with self._lock:
            if self._ws is None or self._ws.closed:
                if not self._reconnect:
                    return
                await self._reconnect_loop()
                if self._ws is None:
                    return
            try:
                await self._ws.send_str(encode_frame(kind, model))
            except Exception as e:  # noqa: BLE001
                log.warning("fleet client send failed: %s", e)
                self._ws = None

    async def _reconnect_loop(self) -> None:
        delay = self._backoff_start
        for attempt in range(6):
            if await self._open_once():
                return
            if attempt < 5:  # don't sleep after the final failed attempt
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._backoff_max)

    async def heartbeat(self, st: RobotStateMsg) -> None:
        await self._send(FrameKind.HEARTBEAT, st)

    async def publish(self, ev: RobotEvent) -> None:
        await self._send(FrameKind.EVENT, ev)

    async def register(self, cap: CapabilityDescriptor) -> None:
        self._cap = cap
        await self._send(FrameKind.REGISTER, cap)

    async def close(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()
