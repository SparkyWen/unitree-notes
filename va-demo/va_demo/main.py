"""va-demo entrypoint: wire up audio, camera, skills, vision, tts, Realtime."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import yaml

from . import audio_io, camera, safety, skills, tts, vision
from .realtime_agent import RealtimeAgent


log = logging.getLogger("va_demo")


DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "va_demo.yaml"


def _load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _build_openai_client():
    from openai import OpenAI

    return OpenAI()


def _setup_logging(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Quiet noisy libraries unless --verbose.
    if not verbose:
        logging.getLogger("websockets").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)


async def _run(args):
    cfg = _load_config(args.config)
    run_mode = args.mode or cfg.get("run_mode", "confirm")

    # ---- audio ----
    sr = cfg["audio"]["samplerate"]
    mic = audio_io.MicStream(
        samplerate=sr,
        block_ms=cfg["audio"]["block_ms"],
        device=cfg["audio"].get("input_device"),
    )
    speaker = audio_io.SpeakerStream(
        samplerate=sr,
        device=cfg["audio"].get("output_device"),
        buffer_ms=cfg["audio"]["speaker_buffer_ms"],
    )
    mic.start()
    speaker.start()

    # ---- camera ----
    cam = camera.Camera(
        host=cfg["camera"]["host"],
        request_port=cfg["camera"]["request_port"],
        request_bgr=True,
    )

    # ---- robot skills (optional) ----
    skill_backend: Optional[skills.SkillBackend] = None
    if not args.no_skills:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize

        ChannelFactoryInitialize(cfg["robot"]["domain_id"], cfg["robot"]["interface"])
        log.info("DDS initialized: domain=%d iface=%s",
                 cfg["robot"]["domain_id"], cfg["robot"]["interface"])
        skill_backend = skills.build_skill_backend()
        log.info("waiting for ComboController policy_active ...")
        # ComboController prints "[combo] policy ready" once boot ramp finishes.
        deadline = asyncio.get_event_loop().time() + 30.0
        while not skill_backend._ctl.policy_active:
            if asyncio.get_event_loop().time() > deadline:
                log.warning("policy not active after 30s; continuing anyway")
                break
            await asyncio.sleep(0.2)

    # ---- safety ----
    cfg_safety = safety.SafetyConfig(
        vx_max=cfg["safety"]["walk"]["vx_max"],
        vy_max=cfg["safety"]["walk"]["vy_max"],
        wz_max=cfg["safety"]["walk"]["wz_max"],
        duration_max_s=cfg["safety"]["walk"]["duration_max_s"],
        duration_min_s=cfg["safety"]["walk"]["duration_min_s"],
        say_max_chars=cfg["safety"]["say"]["max_chars"],
    )
    wd = safety.WatchdogState(
        last_frame_age_provider=cam.frame_age_seconds,
        last_lowstate_age_provider=(skill_backend.lowstate_age_seconds if skill_backend else (lambda: 0.0)),
        max_frame_age_s=cfg["safety"]["watchdog"]["max_frame_age_s"],
        max_lowstate_age_s=cfg["safety"]["watchdog"]["max_lowstate_age_s"],
    )
    sup = safety.SafetySupervisor(cfg_safety, wd, run_mode=run_mode)
    log.info("run_mode=%s", run_mode)

    # ---- openai clients ----
    openai_client = _build_openai_client()
    vision_client = vision.VisionClient(
        openai_client,
        model=os.environ.get("OPENAI_VISION_MODEL", cfg["openai"]["vision_model"]),
        default_detail=cfg["openai"]["vision_detail"],
    )
    tts_client = tts.TTSClient(
        openai_client,
        speaker,
        model=os.environ.get("OPENAI_TTS_MODEL", cfg["openai"]["tts_model"]),
        voice=cfg["openai"]["tts_voice"],
    )

    # ---- realtime ----
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and not args.no_realtime:
        log.error("OPENAI_API_KEY is not set; either export it or pass --no-realtime")
        sys.exit(2)

    if args.no_realtime:
        log.info("realtime disabled; idling — useful with debug scripts. Press Ctrl-C to exit.")
        try:
            while True:
                await asyncio.sleep(1.0)
        finally:
            pass
    else:
        agent = RealtimeAgent(
            api_key=api_key,
            model=os.environ.get("OPENAI_REALTIME_MODEL", cfg["openai"]["realtime_model"]),
            voice=cfg["openai"]["realtime_voice"],
            mic=mic,
            speaker=speaker,
            camera=cam,
            vision=vision_client,
            tts=tts_client,
            skills=skill_backend,
            safety=sup,
            vision_resize_width=cfg["camera"]["vision_resize_width"],
            vision_jpeg_quality=cfg["camera"]["vision_jpeg_quality"],
        )
        try:
            await agent.run()
        finally:
            log.info("shutting down ...")

    # ---- shutdown ----
    if skill_backend is not None:
        skill_backend.shutdown()
    cam.close()
    mic.close()
    speaker.close()


def parse_args():
    p = argparse.ArgumentParser(description="va-demo: G1 vision+audio+Realtime agent")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--mode", choices=["observe", "confirm", "active"], default=None,
                   help="run mode (overrides config)")
    p.add_argument("--no-realtime", action="store_true",
                   help="don't connect to Realtime; useful for debugging audio/camera only")
    p.add_argument("--no-skills", action="store_true",
                   help="don't init DDS / ComboController; tool calls for motion will fail")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    _setup_logging(args.verbose)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    stop_evt = asyncio.Event()

    def _on_signal(*_):
        log.info("signal received, shutting down")
        loop.call_soon_threadsafe(stop_evt.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_evt.set())

    main_task = loop.create_task(_run(args))

    async def _supervise():
        await stop_evt.wait()
        if not main_task.done():
            main_task.cancel()

    sup_task = loop.create_task(_supervise())

    try:
        loop.run_until_complete(main_task)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        sup_task.cancel()
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()


if __name__ == "__main__":
    main()
