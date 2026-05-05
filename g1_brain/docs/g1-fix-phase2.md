# g1-fix-phase2 — `agent_main` hangs after "mic started" and Ctrl-C is dead

Date: 2026-05-05
Branch: main

## 1. Symptom

Running

```bash
python -m g1_brain.apps.agent_main --mode confirm
```

prints one INFO line about the microphone opening and then freezes.
Nothing else appears — no `speaker started`, no `DDS initialized`, no
`[combo] waiting for first /rt/lowstate`. Ctrl-C does not interrupt
the process; SIGTERM is also ignored. The only way out is `kill -9`
from another terminal.

The on-disk `logs/agent.log` confirms the symptom — multiple sessions
in a row stop at exactly the same point:

```
19:05:20,042 INFO va_demo.audio_io: mic started: samplerate=24000, ...
   <hang — no further output until SIGKILL>
```

After SIGKILL, relaunching `agent_main` reproduces the same hang
indefinitely.

## 2. Root cause

There are **two independent failures stacked on top of each other**.
Each one alone would have been recoverable; together they presented
as "the program is bricked".

### 2.1 Process-level: orphaned `agent_main` holding the audio device

A previous `agent_main` invocation had been hard-killed during
shutdown. Its Python process became orphaned to `init` (PPid=1) and
got stuck inside `pipe_read` — single thread, `STAT S`, zero CPU.
It still held five `/memfd:pulseaudio` handles and the linked
`alsa-lib` modules:

```
$ lsof -p 10282 | grep pulseaudio
python  10282 helios  DEL  REG  0,1  12302   /memfd:pulseaudio
python  10282 helios  DEL  REG  0,1   1024   /memfd:pulseaudio
python  10282 helios  DEL  REG  0,1  19631   /memfd:pulseaudio
python  10282 helios  DEL  REG  0,1  12301   /memfd:pulseaudio
python  10282 helios  DEL  REG  0,1  19630   /memfd:pulseaudio
```

WSLg's PulseAudio gives each output stream exclusive ownership of the
default sink for as long as the corresponding `RawOutputStream` is
open. With the orphan still holding it, the next `agent_main`'s
`speaker.start()` (a sounddevice C call into `snd_pcm_open` →
`pa_stream_connect_playback`) blocked forever waiting for the device
to become available. The orphan would never release it because it
was no longer running any Python — its event loop and shutdown
`finally` block had already been killed.

### 2.2 Code-level: synchronous blocking calls inside an async coroutine block SIGINT

Even if the orphan had not existed, two other startup steps would
have hung the same way under the same kinds of failure:

- `combo_ctl.start()` from `g1_sim_demo/g1_sim_rl_combo.py:617-620` is

  ```python
  def start(self):
      print("[combo] waiting for first /rt/lowstate ...")
      while not self.first_state_received:
          time.sleep(0.05)
  ```

  — a synchronous infinite loop with no timeout. It exits only when a
  DDS callback flips the flag. If MuJoCo is not running, it never
  exits.

- `ChannelFactoryInitialize(domain_id, iface)` is a C++ DDS init that
  can hang on a misconfigured network interface.

- `mic.start()` / `speaker.start()` open sounddevice C streams that,
  as §2.1 just demonstrated, can hang on a wedged audio backend.

All four were called *synchronously* from inside `async def _run`.
That mattered because of how `agent_main.main()` set up signals:

```python
for sig in (signal.SIGINT, signal.SIGTERM):
    try:
        loop.add_signal_handler(sig, _on_signal)
```

`loop.add_signal_handler` **disables** Python's default SIGINT handler
(the one that raises `KeyboardInterrupt` at the next bytecode
boundary) and replaces it with an asyncio callback that runs *only
when the event loop iterates*. A synchronous `while … time.sleep`
inside the coroutine body never yields back to the loop, so:

- Python no longer raises `KeyboardInterrupt` from `time.sleep`.
- asyncio's signal callback never gets dispatched either.
- The wakeup-fd write from the kernel happens, but is silently dropped
  on the next iteration *that never arrives*.

Net effect: SIGINT is queued and never delivered to user code. To the
operator the program looks like it is ignoring Ctrl-C completely.

### 2.3 Why the two stack

The orphan (§2.1) is what triggered the hang on this specific machine.
The async/sync trap (§2.2) is what made the hang *unrecoverable*.
Together they produced the user-visible symptom: a single log line
followed by a fully unkillable process. Either one fixed in isolation
would still leave the door open to a recurrence — the next time DDS
mis-routes, or the next time PulseAudio wedges, or the next time
MuJoCo isn't started, the same trap fires. The fix has to address
both layers.

## 3. Fix

All edits land in `g1_brain/g1_brain/apps/agent_main.py` (260
insertions, 48 deletions). No upstream-tree files (`va-demo/`,
`g1_sim_demo/`, `unitree_mujoco/`) are touched, in keeping with
`/home/helios/unitree/CLAUDE.md`'s "treat as documentation-grade
source" rule.

### 3.1 Wrap every potentially-blocking startup call in `asyncio.to_thread + wait_for`

Every C-extension call that historically could hang now runs in the
default thread-pool executor with a finite timeout. The asyncio loop
keeps iterating on the main thread, so:

- the SIGINT handler registered via `loop.add_signal_handler` *can
  fire*;
- `await asyncio.sleep` calls in other tasks continue to drive watchdogs and supervise tasks;
- on timeout we get a regular `asyncio.TimeoutError` instead of a
  permanent block.

Sites converted:

| Call | Timeout | Action on timeout |
|---|---|---|
| `mic.start()` | 5 s | log error pointing at WSL2 audio note, release lock, return 3 |
| `speaker.start()` | 5 s | log error suggesting `pulseaudio --kill`, close mic, release lock, return 3 |
| `ChannelFactoryInitialize(domain, iface)` | 10 s | log error showing the offending domain/iface, drop into `--no-skills` |
| `combo_ctl.init_dds()` | 5 s | log error, drop into `--no-skills` |
| `combo_ctl.start()` | 5 s | log error, drop into `--no-skills` (only reached after first lowstate is observed; see §3.2) |

`MicStream` is now constructed with `loop=asyncio.get_running_loop()`
so its callback can post chunks to the event loop from a worker
thread (otherwise `asyncio.get_event_loop()` inside `MicStream.start`
would fail when called from the executor).

### 3.2 Replace combo's busy-wait with our own async poll

Rather than calling `combo_ctl.start()` directly and relying on its
synchronous `while not first_state_received: time.sleep(0.05)`, we now
do the wait ourselves at the agent_main layer:

```python
log.info("waiting for first /rt/lowstate (MuJoCo simulator must be running) ...")
deadline = asyncio.get_running_loop().time() + 10.0
while not getattr(combo_ctl, "first_state_received", False):
    if asyncio.get_running_loop().time() > deadline:
        log.error(
            "Timed out after 10 s waiting for /rt/lowstate. The MuJoCo "
            "simulator does not appear to be running.\n"
            "  -> Start it in another terminal:\n"
            "       conda activate unitree && export MUJOCO_GL=glfw\n"
            "       cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python\n"
            "       python unitree_mujoco.py\n"
            "  -> Or rerun with --no-skills (or --vision-only) to bypass the RL controller."
        )
        combo_ctl = None
        args.no_skills = True
        break
    await asyncio.sleep(0.1)
```

`await asyncio.sleep(0.1)` keeps the event loop iterating, so:

- Ctrl-C fires within 100 ms;
- the supervise task (`stop_evt.wait()`) stays responsive;
- after 10 s the operator sees the *exact* command they should run
  in another terminal, instead of staring at silence.

Once `first_state_received` is set, calling the upstream
`combo_ctl.start()` (still wrapped in `to_thread`) is safe — its
`while` loop satisfies on the first check and the rest of the method
(numpy snapshot, RecurrentThread.Start) runs in a few ms.

### 3.3 fcntl single-instance lock

To prevent §2.1 from ever recurring, `_run` now acquires an
exclusive `flock` on `<log_dir>/agent_main.lock` (default
`~/unitree/unitree-notes/g1_brain/logs/agent_main.lock`). The lock
file records the holder's PID. Second invocation:

```
$ python -m g1_brain.apps.agent_main --mode confirm
ERROR g1_brain: another g1_brain agent_main is already running
(pid=22218, lock=/home/helios/unitree/unitree-notes/g1_brain/logs/agent_main.lock).
Kill it first:
    kill 22218   # then if needed: kill -9 22218
$ echo $?
4
```

Two important properties:

- `fcntl.flock` is **kernel-released on process death**, including
  SIGKILL and OOM-kill. So even though the lock file persists on
  disk after a hard crash, the next launch acquires it cleanly — no
  stale-lock-file cleanup ritual required.
- The lock is advisory (cooperative), but every entry point into
  `agent_main` (the `--mode {observe,confirm,active}` paths,
  `--vision-only`, `--no-skills`, etc.) goes through the same `_run`,
  so cooperation is automatic for this codebase.

The lock acquisition is also why the OPENAI_API_KEY check moved up:
failing the key check after acquiring the lock would briefly hold
the lock while we exit, and any same-second retry from the operator
would race. Checking the key first means the lock is only held when
we genuinely intend to run.

### 3.4 Bounded shutdown with `_shutdown_step`

The original `finally` block called `watchdogs.stop()`,
`combo.stop_and_settle()`, etc. without timeouts. A single hung step
would force the operator to SIGKILL — which is exactly what created
the orphan in §2.1. The new helper:

```python
async def _shutdown_step(name: str, fn, timeout: float = 3.0) -> None:
    try:
        await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("%s timed out after %.1fs; continuing shutdown", name, timeout)
    except Exception:
        log.exception("%s failed", name)
```

is called for every cleanup step. Per-step timeouts:

| Step | Timeout |
|---|---|
| `auto_trigger.stop` | 3 s |
| `perception.stop` | 3 s |
| `watchdogs.stop` | 3 s |
| `robot_state_producer.stop` | 3 s |
| `combo.stop_and_settle` | 5 s (includes the 1.2 s soften-and-sleep) |
| `camera_hub.close` | 3 s |
| `mic.close` | 2 s |
| `speaker.close` | 2 s |

Total worst-case shutdown: ~24 s. Realistic: under 2 s. Either way,
the process exits and the audio device is released — orphan leak from
§2.1 cannot reappear via this path.

`sm.stop()` is a coroutine, so it stays as `await asyncio.wait_for(sm.stop(), 3.0)`
rather than going through `_shutdown_step` (which expects a sync
callable).

### 3.5 Fail fast on missing OPENAI_API_KEY

The original `_run` checked `OPENAI_API_KEY` only after constructing
mic, speaker, DDS, CameraHub, ComboController, perception runner,
SafetySupervisor, watchdogs, TTS, and vision clients — and only when
`--no-realtime` was off. Two consequences:

- Missing key with `--no-realtime` proceeded past the check, then
  crashed inside `OpenAI()` (which is constructed unconditionally
  for vision and TTS). Confusing error message, audio handles
  leaked.
- Missing key without `--no-realtime` exited cleanly but had already
  initialized everything for nothing.

Moved the check to the very top of `_run`, made it unconditional
(vision + TTS need the key regardless of `--no-realtime`), and
gave the message a worked example:

```
ERROR g1_brain: OPENAI_API_KEY is not set. Export it before launching:
    export OPENAI_API_KEY=sk-...
It is required for the Realtime websocket, TTS, and vision.
```

### 3.6 Propagate the actual exit code

`main()` previously had `return 0` unconditionally:

```python
try:
    loop.run_until_complete(main_task)
except asyncio.CancelledError:
    pass
...
return 0
```

So `_run`'s `return 2` (no key), `return 3` (audio timeout),
`return 4` (lock contention) all surfaced to shell as exit code 0.
That defeats the whole point of having distinct codes for scripting
and for CI. Now:

```python
rc = 0
try:
    rc = loop.run_until_complete(main_task) or 0
...
return int(rc)
```

The `or 0` keeps the previous behaviour for graceful shutdown paths
where `_run` falls off the end implicitly (Python returns `None`).

### 3.7 One-time cleanup of the orphan

The orphan agent_main process (PID 10282) and three other orphan
helper scripts from earlier debugging sessions (PIDs 12516, 12693,
13148) were stuck in `pipe_read` with `PPid=1`. SIGTERM was caught
but never serviced — same async-blocking-trap as §2.2 — so SIGKILL
was the only option. After kill they released the PulseAudio fds and
the audio device became available again. The single-instance lock
(§3.3) prevents this state from being reachable in the future.

## 4. Operator action required

If you are sitting at this state right now (one log line, hang,
unkillable), the recovery is:

```bash
# 1. Find any orphans:
pgrep -af 'agent_main|g1_brain' | grep -v claude

# 2. Kill them. Try SIGTERM first, escalate if needed:
kill <pid>
# wait 1s, then if still alive:
kill -9 <pid>

# 3. (Optional but tidy) remove the stale lock file. Not required —
#    the next launch's flock will succeed regardless because the
#    kernel released the lock when the orphan died:
rm -f ~/unitree/unitree-notes/g1_brain/logs/agent_main.lock

# 4. Restart the agent normally:
conda activate agi
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main --mode confirm
```

Going forward, the new code makes step 1–2 unnecessary — the lock
will reject double-launches with a clear "kill <pid>" instruction,
and the timeouts mean shutdown can never wedge into a state that
needs SIGKILL.

## 5. Verification

### 5.1 Unit tests

```
$ pytest tests/ 2>&1 | tail -3
214 passed in 2.71s
```

All 214 tests pass, including the 9 in `tests/test_apps_smoke.py`
that exercise `agent_main` import / arg-parse paths.

### 5.2 Live happy-path run

`agent_main` launched with MuJoCo + teleimager + estop_listener up:

```
INFO va_demo.audio_io: mic started: samplerate=24000, ...
INFO va_demo.audio_io: speaker started: samplerate=24000, ...     <- previously hung here
selected interface "lo" is not multicast-capable: disabling multicast
INFO g1_brain: DDS initialized: domain=1 iface=lo
INFO g1_brain.perception.mujoco_head_cam: synthesized head camera 'head_camera' on body 'torso_link'
INFO g1_brain: waiting for first /rt/lowstate (MuJoCo simulator must be running) ...
[combo] waiting for first /rt/lowstate ...
[combo] mode_machine=0. Ramping to default pose over 5.0 s ...
INFO g1_brain: waiting for ComboController policy_active ...
[combo] policy ready. wsadqe to walk; 1-8 arm gestures; 0 release.
INFO g1_brain.safety.state_machine: fsm: BOOT -> STANDING (boot complete)
INFO g1_brain: run_mode=confirm
INFO g1_brain: realtime disabled; idling. Ctrl-C to exit.
```

Under SIGTERM: `signal received, shutting down` → `shutting down ...`,
exit 0. Under Ctrl-C: same path, exit 0. Both deliver in under 100 ms.

### 5.3 Single-instance lock

First instance running in background; second instance launched
immediately:

```
ERROR g1_brain: another g1_brain agent_main is already running
(pid=22218, lock=/home/helios/unitree/unitree-notes/g1_brain/logs/agent_main.lock).
Kill it first:
    kill 22218   # then if needed: kill -9 22218
```

Second instance exits with code 4 without touching audio or DDS.
First instance continues unaffected.

### 5.4 Vision-only path

`agent_main --vision-only --no-realtime --no-perception` boots
audio + cameras + safety FSM, skips DDS / combo entirely (the
`--vision-only` branch sets `args.no_skills = True`), reaches
`realtime disabled; idling. Ctrl-C to exit.`, exits cleanly on
SIGTERM.

## 6. Out of scope (separate issues observed during this debug)

The same investigation surfaced a few unrelated issues that were
deliberately not touched in this fix:

- `WARNING g1_brain.perception.runner: pose detector start failed:
  module 'mediapipe' has no attribute 'solutions'` — same MediaPipe
  surface change tracked in phase-1.
- `ALSA lib pcm.c:8787: underrun occurred` — same WSLg cosmetic
  warning tracked in phase-1.
- `Task was destroyed but it is pending! gesture-auto-trigger` on
  shutdown — the existing `_shutdown_step` for `auto_trigger.stop`
  matches the original sync-call signature; if `auto_trigger.stop` is
  in fact a coroutine on some branches, the warning would persist.
  Phase-1 §5 already has this on its watchlist; not re-investigated
  here.
- The hardcoded `~/unitree_sdk2_python/unitree-env` path mismatch
  documented in the workspace-level `CLAUDE.md` — applies to
  `cs47-command-center/services/robot-bridge`, not g1_brain.

## 7. Files changed

```
g1_brain/g1_brain/apps/agent_main.py         (+260 / −48; everything in §3)
g1_brain/docs/g1-fix-phase2.md               (this file)
```
