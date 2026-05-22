"""Tests for memory/jobs.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from g1_brain.memory.jobs import JobScheduler
from g1_brain.memory.schemas import (
    JOB_KIND_PHASE1,
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_LEASED,
    JOB_STATUS_PENDING,
)
from g1_brain.memory.storage import StorageLayer, now_ms


@pytest.fixture
def storage(tmp_path: Path):
    s = StorageLayer(tmp_path / "robot")
    s.init()
    yield s
    s.close()


@pytest.fixture
def jobs(storage):
    return JobScheduler(storage)


def test_enqueue_then_claim(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="sess-1")
    claimed = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert claimed is not None
    assert claimed["job_key"] == "sess-1"
    assert claimed["ownership_token"]
    # Status should now be leased
    assert jobs.status_of(JOB_KIND_PHASE1, "sess-1") == JOB_STATUS_LEASED


def test_claim_returns_none_when_empty(jobs: JobScheduler) -> None:
    claimed = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert claimed is None


def test_claim_respects_debounce(jobs: JobScheduler) -> None:
    future_ms = now_ms() + 5 * 60 * 1000
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="sess-d",
                 debounce_until_ms=future_ms)
    # retry_at is in the future, so claim should return None
    claimed = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert claimed is None


def test_claim_specific_job_key(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="a")
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="b")
    claimed = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10, job_key="b")
    assert claimed is not None
    assert claimed["job_key"] == "b"
    # 'a' remains pending
    assert jobs.status_of(JOB_KIND_PHASE1, "a") == JOB_STATUS_PENDING


def test_only_one_worker_claims_same_job(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="hot")
    first = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    second = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert first is not None
    assert second is None


def test_complete_releases_job(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x")
    c = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert c is not None
    ok = jobs.complete(JOB_KIND_PHASE1, "x", c["ownership_token"], watermark=42)
    assert ok
    assert jobs.status_of(JOB_KIND_PHASE1, "x") == JOB_STATUS_DONE


def test_complete_requires_token(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x")
    c = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert c is not None
    ok = jobs.complete(JOB_KIND_PHASE1, "x", "wrong-token")
    assert not ok


def test_fail_with_retries_reschedules(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x", retry_remaining=3)
    c = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert c is not None
    ok = jobs.fail(JOB_KIND_PHASE1, "x", c["ownership_token"], error="boom")
    assert ok
    # Status back to pending, retry_remaining decremented, retry_at advanced
    row = jobs._storage.execute(
        "SELECT * FROM jobs WHERE kind=? AND job_key=?",
        (JOB_KIND_PHASE1, "x"),
    ).fetchone()
    assert row["status"] == JOB_STATUS_PENDING
    assert row["retry_remaining"] == 2
    assert row["retry_at"] > now_ms()
    assert "boom" in (row["last_error"] or "")


def test_fail_with_no_retries_becomes_failed(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x", retry_remaining=1)
    c = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert c is not None
    ok = jobs.fail(JOB_KIND_PHASE1, "x", c["ownership_token"], error="x")
    assert ok
    assert jobs.status_of(JOB_KIND_PHASE1, "x") == JOB_STATUS_FAILED


def test_heartbeat_extends_lease(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x")
    c = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    original_lease = c["lease_until"]
    ok = jobs.heartbeat(JOB_KIND_PHASE1, "x", c["ownership_token"], extend_s=60)
    assert ok
    row = jobs._storage.execute(
        "SELECT lease_until FROM jobs WHERE kind=? AND job_key=?",
        (JOB_KIND_PHASE1, "x"),
    ).fetchone()
    assert row["lease_until"] > original_lease


def test_heartbeat_rejects_wrong_token(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x")
    c = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert c is not None
    ok = jobs.heartbeat(JOB_KIND_PHASE1, "x", "nope", extend_s=60)
    assert not ok


def test_expired_lease_can_be_reclaimed(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x")
    first = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    # Manually expire lease
    jobs._storage.execute(
        "UPDATE jobs SET lease_until=? WHERE kind=? AND job_key=?",
        (now_ms() - 1000, JOB_KIND_PHASE1, "x"),
    )
    # Reclaim
    second = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    assert second is not None
    assert second["ownership_token"] != first["ownership_token"]


def test_enqueue_after_done_resets_to_pending(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x")
    c = jobs.try_claim(kind=JOB_KIND_PHASE1, lease_s=10)
    jobs.complete(JOB_KIND_PHASE1, "x", c["ownership_token"])
    assert jobs.status_of(JOB_KIND_PHASE1, "x") == JOB_STATUS_DONE
    # Enqueue same key again
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x")
    assert jobs.status_of(JOB_KIND_PHASE1, "x") == JOB_STATUS_PENDING


def test_enqueue_no_op_when_already_pending(jobs: JobScheduler) -> None:
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x", retry_remaining=5)
    jobs.enqueue(kind=JOB_KIND_PHASE1, job_key="x", retry_remaining=3)
    row = jobs._storage.execute(
        "SELECT retry_remaining FROM jobs WHERE kind=? AND job_key=?",
        (JOB_KIND_PHASE1, "x"),
    ).fetchone()
    # Original retry_remaining preserved
    assert row["retry_remaining"] == 5
