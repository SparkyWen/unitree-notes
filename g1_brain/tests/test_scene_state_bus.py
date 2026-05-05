"""Sanity tests for the SceneStateBus + RobotStateBus thread-safety contract."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from g1_brain.scene_state.fusion import SceneStateBus, RobotStateBus
from g1_brain.scene_state.types import (
    Detection,
    GroundConstraint,
    HumanPose,
    RobotState,
)


def _make_pose(label: str = "wave_right", conf: float = 0.9) -> HumanPose:
    return HumanPose(
        landmarks_xy=np.zeros((33, 2), dtype=np.float32),
        landmarks_z=np.zeros((33,), dtype=np.float32),
        visibility=np.ones((33,), dtype=np.float32),
        gesture=label,
        gesture_confidence=conf,
    )


def _make_det(name: str = "person", dist: float = 1.5) -> Detection:
    return Detection(
        class_name=name,
        bbox_xyxy=(10, 10, 50, 80),
        score=0.9,
        distance_m=dist,
        bearing_deg=0.0,
        pitch_deg=0.0,
        source="head",
    )


def test_initial_snapshot_has_defaults():
    bus = SceneStateBus()
    snap = bus.snapshot()
    assert snap.user_pose is None
    assert snap.head_detections == []
    assert snap.user_detections == []
    assert snap.ground is None
    assert snap.ts_usb == 0.0
    assert snap.ts_head == 0.0


def test_update_user_pose_and_snapshot():
    bus = SceneStateBus()
    p = _make_pose()
    bus.update_user_pose(p, ts=time.monotonic())
    snap = bus.snapshot()
    assert snap.user_pose is p
    assert snap.user_pose.gesture == "wave_right"
    assert snap.ts_pose > 0.0


def test_detection_lists_are_isolated():
    """Producer mutating its local list must not leak into past snapshots."""
    bus = SceneStateBus()
    dets = [_make_det("person", 2.0)]
    bus.update_head_detections(dets)
    snap1 = bus.snapshot()
    dets.append(_make_det("chair", 1.0))   # mutate caller-side
    bus.update_head_detections(dets)
    snap2 = bus.snapshot()
    assert len(snap1.head_detections) == 1
    assert len(snap2.head_detections) == 2


def test_ground_constraint_round_trip():
    bus = SceneStateBus()
    gc = GroundConstraint(
        clear_path=True,
        nearest_obstacle_m=1.2,
        nearest_person_m=2.0,
        floor_visible_ratio=0.8,
        surface_tilt_deg=3.0,
    )
    bus.update_ground(gc)
    snap = bus.snapshot()
    assert snap.ground == gc


def test_warnings_dedupe_and_clear():
    bus = SceneStateBus()
    bus.add_warning("usb_dark")
    bus.add_warning("usb_dark")
    bus.add_warning("no_depth")
    assert bus.snapshot().perception_warnings == ["usb_dark", "no_depth"]
    bus.clear_warning("usb_dark")
    assert bus.snapshot().perception_warnings == ["no_depth"]
    bus.clear_warning("nonexistent")  # must not raise


def test_summary_for_llm_includes_persons_and_obstacle():
    bus = SceneStateBus()
    bus.update_head_detections([_make_det("person", 1.5), _make_det("chair", 0.9)])
    bus.update_ground(
        GroundConstraint(
            clear_path=False,
            nearest_obstacle_m=0.8,
            nearest_person_m=1.5,
            floor_visible_ratio=0.7,
            surface_tilt_deg=2.0,
        )
    )
    summary = bus.snapshot().summary_for_llm()
    assert summary["persons_visible"] == 1
    assert summary["nearest_obstacle_m"] == 0.8
    assert summary["nearest_person_m"] == 1.5
    assert summary["clear_path"] is False


def test_frame_age_starts_infinite_and_drops_after_update():
    bus = SceneStateBus()
    assert bus.usb_frame_age_s() == float("inf")
    assert bus.head_frame_age_s() == float("inf")
    bus.update_usb_frame(ts=time.monotonic(), resolution=(480, 640))
    bus.update_head_frame(ts=time.monotonic(), resolution=(480, 640))
    time.sleep(0.02)
    assert bus.usb_frame_age_s() < 1.0
    assert bus.head_frame_age_s() < 1.0


def test_concurrent_updates_do_not_corrupt_snapshot():
    bus = SceneStateBus()
    n_iter = 200

    def writer_pose():
        for i in range(n_iter):
            bus.update_user_pose(_make_pose("wave_right" if i % 2 == 0 else "hands_up", 0.8))

    def writer_det():
        for i in range(n_iter):
            bus.update_head_detections(
                [_make_det("person", 1.0 + (i % 5) * 0.1)] * (1 + (i % 3))
            )

    t1 = threading.Thread(target=writer_pose)
    t2 = threading.Thread(target=writer_det)
    snapshots = []

    def reader():
        for _ in range(n_iter):
            snapshots.append(bus.snapshot())

    t3 = threading.Thread(target=reader)
    for t in (t1, t2, t3):
        t.start()
    for t in (t1, t2, t3):
        t.join(timeout=10.0)
    # Every snapshot must be self-consistent
    for snap in snapshots:
        if snap.user_pose is not None:
            assert snap.user_pose.gesture in ("wave_right", "hands_up", None)
        for d in snap.head_detections:
            assert d.class_name == "person"


def test_robot_state_bus_round_trip():
    bus = RobotStateBus()
    assert bus.snapshot() is None
    assert bus.lowstate_age_s() == float("inf")
    state = RobotState(
        standing=True,
        gravity_proj_z=-0.95,
        base_ang_vel_xyz=(0.0, 0.0, 0.0),
        rl_policy_active=True,
        last_lowstate_age_s=0.05,
    )
    bus.update(state)
    s = bus.snapshot()
    assert s == state
    assert bus.lowstate_age_s() < 1.0
