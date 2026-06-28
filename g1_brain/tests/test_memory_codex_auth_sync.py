"""Tests for codex auth sync into the isolated .codex_runtime CODEX_HOME.

Regression guard for the slow-brain 401 trap: g1_brain points CODEX_HOME at
``.codex_runtime`` whose auth.json is never refreshed by ``codex login`` and
silently expires. StorageLayer.init() must self-heal by copying the operator's
fresh ~/.codex token in.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from g1_brain.memory.storage import (
    StorageLayer,
    codex_access_token_expiry,
    sync_codex_auth,
)


def _write_auth(path: Path, exp_epoch: float | None) -> None:
    """Write a codex-shaped auth.json with a fake JWT access_token."""
    if exp_epoch is None:
        access = "not-a-jwt"
    else:
        payload = base64.urlsafe_b64encode(
            json.dumps({"exp": int(exp_epoch)}).encode()
        ).rstrip(b"=").decode()
        access = f"header.{payload}.sig"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"access_token": access, "refresh_token": "rt.x"},
    }))


def test_expiry_parses_future_and_past(tmp_path: Path) -> None:
    fut = tmp_path / "future.json"
    _write_auth(fut, time.time() + 1000)
    assert codex_access_token_expiry(fut) > time.time()

    past = tmp_path / "past.json"
    _write_auth(past, time.time() - 1000)
    assert codex_access_token_expiry(past) < time.time()

    assert codex_access_token_expiry(tmp_path / "missing.json") is None


def test_sync_copies_when_runtime_expired(tmp_path: Path) -> None:
    host = tmp_path / "host" / "auth.json"
    runtime = tmp_path / "rt" / "auth.json"
    _write_auth(host, time.time() + 10 * 86400)   # fresh host token
    _write_auth(runtime, time.time() - 86400)      # expired runtime token

    assert sync_codex_auth(host, runtime) == "synced"
    # runtime now carries the host's fresh token
    assert codex_access_token_expiry(runtime) > time.time() + 86400
    assert json.loads(runtime.read_text()) == json.loads(host.read_text())


def test_sync_copies_when_runtime_missing(tmp_path: Path) -> None:
    host = tmp_path / "host" / "auth.json"
    runtime = tmp_path / "rt" / "auth.json"
    _write_auth(host, time.time() + 10 * 86400)
    assert sync_codex_auth(host, runtime) == "synced"
    assert runtime.is_file()
    assert oct(runtime.stat().st_mode)[-3:] == "600"


def test_sync_noop_when_runtime_fresh(tmp_path: Path) -> None:
    host = tmp_path / "host" / "auth.json"
    runtime = tmp_path / "rt" / "auth.json"
    _write_auth(host, time.time() + 10 * 86400)
    _write_auth(runtime, time.time() + 10 * 86400)  # already fresh
    original = runtime.read_text()
    assert sync_codex_auth(host, runtime) == "noop_runtime_fresh"
    assert runtime.read_text() == original  # untouched


def test_sync_noop_when_host_missing_or_expired(tmp_path: Path) -> None:
    runtime = tmp_path / "rt" / "auth.json"
    _write_auth(runtime, time.time() - 86400)
    assert sync_codex_auth(tmp_path / "nope.json", runtime) == "noop_no_host_auth"

    host = tmp_path / "host" / "auth.json"
    _write_auth(host, time.time() - 10)            # operator login also stale
    assert sync_codex_auth(host, runtime) == "noop_host_expired"


def test_storage_init_syncs_codex_auth(tmp_path: Path, monkeypatch) -> None:
    host_home = tmp_path / "dot_codex"
    _write_auth(host_home / "auth.json", time.time() + 10 * 86400)
    monkeypatch.setenv("CODEX_HOME", str(host_home))

    storage = StorageLayer(tmp_path / "robot")
    storage.init()
    try:
        runtime_auth = storage.codex_runtime_dir / "auth.json"
        assert runtime_auth.is_file()
        assert codex_access_token_expiry(runtime_auth) > time.time()
    finally:
        storage.close()
