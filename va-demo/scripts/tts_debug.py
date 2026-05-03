#!/usr/bin/env python
"""Synth one TTS clip and play through the speaker.

Usage:
    python scripts/tts_debug.py "你好，我是 G1。"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.audio_io import SpeakerStream
from va_demo.tts import TTSClient


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("text", nargs="*", default=["你好，我是 G1，现在处于观察模式。"])
    p.add_argument("--voice", default="alloy")
    p.add_argument("--model", default=os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"))
    args = p.parse_args()
    text = " ".join(args.text)

    from openai import OpenAI

    spk = SpeakerStream(samplerate=24000)
    spk.start()
    try:
        tts = TTSClient(OpenAI(), spk, model=args.model, voice=args.voice)
        print(f"speaking via {args.model}/{args.voice}: {text!r}")
        await tts.speak(text)
        await asyncio.sleep(1.0)  # let trailing audio drain
    finally:
        spk.close()


if __name__ == "__main__":
    asyncio.run(main())
