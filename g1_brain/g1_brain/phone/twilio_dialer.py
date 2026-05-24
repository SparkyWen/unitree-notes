"""Twilio REST + TwiML helpers for outbound dial.

We use the REST API directly via aiohttp rather than the synchronous
`twilio` SDK so we stay inside the asyncio loop. The official SDK is
used only for type names (not strictly required).
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

import aiohttp

from .config import TwilioConfig


log = logging.getLogger(__name__)


class TwilioDialError(RuntimeError):
    pass


_API_BASE = "https://api.twilio.com/2010-04-01"


class TwilioDialer:
    def __init__(self, cfg: TwilioConfig, public_bridge_url: str) -> None:
        self._cfg = cfg
        self._public_bridge_url = public_bridge_url

    def build_twiml(self, brain_session_id: str) -> str:
        # Note: <Stream> URL is inserted verbatim; caller must ensure it
        # has no XML-special chars (a wss:// URL never does).
        return (
            "<Response>"
            "<Connect>"
            f'<Stream url="{self._public_bridge_url}">'
            f'<Parameter name="brain_session_id" value="{brain_session_id}"/>'
            "</Stream>"
            "</Connect>"
            "</Response>"
        )

    async def dial(
        self, to: str, brain_session_id: Optional[str] = None
    ) -> str:
        """POST /Accounts/{sid}/Calls.json. Returns CallSid on success."""
        bsid = brain_session_id or str(uuid.uuid4())
        twiml = self.build_twiml(bsid)
        url = f"{_API_BASE}/Accounts/{self._cfg.account_sid}/Calls.json"
        auth = aiohttp.BasicAuth(
            self._cfg.api_key_sid, self._cfg.api_key_secret.get_secret_value()
        )
        data = {
            "To": to,
            "From": self._cfg.from_number,
            "Twiml": twiml,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, auth=auth) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise TwilioDialError(
                        f"dial({to}) failed {resp.status}: {text}"
                    )
                body = await resp.json()
                sid = body.get("sid")
                if not sid:
                    raise TwilioDialError(f"no sid in response: {body}")
                log.info("twilio.dial ok to=%s sid=%s", to, sid)
                return sid

    async def hangup(self, call_sid: str) -> None:
        """POST /Calls/{sid}.json Status=completed."""
        url = (
            f"{_API_BASE}/Accounts/{self._cfg.account_sid}"
            f"/Calls/{call_sid}.json"
        )
        auth = aiohttp.BasicAuth(
            self._cfg.api_key_sid, self._cfg.api_key_secret.get_secret_value()
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={"Status": "completed"}, auth=auth) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    log.warning("twilio.hangup(%s) %s: %s", call_sid, resp.status, text)

    async def dry_run(self) -> str:
        """GET /Accounts/{sid}.json. Returns the account's friendly_name."""
        url = f"{_API_BASE}/Accounts/{self._cfg.account_sid}.json"
        auth = aiohttp.BasicAuth(
            self._cfg.api_key_sid, self._cfg.api_key_secret.get_secret_value()
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=auth) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise TwilioDialError(
                        f"dry_run failed {resp.status}: {text}"
                    )
                body = await resp.json()
                return str(body.get("friendly_name", "(unknown)"))
