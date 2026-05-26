"""Tests for phone.tunnel_health — Twilio HMAC + healthz payload + path probe."""
from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

import g1_brain.phone.tunnel_health as th
from g1_brain.phone.tunnel_health import (
    build_healthz_payload,
    ensure_public_path,
    healthz_url_from_bridge_url,
    probe_public_path,
    validate_twilio_signature,
)


# Reference vector: build a signature locally then verify it round-trips.
# Twilio's algorithm: signature = b64(HMAC-SHA1(URL + sorted(k+v) for k,v in params, key=AuthToken))


def _make_sig(url: str, params: dict[str, str], auth_token: str) -> str:
    data = url
    for k in sorted(params):
        data += k + params[k]
    mac = hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(mac).decode()


def test_signature_round_trip_with_params():
    url = "https://example.com/twilio"
    params = {"From": "+1234", "To": "+5678", "CallSid": "CA00"}
    token = "test-token"
    sig = _make_sig(url, params, token)
    assert validate_twilio_signature(url, params, sig, token)


def test_signature_with_empty_params():
    url = "https://example.com/twilio"
    sig = _make_sig(url, {}, "tok")
    assert validate_twilio_signature(url, {}, sig, "tok")


def test_signature_rejects_tampered_url():
    url = "https://example.com/twilio"
    sig = _make_sig(url, {}, "tok")
    assert not validate_twilio_signature(url + "/x", {}, sig, "tok")


def test_signature_rejects_tampered_param():
    url = "https://example.com/twilio"
    params = {"From": "+1234"}
    sig = _make_sig(url, params, "tok")
    assert not validate_twilio_signature(url, {"From": "+9999"}, sig, "tok")


def test_signature_rejects_wrong_token():
    url = "https://example.com/twilio"
    sig = _make_sig(url, {}, "right-token")
    assert not validate_twilio_signature(url, {}, sig, "wrong-token")


def test_healthz_payload_shape():
    p = build_healthz_payload(version="1.0", calls_active=2)
    assert p["ok"] is True
    assert p["calls_active"] == 2
    assert p["version"] == "1.0"


# ----- public-path probe / pre-dial gate -------------------------------------


def test_healthz_url_from_bridge_url():
    assert (
        healthz_url_from_bridge_url("wss://twilio.openproduct.cn/twilio")
        == "https://twilio.openproduct.cn/healthz"
    )
    # host:port preserved; non-wss falls back to http
    assert (
        healthz_url_from_bridge_url("ws://127.0.0.1:8787/twilio")
        == "http://127.0.0.1:8787/healthz"
    )


@pytest.mark.asyncio
async def test_probe_public_path_ok_and_bad():
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    async def healthz(_req):
        return web.json_response({"ok": True})

    async def broken(_req):
        return web.Response(status=502, text="bad gateway")

    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/dead", broken)
    async with TestServer(app) as server:
        assert await probe_public_path(str(server.make_url("/healthz"))) is True
        assert await probe_public_path(str(server.make_url("/dead"))) is False
    # connection refused / wrong port -> False, never raises
    assert await probe_public_path("http://127.0.0.1:1/healthz", timeout=1.0) is False


@pytest.mark.asyncio
async def test_ensure_public_path_healthy_skips_restart(monkeypatch):
    monkeypatch.setattr(th, "probe_public_path", _async_const(True))
    ran = []
    monkeypatch.setattr(th.asyncio, "create_subprocess_shell", _record(ran))
    ok, detail = await ensure_public_path("wss://x/twilio", restart_cmd="false")
    assert ok is True
    assert ran == []  # healthy path must not restart the tunnel


@pytest.mark.asyncio
async def test_ensure_public_path_dead_no_cmd_is_pure_gate(monkeypatch):
    monkeypatch.setattr(th, "probe_public_path", _async_const(False))
    ok, detail = await ensure_public_path("wss://x/twilio", restart_cmd="")
    assert ok is False
    assert "unreachable" in detail


@pytest.mark.asyncio
async def test_ensure_public_path_self_heals(monkeypatch):
    # Fail the first probe, succeed after the (mocked) restart.
    results = iter([False, True])

    async def fake_probe(_url, **_kw):
        return next(results)

    ran = []
    monkeypatch.setattr(th, "probe_public_path", fake_probe)
    monkeypatch.setattr(th.asyncio, "create_subprocess_shell", _record(ran))
    ok, detail = await ensure_public_path(
        "wss://x/twilio", restart_cmd="true", settle_s=0.0
    )
    assert ok is True
    assert len(ran) == 1
    assert "recovered" in detail


# ----- helpers ---------------------------------------------------------------


def _async_const(value):
    async def _f(_url, **_kw):
        return value
    return _f


def _record(sink):
    class _Proc:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def _f(cmd, **_kw):
        sink.append(cmd)
        return _Proc()

    return _f
