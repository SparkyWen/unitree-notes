"""Shared pytest fixtures.

Most subsystems can be tested without DDS / OpenAI / cameras by stubbing
the boundary. We keep the stubs in a single place so tests stay terse.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


# Make sure the package is importable when tests are run from the repo root
# without installing.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


@pytest.fixture
def stub_unitree_sdk(monkeypatch):
    """Replace unitree_sdk2py.* with no-op modules so tests don't need DDS."""
    pkg = types.ModuleType("unitree_sdk2py")
    core = types.ModuleType("unitree_sdk2py.core")
    channel = types.ModuleType("unitree_sdk2py.core.channel")

    class _Pub:
        def __init__(self, *_a, **_k): pass
        def Init(self): pass
        def Write(self, *_a, **_k): pass

    class _Sub:
        def __init__(self, *_a, **_k): pass
        def Init(self, *_a, **_k): pass

    def _init(*_a, **_k):
        return None

    channel.ChannelPublisher = _Pub
    channel.ChannelSubscriber = _Sub
    channel.ChannelFactoryInitialize = _init

    monkeypatch.setitem(sys.modules, "unitree_sdk2py", pkg)
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.core", core)
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.core.channel", channel)
    return channel
