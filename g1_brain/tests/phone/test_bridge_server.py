"""Tests for phone.bridge_server — request validation + routing.

Full audio-loop integration tests live in test_realtime_session.py and
the live E2E.
"""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

# va-demo must be on sys.path before importing BrainRealtimeAgent (it
# subclasses va-demo's RealtimeAgent).
_VA = "/home/helios/unitree/unitree-notes/va-demo"
if _VA not in sys.path:
    sys.path.insert(0, _VA)

from g1_brain.phone.bridge_server import build_app
from g1_brain.phone.config import PhoneConfig, TwilioConfig
from g1_brain.phone.voice_lease import VoiceLeaseManager


def _make_cfgs(tmp_path):
    twilio = TwilioConfig(
        account_sid="AC" + "0" * 32, auth_token="tok",
        api_key_sid="SK" + "0" * 32, api_key_secret="sec",
        from_number="+14155550100",
    )
    phone = PhoneConfig(
        public_bridge_url="wss://example.invalid/twilio",
        allowed_callers=["+61411706848"],
        bind_host="127.0.0.1", bind_port=0,
    )
    return twilio, phone


@pytest.fixture
def lease_path(tmp_path):
    return tmp_path / "lease.json"


@pytest.mark.asyncio
async def test_healthz_returns_ok(tmp_path, lease_path):
    twilio, phone = _make_cfgs(tmp_path)
    app = build_app(
        twilio_cfg=twilio, phone_cfg=phone,
        skill_server=MagicMock(), scene_bus=MagicMock(),
        dialer=MagicMock(),
        voice_lease=VoiceLeaseManager(lease_path),
        version="test",
    )
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/healthz")
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True
            assert body["version"] == "test"
            assert body["calls_active"] == 0


@pytest.mark.asyncio
async def test_ws_rejects_bad_signature(tmp_path, lease_path):
    twilio, phone = _make_cfgs(tmp_path)
    app = build_app(
        twilio_cfg=twilio, phone_cfg=phone,
        skill_server=MagicMock(), scene_bus=MagicMock(),
        dialer=MagicMock(),
        voice_lease=VoiceLeaseManager(lease_path),
        version="test",
    )
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            # WS upgrade without X-Twilio-Signature → reject
            resp = await client.get(
                "/twilio",
                headers={
                    "Upgrade": "websocket",
                    "Connection": "upgrade",
                    "Sec-WebSocket-Version": "13",
                    "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                },
            )
            assert resp.status == 403
