"""Background asyncio task that watches the SceneStateBus for sustained
mirrorable user gestures and tells the brain when one fires.

We use an ``asyncio.Task`` (not a thread) because the only side-effect is
``await brain_agent.inject_perception_event(...)`` which is async-only. The
bus snapshot itself is sync + thread-safe, so polling from asyncio is fine.

Debounce contract (verified by ``tests/test_mock_imitation.py``):

- Wait until the *same* mirrorable gesture has been observed at confidence
  >= ``cfg.auto_suggest_high_conf`` continuously for >= ``cfg.auto_suggest_persist_s``
  seconds.
- After firing, do not fire again for ``COOLDOWN_S`` seconds (default 5 s)
  *for any* mirrorable gesture — this keeps the LLM from getting spammed if
  the user holds a wave for a long time, or rapidly cycles through gestures.
- A drop in confidence (or a switch to a different gesture) resets the
  per-gesture rising-edge timer for the gesture that lost confidence; other
  gestures' timers are not reset by an unrelated gesture appearing.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from .gesture_to_skill import MIRRORABLE_GESTURES

log = logging.getLogger(__name__)


COOLDOWN_S = 5.0
POLL_INTERVAL_S = 0.2


@dataclass
class AutoTriggerConfig:
    """Subset of the YAML ``mock_imitation`` block that we care about."""
    auto_suggest_high_conf: float = 0.8
    auto_suggest_persist_s: float = 1.0


class _BrainProto(Protocol):
    async def inject_perception_event(self, event_text: str) -> None: ...


class GestureAutoTrigger:
    """Polls a SceneStateBus and notifies a brain agent on sustained gestures."""

    def __init__(
        self,
        scene_bus: Any,                # SceneStateBus duck-type (snapshot())
        brain_agent: _BrainProto,
        cfg: AutoTriggerConfig,
        *,
        cooldown_s: float = COOLDOWN_S,
        poll_interval_s: float = POLL_INTERVAL_S,
        time_fn=time.monotonic,        # injectable for tests
    ) -> None:
        self._bus = scene_bus
        self._brain = brain_agent
        self._cfg = cfg
        self._cooldown_s = float(cooldown_s)
        self._poll_interval_s = float(poll_interval_s)
        self._now = time_fn

        # Per-gesture monotonic time at which it first became high-confidence
        # (None = currently below threshold or absent).
        self._rise_t: Dict[str, Optional[float]] = {g: None for g in MIRRORABLE_GESTURES}
        # Last fire time across ALL gestures (cooldown is global, not per-gesture).
        self._last_fire_t: float = -1e9
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> asyncio.Task:
        if self._task is not None and not self._task.done():
            return self._task
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="gesture-auto-trigger")
        return self._task

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    # ----------------------------------------------------------------- internals

    async def _run(self) -> None:
        try:
            while not self._stopping.is_set():
                try:
                    await self._tick()
                except Exception:  # noqa: BLE001
                    log.exception("GestureAutoTrigger tick raised")
                await asyncio.sleep(self._poll_interval_s)
        except asyncio.CancelledError:
            return

    async def _tick(self) -> None:
        scene = self._bus.snapshot()
        pose = getattr(scene, "user_pose", None)
        now = self._now()

        # Identify which gesture (if any) currently meets the high-confidence
        # bar. We only consider mirrorable ones.
        active_g: Optional[str] = None
        if pose is not None:
            g = getattr(pose, "gesture", None)
            conf = float(getattr(pose, "gesture_confidence", 0.0) or 0.0)
            if g in MIRRORABLE_GESTURES and conf >= self._cfg.auto_suggest_high_conf:
                active_g = g

        # Reset rising-edge timers for any mirrorable gesture that is NOT
        # currently active. The active one keeps / acquires its timer.
        for g in MIRRORABLE_GESTURES:
            if g != active_g:
                self._rise_t[g] = None
        if active_g is not None and self._rise_t[active_g] is None:
            self._rise_t[active_g] = now

        # Decide whether to fire.
        if active_g is None:
            return
        held_s = now - (self._rise_t[active_g] or now)
        if held_s < self._cfg.auto_suggest_persist_s:
            return
        if (now - self._last_fire_t) < self._cooldown_s:
            return

        await self._fire(active_g)
        self._last_fire_t = now
        # Force the gesture to satisfy persist_s afresh next time before
        # firing again — important when cooldown elapses while the user is
        # still holding the same pose.
        self._rise_t[active_g] = now

    async def _fire(self, gesture: str) -> None:
        text = (
            f"User showed gesture: {gesture}. "
            f"You may mirror it via mock_imitate."
        )
        log.info("auto-trigger fire: %s", gesture)
        await self._brain.inject_perception_event(text)


__all__ = ["GestureAutoTrigger", "AutoTriggerConfig", "COOLDOWN_S"]
