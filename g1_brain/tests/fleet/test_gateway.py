"""CommandGateway: idempotent issue + event-log lifecycle records."""
import pytest

from g1_brain.fleet.coordinator.gateway import CommandGateway
from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.contracts.models import (
    CommandEnvelope, AdmissionDecision, EventType,
)


def _log(tmp_path):
    log = EventLog(tmp_path / "e.sqlite")
    log.init()
    return log


@pytest.mark.asyncio
async def test_issue_records_and_sends(tmp_path):
    sent = []

    async def transport(rid, env):
        sent.append((rid, env))

    log = _log(tmp_path)
    gw = CommandGateway(send_command=transport, event_log=log)
    env = CommandEnvelope.make(issued_by="c", issued_to="r1", capability="sleep",
                               payload={}, trace_id="tr")
    assert await gw.issue(env) is True
    assert sent and sent[0][0] == "r1"
    evs = log.query(robot_id="r1")
    issued = [e for e in evs if e.type == EventType.COMMAND_ISSUED]
    assert issued and issued[0].trace_id == "tr"


@pytest.mark.asyncio
async def test_issue_idempotent(tmp_path):
    sent = []

    async def transport(rid, env):
        sent.append(env)

    gw = CommandGateway(send_command=transport, event_log=_log(tmp_path))
    env = CommandEnvelope.make(issued_by="c", issued_to="r1", capability="idle",
                               payload={}, idempotency_key="k1")
    assert await gw.issue(env) is True
    env2 = CommandEnvelope.make(issued_by="c", issued_to="r1", capability="idle",
                                payload={}, idempotency_key="k1")
    assert await gw.issue(env2) is False  # duplicate
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_record_admission_correlates_trace(tmp_path):
    async def transport(rid, env):
        pass

    log = _log(tmp_path)
    gw = CommandGateway(send_command=transport, event_log=log)
    env = CommandEnvelope.make(issued_by="c", issued_to="r1", capability="sleep",
                               payload={}, trace_id="tr")
    await gw.issue(env)
    gw.record_admission(AdmissionDecision(command_id=env.command_id, robot_id="r1",
                                          decision="accepted", reason_code="OK",
                                          ts="2026-06-06T00:00:00Z"))
    evs = log.query(robot_id="r1")
    acc = [e for e in evs if e.type == EventType.COMMAND_ACCEPTED]
    assert acc and acc[0].trace_id == "tr"  # correlated via command_id


@pytest.mark.asyncio
async def test_record_admission_refused(tmp_path):
    async def transport(rid, env):
        pass

    log = _log(tmp_path)
    gw = CommandGateway(send_command=transport, event_log=log)
    env = CommandEnvelope.make(issued_by="c", issued_to="r1", capability="patrol",
                               payload={})
    await gw.issue(env)
    gw.record_admission(AdmissionDecision(command_id=env.command_id, robot_id="r1",
                                          decision="refused", reason_code="FSM_FORBIDDEN",
                                          ts="t"))
    evs = log.query(robot_id="r1")
    assert any(e.type == EventType.COMMAND_REFUSED for e in evs)


@pytest.mark.asyncio
async def test_send_failure_records_refused_and_allows_retry(tmp_path):
    async def transport(rid, env):
        raise KeyError(rid)

    log = _log(tmp_path)
    gw = CommandGateway(send_command=transport, event_log=log)
    env = CommandEnvelope.make(issued_by="c", issued_to="r1", capability="sleep",
                               payload={}, idempotency_key="k9")
    assert await gw.issue(env) is False
    evs = log.query(robot_id="r1")
    refused = [e for e in evs if e.type == EventType.COMMAND_REFUSED]
    assert refused and refused[0].payload.get("reason_code") == "NOT_CONNECTED"
    # key not consumed on failure -> retry allowed
    assert "k9" not in gw.issued_keys()
