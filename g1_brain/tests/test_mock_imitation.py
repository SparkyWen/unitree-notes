"""Tests for the mock_imitation package: pure mapping + auto-trigger debounce."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional
from unittest.mock import AsyncMock

import pytest

from g1_brain.mock_imitation import (
    MIRRORABLE_GESTURES,
    map_user_gesture_to_skill_call,
    build_acknowledgment_phrase,
    GestureAutoTrigger,
    AutoTriggerConfig,
)
from g1_brain.scene_state.types import GestureLabel


# --------------------------------------------------------------- map / phrases

@pytest.mark.parametrize("g", list(MIRRORABLE_GESTURES))
def test_map_returns_correct_skill_call_for_mirrorable(g):
    out = map_user_gesture_to_skill_call(g)
    assert out == {"tool": "gesture", "args": {"name": g}}


@pytest.mark.parametrize("g", [
    GestureLabel.POINT_LEFT,
    GestureLabel.POINT_RIGHT,
    GestureLabel.STOP_PALM,
    GestureLabel.CROSSED_ARMS,
    "unknown_gesture",
    "",
])
def test_map_returns_none_for_non_mirrorable(g):
    assert map_user_gesture_to_skill_call(g) is None


@pytest.mark.parametrize("g", list(MIRRORABLE_GESTURES))
def test_ack_phrase_zh_mentions_gesture_or_synonym(g):
    """Either the gesture name verbatim or a recognizable Chinese synonym."""
    phrase = build_acknowledgment_phrase(g, lang="zh")
    assert phrase  # non-empty
    # Allow either the literal name (e.g. "wave_right") or a known synonym
    # in the canned table.
    synonyms = {
        GestureLabel.WAVE_RIGHT: ["挥手", "wave_right"],
        GestureLabel.WAVE_LEFT: ["挥手", "wave_left"],
        GestureLabel.HANDS_UP: ["举", "hands_up"],
        GestureLabel.T_POSE: ["T-pose", "t_pose", "T pose"],
    }[g]
    assert any(s in phrase for s in synonyms), (
        f"phrase {phrase!r} for {g} mentions none of {synonyms}"
    )


@pytest.mark.parametrize("g", list(MIRRORABLE_GESTURES))
def test_ack_phrase_en_mentions_gesture_concept(g):
    phrase = build_acknowledgment_phrase(g, lang="en")
    assert phrase
    # English ack always references the activity.
    keywords_per_g = {
        GestureLabel.WAVE_RIGHT: ["wave"],
        GestureLabel.WAVE_LEFT: ["wave"],
        GestureLabel.HANDS_UP: ["hand"],  # "hands up" / "raise mine"
        GestureLabel.T_POSE: ["T-pose", "t_pose"],
    }[g]
    low = phrase.lower()
    assert any(k.lower() in low for k in keywords_per_g)


def test_ack_phrase_falls_back_for_unknown():
    """Unknown gestures still produce a string mentioning the gesture name."""
    phrase = build_acknowledgment_phrase("mystery_pose", lang="en")
    assert "mystery_pose" in phrase
    phrase_zh = build_acknowledgment_phrase("mystery_pose", lang="zh")
    assert "mystery_pose" in phrase_zh


# --------------------------------------------------------------- auto trigger

@dataclass
class _FakePose:
    gesture: Optional[str]
    gesture_confidence: float


@dataclass
class _FakeScene:
    user_pose: Optional[_FakePose]


class _ScriptedBus:
    """SceneStateBus stub: returns scenes from a script in order; the last
    scene is repeated forever once the script is exhausted."""

    def __init__(self, script: List[_FakeScene]) -> None:
        self.script = list(script)
        self.idx = 0

    def snapshot(self) -> _FakeScene:
        if self.idx < len(self.script):
            s = self.script[self.idx]
            self.idx += 1
            return s
        return self.script[-1] if self.script else _FakeScene(None)


class _FakeClock:
    """Monotonic clock the test advances manually."""
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.mark.asyncio
async def test_auto_trigger_fires_once_across_persist_and_cooldown_window():
    """Feed a long high-conf wave_right and assert exactly ONE event fires
    across the persist_s + cooldown window."""
    clock = _FakeClock()

    # Script: 30 ticks of high-conf wave_right (covers >> persist_s + cooldown).
    high = _FakeScene(_FakePose(gesture=GestureLabel.WAVE_RIGHT, gesture_confidence=0.95))
    script = [high] * 60
    bus = _ScriptedBus(script)

    brain = AsyncMock()
    brain.inject_perception_event = AsyncMock()

    cfg = AutoTriggerConfig(auto_suggest_high_conf=0.8, auto_suggest_persist_s=1.0)
    trig = GestureAutoTrigger(
        bus, brain, cfg,
        cooldown_s=5.0, poll_interval_s=0.2,
        time_fn=clock,
    )

    # Manually drive _tick (avoid real-time sleeps); advance the fake clock by
    # 0.2 s between ticks. 30 ticks = 6.0 s simulated; persist 1.0 s + cooldown
    # 5.0 s = 6.0 s window, so we should see exactly ONE fire.
    for _ in range(30):
        await trig._tick()
        clock.advance(0.2)

    assert brain.inject_perception_event.await_count == 1
    args, _ = brain.inject_perception_event.await_args
    assert "wave_right" in args[0]
    assert "mock_imitate" in args[0]


@pytest.mark.asyncio
async def test_auto_trigger_does_not_fire_below_persist_s():
    """High conf for only 0.6 s (< persist_s=1.0) must not fire."""
    clock = _FakeClock()
    high = _FakeScene(_FakePose(GestureLabel.WAVE_RIGHT, 0.9))
    bus = _ScriptedBus([high] * 4)  # 4 ticks * 0.2 s = 0.6 s only

    brain = AsyncMock()
    cfg = AutoTriggerConfig(auto_suggest_high_conf=0.8, auto_suggest_persist_s=1.0)
    trig = GestureAutoTrigger(
        bus, brain, cfg, cooldown_s=5.0, poll_interval_s=0.2, time_fn=clock,
    )

    for _ in range(4):
        await trig._tick()
        clock.advance(0.2)

    assert brain.inject_perception_event.await_count == 0


@pytest.mark.asyncio
async def test_auto_trigger_resets_on_confidence_drop():
    """High → low → high pattern must not fire if neither high segment is
    long enough on its own."""
    clock = _FakeClock()
    high = _FakeScene(_FakePose(GestureLabel.WAVE_RIGHT, 0.9))
    low = _FakeScene(_FakePose(GestureLabel.WAVE_RIGHT, 0.4))   # below 0.8

    # 3 ticks high (0.6s), 3 ticks low (resets), 3 ticks high (0.6s) — never
    # crosses persist_s in a single segment.
    script = [high, high, high, low, low, low, high, high, high]
    bus = _ScriptedBus(script)

    brain = AsyncMock()
    cfg = AutoTriggerConfig(auto_suggest_high_conf=0.8, auto_suggest_persist_s=1.0)
    trig = GestureAutoTrigger(
        bus, brain, cfg, cooldown_s=5.0, poll_interval_s=0.2, time_fn=clock,
    )

    for _ in range(len(script)):
        await trig._tick()
        clock.advance(0.2)

    assert brain.inject_perception_event.await_count == 0


@pytest.mark.asyncio
async def test_auto_trigger_ignores_non_mirrorable():
    """A high-conf 'point_left' (non-mirrorable) must never fire."""
    clock = _FakeClock()
    high = _FakeScene(_FakePose(GestureLabel.POINT_LEFT, 0.99))
    bus = _ScriptedBus([high] * 30)

    brain = AsyncMock()
    cfg = AutoTriggerConfig(auto_suggest_high_conf=0.8, auto_suggest_persist_s=1.0)
    trig = GestureAutoTrigger(
        bus, brain, cfg, cooldown_s=5.0, poll_interval_s=0.2, time_fn=clock,
    )

    for _ in range(30):
        await trig._tick()
        clock.advance(0.2)

    assert brain.inject_perception_event.await_count == 0


@pytest.mark.asyncio
async def test_auto_trigger_start_stop_lifecycle():
    """start() then stop() shouldn't raise, and the task should be gone."""
    bus = _ScriptedBus([_FakeScene(None)])
    brain = AsyncMock()
    cfg = AutoTriggerConfig()
    trig = GestureAutoTrigger(bus, brain, cfg, poll_interval_s=0.01)

    task = trig.start()
    assert task is not None and not task.done()
    await asyncio.sleep(0.05)  # let it tick at least once
    await trig.stop()
    # After stop, task is cleared
    assert trig._task is None
