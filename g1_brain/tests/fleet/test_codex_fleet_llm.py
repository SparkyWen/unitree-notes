"""CodexFleetLLM — adapter that turns the g1_brain codex brain into a
FleetCommander LLM. The risky part is extracting a clean FleetPlan JSON out of
codex's reasoning+prose reply; that is unit-tested here with a fake codex
client (no real `codex exec`, no network)."""
import pytest

from g1_brain.fleet.coordinator.codex_fleet_llm import (
    CodexFleetLLM, extract_plan_json)


# ---- extract_plan_json: pure JSON-from-prose extraction ----

def test_extract_plain_json():
    assert extract_plan_json('{"summary":"ok","risk":"low"}') == {
        "summary": "ok", "risk": "low"}


def test_extract_fenced_json():
    text = 'Here is the plan:\n```json\n{"summary":"go","assignments":[]}\n```\nDone.'
    assert extract_plan_json(text)["summary"] == "go"


def test_extract_json_with_prose_and_nesting():
    text = ('Reasoning... final plan: {"summary":"x","coordination":'
            '{"type":"relay","point":[0,0]},"assignments":[{"robot_id":"g1_a",'
            '"goal":[1,2]}]} -- done')
    d = extract_plan_json(text)
    assert d["coordination"]["type"] == "relay"
    assert d["assignments"][0]["robot_id"] == "g1_a"


def test_extract_ignores_braces_inside_strings():
    text = '{"summary":"use {these} braces","risk":"low"}'
    assert extract_plan_json(text)["summary"] == "use {these} braces"


def test_extract_no_json_raises():
    with pytest.raises(ValueError):
        extract_plan_json("there is no json here at all")


# ---- CodexFleetLLM.plan_fleet: adapter wiring (fake codex client) ----

class _FakeResult:
    def __init__(self, text):
        self.text = text


class _FakeCodex:
    """Stands in for memory.codex_client.CodexClient."""
    def __init__(self, text):
        self._text = text
        self.prompts = []

    def is_available(self):
        return True

    async def exec_once(self, prompt, *, timeout_s=120.0, **kw):
        self.prompts.append(prompt)
        return _FakeResult(self._text)


def test_plan_fleet_returns_dict_and_embeds_nl_and_snapshot():
    fake = _FakeCodex(
        '{"summary":"会合","coordination":{"type":"rendezvous","point":[0,0]},'
        '"assignments":[],"risk":"low"}')
    llm = CodexFleetLLM(client=fake)
    d = llm.plan_fleet("两机到中间会合", {"robots": [{"robot_id": "g1_a", "x": -1.5, "y": 0}]})
    assert d["coordination"]["type"] == "rendezvous"
    # the operator NL and the fleet snapshot must reach codex in the prompt
    assert "两机到中间会合" in fake.prompts[0]
    assert "g1_a" in fake.prompts[0]
