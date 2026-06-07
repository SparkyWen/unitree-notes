"""Append-only event store (sqlite WAL + jsonl mirror) with replay.

Pattern mirrors g1_brain/memory/storage.py. INSERT OR IGNORE on event_id makes
append idempotent (re-delivered events do not duplicate).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

from g1_brain.fleet.contracts.models import RobotEvent

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    trace_id     TEXT,
    robot_id     TEXT NOT NULL,
    type         TEXT NOT NULL,
    ts           TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    ingest_seq   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_robot ON events(robot_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id, ts, ingest_seq);
"""


class EventLog:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.jsonl_path = self.db_path.with_suffix(".jsonl")
        self._conn: Optional[sqlite3.Connection] = None
        self._seq = 0

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None,
                                     check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        row = self._conn.execute("SELECT MAX(ingest_seq) AS m FROM events").fetchone()
        self._seq = int(row["m"]) if row and row["m"] is not None else 0

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def append(self, ev: RobotEvent) -> None:
        assert self._conn is not None
        next_seq = self._seq + 1
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO events
               (event_id, trace_id, robot_id, type, ts, payload_hash, payload_json, ingest_seq)
               VALUES (?,?,?,?,?,?,?,?)""",
            (ev.event_id, ev.trace_id, ev.robot_id, ev.type.value, ev.ts,
             ev.payload_hash, json.dumps(ev.payload, ensure_ascii=False), next_seq),
        )
        if cur.rowcount:
            self._seq = next_seq
            with open(self.jsonl_path, "a", encoding="utf-8") as fh:
                fh.write(ev.model_dump_json() + "\n")

    def _rows_to_events(self, rows) -> List[RobotEvent]:
        out = []
        for r in rows:
            out.append(RobotEvent(event_id=r["event_id"], trace_id=r["trace_id"],
                                  robot_id=r["robot_id"], type=r["type"], ts=r["ts"],
                                  payload_hash=r["payload_hash"],
                                  payload=json.loads(r["payload_json"])))
        return out

    def query(self, *, robot_id: Optional[str] = None, trace_id: Optional[str] = None,
              since: Optional[str] = None, until: Optional[str] = None,
              limit: int = 500) -> List[RobotEvent]:
        assert self._conn is not None
        clauses, params = [], []
        if robot_id: clauses.append("robot_id = ?"); params.append(robot_id)
        if trace_id: clauses.append("trace_id = ?"); params.append(trace_id)
        if since: clauses.append("ts >= ?"); params.append(since)
        if until: clauses.append("ts <= ?"); params.append(until)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM events {where} ORDER BY ts ASC, ingest_seq ASC LIMIT ?", params,
        ).fetchall()
        return self._rows_to_events(rows)

    def replay(self, trace_id: str) -> List[RobotEvent]:
        return self.query(trace_id=trace_id, limit=100000)
