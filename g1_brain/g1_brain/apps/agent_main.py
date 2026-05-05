"""g1_brain main entry point.

Wires the full Slow-Brain + Fast-Reflex + Safe-Skill pipeline together,
mirroring va-demo/va_demo/main.py's structure but with the new subsystems.

Run modes:
    --mode observe   motion blocked entirely
    --mode confirm   prompt y/N in terminal before each motion (default)
    --mode active    motion executes immediately within safety bounds

Bypass flags (mostly for debugging individual subsystems):
    --no-realtime    skip OpenAI Realtime websocket (idle)
    --no-skills      skip DDS / ComboController init
    --no-perception  skip PerceptionRunner
    --no-wakeword    keep the Realtime uplink always-on (no wake-word gating)
    --vision-only    drop motion tools; implies --no-skills
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


log = logging.getLogger("g1_brain")


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CONFIG = REPO_ROOT / "g1_brain" / "configs" / "g1_brain.yaml"


# ---------------------------------------------------------------------------
# Path / logging / config helpers
# ---------------------------------------------------------------------------


def _ensure_sibling_repos_on_path() -> None:
    """Add ~/unitree/unitree-notes/{va-demo,g1_sim_demo} to sys.path.

    Both packages live alongside g1_brain in the unitree-notes workspace and
    are imported directly; we do not pip-install them.
    """
    home = Path.home()
    candidates = [
        home / "unitree" / "unitree-notes" / "va-demo",
        home / "unitree" / "unitree-notes" / "g1_sim_demo",
    ]
    for p in candidates:
        sp = str(p)
        if p.exists() and sp not in sys.path:
            sys.path.insert(0, sp)


def _setup_logging(verbose: bool, log_dir: Optional[Path] = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_dir / "agent.log", encoding="utf-8")
            handlers.append(fh)
        except OSError as e:
            print(f"[g1_brain] could not open log file: {e}", file=sys.stderr)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    if not verbose:
        logging.getLogger("websockets").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)


def _expand_env_in_obj(obj: Any) -> Any:
    """Recursively walk a yaml-loaded structure and ``os.path.expandvars`` strings.

    This is what gives us ``${HOME}`` substitution in mjcf_path / log_dir etc.
    """
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    if isinstance(obj, list):
        return [_expand_env_in_obj(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _expand_env_in_obj(v) for k, v in obj.items()}
    return obj


def _load_config(path: Path) -> Dict[str, Any]:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return _expand_env_in_obj(cfg)


# ---------------------------------------------------------------------------
# RobotState producer — bridges combo's lowstate into RobotStateBus
# ---------------------------------------------------------------------------


class _RobotStateProducer:
    """Polls ComboController.low_state at ~20 Hz and pushes RobotState.

    This avoids subscribing to ``rt/lowstate`` a second time (combo already
    does it). The watchdogs read from RobotStateBus, not directly from combo.
    """

    def __init__(self, combo_ctl, robot_bus, fsm, hz: float = 20.0):
        from ..safety.pose_check import gravity_proj_z_from_quat

        self._combo = combo_ctl
        self._bus = robot_bus
        self._fsm = fsm
        self._period = 1.0 / max(hz, 1.0)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._gravity_proj_z_from_quat = gravity_proj_z_from_quat

    def start(self) -> None:
        from ..scene_state.types import RobotState

        self._RobotState = RobotState
        self._thread = threading.Thread(
            target=self._loop, name="g1-brain-robotstate", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001 — keep the daemon alive
                log.exception("robotstate producer tick failed")
            self._stop.wait(self._period)

    def _tick(self) -> None:
        s = getattr(self._combo, "low_state", None)
        last_t = float(getattr(self._combo, "last_state_time", 0.0))
        if s is None or last_t <= 0:
            return
        try:
            quat = (
                float(s.imu_state.quaternion[0]),
                float(s.imu_state.quaternion[1]),
                float(s.imu_state.quaternion[2]),
                float(s.imu_state.quaternion[3]),
            )
            gz = self._gravity_proj_z_from_quat(quat)
        except Exception:  # noqa: BLE001
            gz = -1.0
        try:
            ang_vel = (
                float(s.imu_state.gyroscope[0]),
                float(s.imu_state.gyroscope[1]),
                float(s.imu_state.gyroscope[2]),
            )
        except Exception:  # noqa: BLE001
            ang_vel = (0.0, 0.0, 0.0)
        rs = self._RobotState(
            standing=bool(getattr(self._combo, "policy_active", False)),
            gravity_proj_z=gz,
            base_ang_vel_xyz=ang_vel,
            rl_policy_active=bool(getattr(self._combo, "policy_active", False)),
            last_lowstate_age_s=max(0.0, time.monotonic() - last_t),
            mode_machine=int(getattr(self._combo, "mode_machine", 0)),
        )
        self._bus.update(rs)


# ---------------------------------------------------------------------------
# Optional / defensive imports
# ---------------------------------------------------------------------------


def _try_import_combo():
    """Import g1_sim_rl_combo defensively (DDS may be missing)."""
    try:
        import g1_sim_rl_combo  # type: ignore
        return g1_sim_rl_combo
    except Exception as e:  # noqa: BLE001
        log.error("could not import g1_sim_rl_combo: %s", e)
        return None


def _try_import_camera_hub():
    try:
        from ..perception.cameras import CameraHub
        return CameraHub
    except Exception as e:  # noqa: BLE001
        log.warning("CameraHub import failed (perception likely degraded): %s", e)
        return None


def _try_build_perception_runner(cfg, scene_bus, robot_bus):
    try:
        from ..perception.runner import PerceptionRunner
    except Exception as e:  # noqa: BLE001
        log.warning("PerceptionRunner import failed (mediapipe/ultralytics?): %s", e)
        return None
    try:
        return PerceptionRunner(cfg, scene_bus, robot_bus)
    except Exception as e:  # noqa: BLE001
        log.warning("PerceptionRunner construction failed: %s", e)
        return None


def _try_build_skill_server(*, combo_ctl, safety, tts, vision, camera_hub,
                            scene_bus, fsm, sim: bool = True):
    try:
        from ..skills.skill_server import SkillServer
    except Exception as e:  # noqa: BLE001
        log.error("SkillServer import failed: %s", e)
        return None
    return SkillServer(
        combo_ctl=combo_ctl,
        safety=safety,
        tts=tts,
        vision=vision,
        camera_hub=camera_hub,
        scene_bus=scene_bus,
        fsm=fsm,
        sim=sim,
    )


class _PermissiveSafety:
    """Stub safety that always lets calls through.

    The parent va_demo.RealtimeAgent._dispatch_tool calls safety.validate()
    BEFORE _execute_tool. Our _execute_tool re-runs the real SafetySupervisor
    inside SkillServer.execute(). Without this stub the real validate()
    would run twice — and in confirm mode the user would see the y/N prompt
    twice per tool call. Pass this stub to the parent dataclass field
    `safety`; the SkillServer still uses the real one internally.
    """

    async def validate(self, tool, args):
        return (True, "", args)


def _try_build_brain_agent(*, skill_server, scene_bus, mock_imitate_trigger=None,
                           **rt_kwargs):
    from ..brain.realtime_agent import BrainRealtimeAgent

    rt_kwargs["safety"] = _PermissiveSafety()
    return BrainRealtimeAgent(
        skill_server=skill_server,
        scene_bus=scene_bus,
        mock_imitate_trigger=mock_imitate_trigger,
        **rt_kwargs,
    )


def _try_build_gesture_auto_trigger(scene_bus, brain_agent, cfg):
    try:
        from ..mock_imitation.auto_trigger import GestureAutoTrigger
    except Exception as e:  # noqa: BLE001
        log.warning("GestureAutoTrigger import failed: %s", e)
        return None
    try:
        return GestureAutoTrigger(scene_bus, brain_agent, cfg)
    except Exception as e:  # noqa: BLE001
        log.warning("GestureAutoTrigger build failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Main async run
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> int:
    cfg = _load_config(args.config)
    run_mode = args.mode or cfg.get("run_mode", "confirm")

    if args.vision_only and not args.no_skills:
        log.info("--vision-only implies --no-skills; skipping DDS / RL init")
        args.no_skills = True

    # ---- audio ----
    from va_demo import audio_io  # noqa: WPS433
    sr = int(cfg["audio"]["samplerate"])
    mic = audio_io.MicStream(
        samplerate=sr,
        block_ms=int(cfg["audio"]["block_ms"]),
        device=cfg["audio"].get("input_device"),
    )
    speaker = audio_io.SpeakerStream(
        samplerate=sr,
        device=cfg["audio"].get("output_device"),
        buffer_ms=int(cfg["audio"]["speaker_buffer_ms"]),
    )
    mic.start()
    speaker.start()

    # ---- camera hub ----
    CameraHub = _try_import_camera_hub()
    camera_hub = None
    if CameraHub is not None:
        try:
            camera_hub = CameraHub(cfg)
        except Exception as e:  # noqa: BLE001
            log.warning("CameraHub construction failed: %s", e)
            camera_hub = None

    # ---- combo controller (optional) ----
    combo_ctl = None
    if not args.no_skills:
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize  # noqa: WPS433
        except Exception as e:  # noqa: BLE001
            log.error("unitree_sdk2py not available; skipping skills: %s", e)
            args.no_skills = True

    if not args.no_skills:
        ChannelFactoryInitialize(int(cfg["robot"]["domain_id"]),
                                 str(cfg["robot"]["interface"]))
        log.info("DDS initialized: domain=%d iface=%s",
                 int(cfg["robot"]["domain_id"]), str(cfg["robot"]["interface"]))
        combo_mod = _try_import_combo()
        if combo_mod is None:
            log.error("combo controller unavailable; continuing with --no-skills")
            args.no_skills = True
        else:
            try:
                policy_yaml = combo_mod.POLICY_YAML
                policy_onnx = combo_mod.POLICY_ONNX
                deploy_cfg = combo_mod.DeployCfg(policy_yaml)
                policy = combo_mod.Policy(policy_onnx)
                combo_ctl = combo_mod.ComboController(deploy_cfg, policy)
                combo_ctl.init_dds()
                combo_ctl.start()
            except Exception as e:  # noqa: BLE001
                log.exception("ComboController init failed: %s", e)
                combo_ctl = None
                args.no_skills = True

    if combo_ctl is not None:
        log.info("waiting for ComboController policy_active ...")
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 30.0
        while not getattr(combo_ctl, "policy_active", False):
            if loop.time() > deadline:
                log.warning("policy not active after 30s; continuing anyway")
                break
            await asyncio.sleep(0.2)

    # ---- scene + robot buses ----
    from ..scene_state.fusion import RobotStateBus, SceneStateBus

    scene_bus = SceneStateBus()
    robot_bus = RobotStateBus()

    # ---- FSM ----
    from ..safety.state_machine import RobotFsm, RobotFsmState

    fsm = RobotFsm()

    robot_state_producer: Optional[_RobotStateProducer] = None
    if combo_ctl is not None:
        robot_state_producer = _RobotStateProducer(combo_ctl, robot_bus, fsm=fsm)
        robot_state_producer.start()
    # Components are "ready"; transition to STANDING.
    try:
        fsm.transition(RobotFsmState.STANDING, "boot complete")
    except Exception:  # noqa: BLE001
        log.exception("could not transition BOOT -> STANDING; staying in BOOT")

    # ---- E-stop ----
    from ..safety.estop_client import EstopClient

    estop_path = cfg.get("safety", {}).get("estop", {}).get("flag_path",
                                                            "/tmp/g1_brain_estop")
    estop = EstopClient(estop_path)
    if estop.is_engaged():
        log.warning("E-stop is already engaged at startup: %s", estop.reason())
        try:
            fsm.transition(RobotFsmState.EMERGENCY_STOP, "estop engaged at boot")
        except Exception:  # noqa: BLE001
            pass

    # ---- safety supervisor + watchdogs ----
    from ..safety.supervisor import SafetySupervisor

    safety = SafetySupervisor(
        cfg=cfg,
        scene_bus=scene_bus,
        robot_bus=robot_bus,
        fsm=fsm,
        estop=estop,
        run_mode=run_mode,
    )
    log.info("run_mode=%s", run_mode)

    watchdogs = None
    try:
        from ..safety.watchdogs import WatchdogManager
    except Exception as e:  # noqa: BLE001
        log.warning("WatchdogManager import failed; running without watchdogs: %s", e)
    else:
        try:
            watchdogs = WatchdogManager(
                cfg=cfg,
                scene_bus=scene_bus,
                robot_bus=robot_bus,
                fsm=fsm,
                combo_ctl=combo_ctl,
                supervisor=safety,
            )
            watchdogs.start()
        except Exception as e:  # noqa: BLE001
            log.warning("WatchdogManager construction failed: %s", e)
            watchdogs = None

    # ---- perception ----
    perception = None
    if not args.no_perception:
        perception = _try_build_perception_runner(cfg, scene_bus, robot_bus)
        if perception is not None:
            try:
                perception.start()
            except Exception as e:  # noqa: BLE001
                log.warning("PerceptionRunner.start failed: %s", e)
                perception = None

    # ---- TTS + vision ----
    from openai import OpenAI
    from va_demo import tts as va_tts, vision as va_vision  # noqa: WPS433
    from va_demo.spoken_cache import SpokenTranscriptCache

    openai_client = OpenAI()
    spoken_cache = SpokenTranscriptCache()
    tts_client = va_tts.TTSClient(
        openai_client,
        speaker,
        model=os.environ.get("OPENAI_TTS_MODEL", cfg["openai"]["tts_model"]),
        voice=cfg["openai"]["tts_voice"],
        spoken_cache=spoken_cache,
    )
    vision_client = va_vision.VisionClient(
        openai_client,
        model=os.environ.get("OPENAI_VISION_MODEL", cfg["openai"]["vision_model"]),
        default_detail=cfg["openai"]["vision_detail"],
    )

    # ---- skill server ----
    skill_server = None
    if not args.vision_only:
        skill_server = _try_build_skill_server(
            combo_ctl=combo_ctl,
            safety=safety,
            tts=tts_client,
            vision=vision_client,
            camera_hub=camera_hub,
            scene_bus=scene_bus,
            fsm=fsm,
            sim=(cfg.get("mode", "sim") == "sim"),
        )

    # ---- brain realtime agent ----
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and not args.no_realtime:
        log.error("OPENAI_API_KEY is not set; either export it or pass --no-realtime")
        return 2

    brain_agent = None
    if not args.no_realtime:
        try:
            brain_agent = _try_build_brain_agent(
                skill_server=skill_server,
                scene_bus=scene_bus,
                mock_imitate_trigger=None,
                api_key=api_key,
                model=os.environ.get(
                    "OPENAI_REALTIME_MODEL", cfg["openai"]["realtime_model"]
                ),
                voice=cfg["openai"]["realtime_voice"],
                mic=mic,
                speaker=speaker,
                camera=camera_hub,
                vision=vision_client,
                tts=tts_client,
                skills=skill_server,
                safety=safety,
                vision_only=args.vision_only,
                spoken_cache=spoken_cache,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("BrainRealtimeAgent build failed: %s", e)
            brain_agent = None

    # ---- wake-word + utterance + conversation state machine ----
    sm = None
    if (
        brain_agent is not None
        and not args.no_wakeword
        and (cfg.get("wakeword", {}) or {}).get("enabled", True)
    ):
        sm = _build_state_machine(cfg, sr, mic, brain_agent, spoken_cache)
    elif brain_agent is not None:
        log.info("wake-word DISABLED; Realtime uplink runs continuously")

    # ---- mock-imitation auto-trigger ----
    auto_trigger = None
    if (
        brain_agent is not None
        and (cfg.get("mock_imitation", {}) or {}).get("enabled", False)
    ):
        auto_trigger = _try_build_gesture_auto_trigger(
            scene_bus, brain_agent, cfg.get("mock_imitation", {}) or {}
        )
        if auto_trigger is not None:
            try:
                auto_trigger.start()
                log.info("gesture auto-trigger started")
            except Exception as e:  # noqa: BLE001
                log.warning("auto_trigger.start failed: %s", e)
                auto_trigger = None

    # ---- main loop ----
    try:
        if brain_agent is None:
            log.info("realtime disabled; idling. Ctrl-C to exit.")
            while True:
                await asyncio.sleep(1.0)
        else:
            if sm is not None:
                await sm.start()
            else:
                brain_agent.set_uplink_enabled(True)
            await brain_agent.run()
    finally:
        log.info("shutting down ...")
        if sm is not None:
            try:
                await sm.stop()
            except Exception:  # noqa: BLE001
                log.exception("conversation sm.stop failed")
        if auto_trigger is not None:
            try:
                auto_trigger.stop()
            except Exception:  # noqa: BLE001
                log.exception("auto_trigger.stop failed")
        if perception is not None:
            try:
                perception.stop()
            except Exception:  # noqa: BLE001
                log.exception("perception.stop failed")
        if watchdogs is not None:
            try:
                watchdogs.stop()
            except Exception:  # noqa: BLE001
                log.exception("watchdogs.stop failed")
        if robot_state_producer is not None:
            try:
                robot_state_producer.stop()
            except Exception:  # noqa: BLE001
                log.exception("robot_state_producer.stop failed")
        if combo_ctl is not None:
            try:
                combo_ctl.stop_and_settle()
            except Exception:  # noqa: BLE001
                log.exception("combo.stop_and_settle failed")
        if camera_hub is not None:
            try:
                camera_hub.close()
            except Exception:  # noqa: BLE001
                log.exception("camera_hub.close failed")
        try:
            mic.close()
        except Exception:  # noqa: BLE001
            log.exception("mic.close failed")
        try:
            speaker.close()
        except Exception:  # noqa: BLE001
            log.exception("speaker.close failed")
    return 0


def _build_state_machine(cfg, sr, mic, brain_agent, spoken_cache):
    """Wake-word + UtteranceVAD + ConversationStateMachine, mirrors va-demo."""
    from va_demo.conversation_state import ConversationConfig, ConversationStateMachine
    from va_demo.utterance_vad import UtteranceVAD
    from va_demo.wake_word import (
        FasterWhisperBackend,
        OpenAITranscribeBackend,
        WakeWordDetector,
    )

    wakeword_cfg = cfg.get("wakeword", {}) or {}
    utt_cfg = cfg.get("utterance", {}) or {}
    conv_cfg = cfg.get("conversation", {}) or {}

    backend_name = (wakeword_cfg.get("backend") or "openai").lower()
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
        raise ValueError(f"unknown wakeword.backend={backend_name!r}")

    utt_vad = UtteranceVAD(
        samplerate=sr,
        silence_threshold_ms=int(utt_cfg.get("silence_threshold_ms", 1500)),
        max_duration_s=float(utt_cfg.get("max_duration_s", 30.0)),
        aggressiveness=int(utt_cfg.get("vad_aggressiveness", 2)),
    )

    sm_holder: Dict[str, Any] = {"sm": None}

    def _on_wake(evt):
        sm = sm_holder["sm"]
        if sm is not None:
            sm.handle_wake(evt)

    wake = WakeWordDetector(
        backend=backend,
        spoken_cache=spoken_cache,
        on_wake=_on_wake,
        samplerate=sr,
        rolling_window_s=float(wakeword_cfg.get("rolling_window_s", 1.5)),
        inference_rate_hz=float(wakeword_cfg.get("inference_rate_hz", 2.0)),
        rms_threshold=int(wakeword_cfg.get("rms_threshold", 100)),
        cooldown_s=float(wakeword_cfg.get("cooldown_s", 2.0)),
        phrases=wakeword_cfg.get("phrases") or ["hi sparky"],
        selfecho_window_s=float(conv_cfg.get("selfecho_dedup_window_s", 6.0)),
    )

    sm = ConversationStateMachine(
        cfg=ConversationConfig(
            listening_window_s=float(conv_cfg.get("listening_window_s", 8.0)),
            no_speech_timeout_s=float(utt_cfg.get("no_speech_timeout_s", 4.0)),
        ),
        wake_word=wake,
        utterance_vad=utt_vad,
        realtime_agent=brain_agent,
        mic=mic,
    )
    sm_holder["sm"] = sm

    brain_agent.on_response_audio_delta = sm.handle_response_audio_delta
    brain_agent.on_response_done = sm.handle_response_done
    log.info("wake-word enabled: phrases=%s", wakeword_cfg.get("phrases"))
    return sm


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="g1_brain.apps.agent_main",
        description="g1_brain: Slow Brain + Fast Reflex + Safe Skill agent (MuJoCo sim)",
    )
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                   help=f"YAML config path (default: {DEFAULT_CONFIG})")
    p.add_argument("--mode", choices=["observe", "confirm", "active"], default=None,
                   help="run mode (overrides config.run_mode)")
    p.add_argument("--no-realtime", action="store_true",
                   help="don't connect to OpenAI Realtime (idle, useful for debugging)")
    p.add_argument("--no-skills", action="store_true",
                   help="don't init DDS / ComboController; motion tools will fail")
    p.add_argument("--no-perception", action="store_true",
                   help="don't start the PerceptionRunner")
    p.add_argument("--no-wakeword", action="store_true",
                   help="disable wake-word gating; mic streams continuously to Realtime")
    p.add_argument("--vision-only", action="store_true",
                   help="vision-only test mode: drop motion tools, skip DDS init "
                        "(implies --no-skills)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="DEBUG-level logging")
    return p.parse_args(argv)


def main() -> int:
    _ensure_sibling_repos_on_path()
    args = parse_args()

    # Try to read log_dir before logging setup, so the file handler picks the
    # right path. Failure here is non-fatal — we just log to stderr.
    log_dir = None
    try:
        cfg_preview = _load_config(args.config)
        log_dir_str = (cfg_preview.get("logging", {}) or {}).get("log_dir")
        if log_dir_str:
            log_dir = Path(log_dir_str)
    except Exception:  # noqa: BLE001
        pass

    _setup_logging(args.verbose, log_dir=log_dir)

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
        try:
            loop.run_until_complete(asyncio.sleep(0))
        except Exception:  # noqa: BLE001
            pass
        loop.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
