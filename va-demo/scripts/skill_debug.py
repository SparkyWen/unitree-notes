#!/usr/bin/env python
"""Exercise SkillBackend without OpenAI. Drives ComboController via stdin.

Requires unitree_mujoco simulator running on domain 1, interface lo.

Keys:
  w/s/a/d/q/e   walk in that direction for 0.5 s
  1..8          gesture
  r             stop
  0             release_arms
  x             quit
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--domain", type=int, default=1)
    p.add_argument("--iface", default="lo")
    return p.parse_args()


async def main(args):
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize

    from va_demo.skills import GESTURE_KEY_MAP, build_skill_backend

    ChannelFactoryInitialize(args.domain, args.iface)
    skills = build_skill_backend()
    print("waiting for policy_active ...", flush=True)
    for _ in range(150):
        if skills._ctl.policy_active:
            break
        await asyncio.sleep(0.2)
    print("ready. type a key (followed by enter): w/s/a/d/q/e/1..8/r/0/x")

    name_by_key = {v: k for k, v in GESTURE_KEY_MAP.items()}

    loop = asyncio.get_event_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            ch = line.strip()[:1]
            if ch == "x":
                break
            if ch == "w":
                await skills.walk(0.15, 0, 0, 0.5)
            elif ch == "s":
                await skills.walk(-0.15, 0, 0, 0.5)
            elif ch == "a":
                await skills.walk(0, 0.08, 0, 0.5)
            elif ch == "d":
                await skills.walk(0, -0.08, 0, 0.5)
            elif ch == "q":
                await skills.walk(0, 0, 0.3, 0.5)
            elif ch == "e":
                await skills.walk(0, 0, -0.3, 0.5)
            elif ch in name_by_key:
                await skills.gesture(name_by_key[ch])
            elif ch == "r":
                await skills.stop()
            elif ch == "0":
                await skills.release_arms()
    finally:
        skills.shutdown()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
