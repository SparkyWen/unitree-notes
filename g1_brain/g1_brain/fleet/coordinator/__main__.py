"""Run the read-only coordinator: python -m g1_brain.fleet.coordinator"""
from __future__ import annotations

import argparse
from pathlib import Path

from aiohttp import web

from g1_brain.fleet.coordinator.app import build_coordinator_app


def build_default_app(*, db_path: Path) -> web.Application:
    return build_coordinator_app(db_path=Path(db_path))


def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--db", default="logs/fleet/fleet.sqlite")
    args = ap.parse_args()
    app = build_default_app(db_path=Path(args.db))
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
