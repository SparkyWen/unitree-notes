"""LeaseManager: TTL + heartbeat + expiry."""
from g1_brain.fleet.coordinator.lease import LeaseManager


def test_grant_then_expire():
    t = [1000.0]
    lm = LeaseManager(clock=lambda: t[0])
    lm.grant("g1_a", ttl_s=30.0)
    assert lm.tick() == []          # not yet expired
    t[0] = 1040.0
    exp = lm.tick()
    assert len(exp) == 1 and exp[0].robot_id == "g1_a"
    assert lm.tick() == []          # removed after expiry


def test_heartbeat_renews():
    t = [1000.0]
    lm = LeaseManager(clock=lambda: t[0])
    lid = lm.grant("g1_a", ttl_s=30.0)
    t[0] = 1020.0
    assert lm.heartbeat(lid) is True
    t[0] = 1045.0
    assert lm.tick() == []          # renewed to 1050, not expired at 1045
    t[0] = 1060.0
    assert len(lm.tick()) == 1


def test_heartbeat_unknown_lease():
    lm = LeaseManager(clock=lambda: 1.0)
    assert lm.heartbeat("nope") is False


def test_active_lists_outstanding():
    lm = LeaseManager(clock=lambda: 1.0)
    lm.grant("g1_a", ttl_s=30.0)
    lm.grant("g1_b", ttl_s=30.0)
    assert {r.robot_id for r in lm.active()} == {"g1_a", "g1_b"}
