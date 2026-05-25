"""Twilio signature validation + /healthz payload helpers.

Reference: https://www.twilio.com/docs/usage/security#validating-requests
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Mapping


def validate_twilio_signature(
    full_url: str,
    post_params: Mapping[str, str],
    header_signature: str,
    auth_token: str,
) -> bool:
    """Constant-time-compare an X-Twilio-Signature header.

    Algorithm: signed_string = URL + concat(sorted(key + value)) for params;
    HMAC-SHA1(signed_string, auth_token); base64 encode; compare.
    """
    data = full_url
    for k in sorted(post_params):
        data += k + post_params[k]
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(expected, header_signature)


def build_healthz_payload(*, version: str, calls_active: int) -> dict:
    """Stable JSON shape for the /healthz route."""
    return {
        "ok": True,
        "version": version,
        "calls_active": calls_active,
    }
