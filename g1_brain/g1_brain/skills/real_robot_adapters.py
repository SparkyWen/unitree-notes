"""Real-robot skill backend stub (v1).

The shape is a SimSkillBackend twin so `agent_main.py` can branch on
``cfg.mode == "real"`` without import-time conditionals. Every method
raises ``NotImplementedError`` for now — the actual wiring against
LocoClient / G1ArmActionClient / AudioClient.TtsMaker is future work.

This module deliberately does NOT import any real-robot SDK at the top
level so it stays importable in CI / sim-only environments.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

log = logging.getLogger(__name__)


_NOT_WIRED = "real robot not yet wired (v1 stub)"


class RealRobotSkillBackend:
    """Mirror of the SkillServer-internal sim backend, but unimplemented.

    Methods names + arg shapes match what SkillServer's ``_skill_*`` methods
    expect, so swap-in is a single attribute reassignment.
    """

    def __init__(self, *, loco_client: Any = None,
                 arm_action_client: Any = None,
                 audio_client: Any = None) -> None:
        self.loco = loco_client
        self.arm_action = arm_action_client
        self.audio = audio_client
        log.info("RealRobotSkillBackend constructed (stub; %s)", _NOT_WIRED)

    # ----- L2 motion primitives -------------------------------------------
    async def walk(self, vx: float, vy: float, wz: float, duration_s: float) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_WIRED)

    async def turn(self, yaw_deg: float) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_WIRED)

    async def gesture(self, name: str) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_WIRED)

    async def static_pose(self, name: str) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_WIRED)

    async def stop(self) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_WIRED)

    async def release_arms(self) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_WIRED)

    # ----- Real-robot-only L1/L2 ------------------------------------------
    async def loco_high(self, action: str) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_WIRED)

    async def arm_action_high(self, action_id: int) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_WIRED)

    async def audio_tts_robot(self, text: str) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_WIRED)


__all__ = ["RealRobotSkillBackend"]
