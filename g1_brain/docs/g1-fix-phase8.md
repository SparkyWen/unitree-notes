# G1 Brain Fix Phase 8 — Production stability via process isolation

**Branch:** `fix/gestures` · **Date:** 2026-05-06

This document captures the full debugging + fix arc for the
2026-05-06 session in which the operator reported, against the
running production stack:

> "我没有给任何指令，但是机器人的手一直在乱动，一直在乱晃，根本没
> 有保持平衡，而且我让其走，走一小步就直接失衡倒下了。"

(Translation: "I gave no commands, but the robot's hands keep moving,
keep shaking, and don't maintain balance at all; when I tell it to walk,
it falls after a single small step.")

The root cause turned out to be **GIL contention from the perception
subsystem on the 50 Hz control thread**, conclusively proved by the
operator's own reproduction with `--no-perception` ("瞬间就不乱晃了，
非常稳定" — "stops shaking instantly, rock-solid"). The fix is a
**structural isolation of the combo controller into its own subprocess**,
plus three smaller safety-rule corrections that surfaced along the way.

---

## 1. Startup flow (the canonical "production" launch)

```bash
# ─────────── Terminal 1: simulator ───────────
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# In the GLFW viewer:
#   - press '8' a few times to lengthen the elastic band so the robot
#     descends to the floor at a controlled rate;
#   - press '9' to disable the band entirely (clean fall test).

# ─────────── Terminal 2: brain ───────────
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a            # OPENAI_API_KEY etc.
python -m g1_brain.apps.agent_main --mode confirm
```

Internally `agent_main` does this, in order:

1. Open the single-instance lock (`/tmp/g1_brain.lock`).
2. Bring up audio I/O (`va_demo.audio_io.MicStream` + `SpeakerStream`).
3. `ChannelFactoryInitialize(domain_id=1, interface="lo")` for DDS.
4. Build `CameraHub` (head cam = MuJoCo offscreen render; usb cam =
   teleimager / cv2).
5. **Spawn the combo controller as a subprocess** via
   `g1_brain.safety.combo_proxy.ComboProxy.start()` (the new code in
   this phase). The proxy:
   - allocates `mp.Value` shared-memory mirrors for `policy_active`,
     `mode_machine`, `last_state_time`, `first_state_received`;
   - opens a `mp.Pipe` for command messages (`set_command`,
     `push_arm_action`, `release_arms`, `set_safe_hold`, `soften`,
     `stop`);
   - launches the child via `multiprocessing.get_context("spawn")` so
     the child is a fresh interpreter (not a fork — we explicitly do
     **not** want to inherit the parent's DDS / onnxruntime / audio
     thread state);
   - the child re-runs `ChannelFactoryInitialize`, imports
     `g1_sim_rl_combo`, builds `DeployCfg` + `Policy` + `ComboController`,
     calls `init_dds()` then `start()` (which itself blocks on the
     first `rt/lowstate`);
   - once the child has its first lowstate it pushes the read-only
     constants (`arm_rest`, `arm_scale`, `arm_offset`, `mode_machine`)
     back to the parent through a one-shot pipe;
   - parent unblocks `start()` after receiving those constants.
6. Build `RobotStateBus`, `SceneStateBus`.
7. Build `_RobotStateProducer`. Because combo is in a subprocess, also
   call `attach_lowstate_sub(domain, iface)` so the brain has its own
   independent `rt/lowstate` subscription (the LowState\_ message does
   not cross the process boundary cheaply).
8. FSM `BOOT -> STANDING`.
9. `EstopClient(...)`.
10. `SafetySupervisor(..., perception_enabled=not args.no_perception)`.
11. `WatchdogManager(...).start()`.
12. (Optional) `PerceptionRunner.start()` — YOLO + MediaPipe + ground
    constraint loop, all in the agent\_main process. Not in the combo
    subprocess.
13. `BrainRealtimeAgent(...)` — OpenAI Realtime websocket + tool
    routing.
14. Async wait for shutdown signal; on SIGINT, gracefully tear down in
    reverse order (perception → realtime agent → wake-word →
    watchdogs → robot\_state\_producer → ComboProxy.stop\_and\_settle()
    → cameras → audio).

The fall-back paths (`--no-skills`, `--no-perception`,
`--vision-only`) keep the in-process `ComboController` instead of
spawning, because:

- `--no-skills`: nothing to run (no controller).
- `--no-perception`: GIL contention argument disappears, in-process is
  simpler.
- `--vision-only`: implies `--no-skills`.

The new behaviour is gated by `cfg.robot.isolate_controller` (default
`true`), so the operator can fall back to the legacy in-process path
purely from YAML if needed.

---

## 2. Symptoms reported

Three independent failure modes were observed in `--mode confirm`:

| # | Symptom | First seen at |
|---|---------|---------------|
| A | "Hands keep shaking / moving randomly" without any command | every run, immediately after `policy engaged` |
| B | Balance not maintained: gravity\_z oscillating between -0.7 and -1.0 visible in watchdog log | first run (17:24 session) |
| C | Walks `vx=0.2 dur=1.0`, succeeds, then falls **12 s later** at gravity\_z=0.33 | every run with a walk command |

In addition, the audio system was producing
`ALSA underrun` lines almost continuously — a smoking gun that
agent\_main's process was overloaded enough that even the 50 ms audio
buffer (24 kHz × 1200-sample blocks) couldn't be kept full.

---

## 3. Investigation — what we proved before changing code

### 3.1 The policy itself is fine

We ran two existing headless verify scripts unmodified:

```bash
cd ~/unitree/unitree-notes
python g1_brain/docs/verify/g1_stand_policy.py
python g1_brain/docs/verify/g1_combo_integration.py
```

Both pass with worst gravity\_z ≈ -1.000 over 60 s of idle and through
walk-then-stop. The policy + controller in isolation are rock-solid.

### 3.2 Arm motion at idle is small in headless

A new measurement script (`/tmp/g1_arm_motion_check.py`) ran 20 s of
`cmd=(0,0,0)` and logged per-arm-joint deviation. Result:

```
worst peak deviation: 0.041 rad (2.4 deg)
worst raw_action peak: 0.398
mean_dev ≈ rms_dev ≈ peak_dev   (steady offset, no oscillation)
```

So the policy *does* push the arms ~0.4 raw\_action away from default
even at cmd=0, but in clean isolation the result is a static 2.4°
offset, not visible flailing. The flailing the operator sees in
production must therefore come from *time-varying* policy output —
which only happens when the obs stream itself is jittered.

### 3.3 The smoking gun: `--no-perception` is rock-solid

The operator's own A/B test:

| Run | Result |
|-----|--------|
| `--mode confirm` (full stack) | hands shake; falls 12 s after walk |
| `--mode confirm --no-perception` | "瞬间就不乱晃了，非常稳定" (rock-solid, doesn't shake at all) |

This is the conclusive evidence: *something in PerceptionRunner is
destabilizing the controller, even though the controller code is
unchanged*. With Python's GIL the only viable mechanism is contention.

### 3.4 The contended threads in agent\_main process

| Thread | Default rate | CPU profile |
|--------|--------------|-------------|
| Combo `_tick` (50 Hz control) | 50 Hz | numpy + onnxruntime CPU exec |
| MuJoCo head cam render | 20 Hz | OpenGL + 2 renders/frame (RGB + depth) |
| YOLO11s @ head | 15 Hz | torch (GPU) + numpy pre/post (CPU) |
| YOLO11s @ usb  | 15 Hz | same |
| MediaPipe pose @ usb | 15 Hz | TF Lite XNNPACK (CPU only) |
| USB camera poll | 20 Hz | network call to teleimager |
| OpenAI realtime websocket | continuous | I/O bound |
| Audio capture / playback | 24 kHz blocks | small but real-time |

Under GIL, any heavy thread that runs Python or holds the GIL through
a numpy / TF call delays every other thread, including the 50 Hz
control thread. The trained policy is a velocity-tracking RL policy
that expects fresh proprioception every 20 ms; if the obs has 30-50
ms of jitter, the policy starts producing actions that don't match
reality, and over seconds those errors accumulate into visible arm
motion and (eventually) an unrecoverable forward drift after a walk.

---

## 4. The fix — process isolation for the combo controller

### 4.1 Why this design

We rejected three alternatives:

1. **Reduce perception inference rates** (e.g. 15 Hz → 3 Hz). Cuts CPU
   usage but doesn't fix the worst-case stalls — even one slow
   inference still parks the GIL for tens of ms.
2. **Hijack a DDS topic for command bridging** (publish a fake
   `WirelessController_` from agent\_main, subscribe in
   `g1_sim_rl_combo.py`). Hacky and intrusive to the upstream module.
3. **Move PerceptionRunner to a subprocess instead.** Larger surface
   (camera frames are 1 MB at 20 Hz; would need shared memory) and
   leaves combo's API in the parent where any future GIL hog could
   reintroduce the problem.

The chosen design is the simplest one that *physically* removes the
GIL contention without breaking any caller:

- combo runs in a child process spawned via
  `multiprocessing.get_context("spawn").Process(...)`;
- everything that calls combo (skill\_server, watchdogs,
  \_RobotStateProducer) goes through a `ComboProxy` that mirrors the
  old `ComboController` API exactly;
- shared memory via `mp.Value` for hot reads (`policy_active`,
  `mode_machine`, `last_state_time`, `first_state_received`);
- `mp.Pipe` for low-rate writes (commands).

### 4.2 New file: `g1_brain/safety/combo_proxy.py`

Header excerpt:

```python
"""Cross-process proxy for ComboController.

Runs g1_sim_rl_combo.ComboController in a dedicated subprocess so its
50 Hz control loop has its own Python GIL, isolated from agent_main's
perception (YOLO + MediaPipe + MuJoCo head render), AI (OpenAI
realtime websocket + TTS), and audio (sounddevice capture + playback)
threads.
"""
```

Public API (drop-in replacement for `ComboController`):

| Member | Semantics |
|--------|-----------|
| `start()` / `stop_and_settle()` | spawn / join the child |
| `arm_rest` / `arm_scale` / `arm_offset` | populated after `start()` returns |
| `mode_machine` | populated after `start()` returns |
| `policy_active` | shared-memory atomic read |
| `first_state_received` | shared-memory atomic read |
| `last_state_time` | shared-memory atomic read |
| `low_state` | always `None` (see §4.3) |
| `set_command(vx, vy, wz)` | Pipe send |
| `push_arm_action(keyframes)` | Pipe send (numpy arrays pickle through) |
| `release_arms()` | Pipe send |
| `set_safe_hold(active)` | Pipe send |
| `soften(target_scale, duration)` | Pipe send |

Subprocess entry point `_combo_main(...)`:

1. Re-init DDS (`ChannelFactoryInitialize`).
2. Import `g1_sim_rl_combo`, build `DeployCfg` + `Policy` +
   `ComboController`.
3. Block until the simulator is publishing `rt/lowstate`.
4. Push read-only constants back to the parent via a one-shot pipe.
5. `ctl.start()` — spins up the 50 Hz `RecurrentThread` *inside* this
   process.
6. Spawn a small status-update thread that copies `ctl.policy_active`
   etc. into the parent's `mp.Value` mirrors at 20 Hz.
7. Drain command Pipe; dispatch to `ctl.set_command` /
   `push_arm_action` / etc. Catch all exceptions per-message so a
   single bad command doesn't kill the worker.

### 4.3 Why `low_state` is intentionally `None`

The `LowState_` DDS message has 100+ fields and arrives at 500 Hz from
the simulator. Pickling it across the multiprocessing boundary at that
rate is not viable, and even a 50 Hz mirror would dominate the IPC
budget. Instead we make `combo.low_state` `None` on the proxy and
require the brain side to subscribe to `rt/lowstate` directly when it
needs the message.

In practice the only reader is `_RobotStateProducer`, so we extended
it with `attach_lowstate_sub(domain_id, interface)`:

```python
def attach_lowstate_sub(self, domain_id, interface):
    """Open our own rt/lowstate subscription."""
    from unitree_sdk2py.core.channel import (
        ChannelFactoryInitialize, ChannelSubscriber,
    )
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_

    ChannelFactoryInitialize(domain_id, interface)  # idempotent
    self._lowstate_sub = ChannelSubscriber("rt/lowstate", LowState_)
    self._lowstate_sub.Init(self._on_lowstate, 10)
```

`_RobotStateProducer._tick()` now reads `self._lowstate` first, then
falls back to `combo.low_state` (for the in-process path). When the
proxy is in use, the brain has a fully independent view of robot state
and the watchdogs see fresh quaternion / gyro at 500 Hz.

### 4.4 Wiring in `agent_main.py`

Pseudocode of the new branch:

```python
isolate_controller = bool(cfg.get("robot", {}).get("isolate_controller", True))
if args.no_skills or args.no_perception:
    isolate_controller = False     # nothing to spawn, or no GIL pressure

if not args.no_skills and isolate_controller:
    from ..safety.combo_proxy import ComboProxy
    combo_ctl = ComboProxy(domain_id=..., interface=...)
    log.info("spawning combo subprocess (controller isolated from "
             "perception/AI/audio GIL) — waiting for first /rt/lowstate ...")
    await asyncio.wait_for(asyncio.to_thread(combo_ctl.start), timeout=40.0)

if not args.no_skills and not isolate_controller:
    # Legacy in-process path, unchanged.
    combo_mod = _try_import_combo()
    combo_ctl = combo_mod.ComboController(deploy_cfg, policy)
    combo_ctl.init_dds()
    combo_ctl.start()
```

And one extra line where the producer is built:

```python
if isolate_controller:
    robot_state_producer.attach_lowstate_sub(domain, iface)
```

That's the entire wiring change.

---

## 5. Three smaller fixes that surfaced along the way

While converging on the process-isolation fix, three additional bugs
were exposed by the `--no-perception` reproduction. All three are
included in this commit.

### 5.1 head\_frame / usb\_frame watchdog: don't EMERGENCY\_STOP at startup

**File:** `g1_brain/safety/watchdogs.py`

Before: when `head_frame_age_s()` returned `inf` (no head frame ever
received — typical for the first 30 s while the camera spins up) and
`boot_grace_s` (default 5 s) had expired, the watchdog promoted to
`EMERGENCY_STOP`. The operator saw 25 s of `ENGAGED ↔ EMERGENCY_STOP`
flap on every cold start.

After: `_tick_head_frame` and `_tick_usb_frame` distinguish "warming
up" (`age == inf`) from "stale-after-working" (finite-but-large) and
only promote in the second case:

```python
warming_up = age == float("inf")
if age > self.head_max_age:
    self._set_trip("head_frame", f"age={age:.2f}s",
                   emergency=not warming_up)
```

Two regression tests in `test_watchdogs.py`:

- `test_head_frame_inf_age_does_not_emergency` — `age=inf` must not
  promote.
- `test_head_frame_finite_stale_still_emergencies` — once at least one
  frame has arrived, finite-but-stale ages still promote.

### 5.2 SafetySupervisor live check: same inf-age carve-out

**File:** `g1_brain/safety/supervisor.py` Rule 5

The supervisor independently re-checks `head_frame_age_s()` on every
walk/approach call (defense-in-depth, in case the watchdog hadn't
ticked yet). Without the matching carve-out, `--no-perception` was a
dead-end mode: every walk got `watchdog: head frame age infs > 2.00s`.

```python
head_warming_up = head_age == float("inf")
if (
    tool in {"walk", "approach"}
    and head_age > max_head
    and not head_warming_up
):
    return False, f"watchdog: head frame age {head_age:.2f}s > ...", {}
```

Regression test: `test_head_frame_inf_age_does_not_block_walk`.

### 5.3 SafetySupervisor: `perception_enabled` flag for Rule 9

**Files:** `g1_brain/safety/supervisor.py`, `g1_brain/apps/agent_main.py`

With `--no-perception`, `PerceptionRunner` never starts and
`scene_bus.update_ground` is never called. Rule 9 `if ground is None`
was permanently `True` and every walk/approach was rejected with
`scene: no ground constraint yet`.

Solution: thread `args.no_perception` into the supervisor as an
explicit constructor flag, and only block on `ground is None` when
perception was meant to be running:

```python
def __init__(self, ..., perception_enabled: bool = True):
    self.perception_enabled = bool(perception_enabled)

# Rule 9:
if ground is None:
    if self.perception_enabled:
        return False, "scene: no ground constraint yet", {}
    # else: operator opted out; fall through, lowstate / pose / RL
    # policy / parameter clamp checks still apply.
```

Regression tests: `test_perception_disabled_skips_ground_constraint`,
`test_perception_disabled_still_honors_other_rules` (belt-and-braces:
the carve-out is Rule-9-only, lowstate watchdog still rejects).

### 5.4 Confirm prompt: single-keypress cbreak instead of readline

**File:** `g1_brain/safety/supervisor.py` `_confirm_in_terminal`

Two real-world failures:

1. Stale arrow keys queued in stdin's line buffer were returned by
   `readline()` instead of the operator's `y`. The line `"\x1b[C\n"`
   strips/lowers to `"\x1b[c"`, declined; operator's actual `y`
   queued for nobody. Earlier `tcflush` mitigation helped but didn't
   eliminate the race.
2. Operator typed `y` but forgot Enter (the prompt didn't advertise
   that line-mode requires it). 10 s timeout fired with `y` still in
   the buffer — "operator declined in confirm mode" with no recovery.

Rewrote to single-keypress cbreak mode:

```python
tty.setcbreak(fd)
termios.tcflush(sys.stdin, termios.TCIFLUSH)
ch = sys.stdin.read(1)
if ch == "\x1b":  # arrow-key escape: drain ESC [ X then read again
    second = sys.stdin.read(1)
    if second == "[":
        sys.stdin.read(1)
    ch = sys.stdin.read(1)
```

`y` accepts immediately, any other key declines immediately. Falls
back to `readline` when `tcgetattr` fails (piped stdin / CI). Timeout
extended from 10 s to 15 s. Three regression tests in
`test_safety_supervisor.py` covering the happy path, decline-on-arrow,
and the readline fallback.

---

## 6. Tests

```
$ pytest tests/
============================= 230 passed in 2.68s ==============================
```

Six new regression tests (all passing) added across this phase:

| Test | What it locks in |
|------|------------------|
| `test_head_frame_inf_age_does_not_emergency` | Watchdog inf-age carve-out |
| `test_head_frame_finite_stale_still_emergencies` | But stale-after-working still promotes |
| `test_head_frame_inf_age_does_not_block_walk` | Supervisor live-check inf-age carve-out |
| `test_perception_disabled_skips_ground_constraint` | `--no-perception` allows walk |
| `test_perception_disabled_still_honors_other_rules` | But other rules still apply |
| `test_confirm_in_terminal_accepts_single_y_keypress` | cbreak path: `y` alone accepts |
| `test_combo_proxy_imports` | New module loads cleanly |
| `test_combo_proxy_constructs_without_starting` | Default state before `start()` is sane |
| `test_combo_proxy_send_before_start_does_not_crash` | Shutdown / pre-start sends are best-effort |

---

## 7. File-by-file diff summary

```
 g1_brain/g1_brain/apps/agent_main.py        | 163 ++++++++++++++++--
 g1_brain/g1_brain/safety/combo_proxy.py     | 270 ++++++++++++++++++++++++++++ (NEW)
 g1_brain/g1_brain/safety/supervisor.py      | 182 +++++++++++++++----
 g1_brain/g1_brain/safety/watchdogs.py       |  25 ++-
 g1_brain/tests/test_combo_proxy.py          |  60 ++++++ (NEW)
 g1_brain/tests/test_safety_supervisor.py    | 249 ++++++++++++++++++++------
 g1_brain/tests/test_watchdogs.py            |  83 +++++++++
 7 files changed, ~860 insertions(+), ~110 deletions(-)
```

---

## 8. What was deliberately NOT changed

- **`g1_sim_demo/g1_sim_rl_combo.py`** — the controller itself.
  Phase 7 left it correctly engaging the policy continuously with
  proper warm-up / safe-hold semantics; the verify scripts confirm
  it's solid in isolation. The bug was never inside this file.
- **Perception inference rates** — left at the YAML defaults
  (`yolo.inference_hz: 15`, `pose.inference_hz: 15`,
  `cameras.poll_hz: 20`). With combo isolated, perception's CPU
  budget stops mattering for control stability, so there's no reason
  to degrade scene-update freshness.
- **Watchdog `gravity_z_min` / `recovery_hold_s` / `boot_grace_s`** —
  all left at their phase-7 values. The flap they used to produce
  was a downstream consequence of the in-process GIL contention,
  not a tuning issue.
- **MuJoCo simulator** — completely untouched.

---

## 9. How to roll back

Set in `g1_brain/configs/g1_brain.yaml`:

```yaml
robot:
  isolate_controller: false
```

This sends `agent_main` back through the legacy in-process path. No
code change needed. All other phase-8 fixes (watchdog inf-age,
supervisor inf-age, perception\_enabled, confirm cbreak) remain in
effect because they are independent.

---

## 10. Live end-to-end verification (2026-05-06, post-bug-fix)

The first deploy of phase 8 had a mechanical Pipe-direction bug:
``mp.Pipe(duplex=False)`` returns ``(reader, writer)`` and the proxy's
constructor unpacked them as ``(_cmd_parent, _cmd_child)`` — but the
data flow is parent **writes**, child **reads**, so the variable name
"_cmd_child" pointed at the writer end. The subprocess immediately
crashed on its first ``cmd_pipe.recv()`` with
``OSError: connection is write-only``, agent_main timed out waiting,
fell back to "no controller", and the robot collapsed under the
simulator's seed PD.

Three follow-up changes:

1. **Use `Pipe(duplex=True)` for the command pipe.** Both ends can then
   send and recv, so the variable naming reflects ownership rather than
   direction. (The constants pipe stays `duplex=False` because data
   genuinely flows child → parent and the names already match.)
2. **Detect subprocess early-death in `start()`** via
   `multiprocessing.connection.wait([const_pipe, proc.sentinel])` —
   if the child dies before sending constants, `start()` raises
   `RuntimeError` with the exit code instead of blocking until timeout.
3. **agent_main handles the new `RuntimeError`** by falling back to
   the in-process `ComboController` (still has phase-7 stability fixes)
   so a worker import failure does not silently leave the operator with
   no controller.
4. **Two new regression tests** in `test_combo_proxy.py` actually spawn
   subprocesses through the test-only stub entry points
   (`_test_stub_combo_main`, `_test_crashing_combo_main` in
   `combo_proxy.py`) so any future Pipe wiring bug fails CI rather than
   reaching the operator.

After the fix, an end-to-end verify with the headless MuJoCo bridge +
ComboProxy subprocess (analogous to `g1_combo_integration.py` but for
the proxy path; script archived at `/tmp/verify_combo_proxy_headless.py`)
passes all three pass criteria:

```
=== summary ===
  worst gz, idle 30 s:        -1.000  -> PASS
  worst gz, post-walk 20 s:   -0.999  -> PASS
  worst gz, safehold 10 s:    -1.000  -> PASS

[verify] OVERALL PASS — ComboProxy keeps robot stable end-to-end
```

Lifecycle timings during this verify:

| Step | Latency |
|------|---------|
| `ComboProxy.start()` returns | 0.7 s |
| `policy_active` becomes True | 5.9 s after start (= 5 s boot ramp + ~0.9 s warm-up) |
| `stop_and_settle()` returns | 2.45 s |

`pytest tests/` is also green: **232 passed**, including
`test_combo_proxy_full_lifecycle_with_stub_subprocess` and
`test_combo_proxy_detects_subprocess_early_death`.

## 11. Verification protocol for the operator

```bash
# Terminal 1
conda activate unitree && export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# Press 8 a few times to lower the band, then 9 to disable it.

# Terminal 2
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --mode confirm
```

Expected log:

```
... DDS initialized: domain=1 iface=lo
spawning combo subprocess (controller isolated from perception/AI/audio
GIL) — waiting for first /rt/lowstate ...
[combo subproc] waiting for first rt/lowstate ...
[combo subproc] rt/lowstate received; starting control thread
[combo] policy engaged. wsadqe to walk; 1-8 arm gestures; 0 release.
fsm: BOOT -> STANDING (boot complete)
fsm: STANDING -> ENGAGED (policy active)
robot_state: attached own rt/lowstate sub (domain=1 iface=lo)
...
```

Pass criteria:

1. Arms hold their default pose (no visible flailing).
2. `gravity_z` does not appear in the watchdog log during idle (i.e.
   it stays below -0.85).
3. After "Hi Sparky, walk forward" → confirm `y` → robot walks one
   step and stops; no fall in the following 30 s.
4. ALSA underrun lines, if any, are sparse (one or two at most), not
   continuous.
5. `[g1_brain confirm] execute walk(...) ? press y to accept ...` —
   pressing `y` (no Enter) is enough.
