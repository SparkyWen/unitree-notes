"""G1 29-DoF default pose / PD gains / joint indices (no MuJoCo dependency).

Copied from unitree_rl_mjlab/.../velocity/v0/params/deploy.yaml — identical to
the GUI sim's config.py default-hold so the held pose is in-distribution.
"""
from __future__ import annotations

G1_DEFAULT_JOINT_POS = [
    -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
    -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
    0.0, 0.0, 0.0,
    0.35, 0.18, 0.0, 0.87, 0.0, 0.0, 0.0,
    0.35, -0.18, 0.0, 0.87, 0.0, 0.0, 0.0,
]
G1_DEFAULT_KP = [
    40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
    40.2, 99.1, 40.2, 99.1, 28.5, 28.5,
    40.2, 28.5, 28.5,
    14.3, 14.3, 14.3, 14.3, 14.3, 16.8, 16.8,
    14.3, 14.3, 14.3, 14.3, 14.3, 16.8, 16.8,
]
G1_DEFAULT_KD = [
    2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
    2.6, 6.3, 2.6, 6.3, 1.8, 1.8,
    2.6, 1.8, 1.8,
    0.9, 0.9, 0.9, 0.9, 0.9, 1.1, 1.1,
    0.9, 0.9, 0.9, 0.9, 0.9, 1.1, 1.1,
]

# 29-DoF joint indices of interest (legs, waist, left arm, right arm).
KNEE_L, KNEE_R = 3, 9
HIP_PITCH_L, HIP_PITCH_R = 0, 6
SH_PITCH_L, SH_PITCH_R = 15, 22
ELBOW_L, ELBOW_R = 18, 25


def gravity_proj_z_from_quat(quat) -> float:
    """z-component of gravity in the body frame from a [w,x,y,z] quaternion.
    -1.0 when upright. R[2,2] = 1 - 2(x^2+y^2); g_body_z = -R[2,2]."""
    x, y = float(quat[1]), float(quat[2])
    return 2.0 * (x * x + y * y) - 1.0
