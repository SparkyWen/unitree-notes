#!/usr/bin/env python
"""Mic -> speaker echo for ~5 s. Verifies sounddevice mic+speaker work in this env.

Usage:
    python scripts/audio_loopback.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.audio_io import MicStream, SpeakerStream, rms


async def main():
    speaker = SpeakerStream(samplerate=24000)
    speaker.start()
    mic = MicStream(samplerate=24000, block_ms=50)
    mic.start()
    print("speak into the mic for 5 seconds; you should hear yourself echoed back.")
    print("(printing RMS every chunk so you can confirm input is captured)")
    end_at = asyncio.get_event_loop().time() + 5.0
    try:
        while asyncio.get_event_loop().time() < end_at:
            chunk = await mic.queue.get()
            speaker.write(chunk)
            r = rms(chunk)
            bar = "#" * min(60, int(r / 200))
            print(f"\rrms={r:7.1f} |{bar:<60}|", end="", flush=True)
        print()
    finally:
        await asyncio.sleep(0.3)  # let the last chunks play out
        mic.close()
        speaker.close()


if __name__ == "__main__":
    asyncio.run(main())
