"""Tests for phone.twilio_dialer — REST + TwiML, all network mocked."""
from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from g1_brain.phone.config import TwilioConfig
from g1_brain.phone.twilio_dialer import TwilioDialer, TwilioDialError


@pytest.fixture
def cfg():
    return TwilioConfig(
        account_sid="AC" + "0" * 32,
        auth_token="dummy",
        api_key_sid="SK" + "0" * 32,
        api_key_secret="secret",
        from_number="+14155550100",
    )


def test_build_twiml_includes_url_and_parameter(cfg):
    d = TwilioDialer(cfg, public_bridge_url="wss://h/twilio")
    xml = d.build_twiml(brain_session_id="abc-123")
    assert "<Connect>" in xml
    assert '<Stream url="wss://h/twilio">' in xml
    assert '<Parameter name="brain_session_id" value="abc-123"/>' in xml


@pytest.mark.asyncio
async def test_dial_posts_to_calls_endpoint(cfg, monkeypatch):
    d = TwilioDialer(cfg, public_bridge_url="wss://h/twilio")
    fake_resp = MagicMock()
    fake_resp.status = 201
    fake_resp.json = AsyncMock(return_value={"sid": "CA" + "1" * 32})

    captured = {}

    class _Ctx:
        async def __aenter__(self):
            return fake_resp
        async def __aexit__(self, *a):
            return False

    def fake_post(url, *, data, auth, **kwargs):
        captured["url"] = url
        captured["data"] = data
        captured["auth"] = auth
        return _Ctx()

    fake_session = MagicMock()
    fake_session.post = fake_post
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("aiohttp.ClientSession", lambda *a, **k: fake_session)

    sid = await d.dial("+14155550199")
    assert sid.startswith("CA")
    assert "Accounts/AC" in captured["url"]
    assert "Calls.json" in captured["url"]
    assert captured["data"]["To"] == "+14155550199"
    assert captured["data"]["From"] == "+14155550100"
    assert "<Stream url=" in captured["data"]["Twiml"]
    assert captured["auth"].login == cfg.api_key_sid
    assert captured["auth"].password == cfg.api_key_secret.get_secret_value()


@pytest.mark.asyncio
async def test_dial_raises_on_4xx(cfg, monkeypatch):
    d = TwilioDialer(cfg, public_bridge_url="wss://h/twilio")
    fake_resp = MagicMock()
    fake_resp.status = 400
    fake_resp.text = AsyncMock(return_value="bad number")

    class _Ctx:
        async def __aenter__(self): return fake_resp
        async def __aexit__(self, *a): return False

    fake_session = MagicMock()
    fake_session.post = lambda *a, **k: _Ctx()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("aiohttp.ClientSession", lambda *a, **k: fake_session)

    with pytest.raises(TwilioDialError):
        await d.dial("+14155550199")


@pytest.mark.asyncio
async def test_dry_run_hits_accounts_endpoint(cfg, monkeypatch):
    d = TwilioDialer(cfg, public_bridge_url="wss://h/twilio")
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.json = AsyncMock(return_value={"friendly_name": "test-account"})

    captured = {}
    class _Ctx:
        async def __aenter__(self): return fake_resp
        async def __aexit__(self, *a): return False
    def fake_get(url, *, auth, **kwargs):
        captured["url"] = url
        return _Ctx()
    fake_session = MagicMock()
    fake_session.get = fake_get
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("aiohttp.ClientSession", lambda *a, **k: fake_session)

    name = await d.dry_run()
    assert name == "test-account"
    assert captured["url"].endswith(f"Accounts/{cfg.account_sid}.json")
