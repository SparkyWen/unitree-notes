# G1 arm-aware locomotion policy — strategy & plan

## Problem

Current locomotion policy at
[unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx](../unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx)
was trained on the velocity-tracking task (`Unitree-G1-Flat`) and never sees arm
motion. The 16 LLM-callable gestures + static poses defined in
[g1_brain/skills/tool_schemas.py](../g1_brain/g1_brain/skills/tool_schemas.py)
disturb balance because the policy literally cannot observe arm state.

Existing workaround in
[g1_sim_demo/g1_sim_rl_combo.py:22-35](../g1_sim_demo/g1_sim_rl_combo.py#L22-L35)
hides arm motion from the policy: arms are overridden post-policy, the arm slice
of the 98-D obs is masked to defaults, and arm Kp is reduced to `K=2.0` to keep
arm joint_pos_rel in-distribution. Works for small gestures only — large
gestures cause balance loss and/or rebalance-policy thrash.

Goal: a locomotion policy that **observes** the arm motion (canned gesture or
imitation reference) and **balances** against the resulting disturbance. The
arm trajectory is *imposed*, not learned — the policy only learns legs+waist.

## Strategy — try cheapest first

1. **Baseline characterization** — run the existing
   [g1_sim_rl_combo.py](../g1_sim_demo/g1_sim_rl_combo.py) (velocity
   policy + post-policy arm override + arm-slice obs masking + Kp boost
   while overriding) and quantify exactly which gestures break balance
   while walking, and how badly. This is the *direct* test of the goal
   ("walk + rebalance while arms move"), uses code we already have, and
   tells us whether option 2 is actually needed and how aggressive it
   has to be. See §A.
2. **Continue-train the velocity policy** with a new arm-disturbance task (this
   is the option that requires writing new tasks — see §C).
3. **Train a new policy from scratch** as last resort (BeyondMimic / Unitree
   tracking task with custom motion files combining locomotion + gestures).

> Earlier draft of option 1 was a dance smoke test of the
> mimic/dance1_subject2 policy. That test was run (2026-05-08) and
> passed — it validated *architecturally* that a tracking-style
> network can coordinate body+arms cleanly — but it doesn't measure
> the failure mode we actually care about (velocity policy losing
> balance under canned gestures while walking). The dance result is
> kept as a sidebar in §A2 because it bounds option 3's risk; option 1
> proper is now the baseline characterization above. The Python
> deploy adapter built for that test is at
> [g1_sim_demo/g1_sim_rl_mimic.py](../g1_sim_demo/g1_sim_rl_mimic.py).

---

## A. Baseline characterization (option 1)

### What we're measuring

The complaint that motivated this plan: while walking, calling any of
`GESTURE_NAMES` from
[g1_brain/skills/tool_schemas.py](../g1_brain/g1_brain/skills/tool_schemas.py)
disturbs balance, sometimes catastrophically. That's the qualitative
report. Before we commit to training a new policy, we want to *quantify*
it on the existing pipeline so option 2 has a target to beat:

- Per-gesture pass/fail at the standing pose (cmd=0).
- Per-gesture pass/fail while walking (vx=0.2 m/s and the largest in-range vx).
- Tilt magnitude during gesture (max gravity_z deviation from -1.0).
- Foot slip / step length anomaly during gesture.
- Recovery time after gesture ends.
- Whether the existing `K=2.0` arm Kp reduction is actually helping or
  hurting (quick ablation: rerun with `K=ARM_GESTURE_KP_SCALE=2.8`
  default vs `K=1.0`).

This is the *direct* test of the goal: "walk + rebalance while arms move."
Output is a per-gesture × per-speed table that tells us:

  * If everything passes → no need for option 2; we're done.
  * If only large gestures fail → option 2 with a small curriculum
    will likely fix it; aggressive obs/reward changes not needed.
  * If even small gestures wobble → the policy has no margin for arm
    perturbations and option 2 needs full obs exposure of the arm
    reference (not just `arm_qpos_ref`, also `arm_qvel_ref` and a
    short forward horizon).

### Test rig

The existing
[g1_sim_demo/g1_sim_rl_combo.py](../g1_sim_demo/g1_sim_rl_combo.py)
already implements every degree of freedom we need:

  * 50 Hz RL tick on the velocity policy.
  * Keyboard or programmatic walk commands (`set_command(vx, vy, wz)`).
  * `push_arm_action(keyframes)` injects a gesture.
  * `_arm_obs_masked` toggles arm-slice masking — flip it off in a
    fork to measure "what would a no-mask deploy look like?"
  * `ARM_GESTURE_KP_SCALE` controls arm Kp during gesture — vary it.

Build a thin runner script that:

  1. Boots `g1_sim_rl_combo` against `unitree_mujoco` with the band
     workflow (band on, lower in viewer once policy is engaged).
  2. Walks at vx∈{0, 0.2, vx_max} for ~3 s, then triggers each gesture
     in `GESTURE_NAMES`, records lowstate for ~5 s, lets policy
     recover, repeats.
  3. Logs gz, pelvis pos, foot contacts, q_target vs measured q.
  4. Ablates: `arm_obs_masked` ∈ {True, False}, `kp_scale` ∈ {1.0, 2.8}.
     `K=4` envelope: skip — already known to be too tight per the file
     docstring.

Output: a markdown table in this doc summarising pass/fail and worst-case
metrics per (gesture, speed, ablation) cell.

### Smoke-test outcome → decision

- **All cells pass**: ship as-is, close this plan.
- **Some cells fail with masking on but pass with masking off**:
  the masking trick is part of the problem; option 2's main win
  is showing the policy real arm state.
- **Some cells fail regardless of masking**: option 2 must add an
  arm *reference* obs (the upcoming gesture trajectory), not just
  the arm *state*. Implies the arm-disturbance task design in §C
  is the right shape.
- **All cells fail catastrophically**: skip option 2; jump to
  option 3 (adopt published checkpoint; the velocity policy has no
  recoverable margin).

## A2. Sidebar — mimic/dance1_subject2 smoke test (informational)

Run on 2026-05-08 as an architectural sanity check. **Not** the option 1
test; it doesn't measure walking-with-gestures balance. Kept here
because it bounds option 3's risk: it confirmed that a tracking-style
policy *can* coordinate whole-body motion in this MuJoCo bridge, so
adopting BeyondMimic-style published checkpoints (option 3) is a
viable fallback rather than a gamble.

### Artifacts on disk

- Policy:
  [unitree_rl_mjlab/deploy/robots/g1/config/policy/mimic/dance1_subject2/exported/policy.onnx](../unitree_rl_mjlab/deploy/robots/g1/config/policy/mimic/dance1_subject2/exported/policy.onnx)
  + sidecar `policy.onnx.data`
- Reference motion: `params/dance1_subject2.npz` (29-DoF reference at 50 Hz)
- Deploy cfg: `params/deploy.yaml`
- C++ runtime: [deploy/robots/g1/src/State_Mimic.cpp](../unitree_rl_mjlab/deploy/robots/g1/src/State_Mimic.cpp)
  + [State_RLBase.cpp](../unitree_rl_mjlab/deploy/robots/g1/src/State_RLBase.cpp)
- Python adapter (built for this test):
  [g1_sim_demo/g1_sim_rl_mimic.py](../g1_sim_demo/g1_sim_rl_mimic.py)

### Obs/act schema differs from velocity

Mimic deploy.yaml: obs = 154-D, not 183 as a stale draft of this doc
claimed. `motion_command (58)` + `motion_anchor_ori_b (6)` +
`base_ang_vel (3)` + `joint_pos_rel (29)` + `joint_vel_rel (29)` +
`last_action (29)` = 154; all six terms have `history_length: 1`.
Action is still 29-D `JointPositionAction` with same scale/offset as
velocity.

### What this test answered

Question: can a tracking-style network coordinate body+arms cleanly,
i.e. is the architectural premise of options 2 and 3 sound?

Result: yes. Dance plays for 30 s, gz∈[-1.000, -0.855], tracking err
0.1–0.6 rad steady on legs and arms after a 0.3 s ramp. Robot stays
upright after the elastic band is disabled mid-dance.

What it did NOT answer: anything about velocity policy + gestures. The
mimic policy is a different policy on a different task; success on
dance does not imply the velocity policy's gesture handling will
improve on its own.

---

## B. unitree_rl_mjlab task structure (reference)

Verified by exploring the repo. These facts inform options 2 and 3.

### Registration

Tasks register via `register_mjlab_task(task_id, env_cfg, play_env_cfg, rl_cfg, runner_cls)`
in `src/tasks/<task>/config/<robot>/__init__.py`. Existing G1 tasks:

- `Unitree-G1-Flat` — [src/tasks/velocity/config/g1/__init__.py:10-24](../unitree_rl_mjlab/src/tasks/velocity/config/g1/__init__.py#L10-L24)
- `Unitree-G1-Tracking-No-State-Estimation` — [src/tasks/tracking/config/g1/__init__.py:15-21](../unitree_rl_mjlab/src/tasks/tracking/config/g1/__init__.py#L15-L21)

### Env config skeleton (`ManagerBasedRlEnvCfg`)

Top-level fields: `scene`, `observations` (actor + critic groups), `actions`,
`commands`, `rewards`, `terminations`, `events`, `curriculum`, `metrics`,
`viewer`, `sim`, `decimation`, `episode_length_s`.

### Action space — single Box[29], all joints

Both velocity and tracking use:
```python
actions = {"joint_pos": JointPositionActionCfg(actuator_names=(".*",), ...)}
```
[velocity_env_cfg.py:152-159](../unitree_rl_mjlab/src/tasks/velocity/velocity_env_cfg.py#L152-L159).
**No upper/lower-body split.** This is the architectural fact that drives the
new-task design.

### Velocity reward set (14 terms)

Defined at [velocity_env_cfg.py:261-354](../unitree_rl_mjlab/src/tasks/velocity/velocity_env_cfg.py#L261-L354).
The `pose` term penalizes deviation from per-mode (walking/running/standing)
reference posture — **including arms** — and is the only term that conflicts
with imposed arm motion.

### Existing perturbation events (templates for arm-disturbance event)

- `push_robot` — interval-mode velocity impulse, every 5–6 s ([velocity_env_cfg.py:209](../unitree_rl_mjlab/src/tasks/velocity/velocity_env_cfg.py#L209))
- `encoder_bias` — startup-mode joint encoder noise ([:234](../unitree_rl_mjlab/src/tasks/velocity/velocity_env_cfg.py#L234))
- `foot_friction` — startup-mode friction randomization ([:224](../unitree_rl_mjlab/src/tasks/velocity/velocity_env_cfg.py#L224))

`push_robot` is the closest template — same injection mechanism we need for
gesture triggering.

### Tracking task — how arms ARE commanded today

- `MotionLoader` reads `.npz` with keys `joint_pos[T,29]`, `joint_vel[T,29]`,
  `body_pos_w`, `body_quat_w`, `body_lin_vel_w`, `body_ang_vel_w`
  ([tracking/mdp/commands.py:32-57](../unitree_rl_mjlab/src/tasks/tracking/mdp/commands.py#L32-L57))
- `MotionCommand.command` returns `cat([joint_pos, joint_vel])` (58-D) per env
  ([tracking/mdp/commands.py:124](../unitree_rl_mjlab/src/tasks/tracking/mdp/commands.py#L124))
- Reward: per-body pos/ori/vel L2 over all bodies including arm links
  ([tracking_env_cfg.py:211-242](../unitree_rl_mjlab/src/tasks/tracking/tracking_env_cfg.py#L211-L242))

### Training scripts

- [scripts/train.py](../unitree_rl_mjlab/scripts/train.py) — supports `--agent.resume` for warm-start
- [scripts/play.py](../unitree_rl_mjlab/scripts/play.py) — replay; loads `.pt` from `logs/rsl_rl/<exp>/<run>/model_<n>.pt`
- [scripts/csv_to_npz.py](../unitree_rl_mjlab/scripts/csv_to_npz.py) — reference-motion preprocessing

---

## C. Continue-train design (option 2) — implemented 2026-05-08

Rationale: keep the policy I/O at `Box[29] → Box[29]` so warm-start from
`velocity/v0/policy.onnx` works and `g1_sim_rl_combo.py` deploy code path
needs no changes. The training-time disturbance (externally driven arm
joints) mirrors what the deployment code already does (post-policy arm
override in `ComboController._tick`).

### Architecture overview

**Obs** (actor, 177-D = 98 base + 9 gesture_onehot + 70 arm_qpos_ref_horizon):

| Slice | Dim | Description |
|---|---|---|
| base_ang_vel | 3 | IMU angular velocity |
| projected_gravity | 3 | gravity in body frame |
| command | 3 | velocity command (vx, vy, wz) |
| phase | 2 | gait phase sin/cos |
| joint_pos | 29 | q_meas − q_default |
| joint_vel | 29 | dq_meas − dq_default |
| actions | 29 | last policy output |
| **gesture_onehot** | **9** | **one-hot: which gesture is playing (0 if idle)** |
| **arm_qpos_ref_horizon** | **70** | **5 future arm frames × 14 joints (rad)** |

**Action** (29-D): policy outputs all 29 joints; arm slice [15:29] is
overridden at env step time with the gesture reference before being sent to
the physics sim. Legs [0:11] + waist [12:14] are fully controlled by the
policy and this is where balance learning happens.

**Key insight**: the policy must learn to **anticipate** the arm disturbance
using `gesture_onehot` and `arm_qpos_ref_horizon`, then pre-shift its CoM
before the disturbance hits — same as what a human does.

### New files

#### [`src/tasks/velocity/mdp/arm_disturbance.py`](../unitree_rl_mjlab/src/tasks/velocity/mdp/arm_disturbance.py) *(created 2026-05-08)*

- **`GestureLibrary`** — loads `gestures.npz` (`arm_qpos [N_g, T_max, 14]`,
  `lengths [N_g]`); provides `get_frame(gesture_ids, frames)`.
- **`ArmReferenceCommand(CommandTerm)`** — Poisson-like trigger (random idle
  interval sampled from `trigger_interval_range_s`); per-env state
  `{gesture_id, phase_frame, active}`; exposes:
  - `arm_qpos_ref` — [N, 14] absolute arm joint positions
  - `gesture_onehot` — [N, 9] one-hot indicator
  - `arm_qpos_ref_horizon(k=5)` — [N, 70] next 5 frames concatenated
  - Curriculum hook: `cfg.trigger_interval_range_s` can be modified by
    `gesture_intensity` curriculum to ramp disturbance frequency.
- **`arm_qpos_ref_obs`, `gesture_onehot_obs`, `arm_qpos_ref_horizon_obs`** —
  observation functions wired into the env cfg.
- **`arm_track_l2`** — reward: `−||q_arm − arm_ref||²` for active gesture
  envs, zero for idle. Weight 0.05 (secondary to balance rewards ~1.0).
- **`ArmDisturbanceAction(JointPositionAction)`** — overrides `apply_actions()`
  to replace `_processed_actions[:, arm_indices]` with `arm_qpos_ref` for
  active envs before sending targets to the physics sim.
- **`gesture_intensity`** — curriculum term; modifies
  `ArmReferenceCommandCfg.trigger_interval_range_s` by stage.

#### [`src/assets/motions/g1/make_gestures_npz.py`](../unitree_rl_mjlab/src/assets/motions/g1/make_gestures_npz.py) *(created 2026-05-08)*

One-shot generator script. Imports `g1_sim_rl_combo.build_arm_actions()` and
`keyframe_extras.build_extra_arm_actions()`, interpolates all 9 gestures at
50 Hz, saves `gestures.npz`. The `arm_rest` values come from
`velocity/v0/deploy.yaml`, guaranteeing training and deployment use the same
reference coordinate.

Run before training (the training script calls it automatically):
```bash
python src/assets/motions/g1/make_gestures_npz.py
```

#### [`src/tasks/velocity/config/g1/env_cfgs.py`](../unitree_rl_mjlab/src/tasks/velocity/config/g1/env_cfgs.py) *(extended)*

New function `unitree_g1_flat_arm_disturbance_env_cfg(play=False)`:
- Starts from `unitree_g1_flat_env_cfg` and adds:
  - `commands["arm_ref"] = ArmReferenceCommandCfg(...)` (starts at 8–16 s
    interval; curriculum ramps to 4–8 s after 120k steps)
  - `actions["joint_pos"] = ArmDisturbanceActionCfg(...)` (arm override)
  - `observations["actor"/"critic"].terms` updated with `gesture_onehot` (9-D)
    and `arm_qpos_ref_horizon` (70-D)
  - `pose` reward arm stds set to 1e6 (disabled) so the arm pose reward
    doesn't fight the gesture override
  - `rewards["arm_track_l2"]` weight 0.05
  - `curriculum["gesture_intensity"]` with two stages

#### [`src/tasks/velocity/config/g1/__init__.py`](../unitree_rl_mjlab/src/tasks/velocity/config/g1/__init__.py) *(extended)*

Registers `Unitree-G1-Flat-Arm-Disturbance` task.

### Training — one-key launch

```bash
cd ~/unitree-notes/unitree_rl_mjlab
bash scripts/train_arm_disturbance.sh
```

Script ([scripts/train_arm_disturbance.sh](../unitree_rl_mjlab/scripts/train_arm_disturbance.sh)):
1. Generates `gestures.npz` if not present.
2. Symlinks the latest `g1_velocity` checkpoint into the
   `g1_arm_disturbance` log dir so `--agent.resume` can find it.
3. Calls `scripts/train.py Unitree-G1-Flat-Arm-Disturbance` warm-started
   from that checkpoint.

The full underlying command:
```bash
python scripts/train.py \
  Unitree-G1-Flat-Arm-Disturbance \
  --env.scene.num-envs 4096 \
  --agent.resume true \
  --agent.load-run warmstart_velocity_v0 \
  --agent.experiment-name g1_arm_disturbance \
  --agent.max-iterations 10001 \
  --gpu-ids 0
```

### Curriculum stages

| Step range | trigger_interval_range_s | Disturbance rate |
|---|---|---|
| 0 – 120k | 8–16 s | sparse — ~one gesture per episode |
| 120k+ | 4–8 s | nominal — ~two gestures per episode |

The nominal 4–8 s interval comes from the real LLM call rate observed in
the voice-loop demo (~3–7 s between gesture calls). The sparse warmup lets
the policy first consolidate its standing balance before adding frequent
arm disturbances.

### Design decisions (open questions resolved 2026-05-08)

1. **Gesture asset**: one concatenated NPZ keyed by gesture index — simpler
   to load from GPU, avoids file-per-gesture proliferation.
2. **Policy sees both `gesture_onehot` AND `arm_qpos_ref_horizon(k=5)`** —
   onehot identifies WHICH gesture to anticipate; horizon gives the exact
   future trajectory so the policy can pre-shift CoM for large gestures
   (e.g. `hands_up`).
3. **No Kp/Kd change** — training uses real URDF Kp so the policy sees true
   torque/acceleration consequences, matching what deployment will experience
   with the combo controller's arm Kp boost (`ARM_GESTURE_KP_SCALE=2.8`).
   If deployment and training Kp diverge, add domain randomisation later.
4. **`mock_imitate` / human-arm gestures** — treat as graceful-degradation
   OOD: the gesture_onehot will be all-zeros (not in the catalog) but the
   arm_qpos_ref_horizon will still carry the reference, so the policy at
   least observes the incoming disturbance trajectory. No curriculum change
   needed for this case.

---

## D. Train from scratch (option 3) — only if 1 and 2 fail

Use `Unitree-G1-Tracking-No-State-Estimation` with custom motion NPZs
combining locomotion + gestures. Or adopt a published checkpoint:
- BeyondMimic / `HybridRobotics/whole_body_tracking` — same framework
  unitree_rl_mjlab integrates
- HOVER (NVIDIA) — unified velocity+arm-tracking, G1 ports exist
- ExBody2 (Berkeley) — expressive G1 control
- ASAP (CMU) — sim-to-real whole-body G1

Cost estimate: hours-to-day on a single GPU at `--env.scene.num-envs=4096`.

---

## Verification path

For each option:

- **Option 1 (smoke test)**: visually confirm dance1_subject2 plays in MuJoCo
  with the head/torso staying upright and feet not slipping. Record a video
  via `scripts/play.py --video`-equivalent (C++ runtime equivalent: MuJoCo
  native viewer in `simulate/`).
- **Option 2 (continue-train)**: after training, deploy `policy.onnx` into
  `g1_sim_demo/g1_sim_rl_combo.py` — it must drop in unchanged. Run each
  gesture in `GESTURE_NAMES` while standing and while walking; check
  base orientation stays within 15° of upright and no termination fires.
- **Option 3 (from scratch)**: same as option 2 but obs/act adapter changes.

## Status

- [x] Option 1: baseline characterization (2026-05-08) — results summarised
      in §Status below; falsification also in §Status
- [x] Option 2: `Unitree-G1-Flat-Arm-Disturbance` task implemented (2026-05-08)
      — code in `src/tasks/velocity/mdp/arm_disturbance.py`,
        `src/assets/motions/g1/make_gestures_npz.py`,
        `src/tasks/velocity/config/g1/env_cfgs.py`,
        `scripts/train_arm_disturbance.sh`
      — **next step**: run `bash scripts/train_arm_disturbance.sh` on lab GPU,
        then re-verify stand block with `g1_sim_baseline_runner.py --speeds stand`
- [ ] Option 3: train from scratch / adopt published checkpoint

### Option 1 result (2026-05-08) — clean problem split + falsification

Runner: [g1_sim_demo/g1_sim_baseline_runner.py](../g1_sim_demo/g1_sim_baseline_runner.py).
Reuses `ComboController.set_command` and `push_arm_action` (no new
motion code) and the unified gesture table from `skill_server`.

#### Baseline (cmd=0 vs cmd=0.2 m/s)
**Standing balance + arm gesture = fails. walking + arm gesture = already works.**

  * `wave_right` at cmd=0: gz tilts to -0.54 (27° tilt) before
    recovering. `hands_up` at cmd=0: robot tips past vertical, gz
    crosses 0 (full fall), then recovers.
  * All 9 gestures at cmd=0.2 m/s: PASS with max|Δgz| ≤ 0.03.

#### Falsification: "tiny non-zero command unblocks balance"

Hypothesis: a tiny `wz=0.1 rad/s` (no translation) would put the
policy into active-balance mode without translating, and balance
would hold. If true, the brain could inject this internally as a
zero-cost workaround.

Result: **rejected.** Telemetry says all 9 gestures PASS at
`cmd=(0,0,0.1)` with max|Δgz| ≤ 0.025. But the policy correctly
interprets the wz command as "turn-walk slowly" and steps through
~0.8 rad of rotation while the gesture plays. The robot stays
upright but is **walking in a circle**, not standing in place.
User confirmed visual: "not working, we have to retrain."

#### Conclusion → option 2 is required

Both parts of the option-1 read-out must be satisfied:

1. The training task must include cmd=(0,0,0) trajectories with
   the arm-disturbance event active. (Baseline.)
2. At cmd=0, the policy must learn to absorb the disturbance via
   weight shift, NOT via stepping or yaw drift. (Falsification.)
   The existing reward terms (`track_lin_vel_xy`, `track_ang_vel_z`,
   `pose`) already penalise drift, but they never co-occur with an
   arm disturbance, so the policy never learns to anticipate it.

Curriculum recommendation: start training at vx∈[0.1, 0.3] with
gesture events (the policy already wins this), ramp toward vx=0 with
the same disturbance distribution.

### Side-test record: mimic dance smoke test (2026-05-08)

Architectural sanity check (see §A2). Result: PASS. Established that a
154-D tracking policy on the existing MuJoCo bridge can coordinate
whole-body motion cleanly (gz∈[-1.000, -0.855] over 30 s). Bounds the
risk of option 3 (adopting a published whole-body checkpoint).

### Reusable artefact from the side-test

[g1_sim_demo/g1_sim_rl_mimic.py](../g1_sim_demo/g1_sim_rl_mimic.py) —
subclass of `g1_sim_rl_combo.ComboController` that overrides `_tick`,
`_engage`, `_build_obs` for the 154-D mimic obs. Two fixes applied
during the test that should carry into the option 1 baseline runner:

  * **Bridge seed PD cannot statically balance the robot.** The
    elastic band must remain engaged (or the policy must engage)
    before the body has time to tip forward. The mimic adapter
    engages on the very first lowstate and skips the BOOT/STANDBY
    gates. For the option 1 baseline test the canonical
    `g1_sim_rl_combo.py` BOOT phase is fine *as long as* the band
    is up during BOOT and the user lowers it after the policy
    engages — same workflow that's been documented in
    `g1_sim_rl_combo.py`'s docstring all along.

  * **`stop_and_settle` must keep `_tick` publishing during the
    soften ramp.** Otherwise the bridge keeps applying the last
    commanded pose at full Kp ("stubborn posture" observed when
    the dance ended). Fix: set a `dance_done` flag, have `_tick`
    publish `default_q` while soften slews Kp to 0; main loop
    watches `dance_done` (not `_stop`) before triggering the
    soften. Worth folding back into `g1_sim_rl_combo.py` itself if
    the option 1 baseline runner triggers the same path on
    keyboard quit.
