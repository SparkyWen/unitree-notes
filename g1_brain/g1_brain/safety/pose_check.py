"""Pose / IMU sanity helpers used by the SafetySupervisor.

The reference implementation lives in
``g1_sim_demo.g1_sim_rl_combo.quat_rotate_inverse``; we mirror it here as
a tiny pure-numpy helper so the safety package has zero dependency on
g1_sim_demo (which pulls in DDS + the policy).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np


_GRAVITY_W = np.array([0.0, 0.0, -1.0], dtype=np.float64)


def quat_rotate_inverse(quat_wxyz: Sequence[float], v_world: Sequence[float]) -> np.ndarray:
    """Rotate ``v_world`` into body frame using IMU quaternion ``[w,x,y,z]``.

    Mirrors :func:`g1_sim_demo.g1_sim_rl_combo.quat_rotate_inverse` exactly.
    """
    w, x, y, z = (float(v) for v in quat_wxyz)
    vx, vy, vz = (float(v) for v in v_world)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    rx = vx - w * tx + (y * tz - z * ty)
    ry = vy - w * ty + (z * tx - x * tz)
    rz = vz - w * tz + (x * ty - y * tx)
    return np.array([rx, ry, rz], dtype=np.float64)


def gravity_proj_z_from_quat(quat_wxyz: Sequence[float]) -> float:
    """Return the z-component of gravity rotated into the body frame.

    Standing upright -> ≈ -1.0 ; lying on back -> +1.0 ; on side -> ≈ 0.
    Returns NaN-safe float (-1.0 if quaternion is degenerate).
    """
    q = np.asarray(quat_wxyz, dtype=np.float64)
    if q.shape != (4,) or float(np.linalg.norm(q)) < 1e-6:
        # Degenerate quaternion — assume upright (consistent with combo).
        return -1.0
    g_body = quat_rotate_inverse(q, _GRAVITY_W)
    return float(g_body[2])


def is_upright(quat_wxyz: Sequence[float], threshold: float = -0.85) -> bool:
    """True iff the body is upright enough.

    ``gravity_proj_z`` is negative for "feet down". A more-negative value
    means more upright. Returns True iff ``gravity_proj_z <= threshold``
    (i.e. the body is at least ``acos(|threshold|)`` from horizontal — for
    -0.85 that is ~31.8 deg from vertical).
    """
    return gravity_proj_z_from_quat(quat_wxyz) <= threshold


__all__ = [
    "gravity_proj_z_from_quat",
    "is_upright",
    "quat_rotate_inverse",
]
