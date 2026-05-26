"""CLI: dial the configured operator phone number through the running bridge.

Usage:
  python -m g1_brain.phone.call_me [--to +61...] [--dry-run]

Requires:
  - .env loaded (set -a; source .env; set +a) so PhoneConfig env vars resolve
  - The bridge is running (`agent_main.py --enable-phone`) so the call has
    somewhere to land

`--dry-run` skips dialing; instead verifies Twilio creds by GETting
/Accounts/{sid}.json.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .config import load_from_env, PhoneConfigError
from .tunnel_health import ensure_public_path
from .twilio_dialer import TwilioDialer, TwilioDialError


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--to", default=None,
        help="E.164 number to dial; defaults to first PHONE_ALLOWED_CALLERS",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip dial; just verify Twilio creds via GET /Accounts/{sid}",
    )
    args = parser.parse_args(argv)

    try:
        twilio_cfg, phone_cfg = load_from_env()
    except PhoneConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    dialer = TwilioDialer(twilio_cfg, str(phone_cfg.public_bridge_url))

    if args.dry_run:
        try:
            name = await dialer.dry_run()
        except TwilioDialError as e:
            print(f"dry-run failed: {e}", file=sys.stderr)
            return 1
        print(f"Twilio credentials valid; account: {name}")
        return 0

    to = args.to or (phone_cfg.allowed_callers[0] if phone_cfg.allowed_callers else None)
    if not to:
        print("no --to and PHONE_ALLOWED_CALLERS is empty", file=sys.stderr)
        return 2

    # Don't place a call into a dead tunnel — it would ring then drop on answer.
    if phone_cfg.tunnel_healthcheck:
        ok, detail = await ensure_public_path(
            str(phone_cfg.public_bridge_url),
            restart_cmd=phone_cfg.tunnel_restart_cmd,
        )
        if not ok:
            print(f"phone link not ready: {detail}", file=sys.stderr)
            return 1
        print(f"tunnel: {detail}")

    try:
        sid = await dialer.dial(to)
    except TwilioDialError as e:
        print(f"dial failed: {e}", file=sys.stderr)
        return 1
    print(f"call placed; CallSid={sid}; To={to}")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
