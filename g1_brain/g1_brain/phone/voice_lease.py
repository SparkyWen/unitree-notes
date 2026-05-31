"""Cross-process voice lease.

Two named slots — LOCAL_MIC and PHONE — protected by an fcntl.flock'd
JSON file at /tmp/g1_brain_voice_lease (default). Both the long-running
g1_brain process and any va-demo process can read/write safely.

Why a file: cheapest correct cross-process mutex with no extra service.
fcntl.flock is advisory but every process that touches the file uses
this class, so it's effectively mandatory in practice.

Default file path: /tmp/g1_brain_voice_lease (overridable for tests).
"""
from __future__ import annotations

import enum
import fcntl
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_LEASE_PATH = Path("/tmp/g1_brain_voice_lease")


class LeaseHolder(str, enum.Enum):
    LOCAL_MIC = "LOCAL_MIC"
    PHONE = "PHONE"


@dataclass(frozen=True)
class LeaseRecord:
    name: LeaseHolder
    owner: str
    since: float

    def as_dict(self) -> dict:
        return {"holder": self.name.value, "owner": self.owner, "since": self.since}

    @classmethod
    def from_dict(cls, d: dict) -> "LeaseRecord":
        return cls(
            name=LeaseHolder(d["holder"]),
            owner=str(d["owner"]),
            since=float(d["since"]),
        )


class VoiceLeaseManager:
    """Atomic acquire/release of {LOCAL_MIC | PHONE} backed by a lock file."""

    def __init__(
        self,
        path: Path = DEFAULT_LEASE_PATH,
        stale_after_s: float = 3600.0,
    ) -> None:
        self._path = Path(path)
        self._stale_after_s = stale_after_s
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def acquire(self, name: LeaseHolder, owner: str) -> bool:
        with self._locked() as f:
            existing = self._read(f)
            if existing is None:
                self._write(f, LeaseRecord(name=name, owner=owner, since=time.time()))
                return True
            if existing.name == name and existing.owner == owner:
                return True
            # different holder OR different owner of same slot:
            # only steal if stale
            if time.time() - existing.since > self._stale_after_s:
                self._write(f, LeaseRecord(name=name, owner=owner, since=time.time()))
                return True
            # If we're trying to acquire the OTHER slot, that's allowed
            # (the slots represent who's transmitting; LOCAL_MIC can claim
            # while PHONE is held only if PHONE is stale, which we just
            # checked above). Reject.
            return False

    def release(self, name: LeaseHolder, owner: str) -> None:
        with self._locked() as f:
            existing = self._read(f)
            if existing is None:
                return
            if existing.name != name or existing.owner != owner:
                return  # someone else owns it; do nothing
            self._erase(f)

    def current_holder(self) -> Optional[LeaseRecord]:
        with self._locked() as f:
            return self._read(f)

    # ---- internals ------------------------------------------------------

    def _locked(self):
        return _LockedFile(self._path)

    @staticmethod
    def _read(f) -> Optional[LeaseRecord]:
        f.seek(0)
        raw = f.read()
        if not raw.strip():
            return None
        try:
            return LeaseRecord.from_dict(json.loads(raw))
        except Exception:
            return None

    @staticmethod
    def _write(f, rec: LeaseRecord) -> None:
        f.seek(0)
        f.truncate()
        f.write(json.dumps(rec.as_dict()))
        f.flush()
        os.fsync(f.fileno())

    @staticmethod
    def _erase(f) -> None:
        f.seek(0)
        f.truncate()
        f.flush()
        os.fsync(f.fileno())


class _LockedFile:
    """Context manager: open lease file r+ with exclusive flock."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._f = None

    def __enter__(self):
        # open r+, creating if needed
        fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o644)
        self._f = os.fdopen(fd, "r+")
        fcntl.flock(self._f.fileno(), fcntl.LOCK_EX)
        return self._f

    def __exit__(self, exc_type, exc, tb):
        try:
            fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        finally:
            self._f.close()
            self._f = None
