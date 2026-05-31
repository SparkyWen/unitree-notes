# Twilio Voice + OpenAI Realtime → G1 Robot Phone Bridge

**Status**: design approved, awaiting implementation plan
**Date**: 2026-05-24
**Branch**: `feature/mcp-twilio`
**Owner**: Helios

## Problem

Today the G1 voice loop runs on the laptop's local mic and speakers
(`va-demo/va_demo/audio_io.py` → `va-demo/va_demo/realtime_agent.py` →
`g1_brain/skills/skill_server.py`). The operator must be physically
next to the laptop to give voice commands.

We want the same conversational control over a phone call, so the
operator can dial in from anywhere and tell the robot to walk, wave,
stop, or describe what it sees. The minimum proof of success is:
operator picks up a phone call placed by the system, says *"wave your
right hand"*, and the G1 in the local MuJoCo sim actually waves while
the Realtime model replies *"Done."* on the call.

## Definition of done

Six-step live verification, recorded in a verification log:

1. `curl https://<public-host>/healthz` returns 200 from an external network.
2. `twilio_dialer.dry_run()` confirms Twilio creds (`GET /Accounts/{sid}.json` succeeds).
3. MuJoCo sim + `agent_main.py --enable-phone --mode active` both running; bridge log shows `phone bridge listening on :8787`.
4. `python -m g1_brain.phone.call_me --to +61411706848` → operator's phone rings, CallSid logged.
5. Operator picks up, hears Realtime greeting, exchanges one round-trip ("say hello in French") — audio clear both ways, latency ≤ ~2 s round-trip.
6. Operator says **"wave your right hand"** → bridge log shows `gesture(name="wave_right")` → safety + vision-gate passed → DDS dispatched → G1 in MuJoCo waves visibly → Realtime says "Done." Operator says "goodbye" → model calls `end_call()`, call tears down, voice lease released.

Anything short of step 6 = not done.

## Architecture

```
                                            ┌──────────────────────────────────────────────┐
   ☎ +61411706848  ◄────PSTN────► Twilio    │  WSL2 laptop (single host)                   │
                                  Voice     │                                              │
                                    │       │  ┌────────────────┐                          │
                                    │       │  │ MuJoCo sim     │ ◄── DDS ──┐              │
                                  TwiML     │  │ (unitree_mujoco)│           │              │
                                  <Connect> │  └────────────────┘           │              │
                                  <Stream/> │                                │              │
                                    │       │  ┌────────────────────────────┴──────────┐   │
                                    │       │  │ g1_brain process (agent_main.py)      │   │
                                    ▼       │  │                                       │   │
                            Media Streams   │  │  ┌─────────────────────────────────┐  │   │
                              wss bidir     │  │  │ NEW: phone/bridge_server.py     │  │   │
                  ┌─────────► (μ-law/8k)    │  │  │  - aiohttp WS srv on :8787      │  │   │
                  │                         │  │  │  - validate Twilio signature    │  │   │
       reverse    │      ┌──────────────────┼──┼──┤  - μlaw8k ⇄ PCM16-24k transcode │  │   │
       proxy      │      │                  │  │  └──┬──────────────────────────┬───┘  │   │
       (TLS)      │      │                  │  │     │                          │      │   │
  ┌──────────────┐│      │                  │  │     ▼                          ▼      │   │
  │ Public host  ├┘      │                  │  │  ┌─────────────────┐  ┌────────────────┐ │
  │  *.example   │ wss ──┘                  │  │  │ phone/realtime_ │  │ skills/        │ │
  │  ─────────►  │                          │  │  │ session.py      │  │ skill_server.py│ │
  │ nginx / cf   │ ◄──── (init from REST) ──┼──┤  │  - OpenAI RT WS │  │  (existing)    │ │
  │ tunnel       │                          │  │  │  - tool dispatch│──►│ ─► DDS ─►sim   │ │
  └──────┬───────┘                          │  │  └─────┬───────────┘  └────────────────┘ │
         ▲                                  │  │        │                                  │
         │                                  │  │        ▼                                  │
  ┌──────┴───────┐  REST POST /Calls        │  │  ┌────────────────────┐                  │
  │ phone/       │  ◄───────── triggers ────┼──┤  │ safety/supervisor  │ + vision_risk    │
  │ twilio_dialer│             call         │  │  │ (existing, shared) │   gate (existing)│
  └──────────────┘                          │  └───────────────────────────────────────────┘
         ▲
         │
    CLI: python -m g1_brain.phone.call_me
    OR skill: start_phone_call() from va-demo
```

**Single process, single host.** The bridge runs inside the existing
`g1_brain` runtime, sharing the same `SafetySupervisor` and `SkillServer`
instances as the local va-demo path. The public host is dumb TLS
termination + reverse-proxy provisioned per
`TWILIO_BRIDGE_PUBLIC_ENDPOINT.md`; the bridge code does not know or care
which option (Cloudflare Tunnel vs nginx + autossh) sits in front of it.

Two voice paths share one brain core:
- Local: `va-demo/audio_io.py` → `va-demo/realtime_agent.py` → skills
- Phone: `phone/bridge_server.py` → `phone/realtime_session.py` → **same** skills + supervisor

Mutual exclusion via a process-wide `VoiceLeaseManager` (see §Concurrency).

## File layout

```
g1_brain/g1_brain/phone/                          # NEW package
├── __init__.py
├── config.py                  # Pydantic TwilioConfig (loads from env)
├── twilio_dialer.py           # REST: dial outbound, build TwiML
├── bridge_server.py           # aiohttp WS server + per-call PhoneSession
├── audio_codec.py             # μ-law/8k ⇄ PCM16/24k
├── realtime_session.py        # OpenAI Realtime WS + tool dispatch
├── voice_lease.py             # process-wide LOCAL_MIC | PHONE lease
├── call_me.py                 # CLI entry: python -m g1_brain.phone.call_me
└── tunnel_health.py           # /healthz + Twilio sig verification

g1_brain/g1_brain/skills/skill_server.py          # +1 skill: start_phone_call()
g1_brain/g1_brain/apps/agent_main.py              # +--enable-phone flag
g1_brain/configs/g1_brain.yaml                    # +phone: section
g1_brain/.env.example                             # +TWILIO_* + PUBLIC_BRIDGE_URL
g1_brain/tests/phone/
├── test_audio_codec.py
├── test_twilio_dialer.py
├── test_bridge_session.py
├── test_signature_verify.py
├── test_voice_lease.py
├── test_safety_passthrough.py
├── test_phone_session_run_mode.py
└── test_estop_during_call.py
```

### Component responsibilities

| File | Responsibility | Depends on |
|---|---|---|
| `phone/config.py` | Reads `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET`, `TWILIO_FROM_NUMBER`, `PUBLIC_BRIDGE_URL`, `PHONE_ALLOWED_CALLERS`. Pydantic; raises on missing required at boot. | env only |
| `phone/twilio_dialer.py` | `dial(to: str) -> CallSid` — builds TwiML `<Connect><Stream url="{PUBLIC_BRIDGE_URL}"><Parameter name="brain_session_id" value="<uuid>"/></Stream></Connect>`; POSTs `/2010-04-01/Accounts/{sid}/Calls.json`. `dry_run()` helper for credential check. | `twilio` SDK |
| `phone/bridge_server.py` | aiohttp app, routes `/twilio` (WS) + `/healthz` (JSON). On accept: validate `X-Twilio-Signature`, validate caller against `PHONE_ALLOWED_CALLERS`, spawn one `PhoneSession`, acquire voice lease. | `audio_codec`, `realtime_session`, `voice_lease`, `tunnel_health` |
| `phone/audio_codec.py` | `mulaw8k_to_pcm24k(b64) -> bytes`, `pcm24k_to_mulaw8k(bytes) -> b64`. Resampling via `scipy.signal.resample_poly` (up=3, down=1). Frame size: 160 B μ-law in → 1920 B PCM16 out per 20 ms. | numpy, scipy, audioop |
| `phone/realtime_session.py` | `class PhoneRealtimeSession`: opens `wss://api.openai.com/v1/realtime?model=gpt-realtime`, sends `session.update` (phone preamble + base prompt, tool schemas from `skills/tool_schemas.py`, `pcm16` in/out, server VAD), forwards inbound PCM, dispatches tool calls to injected `SkillServer`, returns audio to caller. | `g1_brain/brain/prompts.py`, `skills/tool_schemas.py`, `skills/skill_server.SkillServer`, `safety/supervisor.SafetySupervisor` |
| `phone/voice_lease.py` | `VoiceLeaseManager` with `LOCAL_MIC` and `PHONE` leases. `acquire(name)` flips a shared flag; `release()` clears it. va-demo wake-word loop polls the flag and idles when not the holder. | asyncio |
| `phone/call_me.py` | `python -m g1_brain.phone.call_me [--to +61...]` → `twilio_dialer.dial()`, prints CallSid, exits. Bridge must already be running. | `twilio_dialer` |
| `phone/tunnel_health.py` | `validate_twilio_signature(url, params, header, auth_token) -> bool` (HMAC-SHA1, constant-time compare per Twilio docs); `/healthz` response builder. | hmac, hashlib |

### Reuse boundaries (zero duplication)

- **Prompts**: import base from `g1_brain/brain/prompts.py`, prepend a small phone-call preamble ("You are Sparky on a phone call. The caller cannot see the robot; describe what you're doing.").
- **Tool schemas**: import from `g1_brain/skills/tool_schemas.py` — identical surface to local va-demo.
- **Skill execution**: call the same `SkillServer` instance — DDS, supervisor, vision risk gate all stay where they are.
- **Audio**: phone path bypasses `audio_io.py` entirely. No local mic/speaker access from a phone session.

## Data flow and call lifecycle

### Phase 1 — outbound dial

```
[CLI: python -m g1_brain.phone.call_me --to +61411706848]
        │
        ▼
twilio_dialer.dial(to)
        │  POST https://api.twilio.com/2010-04-01/Accounts/AC.../Calls.json
        │  Body: To=+61411706848 & From=+14232502873
        │        & Twiml=<Response><Connect><Stream url="wss://your-host/twilio">
        │                  <Parameter name="brain_session_id" value="<uuid>"/>
        │                </Stream></Connect></Response>
        ▼
Twilio answers with CallSid → logged. Twilio places PSTN call.
```

`<Parameter name="brain_session_id" value="<uuid>"/>` is set so the
bridge can correlate the inbound WS to the outbound dial and reject
stale / duplicate WS attachments.

### Phase 2 — phone rings, WS attaches

```
Phone rings → operator picks up → Twilio opens WS to wss://<host>/twilio
       │
       ▼
public proxy forwards → WSL2 bridge_server:8787
       │
       ▼
bridge_server:
   - validate X-Twilio-Signature (HMAC-SHA1 of URL+sorted params w/ AuthToken)
     ↳ mismatch → 403, close
   - read first "start" event, check customParameters.brain_session_id is recent
     AND start.from is in PHONE_ALLOWED_CALLERS
     ↳ fail → close
   - acquire voice lease "PHONE"
       ↳ contested → send <Say>busy</Say>-style audio, close
   - spawn PhoneSession
       ↳ open OpenAI Realtime WS
       ↳ send session.update (prompts, tools, audio formats, voice, server VAD)
       ↳ kick greeting: "Hi, this is Sparky. What would you like me to do?"
```

### Phase 3 — bidirectional audio

```
Inbound (operator → robot)                 Outbound (robot → operator)
─────────────────────────                  ──────────────────────────
Twilio {"event":"media",                   OpenAI evt
        "media":{"payload":<b64>}}                "response.output_audio.delta"
   │     (μ-law 8k, 20 ms = 160 B)            │  (PCM16 24k, base64)
   ▼                                            ▼
audio_codec.mulaw8k_to_pcm24k               audio_codec.pcm24k_to_mulaw8k
   │     (decode + upsample 3x)                │  (downsample 3x + μ-law encode)
   ▼                                            ▼
OpenAI WS                                   Twilio WS
   "input_audio_buffer.append"                 {"event":"media",
   {"audio": <b64>}                             "streamSid":<sid>,
                                                "media":{"payload":<b64>}}
```

Server-side VAD on OpenAI handles turn detection. No manual commits needed.

### Phase 4 — tool call

```
OpenAI evt "response.function_call_arguments.done"
   { call_id, name:"gesture", arguments:{name:"wave_right"} }
       │
       ▼
realtime_session._dispatch_tool_call(name, args)
       │     wrapped in asyncio.wait_for(timeout=5.0)
       ▼
SkillServer.invoke(name, args)              ← shared instance
       │
       ├─► SafetySupervisor.check()         (pose, watchdog, scene, run_mode)
       │       blocked → return {"ok":false,"reason":"<why>"}
       │
       ├─► vision_risk_gate.review()        (head-cam JPEG → GPT-5.5)
       │       RISK → return {"ok":false,"reason":"vision_risk:<text>"}
       │       SAFE → proceed
       │
       ├─► dispatch via DDS → ComboController → robot waves
       │
       ▼
return {"ok":true, "summary":"waved right hand for 1.2s"}
       │
       ▼
realtime_session sends to OpenAI:
   "conversation.item.create" type=function_call_output
   { call_id, output: "{\"ok\":true,...}" }
   "response.create"
       │
       ▼
Realtime synthesizes "Done — waved my right hand." → phase 3 outbound audio
```

### Phase 5 — hangup

| Trigger | Behaviour |
|---|---|
| Operator hangs up | Twilio sends `{"event":"stop"}` → `PhoneSession.close()` → defensive `SkillServer.invoke("stop", {})` → OpenAI WS closed → voice lease released |
| Model calls `end_call()` | Bridge calls Twilio REST `POST /Calls/{sid}.json` with `Status=completed` → same cleanup |
| Bridge crash | aiohttp app supervisor restarts; in-flight call dies; PSTN side hangs up on WS silence (~15 s); SafetySupervisor watchdog (`lowstate_max_age_s=0.5`) stops the robot regardless |
| OpenAI Realtime WS drops | Bridge plays Twilio `<Say>` "lost the AI, ending the call" → close → cleanup |

### Tool surface

**Inside a phone session** (Realtime model on the call can invoke):

- `walk(vx, vy, wz, duration_s)` — existing
- `gesture(name)` — existing
- `stop()` — existing
- `describe_scene()` — existing; returns head-cam scene description as text the model can speak
- `end_call()` — NEW, phone-only; calls Twilio REST to terminate
- `say(...)` — NOT exposed; Realtime speaks directly, no separate TTS
- `start_phone_call(...)` — NOT exposed; would recurse, and the caller is already on the line

**On the local va-demo session** (Hi-Sparky wake-word path), the existing
tool surface gains exactly one entry:

- `start_phone_call(to: str)` — NEW; dials via `twilio_dialer.dial()`,
  acquires `PHONE` lease, gracefully suspends the local mic loop. After
  the call ends and the lease releases, the local loop resumes.

### Latency budget (target, measured during verification)

| Hop | Target |
|---|---|
| Phone → Twilio (PSTN) | ~80 ms |
| Twilio → public host → WSL2 | <50 ms intra-region; 100–300 ms cross-region |
| Resample + bridge enqueue | <5 ms per 20 ms frame |
| OpenAI Realtime first-token | 300–800 ms |
| Tool execution (gesture) | 50–200 ms (supervisor + first DDS frame) |

Total "operator finishes speaking → robot starts moving" ≈ 1–2 s,
dominated by Realtime. We measure on the real verification and record
the number.

## Safety

### Auth

Two trust layers, both fail-closed:

1. **Twilio → bridge**: every WS upgrade carries `X-Twilio-Signature`.
   HMAC-SHA1(URL + sorted POST params, `TWILIO_AUTH_TOKEN`), constant-time
   compare. Mismatch → 403. Implemented in `tunnel_health.validate_twilio_signature`.
2. **Caller identity**: first Twilio `start` event includes the call's
   `From` number. We check against `PHONE_ALLOWED_CALLERS` (env list);
   not whitelisted → close immediately.

No spoken passphrase in v1 — outbound calls only ring the To-number we
dialed, single-caller whitelist suffices for the personal-phone demo.

### Robot safety

Zero new safety code. Phone tool calls go through the same chain as the
local mic path:

```
tool_call
   │
   ▼
SafetySupervisor.check()
   ├─ pose: projected gravity z ≤ -0.85
   ├─ watchdog: lowstate < 0.5 s, head_frame < 2 s
   ├─ scene: nearest_obstacle ≥ 0.6 m, nearest_person ≥ 0.8 m
   ├─ walk caps: |vx|≤0.2, |vy|≤0.1, |wz|≤0.3, dur 0.2–60 s
   └─ E-stop file present? → reject all motion
   │
   ▼
vision_risk_gate.review() (head-cam JPEG + GPT-5.5)
   ├─ SAFE → execute
   └─ RISK → reject, reason → model → spoken back to caller
```

Phone session forces `run_mode=active` for its duration (no y/N terminal
reachable from the call). The vision_risk_gate replaces the y/N — it's
designed for exactly this. If `safety.vision_gate.enabled=false` in
config, bridge refuses to start phone sessions and logs why. Fail-closed.

### E-stop during call

Existing `/tmp/g1_brain_estop` file + `estop_listener` (ESC key) work
unchanged. New behaviour: when E-stop trips mid-call, bridge injects a
Realtime system message "Emergency stop engaged" so the operator hears
it spoken. Motion tool calls stay rejected until cleared.

### Concurrency

Hard rule: only one Realtime session may issue tool calls at a time.
Enforced via `phone/voice_lease.py`:

- Two leases: `LOCAL_MIC` (default) and `PHONE`.
- `PhoneSession.start()` calls `acquire("PHONE")`:
  - flips a shared flag the va-demo wake-word loop polls each iteration;
    loop sees `PHONE` lease, skips wake detect and any in-flight utterance,
    idles silently;
  - cancels any in-flight local Realtime tool call (only the lease
    holder dispatches).
- `PhoneSession.close()` releases → wake-word loop resumes.
- Contention: second caller gets immediate "busy" tool result; outbound
  `call_me` CLI errors before placing the call.

If va-demo isn't running, the lease is moot — phone takes it freely.

### Failure modes

| Failure | Behaviour |
|---|---|
| Twilio WS drops mid-call | `finally`: defensive `stop()`, close OpenAI WS, release lease |
| OpenAI Realtime WS drops | Inject `<Say>` "lost the AI", close call, cleanup |
| Bridge crash | PSTN side hangs up after WS silence; supervisor watchdog stops robot |
| Public tunnel dies | Twilio retries WS briefly, then ends call |
| Tool call hangs >5 s | `asyncio.wait_for` timeout → `{"ok":false,"reason":"timeout"}` → model speaks reason |
| Caller silent >30 s | Bridge timer auto-`end_call` to bound minutes |
| `OPENAI_API_KEY` missing at boot | Bridge refuses to accept WS, `/healthz` returns 503 |
| Vision gate dependency down | Per existing gate: fail-closed → reject motion → model speaks reason |

## Credentials

Six new env vars in `g1_brain/.env` (gitignored):

```
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_API_KEY_SID=SK...
TWILIO_API_KEY_SECRET=...
TWILIO_FROM_NUMBER=+14232502873
PUBLIC_BRIDGE_URL=wss://<host>/twilio
PHONE_ALLOWED_CALLERS=+61411706848
```

`g1_brain/.env.example` (committed) holds placeholders only. `config.py`
validates at boot, not at first call. **After demo, rotate
`TWILIO_AUTH_TOKEN` and `TWILIO_API_KEY_SECRET`** — they were shared in
the design conversation.

## Triggers

Two ways to start a call, both feed `twilio_dialer.dial(to)`:

1. **CLI**: `python -m g1_brain.phone.call_me [--to +61...]`. Default
   `--to` from `PHONE_ALLOWED_CALLERS[0]`. Bridge must already be
   running.
2. **Voice from local va-demo**: new `start_phone_call(to: str)` skill
   in `skills/skill_server.py`. Operator says "Hi Sparky, call me" →
   wake-word → Realtime → `start_phone_call` → `twilio_dialer.dial()`.
   When the call connects, the voice lease flips to `PHONE` and the
   local mic loop quietly steps aside.

## Configuration

New `phone:` section in `g1_brain/configs/g1_brain.yaml`:

```yaml
phone:
  enabled: false              # set true OR pass --enable-phone on agent_main
  bind_host: "0.0.0.0"
  bind_port: 8787
  call_idle_timeout_s: 30     # auto end_call if caller silent
  tool_timeout_s: 5.0         # wrap SkillServer.invoke
  realtime_model: "gpt-realtime"
  realtime_voice: "alloy"
  greeting: "Hi, this is Sparky. What would you like me to do?"
```

`agent_main.py --enable-phone` overrides `phone.enabled=true` for that
process.

## Testing

### Unit tests (CI, no network / Twilio / robot)

All under `g1_brain/tests/phone/`, all pure Python:

| Test | Pins |
|---|---|
| `test_audio_codec.py` | round-trip μ-law 8k ↔ PCM 24k; THD < -40 dB on 1 kHz sine; frame sizes (160 B in → 1920 B out / 1920 B in → 160 B out per 20 ms) |
| `test_twilio_dialer.py` | mocked `requests.post`; URL, basic auth header, TwiML body, embedded `brain_session_id` |
| `test_signature_verify.py` | known Twilio test vectors HMAC match; tampered URL or params reject |
| `test_bridge_session.py` | fake Twilio WS replays recorded session; injected tool-call event causes `SkillServer.invoke(gesture, wave_right)`; defensive `stop()` on hangup |
| `test_voice_lease.py` | `LOCAL_MIC` and `PHONE` mutually exclude; busy on contention; release re-enables local |
| `test_safety_passthrough.py` | `walk(vx=1.5)` rejected by supervisor; rejection text reaches model response |
| `test_phone_session_run_mode.py` | starting phone session forces `run_mode=active`; restored on close |
| `test_estop_during_call.py` | E-stop touched mid-call → next motion tool call rejected with E-stop reason |

CI runs on the existing constraints — no Twilio creds, no MuJoCo, no sim.

### Live E2E verification (done gate)

The six steps in §Definition of done, in order. Evidence saved to a
verification log (`/tmp/twilio_bridge_verify_2026-05-24.log`) with
timestamps, request/response snippets, MuJoCo screenshot at step 6, the
exact CallSid, latency measurement from step 5.

Driver responsibility: I run steps 1–3 from this session, then ask the
operator to pick up the phone for steps 4–6 while I watch logs +
MuJoCo and report. Failure at any step → I debug in place, retry, and
re-report. Done only after step 6 observed.

**Explicitly not claimed**:

- Latency is good on the operator's network unless measured.
- Concurrent calls work (we test with 1).
- Cellular dropouts handled gracefully (we test on stable connection).

## Out of scope (v1)

- Twilio MCP server integration (we use the REST SDK directly for outbound dial; MCP is appropriate only when the *model itself* should be able to start additional calls / send SMS mid-conversation).
- Inbound calls (operator dialing Twilio number; possible later by adding a `/twiml/inbound` route).
- Multiple concurrent calls.
- SMS / DTMF / IVR.
- Recording / transcription persistence to memory subsystem (the memory daemon already logs Realtime turns — phone turns will flow through the same path because they share the brain core).
- Real-robot path (sim only for v1; same SkillServer abstracts both, so real-robot enablement is just a config flag change once tested).
- Cellular failover / multi-region tunnel.

## Open questions resolved during design

| Question | Resolution |
|---|---|
| Bridge process placement | WSL2 alongside g1_brain; public host is dumb reverse proxy |
| Trigger method | Both CLI and voice ("Hi Sparky, call me") |
| Twilio MCP vs REST | REST directly — MCP adds no value for outbound dial |
| Run mode during call | Forced `active`; vision_risk_gate replaces y/N |
| Single voice channel | `VoiceLeaseManager` mutual exclusion |
| Sim or real robot | Sim for v1 done gate |
| Authentication | Twilio HMAC signature + caller-id whitelist |
| Public tunnel | User-provisioned per `TWILIO_BRIDGE_PUBLIC_ENDPOINT.md` |
