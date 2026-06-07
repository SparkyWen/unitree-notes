"""CoordinatorAgent: command grammar always works; LLM is optional + re-validated."""
from g1_brain.fleet.coordinator.agent_llm import CoordinatorAgent, StructuredOp
from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.contracts.models import CapabilityDescriptor


def _reg(*rids):
    reg = FleetRegistry()
    for rid in rids:
        reg.register(CapabilityDescriptor(robot_id=rid, frame_id=f"{rid}/map"))
    return reg


# ---- grammar (no LLM) ----

def test_grammar_dispatch():
    op = CoordinatorAgent().parse("dispatch patrol --to fleet")
    assert op.kind == "dispatch" and op.args["task"] == "patrol" and op.args["target"] == "fleet"


def test_grammar_sleep_wake_takeover_status():
    a = CoordinatorAgent()
    assert a.parse("sleep g1_a").args["robot"] == "g1_a"
    assert a.parse("wake g1_a").kind == "wake"
    t = a.parse("takeover g1_a g1_b")
    assert t.args == {"from": "g1_a", "to": "g1_b"}
    assert a.parse("status").kind == "status"


def test_grammar_unknown_returns_none():
    assert CoordinatorAgent().parse("让机群跳舞") is None


# ---- LLM path (mocked), with re-validation ----

def test_llm_parse_used_when_available():
    class FakeLLM:
        def parse(self, nl):
            return {"kind": "takeover", "args": {"from": "g1_a", "to": "g1_b"}}
    op = CoordinatorAgent(llm=FakeLLM()).parse("让2号接替1号")
    assert op.kind == "takeover" and op.args["to"] == "g1_b"


def test_llm_falls_back_to_grammar_on_none():
    class FakeLLM:
        def parse(self, nl):
            return None
    assert CoordinatorAgent(llm=FakeLLM()).parse("status").kind == "status"


def test_llm_op_revalidated_against_registry():
    class FakeLLM:
        def parse(self, nl):
            return {"kind": "sleep", "args": {"robot": "ghost"}}
    agent = CoordinatorAgent(llm=FakeLLM())
    op = agent.parse("put the broken one to sleep")
    ok, reason = agent.validate(op, _reg("g1_a", "g1_b"))
    assert not ok and "ghost" in reason


def test_validate_accepts_known_robot():
    agent = CoordinatorAgent()
    ok, _ = agent.validate(StructuredOp("sleep", {"robot": "g1_a"}), _reg("g1_a"))
    assert ok


# ---- explanation ----

def test_explain_template_cites_evidence_without_llm():
    s = CoordinatorAgent().explain(
        decision="moved task t1 from g1_a to g1_b",
        evidence={"temperature_c": 75.0, "candidate_soc": 0.8})
    assert "t1" in s and "75" in s
