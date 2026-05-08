"""Convert g1_sim_keyboard's arm-only static poses into ComboController-safe
ArmActions.

g1_sim_keyboard ships 11 static poses; ComboController already exposes 8 of
them as RL-policy-tolerant gestures. The two remaining arm-only poses
(`salute_pose`, `hug_pose`) are not in ComboController, so we build them
here. The other 3 (bow / lean / squat / kick / lift_knee / twist) move the
waist or legs, which would corrupt `projected_gravity` and crash the RL
policy — they're intentionally NOT exposed as gestures (see plan §4.2).

These poses are absolute 23-D joint targets. We clamp the arm slice to
the physical joint limits (matching `ComboController.ARM_JOINT_LIMITS`)
before queuing — that's the only structural safety net we still need
because ComboController masks the arm slice of the policy observation
while a gesture is active, eliminating the OOD-on-legs risk that the
older `default ± K*action_scale` envelope used to guard against. If a
joint gets clipped against the physical limit we log a one-line warning
so the gesture's visual fidelity loss is visible, but we never panic.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np

log = logging.getLogger(__name__)


# 23-DOF joint indices (must match g1_sim_rl_combo.J).
# We hardcode the ones we need so this file doesn't need to import the heavy
# combo module at import time.
ARM_START = 13
ARM_END = 23
ARM_DIM = ARM_END - ARM_START   # 10

_LEFT_SHOULDER_PITCH  = 13
_LEFT_SHOULDER_ROLL   = 14
_LEFT_ELBOW           = 16
_RIGHT_SHOULDER_PITCH = 18
_RIGHT_SHOULDER_ROLL  = 19
_RIGHT_ELBOW          = 21


# ---- Pose extraction -----

def _salute_pose_23d() -> np.ndarray:
    """23-D absolute joint target for the salute pose."""
    p = np.zeros(23, dtype=np.float64)
    p[_RIGHT_SHOULDER_PITCH] = -0.6
    p[_RIGHT_SHOULDER_ROLL]  = -0.4
    p[_RIGHT_ELBOW]          =  1.55
    return p


def _hug_pose_23d() -> np.ndarray:
    """23-D absolute joint target for the hug pose."""
    p = np.zeros(23, dtype=np.float64)
    p[_LEFT_SHOULDER_PITCH]  = -0.8
    p[_LEFT_SHOULDER_ROLL]   =  0.6
    p[_LEFT_ELBOW]           =  1.5
    p[_RIGHT_SHOULDER_PITCH] = -0.8
    p[_RIGHT_SHOULDER_ROLL]  = -0.6
    p[_RIGHT_ELBOW]          =  1.5
    return p


# ---- ArmAction container --------------------------------------------------

@dataclass
class ArmAction:
    """Same shape as g1_sim_rl_combo.ArmAction so SkillServer can treat
    pre-built combo actions and these extras uniformly."""
    key: str
    name: str
    keyframes: List[Tuple[float, np.ndarray]]


# Per-arm-joint physical limits (rad). Mirrors
# `ComboController.ARM_JOINT_LIMITS` (g1_sim_rl_combo.py). Kept locally
# so this module doesn't have to import the heavy combo module at import
# time. Indices 0..9 correspond to ARM_START..ARM_START+9.
_ARM_JOINT_LIMITS: Tuple[Tuple[float, float], ...] = (
    (-3.05, 2.65),   # 13 LeftShoulderPitch
    (-1.55, 2.20),   # 14 LeftShoulderRoll
    (-2.55, 2.55),   # 15 LeftShoulderYaw
    (-1.00, 2.05),   # 16 LeftElbow
    (-1.95, 1.95),   # 17 LeftWristRoll
    (-3.05, 2.65),   # 18 RightShoulderPitch
    (-2.20, 1.55),   # 19 RightShoulderRoll
    (-2.55, 2.55),   # 20 RightShoulderYaw
    (-1.00, 2.05),   # 21 RightElbow
    (-1.95, 1.95),   # 22 RightWristRoll
)
_ARM_LIMIT_LO = np.array([lo for (lo, _) in _ARM_JOINT_LIMITS], dtype=np.float64)
_ARM_LIMIT_HI = np.array([hi for (_, hi) in _ARM_JOINT_LIMITS], dtype=np.float64)


def _clamp_to_envelope(
    arm_pose_10d: np.ndarray,
    arm_offset: np.ndarray,  # noqa: ARG001 — kept for API stability
    arm_scale: np.ndarray,   # noqa: ARG001 — kept for API stability
    *,
    k: float = 2.0,          # noqa: ARG001 — kept for API stability
    label: str = "",
) -> np.ndarray:
    """Clamp a 10-D arm pose to the physical joint limits.

    Earlier this clamped to ``arm_offset ± k * arm_scale``, an envelope
    derived from the policy's training distribution. That envelope was
    too tight (for example salute's shoulder_pitch=-0.6 was clipped to
    -0.53 with k=2.0, hug's -0.8 was clipped to -0.53 — both poses lost
    their character). The OOD risk that envelope guarded against is now
    eliminated by `ComboController._build_obs` masking the arm slice of
    the policy observation while a gesture is active, so we only need
    to enforce the physical limits here.

    The signature is preserved for backward compatibility; arm_offset,
    arm_scale, and k are no longer used.
    """
    clipped = np.clip(arm_pose_10d, _ARM_LIMIT_LO, _ARM_LIMIT_HI)
    if not np.allclose(clipped, arm_pose_10d, atol=1e-6):
        violations = np.where(~np.isclose(clipped, arm_pose_10d, atol=1e-6))[0]
        log.warning(
            "[keyframe_extras] %s: clipped %d arm joints to physical limit "
            "(idx %s; abs deltas %s)",
            label or "unnamed",
            len(violations),
            violations.tolist(),
            np.round(np.abs(arm_pose_10d - clipped)[violations], 3).tolist(),
        )
    return clipped


def _build_action(
    name: str,
    pose_23d: np.ndarray,
    arm_rest: np.ndarray,
    arm_offset: np.ndarray,
    arm_scale: np.ndarray,
    *,
    blend_in: float = 1.4,
    hold: float = 1.2,
    blend_out: float = 1.4,
) -> ArmAction:
    """Slice arms 13..22 out of a 23-D pose, clamp to safe envelope, and
    wrap into a 3-keyframe ArmAction (blend-in → hold → return-to-rest)."""
    arm_target = pose_23d[ARM_START:ARM_END].copy()
    arm_target = _clamp_to_envelope(
        arm_target, arm_offset, arm_scale, label=name,
    )
    return ArmAction(
        key=name,           # extras keyed by name; combo's are keyed "1".."8"
        name=name,
        keyframes=[
            (float(blend_in),  arm_target.copy()),
            (float(hold),      arm_target.copy()),
            (float(blend_out), arm_rest.copy()),
        ],
    )


# ---- Public builder --------------------------------------------------------

def build_extra_arm_actions(
    arm_rest: np.ndarray,
    arm_scale: np.ndarray,
    arm_offset: np.ndarray,
) -> List[ArmAction]:
    """Build the 2 arm-only extras (salute, hug) not present in
    `g1_sim_rl_combo.build_arm_actions()`.

    Same shape and conventions as build_arm_actions: each ArmAction is a
    list of (duration_s, arm_pose_10d) keyframes; the final keyframe
    returns to ``arm_rest`` so the RL policy regains the arms cleanly.

    Parameters
    ----------
    arm_rest, arm_scale, arm_offset
        10-D vectors taken from a live ComboController instance
        (``ctl.arm_rest``, ``ctl.arm_scale``, ``ctl.arm_offset``).
    """
    if arm_rest.shape != (ARM_DIM,):
        raise ValueError(f"arm_rest must be ({ARM_DIM},), got {arm_rest.shape}")
    if arm_scale.shape != (ARM_DIM,):
        raise ValueError(f"arm_scale must be ({ARM_DIM},), got {arm_scale.shape}")
    if arm_offset.shape != (ARM_DIM,):
        raise ValueError(f"arm_offset must be ({ARM_DIM},), got {arm_offset.shape}")

    return [
        _build_action(
            "salute", _salute_pose_23d(),
            arm_rest, arm_offset, arm_scale,
            blend_in=1.2, hold=1.2, blend_out=1.2,
        ),
        _build_action(
            "hug", _hug_pose_23d(),
            arm_rest, arm_offset, arm_scale,
            blend_in=1.4, hold=1.0, blend_out=1.4,
        ),
    ]


__all__ = [
    "ArmAction",
    "build_extra_arm_actions",
    "ARM_START",
    "ARM_END",
    "ARM_DIM",
]
