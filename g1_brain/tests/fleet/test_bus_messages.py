from g1_brain.fleet.bus.messages import encode_frame, decode_frame, FrameKind
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


def test_register_frame_roundtrip():
    cap = CapabilityDescriptor(robot_id="r", frame_id="r/map")
    raw = encode_frame(FrameKind.REGISTER, cap)
    kind, model = decode_frame(raw)
    assert kind == FrameKind.REGISTER
    assert isinstance(model, CapabilityDescriptor)
    assert model.robot_id == "r"


def test_heartbeat_and_event_roundtrip():
    st = RobotStateMsg(robot_id="r", ts="t", seq=3)
    kind, model = decode_frame(encode_frame(FrameKind.HEARTBEAT, st))
    assert kind == FrameKind.HEARTBEAT and model.seq == 3

    ev = RobotEvent.make(robot_id="r", type=EventType.SCENE_SNAPSHOT, ts="t", payload={})
    kind, model = decode_frame(encode_frame(FrameKind.EVENT, ev))
    assert kind == FrameKind.EVENT and model.type == EventType.SCENE_SNAPSHOT


def test_ping_frame_has_no_model():
    kind, model = decode_frame(encode_frame(FrameKind.PING, None))
    assert kind == FrameKind.PING and model is None
