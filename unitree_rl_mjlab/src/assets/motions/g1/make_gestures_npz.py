"""Generate gestures.npz for Unitree-G1-Flat-Arm-Disturbance training.

Samples each LLM-callable gesture at `--fps` Hz by linearly interpolating
the keyframe sequences from `g1_sim_rl_combo.build_arm_actions()` and
`keyframe_extras.build_extra_arm_actions()`.  The arm rest position is read
from the velocity/v0 deploy.yaml so the gesture trajectories are in the same
absolute joint-space as the RL environment.

Output:
  gestures.npz
    arm_qpos  float32  [N_g, T_max, 14]  absolute arm joint positions (rad)
    lengths   int32    [N_g]             valid frames per gesture
    names     object   [N_g]             gesture name strings (GESTURE_NAMES order)

Usage (run from the unitree_rl_mjlab/ directory, or anywhere with the repo on
PYTHONPATH):

    source ~/unitree_sdk2_python/unitree-env/bin/activate
    cd ~/unitree-notes/unitree_rl_mjlab
    python src/assets/motions/g1/make_gestures_npz.py \\
        --out src/assets/motions/g1/gestures.npz \\
        --fps 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import yaml

# ── Path setup ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent.parent.parent.parent  # .../unitree-notes
sys.path.insert(0, str(_REPO_ROOT / "g1_sim_demo"))
sys.path.insert(0, str(_REPO_ROOT / "g1_brain"))

from g1_sim_rl_combo import (  # noqa: E402
    ARM_START, ARM_END,
    build_arm_actions,
)
from g1_brain.skills.keyframe_extras import build_extra_arm_actions  # noqa: E402
from g1_brain.skills.tool_schemas import GESTURE_NAMES  # noqa: E402

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEPLOY_YAML = (
    _REPO_ROOT
    / "unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml"
)

_COMBO_KEY_FOR_NAME: dict[str, str] = {
    "wave_right":  "1",
    "wave_left":   "2",
    "hands_up":    "3",
    "t_pose":      "4",
    "salute":      "5",
    "clap":        "6",
    "guard":       "7",
    "punch_combo": "8",
}


# ── Keyframe interpolation ────────────────────────────────────────────────────

def _interp_gesture(
    keyframes: list[tuple[float, np.ndarray]],
    arm_rest: np.ndarray,
    fps: float,
) -> np.ndarray:
    """Return an (T, 14) array sampled at `fps` Hz.

    Keyframe semantics: each (duration_s, target_14d) pair defines a linear
    blend from the *previous* target to `target_14d` over `duration_s` seconds.
    The previous target for the first keyframe is `arm_rest`.
    """
    poses = [arm_rest] + [pose for _, pose in keyframes]
    durations = [d for d, _ in keyframes]

    segments: list[np.ndarray] = []
    for i, (dur, start, end) in enumerate(
        zip(durations, poses[:-1], poses[1:])
    ):
        n_frames = max(1, int(round(dur * fps)))
        # t=0 → start (exclusive of start to avoid duplicate at segment boundary)
        # t=1 → end (inclusive)
        ts = np.linspace(0.0, 1.0, n_frames + 1)[1:]  # exclude t=0, include t=1
        seg = start[None, :] + ts[:, None] * (end - start)[None, :]
        segments.append(seg.astype(np.float32))

    return np.concatenate(segments, axis=0) if segments else arm_rest[None, :].astype(np.float32)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default=str(_SCRIPT_DIR / "gestures.npz"))
    p.add_argument("--fps", type=float, default=50.0)
    p.add_argument(
        "--deploy-yaml",
        default=str(_DEPLOY_YAML),
        help="Path to velocity/v0 deploy.yaml (provides arm_rest).",
    )
    args = p.parse_args()

    # Load arm defaults from deploy.yaml.
    with open(args.deploy_yaml) as f:
        cfg = yaml.safe_load(f)
    action_offset = np.asarray(cfg["actions"]["JointPositionAction"]["offset"], dtype=np.float64)
    action_scale  = np.asarray(cfg["actions"]["JointPositionAction"]["scale"],  dtype=np.float64)
    arm_rest   = action_offset[ARM_START:ARM_END].copy()
    arm_scale  = action_scale[ARM_START:ARM_END].copy()
    arm_offset = arm_rest.copy()  # same as arm_rest in the velocity policy

    print(f"arm_rest  = {arm_rest}")
    print(f"arm_scale = {arm_scale}")

    # Build unified gesture table (mirrors baseline_runner._build_unified_gesture_table).
    combo_actions = build_arm_actions(arm_rest, arm_scale)
    actions_by_key = {a.key: a for a in combo_actions}
    gesture_table: dict[str, object] = {}
    for name, key in _COMBO_KEY_FOR_NAME.items():
        if key in actions_by_key:
            gesture_table[name] = actions_by_key[key]
    extras = build_extra_arm_actions(arm_rest, arm_scale, arm_offset)
    for a in extras:
        gesture_table[a.name] = a  # salute (replaces combo's), hug (new)

    # Verify all GESTURE_NAMES are present.
    missing = [n for n in GESTURE_NAMES if n not in gesture_table]
    if missing:
        raise RuntimeError(f"Missing gestures from table: {missing}")

    # Sample each gesture at `fps` Hz.
    seqs: list[np.ndarray] = []
    for name in GESTURE_NAMES:
        action = gesture_table[name]
        seq = _interp_gesture(action.keyframes, arm_rest, args.fps)
        seqs.append(seq)
        print(f"  {name:<12s}: {seq.shape[0]:3d} frames  "
              f"({seq.shape[0]/args.fps:.2f}s)  "
              f"max|Δq|={np.abs(seq - arm_rest[None,:]).max():.3f}")

    # Pad to uniform length.
    max_t = max(s.shape[0] for s in seqs)
    arm_qpos = np.zeros((len(GESTURE_NAMES), max_t, seqs[0].shape[1]), dtype=np.float32)
    lengths = np.zeros(len(GESTURE_NAMES), dtype=np.int32)
    for i, seq in enumerate(seqs):
        t = seq.shape[0]
        arm_qpos[i, :t] = seq
        # Pad remaining frames with the final pose (hold at rest).
        arm_qpos[i, t:] = seq[-1]
        lengths[i] = t

    names_arr = np.array(GESTURE_NAMES, dtype=object)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_path, arm_qpos=arm_qpos, lengths=lengths, names=names_arr)
    print(f"\nSaved {out_path}  shape=({len(GESTURE_NAMES)}, {max_t}, 14)  "
          f"lengths={lengths.tolist()}")


if __name__ == "__main__":
    main()
