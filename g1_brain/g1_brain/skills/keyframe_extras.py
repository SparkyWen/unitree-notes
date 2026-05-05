"""Convert g1_sim_keyboard's arm-only static poses into ComboController-safe
ArmActions.

g1_sim_keyboard ships 11 static poses; ComboController already exposes 8 of
them as RL-policy-tolerant gestures. The two remaining arm-only poses
(`salute_pose`, `hug_pose`) are not in ComboController, so we build them
here. The other 3 (bow / lean / squat / kick / lift_knee / twist) move the
waist or legs, which would corrupt `projected_gravity` and crash the RL
policy — they're intentionally NOT exposed as gestures (see plan §4.2).

The poses in g1_sim_keyboard are absolute 29-D joint targets relative to
the URDF zero pose. ComboController's gesture envelope is
``arm_offset ± ARM_GESTURE_K * arm_scale``; absolute poses authored
without knowing that envelope can violate it (most notably salute's
shoulder_pitch=-0.6 with default offset 0.35 lands at a 0.95-rad delta,
~2.2× scale on shoulder_pitch — outside the envelope). We always run the
slice through `_clamp_arm_to_safe_envelope` before queueing; if a joint
gets clipped we log a one-line warning so the gesture's visual fidelity
loss is visible, but we never panic.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np

log = logging.getLogger(__name__)


# 29-DOF joint indices (must match g1_sim_keyboard.J / g1_sim_rl_combo.J).
# We hardcode the 4 we need so this file doesn't need to import the heavy
# combo / keyboard modules at import time.
ARM_START = 15
ARM_END = 29
ARM_DIM = ARM_END - ARM_START   # 14

_LEFT_SHOULDER_PITCH  = 15
_LEFT_SHOULDER_ROLL   = 16
_LEFT_ELBOW           = 18
_RIGHT_SHOULDER_PITCH = 22
_RIGHT_SHOULDER_ROLL  = 23
_RIGHT_ELBOW          = 25
_RIGHT_WRIST_PITCH    = 27


# ---- Pose extraction (mirrors g1_sim_keyboard.salute_pose / hug_pose) -----

def _salute_pose_29d() -> np.ndarray:
    """29-D absolute joint target for the salute pose, mirroring
    g1_sim_keyboard.salute_pose() exactly. Hardcoded to avoid importing
    the keyboard module (which has its own DDS side effects)."""
    p = np.zeros(29, dtype=np.float64)
    p[_RIGHT_SHOULDER_PITCH] = -0.6
    p[_RIGHT_SHOULDER_ROLL]  = -0.4
    p[_RIGHT_ELBOW]          =  1.55
    p[_RIGHT_WRIST_PITCH]    = -0.3
    return p


def _hug_pose_29d() -> np.ndarray:
    """29-D absolute joint target for the hug pose, mirroring
    g1_sim_keyboard.hug_pose() exactly."""
    p = np.zeros(29, dtype=np.float64)
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


def _clamp_to_envelope(
    arm_pose_14d: np.ndarray,
    arm_offset: np.ndarray,
    arm_scale: np.ndarray,
    *,
    k: float = 2.0,
    label: str = "",
) -> np.ndarray:
    """Clamp a 14-D arm pose to ``arm_offset ± k * arm_scale``.

    Mirrors `ComboController._clamp_arm_to_safe_envelope` exactly (same
    K=2.0). Logs a single warning if any joint is actually clipped.
    """
    lo = arm_offset - k * arm_scale
    hi = arm_offset + k * arm_scale
    clipped = np.clip(arm_pose_14d, lo, hi)
    if not np.allclose(clipped, arm_pose_14d, atol=1e-6):
        violations = np.where(~np.isclose(clipped, arm_pose_14d, atol=1e-6))[0]
        log.warning(
            "[keyframe_extras] %s: clipped %d arm joints to envelope "
            "(idx %s; abs deltas %s)",
            label or "unnamed",
            len(violations),
            violations.tolist(),
            np.round(np.abs(arm_pose_14d - clipped)[violations], 3).tolist(),
        )
    return clipped


def _build_action(
    name: str,
    pose_29d: np.ndarray,
    arm_rest: np.ndarray,
    arm_offset: np.ndarray,
    arm_scale: np.ndarray,
    *,
    blend_in: float = 1.4,
    hold: float = 1.2,
    blend_out: float = 1.4,
) -> ArmAction:
    """Slice arms 15..28 out of a 29-D pose, clamp to safe envelope, and
    wrap into a 3-keyframe ArmAction (blend-in → hold → return-to-rest)."""
    arm_target = pose_29d[ARM_START:ARM_END].copy()
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
    list of (duration_s, arm_pose_14d) keyframes; the final keyframe
    returns to ``arm_rest`` so the RL policy regains the arms cleanly.

    Parameters
    ----------
    arm_rest, arm_scale, arm_offset
        14-D vectors taken from a live ComboController instance
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
            "salute", _salute_pose_29d(),
            arm_rest, arm_offset, arm_scale,
            blend_in=1.2, hold=1.2, blend_out=1.2,
        ),
        _build_action(
            "hug", _hug_pose_29d(),
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
