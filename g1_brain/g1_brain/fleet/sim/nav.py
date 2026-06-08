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
                k_yaw: float = 1.5, slow_yaw_deg: float = 60.0,
                slow_radius: float = 0.8,
                obstacles=(), peer: Tuple[float, float] = None,
                avoid_radius: float = 0.9, k_avoid: float = 0.9
                ) -> Tuple[float, float, float]:
    x, y, yaw = pose
    gx, gy = goal
    ex, ey = gx - x, gy - y
    dist = math.hypot(ex, ey)
    if dist < stop_radius:
        return (0.0, 0.0, 0.0)
    gxn, gyn = ex / dist, ey / dist                 # unit goal direction
    # goal pull: full speed far away, eased within slow_radius
    approach = min(1.0, dist / slow_radius)
    des_x, des_y = approach * gxn, approach * gyn

    # reactive repulsion from obstacle circles (+ optional peer as a moving one)
    obs = list(obstacles)
    if peer is not None:
        obs = obs + [(peer[0], peer[1], 0.45)]
    for ox, oy, orad in obs:
        dx, dy = x - ox, y - oy                      # obstacle -> robot
        d = math.hypot(dx, dy)
        reach = avoid_radius + orad
        if 1e-6 < d < reach:
            w = k_avoid * (reach - d) / reach
            ux, uy = dx / d, dy / d                  # radial push (away)
            des_x += w * ux
            des_y += w * uy
            # tangential bias to escape head-on local minima: only when the
            # obstacle is roughly ahead toward the goal
            ahead = (-ux) * gxn + (-uy) * gyn
            if ahead > 0.3:
                cross = gxn * (-uy) - gyn * (-ux)
                sgn = 1.0 if cross >= 0 else -1.0
                des_x += 0.8 * w * (-uy) * sgn
                des_y += 0.8 * w * (ux) * sgn

    heading_err = math.atan2(des_y, des_x) - yaw
    heading_err = math.atan2(math.sin(heading_err), math.cos(heading_err))
    wz = _clip(k_yaw * heading_err, *RANGES["wz"])
    c, s = math.cos(-yaw), math.sin(-yaw)
    e_fwd = c * des_x - s * des_y
    e_lat = s * des_x + c * des_y
    facing = max(0.0, math.cos(heading_err))
    if abs(math.degrees(heading_err)) > slow_yaw_deg:
        facing = 0.0
    vx = _clip(k_fwd * e_fwd * facing, *RANGES["vx"])
    vy = _clip(k_lat * e_lat * facing, *RANGES["vy"])
    return (vx, vy, wz)
