# va-demo Wake-Word + Barge-in Redesign

**Status:** approved (decisions confirmed in brainstorming session 2026-05-04)
**Branch:** `feature/audio-fix`
**Target:** runs in MuJoCo sim end-to-end before any real-robot work

---

## 1. Problem

The current `realtime_agent.py` uses OpenAI Realtime's `server_vad` for turn
detection. Two failure modes in practice:

1. **Self-interruption.** `speaker.clear()` fires whenever
   `input_audio_buffer.speech_started` is received. The mic picks up Sparky's
   own TTS playback, server VAD thinks the user is talking, Sparky cuts itself
   off mid-reply. The "answer" is never finished, and the model has no idea
   what it just said because its own audio was never streamed back.
2. **Hair-trigger turn-taking.** Server VAD commits at 500 ms of silence with
   no prior gating, so any cough, throat-clear, or short backchannel becomes
   a request the model tries to answer.

## 2. Goals

* A wake word ("**Hi, Sparky**") gates Realtime processing — no audio is
  committed to the model until it fires.
* Sparky's own TTS playback never interrupts itself.
* The user **can** interrupt Sparky mid-sentence, but only by saying the
  wake word — random side-chatter does not.
* After the wake word fires, the user speaks their request; when they finish
  (silence), the entire utterance is committed to the model in one shot.
* Brief follow-up window after Sparky replies, so a natural multi-turn
  exchange does not require re-saying the wake word every time.

## 3. Decisions (already approved)

| # | Decision | Value |
|---|---|---|
| 1 | Wake-word detector | `faster-whisper` `tiny` (int8), CPU, ~75 MB one-time download |
| 2 | Conversation lifecycle | Single utterance per wake, **plus** `LISTENING_WINDOW = 8 s` post-reply |
| 3 | Self-echo protection | Prompt rule (Sparky never says "Sparky") + RMS gate on mic + last-spoken-text dedup |
| 4 | End-of-utterance detection | `webrtcvad` aggressiveness 2, **silence_threshold = 1500 ms**, **max_utterance = 30 s** |

## 4. Architecture

```
            ┌──────────────────────────┐
            │   MicStream (modified)   │  PCM16 24 kHz, 50 ms blocks
            │   adds .subscribe() fan- │
            │   out so multiple        │
            │   listeners share one    │
            │   capture stream         │
            └────────────┬─────────────┘
                         │
                ┌────────┴─────────┬──────────────────┐
                ▼                  ▼                  ▼
   ┌────────────────────┐ ┌─────────────────┐ ┌──────────────────┐
   │ WakeWordDetector   │ │ UtteranceVAD    │ │ Realtime uplink  │
   │ (new, faster-      │ │ (new, webrtcvad)│ │ (in realtime_    │
   │  whisper tiny,     │ │                 │ │  agent, modified)│
   │  resamples 24k→16k)│ │ resamples 24k→  │ │                  │
   │                    │ │ 16k for vad     │ │ append gated     │
   │ runs always        │ │                 │ │ by state machine │
   │ except CAPTURING   │ │ runs only in    │ │                  │
   │                    │ │ CAPTURING       │ │ runs only in     │
   │                    │ │                 │ │ CAPTURING        │
   └─────────┬──────────┘ └────────┬────────┘ └────────┬─────────┘
             │ wake event           │ silence event     │ rt events
             ▼                      ▼                   ▼
    ┌──────────────────────────────────────────────────────────────┐
    │     ConversationStateMachine (new)                           │
    │     IDLE → AWAKE → CAPTURING → THINKING → SPEAKING →         │
    │     LISTENING_WINDOW → (IDLE or AWAKE)                       │
    └──────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
       SpeakerStream   Realtime WS    SpokenTranscript
       (existing,      (existing,     Cache (new) — used
       clears only     session.update by wake-word dedup
       on wake-word    sets           and by tts.py to
       interrupt)      turn_detection record what Sparky
                       = null)        is currently saying
```

## 5. State Machine

```
                     wake match
                ┌──────────────────────►  AWAKE  (transient, ~0 ms;
                │                           emits "I'm listening" log)
                │                           │
                │                           ▼
              IDLE                     CAPTURING
              ▲ ▲                          │
              │ │                          │ silence ≥ silence_threshold_ms
              │ │                          │   OR length ≥ max_utterance_s
              │ │                          ▼
              │ │   no_speech_timeout    THINKING  (commit + response.create
              │ └────────────────────────  │       sent; waiting for first
              │     (4 s default)          │       audio delta)
              │                            ▼
              │  window expires        SPEAKING  (response.audio.delta →
              │ ┌────────────────────────  │      speaker.write loop)
              │ │                          │
              │ │                          │ response.done
              │ │                          ▼
              │ └─────────────  LISTENING_WINDOW  (8 s; speech > RMS gate
              │                            │      → CAPTURING without
              │                            │      requiring wake word)
              ▼                            │
              IDLE                         ▼
                                 (if speech)→ CAPTURING

   Special edges:
   * SPEAKING + wake match → cancel response → speaker.clear() →
     enter CAPTURING immediately. (User barge-in via wake word.)
   * THINKING + wake match → response.cancel → AWAKE → CAPTURING.
   * Any state + ws error / shutdown → IDLE.
```

### State responsibilities

* **IDLE** — wake-word detector active; uplink to Realtime suppressed; speaker
  silent.
* **AWAKE** — internal, lasts < 1 ms; logs `"[wake] Hi, Sparky"`; emits an
  optional 100 ms "ding" cue (configurable, off by default for the demo);
  flips audio router so subsequent chunks go to **both** uplink and utterance
  VAD; resets utterance VAD silence/length counters.
* **CAPTURING** — uplink active; utterance VAD active; wake-word detector
  paused (we already know we're talking). On commit trigger: send
  `input_audio_buffer.commit` + `response.create`, transition to THINKING.
* **THINKING** — wake-word detector resumes; uplink suppressed; waits for
  `response.audio.delta` to flip to SPEAKING. If `response.done` arrives
  with no audio (e.g. the model only made a tool call and is now waiting on
  the result), stay in THINKING.
* **SPEAKING** — same as THINKING for audio routing, plus
  `speaker.write()` is being driven by downlink. Wake-word match here is the
  only thing that interrupts.
* **LISTENING_WINDOW** — wake-word detector active **and** a low-pass speech
  detector (RMS > rms_threshold for ≥ 300 ms) is active. Either one
  transitions us back into CAPTURING (RMS gate fires AWAKE→CAPTURING
  immediately; wake word same). Timer 8 s (config) → IDLE.

## 6. Wake-Word Detector

`va_demo/wake_word.py`:

* Background `threading.Thread` (not asyncio — faster-whisper is blocking)
* Maintains a deque of the last `rolling_window_s` (1.5 s default) of mic
  audio at 24 kHz; resamples to 16 kHz on inference
* Inference loop runs at `inference_rate_hz` (2 Hz default)
* Each transcription pass:
  1. Skip if no audio added since last pass (deque watermark unchanged).
  2. Compute RMS of the latest 1 s; skip if RMS < `rms_threshold` (default
     1500 for int16; tune in config).
  3. Run `model.transcribe(buffer, language=None, vad_filter=True,
     beam_size=1, no_speech_threshold=0.6)`.
  4. Lowercase the transcript, normalize whitespace, strip punctuation.
  5. Match against any phrase in `phrases:` list (substring match).
  6. **Self-echo dedup:** if the matched phrase appears in
     `SpokenTranscriptCache.recent_text(window_s=6.0)`, skip.
  7. **Cooldown:** if `time.monotonic() - last_fire < cooldown_s` (default
     2 s), skip.
  8. Otherwise post a `WakeEvent(text=transcript, t=now)` to the state
     machine via `loop.call_soon_threadsafe`.

The detector exposes a `pause()` / `resume()` pair the state machine uses
when entering / leaving CAPTURING (to save CPU and avoid trying to match the
user's own request as a wake).

**Failure mode:** if `from faster_whisper import WhisperModel` raises (model
not installed, model file missing, etc.), `wake_word.py` logs `WARN`, prints
a one-time setup hint to stderr, and exposes a no-op detector that never
fires. The state machine then stays IDLE forever — i.e. the demo refuses to
process any speech rather than falling back to the old hair-trigger
behavior. (Documented in README.)

## 7. Utterance VAD

`va_demo/utterance_vad.py`:

* Wraps `webrtcvad.Vad(2)`
* Resamples 24 kHz → 16 kHz (linear; `signal.resample_poly` if scipy
  available, else stride-decimate; precision is fine for VAD)
* Frames audio into 30 ms windows (480 samples @ 16 kHz)
* Tracks two counters:
  * `consecutive_silence_ms` — reset to 0 on any voiced frame
  * `total_duration_ms` — wall clock since CAPTURING entered
* Returns one of `"continue" | "commit_silence" | "commit_max"`:
  * `commit_silence` if `consecutive_silence_ms ≥ silence_threshold_ms`
    AND we have heard at least one voiced frame
  * `commit_max` if `total_duration_ms ≥ max_duration_s * 1000`
* Also exposes `had_any_voice()` so the state machine can detect false
  triggers (wake word fired but user said nothing) → fall back to IDLE
  after `no_speech_timeout_s` (4 s).

## 8. Self-Echo Dedup (`SpokenTranscriptCache`)

`va_demo/spoken_cache.py`: thread-safe ring buffer of recent
`(text, timestamp)` segments.

Writers:
* `RealtimeAgent` writes each `response.audio_transcript.delta` and the
  full text on `response.audio_transcript.done`.
* `TTSClient.speak(text)` writes `text` itself before streaming PCM into
  the speaker.

Reader: `WakeWordDetector.recent_text(window_s)` joins all segments whose
timestamp is within the window and returns lowercased.

Eviction: when the cache size is read, anything older than 30 s is dropped.

## 9. Audio Router

Today, `MicStream` writes PCM chunks into a single `asyncio.Queue` consumed
by `_uplink()`. We add a fan-out:

```python
class MicStream:
    def subscribe(self) -> asyncio.Queue: ...   # new
    def unsubscribe(self, q: asyncio.Queue): ...  # new
    # legacy .queue stays for backward compat — points at the first subscriber
```

Both `WakeWordDetector` (via a thread-side wrapper that bridges queue → deque)
and the Realtime uplink subscribe.

**Important:** the wake-word detector subscribes once and consumes its queue
even when paused (just discards). This avoids unbounded growth.

## 10. Realtime Session Changes

In `realtime_agent.py` `_session_update()`:

```python
"turn_detection": None,                           # was server_vad
# input_audio_transcription stays on, useful for logs / cache
```

Drop the auto-`speaker.clear()` from the
`input_audio_buffer.speech_started` branch (state machine controls it now).

New methods on `RealtimeAgent` that the state machine calls:

* `commit_and_respond()` — send `input_audio_buffer.commit` then
  `response.create`
* `cancel_response()` — send `response.cancel`, then `speaker.clear()`
* `set_uplink_enabled(bool)` — gates whether `_uplink()` actually appends
  (the easy implementation: an `asyncio.Event` `_uplink_enabled` checked
  inside the loop).

The existing tool-call handling (`_dispatch_tool` etc.) is unchanged.

## 11. Configuration (additions to `configs/va_demo.yaml`)

```yaml
wakeword:
  enabled: true
  model_size: tiny           # tiny / base / small (faster-whisper)
  compute_type: int8         # int8 / float16 / float32
  device: cpu                # cpu / cuda
  rolling_window_s: 1.5
  inference_rate_hz: 2.0
  rms_threshold: 1500        # int16 RMS; tune for your mic level
  cooldown_s: 2.0
  language: null             # null = auto detect; "en", "zh" force
  phrases:
    - "hi sparky"
    - "hey sparky"
    - "hi sparkie"
    - "嗨 sparky"
    - "你好 sparky"

utterance:
  silence_threshold_ms: 1500
  max_duration_s: 30.0
  vad_aggressiveness: 2
  no_speech_timeout_s: 4.0   # AWAKE → IDLE if user said nothing

conversation:
  listening_window_s: 8.0
  selfecho_dedup_window_s: 6.0
  rms_gate_during_window: 1500
```

CLI flag: `--no-wakeword` to disable wake-word gating (degrades to old
always-on Realtime behavior — useful for A/B debugging).

## 12. Prompts

Add to `REALTIME_SYSTEM_PROMPT`:

> You are addressed as "Sparky" by the user but you must NEVER refer to
> yourself by that name in your replies. Say "I" instead. This avoids
> confusing the wake-word detector.

## 13. Error Handling

| Failure | Behavior |
|---|---|
| `faster-whisper` not installed / model download fails | Log error, print one-time setup hint, run with detector disabled; if `wakeword.enabled = true`, refuse all Realtime processing (state machine stays IDLE). |
| `webrtcvad` not installed | Log error; fall back to a fixed 5 s record window with a warning. |
| Wake-word inference > inference period (CPU saturation) | Worker drops backlog older than `rolling_window_s`; logs at most once per minute. |
| Wake fires during THINKING | `cancel_response()`, then proceed to AWAKE → CAPTURING. |
| Wake fires during SPEAKING | Same as above; `speaker.clear()` happens inside `cancel_response()`. |
| Realtime ws drops mid-CAPTURING | Lose the in-flight utterance, log it, return to IDLE; state machine will reconnect on next wake (out of scope for v1: just exit and let the user re-launch). |
| User says wake word but then nothing | After `no_speech_timeout_s` (4 s), return to IDLE silently. No commit, no response.create. |

## 14. Testing

**Unit (no live services):**

* `tests/test_wake_word.py`
  * Fake whisper backend that returns scripted transcripts; assert the
    matcher fires on positive phrases, ignores variations, respects RMS
    gate, respects dedup, respects cooldown.
* `tests/test_utterance_vad.py`
  * Synthesized PCM (silence, sine wave, mixed); assert
    `commit_silence` / `commit_max` / `continue` returns at the right
    times.
* `tests/test_state_machine.py`
  * Drive the state machine with mocked `RealtimeAgent` /
    `WakeWordDetector` / `UtteranceVAD`; assert the full IDLE → AWAKE →
    CAPTURING → THINKING → SPEAKING → LISTENING_WINDOW → IDLE/CAPTURING
    transition graph, including the wake-during-SPEAKING edge.
* Existing `tests/test_safety.py` and `tests/test_skills_mock.py` keep
  passing unchanged.

**Live verification scripts:**

* `scripts/wake_word_debug.py` (new) — opens the mic, runs only the
  wake-word detector, prints the wake events with their transcripts.
  Lets the user tune `rms_threshold` and verify the model downloaded.
* `scripts/audio_loopback.py`, `scripts/tts_debug.py`,
  `scripts/skill_debug.py`, `scripts/vision_loop_debug.py` — unchanged.

**End-to-end (MuJoCo, all three terminals):**

1. mic + wake-word only: say "hi sparky" → see `[wake]` log, no Realtime
   call yet (because `wakeword_debug.py` doesn't connect).
2. Full demo, observe mode: launch `python -m va_demo.main --mode observe`
   → say "hi sparky" → ask "你看到什么" → expect `describe_scene` tool
   call, vision answer, Sparky speaks back, then 8 s listening window.
3. Self-interrupt regression test: ask Sparky a long question that takes
   > 5 s to answer; while it is speaking, **don't** say anything — verify
   Sparky finishes its reply (this is the original bug).
4. Wake interrupt test: same long answer, mid-reply say "Hi, Sparky stop"
   — verify Sparky cuts off and re-enters CAPTURING.
5. Confirm/active mode (sim only): "hi sparky 走两步" → verify confirm
   prompt, then walk command in MuJoCo viewer.

## 15. Files

**New**

* `va_demo/wake_word.py`
* `va_demo/utterance_vad.py`
* `va_demo/conversation_state.py`
* `va_demo/spoken_cache.py`
* `tests/test_wake_word.py`
* `tests/test_utterance_vad.py`
* `tests/test_state_machine.py`
* `scripts/wake_word_debug.py`

**Modified**

* `va_demo/audio_io.py` — `MicStream.subscribe()` fan-out
* `va_demo/realtime_agent.py` — `turn_detection: null`, manual
  `commit_and_respond` / `cancel_response`, `set_uplink_enabled`,
  remove auto barge-in `speaker.clear()`
* `va_demo/main.py` — wire wake-word + state machine
* `va_demo/prompts.py` — no-self-name rule
* `va_demo/tts.py` — write spoken text into spoken cache
* `configs/va_demo.yaml` — new sections
* `requirements.txt` — `faster-whisper>=1.0.3`, `webrtcvad-wheels>=2.0.14`
* `README.md` — "Wake-word usage" + first-run model download note

## 16. Out of Scope

* Acoustic Echo Cancellation (AEC). Headphones already solve it; the prompt
  rule + RMS gate + dedup cover the speaker case for the demo.
* Custom wake-word model training. Whisper transcribes any speech, so
  changing the wake phrase is just a config edit.
* Multi-user disambiguation (two voices saying "hi sparky" simultaneously).
* GPU inference for whisper. Tiny on int8 CPU is < 100 ms / pass on a
  modern laptop, fine for 2 Hz polling.
* Real-robot deployment (still on the `g1_real_demo` track).
