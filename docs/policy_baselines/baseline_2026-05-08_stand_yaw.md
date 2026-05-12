# Option-2 falsification test — stand_yaw — 2026-05-08

Hypothesis under test: "the velocity policy can balance against arm
gestures at cmd=(0,0,0); it just needs *any* non-zero velocity command
to wake its leg torques up." If true, a tiny yaw rate would close the
gap and option 2 retraining wouldn't be needed.

Test: run all 9 LLM-callable gestures with `cmd=(0.0, 0.0, 0.1)` (no
translation, tiny constant yaw rate). Same runner / pipeline as the
2026-05-08 stand baseline.

## Result — TELEMETRY PASS, VISUAL FAIL

| Gesture | Verdict (telemetry) | max \|Δgz\| | final gz | max dq (rad/s) | pitch° |
|---|---|---|---|---|---|
| `wave_right` | **PASS** | 0.002 | -1.000 | 16.30 | -0.8 |
| `wave_left` | **PASS** | 0.001 | -1.000 | 8.20 | -0.1 |
| `hands_up` | **PASS** | 0.025 | -1.000 | 14.35 | +0.3 |
| `t_pose` | **PASS** | 0.001 | -1.000 | 13.33 | +0.2 |
| `salute` | **PASS** | 0.004 | -1.000 | 12.66 | -0.8 |
| `clap` | **PASS** | 0.008 | -1.000 | 11.77 | -0.1 |
| `guard` | **PASS** | 0.008 | -1.000 | 13.50 | -0.1 |
| `punch_combo` | **PASS** | 0.009 | -1.000 | 8.01 | -0.5 |
| `hug` | **PASS** | 0.010 | -1.000 | 18.64 | -0.9 |

## Why this is a FAIL despite all-PASS telemetry

The runner's verdict thresholds measure *upright-ness* (gz tilt and
recovery), not *stillness*. With `wz=0.1 rad/s` for ~8 s, the policy
correctly interprets the command as "turn-walk slowly" and steps
through ~0.8 rad (~46°) of yaw rotation while the gesture plays. The
robot stayed upright through every gesture — but it was *walking in
a small circle*, not standing in place.

User-confirmed visual observation (2026-05-08): "no not working, we
have to retrain the model."

The data IS still informative — it confirms the policy has the
balance capability under any non-zero cmd, including the gestures
the original stand-block tipped it on (`wave_right`, `hands_up`).
But the brain-side / cmd-injection workaround is rejected because
the resulting behaviour is "walk in circles while gesturing", not
"stand still and gesture", which is what the user actually wants.

## Conclusion → option 2 (retrain) is required

The fix has to come from training the policy to balance against arm
disturbance *at cmd=0 specifically*, with the additional reward
shape that penalises drift / stepping. This is the design of
option 2 in the parent plan; the falsification result narrows the
training scenario list to specifically:

  * Episodes with cmd=(0,0,0) AND arm-disturbance event firing.
  * `pose / track_lin_vel_xy / track_ang_vel_z` rewards already
    discourage drift while standing — but they don't currently see
    arm disturbance, so they never learn to *expect* and absorb it.
  * No need to expose a non-zero cmd internally; the policy must
    learn that "cmd=0 + arm motion" implies "shift weight, do not
    step."
