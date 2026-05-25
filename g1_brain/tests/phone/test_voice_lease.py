"""Tests for phone.voice_lease — cross-process LOCAL_MIC | PHONE mutex."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from g1_brain.phone.voice_lease import VoiceLeaseManager, LeaseHolder


@pytest.fixture
def lease_path(tmp_path) -> Path:
    return tmp_path / "voice_lease.json"


def test_initial_state_is_local_mic(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    holder = mgr.current_holder()
    assert holder is None or holder.name == LeaseHolder.LOCAL_MIC


def test_acquire_phone_succeeds_when_idle(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    assert mgr.acquire(LeaseHolder.PHONE, owner="call-1") is True
    h = mgr.current_holder()
    assert h.name == LeaseHolder.PHONE
    assert h.owner == "call-1"


def test_acquire_phone_fails_when_phone_already_held_by_other(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    mgr.acquire(LeaseHolder.PHONE, owner="call-1")
    # second process, same lease file
    mgr2 = VoiceLeaseManager(lease_path)
    assert mgr2.acquire(LeaseHolder.PHONE, owner="call-2") is False


def test_acquire_phone_idempotent_for_same_owner(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    assert mgr.acquire(LeaseHolder.PHONE, owner="call-1") is True
    assert mgr.acquire(LeaseHolder.PHONE, owner="call-1") is True


def test_release_only_by_owner(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    mgr.acquire(LeaseHolder.PHONE, owner="call-1")
    # foreign release: no-op
    mgr.release(LeaseHolder.PHONE, owner="someone-else")
    assert mgr.current_holder().name == LeaseHolder.PHONE
    # legitimate release
    mgr.release(LeaseHolder.PHONE, owner="call-1")
    holder = mgr.current_holder()
    assert holder is None or holder.name == LeaseHolder.LOCAL_MIC


def test_stale_lease_is_reclaimable(lease_path):
    mgr = VoiceLeaseManager(lease_path, stale_after_s=0.0)
    mgr.acquire(LeaseHolder.PHONE, owner="dead-call")
    time.sleep(0.01)
    mgr2 = VoiceLeaseManager(lease_path, stale_after_s=0.0)
    assert mgr2.acquire(LeaseHolder.PHONE, owner="new-call") is True


def test_acquire_local_mic_after_phone_release(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    mgr.acquire(LeaseHolder.PHONE, owner="call-1")
    mgr.release(LeaseHolder.PHONE, owner="call-1")
    assert mgr.acquire(LeaseHolder.LOCAL_MIC, owner="va-demo-1") is True
    assert mgr.current_holder().name == LeaseHolder.LOCAL_MIC
