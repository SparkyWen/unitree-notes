"""Tests for phone.config — env loading + validation."""
from __future__ import annotations

import pytest

from g1_brain.phone.config import (
    PhoneConfig,
    TwilioConfig,
    load_from_env,
    PhoneConfigError,
)


def test_load_from_env_with_all_required(phone_env):
    twilio_cfg, phone_cfg = load_from_env()
    assert twilio_cfg.account_sid.startswith("AC")
    assert twilio_cfg.from_number == "+14155550100"
    assert twilio_cfg.auth_token.get_secret_value() == "dummy-auth-token"
    assert phone_cfg.public_bridge_url == "wss://example.invalid/twilio"
    assert phone_cfg.allowed_callers == ["+14155550199"]


def test_load_from_env_missing_required_raises(monkeypatch):
    # No env vars at all
    for k in (
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_API_KEY_SID",
        "TWILIO_API_KEY_SECRET", "TWILIO_FROM_NUMBER",
        "PUBLIC_BRIDGE_URL", "PHONE_ALLOWED_CALLERS",
    ):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(PhoneConfigError) as exc:
        load_from_env()
    assert "TWILIO_ACCOUNT_SID" in str(exc.value)


def test_allowed_callers_parses_comma_list(phone_env, monkeypatch):
    monkeypatch.setenv("PHONE_ALLOWED_CALLERS", "+1234,+5678 , +9999")
    _, phone_cfg = load_from_env()
    assert phone_cfg.allowed_callers == ["+1234", "+5678", "+9999"]


def test_public_bridge_url_rejects_non_wss(phone_env, monkeypatch):
    monkeypatch.setenv("PUBLIC_BRIDGE_URL", "http://example/twilio")
    with pytest.raises(PhoneConfigError):
        load_from_env()


def test_phone_config_defaults(phone_env):
    _, phone_cfg = load_from_env()
    assert phone_cfg.bind_host == "127.0.0.1"   # important — tunnel-only
    assert phone_cfg.bind_port == 8787
    assert phone_cfg.call_idle_timeout_s == 30.0
    assert phone_cfg.tool_timeout_s == 5.0
    assert phone_cfg.realtime_model == "gpt-realtime"
    assert phone_cfg.realtime_voice == "alloy"
