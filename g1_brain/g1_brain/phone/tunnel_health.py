"""Twilio signature validation + /healthz payload helpers.

Reference: https://www.twilio.com/docs/usage/security#validating-requests

Also hosts the public-path liveness probe used to detect a dead reverse SSH
tunnel BEFORE we place an outbound call. In China the long-lived autossh
tunnel to the VPS is regularly killed by the GFW *silently* — the local
socket stays ESTABLISHED and autossh never notices, so the data channel
becomes a zombie. When that happens Twilio's Media Stream WebSocket cannot
reach the bridge and the call is dropped the instant the operator answers
(Twilio error 31920). The probe round-trips the full public path
(TLS -> VPS nginx -> reverse tunnel -> local bridge) so it catches the
zombie regardless of why ssh failed to detect it.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
from typing import Mapping, Tuple
from urllib.parse import urlsplit, urlunsplit

import aiohttp


log = logging.getLogger(__name__)


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


def healthz_url_from_bridge_url(public_bridge_url: str) -> str:
    """Derive the public https /healthz URL from the wss bridge URL.

    `wss://twilio.openproduct.cn/twilio` -> `https://twilio.openproduct.cn/healthz`
    The /healthz route lives on the same host/port as /twilio, so a 200 from
    it proves the entire public path down to the local bridge is alive.
    """
    parts = urlsplit(public_bridge_url)
    scheme = "https" if parts.scheme in ("wss", "https") else "http"
    return urlunsplit((scheme, parts.netloc, "/healthz", "", ""))


async def probe_public_path(healthz_url: str, *, timeout: float = 8.0) -> bool:
    """True iff GET healthz_url returns HTTP 200 with JSON ok==True.

    A dead/zombie tunnel surfaces here as nginx 502 or a timeout; a healthy
    path returns the bridge's own healthz payload.
    """
    try:
        timeout_cfg = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_cfg) as s:
            async with s.get(healthz_url) as resp:
                if resp.status != 200:
                    return False
                body = await resp.json(content_type=None)
                return bool(body.get("ok"))
    except Exception:
        return False


async def ensure_public_path(
    public_bridge_url: str,
    *,
    restart_cmd: str = "",
    attempts: int = 3,
    probe_timeout: float = 8.0,
    settle_s: float = 4.0,
) -> Tuple[bool, str]:
    """Verify Twilio can reach the bridge; optionally self-heal a dead tunnel.

    Returns (ok, detail). If the first probe fails and `restart_cmd` is set,
    run it and re-probe up to `attempts` times — the reverse tunnel needs a
    few seconds to rebind the remote port after a restart. With no
    `restart_cmd` this is a pure gate (probe + report) and never restarts.
    """
    healthz = healthz_url_from_bridge_url(public_bridge_url)
    if await probe_public_path(healthz, timeout=probe_timeout):
        return True, "public path healthy"
    if not restart_cmd:
        return False, (
            f"public path unreachable ({healthz}); tunnel likely down "
            f"(no restart_cmd configured)"
        )
    for i in range(1, attempts + 1):
        log.warning(
            "phone: public path DOWN (%s) — restarting tunnel "
            "(attempt %d/%d): %s",
            healthz, i, attempts, restart_cmd,
        )
        try:
            proc = await asyncio.create_subprocess_shell(
                restart_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                log.warning(
                    "phone: tunnel restart rc=%s stderr=%s",
                    proc.returncode, (stderr or b"").decode(errors="replace")[:200],
                )
        except Exception as e:  # noqa: BLE001
            return False, f"tunnel restart command failed: {e!s}"
        await asyncio.sleep(settle_s)
        if await probe_public_path(healthz, timeout=probe_timeout):
            return True, f"public path recovered after {i} tunnel restart(s)"
    return False, (
        f"public path still unreachable after {attempts} tunnel restart(s) "
        f"({healthz})"
    )
