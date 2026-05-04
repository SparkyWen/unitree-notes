"""SkillBackend: thin async wrapper around the existing ComboController.

We import `g1_sim_demo/g1_sim_rl_combo.py` unmodified. ComboController already
runs its own 50 Hz RecurrentThread; all public methods we use here
(`set_command`, `push_arm_action`, `release_arms`, `stop_and_settle`) are
thread-safe.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger(__name__)


# Map symbolic gesture names exposed to the AI -> the legacy keyboard keys
# in g1_sim_rl_combo.build_arm_actions().
GESTURE_KEY_MAP: Dict[str, str] = {
    "wave_right": "1",
    "wave_left": "2",
    "hands_up": "3",
    "t_pose": "4",
    "salute": "5",
    "clap": "6",
    "guard": "7",
    "punch_combo": "8",
}


def _ensure_g1_sim_demo_on_path():
    p = Path.home() / "unitree" / "unitree-notes" / "g1_sim_demo"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class SkillBackend:
    """Bridges Realtime tool calls to the ComboController in MuJoCo sim."""

    def __init__(self, ctl, arm_actions):
        # ctl: ComboController; arm_actions: list[ArmAction] from build_arm_actions().
        self._ctl = ctl
        self._actions_by_key = {a.key: a for a in arm_actions}

    # ----- watchdog hooks -----------------------------------------------------
    def lowstate_age_seconds(self) -> float:
        if not getattr(self._ctl, "first_state_received", False):
            return float("inf")
        return time.monotonic() - self._ctl.last_state_time

    # ----- skills -------------------------------------------------------------
    async def walk(self, vx: float, vy: float, wz: float, duration_s: float) -> Dict:
        log.info("walk vx=%+0.2f vy=%+0.2f wz=%+0.2f dur=%.2f", vx, vy, wz, duration_s)
        self._ctl.set_command(vx, vy, wz)
        try:
            await asyncio.sleep(duration_s)
        finally:
            self._ctl.set_command(0.0, 0.0, 0.0)
        return {"ok": True, "skill": "walk"}

    async def gesture(self, name: str) -> Dict:
        key = GESTURE_KEY_MAP.get(name)
        if key is None or key not in self._actions_by_key:
            return {"ok": False, "reason": f"unknown gesture: {name!r}"}
        action = self._actions_by_key[key]
        log.info("gesture %s (%s)", name, action.name)
        self._ctl.push_arm_action(action.keyframes)
        # We don't await the gesture's full duration; the RL controller plays it
        # asynchronously and releases arms back to the policy when done. The
        # Realtime model can issue stop / release_arms if it wants to interrupt.
        return {"ok": True, "skill": "gesture", "name": name}

    async def stop(self) -> Dict:
        log.info("stop")
        self._ctl.set_command(0.0, 0.0, 0.0)
        self._ctl.release_arms()
        return {"ok": True, "skill": "stop"}

    async def release_arms(self) -> Dict:
        log.info("release_arms")
        self._ctl.release_arms()
        return {"ok": True, "skill": "release_arms"}

    # ----- lifecycle ----------------------------------------------------------
    def shutdown(self):
        try:
            self._ctl.stop_and_settle()
        except Exception as e:
            log.warning("error during stop_and_settle: %s", e)


def build_skill_backend() -> SkillBackend:
    """Initialize DDS, build ComboController, wait for first lowstate, return SkillBackend.

    Caller is responsible for ChannelFactoryInitialize before calling this.
    """
    _ensure_g1_sim_demo_on_path()
    import g1_sim_rl_combo as combo

    cfg = combo.DeployCfg(combo.POLICY_YAML)
    policy = combo.Policy(combo.POLICY_ONNX)
    ctl = combo.ComboController(cfg, policy)
    actions = combo.build_arm_actions(ctl.arm_rest, ctl.arm_scale)
    ctl.init_dds()
    ctl.start()
    return SkillBackend(ctl, actions)
