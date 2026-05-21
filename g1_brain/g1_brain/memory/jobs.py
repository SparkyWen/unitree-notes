"""Cooperative job queue: claim / lease / retry / heartbeat.

Lives in the jobs table of state.sqlite. Provides primitives used by
Phase1 / Phase2 workers and the Phase2 global lock holder.

All methods are sync; callers wrap in asyncio.to_thread where needed.
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Optional

from .schemas import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_LEASED,
    JOB_STATUS_PENDING,
)
from .storage import StorageLayer, now_ms

log = logging.getLogger(__name__)


def _worker_id() -> str:
    return f"{os.getpid()}-{secrets.token_hex(3)}"


class JobScheduler:
    """Thin wrapper around the jobs table.

    All operations are best-effort:
    - Race losers see status='leased' and retry later.
    - Expired leases are reclaimable by any worker.
    """

    DEFAULT_LEASE_S = 60
    DEFAULT_PHASE2_LEASE_S = 3600

    def __init__(self, storage: StorageLayer):
        self._storage = storage

    # ---------- enqueue ----------

    def enqueue(
        self,
        *,
        kind: str,
        job_key: str,
        retry_remaining: int = 3,
        debounce_until_ms: Optional[int] = None,
    ) -> None:
        """Insert a pending job, or no-op if a non-terminal one exists.

        debounce_until_ms: set as retry_at so worker won't pick before that.
        """
        retry_at = debounce_until_ms if debounce_until_ms is not None else now_ms()
        self._storage.execute(
            """
            INSERT INTO jobs (kind, job_key, status, retry_at, retry_remaining)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(kind, job_key) DO UPDATE SET
                status = CASE
                    WHEN jobs.status IN ('done', 'failed') THEN ?
                    ELSE jobs.status
                END,
                retry_at = CASE
                    WHEN jobs.status IN ('done', 'failed') THEN ?
                    ELSE MIN(jobs.retry_at, excluded.retry_at)
                END,
                retry_remaining = CASE
                    WHEN jobs.status IN ('done', 'failed')
                        THEN excluded.retry_remaining
                    ELSE jobs.retry_remaining
                END,
                last_error = CASE
                    WHEN jobs.status IN ('done', 'failed') THEN NULL
                    ELSE jobs.last_error
                END
            """,
            (kind, job_key, JOB_STATUS_PENDING, retry_at, retry_remaining,
             JOB_STATUS_PENDING, retry_at),
        )

    # ---------- claim ----------

    def try_claim(
        self,
        *,
        kind: str,
        lease_s: int = DEFAULT_LEASE_S,
        job_key: Optional[str] = None,
    ) -> Optional[dict]:
        """Claim one pending job of `kind`. Returns dict or None.

        Atomic via UPDATE ... RETURNING.
        If job_key given, claim that specific key only.
        """
        token = secrets.token_hex(8)
        worker = _worker_id()
        now = now_ms()
        lease_until = now + lease_s * 1000

        where_extra = ""
        params = [
            JOB_STATUS_LEASED, worker, token, now, lease_until,
            kind, now, now,
        ]
        if job_key is not None:
            where_extra = " AND job_key = ?"
            params.append(job_key)

        sql = f"""
            UPDATE jobs
            SET status = ?, worker_id = ?, ownership_token = ?,
                started_at = ?, lease_until = ?
            WHERE kind = ?
              AND status = 'pending'
              AND retry_at <= ?
              AND (lease_until IS NULL OR lease_until < ?)
              {where_extra}
            RETURNING kind, job_key, ownership_token, lease_until,
                      retry_remaining, input_watermark, last_success_watermark
        """

        # Reclaim stale leases too: if status='leased' but lease_until<now,
        # try a second claim pass.
        row = self._storage.execute(sql, tuple(params)).fetchone()
        if row is not None:
            return dict(row)

        # Reclaim expired lease
        params_expired = [
            JOB_STATUS_LEASED, worker, token, now, lease_until,
            kind, now,
        ]
        if job_key is not None:
            params_expired.append(job_key)
        sql_expired = f"""
            UPDATE jobs
            SET status = ?, worker_id = ?, ownership_token = ?,
                started_at = ?, lease_until = ?
            WHERE kind = ?
              AND status = 'leased'
              AND lease_until IS NOT NULL
              AND lease_until < ?
              {where_extra}
            RETURNING kind, job_key, ownership_token, lease_until,
                      retry_remaining, input_watermark, last_success_watermark
        """
        row = self._storage.execute(sql_expired, tuple(params_expired)).fetchone()
        return dict(row) if row else None

    # ---------- heartbeat ----------

    def heartbeat(self, kind: str, job_key: str, token: str,
                  *, extend_s: int = DEFAULT_LEASE_S) -> bool:
        """Push out lease_until. Returns True if we still own the lease."""
        new_until = now_ms() + extend_s * 1000
        cur = self._storage.execute(
            """
            UPDATE jobs SET lease_until = ?
            WHERE kind = ? AND job_key = ? AND ownership_token = ?
              AND status = 'leased'
            """,
            (new_until, kind, job_key, token),
        )
        return cur.rowcount > 0

    # ---------- finish ----------

    def complete(
        self, kind: str, job_key: str, token: str,
        *, watermark: Optional[int] = None,
    ) -> bool:
        cur = self._storage.execute(
            """
            UPDATE jobs
            SET status = ?, finished_at = ?, last_error = NULL,
                last_success_watermark = COALESCE(?, last_success_watermark)
            WHERE kind = ? AND job_key = ? AND ownership_token = ?
            """,
            (JOB_STATUS_DONE, now_ms(), watermark, kind, job_key, token),
        )
        return cur.rowcount > 0

    def fail(
        self, kind: str, job_key: str, token: str,
        *, error: str,
    ) -> bool:
        """Mark a job failed (or schedule a retry if retry_remaining > 0)."""
        # First: read current retry_remaining
        row = self._storage.execute(
            "SELECT retry_remaining FROM jobs WHERE kind = ? AND job_key = ?",
            (kind, job_key),
        ).fetchone()
        if row is None:
            return False
        remaining = (row["retry_remaining"] or 0)

        if remaining <= 1:
            cur = self._storage.execute(
                """
                UPDATE jobs
                SET status = ?, finished_at = ?, last_error = ?,
                    retry_remaining = 0
                WHERE kind = ? AND job_key = ? AND ownership_token = ?
                """,
                (JOB_STATUS_FAILED, now_ms(), error[:1024],
                 kind, job_key, token),
            )
            return cur.rowcount > 0
        else:
            # exponential backoff: 5min * (max_retries - retry_remaining + 1)
            delay_ms = 5 * 60 * 1000 * (4 - remaining)
            retry_at = now_ms() + delay_ms
            cur = self._storage.execute(
                """
                UPDATE jobs
                SET status = ?, retry_at = ?, retry_remaining = ?,
                    last_error = ?, lease_until = NULL,
                    worker_id = NULL, ownership_token = NULL,
                    started_at = NULL
                WHERE kind = ? AND job_key = ? AND ownership_token = ?
                """,
                (JOB_STATUS_PENDING, retry_at, remaining - 1, error[:1024],
                 kind, job_key, token),
            )
            return cur.rowcount > 0

    # ---------- introspection ----------

    def status_of(self, kind: str, job_key: str) -> Optional[str]:
        row = self._storage.execute(
            "SELECT status FROM jobs WHERE kind = ? AND job_key = ?",
            (kind, job_key),
        ).fetchone()
        return row["status"] if row else None
