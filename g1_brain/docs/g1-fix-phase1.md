# g1-fix-phase1 — robot "flies around" after `agent_main` start

Date: 2026-05-05
Branch: main

## 1. Symptom

Running `python -m g1_brain.apps.agent_main --mode confirm` against a
freshly-started `unitree_mujoco.py`, the robot never settles. The log
shows the pose watchdog flapping continuously, with `gravity_z` swinging
across the full range that an upright body should never see:

```
watchdog pose tripped: gravity_z=-0.10   # ~horizontal
watchdog pose tripped: gravity_z=-0.85   # barely upright (threshold edge)
watchdog pose tripped: gravity_z=+0.46   # upside-down
watchdog pose tripped: gravity_z=-0.32
...
```

`gravity_proj_z` is the world-frame gravity vector rotated into the body
frame; an upright G1 has it ≈ -1.0 and a body that is upside-down has it
≈ +1.0 (see `g1_brain/safety/pose_check.py`). Values oscillating
between `-0.85` and `+0.46` describe a body tumbling without stable
ground contact.

The lowstate / RL-policy / camera watchdogs are all fine; the policy
boots normally and reaches `policy ready` at the expected time. The
problem is purely in the simulator-side physics state.

## 2. Root cause

`unitree_mujoco/simulate_python/unitree_mujoco.py` attaches a virtual
elastic band between the robot's `torso_link` and the world point
`(0, 0, 3)`:

```python
class ElasticBand:
    def __init__(self):
        self.stiffness = 200
        self.damping = 100
        self.point = np.array([0, 0, 3])
        self.length = 0
        self.enable = True

    def Advance(self, x, dx):
        δx = self.point - x
        distance = np.linalg.norm(δx)
        direction = δx / distance
        f = (self.stiffness * (distance - self.length)
             - self.damping * v) * direction
        return f
```

`config.py` previously shipped `ELASTIC_BAND_INIT_LENGTH = 0.0`. With
the G1 torso at z ≈ 1.05 m (pelvis at 0.793 m + waist segments) and the
anchor at z = 3, the band's distance is ≈ 1.95 m, so the upward force
applied to `torso_link` is

```
f = stiffness * (distance - length) ≈ 200 * 1.95 = 390 N (upward)
```

That is essentially the G1's weight (~36 kg → ~360 N). The band is
not "holding the torso near standing height" as the old comment
claimed — it is *cancelling gravity* on the torso, leaving the robot
hanging mid-air with no foot contact.

The velocity-tracking RL policy (`unitree_rl_mjlab/.../policy.onnx`)
was trained on `feet-on-ground` rollouts. Its 98-D observation
includes `projected_gravity` (3 D) and `joint_pos_rel` / `joint_vel_rel`
(29+29 D). With no ground contact and the band yanking the torso
around, `projected_gravity` rotates freely and `joint_vel_rel` spikes
on every direction change — both far outside training distribution.
An MLP on out-of-distribution input produces garbage on every output
dimension (see `g1_sim_demo/docs/demo-QA5.md` for the long version
of this argument), and that garbage is what feeds back into the next
tick's lowcmd. The result is the chaotic IMU trace shown in §1.

The README and `docs/how_to_run.md` both told the operator to press
`8` several times in the viewer to lengthen the band and `9` to
release it — but in this session the operator started `agent_main`
without ever focusing the viewer window or pressing those keys. The
pose watchdog correctly diagnosed the consequence (a tipping body)
but the underlying cause is the simulator config, not anything in
`g1_brain`.

## 3. Fix

Make the simulator's default elastic-band length match the robot's
standing height, so the band is slack out of the box and the operator
does not have to press anything.

### 3.1 `unitree_mujoco/simulate_python/config.py`

`ELASTIC_BAND_INIT_LENGTH` changed from `0.0` to `2.0`. With the
anchor at z=3 and `length=2.0`:

- Standing G1: torso at z ≈ 1.05, distance ≈ 1.95 < length → spring
  in slight compression, force ≈ 200 × (1.95 − 2.0) = −10 N along the
  anchor→torso direction (i.e. ~10 N gently pushing down). Effectively
  zero — the robot stands on its own under gravity + foot contact.
- Tipping G1: torso falls to z ≈ 0.5, distance ≈ 2.5 > length →
  force ≈ 200 × (2.5 − 2.0) = 100 N upward, catching the fall.

So the band is invisible during normal operation but still acts as a
soft safety net on falls — which is what an operator would *want*
the band to do for an RL walking demo.

The block comment above the constant was rewritten to explain the
physics and the rationale for the new default. The previous comment
("Default 0.0 matches the original behaviour — band attached at
point=(0,0,3) holds the torso near standing height. For the RL walking
demos … press '8' a few times to lengthen the band, then '9' to disable
it.") was misleading on two counts: (a) length=0 does not "hold" the
torso, it cancels its weight; (b) the press-8-then-9 ritual is no
longer needed.

### 3.2 `g1_brain/README.md`

Terminal-1 block updated. Removed the implicit assumption that the
operator would `press 8 a few times to lower elastic band`; instead,
notes that the G1 lands on the floor immediately under the new
default, with `9` / `8` / `7` retained as optional viewer controls.

### 3.3 `g1_brain/docs/how_to_run.md`

Two edits:

- §2 (the 4-terminal startup) now matches README.md — the inline
  comment block under `python unitree_mujoco.py` no longer tells the
  operator to press `8` to drop the robot. It documents the new
  default and the still-available `7` / `8` / `9` keys.
- §5.7 (head camera renders sky-only frame) replaced the
  "Press `8` … to drop the robot onto the floor" sanity check with a
  note to verify `ELASTIC_BAND_INIT_LENGTH` is at the new default
  (2.0). On older checkouts where it is still `0.0`, the head camera
  sees only sky for exactly the same reason this bug exists — the
  robot is suspended above the floor.

## 4. Operator action required

The fix lives in `config.py`, which the running `unitree_mujoco.py`
process loaded at startup. The simulator process must be restarted
for the new value to take effect; sourcing `.env` again or restarting
`agent_main` alone is not enough.

```bash
# Terminal 1 (the MuJoCo one): Ctrl-C, then
python unitree_mujoco.py
# G1 should now land on the floor and stand without any key presses.

# Terminal 4 (the agent one):
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --mode confirm
```

After restart the expected steady-state from the agent's log is
`gravity_z` ≈ −0.99, no `watchdog pose tripped` lines after boot, and
`fsm: BOOT -> STANDING` should *not* be followed by an immediate
`STANDING -> EMERGENCY_STOP`.

## 5. Out of scope (separate issues observed in the same log)

The same session log surfaces three unrelated problems that were
deliberately not touched in this fix:

- `WARNING g1_brain.perception.runner: pose detector start failed:
  module 'mediapipe' has no attribute 'solutions'` — MediaPipe import
  surface changed in a recent release; the perception runner falls
  back gracefully. Independent of the falling-robot bug.
- `ALSA lib pcm.c:8787:(snd_pcm_recover) [error.pcm] underrun
  occurred` — cosmetic PulseAudio buffer-alignment warnings under
  WSLg; documented in `how_to_run.md` §7.
- `RuntimeWarning: coroutine 'GestureAutoTrigger.stop' was never
  awaited` and `Task was destroyed but it is pending! …
  gesture-auto-trigger` — `agent_main._run`'s shutdown path calls
  `auto_trigger.stop()` synchronously even though `stop` is `async`
  in `mock_imitation/auto_trigger.py`. Affects shutdown only.

These are tracked here so they are not lost; each warrants its own
phase.

## 6. Verification

Manual: restart the simulator + agent per §4. The GLFW viewer should
show G1 standing on the floor in its kneeling-default pose; the
agent log should be clean. No automated test was added because the
behaviour is a property of the simulator's externally-applied force
field, not of any g1_brain code path.

## 7. Files changed

```
unitree_mujoco/simulate_python/config.py            (1 value, comment block)
g1_brain/README.md                                  (terminal-1 block)
g1_brain/docs/how_to_run.md                         (§2 startup, §5.7 sanity)
g1_brain/docs/g1-fix-phase1.md                      (this file)
```
