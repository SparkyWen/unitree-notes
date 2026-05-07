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
from .conversation_state import ConversationConfig, ConversationStateMachine
from .realtime_agent import RealtimeAgent
from .spoken_cache import SpokenTranscriptCache
from .utterance_vad import UtteranceVAD
from .wake_word import (
    FasterWhisperBackend,
    OpenAITranscribeBackend,
    WakeWordDetector,
)


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
    if not verbose:
        logging.getLogger("websockets").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)


async def _run(args):
    cfg = _load_config(args.config)
    run_mode = args.mode or cfg.get("run_mode", "confirm")

    if args.vision_only:
        # Vision-only mode runs without DDS / ComboController; mujoco does not
        # need to be running. The existing --no-skills branch handles the
        # rest of the bypass.
        if not args.no_skills:
            log.info("--vision-only implies --no-skills; skipping DDS init")
        args.no_skills = True

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
    if args.mujoco_camera:
        from . import mujoco_camera as mjcam

        cam_cfg = cfg.get("camera", {}) or {}
        mjcf_path = os.path.expanduser(os.path.expandvars(
            cam_cfg.get("mjcf_path")
            or os.environ.get(
                "G1_MJCF_PATH",
                "~/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_29dof.xml",
            )
        ))
        cam = mjcam.MuJoCoHeadCamera(
            mjcf_path=mjcf_path,
            camera_name=cam_cfg.get("camera_name", "head_camera"),
            width=int(cam_cfg.get("head_width", 640)),
            height=int(cam_cfg.get("head_height", 480)),
            poll_hz=float(cam_cfg.get("head_poll_hz", 20.0)),
            subscribe_dds=not args.no_skills,
        )
        log.info("mujoco-camera enabled: mjcf=%s subscribe_dds=%s",
                 mjcf_path, not args.no_skills)
    else:
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
    spoken_cache = SpokenTranscriptCache()
    tts_client = tts.TTSClient(
        openai_client,
        speaker,
        model=os.environ.get("OPENAI_TTS_MODEL", cfg["openai"]["tts_model"]),
        voice=cfg["openai"]["tts_voice"],
        spoken_cache=spoken_cache,
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
        # ---- shutdown ----
        if skill_backend is not None:
            skill_backend.shutdown()
        cam.close()
        mic.close()
        speaker.close()
        return

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
        spoken_cache=spoken_cache,
        vision_only=args.vision_only,
    )
    if args.vision_only:
        log.info("vision-only mode: tools=[say, describe_scene]; motion tools removed")

    sm: Optional[ConversationStateMachine] = None
    wakeword_cfg = cfg.get("wakeword", {}) or {}
    if not args.no_wakeword and wakeword_cfg.get("enabled", True):
        utt_cfg = cfg.get("utterance", {}) or {}
        conv_cfg = cfg.get("conversation", {}) or {}
        backend_name = (wakeword_cfg.get("backend") or "openai").lower()
        try:
            if backend_name == "openai":
                backend = OpenAITranscribeBackend(
                    model=wakeword_cfg.get("openai_model", "gpt-4o-transcribe"),
                    prompt=wakeword_cfg.get("openai_prompt", "Sparky"),
                    language=wakeword_cfg.get("language") or None,
                )
            elif backend_name == "local":
                backend = FasterWhisperBackend(
                    model_size=wakeword_cfg.get("model_size", "tiny"),
                    compute_type=wakeword_cfg.get("compute_type", "int8"),
                    device=wakeword_cfg.get("device", "cpu"),
                    language=wakeword_cfg.get("language") or None,
                )
            else:
                log.error(
                    "unknown wakeword.backend=%r (expected 'openai' or 'local')",
                    backend_name,
                )
                sys.exit(3)
        except Exception as e:
            log.error(
                "wake-word backend failed to load (%s). "
                "Re-run with --no-wakeword to fall back to always-on Realtime.",
                e,
            )
            sys.exit(3)
        utt_vad = UtteranceVAD(
            samplerate=sr,
            silence_threshold_ms=utt_cfg.get("silence_threshold_ms", 1500),
            max_duration_s=utt_cfg.get("max_duration_s", 30.0),
            aggressiveness=utt_cfg.get("vad_aggressiveness", 2),
        )
        wake = WakeWordDetector(
            backend=backend,
            spoken_cache=spoken_cache,
            on_wake=lambda evt: sm.handle_wake(evt) if sm else None,
            samplerate=sr,
            rolling_window_s=wakeword_cfg.get("rolling_window_s", 1.5),
            inference_rate_hz=wakeword_cfg.get("inference_rate_hz", 2.0),
            rms_threshold=wakeword_cfg.get("rms_threshold", 100),
            cooldown_s=wakeword_cfg.get("cooldown_s", 2.0),
            phrases=wakeword_cfg.get("phrases") or ["hi sparky"],
            selfecho_window_s=conv_cfg.get("selfecho_dedup_window_s", 6.0),
        )
        sm = ConversationStateMachine(
            cfg=ConversationConfig(
                listening_window_s=conv_cfg.get("listening_window_s", 8.0),
                no_speech_timeout_s=utt_cfg.get("no_speech_timeout_s", 4.0),
            ),
            wake_word=wake,
            utterance_vad=utt_vad,
            realtime_agent=agent,
            mic=mic,
            speaker=speaker,
        )
        agent.on_response_audio_delta = sm.handle_response_audio_delta
        agent.on_response_done = sm.handle_response_done
        log.info("wake-word enabled: phrases=%s", wakeword_cfg.get("phrases"))
    else:
        log.info("wake-word DISABLED (--no-wakeword or wakeword.enabled=false); "
                 "Realtime uplink runs continuously")

    try:
        if sm is not None:
            await sm.start()
        else:
            agent.set_uplink_enabled(True)
        await agent.run()
    finally:
        log.info("shutting down ...")
        if sm is not None:
            await sm.stop()

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
    p.add_argument("--no-wakeword", action="store_true",
                   help="disable wake-word gating; mic streams continuously to Realtime "
                        "(use to A/B against the original behavior)")
    p.add_argument("--vision-only", action="store_true",
                   help="vision-only test mode: drop motion tools (walk/gesture/stop/release_arms) "
                        "from the Realtime schema and skip DDS/ComboController init. "
                        "Implies --no-skills. MuJoCo is not required.")
    p.add_argument("--mujoco-camera", action="store_true",
                   help="render head-camera frames from MuJoCo's offscreen view of "
                        "the simulated G1 instead of pulling from teleimager. MJCF "
                        "is read from camera.mjcf_path / G1_MJCF_PATH env / a sane "
                        "default. Subscribes to rt/lowstate to track live joint pose "
                        "when DDS is up (i.e. without --no-skills/--vision-only).")
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
