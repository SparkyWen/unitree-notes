"""SafetySupervisor exerciser.

Builds a SafetySupervisor with mocked SceneStateBus / RobotStateBus / FSM /
EstopClient, runs a list of scenarios (inline default or loaded from a JSON
file via argv), and prints expected vs actual reject reasons.

Useful for A/B-ing safety config tweaks without booting the agent.

Each scenario is a dict like:
  {
    "name": "walk-blocked-by-obstacle",
    "tool": "walk",
    "args": {"vx": 0.2, "duration_s": 0.5},
    "expect_ok": false,
    "expect_reason_contains": "obstacle",
    "scene": {
        "ground": {"clear_path": true, "nearest_obstacle_m": 0.4,
                   "nearest_person_m": 5.0,
                   "floor_visible_ratio": 1.0, "surface_tilt_deg": 0.0}
    },
    "robot": {"rl_policy_active": true, "gravity_proj_z": -0.99,
              "lowstate_age_s": 0.05},
    "fsm": "ENGAGED",
    "estop": false,
    "run_mode": "active"
  }
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


log = logging.getLogger("g1_brain.safety_debug")


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CONFIG = REPO_ROOT / "g1_brain" / "configs" / "g1_brain.yaml"


# --- default scenarios -------------------------------------------------------

DEFAULT_SCENARIOS: List[Dict[str, Any]] = [
    {
        "name": "say-allowed",
        "tool": "say",
        "args": {"text": "hello"},
        "expect_ok": True,
        "fsm": "STANDING",
    },
    {
        "name": "walk-rejected-in-standing",
        "tool": "walk",
        "args": {"vx": 0.2, "duration_s": 0.5},
        "expect_ok": False,
        "expect_reason_contains": "fsm",
        "fsm": "STANDING",
        "run_mode": "active",
    },
    {
        "name": "walk-blocked-by-obstacle",
        "tool": "walk",
        "args": {"vx": 0.2, "duration_s": 0.5},
        "expect_ok": False,
        "expect_reason_contains": "obstacle",
        "fsm": "ENGAGED",
        "run_mode": "active",
        "scene": {"ground": {"clear_path": True, "nearest_obstacle_m": 0.3,
                              "nearest_person_m": 5.0,
                              "floor_visible_ratio": 1.0, "surface_tilt_deg": 0.0}},
    },
    {
        "name": "walk-ok-active",
        "tool": "walk",
        "args": {"vx": 0.2, "duration_s": 0.5},
        "expect_ok": True,
        "fsm": "ENGAGED",
        "run_mode": "active",
        "scene": {"ground": {"clear_path": True, "nearest_obstacle_m": 1.5,
                              "nearest_person_m": 5.0,
                              "floor_visible_ratio": 1.0, "surface_tilt_deg": 0.0}},
    },
    {
        "name": "estop-blocks-walk",
        "tool": "walk",
        "args": {"vx": 0.2, "duration_s": 0.5},
        "expect_ok": False,
        "expect_reason_contains": "estop",
        "fsm": "ENGAGED",
        "estop": True,
        "run_mode": "active",
        "scene": {"ground": {"clear_path": True, "nearest_obstacle_m": 1.5,
                              "nearest_person_m": 5.0,
                              "floor_visible_ratio": 1.0, "surface_tilt_deg": 0.0}},
    },
    {
        "name": "tipping-triggers-emergency",
        "tool": "walk",
        "args": {"vx": 0.1, "duration_s": 0.5},
        "expect_ok": False,
        "expect_reason_contains": "tipping",
        "fsm": "ENGAGED",
        "run_mode": "active",
        "robot": {"rl_policy_active": True, "gravity_proj_z": -0.5,
                   "lowstate_age_s": 0.05},
    },
]


def _build_supervisor(scenario: Dict[str, Any], cfg_path: Path):
    """Construct a fresh SafetySupervisor + buses + fsm + estop for one scenario."""
    import yaml

    from ..safety.estop_client import EstopClient
    from ..safety.state_machine import RobotFsm, RobotFsmState
    from ..safety.supervisor import SafetySupervisor
    from ..scene_state.fusion import RobotStateBus, SceneStateBus
    from ..scene_state.types import GroundConstraint, RobotState

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}

    scene_bus = SceneStateBus()
    robot_bus = RobotStateBus()

    # Scene state seeding
    scene = scenario.get("scene") or {}
    if "ground" in scene:
        g = scene["ground"]
        scene_bus.update_ground(GroundConstraint(
            clear_path=bool(g.get("clear_path", True)),
            nearest_obstacle_m=float(g.get("nearest_obstacle_m", math.inf)),
            nearest_person_m=float(g.get("nearest_person_m", math.inf)),
            floor_visible_ratio=float(g.get("floor_visible_ratio", 1.0)),
            surface_tilt_deg=float(g.get("surface_tilt_deg", 0.0)),
        ))
    # Pretend cameras have been alive for 0.1s so head_frame watchdog is happy.
    import time
    now = time.monotonic()
    scene_bus.update_usb_frame(ts=now - 0.1, resolution=(640, 480))
    scene_bus.update_head_frame(ts=now - 0.1, resolution=(640, 480))

    # Robot state seeding
    rs_in = scenario.get("robot") or {}
    rs = RobotState(
        standing=True,
        gravity_proj_z=float(rs_in.get("gravity_proj_z", -0.99)),
        base_ang_vel_xyz=(0.0, 0.0, 0.0),
        rl_policy_active=bool(rs_in.get("rl_policy_active", True)),
        last_lowstate_age_s=float(rs_in.get("lowstate_age_s", 0.05)),
    )
    robot_bus.update(rs)

    # FSM
    fsm = RobotFsm()
    target_state = RobotFsmState[scenario.get("fsm", "ENGAGED")]
    if target_state != RobotFsmState.BOOT:
        # walk through legal transitions to reach it
        if target_state == RobotFsmState.STANDING:
            fsm.transition(RobotFsmState.STANDING, "init")
        elif target_state == RobotFsmState.ENGAGED:
            fsm.transition(RobotFsmState.STANDING, "init")
            fsm.transition(RobotFsmState.ENGAGED, "init")
        elif target_state == RobotFsmState.ACTING:
            fsm.transition(RobotFsmState.STANDING, "init")
            fsm.transition(RobotFsmState.ENGAGED, "init")
            fsm.transition(RobotFsmState.ACTING, "init")
        elif target_state == RobotFsmState.EMERGENCY_STOP:
            fsm.transition(RobotFsmState.EMERGENCY_STOP, "init")

    # E-stop in a temp directory so scenarios don't clobber the real one
    tmp = Path(tempfile.gettempdir()) / f"g1_brain_estop_dbg_{id(scenario):x}"
    estop = EstopClient(tmp)
    if scenario.get("estop"):
        estop.engage(scenario.get("estop_reason", "scenario"))
    else:
        estop.release()

    sup = SafetySupervisor(
        cfg=cfg,
        scene_bus=scene_bus,
        robot_bus=robot_bus,
        fsm=fsm,
        estop=estop,
        run_mode=scenario.get("run_mode", "active"),
        confirm_fn=lambda *_a, **_k: _async_true(),
    )
    return sup


async def _async_true():
    return True


async def _run_scenario(s: Dict[str, Any], cfg_path: Path) -> Dict[str, Any]:
    sup = _build_supervisor(s, cfg_path)
    ok, reason, sanitized = await sup.validate(s["tool"], s.get("args") or {})
    expected_ok = bool(s.get("expect_ok", True))
    expect_substr = s.get("expect_reason_contains")
    matched = ok == expected_ok
    if expect_substr is not None and not ok:
        matched = matched and (expect_substr.lower() in reason.lower())
    return {
        "name": s.get("name", "<unnamed>"),
        "ok": ok,
        "reason": reason,
        "sanitized": sanitized,
        "expected_ok": expected_ok,
        "expected_reason_contains": expect_substr,
        "matched": matched,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="g1_brain safety scenario runner")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--scenarios", type=Path, default=None,
                   help="JSON file containing a list of scenarios")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.scenarios:
        with open(args.scenarios) as f:
            scenarios = json.load(f)
    else:
        scenarios = DEFAULT_SCENARIOS

    async def _go():
        results = []
        for s in scenarios:
            try:
                r = await _run_scenario(s, args.config)
            except Exception as e:  # noqa: BLE001
                log.exception("scenario %r failed", s.get("name"))
                r = {"name": s.get("name", "<?>"), "matched": False,
                     "reason": f"exception: {e}"}
            results.append(r)
        return results

    results = asyncio.run(_go())

    n_pass = sum(1 for r in results if r.get("matched"))
    print(f"\n=== safety_debug: {n_pass}/{len(results)} matched expected ===")
    for r in results:
        flag = "PASS" if r.get("matched") else "FAIL"
        print(f"  [{flag}] {r['name']}: ok={r.get('ok')} reason={r.get('reason')!r}")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
