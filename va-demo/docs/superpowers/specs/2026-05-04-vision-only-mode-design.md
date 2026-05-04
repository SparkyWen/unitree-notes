# Vision-Only Test Mode — Design Spec

**Date:** 2026-05-04
**Branch:** `feature/video-listen`
**Status:** Approved (architecture)

---

## 0. One-line summary

Add a `--vision-only` CLI flag to `python -m va_demo.main` that strips all
motion tools and DDS init from the existing wake-word + Realtime pipeline,
leaving a focused loop: **wake word → transcribe utterance → Realtime model
calls `describe_scene` → vision API on the latest teleimager frame → Realtime
voice reply through the speaker**. No motor commands, no MuJoCo dependency.

---

## 1. Motivation

The user has finished:

- Audio wake-word ("Hi Sparky") + 5-state conversation state machine
- Low-latency voice output (Realtime API audio + TTS streaming)
- Camera ingestion via the existing `teleimager.image_server` ZMQ client

`describe_scene` already exists as a Realtime tool, so visual understanding is
nominally functional. But two things are awkward for *isolated visual testing*:

1. The agent currently advertises `walk` / `gesture` / `stop` / `release_arms`,
   which means the model can call them mid-test (driven by user phrasing or
   the safety prompt) and the run requires MuJoCo + DDS to be up before the
   ComboController will report `policy_active`.
2. There is no clean signal to the model "this is a vision-only test; do not
   try to move."

Both issues are best solved by a single mode switch that re-shapes the tool
list and prompt at session-update time and skips the DDS init path.

---

## 2. Out of scope

- Multi-frame video understanding (still single keyframe per tool call)
- Local YOLO / depth / scene-graph perception
- Replacing `gpt-5.5` (env var override `OPENAI_VISION_MODEL` is the existing
  escape hatch and stays as-is)
- A standalone "vision wake phrase" that bypasses the Realtime model — we
  explicitly chose to reuse the Realtime tool path (interpretation A in
  the brainstorm)
- Any change to motor / DDS / safety code paths when vision-only is OFF
  (default behavior must be byte-for-byte unchanged)

---

## 3. User-visible behavior

Run:

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
python -m va_demo.main --vision-only
```

Required services (only two terminals):

1. `teleimager.image_server` (camera frames)
2. `va_demo.main --vision-only` (this process)

**MuJoCo / `unitree_mujoco.py` is NOT required** in this mode.

Conversation:

- User: "Hi Sparky"
- (state machine: IDLE → CAPTURING)
- User: "前面有什么？" (or any visual question, in CN or EN)
- (UtteranceVAD commits after 1.5 s silence → THINKING → Realtime response)
- Realtime model → tool call `describe_scene{question:"前面有什么"}`
- va-demo → camera latest JPEG → vision.describe → text
- Realtime model speaks the description in the user's language
- (state machine: SPEAKING → LISTENING_WINDOW(8s) → IDLE)

Tools the Realtime model sees in this mode:

| Tool | Status |
|---|---|
| `say(text)` | KEEP (canned TTS) |
| `describe_scene(question?, detail?)` | KEEP (the whole point) |
| `walk` | REMOVED from schema |
| `gesture` | REMOVED from schema |
| `stop` | REMOVED from schema |
| `release_arms` | REMOVED from schema |

---

## 4. Architecture

### 4.1 Files touched

| File | Change |
|---|---|
| `va_demo/prompts.py` | Add `REALTIME_SYSTEM_PROMPT_VISION_ONLY` constant |
| `va_demo/realtime_agent.py` | `_build_tool_schemas()` accepts `vision_only: bool`; `RealtimeAgent` gains a `vision_only: bool = False` field; session.update picks the right prompt + schemas |
| `va_demo/main.py` | New CLI flag `--vision-only`; force `args.no_skills = True` when set; pass `vision_only=True` into `RealtimeAgent`; log a banner |
| `configs/va_demo.yaml` | Add `vision_only: false` (default; CLI flag overrides) — purely documentary |
| `tests/test_vision_only_mode.py` | New: assert tool schema shape + prompt selection in both modes |
| `README.md` | New "Vision-only test mode" subsection under "Run order" |

No other module changes. `camera.py`, `vision.py`, `tts.py`, `wake_word.py`,
`conversation_state.py`, `spoken_cache.py`, `utterance_vad.py`, `safety.py`,
`audio_io.py`, `skills.py` are untouched.

### 4.2 The two new prompt + tool variants

`_build_tool_schemas(vision_only: bool)` — when `vision_only=True`, returns
just `say` and `describe_scene` (existing schemas, unchanged shape). When
`vision_only=False`, returns the existing 6-tool list (regression-safe
default).

`REALTIME_SYSTEM_PROMPT_VISION_ONLY` — replaces the current motion-aware
prompt. New text emphasizes:
- "You are in vision-test mode."
- "You can speak with the user and look at the camera (via describe_scene)."
- "You CANNOT move. There are no walk, gesture, or stop tools available."
- "When the user asks any visual question, ALWAYS call describe_scene first."
- Self-name and language rules carried over verbatim from the existing
  prompt (the wake-word self-echo defenses still apply).

### 4.3 main.py wiring

```
parse_args()
  → if args.vision_only: args.no_skills = True
  → load yaml
  → init mic/speaker/camera (unchanged)
  → if not args.no_skills: init DDS + ComboController (unchanged path)
  → safety supervisor (unchanged; describe_scene + say already in whitelist)
  → vision/tts clients (unchanged)
  → RealtimeAgent(..., vision_only=args.vision_only)
  → wake_word + state_machine (unchanged)
  → agent.run()
```

`vision_only=True` short-circuits the DDS branch via the existing
`args.no_skills` path; we do NOT fork main into two control flows.

---

## 5. Data flow (one full round-trip)

```
[mic] PCM 24kHz mono
   │
   ├─ MicStream.subscribe() ──► WakeWordDetector(thread)
   │                              │  on "hi sparky" match (RMS-gated, dedup)
   │                              ▼
   │                            sm.handle_wake() → state CAPTURING
   │                              │
   │                              ▼
   ├─ MicStream.queue ──► RealtimeAgent.uplink (gated by uplink_enabled)
   │                              │  base64 PCM → input_audio_buffer.append
   │                              ▼
   │                          OpenAI Realtime WS
   │
   └─ MicStream.subscribe() ──► UtteranceVAD
                                  │  on 1.5s silence → sm._enter_thinking()
                                  ▼
                              agent.commit_and_respond()
                              → input_audio_buffer.commit
                              → response.create

[Realtime model output]
   ├─ response.audio_transcript.delta → spoken_cache + stdout
   └─ response.function_call_arguments.done(name="describe_scene")
        │
        ▼
      _dispatch_tool
        ├─ safety.validate("describe_scene", args)  → ok (whitelisted)
        ├─ camera.latest_jpeg_b64(width=1024, q=85)
        │     │  (ZMQ pull from teleimager; cached if no new frame)
        ├─ vision.describe(b64, VISION_SCENE_PROMPT + question, detail=medium)
        │     │  POST openai responses.create model=gpt-5.5
        │     │  thread-pooled, 15s timeout
        ▼     ▼
      conversation.item.create function_call_output {ok:true, description:"..."}
      → response.create  (model continues, now produces audio)

[Realtime model audio reply]
   └─ response.audio.delta → SpeakerStream.write
        │  (state machine: THINKING → SPEAKING on first delta)
        ▼
      response.done → sm._enter_listening_window() (8s window)
      → 8s later → IDLE
```

Side-channel: `RealtimeAgent` may also receive `say(text)` tool calls →
`tts.speak(text)` → SpeakerStream. Unchanged from the existing flow.

---

## 6. Error handling

All error paths sourced from the existing implementation; vision-only does
NOT introduce new failure surfaces.

| Failure | Existing behavior | Vision-only impact |
|---|---|---|
| teleimager not running | `camera.latest_jpeg_b64()` → `None` → tool returns `{ok:false, reason:"no frame available"}`; model apologizes in voice | Same. Tested via `--no-realtime` + `camera_debug.py` |
| Frame older than `safety.watchdog.max_frame_age_s` (2 s) | Watchdog forces SAFE_HOLD-equivalent; `describe_scene` already does its own staleness check via `frame_age_seconds()` indirectly through camera cache | Same |
| `gpt-5.5` not available on account | `vision.describe()` catches, returns `"(vision request failed: ...)"`; Realtime model speaks the error string | Same. User sets `OPENAI_VISION_MODEL=gpt-5.1` (or similar) and restarts |
| Realtime WS disconnect | `RealtimeAgent.run()` raises; main exits with traceback | Same |
| Wake-word false trigger | `cooldown_s=2.0` + RMS gate + self-echo dedup (all in place) | Same |
| Model tries to call a removed tool | Cannot — schema is not advertised. Defensive: `_execute_tool` already returns `{ok:false, reason:"unknown tool: ..."}` | Same |
| User runs `--vision-only` without teleimager | va-demo starts, wake-word fires, tool returns no-frame; Realtime model says "I can't see anything right now" | Acceptable; documented in README |

---

## 7. Testing

### 7.1 Unit (new — 1 file, ~3 cases)

`tests/test_vision_only_mode.py`:

```
test_tool_schemas_vision_only_excludes_motion_tools()
    schemas = _build_tool_schemas(vision_only=True)
    names = {s["name"] for s in schemas}
    assert names == {"say", "describe_scene"}

test_tool_schemas_default_keeps_motion_tools()
    schemas = _build_tool_schemas(vision_only=False)  # default
    names = {s["name"] for s in schemas}
    assert names == {"say", "stop", "release_arms", "walk", "gesture", "describe_scene"}

test_realtime_agent_vision_only_picks_vision_prompt()
    agent = RealtimeAgent(..., vision_only=True)
    # session_update happens inside an async run; we assert the resolved
    # instructions string at the field level:
    assert agent._resolve_instructions() == REALTIME_SYSTEM_PROMPT_VISION_ONLY
    agent2 = RealtimeAgent(..., vision_only=False)
    assert agent2._resolve_instructions() == REALTIME_SYSTEM_PROMPT
```

(Helper `_resolve_instructions()` may be added to RealtimeAgent for testability;
alternatively the test can read the field directly. Choice deferred to
implementation.)

### 7.2 Regression

`pytest tests/ -v` — all 49 existing cases must still pass. The default
parameter value `vision_only=False` guarantees byte-for-byte behavior
preservation in every existing call path.

### 7.3 Manual smoke

Documented in README:

```bash
# Terminal 1
cd ~/unitree/unitree-notes/teleimager && python -m teleimager.image_server

# Terminal 2
cd ~/unitree/unitree-notes/va-demo && python -m va_demo.main --vision-only -v
# wait for "wake-word enabled" log
# say "Hi Sparky" → "看看前面有什么"
# expect: a spoken reply describing the camera scene
```

Quick non-Realtime sanity (already exists):

```bash
python scripts/camera_debug.py --question "前面有什么"
```

---

## 8. Backwards compatibility

- All new parameters default to `False` / `vision_only=False`.
- Without `--vision-only` the codepath is identical to today's `main.py`.
- `configs/va_demo.yaml::vision_only` is documentary (defaults to false; CLI
  flag is the source of truth in this iteration). Not required to read it
  from yaml — that's a follow-up if the user wants to make the mode persistent.

---

## 9. Open questions

None at design time. All architectural choices were resolved in the
brainstorm:

- Reuse Realtime + describe_scene tool path (not a standalone vision wake)
- `--vision-only` flag, not deletion of motion code (preserve later use)
- Keep `gpt-5.5` default; rely on `OPENAI_VISION_MODEL` env override

---

## 10. Acceptance criteria

1. `python -m va_demo.main --vision-only --help` shows the new flag.
2. With teleimager up and OPENAI_API_KEY set, the smoke procedure in §7.3
   produces a spoken description of the camera scene.
3. Without `--vision-only`, all behavior is unchanged (regression suite green).
4. The Realtime model in vision-only mode never receives `walk` / `gesture` /
   `stop` / `release_arms` schemas (verifiable by enabling DEBUG logs and
   inspecting the session.update payload, or by the unit test above).
5. va-demo starts cleanly with `--vision-only` even when MuJoCo / DDS is not
   running.
