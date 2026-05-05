"""Thread-safe buses that perception writes to and safety/brain read from.

Design:
- Producers (camera threads, YOLO thread, pose thread) call `update_*()`
  with the freshest piece of data they own.
- Consumers (SafetySupervisor.validate, SkillServer per-step check, Brain
  scene_summary tool) call `snapshot()` and treat the result as read-only.
- We rebuild the SceneState dataclass on every snapshot so consumers can
  hand the snapshot to async coroutines without worrying about live mutation.
"""
from __future__ import annotations

import threading
import time
from typing import Optional, List

from .types import (
    SceneState,
    RobotState,
    Detection,
    HumanPose,
    GroundConstraint,
)


class SceneStateBus:
    """Thread-safe accumulator of perception sub-results into one SceneState."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._user_pose: Optional[HumanPose] = None
        self._user_detections: List[Detection] = []
        self._head_detections: List[Detection] = []
        self._ground: Optional[GroundConstraint] = None
        self._ts_usb: float = 0.0
        self._ts_head: float = 0.0
        self._ts_pose: float = 0.0
        self._ts_yolo_usb: float = 0.0
        self._ts_yolo_head: float = 0.0
        self._usb_res: tuple = (0, 0)
        self._head_res: tuple = (0, 0)
        self._warnings: List[str] = []

    # ---------- producer-side updates ----------

    def update_usb_frame(self, *, ts: float, resolution: tuple) -> None:
        with self._lock:
            self._ts_usb = ts
            self._usb_res = resolution

    def update_head_frame(self, *, ts: float, resolution: tuple) -> None:
        with self._lock:
            self._ts_head = ts
            self._head_res = resolution

    def update_user_pose(self, pose: Optional[HumanPose], ts: Optional[float] = None) -> None:
        with self._lock:
            self._user_pose = pose
            if ts is not None:
                self._ts_pose = ts

    def update_user_detections(self, dets: List[Detection], ts: Optional[float] = None) -> None:
        with self._lock:
            self._user_detections = list(dets)
            if ts is not None:
                self._ts_yolo_usb = ts

    def update_head_detections(self, dets: List[Detection], ts: Optional[float] = None) -> None:
        with self._lock:
            self._head_detections = list(dets)
            if ts is not None:
                self._ts_yolo_head = ts

    def update_ground(self, ground: Optional[GroundConstraint]) -> None:
        with self._lock:
            self._ground = ground

    def add_warning(self, w: str) -> None:
        with self._lock:
            if w not in self._warnings:
                self._warnings.append(w)

    def clear_warning(self, w: str) -> None:
        with self._lock:
            try:
                self._warnings.remove(w)
            except ValueError:
                pass

    # ---------- consumer-side snapshots ----------

    def snapshot(self) -> SceneState:
        with self._lock:
            return SceneState(
                ts_usb=self._ts_usb,
                ts_head=self._ts_head,
                ts_pose=self._ts_pose,
                ts_yolo_usb=self._ts_yolo_usb,
                ts_yolo_head=self._ts_yolo_head,
                user_pose=self._user_pose,
                user_detections=list(self._user_detections),
                head_detections=list(self._head_detections),
                ground=self._ground,
                usb_resolution=self._usb_res,
                head_resolution=self._head_res,
                perception_warnings=list(self._warnings),
            )

    # ---------- watchdog hooks ----------

    def usb_frame_age_s(self, now: Optional[float] = None) -> float:
        now = time.monotonic() if now is None else now
        with self._lock:
            return float("inf") if self._ts_usb <= 0 else now - self._ts_usb

    def head_frame_age_s(self, now: Optional[float] = None) -> float:
        now = time.monotonic() if now is None else now
        with self._lock:
            return float("inf") if self._ts_head <= 0 else now - self._ts_head


class RobotStateBus:
    """Mirror of the latest derived RobotState. Producer is the lowstate listener."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: Optional[RobotState] = None
        self._last_update_s: float = 0.0

    def update(self, state: RobotState) -> None:
        with self._lock:
            self._state = state
            self._last_update_s = time.monotonic()

    def snapshot(self) -> Optional[RobotState]:
        with self._lock:
            return self._state

    def lowstate_age_s(self, now: Optional[float] = None) -> float:
        now = time.monotonic() if now is None else now
        with self._lock:
            return float("inf") if self._last_update_s <= 0 else now - self._last_update_s
