from g1_brain.fleet.coordinator.event_log import EventLog
from g1_brain.fleet.contracts.models import RobotEvent, EventType


def _ev(robot, trace, t):
    return RobotEvent.make(robot_id=robot, trace_id=trace, type=EventType.ACTION_RESULT,
                           ts=t, payload={"k": t})


def test_append_and_query_by_robot(tmp_path):
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    log.append(_ev("r1", "trace-a", "2026-06-06T00:00:01Z"))
    log.append(_ev("r2", "trace-a", "2026-06-06T00:00:02Z"))
    rows = log.query(robot_id="r1")
    assert len(rows) == 1 and rows[0].robot_id == "r1"
    log.close()


def test_replay_returns_trace_in_order(tmp_path):
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    log.append(_ev("r1", "trace-x", "2026-06-06T00:00:03Z"))
    log.append(_ev("r1", "trace-x", "2026-06-06T00:00:01Z"))
    log.append(_ev("r1", "trace-y", "2026-06-06T00:00:02Z"))
    out = log.replay("trace-x")
    assert [e.ts for e in out] == ["2026-06-06T00:00:01Z", "2026-06-06T00:00:03Z"]
    log.close()


def test_append_is_idempotent_on_event_id(tmp_path):
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    ev = _ev("r1", "trace-a", "2026-06-06T00:00:01Z")
    log.append(ev); log.append(ev)  # same event_id twice
    assert len(log.query(robot_id="r1")) == 1
    mirror = tmp_path / "fleet.jsonl"
    assert len([ln for ln in mirror.read_text().splitlines() if ln.strip()]) == 1
    log.close()


def test_jsonl_mirror_written(tmp_path):
    log = EventLog(tmp_path / "fleet.sqlite"); log.init()
    log.append(_ev("r1", "trace-a", "2026-06-06T00:00:01Z"))
    mirror = tmp_path / "fleet.jsonl"
    assert mirror.exists() and mirror.read_text().strip() != ""
    log.close()
