"""Tap ConversationLogger's meta loggers and fan out as RobotEvent.

Zero-impact: each wrapper calls the original method first, then enqueues a
RobotEvent. The queue is bounded; on overflow we drop the OLDEST event to
protect the newest (best-effort, never blocks the caller).

Only JSON-safe loggers are tapped (log_safety_event, log_action_result).
Perception/scene events are produced by the robot-agent's perception loop
(a later task), not here, because log_scene_snapshot carries a live
non-JSON SceneState object.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from g1_brain.fleet.contracts.models import EventType, RobotEvent

log = logging.getLogger(__name__)


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class EventSink:
    def __init__(self, *, robot_id: str, maxsize: int = 256):
        self.robot_id = robot_id
        self.queue: "asyncio.Queue[RobotEvent]" = asyncio.Queue(maxsize=maxsize)

    def emit(self, type_: EventType, payload: Dict[str, Any],
             trace_id: str | None = None) -> None:
        ev = RobotEvent.make(robot_id=self.robot_id, type=type_, ts=_iso_now(),
                             payload=payload, trace_id=trace_id)
        try:
            self.queue.put_nowait(ev)
        except asyncio.QueueFull:
            # Drop oldest to make room; protects newest safety/action events.
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(ev)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                log.warning("event fan-out dropped %s", type_)


def attach_to_logger(logger: Any, sink: EventSink) -> None:
    """Wrap logger.log_* so each call also enqueues a RobotEvent."""

    def _wrap(method_name: str, ev_type: EventType):
        original = getattr(logger, method_name, None)
        if original is None:
            return

        def wrapped(**kw):
            original(**kw)
            sink.emit(ev_type, dict(kw))

        setattr(logger, method_name, wrapped)

    # Only JSON-safe loggers are tapped. Perception/scene events are produced by
    # the robot-agent's perception loop (a later task), not here.
    _wrap("log_safety_event", EventType.SAFETY_EVENT)
    _wrap("log_action_result", EventType.ACTION_RESULT)
