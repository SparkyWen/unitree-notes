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

1. **Smoke-test the mimic/dance1_subject2 policy** already on disk. If
   tracking-style policies coordinate body+arms cleanly, that validates the
   approach and informs option 2.
2. **Continue-train the velocity policy** with a new arm-disturbance task (this
   is the option that requires writing new tasks — see §C).
3. **Train a new policy from scratch** as last resort (BeyondMimic / Unitree
   tracking task with custom motion files combining locomotion + gestures).

---

## A. Smoke-test mimic/dance1_subject2 (option 1)

### Artifacts on disk

- Policy:
  [unitree_rl_mjlab/deploy/robots/g1/config/policy/mimic/dance1_subject2/exported/policy.onnx](../unitree_rl_mjlab/deploy/robots/g1/config/policy/mimic/dance1_subject2/exported/policy.onnx)
  + sidecar `policy.onnx.data`
- Reference motion: `params/dance1_subject2.npz` (29-DoF reference at 50 Hz)
- Deploy cfg: `params/deploy.yaml`
- C++ runtime: [deploy/robots/g1/src/State_Mimic.cpp](../unitree_rl_mjlab/deploy/robots/g1/src/State_Mimic.cpp)
  + [State_RLBase.cpp](../unitree_rl_mjlab/deploy/robots/g1/src/State_RLBase.cpp)
- C++ MuJoCo bridge: [unitree_rl_mjlab/simulate/](../unitree_rl_mjlab/simulate/)

### Obs/act schema differs from velocity

Mimic deploy.yaml shows obs ≈ 183-D vs velocity's 98-D:
`motion_command (58)` + `motion_anchor_ori_b (6)` + `base_ang_vel (3)` +
`joint_pos_rel (29)` + `joint_vel_rel (29)` + `last_action (29)`. Action is
still 29-D `JointPositionAction` with same scale/offset as velocity.

**Implication: cannot drop the mimic ONNX into `g1_sim_rl_combo.py`** without
a new obs builder that pulls `motion_command` from the .npz frame-by-frame and
computes `motion_anchor_ori_b`.

### Smoke-test paths (3 options, in order of effort)

| | Path | Effort | Notes |
|---|---|---|---|
| A | Build & run C++ FSM controller (`State_Mimic`) against `simulate/` MuJoCo bridge | medium | Canonical. CMake build of `simulate/` + `deploy/`. DDS over `lo`. |
| B | Write Python ONNX adapter mimicking the C++ obs builder, drive `unitree_mujoco` directly (like `g1_sim_rl_combo.py`) | high | Gives us a Python rig we can extend; risks obs-norm mismatch. |
| C | Use `unitree_rl_mjlab/scripts/play.py` | blocked | `play.py` needs the RSL-RL `.pt` checkpoint, which we don't have — only the ONNX export. |

**Recommended: path A.** It's the canonical runtime and the policy was
exported specifically for it; obs normalization etc. is guaranteed to match.

### Smoke-test outcome → decision

- **Mimic tracks dance cleanly**: tracking-style policies *can* do whole-body
  coord. Move to option 2 with confidence.
- **Mimic fails / falls**: skip to option 3 (find a published checkpoint, e.g.
  BeyondMimic / HOVER / ExBody2 G1 release) before sinking time into
  custom training.

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

## C. Continue-train design (option 2) — Approach A: post-policy arm override

Rationale: keep the policy I/O at `Box[29] → Box[29]` so warm-start from
`velocity/v0/policy.onnx` works and `g1_sim_rl_combo.py` deploy code path
needs no changes.

### Files to create

1. **`unitree_rl_mjlab/src/tasks/velocity/mdp/arm_disturbance.py`** *(new)*
   - `GestureLibrary`: loads gesture keyframe trajectories (one NPZ keyed by
     gesture id, 50 Hz, arm-only DoFs). Source: regenerate from
     [g1_sim_demo/g1_sim_rl_combo.py](../g1_sim_demo/g1_sim_rl_combo.py)
     `build_arm_actions()` so training references match deploy injection.
   - `ArmReferenceCommand(CommandTerm)`: per-env state `{gesture_id, phase_t,
     active}`. Triggers Poisson-like every 4–8 s with high prob of "none".
     Exposes `arm_qpos_ref`, `arm_qvel_ref`, `arm_qpos_ref_horizon(k=5)`,
     `gesture_onehot`.
   - `arm_qpos_ref_obs(env)`, `gesture_onehot_obs(env)` — obs functions.

2. **`unitree_rl_mjlab/src/tasks/velocity/config/g1/env_cfgs.py`** *(extend)*
   - Add `unitree_g1_flat_arm_disturbance_env_cfg(play=False)` that:
     - Subclasses `JointPositionActionTerm`; in `apply_actions()`, overwrite
       `processed[:, ARM_SLICE] = command.arm_qpos_ref` after base processing.
     - Adds `ArmReferenceCommand` to `commands["arm_ref"]`.
     - Appends `arm_qpos_ref` (~50-D w/ horizon) and `gesture_onehot` (~10-D)
       to both `observations["actor"]` and `observations["critic"]`.
     - Masks the `pose` reward arm slice (zero per-joint std weight on arm
       indices) so it doesn't fight the override.
     - Adds weak `arm_track_l2` reward (~0.1) against `arm_qpos_ref` for
       drift control even though arms are externally driven.
     - Adds `gesture_intensity` curriculum: ramps trigger probability +
       amplitude scale α∈[0,1] over first ~10k steps. Pattern from
       [velocity/mdp/curriculums.py](../unitree_rl_mjlab/src/tasks/velocity/mdp/curriculums.py).

3. **`unitree_rl_mjlab/src/tasks/velocity/config/g1/__init__.py`** *(extend)*
   - Add `register_mjlab_task("Unitree-G1-Flat-Arm-Disturbance", …)`.

4. **`unitree_rl_mjlab/src/assets/motions/g1/gestures.npz`** *(new asset)*
   - Concatenated arm-only keyframes keyed by gesture id (matches
     `GESTURE_NAMES` from `tool_schemas.py`). Generated by a one-shot script
     that imports `g1_sim_rl_combo.build_arm_actions()`.

### Training command

```bash
python scripts/train.py Unitree-G1-Flat-Arm-Disturbance \
  --env.scene.num-envs=4096 \
  --agent.resume=true \
  --agent.load-run=<path-to-velocity/v0-checkpoint>
```

### Open questions to answer before coding

1. **Gesture asset format**: one NPZ per gesture, or one concatenated NPZ
   keyed by id? *Recommend latter.*
2. **Should the policy see `gesture_onehot`?** *Recommend yes* — easier
   learning signal than expecting it to infer "arm motion incoming" from
   kinematics alone.
3. **Arm Kp/Kd at training time**: deploy uses `K=2.0` to keep arms
   in-distribution under the masking trick. For training under override we
   should use **real URDF Kp** so the policy sees the true torque/accel
   consequences. Otherwise sim-train and deploy disagree on disturbance
   magnitude.
4. **`mock_imitate` / human-shape gestures**: track user arm pose, not a
   canned trajectory. Train on canned keyframes only; treat `mock_imitate` as
   graceful-degradation OOD case (already amplitude-bounded by
   `MIRRORABLE_GESTURES`).

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

- [ ] Option 1: smoke-test mimic/dance1_subject2
- [ ] Option 2: write `Unitree-G1-Flat-Arm-Disturbance` task
- [ ] Option 3: train from scratch / adopt published checkpoint
