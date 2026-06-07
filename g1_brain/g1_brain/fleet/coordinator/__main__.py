"""Run the coordinator: python -m g1_brain.fleet.coordinator"""
from __future__ import annotations

import argparse
import socket
from pathlib import Path

from aiohttp import web

from g1_brain.fleet.coordinator.app import build_coordinator_app


def build_default_app(*, db_path: Path) -> web.Application:
    return build_coordinator_app(db_path=Path(db_path))


def _primary_ip() -> str:
    """Best-effort primary outbound IPv4 (the WSL2 eth0 IP under NAT)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no traffic sent; just picks the iface
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()


def _print_banner(host: str, port: int) -> None:
    ip = _primary_ip()
    bar = "=" * 64
    print(f"\n{bar}\n  Fleet Coordinator — open the dashboard in your browser:\n", flush=True)
    print(f"    http://localhost:{port}        (Windows Chrome, if WSL2 forwarding works)", flush=True)
    print(f"    http://127.0.0.1:{port}        (from inside WSL2)", flush=True)
    if ip not in ("127.0.0.1", host):
        print(f"    http://{ip}:{port}   <-- WSL2 IP fallback if localhost fails from Windows", flush=True)
    print(f"\n  Listening on {host}:{port}. If Windows can't reach localhost, use the", flush=True)
    print(f"  WSL2 IP above, or run `wsl --shutdown` in Windows and restart (see", flush=True)
    print(f"  instructions.md §7.3 'WSL2 网络排查').\n{bar}\n", flush=True)


def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--db", default="logs/fleet/fleet.sqlite")
    args = ap.parse_args()
    app = build_default_app(db_path=Path(args.db))
    _print_banner(args.host, args.port)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":  # pragma: no cover
    main()
