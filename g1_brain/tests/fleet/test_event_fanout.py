import asyncio
import pytest

from g1_brain.fleet.harness_core.event_fanout import EventSink, attach_to_logger
from g1_brain.fleet.contracts.models import EventType


class _FakeLogger:
    """Minimal stand-in exposing the methods EventSink taps."""
    def __init__(self):
        self.calls = []

    def log_safety_event(self, **kw):
        self.calls.append(("safety", kw))

    def log_action_result(self, **kw):
        self.calls.append(("action", kw))


@pytest.mark.asyncio
async def test_safety_event_is_fanned_out_and_original_called():
    logger = _FakeLogger()
    sink = EventSink(robot_id="r1", maxsize=8)
    attach_to_logger(logger, sink)

    logger.log_safety_event(kind="reject", rule="RULE-9", details="too close")

    assert logger.calls == [("safety", {"kind": "reject", "rule": "RULE-9",
                                        "details": "too close"})]
    ev = await asyncio.wait_for(sink.queue.get(), timeout=1.0)
    assert ev.type == EventType.SAFETY_EVENT
    assert ev.robot_id == "r1"
    assert ev.payload["rule"] == "RULE-9"


@pytest.mark.asyncio
async def test_action_result_is_fanned_out():
    logger = _FakeLogger()
    sink = EventSink(robot_id="r1", maxsize=8)
    attach_to_logger(logger, sink)
    logger.log_action_result(tool_use_id="c1", tool_name="walk", args={"vx": 0.1},
                             status="ok", outcome_metrics={"displacement_m": 0.2})
    ev = await asyncio.wait_for(sink.queue.get(), timeout=1.0)
    assert ev.type == EventType.ACTION_RESULT
    assert ev.payload["tool_name"] == "walk"


@pytest.mark.asyncio
async def test_queue_drops_oldest_when_full():
    logger = _FakeLogger()
    sink = EventSink(robot_id="r1", maxsize=2)
    attach_to_logger(logger, sink)
    for i in range(5):
        logger.log_safety_event(kind="warn", rule=f"RULE-{i}")
    assert sink.queue.qsize() == 2
