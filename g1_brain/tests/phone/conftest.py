"""Shared fixtures for phone bridge tests.

Phone tests must NEVER hit the real Twilio API or OpenAI Realtime —
they use mocks throughout. This conftest provides a fixture that
populates required env vars with safe dummy values.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def phone_env(monkeypatch):
    """Set every env var TwilioConfig + PhoneConfig require to a dummy."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC" + "0" * 32)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "dummy-auth-token")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK" + "0" * 32)
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "dummy-api-secret")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+14155550100")
    monkeypatch.setenv("PUBLIC_BRIDGE_URL", "wss://example.invalid/twilio")
    monkeypatch.setenv("PHONE_ALLOWED_CALLERS", "+14155550199")
    yield
