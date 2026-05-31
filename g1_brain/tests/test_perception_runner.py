"""PerceptionRunner CameraHub sharing.

Regression: agent_main builds a CameraHub for skills/vision/describe_scene;
PerceptionRunner used to build a SECOND one for yolo/pose/ground, so the same
head camera was rendered by two offscreen render threads on Mesa llvmpipe
(~160 ms/frame each) — doubled CPU and doubled DDS subscribers for zero
benefit. py-spy on a wedged session showed two "g1-brain-head-render" threads
pegging llvmpipe. PerceptionRunner must REUSE an injected hub and must NOT
close it (agent_main owns its lifecycle); it only builds + owns a hub when
none is injected (perception_debug / tests).
"""
from __future__ import annotations

from g1_brain.perception import runner as runner_mod
from g1_brain.scene_state.fusion import SceneStateBus


class _FakeHead:
    def latest_depth_meters(self):
        return None


class _FakeHub:
    """Minimal CameraHub stand-in: no real camera, no render thread."""

    def __init__(self, *args, **kwargs):
        self.closed = False
        self._head = _FakeHead()

    @property
    def has_usb(self):
        return False

    @property
    def has_head(self):
        return True

    def latest_head_bgr(self):
        return None

    def latest_usb_bgr(self):
        return None

    def head_frame_age_seconds(self):
        return 0.0

    def usb_frame_age_seconds(self):
        return float("inf")

    def head_resolution(self):
        return (480, 640)

    def usb_resolution(self):
        return (0, 0)

    def head_hfov_deg(self):
        return 60.0

    def head_vfov_deg(self):
        return 45.0

    def close(self):
        self.closed = True


# yolo/pose/mono_depth disabled so start() touches no heavy deps
# (ultralytics/mediapipe/transformers) — only the hub + the light
# frame-age/ground daemon loops run.
_DISABLED_CFG = {
    "perception": {
        "yolo": {"enabled": False},
        "pose": {"enabled": False},
        "mono_depth": {"enabled": False},
    }
}


def test_runner_reuses_injected_hub_and_builds_no_second(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError(
            "PerceptionRunner built its own CameraHub despite an injected one"
        )

    monkeypatch.setattr(runner_mod, "CameraHub", _boom)
    hub = _FakeHub()
    r = runner_mod.PerceptionRunner(_DISABLED_CFG, SceneStateBus(), camera_hub=hub)
    r.start()
    try:
        assert r._cams is hub
        assert r._owns_cams is False
    finally:
        r.stop()
    assert hub.closed is False, "injected hub must NOT be closed by the runner"


def test_runner_without_injection_builds_and_owns_its_hub(monkeypatch):
    built = {"n": 0}

    class _RecordingHub(_FakeHub):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            built["n"] += 1

    monkeypatch.setattr(runner_mod, "CameraHub", _RecordingHub)
    r = runner_mod.PerceptionRunner(_DISABLED_CFG, SceneStateBus())
    r.start()
    try:
        assert built["n"] == 1, "runner must build exactly one hub when none injected"
        assert r._owns_cams is True
    finally:
        r.stop()
    assert r._cams.closed is True, "a self-built hub must be closed on stop()"
