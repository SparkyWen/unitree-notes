"""Read-only console: format coordinator API JSON for a terminal.

Pure formatting — no new logic. A future web UI replaces this; the API is stable.
"""
from __future__ import annotations

import argparse
import asyncio
from typing import List


def format_fleet(robots: List[dict], rollup: dict) -> str:
    lines = ["=== FLEET ==="]
    for r in robots:
        st = r.get("state") or {}
        lines.append(f"  {r.get('robot_id', '?'):<12} {r.get('status', '?'):<8} "
                     f"fsm={st.get('fsm_state', '?')} "
                     f"caps={len(r.get('capabilities', []))}")
    lines.append("=== PERCEPTION ===")
    lines.append(f"  robots_reporting={rollup.get('robot_count', 0)} "
                 f"path_blocked={rollup.get('robots_path_blocked', 0)} "
                 f"with_humans={rollup.get('robots_with_humans', 0)}")
    return "\n".join(lines)


async def _fetch(base: str) -> str:
    import aiohttp
    async with aiohttp.ClientSession() as s:
        resp = await s.get(f"{base}/robots")
        resp.raise_for_status()
        robots = await resp.json()
        resp = await s.get(f"{base}/perception")
        resp.raise_for_status()
        perc = await resp.json()
    return format_fleet(robots, perc.get("rollup", {}))


def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8090")
    args = ap.parse_args()
    print(asyncio.run(_fetch(args.base)))


if __name__ == "__main__":  # pragma: no cover
    main()
