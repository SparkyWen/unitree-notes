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
