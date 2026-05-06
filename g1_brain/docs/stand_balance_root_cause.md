# Stand-balance root cause + fix (2026-05-06)

This document captures everything that changed in the `fix/gestures` branch
during the 2026-05-06 stand-balance debugging session: what the user
observed, how the root cause was isolated against MuJoCo, what code moved,
and how to re-verify the fix.

## 1. What the user observed

Running `python -m g1_brain.apps.agent_main --mode confirm` against
`unitree_mujoco.py`:

- After the operator presses key `8` to lengthen the elastic band and
  key `9` to disable it, the robot collapses within seconds.
- `logs/agent.log` shows a repeating cycle, e.g. session 16:00:

  ```
  STANDING -> ENGAGED  (policy active)
  watchdog pose tripped: gravity_z=-0.79
  ENGAGED -> EMERGENCY_STOP (gravity_z=0.09)
  combo safe-hold engaged
  ... 5 s of watchdog clear ...
  EMERGENCY_STOP -> STANDING -> ENGAGED
  pose trips again ~5 s later, repeat
  ```
- Earlier session 15:42 shows the same pattern triggered after a
  successful `walk(vx=0.2, dur=1.0)` skill — the robot walks fine,
  then ~5 s after `cmd → 0` the pose watchdog fires.

The user's hypothesis was "policy problem". Verification turned this on
its head.

## 2. Where I looked

`agent_main` does not control motors directly. It imports
`g1_sim_rl_combo.ComboController` (see `apps/agent_main.py:565-570`)
and that controller's 50 Hz `_tick` is the only thing publishing to
`rt/lowcmd`. So the root cause has to live in `_tick` or in the things
the watchdog/skill_server poke at it (`set_command`, `set_safe_hold`,
`push_arm_action`).

I instrumented MuJoCo headless to test the central assumption baked
into multiple `_tick` branches: "publishing `default_q` at full Kp keeps
G1 standing." Four scripts, all archived under `docs/verify/`:

| Script | What it isolates |
|---|---|
| `verify/g1_stand_verify.py` | Pure PD against `default_q`, sweep of Kp scales |
| `verify/g1_bridge_seed_test.py` | The bridge's seed `G1_DEFAULT_KP/KD` (= what `safe_hold` was emulating) |
| `verify/g1_stand_policy.py` | Policy at cmd=0 for 60 s + walk-then-stand for 60 s, no DDS |
| `verify/g1_combo_integration.py` | Full DDS round-trip (bridge + combo + elastic band), end-to-end pass criterion |

All four load `unitree_robots/g1/scene_29dof.xml` at the trained `home`
keyframe so the robot starts grounded at `default_q` (no band help in
scripts 1–3; script 4 mimics the operator's lower-then-disable workflow).

## 3. What the data says

| Setup | gz at t=1 s | gz at t=3 s | pelvis_z at t=3 s | Verdict |
|---|---|---|---|---|
| `default_q` + bridge seed PD | -0.96 | +0.12 | 0.089 | **Falls in ~2 s** |
| `default_q` + deploy.yaml × 1.0 | -0.97 | +0.12 | 0.089 | **Falls in ~1.5 s** |
| `default_q` + deploy.yaml × 1.4 (was `STAND_KP_BOOST_TARGET`) | -0.95 | +0.12 | 0.089 | **Falls in ~1.5 s** |
| `default_q` + deploy.yaml × 2.0 | -0.96 | +0.11 | 0.089 | **Falls in ~1.5 s** |
| `default_q` + deploy.yaml × 3.0 | -0.97 | +0.10 | 0.089 | **Falls in ~1.5 s** |
| `default_q` + kb-demo (60/100/40) | -0.96 | +0.12 | 0.089 | **Falls in ~1.5 s** |
| `default_q` + kb-demo × 1.5 | -0.96 | +0.11 | 0.089 | **Falls in ~1.5 s** |
| **Policy at cmd=0**, deploy.yaml gains | -1.000 | -1.000 | 0.783 | **Stable for 60 s** |
| **Policy** during walk(0.2, 1 s) + 57 s idle | -1.000 | -1.000 | 0.783 | **Stable for 60 s** |

The bent-knee `default_q` (knee = 0.30 rad, hip_pitch = -0.10 rad,
ankle_pitch = -0.20 rad) puts the COM forward of the ankle joint axis.
Pure PD around that pose has no way to detect the body tipping and
shift load to the toes — gravity wins, robot falls. The trained
policy detects the tip via `projected_gravity` / `joint_pos_rel` and
produces exactly that load shift, which is why it remains stable.

**Conclusion:** only the policy can keep G1 upright at `default_q`.
Any code path that publishes `default_q` for "safety" actively makes
things worse.

## 4. What was wrong in `g1_sim_rl_combo.py`

Three `_tick` branches replaced the policy's output with a `default_q`
publish:

1. **Stand-still bypass** (old lines 1138–1215) — when `||cmd|| < 0.08`
   for 0.3 s, publish `default_q`. Triggered every time the robot came
   to rest after a walk → matches the user's "5 s after walk done"
   collapse signature.
2. **STANDBY phase** (old lines 1104–1136) — between BOOT done and
   policy engagement, publish `default_q` and gate engagement on
   `gz < -0.95 / pose_err < 0.08 / vel_err < 0.30`. On a grounded robot
   the publish itself collapses the body, so the gates never pass and
   the only path to engagement is the 30 s timeout — by which point
   the robot is already on the floor. (User's log shows
   `pose_err=0.519, vel_err=27.322, gravity_z=-0.02` at the timeout.)
3. **safe-hold** (old lines 1069–1086) — on watchdog `EMERGENCY_STOP`,
   publish `default_q` until auto-recovery. Any transient watchdog
   trip became a permanent fall.

All three were grounded in the docstring claim that the policy
"wobbles `gz=-0.95→-0.50` within ~30 s and falls" at cmd=0. The 60 s
headless test (`verify/g1_stand_policy.py`) shows that claim is wrong
for the current policy: gz stays at -1.000 indefinitely.

## 5. The fix

One file changed: `g1_sim_demo/g1_sim_rl_combo.py`. Net diff: −161 / +86.

- **Stand-still bypass removed.** `_tick` always runs the policy in
  POLICY phase regardless of `||cmd||`. `_stand_active` is still
  tracked (for telemetry / future use) but no longer reroutes the
  publish path. The wind-down blend, which only existed to soften
  the bypass transition, is also gone.
- **STANDBY collapsed.** As soon as `_boot_done` is True, the next
  tick sets `policy_active = True` and runs the policy directly. The
  pre-existing `POLICY_WARMUP_S = 0.6` cosine ease-in + clip protects
  against a bad first inference. `_can_engage_policy` is now dead
  code (kept for diff-size discipline; can be deleted in a follow-up).
- **safe-hold made publish-neutral.** The flag is still set/cleared
  by the watchdog manager, and the `SafetySupervisor` still rejects
  new walk commands while in `EMERGENCY_STOP`; but `_tick` no longer
  short-circuits to `default_q`. The policy keeps running, which is
  what gives auto-recovery a chance of actually recovering the body.
- **`_leg_kp_boost` simplified** to "boost while not yet
  policy-active" only (was previously also gated on `_safe_hold` and
  `_stand_active`, both now defunct as triggers). During the policy
  phase the boost is 1.0× so the policy sees its training-time gains.

The arm-overlay path (gestures) is untouched: `_advance_arms`,
`_clamp_arm_to_safe_envelope`, `_rate_limit_arm_step`,
`_arm_kp_boost`, and `_arm_obs_masked` all still work the same way.

`g1_brain/` itself was not changed — `agent_main.py`, `watchdogs.py`,
`state_machine.py`, and `skill_server.py` already do the right thing
once the controller stops sabotaging itself.

## 6. End-to-end verification

`docs/verify/g1_combo_integration.py` brings up `UnitreeSdk2Bridge` +
`ElasticBand` + `ComboController` in one process and runs the
operator's exact key-press workflow. Run it from the `agi` conda env:

```bash
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
~/miniforge3/envs/agi/bin/python -u \
    ~/unitree/unitree-notes/g1_brain/docs/verify/g1_combo_integration.py
```

(The `cd` is so the `import config` inside `unitree_sdk2py_bridge.py`
finds `unitree_mujoco/simulate_python/config.py`.)

Output, verbatim from the post-fix run:

```
[combo] policy engaged. wsadqe to walk; 1-8 arm gestures; 0 release.
[verify] policy_active=True after 5.1s (boot_done=True)

--- 0a) lower band over 4s (operator presses 8 ~25 times) ---
[verify] band.length=2.50, gz=-1.000, pelvis_z=0.783

--- 0b) press 9 to disable band (robot must now balance) ---
[verify] gz=-1.000, pelvis_z=0.783

--- 1) idle 60s at cmd=(0,0,0) ---       worst gz=-1.000  PASS
--- 2) walk(vx=0.2) 1s + idle 30s ---    worst gz=-0.986  PASS
--- 3) safe_hold ON 5s + OFF + idle 20s  worst gz=-1.000  PASS
```

Pass criterion is `worst gz < -0.85` (≤ ~32° tilt). All three
scenarios cleared it by a huge margin. The unit-test suite
(`pytest g1_brain/tests/`) is also still green: 221 passed.

For a quick cmd=0 stability check without DDS, the lighter
`verify/g1_stand_policy.py` runs in ~30 s wall clock and prints
`gz=-1.000` every second for 60 s of simulated time.

## 7. What's deliberately NOT in this fix

- **Static gestures don't reach correct position** (the user's
  secondary complaint). Independent issue: every entry in
  `build_arm_actions` ends with a keyframe back to `arm_rest`, so
  `static_pose t_pose` is actually a 5.6 s sequence that returns
  to rest. That's a `keyframe_extras.py` / `build_arm_actions`
  scope question, not a balance question. Pending operator
  confirmation before changing it.
- **Watchdog `gravity_z_min` threshold (-0.85)** is unchanged. With
  the controller fix the threshold no longer trips spuriously
  because the policy keeps the body upright; if real-world walking
  ever produces transient -0.80 dips we can revisit, but right now
  there is no evidence to weaken the safety threshold.
- **`_can_engage_policy` and the `STAND_*` constants** are now dead
  code. They are intentionally left in place to keep this commit's
  diff focused on the behavioural fix; a follow-up cleanup can
  remove them once the fix has soaked.
