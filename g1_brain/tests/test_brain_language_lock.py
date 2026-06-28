"""Tests for the English-only language lock.

Regression guard for the Realtime agent drifting into Korean/Chinese: the
persona prompts must not invite a language switch, and a hard language
directive must be appended LAST to the resolved instructions (and a language
hint must reach the input-transcription config).
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

# va-demo must be importable for BrainRealtimeAgent's parent class.
_VA = Path(__file__).resolve().parents[2] / "va-demo"
if str(_VA) not in sys.path:
    sys.path.insert(0, str(_VA))

from g1_brain.brain.prompts import (  # noqa: E402
    PHONE_CALL_PREAMBLE,
    REALTIME_SYSTEM_PROMPT_BRAIN,
    REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY,
    language_directive,
)
from g1_brain.brain.realtime_agent import BrainRealtimeAgent  # noqa: E402


class _StubMic:
    queue = None

    def subscribe(self):
        return asyncio.Queue()


class _StubSpeaker:
    def write(self, data):  # pragma: no cover - never called here
        pass

    def clear(self):  # pragma: no cover
        pass


def _make_agent(**kw) -> BrainRealtimeAgent:
    return BrainRealtimeAgent(
        api_key="sk-test",
        model="test-model",
        voice="alloy",
        mic=_StubMic(),
        speaker=_StubSpeaker(),
        camera=None,
        vision=None,
        tts=None,
        skills=None,
        safety=None,
        skill_server=None,
        **kw,
    )


# ----------------------------------------------------------- directive ----

def test_language_directive_english():
    d = language_directive("en")
    assert "English only" in d
    assert "HARD RULE" in d
    # Must be safe to append to the vision-only prompt (no wake/keyword words).
    assert not re.search(r"\bwalk\b", d, re.IGNORECASE)
    assert not re.search(r"\bgesture\b", d, re.IGNORECASE)


def test_language_directive_other_language():
    assert "Chinese only" in language_directive("zh")
    # Unknown code falls back to the raw code rather than crashing.
    assert "xx" in language_directive("xx")


def test_personas_no_longer_force_user_language():
    for p in (REALTIME_SYSTEM_PROMPT_BRAIN, REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY):
        assert "Speak in the user's language" not in p
    # The phone preamble no longer mirrors the operator's language.
    assert "reply in Chinese" not in PHONE_CALL_PREAMBLE


# --------------------------------------------------- resolved instructions ----

def test_default_instructions_end_with_english_lock():
    agent = _make_agent()
    instr = agent._resolve_instructions()
    assert instr.rstrip().endswith(language_directive("en").rstrip())
    assert "English only" in instr


def test_configured_language_flows_into_directive():
    agent = _make_agent(response_language="zh")
    assert "Chinese only" in agent._resolve_instructions()


def test_vision_only_instructions_get_directive():
    agent = _make_agent(vision_only=True)
    instr = agent._resolve_instructions()
    assert "English only" in instr
    # The vision-only base must still avoid the wake/keyword words; the appended
    # directive must not reintroduce them.
    assert not re.search(r"\bwalk\b", instr, re.IGNORECASE)
    assert not re.search(r"\bgesture\b", instr, re.IGNORECASE)


def test_directive_is_after_memory_addendum():
    agent = _make_agent()
    agent.append_developer_instructions("REMEMBER: the user likes tea.")
    instr = agent._resolve_instructions()
    assert instr.index("REMEMBER") < instr.index("HARD RULE")


# --------------------------------------------------- transcription hint ----

def test_transcription_cfg_includes_language_when_set():
    agent = _make_agent(transcribe_language="en")
    cfg = agent._transcription_cfg()
    assert cfg["language"] == "en"
    assert cfg["model"] == "gpt-4o-mini-transcribe"


def test_transcription_cfg_omits_language_when_unset():
    agent = _make_agent()  # transcribe_language defaults to None
    assert "language" not in agent._transcription_cfg()
