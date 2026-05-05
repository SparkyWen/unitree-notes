"""纯函数派生量计算：手势分类、bbox→方位、地面/可行走约束。

These functions deliberately have NO side effects, no I/O, no network, no
GPU; they only depend on numpy. Unit tests can import this module without
touching MuJoCo, OpenCV, MediaPipe, or DDS.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

from ..scene_state.types import GroundConstraint, GestureLabel


# ---------------------------------------------------------------------------
# MediaPipe BlazePose 33-landmark canonical indices.
# ---------------------------------------------------------------------------
NOSE = 0
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_HIP = 23
RIGHT_HIP = 24


# =============================================================================
# bbox -> bearing / pitch
# =============================================================================

def bbox_to_bearing_pitch(
    bbox_xyxy: Sequence[float],
    image_shape: Tuple[int, int],
    hfov_deg: float,
    vfov_deg: float,
) -> Tuple[float, float]:
    """Map a bounding-box center to a (bearing_deg, pitch_deg) pair.

    Convention: image (0,0) is top-left, x grows rightward, y grows down.
    Bearing is positive for "to the right of the optical axis"; pitch is
    positive for "above the optical axis" (which is the OPPOSITE sign of
    image-y).
    """
    if len(image_shape) >= 2:
        h, w = int(image_shape[0]), int(image_shape[1])
    else:
        raise ValueError(f"image_shape must be (H, W[, C]); got {image_shape}")
    if w <= 0 or h <= 0:
        raise ValueError("image_shape must have positive width/height")

    x1, y1, x2, y2 = bbox_xyxy
    cx = 0.5 * (x1 + x2)
    cy = 0.5 * (y1 + y2)

    # Map pixel offset -> normalized angular fraction of the half FoV.
    nx = (cx - 0.5 * w) / (0.5 * w)
    ny = (cy - 0.5 * h) / (0.5 * h)
    bearing = nx * (hfov_deg * 0.5)
    pitch = -ny * (vfov_deg * 0.5)
    return float(bearing), float(pitch)


# =============================================================================
# ground constraint from a depth map
# =============================================================================

def floor_visible_ratio(depth_m: np.ndarray, ground_z_threshold_m: float = 1.5) -> float:
    """Fraction of the bottom-half of the image whose depth exceeds the
    `ground_z_threshold_m`. Used as a sanity check for "did we lose the ground"
    rather than as a primary planning signal.
    """
    if depth_m.ndim != 2 or depth_m.size == 0:
        return 0.0
    h = depth_m.shape[0]
    bottom = depth_m[h // 2 :, :]
    finite = np.isfinite(bottom)
    if not finite.any():
        return 0.0
    mask = finite & (bottom > ground_z_threshold_m)
    return float(mask.sum()) / float(finite.sum())


def _cone_mask(
    h: int, w: int, hfov_deg: float, vfov_deg: float, cone_half_angle_deg: float
) -> np.ndarray:
    """Return a (H, W) bool mask of pixels whose angular distance from the
    forward direction is within `cone_half_angle_deg` AND that lie in the
    lower 60% of the image (where the floor / near obstacles project).
    """
    ys = np.arange(h, dtype=np.float32)
    xs = np.arange(w, dtype=np.float32)
    nx = (xs - 0.5 * w) / (0.5 * w)
    ny = (ys - 0.5 * h) / (0.5 * h)
    bearing = nx * (hfov_deg * 0.5)
    pitch = -ny * (vfov_deg * 0.5)
    bearing2d, pitch2d = np.meshgrid(bearing, pitch)
    angular = np.sqrt(bearing2d ** 2 + pitch2d ** 2)
    in_cone = angular <= cone_half_angle_deg
    floor_band = np.zeros((h, w), dtype=bool)
    floor_band[int(h * 0.4) :, :] = True
    return in_cone & floor_band


def _surface_tilt_deg(depth_m: np.ndarray, mask: np.ndarray, hfov_deg: float) -> float:
    """Fit a plane to the masked depth pixels and return the angle between
    its normal and the camera's forward axis. Returns 0 if there are too
    few points to fit.
    """
    pts_idx = np.argwhere(mask & np.isfinite(depth_m))
    if pts_idx.shape[0] < 30:
        return 0.0
    h, w = depth_m.shape
    fx = 0.5 * w / math.tan(math.radians(hfov_deg) * 0.5)
    fy = fx
    z = depth_m[mask & np.isfinite(depth_m)]
    u = pts_idx[:, 1] - 0.5 * w
    v = pts_idx[:, 0] - 0.5 * h
    x = u * z / fx
    y = v * z / fy
    A = np.column_stack([x, y, np.ones_like(z)])
    try:
        coef, *_ = np.linalg.lstsq(A, z, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0
    normal = np.array([-coef[0], -coef[1], 1.0])
    normal /= np.linalg.norm(normal)
    forward = np.array([0.0, 0.0, 1.0])
    cos = float(np.clip(abs(np.dot(normal, forward)), 0.0, 1.0))
    return float(math.degrees(math.acos(cos)))


def compute_ground_constraint(
    depth_m: np.ndarray,
    hfov_deg: float,
    vfov_deg: float,
    cone_half_angle_deg: float = 15.0,
    min_dist_m: float = 0.5,
    max_dist_m: float = 1.5,
    safe_clearance_m: float = 0.6,
    nearest_person_m: float = float("inf"),
) -> GroundConstraint:
    """Implement §2.4.1 of the design doc.

    A 'clear path' means at least 90% of the cone-region pixels report a depth
    larger than `safe_clearance_m`. `nearest_obstacle_m` is the minimum depth
    inside the cone; +inf if the cone is empty.
    """
    if depth_m.ndim != 2 or depth_m.size == 0:
        return GroundConstraint(
            clear_path=False,
            nearest_obstacle_m=float("inf"),
            nearest_person_m=nearest_person_m,
            floor_visible_ratio=0.0,
            surface_tilt_deg=0.0,
        )
    h, w = depth_m.shape
    mask = _cone_mask(h, w, hfov_deg, vfov_deg, cone_half_angle_deg)
    finite = np.isfinite(depth_m)
    cone = mask & finite
    if not cone.any():
        return GroundConstraint(
            clear_path=False,
            nearest_obstacle_m=float("inf"),
            nearest_person_m=nearest_person_m,
            floor_visible_ratio=floor_visible_ratio(depth_m),
            surface_tilt_deg=0.0,
        )
    z = depth_m[cone]
    # Restrict to the planning band for "nearest obstacle" semantics; depths
    # beyond max_dist_m count as "free" regardless of the actual reading.
    in_band = z[(z >= min_dist_m) & (z <= max_dist_m)]
    nearest = float(in_band.min()) if in_band.size > 0 else float("inf")
    safe_pixels = float(np.sum(z > safe_clearance_m)) / float(z.size)
    clear = safe_pixels >= 0.9
    tilt = _surface_tilt_deg(depth_m, mask, hfov_deg)
    return GroundConstraint(
        clear_path=bool(clear),
        nearest_obstacle_m=nearest,
        nearest_person_m=nearest_person_m,
        floor_visible_ratio=floor_visible_ratio(depth_m),
        surface_tilt_deg=tilt,
    )


# =============================================================================
# gesture classification (geometric rules over MediaPipe landmarks)
# =============================================================================

def _vis_ok(visibility: np.ndarray, indices: Sequence[int], min_v: float = 0.5) -> bool:
    return bool(np.all(visibility[list(indices)] >= min_v))


def _shoulder_width(xy: np.ndarray) -> float:
    return float(abs(xy[LEFT_SHOULDER, 0] - xy[RIGHT_SHOULDER, 0])) + 1e-6


def _torso_height(xy: np.ndarray) -> float:
    """A reference vertical distance: shoulders -> hips midpoint."""
    sh_y = 0.5 * (xy[LEFT_SHOULDER, 1] + xy[RIGHT_SHOULDER, 1])
    hp_y = 0.5 * (xy[LEFT_HIP, 1] + xy[RIGHT_HIP, 1])
    return float(abs(hp_y - sh_y)) + 1e-6


def _saturate(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


def _score_wave(xy: np.ndarray, vis: np.ndarray, side: str) -> float:
    """Score for a one-arm wave on the given side ('left' / 'right').

    "right" means the user's right hand — which appears on the LEFT half of
    the mirrored selfie image (MediaPipe already mirrors). We just trust the
    landmark labels.
    """
    if side == "right":
        wrist = RIGHT_WRIST
        shoulder = RIGHT_SHOULDER
        other_wrist = LEFT_WRIST
        other_shoulder = LEFT_SHOULDER
    else:
        wrist = LEFT_WRIST
        shoulder = LEFT_SHOULDER
        other_wrist = RIGHT_WRIST
        other_shoulder = RIGHT_SHOULDER
    if not _vis_ok(vis, [wrist, shoulder, LEFT_HIP, RIGHT_HIP]):
        return 0.0
    sw = _shoulder_width(xy)
    th = _torso_height(xy)
    # wrist must be above shoulder
    rise = (xy[shoulder, 1] - xy[wrist, 1]) / th
    rise_score = _saturate((rise - 0.2) / 0.6)
    # wrist must extend laterally outside the shoulder
    lateral = abs(xy[wrist, 0] - xy[shoulder, 0]) / sw
    lat_score = _saturate((lateral - 0.3) / 0.7)
    # other arm should NOT also be raised (otherwise it's hands_up)
    other_rise = (xy[other_shoulder, 1] - xy[other_wrist, 1]) / th
    if other_rise > 0.5:
        return 0.0
    return float(0.5 * rise_score + 0.5 * lat_score)


def _score_hands_up(xy: np.ndarray, vis: np.ndarray) -> float:
    if not _vis_ok(vis, [LEFT_WRIST, RIGHT_WRIST, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]):
        return 0.0
    th = _torso_height(xy)
    l = (xy[LEFT_SHOULDER, 1] - xy[LEFT_WRIST, 1]) / th
    r = (xy[RIGHT_SHOULDER, 1] - xy[RIGHT_WRIST, 1]) / th
    return _saturate((min(l, r) - 0.3) / 0.7)


def _score_t_pose(xy: np.ndarray, vis: np.ndarray) -> float:
    if not _vis_ok(vis, [LEFT_WRIST, RIGHT_WRIST, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]):
        return 0.0
    sw = _shoulder_width(xy)
    th = _torso_height(xy)
    # both wrists roughly at shoulder height
    dy_l = abs(xy[LEFT_WRIST, 1] - xy[LEFT_SHOULDER, 1]) / th
    dy_r = abs(xy[RIGHT_WRIST, 1] - xy[RIGHT_SHOULDER, 1]) / th
    horiz_score = _saturate(1.0 - max(dy_l, dy_r) / 0.25)
    # both wrists laterally extended away from torso
    lat_l = (xy[LEFT_SHOULDER, 0] - xy[LEFT_WRIST, 0]) / sw
    lat_r = (xy[RIGHT_WRIST, 0] - xy[RIGHT_SHOULDER, 0]) / sw
    lat_score = _saturate((min(lat_l, lat_r) - 0.5) / 1.5)
    return float(0.5 * horiz_score + 0.5 * lat_score)


def _score_point(xy: np.ndarray, vis: np.ndarray, side: str) -> float:
    """Pointing: one arm extended horizontally outward, the other arm low.

    `side` is the direction the arm extends (the camera-frame direction):
      - 'point_right' = arm extending in the +x (right side of frame)
      - 'point_left'  = arm extending in the -x (left side of frame)
    """
    if side == "right":
        wrist = RIGHT_WRIST
        shoulder = RIGHT_SHOULDER
        other_wrist = LEFT_WRIST
        other_shoulder = LEFT_SHOULDER
        sign = +1.0
    else:
        wrist = LEFT_WRIST
        shoulder = LEFT_SHOULDER
        other_wrist = RIGHT_WRIST
        other_shoulder = RIGHT_SHOULDER
        sign = -1.0
    if not _vis_ok(vis, [wrist, shoulder, other_wrist, other_shoulder, LEFT_HIP, RIGHT_HIP]):
        return 0.0
    sw = _shoulder_width(xy)
    th = _torso_height(xy)
    # wrist must be near shoulder height (within +/- 0.25 torso) — arm horizontal
    dy = abs(xy[wrist, 1] - xy[shoulder, 1]) / th
    horiz = _saturate(1.0 - dy / 0.3)
    # wrist must be far outside the shoulder in the chosen direction
    dx = (xy[wrist, 0] - xy[shoulder, 0]) * sign / sw
    extend = _saturate((dx - 0.6) / 1.4)
    # other arm should be near body (low and close to other shoulder)
    other_dy = (xy[other_shoulder, 1] - xy[other_wrist, 1]) / th
    if other_dy > 0.2:
        return 0.0
    return float(0.5 * horiz + 0.5 * extend)


def _score_stop_palm(xy: np.ndarray, vis: np.ndarray) -> float:
    """One arm in front, elbow bent ~90°, wrist roughly head-height."""
    # Use right arm as canonical (handles left/right-handed by symmetry: we
    # accept whichever arm scores higher).
    best = 0.0
    for wrist, elbow, shoulder, other_wrist, other_shoulder in [
        (RIGHT_WRIST, RIGHT_ELBOW, RIGHT_SHOULDER, LEFT_WRIST, LEFT_SHOULDER),
        (LEFT_WRIST, LEFT_ELBOW, LEFT_SHOULDER, RIGHT_WRIST, RIGHT_SHOULDER),
    ]:
        if not _vis_ok(vis, [wrist, elbow, shoulder]):
            continue
        sw = _shoulder_width(xy)
        th = _torso_height(xy)
        # wrist is close to shoulder horizontally (palm is in front, not extended)
        dx = abs(xy[wrist, 0] - xy[shoulder, 0]) / sw
        center = _saturate(1.0 - dx / 0.6)
        # wrist at or above shoulder height
        rise = (xy[shoulder, 1] - xy[wrist, 1]) / th
        rise_score = _saturate((rise - 0.0) / 0.6)
        # elbow lower than wrist (palm raised)
        elbow_below = (xy[elbow, 1] - xy[wrist, 1]) / th
        elbow_score = _saturate((elbow_below - 0.05) / 0.4)
        # other arm not raised
        other_rise = (xy[other_shoulder, 1] - xy[other_wrist, 1]) / th
        if other_rise > 0.5:
            continue
        s = 0.4 * center + 0.3 * rise_score + 0.3 * elbow_score
        if s > best:
            best = s
    return float(best)


def _score_crossed_arms(xy: np.ndarray, vis: np.ndarray) -> float:
    if not _vis_ok(vis, [LEFT_WRIST, RIGHT_WRIST, LEFT_SHOULDER, RIGHT_SHOULDER]):
        return 0.0
    sw = _shoulder_width(xy)
    th = _torso_height(xy)
    body_mid = 0.5 * (xy[LEFT_SHOULDER, 0] + xy[RIGHT_SHOULDER, 0])
    # left wrist crossed to the right side, right wrist crossed to the left side
    left_cross = (xy[LEFT_WRIST, 0] - body_mid) / sw
    right_cross = (body_mid - xy[RIGHT_WRIST, 0]) / sw
    cross_score = _saturate((min(left_cross, right_cross) - 0.0) / 0.5)
    # wrists roughly chest height (between shoulders and hips)
    sh_y = 0.5 * (xy[LEFT_SHOULDER, 1] + xy[RIGHT_SHOULDER, 1])
    hp_y = 0.5 * (xy[LEFT_HIP, 1] + xy[RIGHT_HIP, 1])
    chest_band_top = sh_y - 0.1 * th
    chest_band_bot = hp_y + 0.1 * th
    height_ok = (
        chest_band_top <= xy[LEFT_WRIST, 1] <= chest_band_bot
        and chest_band_top <= xy[RIGHT_WRIST, 1] <= chest_band_bot
    )
    return float(cross_score if height_ok else 0.5 * cross_score)


_GESTURE_SCORERS = (
    (GestureLabel.WAVE_RIGHT, lambda xy, v: _score_wave(xy, v, "right")),
    (GestureLabel.WAVE_LEFT, lambda xy, v: _score_wave(xy, v, "left")),
    (GestureLabel.HANDS_UP, _score_hands_up),
    (GestureLabel.T_POSE, _score_t_pose),
    (GestureLabel.POINT_RIGHT, lambda xy, v: _score_point(xy, v, "right")),
    (GestureLabel.POINT_LEFT, lambda xy, v: _score_point(xy, v, "left")),
    (GestureLabel.STOP_PALM, _score_stop_palm),
    (GestureLabel.CROSSED_ARMS, _score_crossed_arms),
)


def classify_gesture(
    landmarks_xy: np.ndarray,
    visibility: np.ndarray,
    min_confidence: float = 0.5,
) -> Tuple[Optional[str], float]:
    """Score every candidate gesture and return the best (label, conf).

    Returns (None, best_score) when the best score is below `min_confidence`.
    `landmarks_xy` is shape (33, 2) in normalized image coords; `visibility`
    is shape (33,).
    """
    if landmarks_xy.shape != (33, 2) or visibility.shape != (33,):
        return None, 0.0
    best_label: Optional[str] = None
    best_score = 0.0
    # Hands-up dominates wave when both arms are raised; we evaluate every
    # rule and pick the argmax above threshold.
    for label, scorer in _GESTURE_SCORERS:
        s = float(scorer(landmarks_xy, visibility))
        if s > best_score:
            best_label = label
            best_score = s
    if best_score < min_confidence:
        return None, best_score
    return best_label, best_score


__all__ = [
    "bbox_to_bearing_pitch",
    "compute_ground_constraint",
    "floor_visible_ratio",
    "classify_gesture",
]
