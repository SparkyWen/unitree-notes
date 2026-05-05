"""Round-trip test for the file-based E-stop client."""
from __future__ import annotations

from pathlib import Path

import pytest

from g1_brain.safety.estop_client import EstopClient


def test_engage_query_release(tmp_path: Path):
    flag = tmp_path / "estop_flag"
    cli = EstopClient(flag)
    assert not cli.is_engaged()
    assert cli.reason() is None

    cli.engage("test reason")
    assert cli.is_engaged()
    reason_text = cli.reason() or ""
    assert "test reason" in reason_text

    cli.release()
    assert not cli.is_engaged()
    assert cli.reason() is None


def test_release_when_missing_is_silent(tmp_path: Path):
    flag = tmp_path / "estop_flag"
    cli = EstopClient(flag)
    cli.release()  # must not raise
    assert not cli.is_engaged()


def test_engage_overwrites_reason(tmp_path: Path):
    flag = tmp_path / "estop_flag"
    cli = EstopClient(flag)
    cli.engage("first")
    cli.engage("second")
    text = cli.reason() or ""
    assert "second" in text
    assert "first" not in text


def test_engage_creates_parent_dir(tmp_path: Path):
    flag = tmp_path / "nested" / "dir" / "estop_flag"
    cli = EstopClient(flag)
    cli.engage("nested")
    assert cli.is_engaged()
    cli.release()
    assert not cli.is_engaged()
