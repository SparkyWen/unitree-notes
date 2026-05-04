#!/usr/bin/env python3
"""Listen on the mic and print 'WAKE' every time the wake word fires.

Use to tune rms_threshold and confirm the faster-whisper model loaded.

Usage:
    conda activate agi
    cd ~/unitree/unitree-notes/va-demo
    python scripts/wake_word_debug.py [--rms 1500] [--phrase "hi sparky"]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.audio_io import MicStream
from va_demo.spoken_cache import SpokenTranscriptCache
from va_demo.wake_word import FasterWhisperBackend, WakeWordDetector


async def amain(args):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mic = MicStream(samplerate=24000, block_ms=50)
    mic.loop = asyncio.get_event_loop()
    mic.start()
    cache = SpokenTranscriptCache()
    backend = FasterWhisperBackend(
        model_size=args.model_size,
        compute_type=args.compute_type,
        device=args.device,
    )

    def _on_wake(evt):
        print(f"WAKE @ {evt.t:.2f}: {evt.text!r}", flush=True)

    detector = WakeWordDetector(
        backend=backend,
        spoken_cache=cache,
        on_wake=_on_wake,
        samplerate=24000,
        rolling_window_s=1.5,
        inference_rate_hz=2.0,
        rms_threshold=args.rms,
        cooldown_s=1.0,
        phrases=[args.phrase] if args.phrase else None,
    )
    detector.start()
    q = mic.queue
    print("listening; press Ctrl-C to stop")
    try:
        while True:
            chunk = await q.get()
            detector.feed(chunk)
    except KeyboardInterrupt:
        pass
    finally:
        detector.stop()
        mic.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rms", type=int, default=1500)
    p.add_argument("--phrase", type=str, default=None)
    p.add_argument("--model-size", default="tiny")
    p.add_argument("--compute-type", default="int8")
    p.add_argument("--device", default="cpu")
    args = p.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
