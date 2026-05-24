"""Test the start_phone_call skill on SkillServer."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from g1_brain.skills.skill_server import SkillServer


async def _passthrough_validate(tool, args):
    """Safety mock that approves all calls and passes sanitized args through."""
    return (True, "", dict(args or {}))


def _make_server(*, dialer=None, default_to=None):
    safety = MagicMock()
    safety.validate = _passthrough_validate
    return SkillServer(
        combo_ctl=MagicMock(),
        safety=safety,
        tts=MagicMock(), vision=MagicMock(),
        camera_hub=MagicMock(), scene_bus=MagicMock(), fsm=MagicMock(),
        sim=True,
        dialer=dialer,
        default_phone_to=default_to,
    )


@pytest.mark.asyncio
async def test_start_phone_call_no_dialer():
    server = _make_server(dialer=None)
    r = await server.execute("start_phone_call", {"to": "+1"})
    assert r["ok"] is False
    assert "phone bridge not enabled" in r["reason"]


@pytest.mark.asyncio
async def test_start_phone_call_uses_default_to():
    dialer = MagicMock(); dialer.dial = AsyncMock(return_value="CA1" + "0" * 31)
    server = _make_server(dialer=dialer, default_to="+14155550199")
    r = await server.execute("start_phone_call", {})
    assert r["ok"] is True
    dialer.dial.assert_awaited_once_with("+14155550199")


@pytest.mark.asyncio
async def test_start_phone_call_with_explicit_to_allowed():
    dialer = MagicMock(); dialer.dial = AsyncMock(return_value="CA2" + "0" * 31)
    server = _make_server(dialer=dialer, default_to="+1default")
    server._allowed_phone_callers = ["+14155550199"]  # explicit allowlist
    r = await server.execute("start_phone_call", {"to": "+14155550199"})
    assert r["ok"] is True
    dialer.dial.assert_awaited_once_with("+14155550199")


@pytest.mark.asyncio
async def test_start_phone_call_rejects_non_whitelisted_to():
    dialer = MagicMock(); dialer.dial = AsyncMock(return_value="should-not-dial")
    server = _make_server(dialer=dialer, default_to="+61411706848")
    # Simulates wake-word ASR mishearing the last digit (real incident).
    r = await server.execute("start_phone_call", {"to": "+61411706888"})
    assert r["ok"] is False
    assert "not in allowed callers" in r["reason"]
    dialer.dial.assert_not_called()
