"""Pydantic-validated config for the Twilio phone bridge.

Source of truth for Twilio credentials, public bridge URL, allowed-caller
whitelist. Failure mode is loud: missing env vars → PhoneConfigError at
boot (not at first call).
"""
from __future__ import annotations

import os
from typing import List, Tuple

from pydantic import BaseModel, Field, SecretStr, field_validator


class PhoneConfigError(RuntimeError):
    """Raised when phone bridge config is incomplete or invalid."""


class TwilioConfig(BaseModel):
    account_sid: str = Field(..., min_length=2)
    auth_token: SecretStr
    api_key_sid: str = Field(..., min_length=2)
    api_key_secret: SecretStr
    from_number: str = Field(..., pattern=r"^\+\d{8,15}$")


class PhoneConfig(BaseModel):
    public_bridge_url: str
    allowed_callers: List[str]
    bind_host: str = "127.0.0.1"
    bind_port: int = 8787
    call_idle_timeout_s: float = 30.0
    tool_timeout_s: float = 5.0
    realtime_model: str = "gpt-realtime"
    realtime_voice: str = "alloy"
    # ISO-639-1 reply/transcription language lock for the phone session.
    # Defaults to English so a call never drifts into another language.
    language: str = "en"
    greeting: str = "Hi, this is Sparky. What would you like me to do?"

    @field_validator("public_bridge_url")
    @classmethod
    def _wss_only(cls, v: str) -> str:
        if not v.startswith("wss://"):
            raise ValueError("public_bridge_url must be wss://...")
        return v

    @field_validator("allowed_callers")
    @classmethod
    def _non_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("allowed_callers must be non-empty")
        for entry in v:
            if not entry.startswith("+"):
                raise ValueError(f"allowed_callers entries must be E.164 (+...): {entry}")
        return v


_REQUIRED = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_API_KEY_SID",
    "TWILIO_API_KEY_SECRET",
    "TWILIO_FROM_NUMBER",
    "PUBLIC_BRIDGE_URL",
    "PHONE_ALLOWED_CALLERS",
]


def load_from_env() -> Tuple[TwilioConfig, PhoneConfig]:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise PhoneConfigError(f"missing env vars: {', '.join(missing)}")

    callers = [
        c.strip()
        for c in os.environ["PHONE_ALLOWED_CALLERS"].split(",")
        if c.strip()
    ]

    try:
        twilio_cfg = TwilioConfig(
            account_sid=os.environ["TWILIO_ACCOUNT_SID"],
            auth_token=os.environ["TWILIO_AUTH_TOKEN"],
            api_key_sid=os.environ["TWILIO_API_KEY_SID"],
            api_key_secret=os.environ["TWILIO_API_KEY_SECRET"],
            from_number=os.environ["TWILIO_FROM_NUMBER"],
        )
        phone_cfg = PhoneConfig(
            public_bridge_url=os.environ["PUBLIC_BRIDGE_URL"],
            allowed_callers=callers,
        )
    except Exception as e:
        raise PhoneConfigError(str(e)) from e

    return twilio_cfg, phone_cfg
