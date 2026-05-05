"""Lightweight client for the file-based E-stop flag.

The flag is a regular file whose presence == "engaged". Multiple readers
(SafetySupervisor, watchdog, the listener itself) all use the same path
from ``cfg["safety"]["estop"]["flag_path"]``. Writes are best-effort:
the flag may already exist (re-engage is a no-op) and may be missing on
release (we silently swallow the error).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional, Union

log = logging.getLogger(__name__)

PathLike = Union[str, os.PathLike]


class EstopClient:
    def __init__(self, flag_path: PathLike) -> None:
        self.flag_path = Path(flag_path)

    # ----- queries ----------------------------------------------------------

    def is_engaged(self) -> bool:
        try:
            return self.flag_path.exists()
        except OSError:
            # If we can't stat the file, assume engaged (fail-safe).
            log.exception("estop: stat failed for %s; assuming engaged", self.flag_path)
            return True

    def reason(self) -> Optional[str]:
        """Read the file content as the engagement reason. None if not engaged."""
        try:
            return self.flag_path.read_text(encoding="utf-8").strip() or None
        except FileNotFoundError:
            return None
        except OSError:
            log.exception("estop: cannot read %s", self.flag_path)
            return None

    # ----- mutations --------------------------------------------------------

    def engage(self, reason: str = "manual") -> None:
        try:
            self.flag_path.parent.mkdir(parents=True, exist_ok=True)
            payload = f"{reason}\n@ts={time.time():.3f}\n"
            self.flag_path.write_text(payload, encoding="utf-8")
            log.warning("estop: ENGAGED (%s) -> %s", reason, self.flag_path)
        except OSError:
            log.exception("estop: failed to engage at %s", self.flag_path)
            raise

    def release(self) -> None:
        try:
            self.flag_path.unlink()
            log.info("estop: released %s", self.flag_path)
        except FileNotFoundError:
            pass
        except OSError:
            log.exception("estop: failed to release %s", self.flag_path)
            raise


__all__ = ["EstopClient"]
