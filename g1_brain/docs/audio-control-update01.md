# Audio Control — Update 01

Date: 2026-05-07
Branch: `feature/audio-control`

## Goal

Three concrete user-facing fixes to the voice loop in
`g1_brain.apps.agent_main --mode confirm`:

1. **Wake-word barge-in always works.** Saying "hi sparky" must immediately
   interrupt the agent, no matter what state it is in (model speaking, model
   running tools, user mid-utterance). On barge-in, the robot also stops
   moving (releases arms, halts walking) so the user can give a fresh command
   without a runaway action.
2. **No mic listening between turns.** Once the entire current plan finishes
   (all `response.done` events with no follow-up function calls fired, all
   tool calls returned, speaker drained), the mic uplink to the OpenAI
   Realtime model is disabled. The Realtime model is no longer fed audio
   chatter. Re-engagement is only via wake-word.
3. **Per-process conversation jsonl.** Each `agent_main` run writes one
   `logs/conversations/<ISO>-<uuid>.jsonl` file containing every user turn,
   every assistant turn, every tool call/result, every wake event, and
   significant state transitions. New launch = fresh file (old files
   preserved on disk; rotated by count). Schema is Claude-compatible so the
   user's existing Claude harness with memory retrieval / SQLite FTS5 can
   ingest these files later without a schema migration.

The implementation respects the architecture rule in
`docs/architecture.md` §7: BrainRealtimeAgent extends va-demo's
`RealtimeAgent`; va-demo source files are not modified.

---

## §1 Architecture overview

```
g1_brain.apps.agent_main._build_state_machine
            │
            ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                                                             │
   │  ┌────────────────────────┐                                 │
   │  │ MicStream (va-demo)    │── fan-out (subscribe)           │
   │  └─┬──────┬───────────────┘                                 │
   │    │      │                                                 │
   │    │      │                                                 │
   │    ▼      ▼                                                 │
   │  ┌──────┐ ┌─────────────────────────────────────────┐       │
   │  │Wake  │ │ BrainConversationStateMachine  (NEW)    │       │
   │  │Word  │ │                                         │       │
   │  │(va)  │ │  states: IDLE, CAPTURING,               │       │
   │  └──────┘ │          THINKING, SPEAKING             │       │
   │     │     │                                         │       │
   │     │ on  │  no LISTENING_WINDOW.                   │       │
   │     │ wake│  CAPTURING does not pause wake-word.    │       │
   │     ├────►│  any state allows barge-in.             │       │
   │     │     │                                         │       │
   │     │     │  drives: agent.set_uplink_enabled,      │       │
   │     │     │          agent.commit_and_respond,      │       │
   │     │     │          agent.cancel_in_flight (NEW),  │       │
   │     │     │          stop_skill_callable (NEW)      │       │
   │     │     └─────────────────┬───────────────────────┘       │
   │     │                       │  callbacks                    │
   │     │                       ▼                               │
   │     │  ┌────────────────────────────────────────────────┐   │
   │     │  │ BrainRealtimeAgent (extends va-demo)           │   │
   │     │  │                                                │   │
   │     │  │ + plan tracker:                                │   │
   │     │  │     _this_response_had_function_call : bool    │   │
   │     │  │     _pending_function_calls : set[call_id]     │   │
   │     │  │                                                │   │
   │     │  │ + new hooks:                                   │   │
   │     │  │     on_plan_done()                             │   │
   │     │  │     on_user_transcript(text)                   │   │
   │     │  │     on_assistant_transcript_done(text)         │   │
   │     │  │     on_tool_use(call_id, name, args)           │   │
   │     │  │     on_tool_result(call_id, name, result)      │   │
   │     │  │     on_response_canceled(reason)               │   │
   │     │  │                                                │   │
   │     │  │ + new control:                                 │   │
   │     │  │     cancel_in_flight() →                       │   │
   │     │  │       response.cancel +                        │   │
   │     │  │       input_audio_buffer.clear                 │   │
   │     │  └─────────────────┬──────────────────────────────┘   │
   │     │                    │ callbacks                        │
   │     │                    ▼                                  │
   │     │  ┌────────────────────────────────────────────┐       │
   │     └─►│ ConversationLogger (NEW)                   │       │
   │        │                                            │       │
   │        │ logs/conversations/<ISO>-<uuid>.jsonl      │       │
   │        │ Claude-shape lines, append-only            │       │
   │        │ flushed per write                          │       │
   │        └────────────────────────────────────────────┘       │
   │                                                             │
   └─────────────────────────────────────────────────────────────┘
```

### Files touched

| File | Change |
|---|---|
| `g1_brain/brain/conversation_state.py` | **new** — ~280 lines |
| `g1_brain/brain/conversation_logger.py` | **new** — ~200 lines |
| `g1_brain/brain/realtime_agent.py` | + plan tracker, + 6 hooks, + `cancel_in_flight()` |
| `g1_brain/apps/agent_main.py` | rewrite `_build_state_machine`; pass stop-skill callable |
| `g1_brain/brain/prompts.py` | add a one-line "no follow-up listening" reminder so the LLM does not chain "anything else?" prompts |
| `g1_brain/configs/g1_brain.yaml` | new `audio_control:` section |
| `va_demo/*` | **untouched** |
| `tests/test_brain_conversation_state.py` | **new** |
| `tests/test_conversation_logger.py` | **new** |
| `tests/test_brain_realtime_agent_plan_tracker.py` | **new** |

---

## §2 State machine detail

Four states. No LISTENING_WINDOW, no AWAKE.

```
                      ┌──── wake (mid-utterance restart) ───┐
                      │                                     │
                      ▼                                     │
   ┌──────┐  wake   ┌──────────┐  vad commit   ┌──────────┐│
   │ IDLE │────────►│CAPTURING │──────────────►│ THINKING │┘
   └──────┘         └──────────┘               └──────────┘
      ▲                  │                          │
      │     no_speech    │                          │ first
      │     timeout      │                          │ audio.delta
      │                  │                          ▼
      │                  │                     ┌──────────┐
      │                  │                     │ SPEAKING │
      │                  │                     └──────────┘
      │                  │                          │
      │   plan_done      │                          │ plan_done
      │   (drain wait)   │   wake (barge-in)        │
      └──────────────────┴──────────────────────────┘
                         (barge-in path: cancel + stop + → CAPTURING)
```

### Transition table

| state | event | next | actions |
|---|---|---|---|
| IDLE | wake | CAPTURING | uplink ON; vad reset; start no_speech timer; `turn_id += 1` |
| IDLE | response.audio.delta (stale) | IDLE | ignore |
| IDLE | plan_done (stale) | IDLE | ignore |
| CAPTURING | wake (mid-utterance, age ≥ `min_capture_age_s`) | CAPTURING | send `input_audio_buffer.clear`; reset vad; restart no_speech timer; logger meta `barge_in_in_capture`; **no skill stop** (no plan in flight) |
| CAPTURING | wake (age < `min_capture_age_s`) | CAPTURING | suppress (echo of model speech bleeding into capture window) |
| CAPTURING | vad commit_silence \| commit_max | THINKING | uplink OFF; `agent.commit_and_respond()` |
| CAPTURING | no_speech_timeout (no voice ever) | IDLE | uplink OFF; `input_audio_buffer.clear` (best effort); meta `no_speech_idle` |
| THINKING | response.audio.delta | SPEAKING | record state |
| THINKING | wake | CAPTURING | barge-in path (see §3) |
| THINKING | plan_done (silent plan) | IDLE-pending | drain wait → IDLE |
| SPEAKING | wake | CAPTURING | barge-in path (see §3) |
| SPEAKING | response.audio.delta | SPEAKING | continue |
| SPEAKING | plan_done | IDLE-pending | drain wait → IDLE |

`IDLE-pending` is **not** a separate state; it is an `asyncio.Task` that:

1. polls `speaker.pending_bytes()` until `≤ drain_threshold_bytes` or
   `drain_max_wait_s` elapses,
2. then sets state = IDLE, uplink OFF (idempotent), wake_word.resume()
   (idempotent), logger meta `idle`.

A wake event during the drain window cancels the drain task and routes
straight into the barge-in path.

### Plan tracking

OpenAI Realtime semantics: a single user turn may produce N responses
because each function-call response triggers another `response.create` after
the client returns the tool result. Hence `response.done` is a **per-response**
event, not a **per-turn** event.

Tracking lives inside `BrainRealtimeAgent`:

- `_this_response_had_function_call: bool` — reset on `response.created`,
  set to True on each `function_call_arguments.done` during this response.
- `_pending_function_calls: set[str]` — call_ids the client is currently
  executing (added in `_dispatch_tool` entry, removed in finally).
- On `response.done`:
    - if `_this_response_had_function_call` is True **or**
      `_pending_function_calls` non-empty → another response will follow,
      do **not** emit `on_plan_done`.
    - else → emit `on_plan_done()`.

A 30 s **plan watchdog** starts on the first `function_call_arguments.done`
of a turn and resets each time `_pending_function_calls` changes. If it
expires while the set is non-empty, log a warning, force-emit
`on_plan_done()`, and meta-log `plan_watchdog_timeout`.

---

## §3 Barge-in mechanics + safety

A wake event in any state ≠ IDLE routes to `_handle_barge_in(evt)`,
guarded by an `asyncio.Lock` so two wake events ms apart cannot double-stop.

```
async def _handle_barge_in(self, evt, *, was_state):
    await self._barge_in_lock.acquire()
    try:
        # 1. cancel any pending IDLE-drain task
        self._cancel_drain()

        # 2. tell server to drop the in-flight response and any uncommitted
        #    user audio buffer. `cancel_in_flight()` is best-effort.
        if was_state in (THINKING, SPEAKING):
            await self.agent.cancel_in_flight()

        # 3. drop residual TTS audio in the local playback buffer.
        if was_state in (THINKING, SPEAKING):
            self.speaker.clear()

        # 4. stop the robot if we asked it to do something. Idempotent;
        #    SafetySupervisor handles "nothing to stop" gracefully.
        if was_state in (THINKING, SPEAKING) and self.cfg.also_stop_skills:
            try:
                await asyncio.wait_for(
                    self._stop_skill_callable(), timeout=2.0
                )
            except Exception:
                log.warning("stop skill on barge-in failed", exc_info=True)

        # 5. reset capture-side state.
        self.vad.reset()
        self.agent.reset_plan_tracker()

        # 6. transition into CAPTURING for the new turn.
        self.agent.set_uplink_enabled(True)
        self._set_state(CAPTURING)
        self._capture_started_at = time.monotonic()
        self._reset_timer(self.cfg.no_speech_timeout_s,
                          self._no_speech_timeout_cb)

        # 7. logger
        self.logger.log_barge_in(was_state=was_state, wake_text=evt.text)
    finally:
        self._barge_in_lock.release()
```

### Wake during CAPTURING

CAPTURING-to-CAPTURING wake (the user redoing their utterance) calls a
narrower path: `_handle_capture_restart(evt)`:

```
async def _handle_capture_restart(self, evt):
    # The server may have buffered partial audio we don't want.
    await self.agent.input_audio_buffer_clear()
    self.vad.reset()
    self._capture_started_at = time.monotonic()
    self._reset_timer(self.cfg.no_speech_timeout_s,
                      self._no_speech_timeout_cb)
    self.logger.log_barge_in(was_state=CAPTURING, wake_text=evt.text)
```

`min_capture_age_s` (default 0.4 s) suppresses wake events that arrive
right after entering CAPTURING — those are usually echoes of the model's
last word bleeding into the new capture window before the wake-word
detector's rolling buffer has flushed.

### Safety implications

Step 4 calls the SkillServer's `stop` tool. SafetySupervisor enforces:

- `stop` is whitelisted in all run modes (observe / confirm / active) since
  it is a safety primitive. Confirmed by reading `safety/supervisor.py`.
- In `confirm` mode, `stop` does **not** prompt the operator. It is treated
  as user-driven and applied immediately.
- If the FSM is in EMERGENCY_STOP, `stop` is a no-op.
- If the robot is STANDING (no motion in flight), `stop` returns ok=true with
  a "nothing to stop" reason.

If `audio_control.barge_in.also_stop_skills: false`, step 4 is skipped —
useful when iterating UX with the simulator and you do not want the arms to
reset every barge-in.

---

## §4 JSONL schema

### File

```
${log_dir}/conversations/<ISO-8601-UTC>-<short-uuid>.jsonl
```

Example: `2026-05-07T15-22-03Z-a1b2c3d4.jsonl`.

- Created at `agent_main` start, closed on shutdown.
- Append-only, line-buffered (`open(..., "a", buffering=1)` plus an
  explicit `flush()` after each write so a SIGKILL keeps everything up
  to the last completed event).
- Rotation: at `agent_main` start, list files in `conversations/`; if there
  are more than `keep_last_n` (default 50), unlink the oldest.

### Common fields

Every line has:

- `uuid` — per-event UUIDv4
- `parent_uuid` — previous event's uuid in this turn, or null at session
  start
- `session_id` — stable per-process UUID, also embedded in filename
- `turn_id` — `t-0000` increments per `IDLE → CAPTURING` transition
- `timestamp` — ISO-8601 UTC with millisecond precision
  (e.g. `2026-05-07T15:22:03.456Z`)
- `type` — one of `user`, `assistant`, `tool_use`, `tool_result`, `system`,
  `meta`
- `message` — typed content block (absent for `meta`)

### Message shapes (Claude-compatible)

#### user

Source: `conversation.item.input_audio_transcription.completed`.

```jsonc
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [{"type": "text", "text": "走五米"}]
  },
  ...
}
```

#### assistant

Source: `response.audio_transcript.done` (the transcript of the model's
audio reply). Ignored for responses that emit only function calls.

```jsonc
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [{"type": "text", "text": "好的，我先走两米看看路况"}]
  },
  ...
}
```

#### tool_use

Source: `response.function_call_arguments.done`.

```jsonc
{
  "type": "tool_use",
  "message": {
    "role": "assistant",
    "content": [{"type": "tool_use", "id": "call_abc",
                 "name": "walk",
                 "input": {"vx": 0.2, "duration_s": 1.0}}]
  },
  ...
}
```

#### tool_result

Source: tool dispatch return value. Claude convention puts `tool_result`
inside a `user` role message.

```jsonc
{
  "type": "tool_result",
  "message": {
    "role": "user",
    "content": [{"type": "tool_result",
                 "tool_use_id": "call_abc",
                 "content": [{"type": "text",
                              "text": "{\"ok\":true,\"executed\":\"walk\"}"}]}]
  },
  ...
}
```

#### system

Used for perception event injection (`inject_perception_event`) and the
session's system prompt at startup.

```jsonc
{
  "type": "system",
  "message": {
    "role": "system",
    "content": [{"type": "text", "text": "User showed gesture: wave_right"}]
  },
  ...
}
```

#### meta

Out-of-band events. No `message` field; uses `subtype` and `data`.

```jsonc
{"type": "meta", "subtype": "session_start", "data": {"argv": [...], "config_path": "..."}, ...}
{"type": "meta", "subtype": "wake_event", "data": {"text": "hi sparky"}, ...}
{"type": "meta", "subtype": "barge_in", "data": {"from_state": "SPEAKING", "wake_text": "hi sparky"}, ...}
{"type": "meta", "subtype": "state_transition", "data": {"from": "CAPTURING", "to": "THINKING"}, ...}
{"type": "meta", "subtype": "plan_done", "data": {"turn_id": "t-0001"}, ...}
{"type": "meta", "subtype": "plan_watchdog_timeout", "data": {"pending": ["call_xy"]}, ...}
{"type": "meta", "subtype": "no_speech_idle", "data": {"timeout_s": 4.0}, ...}
{"type": "meta", "subtype": "shutdown", "data": {}, ...}
{"type": "meta", "subtype": "error", "data": {"where": "...", "msg": "..."}, ...}
```

### Trim policy

Per-event `text` payload trimmed to `max_text_kb` (default 4 KB). The full
text remains in `agent.log`. Rationale: `describe_scene` returns multi-
hundred-character descriptions, and tool results may contain dense state
dumps; we keep the jsonl skim-friendly.

---

## §5 Error handling, edge cases, config

### Edge cases

| # | Scenario | Behaviour |
|---|---|---|
| 1 | Wake event arrives during shutdown | dropped (`_stopped` flag) |
| 2 | Two wake events within ms of each other | `_barge_in_lock` serializes them; second one runs after first finishes and is suppressed because state is already CAPTURING and capture age < `min_capture_age_s` |
| 3 | `cancel_in_flight()` called when no response is active | `response.cancel` send raises; caught, debug-logged |
| 4 | `_pending_function_calls` never empties | 30 s plan watchdog forces `on_plan_done()`; meta-log `plan_watchdog_timeout` |
| 5 | WS disconnects during plan | `BrainRealtimeAgent.run()` propagates to `agent_main`'s shutdown; `on_plan_done` fires from a `finally` so the state machine doesn't get stuck in SPEAKING |
| 6 | Logger file `open()` fails | warn + run with logging disabled (no agent crash) |
| 7 | Tool result is huge (e.g. 10 KB describe_scene output) | trimmed to `max_text_kb` in jsonl; full text in `agent.log` |
| 8 | Agent killed mid-turn (SIGKILL) | last written line survives because file is line-buffered + flushed |
| 9 | `stop` skill itself fails on barge-in | warn-logged; barge-in still proceeds into CAPTURING (do not block on motion stop) |
| 10 | User's first wake is suppressed by `min_capture_age_s` cooldown after just-finished plan | not an issue — drain wait + IDLE happen first; CAPTURING only re-entered via wake from IDLE, which has no min-age check |

### YAML config additions

```yaml
audio_control:
  barge_in:
    enabled: true                # set false to revert to "ignore wake during SPEAKING/THINKING"
    also_stop_skills: true       # call stop() on barge-in (option A from brainstorming)
    min_capture_age_s: 0.4       # suppress wake echo right after CAPTURING entered
  idle_after_plan:
    enabled: true                # skip LISTENING_WINDOW; go straight to drain → IDLE
    drain_threshold_bytes: 2400  # ~50 ms residual at 24 kHz pcm16
    drain_max_wait_s: 6.0        # hard cap
  plan_watchdog_s: 30.0          # force plan_done if tools never resolve
  transcript:
    enabled: true
    dir: "${HOME}/unitree/unitree-notes/g1_brain/logs/conversations"
    keep_last_n: 50              # rotate: delete oldest beyond this count on startup
    max_text_kb: 4               # trim per-event content to this size
```

`audio_control.barge_in.enabled: false` and
`audio_control.idle_after_plan.enabled: false` together restore exactly the
old behaviour, modulo the jsonl logger (which is independent and gated by
`audio_control.transcript.enabled`).

### Behavioural change to prompts

`brain/prompts.py` gets one new line in `REALTIME_SYSTEM_PROMPT_BRAIN` and
`REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY`:

> When you finish answering, do not append "anything else?" or similar
> follow-up prompts. The voice loop will only listen again when the user
> says the wake phrase, so leaving the floor open with a question wastes a
> turn.

This is purely a stylistic nudge; the state machine no longer listens
either way.

---

## §6 Testing

Unit tests, no real audio, no real OpenAI WS.

### tests/test_brain_conversation_state.py

- `IDLE → CAPTURING` on wake; uplink enabled; turn_id increments
- `CAPTURING → THINKING` on vad commit; uplink disabled; commit_and_respond
  called
- `CAPTURING → IDLE` on no-speech timeout; uplink disabled; meta logged
- `CAPTURING → CAPTURING` on wake mid-utterance after `min_capture_age_s`;
  input_audio_buffer.clear sent; vad reset; **no** skill stop
- Wake within `min_capture_age_s` is suppressed
- `THINKING → CAPTURING` on wake (barge-in path): cancel_in_flight,
  speaker.clear, stop_skill all called
- `SPEAKING → CAPTURING` on wake: same as above
- `SPEAKING → IDLE` via drain wait after `plan_done`; respects
  `drain_max_wait_s` hard cap
- Drain wait cancelled when wake fires during it; routes into barge-in
- Wake during `_stopped` is dropped (no callbacks)
- `also_stop_skills: false` skips stop_skill but still cancels response
- Two concurrent wake events serialize via lock

### tests/test_conversation_logger.py

- Session-start + shutdown emit meta lines
- user/assistant/tool_use/tool_result rendered to Claude shape; uuid present;
  parent_uuid chains within a turn
- Trim logic on text > `max_text_kb`
- `keep_last_n` rotation deletes oldest files at startup
- File handle closed cleanly on `close()`
- `open()` failure does not raise; subsequent log calls become no-ops
- Multi-thread writes are serialized (a `threading.Lock` around `write+flush`)

### tests/test_brain_realtime_agent_plan_tracker.py

- Sequence: response.created → audio.delta → fcall_args.done →
  response.done → tool dispatch → next response.created → audio.delta →
  response.done (no fcall) → `on_plan_done` fires exactly once
- Tool dispatch error path still removes call_id and ends plan
- `cancel_in_flight()` handles "no active response" gracefully
- 30 s plan watchdog forces on_plan_done after timeout

### Verification (post-test)

- `pytest tests/` passes (existing + new)
- Import smoke: `python -c "from g1_brain.brain.conversation_state import
  BrainConversationStateMachine; from g1_brain.brain.conversation_logger
  import ConversationLogger"` (with va-demo on path)
- YAML loads cleanly: `python -c "import yaml; yaml.safe_load(open('configs/g1_brain.yaml'))"`

End-to-end voice test in MuJoCo sim is not part of automated verification —
it requires audio hardware. The README / `how_to_run.md` should mention
that the human operator needs to do this.
