import json
from g1_brain.fleet.contracts.json_schema_export import export_schemas


def test_export_writes_one_file_per_model(tmp_path):
    written = export_schemas(tmp_path)
    names = {p.name for p in written}
    assert "CapabilityDescriptor.v1.schema.json" in names
    assert "RobotStateMsg.v1.schema.json" in names
    assert "RobotEvent.v1.schema.json" in names
    for p in written:
        doc = json.loads(p.read_text())
        assert "properties" in doc
