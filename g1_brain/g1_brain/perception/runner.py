"""PerceptionRunner: 启停所有感知后台线程，对外只暴露这一个对象。

`apps/agent_main.py` only sees this class; it doesn't know about cameras,
YOLO, or MediaPipe directly.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from ..scene_state.fusion import SceneStateBus, RobotStateBus
from .cameras import CameraHub
from .derivations import compute_ground_constraint

log = logging.getLogger(__name__)


class PerceptionRunner:
    """Owns CameraHub + ObjectDetector + PoseDetector + ground-constraint loop."""

    def __init__(
        self,
        config: dict,
        scene_bus: SceneStateBus,
        robot_bus: Optional[RobotStateBus] = None,
        camera_hub: Optional[CameraHub] = None,
    ):
        self._cfg = config or {}
        self._scene = scene_bus
        self._robot = robot_bus

        # When agent_main already built a CameraHub (for skills/vision/
        # describe_scene), REUSE it instead of building a second one. Each
        # MuJoCoHeadCamera spins its own offscreen render thread that renders
        # the SAME head camera on Mesa llvmpipe (~160 ms/frame); two hubs meant
        # two render threads → doubled CPU and doubled DDS subscribers for zero
        # benefit (py-spy showed two "g1-brain-head-render" threads pegging
        # llvmpipe). agent_main owns the injected hub's lifecycle, so we must
        # NOT close it in stop(); only a hub WE built is ours to close.
        self._cams: Optional[CameraHub] = camera_hub
        self._owns_cams = camera_hub is None
        self._yolo = None
        self._pose = None
        self._depth_backend = None
        self._stop = threading.Event()
        self._ground_thread: Optional[threading.Thread] = None
        self._frame_thread: Optional[threading.Thread] = None
        self._started = False

    # ---------------- start/stop ----------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._cams is None:
            self._cams = CameraHub(
                self._cfg.get("cameras", {}),
                robot_mjcf_path=(self._cfg.get("robot", {}) or {}).get("mjcf_path"),
            )
            self._owns_cams = True

        perc = self._cfg.get("perception", {}) or {}
        device = perc.get("device", "auto")

        # Object detector
        ycfg = perc.get("yolo", {}) or {}
        if ycfg.get("enabled", True):
            try:
                from .object_detector import ObjectDetector

                self._yolo = ObjectDetector(
                    cameras=self._cams,
                    scene_bus=self._scene,
                    weights=ycfg.get("weights", "yolo11s.pt"),
                    conf=float(ycfg.get("conf", 0.4)),
                    inference_hz=float(ycfg.get("inference_hz", 15.0)),
                    sources=list(ycfg.get("sources", ["head", "usb"])),
                    device=device,
                )
                self._yolo.start()
            except Exception as e:
                log.warning("object detector start failed: %s", e)
                self._yolo = None

        # Pose detector (USB only)
        pcfg = perc.get("pose", {}) or {}
        if pcfg.get("enabled", True) and self._cams.has_usb:
            try:
                from .pose_detector import PoseDetector

                self._pose = PoseDetector(
                    cameras=self._cams,
                    scene_bus=self._scene,
                    inference_hz=float(pcfg.get("inference_hz", 15.0)),
                    min_visibility=float(pcfg.get("min_visibility", 0.5)),
                    gesture_persist_frames=int(pcfg.get("gesture_persist_frames", 3)),
                    gesture_min_confidence=float(pcfg.get("gesture_min_confidence", 0.7)),
                )
                self._pose.start()
            except Exception as e:
                log.warning("pose detector start failed: %s", e)
                self._pose = None

        # Depth backend selection (passive: depth comes from head cam already;
        # this object exists for the brain layer to query / for sim2real).
        mcfg = perc.get("mono_depth", {}) or {}
        if mcfg.get("enabled", False):
            try:
                from .depth import MonoDepthAnythingV2

                self._depth_backend = MonoDepthAnythingV2(
                    model=mcfg.get("model", "depth-anything/Depth-Anything-V2-Small-hf"),
                    device=mcfg.get("device", "cuda:0" if device != "cpu" else "cpu"),
                )
            except Exception as e:
                log.warning("mono depth init failed: %s", e)
                self._depth_backend = None
        else:
            from .depth import MuJoCoNativeDepth

            self._depth_backend = MuJoCoNativeDepth(self._cams._head)

        # Frame-age publisher loop: keeps the SceneStateBus's per-source
        # timestamps fresh even when no other consumer pulled a frame yet
        # (mirrors the watchdog rationale in va_demo.camera).
        self._frame_thread = threading.Thread(
            target=self._frame_age_loop, name="perception-frame-age", daemon=True
        )
        self._frame_thread.start()

        # Ground constraint loop @ 5 Hz
        self._ground_thread = threading.Thread(
            target=self._ground_loop, name="ground-constraint", daemon=True
        )
        self._ground_thread.start()

    def stop(self) -> None:
        self._stop.set()
        for det in (self._yolo, self._pose):
            if det is not None:
                try:
                    det.stop()
                except Exception:
                    pass
        for t in (self._ground_thread, self._frame_thread):
            if t is not None:
                try:
                    t.join(timeout=1.0)
                except Exception:
                    pass
        # Only close a hub we built. An injected hub belongs to agent_main,
        # which closes it in its own shutdown step (double-close would race
        # the render thread's GL-context teardown).
        if self._cams is not None and self._owns_cams:
            self._cams.close()

    # ---------------- background loops ----------------

    def _frame_age_loop(self) -> None:
        # Polls camera timestamps and pushes them into the bus so the safety
        # watchdog has a fresh frame_age reading.
        while not self._stop.is_set():
            try:
                if self._cams.has_usb:
                    bgr = self._cams.latest_usb_bgr()
                    if bgr is not None:
                        self._scene.update_usb_frame(
                            ts=time.monotonic() - self._cams.usb_frame_age_seconds(),
                            resolution=self._cams.usb_resolution(),
                        )
                if self._cams.has_head:
                    bgr = self._cams.latest_head_bgr()
                    if bgr is not None:
                        self._scene.update_head_frame(
                            ts=time.monotonic() - self._cams.head_frame_age_seconds(),
                            resolution=self._cams.head_resolution(),
                        )
            except Exception as e:
                log.debug("frame age loop: %s", e)
            self._stop.wait(0.2)

    def _ground_loop(self) -> None:
        gcfg = (self._cfg.get("perception", {}) or {}).get("ground_constraint", {}) or {}
        cone_half = float(gcfg.get("cone_half_angle_deg", 15.0))
        min_d = float(gcfg.get("cone_min_dist_m", 0.5))
        max_d = float(gcfg.get("cone_max_dist_m", 1.5))
        safe_clear = float(gcfg.get("safe_clearance_m", 0.6))
        while not self._stop.is_set():
            try:
                depth = (
                    self._depth_backend.latest_depth_meters(self._cams.latest_head_bgr())
                    if self._depth_backend is not None
                    else None
                )
                if depth is not None and self._cams is not None and self._cams.has_head:
                    # nearest_person_m: derived from head detections that we
                    # already published with depth (the YOLO worker fills
                    # `distance_m`); cheap re-scan on snapshot.
                    snap = self._scene.snapshot()
                    nearest_person = float("inf")
                    for d in snap.head_detections:
                        if d.class_name == "person" and d.distance_m is not None:
                            nearest_person = min(nearest_person, float(d.distance_m))
                    gc = compute_ground_constraint(
                        depth_m=depth,
                        hfov_deg=self._cams.head_hfov_deg(),
                        vfov_deg=self._cams.head_vfov_deg(),
                        cone_half_angle_deg=cone_half,
                        min_dist_m=min_d,
                        max_dist_m=max_d,
                        safe_clearance_m=safe_clear,
                        nearest_person_m=nearest_person,
                    )
                    self._scene.update_ground(gc)
            except Exception as e:
                log.debug("ground loop: %s", e)
            self._stop.wait(0.2)

    # ---------------- accessors ----------------

    @property
    def cameras(self) -> Optional[CameraHub]:
        return self._cams
