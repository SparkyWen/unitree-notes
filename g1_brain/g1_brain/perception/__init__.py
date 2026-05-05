"""Fast Reflex perception layer (cameras + YOLO + MediaPipe + depth).

Importing this package triggers ONLY light imports; heavy deps (mujoco,
ultralytics, mediapipe, transformers) are loaded inside the relevant class
constructors so unit tests of `derivations.py` stay GPU-free.
"""
from .derivations import (
    bbox_to_bearing_pitch,
    classify_gesture,
    compute_ground_constraint,
    floor_visible_ratio,
)

__all__ = [
    "bbox_to_bearing_pitch",
    "classify_gesture",
    "compute_ground_constraint",
    "floor_visible_ratio",
]
