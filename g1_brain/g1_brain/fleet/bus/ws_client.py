"""Outbound FleetBus client (robot-agent side) with reconnect + backoff.

Backoff schedule mirrors brain/realtime_agent.py (1s -> 15s capped). The client
re-sends REGISTER on every (re)connect so a coordinator restart re-learns the
robot. heartbeat()/publish() no-op silently while disconnected (telemetry is
best-effort; local safety is unaffected).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

import aiohttp

from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    AdmissionDecision, CapabilityDescriptor, CommandEnvelope, RobotStateMsg,
    RobotEvent,
)

log = logging.getLogger(__name__)

OnCommand = Callable[[CommandEnvelope], Awaitable[Optional[AdmissionDecision]]]


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
        # Set by RobotAgent: handles down-bound commands, returns the decision.
        self.on_command: Optional[OnCommand] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._closing = False

    async def connect(self, cap: CapabilityDescriptor) -> None:
        self._cap = cap
        self._closing = False
        if self._session is not None:
            await self._session.close()
        self._session = aiohttp.ClientSession()
        await self._open_once()
        if self._recv_task is None:
            self._recv_task = asyncio.create_task(self._recv_loop())

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

    async def _recv_loop(self) -> None:
        """Own the read side: dispatch inbound COMMAND frames to on_command and
        reply with an ADMISSION. Survives reconnects (follows self._ws)."""
        while not self._closing:
            ws = self._ws
            if ws is None or ws.closed:
                await asyncio.sleep(0.05)
                continue
            try:
                msg = await ws.receive()
            except Exception:  # noqa: BLE001
                await asyncio.sleep(0.05)
                continue
            if msg.type != aiohttp.WSMsgType.TEXT:
                # CLOSE/CLOSING/CLOSED/ERROR/PING/PONG -> let _send handle reconnect
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    await asyncio.sleep(0.05)
                continue
            try:
                kind, model = decode_frame(msg.data)
            except Exception:  # noqa: BLE001
                log.warning("fleet client: undecodable frame", exc_info=True)
                continue
            if kind == FrameKind.COMMAND and isinstance(model, CommandEnvelope):
                if self.on_command is None:
                    continue
                try:
                    decision = await self.on_command(model)
                except Exception:  # noqa: BLE001
                    log.exception("on_command raised")
                    decision = None
                if decision is not None:
                    await self._send(FrameKind.ADMISSION, decision)

    async def close(self) -> None:
        self._closing = True
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._recv_task = None
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()
