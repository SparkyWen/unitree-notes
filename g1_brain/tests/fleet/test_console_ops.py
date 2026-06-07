"""Operator console: command-body builders + rich status formatting (pure)."""
from g1_brain.fleet.console.cli import build_command_body, format_status


def test_build_command_body_sleep_wake():
    assert build_command_body("sleep", robot="g1_a") == {"op": "sleep", "args": {"robot": "g1_a"}}
    assert build_command_body("wake", robot="g1_a") == {"op": "wake", "args": {"robot": "g1_a"}}


def test_build_command_body_takeover():
    assert build_command_body("takeover", from_robot="g1_a", to_robot="g1_b") == {
        "op": "takeover", "args": {"from": "g1_a", "to": "g1_b"}}


def test_build_command_body_inject():
    b = build_command_body("inject", robot="g1_a", battery_temperature_c=75.0, fault="battery_hot")
    assert b["op"] == "inject" and b["robot"] == "g1_a"
    assert b["battery_temperature_c"] == 75.0 and b["fault"] == "battery_hot"


def test_build_command_body_dispatch():
    assert build_command_body("dispatch", task="patrol", target="fleet") == {
        "op": "dispatch", "args": {"task": "patrol", "target": "fleet"}}


def test_format_status_shows_battery_anomalies_assignments():
    robots = [{
        "robot_id": "g1_a", "status": "online", "capabilities": ["patrol"],
        "state": {"fsm_state": "DORMANT",
                  "core": {"battery": {"temperature_c": 75.0, "soc": 0.4},
                           "health": {"level": "warning"}}}}]
    dispatch = {
        "assignments": {"t1": "g1_b"}, "needs_operator": [],
        "anomalies": [{"robot_id": "g1_a", "kind": "battery_overheat",
                       "severity": "critical", "evidence": {"temperature_c": 75.0}}],
        "leases": []}
    s = format_status(robots, {"robot_count": 1, "robots_path_blocked": 0,
                               "robots_with_humans": 0}, dispatch)
    assert "g1_a" in s and "75" in s and "DORMANT" in s
    assert "battery_overheat" in s
    assert "t1" in s and "g1_b" in s
