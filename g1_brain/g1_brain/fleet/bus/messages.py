"""Wire envelope for the FleetBus: a JSON frame with a kind discriminator."""
from __future__ import annotations

import enum
import json
from typing import Optional, Tuple

from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent,
    CommandEnvelope, AdmissionDecision,
)


class FrameKind(str, enum.Enum):
    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    EVENT = "event"
    PING = "ping"
    PONG = "pong"
    COMMAND = "command"      # coordinator -> robot (down-bound)
    ADMISSION = "admission"  # robot -> coordinator (admission decision)


_MODEL_FOR = {
    FrameKind.REGISTER: CapabilityDescriptor,
    FrameKind.HEARTBEAT: RobotStateMsg,
    FrameKind.EVENT: RobotEvent,
    FrameKind.COMMAND: CommandEnvelope,
    FrameKind.ADMISSION: AdmissionDecision,
}


def encode_frame(kind: FrameKind, model: Optional[object]) -> str:
    body = model.model_dump(mode="json") if model is not None else None
    return json.dumps({"kind": kind.value, "body": body}, ensure_ascii=False)


def decode_frame(raw: str) -> Tuple[FrameKind, Optional[object]]:
    obj = json.loads(raw)
    kind = FrameKind(obj["kind"])
    model_cls = _MODEL_FOR.get(kind)
    if model_cls is None or obj.get("body") is None:
        return kind, None
    return kind, model_cls.model_validate(obj["body"])
