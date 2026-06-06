"""Dump pydantic contract models to JSON Schema files (CI artifact)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .models import CapabilityDescriptor, RobotStateMsg, RobotEvent

_MODELS = {
    "CapabilityDescriptor.v1": CapabilityDescriptor,
    "RobotStateMsg.v1": RobotStateMsg,
    "RobotEvent.v1": RobotEvent,
}


def export_schemas(out_dir: Path) -> List[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for name, model in _MODELS.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False))
        written.append(path)
    return written


if __name__ == "__main__":  # pragma: no cover
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("contracts_schema")
    for p in export_schemas(target):
        print(p)
