"""
Baseline characterization runner for `docs/g1_arm_aware_policy_plan.md`
option 1.

Drives the existing
[g1_sim_demo/g1_sim_rl_combo.py::ComboController](./g1_sim_rl_combo.py)
through the full LLM-callable gesture catalog from
[g1_brain/skills/tool_schemas.py::GESTURE_NAMES](../g1_brain/g1_brain/skills/tool_schemas.py)
at multiple walking speeds and records balance metrics. Output is a
pass/marginal/fail table that tells us:

  * Which gestures the current velocity policy + post-policy override +
    arm-slice obs masking can already handle without losing balance.
  * Which gestures break it, and how badly (max gz tilt, max joint vel,
    recovery time).

The runner is *only* an orchestrator — it must not invent any motion
code. It uses combo.push_arm_action / set_command exactly as the
skill_server does. Gesture keyframes come from
``combo.build_arm_actions(arm_rest, arm_scale)`` (8 combo gestures) and
``g1_brain.skills.keyframe_extras.build_extra_arm_actions(...)`` (2
extras: salute, hug). Names mirror
``skill_server._COMBO_KEY_FOR_NAME``.

Usage
-----
  Terminal 1:
      source ~/unitree_sdk2_python/unitree-env/bin/activate
      cd ~/unitree-notes/unitree_mujoco/simulate_python
      python unitree_mujoco.py
      # In the viewer: press 8 ~10 times to lower the band, then 9 to
      # disable. Wait for the runner to prompt before pressing keys.

  Terminal 2:
      source ~/unitree_sdk2_python/unitree-env/bin/activate
      cd ~/unitree-notes/g1_sim_demo
      python g1_sim_baseline_runner.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

import g1_sim_rl_combo as combo
from g1_sim_rl_combo import (
    ComboController,
    G1_NUM_MOTOR,
    DeployCfg,
    Policy,
    GRAVITY_W,
    quat_rotate_inverse,
)

# Add g1_brain to path so we can reuse keyframe_extras + GESTURE_NAMES.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "g1_brain"))
from g1_brain.skills.keyframe_extras import build_extra_arm_actions  # noqa: E402
from g1_brain.skills.tool_schemas import GESTURE_NAMES  # noqa: E402


# Gesture-name -> combo.build_arm_actions key. Mirrors
# skill_server._COMBO_KEY_FOR_NAME exactly.
_COMBO_KEY_FOR_NAME: Dict[str, str] = {
    "wave_right":  "1",
    "wave_left":   "2",
    "hands_up":    "3",
    "t_pose":      "4",
    "salute":      "5",
    "clap":        "6",
    "guard":       "7",
    "punch_combo": "8",
}


def _build_unified_gesture_table(ctl: ComboController) -> Dict[str, "combo.ArmAction"]:
    """Same construction order as g1_brain.skills.skill_server._build_gesture_table.
    Combo gestures come first; extras override on name collision."""
    combo_actions = combo.build_arm_actions(ctl.arm_rest, ctl.arm_scale)
    actions_by_key = {a.key: a for a in combo_actions}

    table: Dict[str, "combo.ArmAction"] = {}
    for name, key in _COMBO_KEY_FOR_NAME.items():
        if key in actions_by_key:
            table[name] = actions_by_key[key]

    extras = build_extra_arm_actions(ctl.arm_rest, ctl.arm_scale, ctl.arm_offset)
    for a in extras:
        table[a.name] = a    # salute (replaces combo's), hug (new)
    return table


# ---- Metrics --------------------------------------------------------------

@dataclass
class TrialMetrics:
    gesture: str
    speed_label: str
    cmd: Tuple[float, float, float]
    max_abs_gz_dev: float        # max |gz - (-1)| over the trial window
    final_gz: float              # gz 5 s after gesture trigger
    max_joint_vel: float         # max |dq| over the window (rad/s)
    final_pelvis_pitch_deg: float  # 0 if upright; sign = forward/back tilt
    fell: bool                   # gz crossed 0 at any point
    verdict: str                 # PASS / MARGINAL / FAIL


def _gz(low_state) -> float:
    q = np.array(list(low_state.imu_state.quaternion))
    if np.linalg.norm(q) < 1e-6:
        q = np.array([1.0, 0.0, 0.0, 0.0])
    return float(quat_rotate_inverse(q, GRAVITY_W)[2])


def _max_abs_dq(low_state) -> float:
    return max(abs(low_state.motor_state[i].dq) for i in range(G1_NUM_MOTOR))


def _pelvis_pitch_deg(low_state) -> float:
    q = np.array(list(low_state.imu_state.quaternion))
    w, x, y, z = q if np.linalg.norm(q) > 1e-6 else (1.0, 0.0, 0.0, 0.0)
    # pitch = asin(2*(w*y - z*x)), in [-π/2, π/2]; positive = nose-up.
    s = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    return float(np.degrees(np.arcsin(s)))


def _classify(m: TrialMetrics) -> str:
    if m.fell:
        return "FAIL"
    if m.max_abs_gz_dev > 0.15 or abs(m.final_gz + 1.0) > 0.15:
        return "FAIL"
    if m.max_abs_gz_dev > 0.05 or abs(m.final_gz + 1.0) > 0.05:
        return "MARGINAL"
    return "PASS"


# ---- Runner ---------------------------------------------------------------

class BaselineRunner:
    POLICY_WAIT_TIMEOUT_S = 30.0   # max wait for ComboController to engage
    GESTURE_RECOVER_S = 5.0        # post-gesture quiescent window
    SAMPLE_DT = 0.05               # 20 Hz metrics sampling
    PRE_GESTURE_SETTLE_S = 1.5     # let walking command stabilise

    def __init__(self, network: str = "lo"):
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        if network == "lo":
            ChannelFactoryInitialize(1, "lo")
            print("[runner] sim mode on lo (domain 1).")
        else:
            ChannelFactoryInitialize(0, network)
            print(f"[runner] real-robot mode on {network} (domain 0).")

        self.cfg = DeployCfg(combo.POLICY_YAML)
        self.policy = Policy(combo.POLICY_ONNX)
        self.ctl = ComboController(self.cfg, self.policy)
        self.ctl.init_dds()
        self.ctl.start()

        self.gestures = _build_unified_gesture_table(self.ctl)
        self.results: List[TrialMetrics] = []

    def wait_for_engagement(self) -> None:
        t0 = time.monotonic()
        while not self.ctl.policy_active:
            if time.monotonic() - t0 > self.POLICY_WAIT_TIMEOUT_S:
                raise RuntimeError(
                    "[runner] ComboController never engaged. Is the elastic "
                    "band still suspending the robot?"
                )
            time.sleep(0.1)
        print("[runner] policy engaged.")

    def prompt_band_release(self, fallback_wait_s: float = 25.0) -> None:
        print("\n" + "=" * 60)
        print(" In the MuJoCo viewer:")
        print("   1) press 8 ~10 times to lengthen the elastic band")
        print("   2) press 9 once to disable the band entirely")
        print(f" Then press ENTER here (or wait {fallback_wait_s:.0f}s "
              "if no terminal).")
        print("=" * 60)
        try:
            if sys.stdin.isatty():
                input()
            else:
                # Non-interactive harness — give the operator time to
                # interact with the viewer window.
                time.sleep(fallback_wait_s)
        except EOFError:
            time.sleep(fallback_wait_s)

    def run_trial(self, gesture_name: str, cmd: Tuple[float, float, float],
                  speed_label: str) -> TrialMetrics:
        action = self.gestures[gesture_name]

        # Phase 1: settle into the requested walking command.
        self.ctl.set_command(*cmd)
        time.sleep(self.PRE_GESTURE_SETTLE_S)

        # Compute total trial window: max keyframe duration + recovery.
        gesture_dur = sum(d for d, _ in action.keyframes)
        win = gesture_dur + self.GESTURE_RECOVER_S
        n_samples = int(win / self.SAMPLE_DT)

        # Phase 2: trigger gesture, sample lowstate during + recovery.
        max_dev = 0.0
        max_dq = 0.0
        fell = False
        self.ctl.push_arm_action(action.keyframes)
        gesture_t0 = time.monotonic()
        for _ in range(n_samples):
            low = self.ctl.low_state
            if low is None:
                time.sleep(self.SAMPLE_DT)
                continue
            gz = _gz(low)
            dq = _max_abs_dq(low)
            if abs(gz + 1.0) > max_dev:
                max_dev = abs(gz + 1.0)
            if dq > max_dq:
                max_dq = dq
            if gz > 0.0:
                fell = True
            time.sleep(self.SAMPLE_DT)

        # Snapshot final state for verdict.
        low = self.ctl.low_state
        final_gz = _gz(low)
        final_pitch = _pelvis_pitch_deg(low)

        m = TrialMetrics(
            gesture=gesture_name, speed_label=speed_label, cmd=cmd,
            max_abs_gz_dev=max_dev, final_gz=final_gz,
            max_joint_vel=max_dq, final_pelvis_pitch_deg=final_pitch,
            fell=fell, verdict="",
        )
        m.verdict = _classify(m)
        elapsed = time.monotonic() - gesture_t0
        print(f"  {gesture_name:<11s} cmd={cmd} -> {m.verdict:<8s} "
              f"max|Δgz|={max_dev:.3f}  final_gz={final_gz:+.3f}  "
              f"max_dq={max_dq:.2f}  pitch={final_pitch:+.1f}°  "
              f"({elapsed:.1f}s)")

        # Phase 3: stop walking, release arms, brief quiescent before next.
        self.ctl.set_command(0.0, 0.0, 0.0)
        self.ctl.release_arms()
        time.sleep(1.0)
        return m

    # Available speed modes; CLI --speeds picks a subset. cmd=(0,0,0.1)
    # is the option-2 falsification: tiny yaw rate keeps the policy in
    # active-balance mode without translating, so we can tell whether
    # the cmd=0 failure is "training gap" (a non-zero cmd fixes it) or
    # "architecture limit" (gesture physics forces displacement).
    SPEEDS_TABLE: Dict[str, Tuple[float, float, float]] = {
        "stand":      (0.0, 0.0, 0.0),
        "stand_yaw":  (0.0, 0.0, 0.1),
        "walk_slow":  (0.2, 0.0, 0.0),
    }

    def run_grid(self, speed_labels: Optional[List[str]] = None) -> None:
        if not speed_labels:
            speed_labels = ["stand", "walk_slow"]
        speeds = [(lbl, self.SPEEDS_TABLE[lbl]) for lbl in speed_labels]

        # Trial order: as specified in --speeds. Default keeps the
        # original ordering (stand first to catch static-balance failures
        # before locomotion confound).
        for label, cmd in speeds:
            print(f"\n=== {label} (cmd={cmd}) ===")
            for name in GESTURE_NAMES:
                if name not in self.gestures:
                    print(f"  {name:<11s} SKIP (not in unified table)")
                    continue
                if self.ctl._stop.is_set():
                    print("[runner] controller stopped — aborting grid.")
                    return
                m = self.run_trial(name, cmd, label)
                self.results.append(m)
                if m.fell:
                    print(f"[runner] {name} caused a fall — stopping {label} block.")
                    break

    def write_report(self, path: Path) -> None:
        # Markdown table grouped by speed_label.
        lines = [
            f"# Option 1 baseline characterization — {time.strftime('%Y-%m-%d %H:%M')}",
            "",
            "Velocity policy = `mimic/dance1_subject2/exported/policy.onnx` ❌",
            "Velocity policy = `velocity/v0/exported/policy.onnx`",
            "Pipeline = `g1_sim_rl_combo.ComboController`",
            "  (post-policy arm override + arm-slice obs masking + Kp boost)",
            "",
            "Verdict thresholds:",
            "  - PASS:     max|Δgz| ≤ 0.05 AND |final_gz + 1| ≤ 0.05",
            "  - MARGINAL: max|Δgz| ≤ 0.15 AND |final_gz + 1| ≤ 0.15",
            "  - FAIL:     anything worse, or robot fell (gz crossed 0)",
            "",
        ]
        for label in sorted({r.speed_label for r in self.results}):
            rows = [r for r in self.results if r.speed_label == label]
            lines.append(f"## {label}")
            lines.append("")
            lines.append("| Gesture | Verdict | max \\|Δgz\\| | final gz | max dq (rad/s) | pitch° |")
            lines.append("|---|---|---|---|---|---|")
            for r in rows:
                lines.append(
                    f"| `{r.gesture}` | **{r.verdict}** | {r.max_abs_gz_dev:.3f} | "
                    f"{r.final_gz:+.3f} | {r.max_joint_vel:.2f} | "
                    f"{r.final_pelvis_pitch_deg:+.1f} |"
                )
            lines.append("")
        path.write_text("\n".join(lines))
        print(f"[runner] wrote {path}")

    def stop(self) -> None:
        self.ctl.stop_and_settle()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--network", default="lo")
    p.add_argument("--report",
                   default=f"/tmp/baseline_{time.strftime('%Y%m%d_%H%M%S')}.md")
    p.add_argument("--no-prompt", action="store_true",
                   help="skip the band-release prompt (assume already done)")
    p.add_argument("--speeds", default="stand,walk_slow",
                   help=("comma-separated subset of "
                         f"{','.join(BaselineRunner.SPEEDS_TABLE)}"))
    args = p.parse_args()

    speed_labels = [s.strip() for s in args.speeds.split(",") if s.strip()]
    bad = [s for s in speed_labels if s not in BaselineRunner.SPEEDS_TABLE]
    if bad:
        raise SystemExit(f"[runner] unknown --speeds entry: {bad}")

    runner = BaselineRunner(network=args.network)
    try:
        runner.wait_for_engagement()
        if not args.no_prompt:
            runner.prompt_band_release()
        else:
            time.sleep(2.0)
        runner.run_grid(speed_labels=speed_labels)
    finally:
        runner.write_report(Path(args.report))
        runner.stop()


if __name__ == "__main__":
    main()
