from g1_brain.fleet.coordinator.__main__ import build_default_app


def test_build_default_app(tmp_path):
    app = build_default_app(db_path=tmp_path / "fleet.sqlite")
    paths = {r.resource.canonical for r in app.router.routes() if r.resource}
    assert "/fleet" in paths
    assert "/robots" in paths
    app["event_log"].close()
