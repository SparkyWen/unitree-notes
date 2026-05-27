"""Smoke tests for the apps/ entry points.

We don't actually run the agent — we only want to know:
  - parse_args() accepts the documented flags and gives sensible defaults
  - agent_main imports cleanly when the heavy deps are present (skipped if not)
  - ${HOME} substitution works
"""
from __future__ import annotations

import importlib
import os
import sys
import textwrap
from pathlib import Path

import pytest


def _have(mod: str) -> bool:
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def test_parse_args_defaults():
    from g1_brain.apps import agent_main

    args = agent_main.parse_args(
        ["--no-realtime", "--no-skills", "--no-perception", "--no-wakeword"]
    )
    assert args.no_realtime is True
    assert args.no_skills is True
    assert args.no_perception is True
    assert args.no_wakeword is True
    assert args.vision_only is False
    assert args.verbose is False
    # mode left as None means "fall through to config.run_mode"
    assert args.mode is None
    # Default config should at least exist on disk for typical layouts.
    assert isinstance(args.config, Path)


def test_parse_args_mode_and_vision_only():
    from g1_brain.apps import agent_main

    args = agent_main.parse_args(["--mode", "active", "--vision-only", "-v"])
    assert args.mode == "active"
    assert args.vision_only is True
    assert args.verbose is True


def test_parse_args_rejects_bad_mode():
    from g1_brain.apps import agent_main

    with pytest.raises(SystemExit):
        agent_main.parse_args(["--mode", "bogus"])


def test_expand_env_substitutes_home(tmp_path, monkeypatch):
    from g1_brain.apps.agent_main import _expand_env_in_obj, _load_config

    cfg = {
        "mjcf_path": "${HOME}/foo/bar.xml",
        "logging": {"log_dir": "${HOME}/logs"},
        "list": ["${HOME}/x", "static"],
    }
    out = _expand_env_in_obj(cfg)
    home = os.path.expanduser("~")
    assert out["mjcf_path"].startswith(home)
    assert out["logging"]["log_dir"].startswith(home)
    assert out["list"][0].startswith(home)
    assert out["list"][1] == "static"

    # Round-trip through _load_config too.
    cfg_path = tmp_path / "test.yaml"
    cfg_path.write_text(textwrap.dedent("""
        a: "${HOME}/aaa"
        nested:
          b: "${HOME}/bbb"
    """).strip(), encoding="utf-8")
    loaded = _load_config(cfg_path)
    assert loaded["a"].startswith(home)
    assert loaded["nested"]["b"].startswith(home)


@pytest.mark.skipif(
    not (_have("yaml")),
    reason="pyyaml is required to import agent_main meaningfully",
)
def test_agent_main_imports():
    """Importing agent_main shouldn't fail even when the optional heavy deps
    (mediapipe, ultralytics, mujoco, transformers, websockets) are missing —
    those imports are deferred / try/except'd."""
    sys.modules.pop("g1_brain.apps.agent_main", None)
    mod = importlib.import_module("g1_brain.apps.agent_main")
    # Public entry points must be present.
    assert hasattr(mod, "parse_args")
    assert hasattr(mod, "main")
    assert callable(mod.parse_args)
    assert callable(mod.main)


def test_perception_debug_imports():
    sys.modules.pop("g1_brain.apps.perception_debug", None)
    mod = importlib.import_module("g1_brain.apps.perception_debug")
    assert hasattr(mod, "main")


def test_safety_debug_imports_and_default_scenarios():
    sys.modules.pop("g1_brain.apps.safety_debug", None)
    mod = importlib.import_module("g1_brain.apps.safety_debug")
    assert hasattr(mod, "main")
    assert hasattr(mod, "DEFAULT_SCENARIOS")
    assert isinstance(mod.DEFAULT_SCENARIOS, list)
    assert all("name" in s and "tool" in s for s in mod.DEFAULT_SCENARIOS)


def test_estop_test_imports():
    sys.modules.pop("g1_brain.apps.estop_test", None)
    mod = importlib.import_module("g1_brain.apps.estop_test")
    assert hasattr(mod, "main")


def test_skill_debug_imports():
    sys.modules.pop("g1_brain.apps.skill_debug", None)
    mod = importlib.import_module("g1_brain.apps.skill_debug")
    assert hasattr(mod, "main")
    assert hasattr(mod, "KEY_TO_SKILL")
    assert "1" in mod.KEY_TO_SKILL and "q" not in mod.KEY_TO_SKILL


def test_start_perception_bg_does_not_block_event_loop():
    """Regression: perception.start() must run OFF the event-loop thread.

    Loading YOLO→CUDA / MediaPipe / a head-cam MjModel synchronously on the
    event loop froze audio/VAD and the wake-word path for ~49 s at boot, so
    "Hi Sparky" was silently dropped until it finished. _start_perception_bg
    runs start() in a worker thread; a concurrent coroutine must keep making
    progress while perception "loads".
    """
    import asyncio
    import time

    from g1_brain.apps import agent_main

    load_s = 0.4

    class _SlowPerception:
        def __init__(self):
            self.started = False

        def start(self):
            # time.sleep releases the GIL — stands in for a blocking model load.
            time.sleep(load_s)
            self.started = True

    async def _drive():
        perc = _SlowPerception()
        start_task = asyncio.create_task(agent_main._start_perception_bg(perc))
        ticks = 0
        t0 = time.monotonic()
        while not start_task.done() and time.monotonic() - t0 < 2.0:
            await asyncio.sleep(0.02)
            ticks += 1
        await start_task
        return perc.started, ticks

    started, ticks = asyncio.run(_drive())
    assert started is True
    # If start() had run on the loop, the ~0.02 s ticker would have been frozen
    # for the whole load window and ticked only once or twice. In a worker
    # thread it keeps cycling, so we see many ticks across load_s.
    assert ticks >= 5, f"event loop appears blocked during perception load (ticks={ticks})"


def test_drain_pending_tasks_cancels_stragglers():
    """Regression: _drain_pending_tasks must cancel + await tasks still pending
    at teardown, so the loop doesn't GC them with "Task was destroyed but it is
    pending!".
    """
    import asyncio

    from g1_brain.apps import agent_main

    loop = asyncio.new_event_loop()
    try:
        async def _forever():
            while True:
                await asyncio.sleep(10)

        task = loop.create_task(_forever())
        loop.run_until_complete(asyncio.sleep(0))  # let it start
        assert not task.done()

        agent_main._drain_pending_tasks(loop)

        assert task.done()
        assert task.cancelled()
    finally:
        loop.close()


def test_drain_pending_tasks_noop_when_nothing_pending():
    import asyncio

    from g1_brain.apps import agent_main

    loop = asyncio.new_event_loop()
    try:
        agent_main._drain_pending_tasks(loop)  # must not raise
    finally:
        loop.close()
