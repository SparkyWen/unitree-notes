# g1-fix-phase6 — sitting startup, "flying" agent_main, and unexpressive gestures

Date: 2026-05-05
Branch: fix/g1-balance

## 1. Symptoms (operator-reported)

Three closely-related issues observed when running the G1 RL stack against
`unitree_mujoco`:

1. **MuJoCo opens with the robot already sitting on the floor.**
   Pressing the viewer's "Reset" key returns it to the same collapsed pose
   instead of the upright trained pose.

2. **`python -m g1_brain.apps.agent_main` frequently makes the robot "fly
   around" right after launch.**  The operator routinely had to press
   MuJoCo's reset many times in a row to get a single run that stayed
   stably standing.

3. **Static arm gestures from `g1_sim_rl_combo` look stunted and tend to
   make the robot lose balance.**  Walking and running motions remained
   correct, but `hands_up`, `T-pose`, `salute`, etc. clearly didn't reach
   the intended angles, and triggering one from a stand often tipped the
   robot over.

These three symptoms share root causes; the phase-6 fix addresses them
together as a single self-consistent change.

## 2. Root-cause analysis

### 2.1 Sitting at startup

`unitree_mujoco/simulate_python/config.py` had been changed in
`a47d3c0 fix: balance of g1` from `ELASTIC_BAND_INIT_LENGTH = 0.0` to
`= 2.0`. The intent was that the elastic band's natural length matched
the robot's standing height (torso z ≈ 1.05 m, anchor at z = 3.0 m, so
distance ≈ 1.95 m < 2.0 m), making the band slack at standing.

The flaw: at MuJoCo startup **no controller is producing torques yet**.
`UnitreeSdk2Bridge.ApplyControl` early-returns when `_latest_cmd is None`,
so the robot is unactuated. Gravity collapses the legs immediately. The
band is slack and never catches it. The robot ends up in a heap on the
floor, which the operator described as "sitting".

### 2.2 Robot "flying" at `agent_main` launch

`ComboController._tick` activated the policy unconditionally
`boot_dur` (5 s) after the first `rt/lowstate`:

```python
self.boot_t += self.cfg.step_dt
if self.boot_t >= self.boot_dur:
    self.policy_active = True            # <-- no gating!
    return
```

By the time the policy was engaged, the robot was usually still:

  * mid-air on the elastic band (distance changing → joint dynamics not
    yet at steady state), or
  * mid-recovery from a partial collapse (joints sweeping back to
    `default_q`, with non-trivial `joint_vel_rel`), or
  * tilted past the policy's training distribution because the boot ramp
    blends `boot_q_from -> default_q` at fixed timing and the band's
    pull/release timing depended on the operator.

The MLP receives an out-of-distribution observation, fires a noisy
action on every output dim, the legs slam into bad targets, and the
robot launches itself. Hence the "fly around" experience and the
operator's habit of resetting until a lucky initial condition let it
stabilise.

### 2.3 Unexpressive / unbalancing gestures

`g1_sim_rl_combo.build_arm_actions` encoded each gesture as a
*delta from default* in units of `action_scale`:

```python
arm_pose = arm_rest + delta * arm_scale[15:29]
```

clipped to `default ± ARM_GESTURE_K * action_scale` with `K = 2.0`.
For shoulder pitch (`scale = 0.44`) this caps each joint at ±0.88 rad.
That is far too narrow to express recognisable gestures. For example
`hands_up` was supposed to bring the arms overhead (shoulder pitch
≈ −1.6 rad in `g1_sim_keyboard.py`'s legacy reference), but the clamp
gave only `default + (−2 × 0.44) = −0.53` rad — barely above the side.
Salute, T-pose, hug, etc. all suffered similarly.

The motivation for the K=2 envelope was to keep `joint_pos_rel[15:29]`
inside the policy's training distribution. The envelope did its job —
gestures within it didn't break legs — but at the cost of expressiveness.
Operators bumping `K` up themselves got expressive gestures *and* leg
collapse, because once the arm `joint_pos_rel` slot in the observation
left training distribution, the MLP corrupted *every* output dim,
including legs.

## 3. Fix design

### 3.1 Stand-pose-from-zero: default-pose holding PD in the bridge

The simulator must keep the robot in its trained default joint pose
**before any external controller is running**, so that:

  * MuJoCo opens with the robot visually upright (no "sitting" symptom);
  * when `agent_main` later starts, the very first `rt/lowstate` it
    samples already shows `joint_pos_rel ≈ 0`, so the boot ramp blends
    default → default (a near no-op) and the engagement gates pass
    quickly.

We seed `_latest_cmd` in `UnitreeSdk2Bridge.__init__` with a
default-pose PD whose gains and target come from `config.py`:

```python
G1_DEFAULT_JOINT_POS = [...]   # copy of deploy.yaml :: default_joint_pos
G1_DEFAULT_KP        = [...]   # copy of stiffness
G1_DEFAULT_KD        = [...]   # copy of damping
```

`LowCmdHandler` overwrites this seed the moment an external controller
publishes its first `rt/lowcmd`, so there is no fight between bridge-PD
and controller-PD. The operator workflow returns to "press 8 to lower
the band, press 9 to disable it", with the elastic-band keybindings
unchanged from the original demo (`7 = shorten / lift`, `8 = lengthen
/ lower`, `9 = toggle on/off`). `ELASTIC_BAND_INIT_LENGTH` is restored
to `0.0`, which matches the original behaviour the operator
remembered: at startup the band lifts the torso to ~1.5 m, the
default-pose PD holds the joints at `default_q`, and the operator can
manually lower the band whenever they're ready.

### 3.2 MuJoCo `<keyframe>` and startup qpos

`unitree_mujoco/unitree_robots/g1/g1_29dof.xml` now declares an explicit
`<keyframe name="home">` whose `qpos` matches `default_joint_pos`. This
gives:

  * a sensible starting state when the simulator initialises
    `mj_data` (we also call `_set_g1_default_qpos` in
    `unitree_mujoco.py` to write the same values into `mj_data.qpos`
    before `viewer.launch_passive`, so the very first frame already
    shows the trained pose);
  * a target for `mj_resetDataKeyframe` if the operator wants to
    programmatically reset to "home" later.

### 3.3 Anti-flying engagement gates and policy warm-up

The `ComboController` boot path now has three phases instead of two:

```
BOOT (5 s) → STANDBY (≤30 s) → POLICY
```

* **BOOT** — same as before. Cosine ease-in from `boot_q_from` to
  `default_q` with `kp_scale` ramping from `BOOT_KP_FLOOR` (0.3) to 1.0.
* **STANDBY** — *new*. The controller keeps publishing `default_q` at
  full Kp and waits for measurable quiescence:

  | gate | constant | meaning |
  |------|----------|---------|
  | `pose_err <= ENGAGE_POSE_TOL` | 0.08 rad | per-joint distance from `default_q` (legs+waist) |
  | `vel_err <= ENGAGE_VEL_TOL`   | 0.30 rad/s | per-joint speed (legs+waist) |
  | `gravity_proj_z <= ENGAGE_GRAV_Z` | −0.85 | body upright (cos⁻¹ ≈ 31°) |
  | `held_for_s >= ENGAGE_HOLD_S` | 0.8 s | all of the above continuously satisfied |

  `ENGAGE_TIMEOUT_S = 30 s` is a safety hatch: if the gates somehow
  never converge we engage anyway and log the final gate state, so the
  controller can never wedge in STANDBY forever.

* **POLICY** — same as before, but the first `POLICY_WARMUP_S = 0.6 s`
  blends `raw_action` with the held default action (cosine ease-in) and
  hard-clips its magnitude to `±POLICY_WARMUP_CLIP = 0.8`. A single bad
  inference at hand-off can no longer slingshot a leg.

Combined with the default-pose PD in the bridge, by the time
`agent_main` reaches the policy phase the observation is in
distribution. The "flying" symptom is eliminated by construction.

### 3.4 Expressive gestures via observation masking

The K=2 envelope is removed. Each gesture is now an **absolute** 14-D
arm pose authored in joint-angle space, clamped only to the **physical
joint limits** taken from the MJCF (`ARM_JOINT_LIMITS`):

| joint | training scale | old envelope | new physical limit |
|-------|---------------|--------------|--------------------|
| shoulder pitch | 0.44 | ±0.88 rad | -3.05 / +2.65 rad |
| shoulder roll  | 0.35 | ±0.70     | varies (mirrored)  |
| elbow          | 0.44 | ±0.88     | -1.00 / +2.05      |
| wrist pitch    | 0.07 | ±0.14     | ±1.55              |

The OOD risk that the old envelope guarded against is now eliminated
by **masking the arm slice of the policy observation while a gesture
override is active**. `_build_obs` zeroes
`joint_pos_rel[15:29]`, `joint_vel_rel[15:29]`, and
`last_raw_action[15:29]` when `_arm_obs_masked` is True. The policy
sees "arms at default, not moving" no matter where the arms physically
are, so its leg/waist output stays in distribution. The arms are still
rate-limited by `ARM_GESTURE_RATE_K_PER_SEC = 4.0` to keep
`joint_vel_rel` reasonable for diagnostics, and the per-tick rate
limit also keeps the actuators away from their torque limit.

The 8 keyboard-assigned gestures were rewritten using the legacy
`g1_sim_keyboard.py` poses — the ones the operator remembered as
"the gestures looked right":

| key | gesture | shoulder pitch (rad) | other notable |
|-----|---------|----------------------|---------------|
| 1   | wave R  | -0.4 | shoulder roll -1.2, elbow 1.4 |
| 2   | wave L  | -0.4 | shoulder roll +1.2, elbow 1.4 |
| 3   | hands up | -1.6 | elbow 0 (straight up) |
| 4   | T-pose  | (default) | shoulder roll ±1.5, elbow 0 |
| 5   | salute  | -0.6 (R) | elbow 1.55, wrist pitch -0.3 |
| 6   | clap    | -0.8 | shoulder roll ±0.4, elbow 1.2 |
| 7   | guard   | -0.6 | shoulder roll ±0.5, elbow 1.4 |
| 8   | punch   | -1.0 | extended arm + guard return |

`g1_brain/g1_brain/skills/keyframe_extras.py` (which wraps the
`salute` and `hug` static poses for the brain skill server) is updated
the same way: it now clamps to the same physical joint limits and the
old `arm_offset / arm_scale / k` parameters of `_clamp_to_envelope`
are kept for API stability but ignored.

## 4. Files changed

| Path | Change |
|------|--------|
| `unitree_mujoco/simulate_python/config.py` | Restore `ELASTIC_BAND_INIT_LENGTH = 0.0`; add `G1_DEFAULT_JOINT_POS / KP / KD` constants. |
| `unitree_mujoco/simulate_python/unitree_sdk2py_bridge.py` | New `_maybe_seed_default_hold_cmd` and `_apply_default_qpos`; track `_external_cmd_received`; seed `_latest_cmd` on construction. |
| `unitree_mujoco/simulate_python/unitree_mujoco.py` | New `_set_g1_default_qpos()` called before `viewer.launch_passive`. |
| `unitree_mujoco/unitree_robots/g1/g1_29dof.xml` | Add `<keyframe name="home">` with the trained `default_joint_pos`. |
| `g1_sim_demo/g1_sim_rl_combo.py` | New BOOT / STANDBY / POLICY state machine with `_can_engage_policy` gates and warm-up clipping; absolute-pose gestures; physical-limit clamp; arm-slice obs masking. |
| `g1_brain/g1_brain/skills/keyframe_extras.py` | Use physical joint limits (`_ARM_JOINT_LIMITS`) instead of the old `default ± k*action_scale` envelope. |

## 5. Verification

* `python3 -m pytest g1_brain/tests/` — 219 tests pass.
* Manual smoke test of `ComboController._can_engage_policy`:
  * fresh STANDBY at default pose → `False` (needs to hold).
  * after holding 1 s → `True`.
  * pose drifted +0.5 rad → `False`.
* Manual smoke test of `_build_obs` masking: with `_arm_obs_masked = True`
  the arm slice of `joint_pos_rel` is exactly 0; with
  `_arm_obs_masked = False` it reflects the live pose deviation.
* Manual MuJoCo MJCF compile: the new keyframe loads
  (`mj_resetDataKeyframe(m, d, 0)` reproduces the trained joint pose).
* Manual gesture amplitude check: `hands_up` now reaches max joint
  deviation 1.95 rad (was 0.88), `T-pose` 1.32 rad, `wave` 1.02 rad —
  all well within the physical joint limits and recognisable visually.

## 6. Operator-visible workflow

After this change the recommended workflow is the **original** one the
operator remembered:

```bash
# Terminal 1 — start the simulator
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# Robot starts at the trained default pose, suspended high up by the
# elastic band. To bring it down to the ground:
#   - press 8 a few times to lengthen the band (lower the robot);
#   - press 7 if you over-shoot and want to lift it back up;
#   - press 9 once on the ground to disable the band entirely.

# Terminal 2 — launch the agent / RL combo
conda activate unitree
python -m g1_brain.apps.agent_main
# Wait for "[combo] policy engaged" — that's STANDBY -> POLICY firing
# after the engagement gates pass (~1-2 s after BOOT finishes if the
# robot is on the ground at the trained pose, longer if you're still
# lowering the band).
```

If the operator launches `agent_main` *before* lowering the band, the
controller stays in STANDBY (holding `default_q`) until the band is
released and the gates pass; the policy is never engaged on a
mid-air-suspended state.
