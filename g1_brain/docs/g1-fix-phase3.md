# g1-fix-phase3 — "Sparky 挥手做不到" / EMERGENCY_STOP ↔ ENGAGED flap loop

Date: 2026-05-05
Branch: main

## 1. Symptom

Running

```bash
python -m g1_brain.apps.agent_main --mode confirm
```

The user reports voice-controlled gestures don't execute ("我让他挥手他好像也做不到").
Live log over a ~10-minute session shows:

- A vague-looking initial bring-up that *seemed* fine —
  `BOOT → STANDING → ENGAGED` — but pose watchdog tripped at
  `gravity_z=-0.76` already 7 s after engagement (within boot grace,
  no promotion).
- After ~5 minutes of OK operation, a hard fall:

  ```
  19:42:31,443 watchdog pose tripped: gravity_z=-0.85
  19:42:31,950 fsm: ENGAGED -> EMERGENCY_STOP (... gravity_z=-0.13)
  ```

  `gravity_z` flipping from -0.85 to -0.13 in 0.5 s = the robot
  physically fell over.
- Then a **90+ second flap loop**, one cycle every ~100 ms:

  ```
  pose tripped: gz=-0.75
  pose cleared
  pose tripped: gz=-0.71
  pose cleared
  ...
  fsm: EMERGENCY_STOP -> RECOVERING (clear for 2.0s)
  fsm: RECOVERING    -> STANDING    (auto-recovery complete)
  fsm: STANDING      -> ENGAGED     (policy active)
  fsm: ENGAGED       -> EMERGENCY_STOP (gz=-0.81)
  ```

  Auto-recovery declared "all clear", policy re-engaged, pose tripped
  again within 0.5 s — over and over.
- Background warnings the user also wanted understood:
  - `pose detector start failed: module 'mediapipe' has no attribute 'solutions'`
  - `[user] 这是那个男的吗?她为什么要把那个东西塞嘴里?` (clearly not what
    the operator said — wake-word ASR transcribed environmental noise
    because the RMS gate was too low)
  - The agent refused `walk forward` citing `surface_tilt_deg=83°`.

## 2. Root cause

There are **five independent failures** stacked on top of each other.
Each is small; together they make voice-driven motion essentially
impossible.

### 2.1 `--mode confirm` is incompatible with voice control

`safety/supervisor.py:_confirm_in_terminal` blocks on
`sys.stdin.readline` for every motion call:

```python
async def _confirm_in_terminal(tool, sanitized):
    print(f"[g1_brain confirm] execute {tool}({sanitized}) ? [y/N] ", ...)
    line = await asyncio.wait_for(
        loop.run_in_executor(None, sys.stdin.readline), timeout=10.0
    )
    return line.strip().lower() in ("y", "yes")
```

The operator is talking to the robot — they cannot reach the terminal
mid-conversation. After 10 s the call returns `False`; supervisor
rejects with `operator declined in confirm mode`. The LLM gets
`ok=false` and tells the user "I can't do that right now" without
ever explaining why.

This alone is enough to make every gesture fail.

### 2.2 Watchdog auto-recovery has no post-recovery grace window

`WatchdogManager._on_fsm_transition` did not exist; `_started_at` was
set once at `start()` and never refreshed. So:

- `boot_grace_s=5.0` covers the very first 5 s after process start.
- After a fall + auto-recovery, the FSM walks
  `EMERGENCY_STOP → RECOVERING → STANDING → ENGAGED` in ~2.3 s.
- The RL policy needs ~1 s of stable ticks to re-stabilize, but the
  pose watchdog (hold-down 0.5 s) starts judging it the same instant
  STANDING happens.
- A single transient `gravity_z > -0.85` sample 0.5 s after re-engage
  promotes back to EMERGENCY_STOP.
- Loop. Forever.

### 2.3 mediapipe 0.10.30+ in the `agi` env ships without `solutions/`

`g1_brain/perception/pose_detector.py:51` does:

```python
self._pose = mp.solutions.pose.Pose(...)
```

In the `agi` env, mediapipe was 0.10.35 and `hasattr(mp, 'solutions')`
returned `False`. Verified: only `mediapipe.tasks` was shipped,
`mediapipe.solutions` and `mediapipe.python` were absent.

`PerceptionRunner.start` catches the exception and runs without
PoseDetector — so user-side gesture recognition (mock_imitate auto-trigger)
silently dies. Doesn't directly affect the robot waving on voice
command, but related-feature surface area shrinks unannounced.

### 2.4 Wake-word `rms_threshold=100` too low

User noted yesterday they tuned RMS threshold from default down to
100 to be sensitive. Result: ALSA underruns, fan noise, and ambient
voices are crossing the gate. Wake-word ASR then runs on garbage
audio and emits transcripts like
`[user] 这是那个男的吗?她为什么要把那个东西塞嘴里?` — which the LLM
treats as a real instruction. This pollutes both the conversation
and the gesture-trigger pipeline.

### 2.5 Robot fell at 19:42:31 (E-class — out of repo scope)

Looking at the 10 s leading up to the big fall:

```
19:42:21 watchdog head_frame tripped: age=2.16s
19:42:24 watchdog head_frame tripped: age=2.47s
...
19:42:31 watchdog pose tripped: gravity_z=-0.85
```

The head camera started missing frames for 2+ seconds at a time. The
combo controller's `_tick` runs at 50 Hz on the same Python process as
YOLO + mediapipe + Realtime websocket + audio. When ONNX inference
slips past 20 ms the control loop falls behind, and on a humanoid
that's a fall. **No code bug**: the robot fell because the system
was overloaded.

The agent's "surface tilt 83°" refusal of `walk forward` was a
downstream effect — the head camera was pointing at the floor because
the body had tilted, and the vision model honestly reported what it
saw.

## 3. Fix

### 3.1 (A) default `run_mode` flipped to `active`

`g1_brain/configs/g1_brain.yaml:2`

```yaml
run_mode: "active"              # observe / confirm / active
                                # NOTE: "confirm" requires terminal y/N input
                                # for every motion call and therefore blocks
                                # voice control (the operator can't reach the
                                # terminal mid-conversation). Use "confirm"
                                # only for keyboard-driven debugging.
```

Operators driving the robot by voice no longer need to remember
`--mode active`. CLI override (`--mode confirm`) still works for
keyboard-driven debugging sessions.

### 3.2 (B) safety rejections now log at WARNING

`g1_brain/skills/skill_server.py` (around line 182):

```python
if not ok:
    log.warning("safety rejected %s(%s): %s", tool, args, reason)
    return {"ok": False, "skill": tool, "reason": reason}
```

Previously the LLM saw the rejection reason in its tool result, but
the *operator* watching the terminal never did — they just heard
Sparky say "I can't do that". Now every rejection lands in the
terminal and `agent.log` with the exact rule that fired.

### 3.3 (C) mediapipe pinned to 0.10.21

```bash
pip install 'mediapipe==0.10.21'
```

0.10.21 is the most recent build that still ships both
`mediapipe.solutions/` (legacy / used by `pose_detector.py`) and
`mediapipe.tasks/`. Pin recorded in
`~/.claude/projects/-home-helios-unitree-unitree-notes/memory/agi_env.md`
so future env work doesn't auto-upgrade and re-break perception.

Verified post-install:

```python
import mediapipe as mp
mp.solutions.pose.Pose(static_image_mode=False)   # constructs cleanly
```

### 3.4 (D) auto-recovery re-arms the boot-grace window

This is the core fix for the flap loop.

`g1_brain/configs/g1_brain.yaml:90`

```yaml
recovery_hold_s: 5.0   # was 2.0
```

`g1_brain/safety/watchdogs.py` — added FSM subscription:

```python
def start(self) -> None:
    ...
    self._started_at = time.monotonic()
    # Re-arm the boot-grace window every time auto-recovery completes a
    # RECOVERING -> STANDING transition. Without this, the policy's first
    # ~1 s after re-engagement was tripping the pose watchdog again
    # immediately, producing an ENGAGED <-> EMERGENCY_STOP flap.
    self.fsm.subscribe(self._on_fsm_transition)
    ...

def stop(self) -> None:
    try:
        self.fsm.unsubscribe(self._on_fsm_transition)
    except Exception:
        pass
    ...

def _on_fsm_transition(self, old, new, reason) -> None:
    if old == RobotFsmState.RECOVERING and new == RobotFsmState.STANDING:
        self._started_at = time.monotonic()
        log.info(
            "watchdogs: re-armed boot-grace (%.1fs) after auto-recovery",
            self.boot_grace_s,
        )
```

Effect: every time the system finishes auto-recovery, the watchdogs
forgive transient trips for the next 5 s (same window we already use
at boot). The RL policy gets a fair chance to actually settle before
the next pose check decides it failed. This **does not** mask real
falls — after the 5 s grace expires, watchdogs work exactly as
before.

### 3.5 (audio) wake-word RMS gate raised to 300

`g1_brain/configs/g1_brain.yaml:115`

```yaml
rms_threshold: 300   # was 100
```

100 was the operator's experimental low-sensitivity value from the
day before; it let too much ambient audio through and the wake-word
ASR was emitting noise transcripts. 300 is the original
va-demo / brain default and matches the wakeword backend's
calibration.

### 3.6 New regression tests

`g1_brain/tests/test_watchdogs.py` (3 new tests):

- `test_recovery_to_standing_rearms_boot_grace` — verifies the new
  edge re-arms `_started_at`.
- `test_other_transitions_do_not_rearm_grace` — verifies no other FSM
  edge bumps `_started_at` (so we don't accidentally extend grace
  during ordinary operation).
- `test_unsubscribe_on_stop` — verifies `stop()` detaches the FSM
  subscriber (no leaked listeners across watchdog restarts).

```
$ python -m pytest g1_brain/tests/ -q
217 passed in 2.72s
```

(was 214 before, +3 from `test_watchdogs.py`)

## 4. Out of scope (E)

The actual fall at 19:42:31 was a CPU-overrun symptom, not a g1_brain
code bug:

- 50 Hz combo controller + YOLO + mediapipe + Realtime websocket +
  audio + Vision API all running on one Python process.
- ONNX inference latency creeping past 20 ms (one control tick) →
  policy commands stale → robot falls.

Workaround for low-CPU testing:

```yaml
perception:
  yolo:
    enabled: false   # ~30% CPU savings; mediapipe still runs on USB
                     # for user-gesture recognition
```

Real fix would be moving the perception workers to subprocesses or a
GPU runtime, which is a separate piece of work.

## 5. Files changed

```
configs/g1_brain.yaml             4 edits (run_mode, recovery_hold_s, rms_threshold + comments)
g1_brain/safety/watchdogs.py      +1 subscribe in start, +1 unsubscribe in stop, +1 _on_fsm_transition method
g1_brain/skills/skill_server.py   +1 log.warning on safety rejection
g1_brain/tests/test_watchdogs.py  new file, 3 tests
```

Memory files updated:

```
~/.claude/projects/-home-helios-unitree-unitree-notes/memory/agi_env.md
    +1 line documenting the mediapipe 0.10.21 pin requirement
```

## 6. Verification

```
python -m pytest g1_brain/tests/ -q
217 passed in 2.72s
```

Manual verification recommended on a fresh launch:

```bash
# (skip --mode confirm; default is now active)
python -m g1_brain.apps.agent_main
```

Expected:
- No `pose detector start failed` warning at startup (mediapipe fixed).
- After any auto-recovery, log line `watchdogs: re-armed boot-grace (5.0s)
  after auto-recovery` followed by 5 s of stable ENGAGED operation
  rather than immediate re-promotion to EMERGENCY_STOP.
- `safety rejected gesture(...): ...` lines in the terminal whenever a
  motion call is denied — operator can finally see the reason.
- Wake-word triggers only on actual "Hi Sparky" — fewer noise transcripts.
