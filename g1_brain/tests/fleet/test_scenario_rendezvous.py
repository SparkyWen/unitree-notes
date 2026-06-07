"""P3 end-to-end gate: NL command -> commander -> sub-agents -> barrier ->
two RL G1s rendezvous in one shared world and hand off patrol. Empirical
(steps real physics); paced ~real time. No OpenAI key needed (deterministic)."""
import pytest

from g1_brain.fleet.sim.scenario_rendezvous import run


@pytest.mark.slow
def test_rendezvous_relay_end_to_end():
    r = run("让 g1_a 和 g1_b 到中间会合，然后 g1_a 把巡逻交给 g1_b")
    assert r["ok"] and r["plan_type"] == "relay"
    assert r["barrier_fired"], "rendezvous barrier never fired"
    assert r["completed"], "op sequences did not complete"
    assert r["upright"], "a robot fell during the demo"
    assert r["min_sep"] > 0.3, "robots collided"
    assert r["receiver_posture"] == "PATROL" and r["receiver_moved"] > 0.12
    assert r["hander_posture"] == "IDLE"
