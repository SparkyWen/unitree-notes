"""Shared data contracts for the perception → safety → skill pipeline.

These dataclasses are the ONLY thing other subsystems are allowed to read
from perception. Concrete fields here are stable; if a subsystem needs new
data, add it here first then implement on the producer side.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import math
import numpy as np


# ---------- Gesture labels (string enum) ------------------------------------

class GestureLabel:
    """String constants — kept as a class instead of enum so JSON serialization
    is trivial and matches the LLM tool schema enum verbatim."""
    WAVE_RIGHT = "wave_right"
    WAVE_LEFT = "wave_left"
    HANDS_UP = "hands_up"
    T_POSE = "t_pose"
    POINT_LEFT = "point_left"
    POINT_RIGHT = "point_right"
    STOP_PALM = "stop_palm"
    CROSSED_ARMS = "crossed_arms"

    ALL = (
        WAVE_RIGHT, WAVE_LEFT, HANDS_UP, T_POSE,
        POINT_LEFT, POINT_RIGHT, STOP_PALM, CROSSED_ARMS,
    )
    # Subset that the robot can mirror back via mock_imitate.
    MIRRORABLE = (WAVE_RIGHT, WAVE_LEFT, HANDS_UP, T_POSE)


# ---------- Vision: detected object / person --------------------------------

@dataclass(frozen=True)
class Detection:
    class_name: str
    bbox_xyxy: Tuple[float, float, float, float]   # pixels
    score: float                                    # 0..1
    distance_m: Optional[float] = None              # None if no depth
    bearing_deg: Optional[float] = None             # left negative, right positive
    pitch_deg: Optional[float] = None               # up positive, down negative
    source: str = "unknown"                         # 'usb' | 'head'


# ---------- Vision: human pose ----------------------------------------------

@dataclass(frozen=True)
class HumanPose:
    """MediaPipe BlazePose 33-landmark output + derived gesture label.

    `landmarks_xy`: shape (33, 2), normalized image coords [0, 1].
    `landmarks_z`: shape (33,), MediaPipe-style depth relative to hip midpoint.
    `visibility`: shape (33,), 0..1 per-landmark visibility score.
    """
    landmarks_xy: np.ndarray
    landmarks_z: np.ndarray
    visibility: np.ndarray
    gesture: Optional[str] = None
    gesture_confidence: float = 0.0
    source: str = "usb"


# ---------- Scene: ground / path constraint ---------------------------------

@dataclass(frozen=True)
class GroundConstraint:
    """Aggregated 'is it safe to step forward?' info from the head camera."""
    clear_path: bool
    nearest_obstacle_m: float       # inf if nothing in cone
    nearest_person_m: float         # inf if no person anywhere
    floor_visible_ratio: float      # 0..1, fraction of bottom-half pixels classified as floor
    surface_tilt_deg: float         # 0 = flat; >15 considered uneven


# ---------- Aggregated scene state ------------------------------------------

@dataclass
class SceneState:
    """The single object the SafetySupervisor reads.

    Mutability: the bus replaces the whole instance atomically; consumers MUST
    treat the returned snapshot as read-only.
    """
    # Per-source timestamps (time.monotonic())
    ts_usb: float = 0.0
    ts_head: float = 0.0
    ts_pose: float = 0.0
    ts_yolo_usb: float = 0.0
    ts_yolo_head: float = 0.0

    # USB camera (user-facing) results
    user_pose: Optional[HumanPose] = None
    user_detections: List[Detection] = field(default_factory=list)

    # MuJoCo / robot head camera results
    head_detections: List[Detection] = field(default_factory=list)
    ground: Optional[GroundConstraint] = None

    # Metadata
    usb_resolution: Tuple[int, int] = (0, 0)
    head_resolution: Tuple[int, int] = (0, 0)
    perception_warnings: List[str] = field(default_factory=list)

    def summary_for_llm(self) -> dict:
        """A compact dict the brain can attach to tool results / inject into prompts."""
        n_persons = sum(1 for d in self.head_detections if d.class_name == "person")
        if not self.head_detections:
            n_persons = sum(1 for d in self.user_detections if d.class_name == "person")
        ground = self.ground
        gesture = self.user_pose.gesture if self.user_pose else None
        gesture_conf = self.user_pose.gesture_confidence if self.user_pose else 0.0
        return {
            "persons_visible": n_persons,
            "nearest_obstacle_m": (
                round(ground.nearest_obstacle_m, 2)
                if ground and math.isfinite(ground.nearest_obstacle_m) else None
            ),
            "nearest_person_m": (
                round(ground.nearest_person_m, 2)
                if ground and math.isfinite(ground.nearest_person_m) else None
            ),
            "clear_path": ground.clear_path if ground else None,
            "surface_tilt_deg": round(ground.surface_tilt_deg, 1) if ground else None,
            "user_gesture": gesture if gesture_conf >= 0.5 else None,
            "user_gesture_confidence": round(gesture_conf, 2),
            "warnings": list(self.perception_warnings),
        }


# ---------- Robot state (lowstate-derived) ----------------------------------

@dataclass(frozen=True)
class RobotState:
    """Derived from rt/lowstate; what SafetySupervisor needs about the body.

    `gravity_proj_z`: z-component of the gravity vector projected into the
    body frame using the IMU quaternion. Standing upright -> ≈ -1.0;
    falling -> approaches 0; on its back -> +1.0. Threshold typically -0.85.
    """
    standing: bool
    gravity_proj_z: float
    base_ang_vel_xyz: Tuple[float, float, float]
    rl_policy_active: bool
    last_lowstate_age_s: float
    mode_machine: int = 0


# Re-export
__all__ = [
    "Detection",
    "HumanPose",
    "GroundConstraint",
    "SceneState",
    "RobotState",
    "GestureLabel",
]
