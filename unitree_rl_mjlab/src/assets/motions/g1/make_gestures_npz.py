"""Generate gestures.npz for arm-disturbance training.

Samples each LLM-callable gesture at `--fps` Hz by linearly interpolating
the keyframe sequences from `g1_sim_rl_combo.build_arm_actions()` and
`keyframe_extras.build_extra_arm_actions()`.  The arm rest position is read
from the velocity/v0 deploy.yaml so the gesture trajectories are in the same
absolute joint-space as the RL environment.

Output (--dof 23, default):
  gestures_23dof.npz
    arm_qpos  float32  [N_g, T_max, 10]  arm joint positions (rad), 5 per arm
    lengths   int32    [N_g]             valid frames per gesture
    names     object   [N_g]             gesture name strings

Output (--dof 29):
  gestures.npz
    arm_qpos  float32  [N_g, T_max, 14]  arm joint positions (rad), 7 per arm

Usage:

    source ~/unitree_sdk2_python/unitree-env/bin/activate
    cd ~/unitree-notes/unitree_rl_mjlab
    python src/assets/motions/g1/make_gestures_npz.py  # 23-DOF (default)
    python src/assets/motions/g1/make_gestures_npz.py --dof 29  # 29-DOF
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
_DEPLOY_YAML_29DOF = (
    _REPO_ROOT
    / "unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml"
)
_DEPLOY_YAML_23DOF = (
    _REPO_ROOT
    / "unitree_rl_mjlab/deploy/robots/g1_23dof/config/policy/velocity/v0/params/deploy.yaml"
)

# 23-DOF arm space uses 5 joints per arm (drops wrist_pitch + wrist_yaw).
# These are the column indices into the 14-D (29-DOF) arm trajectory to keep.
_23DOF_ARM_COLS = [0, 1, 2, 3, 4, 7, 8, 9, 10, 11]

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
    p.add_argument("--out", default=None,
                   help="Output path. Defaults to gestures_23dof.npz (--dof 23) "
                        "or gestures.npz (--dof 29).")
    p.add_argument("--fps", type=float, default=50.0)
    p.add_argument("--dof", type=int, default=23, choices=[23, 29],
                   help="Target DOF variant. 23 = 5 joints/arm (default); "
                        "29 = 7 joints/arm.")
    p.add_argument(
        "--deploy-yaml",
        default=None,
        help="Path to velocity/v0 deploy.yaml (provides arm_rest). "
             "Defaults to the matching DOF variant.",
    )
    args = p.parse_args()

    if args.out is None:
        args.out = str(_SCRIPT_DIR / ("gestures_23dof.npz" if args.dof == 23 else "gestures.npz"))
    if args.deploy_yaml is None:
        args.deploy_yaml = str(_DEPLOY_YAML_23DOF if args.dof == 23 else _DEPLOY_YAML_29DOF)

    # Load arm defaults from deploy.yaml.
    # For 23-DOF we read the 23-DOF yaml but still generate 14-D trajectories
    # using the 29-DOF arm ordering (wrist rest = 0, same as 29-DOF), then
    # slice to 10-D by dropping wrist_pitch/yaw columns.
    with open(args.deploy_yaml) as f:
        cfg = yaml.safe_load(f)
    action_offset = np.asarray(cfg["actions"]["JointPositionAction"]["offset"], dtype=np.float64)
    action_scale  = np.asarray(cfg["actions"]["JointPositionAction"]["scale"],  dtype=np.float64)

    if args.dof == 23:
        # 23-DOF deploy.yaml has 23 entries; arm joints are at indices 13:23.
        arm_rest_10  = action_offset[13:23].copy()
        arm_scale_10 = action_scale[13:23].copy()
        # Pad to 14-D for build_arm_actions (wrist_pitch/yaw stay at 0).
        arm_rest   = np.zeros(14, dtype=np.float64)
        arm_scale  = np.full(14, 0.07, dtype=np.float64)  # small default for wrist
        arm_rest[_23DOF_ARM_COLS]  = arm_rest_10
        arm_scale[_23DOF_ARM_COLS] = arm_scale_10
    else:
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

    # For 23-DOF: drop wrist_pitch/yaw columns (indices 5,6,12,13 in 14-D arm space).
    if args.dof == 23:
        seqs = [s[:, _23DOF_ARM_COLS] for s in seqs]

    arm_dim = seqs[0].shape[1]

    # Pad to uniform length.
    max_t = max(s.shape[0] for s in seqs)
    arm_qpos = np.zeros((len(GESTURE_NAMES), max_t, arm_dim), dtype=np.float32)
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
    print(f"\nSaved {out_path}  shape=({len(GESTURE_NAMES)}, {max_t}, {arm_dim})  "
          f"lengths={lengths.tolist()}")


if __name__ == "__main__":
    main()
