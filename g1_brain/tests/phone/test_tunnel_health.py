"""Tests for phone.tunnel_health — Twilio HMAC + healthz payload."""
from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from g1_brain.phone.tunnel_health import validate_twilio_signature, build_healthz_payload


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
