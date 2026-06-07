from g1_brain.fleet.coordinator.registry import FleetRegistry
from g1_brain.fleet.contracts.models import CapabilityDescriptor, RobotStateMsg


def _clock():
    box = {"t": 1000.0}
    return box, (lambda: box["t"])


def test_register_then_heartbeat_online():
    box, now = _clock()
    reg = FleetRegistry(stale_after_s=5.0, offline_after_s=15.0, now=now)
    reg.register(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
    reg.on_heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=1))
    assert reg.status("r1") == "online"


def test_transitions_to_stale_then_offline():
    box, now = _clock()
    reg = FleetRegistry(stale_after_s=5.0, offline_after_s=15.0, now=now)
    reg.register(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
    reg.on_heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=1))
    box["t"] = 1008.0
    assert reg.status("r1") == "stale"
    box["t"] = 1020.0
    assert reg.status("r1") == "offline"


def test_out_of_order_seq_dropped():
    box, now = _clock()
    reg = FleetRegistry(stale_after_s=5.0, offline_after_s=15.0, now=now)
    reg.register(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
    reg.on_heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=5, fsm_state="ENGAGED"))
    reg.on_heartbeat(RobotStateMsg(robot_id="r1", ts="t", seq=2, fsm_state="ACTING"))
    assert reg.latest_state("r1").fsm_state == "ENGAGED"


def test_list_robots():
    box, now = _clock()
    reg = FleetRegistry(stale_after_s=5.0, offline_after_s=15.0, now=now)
    reg.register(CapabilityDescriptor(robot_id="r1", frame_id="r1/map"))
    reg.register(CapabilityDescriptor(robot_id="r2", frame_id="r2/map"))
    assert {r["robot_id"] for r in reg.list_robots()} == {"r1", "r2"}
