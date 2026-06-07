"""Position->velocity navigation outer loop for the RL velocity policy.

Converts (current pose, goal xy) into a body-frame velocity command
[vx, vy, wz], clamped to the policy's trained command ranges so we never
drive the gait policy out of distribution."""
from __future__ import annotations

import math
from typing import Tuple

RANGES = {"vx": (-0.5, 1.0), "vy": (-0.5, 0.5), "wz": (-1.0, 1.0)}


def _clip(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def nav_command(pose: Tuple[float, float, float], goal: Tuple[float, float], *,
                stop_radius: float = 0.25, k_fwd: float = 1.2, k_lat: float = 1.2,
                k_yaw: float = 1.5, slow_yaw_deg: float = 60.0) -> Tuple[float, float, float]:
    x, y, yaw = pose
    gx, gy = goal
    ex, ey = gx - x, gy - y
    dist = math.hypot(ex, ey)
    if dist < stop_radius:
        return (0.0, 0.0, 0.0)
    # error in body frame
    c, s = math.cos(-yaw), math.sin(-yaw)
    e_fwd = c * ex - s * ey
    e_lat = s * ex + c * ey
    heading_err = math.atan2(ey, ex) - yaw
    heading_err = math.atan2(math.sin(heading_err), math.cos(heading_err))  # wrap
    wz = _clip(k_yaw * heading_err, *RANGES["wz"])
    # don't barrel forward until roughly facing the goal
    facing = max(0.0, math.cos(heading_err))
    if abs(math.degrees(heading_err)) > slow_yaw_deg:
        facing = 0.0
    vx = _clip(k_fwd * e_fwd * facing, *RANGES["vx"])
    vy = _clip(k_lat * e_lat * facing, *RANGES["vy"])
    return (vx, vy, wz)
