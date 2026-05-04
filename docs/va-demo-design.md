# va-demo: G1 vision + audio + Realtime agent design

> Date: 2026-05-04
> Location of spec: `docs/va-demo-design.md` (this file) and `docs/superpowers/specs/2026-05-04-va-demo-design.md` (mirror for tooling).
> Implements the architecture from `docs/vlm_audio_mock_deep.md` §11 Phase 1–4 as one runnable Python package.

## 1. Goal

A single runnable Python agent that lets a Unitree G1 (in MuJoCo simulation) **see, hear, speak, walk, and gesture** through OpenAI's APIs:

- **Real-time camera streaming** — pull frames from the existing `teleimager.image_server` (already verified per `docs/camera_ui_demo.md`).
- **Real-time microphone capture and speaker playback** — `sounddevice` 24 kHz PCM16 mono on the WSL host.
- **OpenAI Realtime API** (`gpt-realtime` over WebSocket) — full-duplex voice conversation, server VAD turn detection.
- **OpenAI Responses API** (`gpt-5.5` vision-capable) — invoked as a tool when the user asks "look at the scene". Single-frame snapshot, JPEG base64.
- **OpenAI TTS** (`gpt-4o-mini-tts`) — for canned/agent-initiated speech that does not need to be a Realtime turn.
- **G1 motion** — walk + 8 arm gestures via the existing `g1_sim_demo/g1_sim_rl_combo.py` `ComboController`. The demo imports it; **does not modify it**.

Out of scope (future phases): real-robot DDS backend, local YOLO/depth, LeRobot, GMR retargeting, scene graph memory, multi-frame video reasoning, behavior tree.

## 2. Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                            va_demo.main                               │
│         asyncio event loop bootstraps and owns the lifecycle           │
└──────┬──────────────┬───────────────┬─────────────────┬───────────────┘
       │              │               │                 │
       ▼              ▼               ▼                 ▼
   audio_io       camera         realtime_agent      skills
  (sounddevice)  (TeleImager)    (WebSocket)      (ComboController
   PCM16 in/out   ZMQ pull        tool calls          wrapper)
                  → BGR / JPEG    ▲                       │
                                  │                       │
       ┌──────────────────────────┼─────────────────┐     │
       │                          │                 │     │
       ▼                          ▼                 ▼     ▼
     vision               tts                  safety  ComboController
   (Responses API)    (Audio Speech API)    (whitelist+   (g1_sim_demo,
   gpt-5.5 single      gpt-4o-mini-tts        limits +     50 Hz tick,
    image → text)      streaming → speaker)   modes +      DDS lo:1)
                                              watchdog)
```

Single Python process. The only external services we depend on are:

| Service | Process | Transport |
|---|---|---|
| MuJoCo G1 simulator | `unitree_mujoco/simulate_python/python unitree_mujoco.py` | DDS domain 1, interface `lo` (`rt/lowstate`, `rt/lowcmd`) |
| TeleImager image server | `python -m teleimager.image_server` | ZMQ PUB on `127.0.0.1:55555`, REQ on `60000` |
| OpenAI APIs | cloud | HTTPS + WSS |

## 3. Module responsibilities

### `va_demo/audio_io.py`
- `MicStream`: opens `sounddevice.RawInputStream(samplerate=24000, channels=1, dtype='int16')`. Pushes raw PCM16 chunks (~50–100 ms) into an `asyncio.Queue`.
- `SpeakerStream`: opens `RawOutputStream`. Plays bytes pulled from a queue. Supports clear/preempt (so a tool result can interrupt model speech if desired).
- `AudioMixer` (later): not in v1; the speaker plays whichever stream most recently pushed.

### `va_demo/camera.py`
- Wraps `teleimager.image_client.ImageClient(host=..., request_bgr=True)`.
- `latest_bgr() -> np.ndarray | None` — pulls from the head camera triple-ring-buffer.
- `latest_jpeg_b64(width=1024, jpeg_quality=85) -> str | None` — resize + encode for vision API.
- `frame_age_seconds() -> float` — used by safety for stale-frame watchdog.

### `va_demo/vision.py`
- `describe(prompt: str, image_b64: str, model: str, detail: str) -> str` — single call to `client.responses.create` with `input_text` + `input_image`.
- Robust to JSON-mode vs free-text: caller chooses via prompt.
- Includes timeout (15 s) and falls back to "I cannot see clearly right now" on error.

### `va_demo/tts.py`
- `speak(text: str, voice: str, model: str)` — streams audio from `client.audio.speech.with_streaming_response.create` and pushes PCM/MP3 bytes into the `SpeakerStream`. We use `response_format="pcm"` (PCM16 24 kHz) so output rate matches the input device.

### `va_demo/skills.py`
- `SkillBackend` constructed with a live `ComboController` and the loaded `arm_actions` table.
- Methods (each is `async` and offloads the blocking part to a thread executor):
  - `walk(vx, vy, wz, duration_s)` — `ctl.set_command(vx,vy,wz)` → `await asyncio.sleep(duration_s)` → `ctl.set_command(0,0,0)`.
  - `gesture(name)` — looks up `ArmAction` by symbolic name → `ctl.push_arm_action(action.keyframes)`.
  - `stop()` — `ctl.set_command(0,0,0)` + `ctl.release_arms()`.
  - `release_arms()` — `ctl.release_arms()`.
- All methods are idempotent and thread-safe (ComboController already locks `_cmd_lock`/`_arm_lock`).
- Gesture name map:
  ```
  wave_right  → "1"
  wave_left   → "2"
  hands_up    → "3"
  t_pose      → "4"
  salute      → "5"
  clap        → "6"
  guard       → "7"
  punch_combo → "8"
  ```

### `va_demo/safety.py`
- `SafetySupervisor(config, run_mode)` — `validate(action_name, args) -> (ok, reason)`.
- Whitelist of action names. Per-action numeric bounds clipped/rejected.
- `run_mode`:
  - `observe`: every motion action rejected with reason="observe_only mode"; `say` and `describe_scene` allowed.
  - `confirm`: motion actions blocked until `confirm_in_terminal()` resolves to `y` (printed to stderr; reads stdin nonblocking). `say`/`describe_scene` pass through.
  - `active`: motion executes if numeric bounds pass.
- Watchdog state read from `WatchdogState` — last-frame age, last-lowstate age. If frame > 2 s stale, reject `describe_scene`. If lowstate > 0.5 s stale, reject all motion. (lowstate watchdog is a defensive double-check; the ComboController already holds default pose if stale.)

### `va_demo/realtime_agent.py`
- Owns the WebSocket connection to `wss://api.openai.com/v1/realtime?model={OPENAI_REALTIME_MODEL}`.
- Sends `session.update` on connect:
  - `modalities: ["audio","text"]`
  - `voice: "alloy"` (configurable)
  - `input_audio_format: "pcm16"`, `output_audio_format: "pcm16"`
  - `turn_detection: {type: "server_vad", threshold: 0.5, prefix_padding_ms: 300, silence_duration_ms: 500}`
  - `tools: [<see §4>]`
  - `instructions: <system prompt; see §6>`
- Two concurrent asyncio tasks:
  - **uplink**: read `MicStream` queue → send `input_audio_buffer.append`.
  - **downlink**: parse server events → push audio deltas to `SpeakerStream`, dispatch tool calls.
- Tool call dispatcher: for each `response.function_call_arguments.done`, look up tool handler in a registry. Run handler (most are `await skills.X(...)` / `await vision.describe(...)`), return `conversation.item.create` with the function call output, then `response.create` so the model speaks the result.
- Uses the `openai` Python SDK's `client.beta.realtime.connect()` async ctx manager when available; falls back to raw `websockets.connect()` if SDK doesn't support it. The wire-format event handling is identical either way.

### `va_demo/main.py`
CLI:
```
python -m va_demo.main \
  [--mode observe|confirm|active] \
  [--config configs/va_demo.yaml] \
  [--no-realtime]   # debug: vision+tts only, no Realtime conversation
  [--no-skills]     # debug: don't open DDS / publish lowcmd
```

Boot order:
1. Load config.
2. Open `MicStream` + `SpeakerStream`.
3. Open `Camera` (TeleImager `ImageClient`).
4. (Unless `--no-skills`) `ChannelFactoryInitialize(1, "lo")`, build `ComboController`, `init_dds`, `start`, wait `policy_active`.
5. Build `SafetySupervisor`.
6. (Unless `--no-realtime`) connect Realtime, register tools, run uplink+downlink.
7. Trap SIGINT → `skill_backend.stop()`, `ctl.stop_and_settle()`, close streams.

## 4. Realtime tool schema

Sent in `session.update.tools`. Schema is JSON Schema draft-07 compatible.

| Tool | Args | Effect |
|---|---|---|
| `say` | `text: string ≤200` | `await tts.speak(text)`; returns `{ok: true}` |
| `stop` | — | `await skills.stop()`; returns `{ok: true}` |
| `release_arms` | — | `await skills.release_arms()` |
| `walk` | `vx ∈ [-0.3, 0.3]`, `vy ∈ [-0.1, 0.1]`, `wz ∈ [-0.4, 0.4]`, `duration_s ∈ [0.2, 1.5]` | `await skills.walk(...)` |
| `gesture` | `name: enum[wave_right, wave_left, hands_up, t_pose, salute, clap, guard, punch_combo]` | `await skills.gesture(name)` |
| `describe_scene` | `question: string` (optional, e.g., "what's in front of me?"), `detail: enum[low, medium, high]` (default `medium`) | grab latest frame → `vision.describe(...)` → returns `{description: string}` |

Safety supervisor validates each call against numeric bounds and run_mode **before** executing. Rejections return `{ok: false, reason: "..."}` so the model can explain politely.

## 5. Run modes

| Mode | Motion tools | Vision/TTS | Notes |
|---|---|---|---|
| `observe` (debug) | rejected | allowed | Prove vision+TTS+Realtime loop without moving the robot. |
| `confirm` (default) | terminal y/N gate | allowed | First trustable mode. Operator approves each motion. |
| `active` | safety bounds only | allowed | Hands-off. Use only after `confirm` mode passes. |

`stop`, `release_arms`, `say`, `describe_scene` are never gated by confirm-prompt (only by safety bounds and watchdog).

## 6. System prompt (Realtime instructions)

Stored in `va_demo/prompts.py`. Text (Chinese + English mix per user preference):

```
You are the voice agent of a Unitree G1 humanoid robot running in a MuJoCo
simulator. You can speak with the user, look at the camera (via the
describe_scene tool), and request small motion primitives (walk, gesture, stop).

Rules:
- You DO NOT have direct motor control. You can only call the tools provided.
- Be conservative. Walk durations should be ≤ 1.0 s and speeds ≤ 0.2 m/s
  unless the user explicitly insists.
- When the user asks anything about what's around you, what's in front, what
  you see, who's there, or any visual question, ALWAYS call describe_scene
  first. Do not guess.
- If a tool returns ok=false, explain the reason to the user briefly and
  propose a safer alternative.
- Speak in the user's language (Chinese or English).
- Keep replies short and natural. Do not narrate every tool call.
```

## 7. Config (`configs/va_demo.yaml`)

```yaml
openai:
  realtime_model: "gpt-realtime"
  vision_model: "gpt-5.5"
  tts_model: "gpt-4o-mini-tts"
  tts_voice: "alloy"
  realtime_voice: "alloy"
  vision_detail: "medium"

audio:
  samplerate: 24000
  block_ms: 50               # mic chunk size
  speaker_buffer_ms: 200

camera:
  host: "127.0.0.1"
  request_port: 60000
  vision_resize_width: 1024
  vision_jpeg_quality: 85

robot:
  domain_id: 1
  interface: "lo"

safety:
  walk:
    vx_max: 0.3
    vy_max: 0.1
    wz_max: 0.4
    duration_max_s: 1.5
    duration_min_s: 0.2
  say:
    max_chars: 200
  watchdog:
    max_frame_age_s: 2.0
    max_lowstate_age_s: 0.5

run_mode: "confirm"   # observe | confirm | active
```

Env overrides (highest priority): `OPENAI_API_KEY` (required), `OPENAI_REALTIME_MODEL`, `OPENAI_VISION_MODEL`, `OPENAI_TTS_MODEL`.

## 8. Dependencies

Added to `va-demo/requirements.txt`:
```
openai>=1.55.0
sounddevice>=0.4.7
websockets>=12
pyyaml
numpy
opencv-python
pyzmq
```

The `agi` conda env already has zmq/cv2/numpy/pyyaml/websockets. We additionally `pip install openai sounddevice`. `sounddevice` ships a Linux wheel that bundles PortAudio so no apt is needed.

The package depends on:
- `unitree_sdk2py` (already installed in `agi`)
- `teleimager` (already installed in `agi`)
- `g1_sim_demo.g1_sim_rl_combo` (sibling package; we add `~/unitree/unitree-notes/g1_sim_demo` to `sys.path` at runtime so we can `from g1_sim_rl_combo import ComboController, DeployCfg, Policy, build_arm_actions, POLICY_YAML, POLICY_ONNX`).

## 9. Verification plan

| Layer | Verification | Needs live service? |
|---|---|---|
| Imports | `python -c "import va_demo; from va_demo import audio_io, camera, vision, tts, skills, safety, realtime_agent, main"` | no |
| Safety unit tests | `pytest tests/test_safety.py` — whitelist, numeric bounds, mode gating | no |
| Skills unit tests | `pytest tests/test_skills_mock.py` — gesture name map, walk bound clamping (mocked ComboController) | no |
| Audio loopback | `python scripts/audio_loopback.py` — mic→speaker echo for 5 s, prints RMS | mic+speaker |
| Camera + vision | `python scripts/camera_debug.py` — pulls frame, sends to vision, prints | TeleImager + OPENAI_API_KEY |
| TTS | `python scripts/tts_debug.py "你好，我是 G1。"` | speaker + OPENAI_API_KEY |
| Skills only | `python scripts/skill_debug.py` — exercise walk/gesture interactively | MuJoCo + lowstate |
| Vision loop | `python scripts/vision_loop_debug.py` — 1 Hz frame→vision→print | TeleImager + OPENAI_API_KEY |
| Full demo | `python -m va_demo.main` | all of the above |

Initial verification run by the implementer covers the first three rows (no live services needed). Live-service runs are the user's responsibility — README documents the exact start order.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| WSL audio jitter | `audio_loopback.py` proves the path; speaker buffer 200 ms; mic block 50 ms. |
| OpenAI Realtime SDK API drift | Wire-protocol events handled by hand; `openai.beta.realtime` used opportunistically, raw `websockets` fallback. |
| ComboController's 50 Hz `RecurrentThread` vs asyncio | All public methods are thread-safe (existing `_cmd_lock` / `_arm_lock`); skills coroutines call them directly. `asyncio.sleep` for duration only. |
| Vision API latency (~1–3 s) | Run as tool call, not in a tight loop. Realtime model speaks "稍等" while waiting if it chooses. Tool result then drives the answer. |
| TTS and Realtime audio competing for speaker | `say` tool is allowed, but for v1 we recommend the model use direct Realtime audio for replies. `say` is for canned/agent-initiated TTS only. Both feed the same `SpeakerStream`; no mixer in v1. |
| `gpt-5.5` model id may not exist on the user's account | Configurable per env var; fall back to `gpt-5` if needed. README documents. |
| Vision request stalls on missing frame | Watchdog: frame age > 2 s → tool returns `{ok: false, reason: "no recent frame"}`. |

## 11. File checklist for implementation

```
va-demo/
├── README.md
├── requirements.txt
├── configs/va_demo.yaml
├── va_demo/__init__.py
├── va_demo/audio_io.py
├── va_demo/camera.py
├── va_demo/vision.py
├── va_demo/tts.py
├── va_demo/skills.py
├── va_demo/safety.py
├── va_demo/realtime_agent.py
├── va_demo/prompts.py
├── va_demo/main.py
├── scripts/audio_loopback.py
├── scripts/camera_debug.py
├── scripts/tts_debug.py
├── scripts/skill_debug.py
├── scripts/vision_loop_debug.py
├── tests/__init__.py
├── tests/test_safety.py
└── tests/test_skills_mock.py
```
