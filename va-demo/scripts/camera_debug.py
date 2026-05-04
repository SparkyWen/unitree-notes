#!/usr/bin/env python
"""Pull one frame from teleimager, send to vision API, print description.

Requires:
  - teleimager.image_server running on 127.0.0.1
  - OPENAI_API_KEY exported

Usage:
    python scripts/camera_debug.py [--question "..."] [--detail medium]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.camera import Camera
from va_demo.prompts import VISION_SCENE_PROMPT
from va_demo.vision import VisionClient


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--question", default="")
    p.add_argument("--detail", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--model", default=os.environ.get("OPENAI_VISION_MODEL", "gpt-5.5"))
    args = p.parse_args()

    from openai import OpenAI

    cam = Camera(host=args.host, request_port=60000, request_bgr=True)
    print("waiting up to 5s for first frame ...", flush=True)
    for _ in range(50):
        if cam.latest_bgr() is not None:
            break
        await asyncio.sleep(0.1)
    if cam.latest_bgr() is None:
        print("no frame received; is teleimager.image_server running on", args.host, "?")
        sys.exit(1)
    b64 = cam.latest_jpeg_b64(width=1024, jpeg_quality=85)
    print(f"frame ok ({len(b64)} bytes b64). sending to {args.model} (detail={args.detail}) ...",
          flush=True)

    vc = VisionClient(OpenAI(), model=args.model, default_detail=args.detail)
    prompt = VISION_SCENE_PROMPT
    if args.question:
        prompt += f"\nUser question: {args.question}"
    text = await vc.describe(b64, prompt, detail=args.detail)
    print("\n=== vision result ===")
    print(text)
    cam.close()


if __name__ == "__main__":
    asyncio.run(main())
