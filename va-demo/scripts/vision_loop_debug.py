#!/usr/bin/env python
"""1 Hz: pull frame -> vision API -> print. Useful for stress-testing latency.

Ctrl-C to stop.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.camera import Camera
from va_demo.prompts import VISION_SCENE_PROMPT
from va_demo.vision import VisionClient


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--detail", default="low", choices=["low", "medium", "high"])
    p.add_argument("--model", default=os.environ.get("OPENAI_VISION_MODEL", "gpt-5.5"))
    p.add_argument("--rate-hz", type=float, default=1.0)
    args = p.parse_args()

    from openai import OpenAI

    cam = Camera(host=args.host, request_port=60000, request_bgr=True)
    vc = VisionClient(OpenAI(), model=args.model, default_detail=args.detail)
    period = 1.0 / max(args.rate_hz, 0.1)
    print(f"sampling at {args.rate_hz} Hz; Ctrl-C to stop")
    try:
        while True:
            t0 = time.monotonic()
            b64 = cam.latest_jpeg_b64(width=768, jpeg_quality=80)
            if b64 is None:
                print("(no frame yet)")
            else:
                text = await vc.describe(b64, VISION_SCENE_PROMPT, detail=args.detail)
                dt = time.monotonic() - t0
                print(f"[{dt*1000:5.0f} ms] {text}")
            sleep_for = period - (time.monotonic() - t0)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
    except KeyboardInterrupt:
        pass
    finally:
        cam.close()


if __name__ == "__main__":
    asyncio.run(main())
