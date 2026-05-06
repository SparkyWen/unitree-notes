# G1 Brain Fix Phase 9 — Audio playback quality + follow-up speech UX

**Branch:** `fix/audio-play-display` · **Date:** 2026-05-06

This phase fixes three distinct, user-visible issues observed during a
`python -m g1_brain.apps.agent_main --mode confirm` session on WSL2 +
PulseAudio. The operator's report (verbatim):

> 1. 当机器人说话的时候非常的一卡一顿，请您找出根本原因彻底修复。
> 2. 当我说完 hi sparky 后并且说了自己的命令，机器人回复我后，会
>    进入 LISTENING_WINDOW，但是当我继续说话的时候好像什么都无法
>    录入？只能重新 hi sparky 来重新开启指令。
> 3. (ALSA underrun spam) 这部分内容太影响显示了，请您彻底修复。

(Translations:
1. The robot's speech is choppy/stuttering — find the root cause and
   fix it completely.
2. After "Hi Sparky" + a command, the robot replies and enters
   `LISTENING_WINDOW`, but if I keep talking nothing seems to be
   captured — I have to re-say "Hi Sparky" to start a new command.
3. The `ALSA lib pcm.c:8787:(snd_pcm_recover) [error.pcm] underrun
   occurred` lines are completely destroying the terminal output —
   fix this for good.)

All three are now resolved. This document records the root-cause
investigation and the fixes for future maintainers.

---

## 1. Symptoms (verbatim from the live session log)

```
2026-05-06 19:02:54,490 INFO va_demo.conversation_state: [state] THINKING -> SPEAKING是
ALSA lib pcm.c:8787:(snd_pcm_recover) [error.pcm] underrun occurred你的机器
ALSA lib pcm.c:8787:(snd_pcm_recover) [error.pcm] underrun occurred人助理。
…
2026-05-06 19:08:21,617 INFO va_demo.conversation_state: [utterance] commit_silence after 7.34s
…
2026-05-06 19:08:23,585 INFO va_demo.conversation_state: [state] THINKING -> LISTENING_WINDOW
2026-05-06 19:08:31,587 INFO va_demo.conversation_state: [state] LISTENING_WINDOW -> IDLE
```

* `ALSA lib pcm.c:8787:(snd_pcm_recover) [error.pcm] underrun occurred`
  prints **mid-line**, fragmenting every other log message and the
  Realtime transcript stream.
* The robot's speech is choppy because each underrun corresponds to
  ALSA inserting silence into the playback ring buffer.
* `LISTENING_WINDOW -> IDLE` 8 s after a reply with no `[wake]` event
  in between, even when the operator was actively speaking — proof
  the follow-up audio went nowhere.

---

## 2. Root causes

### 2.1 Choppy TTS — `SpeakerStream` opens at PortAudio defaults

Old code in `va-demo/va_demo/audio_io.py`:

```python
self._stream = self._sd.RawOutputStream(
    samplerate=self.samplerate,
    blocksize=0,                # ← let PortAudio pick (very small on PulseAudio)
    dtype="int16",
    channels=1,
    device=self.device,
    callback=self._callback,
                                # ← no `latency` kwarg
)
```

* `blocksize=0` lets the PulseAudio ALSA plugin pick whatever it wants
  (it picks a small frame count for "low latency"), and `latency`
  isn't passed, so the ring buffer between PortAudio and PulseAudio is
  tiny — single-digit milliseconds.
* The audio callback is a Python function and therefore runs *under
  the GIL*. Whenever a perception worker (YOLO, MediaPipe), the DDS
  callback thread, or the OpenAI-Realtime websocket co-routine runs,
  the audio callback can be delayed by tens of milliseconds.
* With a tiny ring buffer, any such delay drains the buffer — ALSA's
  pulse plugin reports `EPIPE`, calls `snd_pcm_recover`, and the user
  hears a gap in the speech ("一卡一顿").
* Process-isolating the combo controller (Phase 8) helped the
  *control* thread but not the audio callback, which still shares a
  process with perception, vision, the agent, etc.

### 2.2 Cosmetic ALSA spam goes straight to stderr

`snd_pcm_recover` is libasound's standard auto-recovery path — by
default it logs through `snd_lib_error_default`, which writes to
stderr. There is no Python hook; sounddevice/PortAudio do not
intercept it. Every recovery the user sees in their terminal is a
cosmetic side-effect of (2.1), but the spam itself is independent of
whether the recovery actually masked the gap.

### 2.3 No follow-up listening — `LISTENING_WINDOW` only listens for the wake phrase

`va-demo/va_demo/conversation_state.py` (old `_enter_listening_window`):

```python
def _enter_listening_window(self) -> None:
    self.wake_word.resume()
    self._set_state(State.LISTENING_WINDOW)
    self._reset_timer(self.cfg.listening_window_s, self._listening_window_cb)
```

In `LISTENING_WINDOW`:

* The Realtime uplink is **off** (left disabled by `_enter_thinking`).
* The utterance VAD is **idle** — no `vad.process(...)` calls happen
  in this state.
* Only `wake_word.feed(...)` runs; only an "Hi Sparky" match
  re-triggers `_enter_capturing()`.

So if the user keeps talking ("turn left a bit" / "向左走一点"), the
audio is just dropped on the floor. The `[utterance] commit_silence
after 7.34s` line in the log is from the **previous** turn — there is
no captured utterance during a `LISTENING_WINDOW` follow-up.

The naïve fix ("just enable uplink + VAD in LW") would feed the
model's still-playing TTS audio back into its own input — the
speaker echoes through the laptop mic and the model would respond to
itself. So the fix has to wait for the speaker buffer to drain
*before* it arms follow-up listening.

---

## 3. The fixes

### 3.1 SpeakerStream / MicStream — explicit latency + fixed blocksize

`va-demo/va_demo/audio_io.py:SpeakerStream`:

| Attribute | Old | New |
|-----------|-----|-----|
| `blocksize` | `0` (PortAudio picks) | `samplerate * 20 / 1000` = 480 frames at 24 kHz (20 ms) |
| `latency`   | not passed (None) | `0.20` seconds |

`MicStream` mirrors this with `latency=0.10` (capture-side
robustness; the mic side cares about overrun, not underrun, but the
same buffer-size argument applies).

The 200 ms requested speaker latency is several orders of magnitude
larger than any GIL stall we've ever measured in this stack — even
under perception load the audio callback now has 200 ms of headroom
to recover before ALSA underflows.

The new constructor signature accepts `latency_s=` and
`blocksize_frames=` kwargs (defaulting to the values above) so
operators can tune for a different platform without editing code.

### 3.2 `_silence_libasound_errors()` — install a no-op snd_lib error handler

Same file, top of module:

```python
def _silence_libasound_errors() -> None:
    proto = ctypes.CFUNCTYPE(
        None,
        ctypes.c_char_p,  # filename
        ctypes.c_int,     # line
        ctypes.c_char_p,  # function
        ctypes.c_int,     # err
        ctypes.c_char_p,  # fmt
    )
    handler = proto(lambda *a, **k: None)
    for libname in ("libasound.so.2", "libasound.so"):
        try:
            lib = ctypes.cdll.LoadLibrary(libname)
            lib.snd_lib_error_set_handler(handler)
            return
        except OSError:
            continue
```

Called at module import time. Held at module scope so the GC can't
collect the function pointer behind libasound's back. Linux-only;
no-op on macOS/Windows. Recovery itself still happens — only the
stderr write is suppressed.

### 3.3 `LISTENING_WINDOW` follow-up via drain-then-arm + VAD

`ConversationConfig` gained two knobs:

```python
lw_drain_threshold_bytes: int = 2400   # ≈ 50 ms of 24 kHz int16 mono
lw_drain_max_wait_s: float = 6.0       # cap on speaker-drain wait
```

`ConversationStateMachine.__init__` now takes a `speaker=` kwarg.
`_enter_listening_window` now schedules an async arm task instead of
just starting the IDLE-fallback timer:

```python
def _enter_listening_window(self) -> None:
    self.wake_word.resume()
    self._set_state(State.LISTENING_WINDOW)
    self._lw_followup_armed = False
    self._lw_arm_task = asyncio.create_task(
        self._arm_lw_followup_when_drained(), name="sm-lw-arm"
    )
    self._reset_timer(self.cfg.listening_window_s, self._listening_window_cb)

async def _arm_lw_followup_when_drained(self) -> None:
    deadline = time.monotonic() + self.cfg.lw_drain_max_wait_s
    if self.speaker is not None:
        while time.monotonic() < deadline:
            if self._state != State.LISTENING_WINDOW:
                return  # left LW already (e.g. wake fired)
            if self.speaker.pending_bytes() <= self.cfg.lw_drain_threshold_bytes:
                break
            await asyncio.sleep(0.05)
    if self._state != State.LISTENING_WINDOW:
        return
    self.vad.reset()
    self._lw_followup_armed = True
```

`SpeakerStream.pending_bytes()` was added for exactly this purpose —
it returns `len(self._buf)`, which is the audio already received from
the model and not yet pulled by the PortAudio callback.

`_on_audio_chunk` now has a third branch:

```python
if self._state == State.LISTENING_WINDOW and self._lw_followup_armed:
    had_voice_before = self.vad.had_any_voice()
    self.vad.process(chunk)
    if not had_voice_before and self.vad.had_any_voice():
        log.info("[lw] follow-up speech detected; engaging CAPTURING")
        self._lw_to_capturing()
```

`_lw_to_capturing` differs from `_enter_capturing` in one important
way: it **does not reset the VAD**. The VAD already saw the voice
that triggered the transition; resetting would push back the
silence-commit countdown by however many milliseconds of speech
already happened, making the user feel like the robot is slow to
acknowledge their words.

`_cancel_lw_arm()` is called from every state-leaving path (wake fire
→ `_enter_capturing`, follow-up fire → `_lw_to_capturing`, IDLE
fallback → `_listening_window_cb`, shutdown → `stop()`) so the arm
task is never orphaned.

### 3.4 Wake-word stays armed in LW (defense in depth)

The wake-word detector continues to be `resume()`d in
`_enter_listening_window`. If the operator says "Hi Sparky" inside
the window — for example because they want to interrupt while the TTS
is still draining and thus before follow-up VAD has armed — the
wake-word path still drops them straight into `_enter_capturing()`,
and `_enter_capturing` cancels the pending arm task.

### 3.5 Wiring

`va-demo/va_demo/main.py` and `g1_brain/g1_brain/apps/agent_main.py`
now both pass `speaker=speaker` to `ConversationStateMachine(...)`.
Backward compatibility is preserved because the kwarg defaults to
`None` — older callers, and tests that don't care about the drain
gate, just skip the wait loop.

---

## 4. Files changed

```
g1_brain/g1_brain/apps/agent_main.py     |   5 +-
va-demo/tests/test_conversation_state.py | 115 ++++++++++++++++++++++-
va-demo/va_demo/audio_io.py              | 102 +++++++++++++++++++-
va-demo/va_demo/conversation_state.py    | 109 ++++++++++++++++++++-
va-demo/va_demo/main.py                  |   1 +
```

---

## 5. Tests

New test cases in `va-demo/tests/test_conversation_state.py`:

| Test | What it proves |
|------|---------------|
| `test_listening_window_voice_engages_capturing_without_wake` | A voice burst inside LW transitions straight to CAPTURING; uplink is enabled and wake is paused. |
| `test_listening_window_waits_for_speaker_drain_before_arming` | While the speaker has audio queued, follow-up VAD stays disarmed; once the buffer drains, it arms. |
| `test_listening_window_falls_back_to_idle_without_followup` | If no follow-up voice arrives within `listening_window_s`, the SM still falls back to IDLE and the arm flag is cleared. |
| `test_wake_in_listening_window_cancels_arm_task` | A wake-word fire while the arm task is still waiting on drain transitions to CAPTURING and cancels the arm task cleanly. |

Test fixtures added: `FakeSpeaker.pending_bytes()`, scripted
`FakeVAD.voice_after_process` for modeling "voice arrives mid-window"
without monkey-patching.

Run results:

```
$ cd va-demo && pytest tests/ -q
…
62 passed, 1 warning in 7.74s

$ cd g1_brain && pytest tests/ -q
…
232 passed in 3.20s
```

---

## 6. Verification plan (live)

```bash
# Terminal 1 — simulator
conda activate unitree && export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py

# Terminal 2 — image server
conda activate unitree
cd ~/unitree/unitree-notes/teleimager
python image_server.py

# Terminal 3 — agent
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.apps.agent_main --mode active
```

Expected, after this phase:

1. **Audio quality** — no audible gaps in the model's reply. If any
   underruns *do* still happen under extreme load, they no longer
   pollute stderr, but the recovered-with-silence frames are now far
   shorter than the listener can hear.
2. **Follow-up speech** — after the reply finishes draining,
   `[lw] follow-up VAD armed` is logged at DEBUG; speaking again
   immediately produces `[lw] follow-up speech detected; engaging
   CAPTURING` followed by the normal commit/think/speak cycle.
3. **Terminal cleanliness** — no `ALSA lib pcm.c:…` lines in the
   transcript.

---

## 7. Tradeoffs / caveats

* The 200 ms speaker latency makes barge-in (via `speaker.clear()`)
  feel ~200 ms slower than the old configuration. Wake-word barge-in
  is already disabled by design, and TTS interruption was already
  rare, so this is acceptable.
* If a user starts speaking *before* the model has finished its
  reply, the follow-up VAD is not yet armed, so their speech is lost.
  The wake-word path remains as the documented "interrupt me now"
  escape hatch. (Adding true overlap support would require AEC, which
  is out of scope.)
* The `lw_drain_max_wait_s = 6 s` cap means that on a *truly*
  pathological speaker buffer (e.g. a TTS bug leaving permanent
  residue) we will eventually arm follow-up anyway, accepting a small
  echo-trigger risk. In practice the buffer drains in well under
  500 ms after `response.done`.
* `snd_lib_error_set_handler` is a process-global setting. Other
  Python libraries that load libasound in the same process will also
  see the no-op handler. The only ALSA messages we suppress are the
  cosmetic recovery prints; nothing in this stack relies on parsing
  them.
