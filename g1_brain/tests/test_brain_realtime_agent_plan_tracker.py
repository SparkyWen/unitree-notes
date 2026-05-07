"""Tests for BrainRealtimeAgent plan tracking + new hooks.

Covers the multi-response plan logic that drives plan_done — without
hitting an actual OpenAI Realtime websocket. We construct a
BrainRealtimeAgent with all I/O dependencies stubbed and feed
hand-crafted Realtime events through ``_handle_event`` directly.

Key invariants:
- ``on_plan_done`` fires exactly once per plan
- intermediate ``response.done`` events whose response had a function_call
  output do NOT fire plan_done (the model will continue after the tool
  result)
- terminal ``response.done`` events whose response had no function_call
  fire plan_done
- ``cancel_in_flight`` resets plan state and is a no-op when WS is None
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, List

import pytest

# va-demo must be on sys.path before importing BrainRealtimeAgent (it
# subclasses va-demo's RealtimeAgent).
_VA = "/home/helios/unitree/unitree-notes/va-demo"
if _VA not in sys.path:
    sys.path.insert(0, _VA)

from g1_brain.brain.realtime_agent import BrainRealtimeAgent  # noqa: E402


# ----------------------------------------------------------------- stubs ----

class _StubSpeaker:
    def __init__(self):
        self.cleared = 0
        self.written = bytearray()

    def write(self, data):
        self.written.extend(data)

    def clear(self):
        self.cleared += 1

    def pending_bytes(self):
        return len(self.written)


class _StubMic:
    """Minimal MicStream stand-in. We never run uplink in these tests."""

    queue = None

    def subscribe(self):
        return asyncio.Queue()


class _StubSafety:
    async def validate(self, name, args):
        return True, "", args


class _StubSkillServer:
    def __init__(self, results=None):
        self.calls: List[tuple] = []
        self._results = results or {}

    async def execute(self, name, args):
        self.calls.append((name, args))
        return self._results.get(name, {"ok": True})


class _RecordingWS:
    def __init__(self):
        self.sent: List[Dict[str, Any]] = []
        self.fail_on_send = False

    async def send(self, raw):
        if self.fail_on_send:
            raise RuntimeError("ws closed")
        self.sent.append(json.loads(raw))


# ------------------------------------------------------------- helpers ----

def _make_agent(skill_server=None, ws=None):
    """Build a BrainRealtimeAgent with all I/O stubbed."""
    agent = BrainRealtimeAgent(
        api_key="sk-test",
        model="test-model",
        voice="verse",
        mic=_StubMic(),
        speaker=_StubSpeaker(),
        camera=None,
        vision=None,
        tts=None,
        skills=None,
        safety=_StubSafety(),
        skill_server=skill_server or _StubSkillServer(),
    )
    if ws is not None:
        agent._ws = ws
    return agent


def _resp_done(*, with_function_call=False, response_id="resp_1"):
    output = []
    if with_function_call:
        output.append({"type": "function_call", "call_id": "call_xx", "name": "walk"})
    return {"type": "response.done",
            "response": {"id": response_id, "output": output}}


# ---------------------------------------------------------------- tests ----

@pytest.mark.asyncio
async def test_leaf_response_done_fires_plan_done():
    """A response with no function_call output → on_plan_done fires once."""
    agent = _make_agent()
    fired = []
    agent.on_plan_done = lambda: fired.append("plan_done")
    # Mark plan active (commit_and_respond does this in normal flow).
    agent._plan_active = True

    await agent._handle_event(_RecordingWS(), _resp_done(with_function_call=False))

    assert fired == ["plan_done"]
    # Idempotent: a stale response.done after plan_done already fired stays silent.
    await agent._handle_event(_RecordingWS(), _resp_done(with_function_call=False))
    assert fired == ["plan_done"]


@pytest.mark.asyncio
async def test_intermediate_response_done_does_not_fire_plan_done():
    """response.done whose response had a function_call must not fire plan_done."""
    agent = _make_agent()
    fired = []
    agent.on_plan_done = lambda: fired.append("plan_done")
    agent._plan_active = True

    await agent._handle_event(_RecordingWS(),
                              _resp_done(with_function_call=True))
    assert fired == []
    assert agent._plan_active is True


@pytest.mark.asyncio
async def test_full_multi_response_plan_fires_once():
    """Simulate: intermediate response.done (had fcall) → tool dispatch →
    next response.created → leaf response.done (no fcall) → plan_done."""
    skill = _StubSkillServer(results={"walk": {"ok": True}})
    ws = _RecordingWS()
    agent = _make_agent(skill_server=skill, ws=ws)
    fired = []
    agent.on_plan_done = lambda: fired.append("plan_done")
    agent._plan_active = True

    # function_call_arguments.done fires before the response.done that
    # carries the function_call output item, in real Realtime traffic.
    await agent._handle_event(ws, {
        "type": "response.function_call_arguments.done",
        "call_id": "call_walk",
        "name": "walk",
        "arguments": json.dumps({"vx": 0.2, "duration_s": 1.0}),
    })

    # Tool dispatch should have run + sent function_call_output + response.create.
    sent_types = [m["type"] for m in ws.sent]
    assert "conversation.item.create" in sent_types
    assert "response.create" in sent_types
    assert skill.calls == [("walk", {"vx": 0.2, "duration_s": 1.0})]

    # Intermediate response.done (with fcall) — must NOT fire plan_done.
    await agent._handle_event(ws, _resp_done(with_function_call=True))
    assert fired == []
    assert agent._plan_active is True

    # Next leaf response.done (no fcall) — fires plan_done exactly once.
    await agent._handle_event(ws, _resp_done(with_function_call=False,
                                             response_id="resp_2"))
    assert fired == ["plan_done"]


@pytest.mark.asyncio
async def test_tool_use_and_tool_result_callbacks_fire():
    skill = _StubSkillServer(results={"walk": {"ok": True, "executed": "walk"}})
    ws = _RecordingWS()
    agent = _make_agent(skill_server=skill, ws=ws)
    tool_uses, tool_results = [], []
    agent.on_tool_use = lambda call_id, name, args: tool_uses.append((call_id, name, args))
    agent.on_tool_result = lambda call_id, name, res: tool_results.append((call_id, name, res))

    await agent._handle_event(ws, {
        "type": "response.function_call_arguments.done",
        "call_id": "call_w",
        "name": "walk",
        "arguments": json.dumps({"vx": 0.1, "duration_s": 1.0}),
    })

    assert tool_uses == [("call_w", "walk", {"vx": 0.1, "duration_s": 1.0})]
    assert tool_results == [
        ("call_w", "walk", {"ok": True, "executed": "walk"}),
    ]


@pytest.mark.asyncio
async def test_user_transcript_callback_fires():
    agent = _make_agent()
    seen = []
    agent.on_user_transcript = lambda t: seen.append(t)
    await agent._handle_event(_RecordingWS(), {
        "type": "conversation.item.input_audio_transcription.completed",
        "transcript": "走五米",
    })
    assert seen == ["走五米"]


@pytest.mark.asyncio
async def test_assistant_transcript_done_callback_fires():
    agent = _make_agent()
    seen = []
    agent.on_assistant_transcript_done = lambda t: seen.append(t)
    await agent._handle_event(_RecordingWS(), {
        "type": "response.audio_transcript.done",
        "transcript": "好的，开始走",
    })
    assert seen == ["好的，开始走"]


@pytest.mark.asyncio
async def test_cancel_in_flight_clears_speaker_and_resets_plan():
    ws = _RecordingWS()
    agent = _make_agent(ws=ws)
    agent._plan_active = True
    canceled = []
    agent.on_response_canceled = lambda r: canceled.append(r)

    await agent.cancel_in_flight()

    sent_types = [m["type"] for m in ws.sent]
    assert "response.cancel" in sent_types
    assert "input_audio_buffer.clear" in sent_types
    assert agent.speaker.cleared >= 1
    assert canceled == ["barge_in"]
    assert agent._plan_active is False


@pytest.mark.asyncio
async def test_cancel_in_flight_no_ws_does_nothing():
    agent = _make_agent()  # _ws is None
    # Must not raise.
    await agent.cancel_in_flight()
    # speaker.cleared should be 0 because we never reached the local clear.
    assert agent.speaker.cleared == 0


@pytest.mark.asyncio
async def test_cancel_in_flight_swallows_send_failures():
    ws = _RecordingWS()
    ws.fail_on_send = True
    agent = _make_agent(ws=ws)
    # Must not raise even when both sends fail.
    await agent.cancel_in_flight()


@pytest.mark.asyncio
async def test_response_had_function_call_helper():
    assert BrainRealtimeAgent._response_had_function_call(
        {"response": {"output": [{"type": "function_call"}]}}
    ) is True
    assert BrainRealtimeAgent._response_had_function_call(
        {"response": {"output": [{"type": "message"}]}}
    ) is False
    assert BrainRealtimeAgent._response_had_function_call(
        {"response": {"output": []}}
    ) is False
    # Defensive: missing output / response.
    assert BrainRealtimeAgent._response_had_function_call(
        {}
    ) is False


@pytest.mark.asyncio
async def test_commit_and_respond_marks_plan_active():
    ws = _RecordingWS()
    agent = _make_agent(ws=ws)
    assert agent._plan_active is False
    await agent.commit_and_respond()
    assert agent._plan_active is True
    sent_types = [m["type"] for m in ws.sent]
    assert "input_audio_buffer.commit" in sent_types
    assert "response.create" in sent_types


@pytest.mark.asyncio
async def test_tool_dispatch_failure_emits_plan_done_via_finally():
    """If sending function_call_output / response.create fails (WS closed),
    the agent falls back to firing plan_done so the state machine doesn't
    get stuck waiting for a response that will never arrive."""
    skill = _StubSkillServer(results={"walk": {"ok": True}})
    ws = _RecordingWS()
    ws.fail_on_send = True
    agent = _make_agent(skill_server=skill, ws=ws)
    agent._plan_active = True
    fired = []
    agent.on_plan_done = lambda: fired.append("plan_done")

    await agent._handle_event(ws, {
        "type": "response.function_call_arguments.done",
        "call_id": "call_w",
        "name": "walk",
        "arguments": json.dumps({"vx": 0.1, "duration_s": 1.0}),
    })
    assert fired == ["plan_done"]


@pytest.mark.asyncio
async def test_audio_delta_writes_speaker_and_fires_callback():
    import base64
    agent = _make_agent()
    delta_fired = []
    agent.on_response_audio_delta = lambda: delta_fired.append(1)
    await agent._handle_event(_RecordingWS(), {
        "type": "response.audio.delta",
        "delta": base64.b64encode(b"\x00\x01\x02").decode("ascii"),
    })
    assert bytes(agent.speaker.written) == b"\x00\x01\x02"
    assert delta_fired == [1]


# --------------------------------------------------------------------------
# barge-in: cancelled responses must not bleed into the next turn
# --------------------------------------------------------------------------
#
# Repro of the field log around 19:57 / 20:01: after the operator says
# 'Hi Sparky' the OpenAI Realtime server emits one or more events for the
# response that was *just* cancelled — typically because the response had
# already been finalized server-side before the cancel arrived (the
# error 'response_cancel_not_active' confirms this race).
#
# Without the filter:
#   - audio.delta + audio_transcript.delta from the cancelled response
#     keep writing to the speaker so the user hears the robot finish the
#     OLD reply after their barge-in;
#   - function_call_arguments.done from the cancelled response dispatches
#     stale walks/turns AFTER the user issued a new command;
#   - each stale dispatch sends response.create which lands a fresh
#     response on top of the still-live (server-side) cancelled one,
#     producing 'conversation_already_has_active_response' on the next
#     real turn.
# The fixture below pins the contract: events whose response_id was
# marked cancelled at cancel_in_flight() time are silently dropped, while
# events for a *new* response_id pass through normally.

@pytest.mark.asyncio
async def test_audio_delta_for_cancelled_response_is_dropped():
    import base64
    ws = _RecordingWS()
    agent = _make_agent(ws=ws)
    delta_fired = []
    agent.on_response_audio_delta = lambda: delta_fired.append(1)

    # Server sends response.created → we track id; barge-in cancels.
    await agent._handle_event(ws, {
        "type": "response.created", "response": {"id": "resp_old"},
    })
    await agent.cancel_in_flight()
    assert "resp_old" in agent._cancelled_response_ids

    # Late audio.delta from the cancelled response: dropped entirely.
    await agent._handle_event(ws, {
        "type": "response.audio.delta",
        "response_id": "resp_old",
        "delta": base64.b64encode(b"\x10\x20\x30").decode("ascii"),
    })
    assert bytes(agent.speaker.written) == b""
    assert delta_fired == []


@pytest.mark.asyncio
async def test_audio_transcript_delta_for_cancelled_response_is_dropped(capsys):
    ws = _RecordingWS()
    agent = _make_agent(ws=ws)

    await agent._handle_event(ws, {
        "type": "response.created", "response": {"id": "resp_old"},
    })
    await agent.cancel_in_flight()

    # Late transcript delta from the cancelled response: must NOT print
    # the leftover phrase (this was the visible 'I've moved forward 10
    # meters' echo in the field log).
    await agent._handle_event(ws, {
        "type": "response.audio_transcript.delta",
        "response_id": "resp_old",
        "delta": "I've moved forward 10 meters",
    })
    captured = capsys.readouterr()
    assert "10 meters" not in captured.out
    assert "10 meters" not in captured.err


@pytest.mark.asyncio
async def test_function_call_arguments_done_for_cancelled_response_is_dropped():
    """Late tool dispatch from a cancelled response must not run the skill."""
    skill = _StubSkillServer(results={"walk": {"ok": True}})
    ws = _RecordingWS()
    agent = _make_agent(skill_server=skill, ws=ws)

    await agent._handle_event(ws, {
        "type": "response.created", "response": {"id": "resp_old"},
    })
    await agent.cancel_in_flight()

    # Server emits a queued function_call_arguments.done for the cancelled
    # response (this is the 'tool call: turn({yaw_deg: -25})' chain we saw
    # firing AFTER the user said 'Turn right' in the 20:00:56 log slice).
    await agent._handle_event(ws, {
        "type": "response.function_call_arguments.done",
        "response_id": "resp_old",
        "call_id": "call_walk_old",
        "name": "walk",
        "arguments": json.dumps({"vx": 0.2, "duration_s": 1.0}),
    })

    # Skill must not have been executed; no follow-up response.create
    # must have been queued (which would otherwise collide with the new
    # turn's response.create as 'conversation_already_has_active_response').
    assert skill.calls == []
    sent_types = [m["type"] for m in ws.sent]
    # The only sends we expect are the response.cancel + buffer clear
    # from cancel_in_flight itself.
    assert "response.create" not in sent_types
    assert "conversation.item.create" not in sent_types


@pytest.mark.asyncio
async def test_response_done_for_cancelled_response_does_not_fire_plan_done():
    ws = _RecordingWS()
    agent = _make_agent(ws=ws)
    fired = []
    agent.on_plan_done = lambda: fired.append("plan_done")
    agent._plan_active = True

    await agent._handle_event(ws, {
        "type": "response.created", "response": {"id": "resp_old"},
    })
    await agent.cancel_in_flight()
    # cancel_in_flight already clears plan_active; restore for the test
    # so we'd see plan_done if the late event were not dropped.
    agent._plan_active = True

    await agent._handle_event(ws, _resp_done(
        with_function_call=False, response_id="resp_old",
    ))
    assert fired == []


@pytest.mark.asyncio
async def test_new_response_after_cancel_passes_through():
    """Events for a fresh response (created AFTER the cancel) must not be
    affected by the cancelled set. Otherwise we'd silence the next turn."""
    import base64
    ws = _RecordingWS()
    agent = _make_agent(ws=ws)

    await agent._handle_event(ws, {
        "type": "response.created", "response": {"id": "resp_old"},
    })
    await agent.cancel_in_flight()

    # Brand-new response from the user's next turn.
    await agent._handle_event(ws, {
        "type": "response.created", "response": {"id": "resp_new"},
    })
    await agent._handle_event(ws, {
        "type": "response.audio.delta",
        "response_id": "resp_new",
        "delta": base64.b64encode(b"\xaa\xbb").decode("ascii"),
    })
    assert bytes(agent.speaker.written) == b"\xaa\xbb"


@pytest.mark.asyncio
async def test_in_flight_dispatch_suppresses_response_create_after_cancel():
    """If a tool was dispatched on a response that gets cancelled WHILE the
    skill is executing (e.g. operator barges in 14 s into a 50 s walk),
    the tool eventually returns and _dispatch_tool would normally send
    function_call_output + response.create. That follow-up MUST be
    skipped — the next user turn's response.create would otherwise hit
    'conversation_already_has_active_response'.
    """
    skill = _StubSkillServer(results={"walk": {"ok": True}})
    ws = _RecordingWS()
    agent = _make_agent(skill_server=skill, ws=ws)
    plan_done_fired = []
    agent.on_plan_done = lambda: plan_done_fired.append(1)
    agent._plan_active = True

    # Track the response, then mark it cancelled (simulating cancel
    # arriving WHILE _skill_walk is awaiting its sleep loop).
    agent._current_response_id = "resp_walk_old"
    agent._cancelled_response_ids.append("resp_walk_old")

    # The dispatch event was already in flight before the cancel; the
    # outer _handle_event drop-filter wouldn't catch this case in the
    # field because dispatch can also be triggered for events whose
    # response_id is added to the cancelled set DURING execution. Drive
    # _dispatch_tool directly to exercise the in-flight path.
    await agent._dispatch_tool(ws, {
        "type": "response.function_call_arguments.done",
        "response_id": "resp_walk_old",
        "call_id": "call_walk_old",
        "name": "walk",
        "arguments": json.dumps({"vx": 0.2, "duration_s": 1.0}),
    })

    # Skill ran (we cannot un-run an already-dispatched skill), but the
    # WS follow-up is suppressed.
    assert skill.calls == [("walk", {"vx": 0.2, "duration_s": 1.0})]
    sent_types = [m["type"] for m in ws.sent]
    assert "conversation.item.create" not in sent_types
    assert "response.create" not in sent_types
    # Plan_done fired so the SM doesn't sit waiting for a leaf response.done.
    assert plan_done_fired == [1]


@pytest.mark.asyncio
async def test_cancelled_response_id_set_is_bounded():
    """Many barge-ins in a long session must not grow the cancelled set
    without bound. The cap is small — just verify the LRU drops the
    oldest id once the cap is reached."""
    agent = _make_agent(ws=_RecordingWS())
    agent._cancelled_response_id_cap = 4
    for i in range(8):
        agent._current_response_id = f"resp_{i}"
        agent._mark_current_response_cancelled()
    assert len(agent._cancelled_response_ids) == 4
    # Oldest 4 dropped, newest 4 retained.
    assert agent._cancelled_response_ids == [
        "resp_4", "resp_5", "resp_6", "resp_7",
    ]
