"""Unit tests for SkillBackend with a fake ComboController."""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.skills import GESTURE_KEY_MAP, SkillBackend


class FakeArmAction:
    def __init__(self, key, name):
        self.key = key
        self.name = name
        self.keyframes = [(1.0, [0.0] * 14)]


@dataclass
class FakeCtl:
    cmds: List[tuple] = field(default_factory=list)
    pushed: List[List] = field(default_factory=list)
    released: int = 0
    settled: int = 0
    first_state_received: bool = True
    last_state_time: float = 0.0
    policy_active: bool = True

    def __post_init__(self):
        self.last_state_time = time.monotonic()

    def set_command(self, vx, vy, wz):
        self.cmds.append((vx, vy, wz))

    def push_arm_action(self, kfs):
        self.pushed.append(list(kfs))

    def release_arms(self):
        self.released += 1

    def stop_and_settle(self):
        self.settled += 1


def _backend():
    ctl = FakeCtl()
    actions = [FakeArmAction(k, n) for n, k in GESTURE_KEY_MAP.items()]
    return SkillBackend(ctl, actions), ctl


def _run(coro):
    return asyncio.run(coro)


def test_walk_sets_then_zeroes_command():
    sk, ctl = _backend()
    out = _run(sk.walk(0.2, 0.0, 0.0, 0.05))
    assert out["ok"] is True
    assert ctl.cmds[0] == (0.2, 0.0, 0.0)
    assert ctl.cmds[-1] == (0.0, 0.0, 0.0)


def test_walk_zeroes_even_on_cancel():
    sk, ctl = _backend()

    async def _cancel():
        task = asyncio.create_task(sk.walk(0.2, 0.0, 0.0, 5.0))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    _run(_cancel())
    assert ctl.cmds[0] == (0.2, 0.0, 0.0)
    assert ctl.cmds[-1] == (0.0, 0.0, 0.0)


def test_gesture_known():
    sk, ctl = _backend()
    out = _run(sk.gesture("wave_right"))
    assert out["ok"] is True
    assert len(ctl.pushed) == 1


def test_gesture_unknown():
    sk, _ = _backend()
    out = _run(sk.gesture("moonwalk"))
    assert out["ok"] is False
    assert "unknown" in out["reason"]


def test_stop_zeroes_and_releases():
    sk, ctl = _backend()
    _run(sk.stop())
    assert ctl.cmds[-1] == (0.0, 0.0, 0.0)
    assert ctl.released == 1


def test_release_arms():
    sk, ctl = _backend()
    _run(sk.release_arms())
    assert ctl.released == 1


def test_lowstate_age_when_recent():
    sk, ctl = _backend()
    ctl.last_state_time = time.monotonic()
    age = sk.lowstate_age_seconds()
    assert age < 0.1


def test_lowstate_age_when_no_state():
    sk, ctl = _backend()
    ctl.first_state_received = False
    assert sk.lowstate_age_seconds() == float("inf")
