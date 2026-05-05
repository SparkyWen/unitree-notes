"""Keyboard-driven SkillServer tester.

Like g1_sim_keyboard.py but routed through SkillServer (which itself goes
through SafetySupervisor in run_mode=active with NO perception gating —
override done explicitly here for debugging).

Number keys map to the 9 skills:
  1  walk forward (vx=0.15, 0.6 s)
  2  turn left   (yaw_deg=-15)
  3  wave_right  gesture
  4  hands_up    gesture
  5  salute      gesture
  6  hug         gesture
  7  t_pose      gesture
  8  stop
  9  release_arms

  q  quit (calls combo.stop_and_settle and exits cleanly)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional

import yaml


log = logging.getLogger("g1_brain.skill_debug")


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CONFIG = REPO_ROOT / "g1_brain" / "configs" / "g1_brain.yaml"


KEY_TO_SKILL = {
    "1": ("walk", {"vx": 0.15, "vy": 0.0, "wz": 0.0, "duration_s": 0.6}),
    "2": ("turn", {"yaw_deg": -15.0}),
    "3": ("gesture", {"name": "wave_right"}),
    "4": ("gesture", {"name": "hands_up"}),
    "5": ("gesture", {"name": "salute"}),
    "6": ("gesture", {"name": "hug"}),
    "7": ("gesture", {"name": "t_pose"}),
    "8": ("stop", {}),
    "9": ("release_arms", {}),
}


def _ensure_sibling_repos_on_path() -> None:
    home = Path.home()
    for p in (
        home / "unitree" / "unitree-notes" / "va-demo",
        home / "unitree" / "unitree-notes" / "g1_sim_demo",
    ):
        sp = str(p)
        if p.exists() and sp not in sys.path:
            sys.path.insert(0, sp)


def _load_config(path: Path) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    def _x(o):
        if isinstance(o, str):
            return os.path.expandvars(o)
        if isinstance(o, list):
            return [_x(v) for v in o]
        if isinstance(o, dict):
            return {k: _x(v) for k, v in o.items()}
        return o
    return _x(cfg)


async def _async_main(args) -> int:
    cfg = _load_config(args.config)

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize  # type: ignore
    ChannelFactoryInitialize(int(cfg["robot"]["domain_id"]),
                             str(cfg["robot"]["interface"]))

    import g1_sim_rl_combo as combo_mod  # type: ignore
    deploy_cfg = combo_mod.DeployCfg(combo_mod.POLICY_YAML)
    policy = combo_mod.Policy(combo_mod.POLICY_ONNX)
    combo_ctl = combo_mod.ComboController(deploy_cfg, policy)
    combo_ctl.init_dds()
    combo_ctl.start()

    log.info("waiting for ComboController policy_active ...")
    deadline = asyncio.get_event_loop().time() + 30.0
    while not getattr(combo_ctl, "policy_active", False):
        if asyncio.get_event_loop().time() > deadline:
            log.warning("policy not active after 30s; continuing anyway")
            break
        await asyncio.sleep(0.2)

    from ..safety.estop_client import EstopClient
    from ..safety.state_machine import RobotFsm, RobotFsmState
    from ..safety.supervisor import SafetySupervisor
    from ..scene_state.fusion import RobotStateBus, SceneStateBus
    from ..scene_state.types import GroundConstraint, RobotState

    scene_bus = SceneStateBus()
    robot_bus = RobotStateBus()
    fsm = RobotFsm()
    fsm.transition(RobotFsmState.STANDING, "boot")
    fsm.transition(RobotFsmState.ENGAGED, "skill_debug")

    # Disable perception-gating by feeding clean ground state.
    import math
    scene_bus.update_ground(GroundConstraint(
        clear_path=True,
        nearest_obstacle_m=math.inf,
        nearest_person_m=math.inf,
        floor_visible_ratio=1.0,
        surface_tilt_deg=0.0,
    ))
    import time
    now = time.monotonic()
    scene_bus.update_head_frame(ts=now, resolution=(640, 480))
    scene_bus.update_usb_frame(ts=now, resolution=(640, 480))

    estop = EstopClient(cfg.get("safety", {}).get("estop", {})
                        .get("flag_path", "/tmp/g1_brain_estop"))

    safety = SafetySupervisor(
        cfg=cfg,
        scene_bus=scene_bus,
        robot_bus=robot_bus,
        fsm=fsm,
        estop=estop,
        run_mode="active",
        confirm_fn=lambda *_a, **_k: _async_true(),
    )

    # Background pump from combo to RobotStateBus
    from .agent_main import _RobotStateProducer
    rsp = _RobotStateProducer(combo_ctl, robot_bus, fsm)
    rsp.start()

    from ..skills.skill_server import SkillServer
    skill_server = SkillServer(
        combo_ctl=combo_ctl,
        safety=safety,
        tts=None,
        vision=None,
        camera_hub=None,
        scene_bus=scene_bus,
        fsm=fsm,
        sim=True,
    )

    print("\n=== g1_brain skill_debug ===")
    for k, (tool, a) in KEY_TO_SKILL.items():
        print(f"  {k}  {tool}({a})")
    print("  q  quit\n")

    loop = asyncio.get_event_loop()
    stop = asyncio.Event()

    def _reader():
        try:
            for line in sys.stdin:
                key = line.strip().lower()
                if not key:
                    continue
                if key == "q":
                    loop.call_soon_threadsafe(stop.set)
                    return
                if key in KEY_TO_SKILL:
                    tool, a = KEY_TO_SKILL[key]
                    fut = asyncio.run_coroutine_threadsafe(
                        skill_server.execute(tool, a), loop
                    )
                    try:
                        result = fut.result(timeout=10.0)
                    except Exception as e:  # noqa: BLE001
                        result = {"ok": False, "reason": f"exception: {e}"}
                    print(f"  -> {result}")
                else:
                    print(f"  unknown key {key!r}")
        except Exception:  # noqa: BLE001
            log.exception("reader thread crashed")
            loop.call_soon_threadsafe(stop.set)

    threading.Thread(target=_reader, name="skill-debug-reader", daemon=True).start()

    try:
        await stop.wait()
    finally:
        print("\nstopping ...")
        try:
            await skill_server.execute("stop", {})
        except Exception:  # noqa: BLE001
            log.exception("final stop failed")
        rsp.stop()
        try:
            combo_ctl.stop_and_settle()
        except Exception:  # noqa: BLE001
            log.exception("stop_and_settle failed")
    return 0


async def _async_true():
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="g1_brain skill keyboard debug")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    _ensure_sibling_repos_on_path()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
