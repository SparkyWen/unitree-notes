"""Pure-Python unit tests for `g1_brain.perception.derivations`.

These must NOT import mujoco / mediapipe / ultralytics / cv2.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from g1_brain.perception.derivations import (
    bbox_to_bearing_pitch,
    classify_gesture,
    compute_ground_constraint,
    floor_visible_ratio,
)
from g1_brain.scene_state.types import GestureLabel


# ---------------------------------------------------------------------------
# Synthetic-landmark helpers
# ---------------------------------------------------------------------------

def _blank_landmarks() -> np.ndarray:
    """Default neutral pose: shoulders, hips, elbows, wrists in plausible spots."""
    xy = np.zeros((33, 2), dtype=np.float32)
    # Image-coords frame: x in [0,1] left->right, y in [0,1] top->bottom.
    # Standing-front-facing person, centered.
    xy[0] = (0.5, 0.18)        # NOSE
    xy[11] = (0.40, 0.32)      # LEFT_SHOULDER
    xy[12] = (0.60, 0.32)      # RIGHT_SHOULDER
    xy[13] = (0.36, 0.50)      # LEFT_ELBOW
    xy[14] = (0.64, 0.50)      # RIGHT_ELBOW
    xy[15] = (0.34, 0.66)      # LEFT_WRIST
    xy[16] = (0.66, 0.66)      # RIGHT_WRIST
    xy[23] = (0.43, 0.65)      # LEFT_HIP
    xy[24] = (0.57, 0.65)      # RIGHT_HIP
    xy[25] = (0.43, 0.85)      # LEFT_KNEE
    xy[26] = (0.57, 0.85)      # RIGHT_KNEE
    return xy


def _all_visible() -> np.ndarray:
    return np.ones((33,), dtype=np.float32)


# ---------------------------------------------------------------------------
# bbox_to_bearing_pitch
# ---------------------------------------------------------------------------

def test_center_bbox_is_zero_bearing():
    bx = (310, 230, 330, 250)  # 20x20 box centered in 640x480
    bearing, pitch = bbox_to_bearing_pitch(bx, (480, 640), 60.0, 45.0)
    assert abs(bearing) < 1e-3
    assert abs(pitch) < 1e-3


def test_right_bbox_positive_bearing():
    bx = (560, 230, 600, 250)
    bearing, pitch = bbox_to_bearing_pitch(bx, (480, 640), 60.0, 45.0)
    assert bearing > 5.0


def test_left_bbox_negative_bearing():
    bx = (40, 230, 80, 250)
    bearing, pitch = bbox_to_bearing_pitch(bx, (480, 640), 60.0, 45.0)
    assert bearing < -5.0


def test_top_bbox_positive_pitch():
    bx = (310, 20, 330, 60)
    bearing, pitch = bbox_to_bearing_pitch(bx, (480, 640), 60.0, 45.0)
    assert pitch > 5.0


def test_bottom_bbox_negative_pitch():
    bx = (310, 420, 330, 460)
    bearing, pitch = bbox_to_bearing_pitch(bx, (480, 640), 60.0, 45.0)
    assert pitch < -5.0


# ---------------------------------------------------------------------------
# compute_ground_constraint
# ---------------------------------------------------------------------------

def test_uniform_far_depth_is_clear():
    depth = np.full((48, 64), 2.0, dtype=np.float32)
    gc = compute_ground_constraint(depth, hfov_deg=60.0, vfov_deg=45.0)
    assert gc.clear_path is True
    # No reading inside [0.5, 1.5] band -> nearest_obstacle_m is +inf.
    assert math.isinf(gc.nearest_obstacle_m)
    assert gc.surface_tilt_deg < 5.0


def test_obstacle_blob_detected():
    depth = np.full((48, 64), 2.0, dtype=np.float32)
    # Obstacle blob right in front of the cone center, at 0.8m
    depth[24:32, 28:36] = 0.8
    gc = compute_ground_constraint(depth, hfov_deg=60.0, vfov_deg=45.0)
    assert math.isfinite(gc.nearest_obstacle_m)
    assert 0.7 <= gc.nearest_obstacle_m <= 0.9


def test_close_obstacle_blocks_path():
    # Close obstacle (< safe_clearance_m=0.6) should violate the 90% cleared
    # criterion, so clear_path goes False.
    depth = np.full((48, 64), 0.4, dtype=np.float32)
    gc = compute_ground_constraint(depth, hfov_deg=60.0, vfov_deg=45.0)
    assert gc.clear_path is False


def test_tilted_plane_detected():
    # Build a depth map that linearly increases along v (image y), simulating
    # a ground plane viewed at a glancing angle.
    h, w = 48, 64
    rows = np.linspace(0.5, 2.5, h, dtype=np.float32)
    depth = np.tile(rows[:, None], (1, w))
    gc = compute_ground_constraint(depth, hfov_deg=60.0, vfov_deg=45.0)
    assert gc.surface_tilt_deg > 5.0


def test_floor_visible_ratio_basic():
    depth = np.full((48, 64), 2.0, dtype=np.float32)
    r = floor_visible_ratio(depth, ground_z_threshold_m=1.5)
    assert r > 0.99
    depth_close = np.full((48, 64), 0.5, dtype=np.float32)
    r = floor_visible_ratio(depth_close, ground_z_threshold_m=1.5)
    assert r < 0.01


def test_empty_depth_returns_blocked():
    gc = compute_ground_constraint(
        np.zeros((0, 0), dtype=np.float32), hfov_deg=60.0, vfov_deg=45.0
    )
    assert gc.clear_path is False


# ---------------------------------------------------------------------------
# classify_gesture
# ---------------------------------------------------------------------------

def test_neutral_pose_no_gesture():
    xy = _blank_landmarks()
    vis = _all_visible()
    label, conf = classify_gesture(xy, vis)
    assert label is None


def test_wave_right():
    xy = _blank_landmarks()
    # Raise the user's right wrist (idx 16) up and outward
    xy[16] = (0.78, 0.10)
    xy[14] = (0.72, 0.20)
    label, conf = classify_gesture(xy, _all_visible())
    assert label == GestureLabel.WAVE_RIGHT
    assert conf > 0.5


def test_wave_left():
    xy = _blank_landmarks()
    xy[15] = (0.22, 0.10)
    xy[13] = (0.28, 0.20)
    label, conf = classify_gesture(xy, _all_visible())
    assert label == GestureLabel.WAVE_LEFT
    assert conf > 0.5


def test_hands_up():
    xy = _blank_landmarks()
    # Both wrists raised well above shoulders, kept laterally close to head.
    xy[15] = (0.42, 0.05)
    xy[16] = (0.58, 0.05)
    xy[13] = (0.40, 0.18)
    xy[14] = (0.60, 0.18)
    label, conf = classify_gesture(xy, _all_visible())
    assert label == GestureLabel.HANDS_UP
    assert conf > 0.5


def test_t_pose():
    xy = _blank_landmarks()
    # Wrists at shoulder height, far outside torso.
    xy[15] = (0.05, 0.32)
    xy[16] = (0.95, 0.32)
    xy[13] = (0.20, 0.32)
    xy[14] = (0.80, 0.32)
    label, conf = classify_gesture(xy, _all_visible())
    assert label == GestureLabel.T_POSE
    assert conf > 0.5


def test_point_right():
    xy = _blank_landmarks()
    # Right arm extended horizontally to image-right; left arm low/tucked.
    xy[16] = (0.95, 0.32)
    xy[14] = (0.80, 0.32)
    xy[15] = (0.41, 0.65)
    xy[13] = (0.40, 0.50)
    label, conf = classify_gesture(xy, _all_visible())
    assert label == GestureLabel.POINT_RIGHT
    assert conf > 0.5


def test_point_left():
    xy = _blank_landmarks()
    xy[15] = (0.05, 0.32)
    xy[13] = (0.20, 0.32)
    xy[16] = (0.59, 0.65)
    xy[14] = (0.60, 0.50)
    label, conf = classify_gesture(xy, _all_visible())
    assert label == GestureLabel.POINT_LEFT
    assert conf > 0.5


def test_stop_palm():
    xy = _blank_landmarks()
    # Right palm raised in front, elbow bent (elbow below wrist), wrist near
    # shoulder horizontally (palm centered in front of body).
    xy[16] = (0.62, 0.18)
    xy[14] = (0.62, 0.40)
    xy[15] = (0.41, 0.65)
    xy[13] = (0.40, 0.50)
    label, conf = classify_gesture(xy, _all_visible())
    assert label == GestureLabel.STOP_PALM
    assert conf > 0.5


def test_crossed_arms():
    xy = _blank_landmarks()
    # Both wrists at chest height, crossed past body midline.
    xy[15] = (0.62, 0.45)  # left wrist crosses to right side
    xy[13] = (0.45, 0.45)
    xy[16] = (0.38, 0.45)  # right wrist crosses to left side
    xy[14] = (0.55, 0.45)
    label, conf = classify_gesture(xy, _all_visible())
    assert label == GestureLabel.CROSSED_ARMS
    assert conf > 0.5


def test_low_visibility_returns_none():
    xy = _blank_landmarks()
    xy[16] = (0.78, 0.10)
    xy[14] = (0.72, 0.20)
    vis = _all_visible()
    vis[15] = 0.0
    vis[16] = 0.1
    vis[12] = 0.1
    label, conf = classify_gesture(xy, vis)
    assert label is None


def test_invalid_shape_returns_none():
    label, conf = classify_gesture(np.zeros((10, 2)), np.ones((10,)))
    assert label is None
    assert conf == 0.0
