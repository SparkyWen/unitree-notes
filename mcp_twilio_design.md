# mcp_twilio_design.md — Twilio Voice + OpenAI Realtime → G1 Robot

**Status**: design complete, awaiting `PUBLIC_BRIDGE_URL` from VPS agent, then implementation
**Branch**: `feature/mcp-twilio`
**Owner**: Helios
**Date**: 2026-05-24
**Companion spec**: `docs/superpowers/specs/2026-05-24-twilio-realtime-phone-bridge-design.md`
**Companion runbook**: `TWILIO_BRIDGE_PUBLIC_ENDPOINT.md` (provisioned by VPS agent)

---

## 0. Table of contents

1. Executive summary
2. Goals, non-goals, definition of done
3. System architecture (three views: topology / process / sequence)
4. Component catalogue (every file, every class, every method)
5. Audio pipeline (μ-law/PCM details, framing, jitter, clock)
6. Twilio integration (REST dial-out + Media Streams protocol)
7. OpenAI Realtime integration (events, session config, tool dispatch)
8. Tool surface (phone-session vs local-mic-session)
9. Safety architecture (auth, robot safety, E-stop, threat model)
10. Concurrency model (VoiceLeaseManager, asyncio task tree)
11. Call lifecycle state machine
12. Configuration (env vars, yaml keys, CLI flags)
13. Error handling matrix
14. Testing strategy (unit + integration)
15. Live E2E verification protocol
16. Deployment topology (WSL2 + public host)
17. Public endpoint provisioning (the VPS-agent contract)
18. Operational runbook (start / monitor / debug / rotate)
19. Future work / out-of-scope
20. Decisions log
21. Appendices (API references, sample payloads, glossary)

---

## 1. Executive summary

We add the ability to operate the G1 humanoid over a regular phone
call. The system places an outbound call to a whitelisted operator
phone number, attaches the call's bidirectional audio to an OpenAI
Realtime voice session, and lets the operator say things like *"wave
your right hand"* or *"walk forward one step"*. The model issues tool
calls that flow through the **existing** safety supervisor + vision
risk gate + skill server stack and actuate the robot (sim in v1, real
robot via the same path in a later phase).

The integration touches:

- **Twilio Voice + Media Streams** for PSTN audio (μ-law/8 kHz, base64
  over WebSocket).
- **OpenAI Realtime API** (`gpt-realtime` model) for ASR + dialogue +
  TTS in one duplex session.
- **g1_brain** for robot reasoning, safety, and skill dispatch — reused
  intact.
- **A new `g1_brain/phone/` package** that is the only net-new module.

The local mic path (`va-demo`) is **not** modified beyond adding one
new skill (`start_phone_call`). When a call is active, a
process-wide voice lease tells the local wake-word loop to step aside
quietly.

Reachability from the public Twilio infrastructure to the WSL2 laptop
is solved by a TLS-terminating reverse proxy on a public host the
operator already controls — its concrete form (Cloudflare named tunnel
vs nginx + autossh) is delegated to a VPS-side agent and lives in
`TWILIO_BRIDGE_PUBLIC_ENDPOINT.md`.

---

## 2. Goals, non-goals, definition of done

### 2.1 Goals

- G1 in the local MuJoCo sim performs operator-requested motions
  spoken over a normal phone call.
- All robot tool calls flow through the same `SafetySupervisor` and
  `vision_risk_gate.review()` chain as the local mic path. **No new
  safety code.**
- Operator can trigger the call two ways: a CLI command, or by
  speaking *"Hi Sparky, call me"* to the local mic.
- The full system (sim + brain + bridge) starts in three terminals,
  reusing the existing run mode the operator already knows.
- Credentials and tunnel configuration live in env vars and a single
  ops runbook; nothing secret is committed.
- Latency budget: operator-finishes-speaking → robot-starts-moving
  ≤ ~2 s on a stable connection.

### 2.2 Non-goals (v1)

- Inbound calls (operator dialling the Twilio DID). Possible add-on
  later by mounting a `/twiml/inbound` route.
- Twilio MCP server integration. The Twilio REST SDK suffices for
  outbound dial; MCP is appropriate only if the model itself should
  initiate additional calls / SMS mid-conversation.
- Concurrent calls. The bridge accepts exactly one phone session at
  a time.
- SMS / DTMF / IVR menus.
- Real robot via DDS to a physical G1. The architecture supports it
  (single config switch), but v1 verifies in sim only.
- Cellular failover or multi-region tunnels.
- Recording / transcription persistence beyond what the existing
  memory subsystem already provides.

### 2.3 Definition of done (six-step gate)

Steps must pass IN ORDER. Anything short of step 6 = not done.

1. **Tunnel reachable**: `curl -i https://<host>/healthz` from an
   external network returns either `200` (backend up) or `502`
   (backend down) — never DNS failure, never TLS error, never 404.
2. **Twilio creds valid**: `twilio_dialer.dry_run()` succeeds
   (`GET /Accounts/{sid}.json` → 200, account friendly name printed).
3. **System running**: MuJoCo sim + `agent_main.py --enable-phone
   --mode active` both up. Bridge log shows
   `phone bridge listening on 0.0.0.0:8787`. G1 standing upright in
   the viewer.
4. **Outbound dial**: `python -m g1_brain.phone.call_me` →
   operator's phone rings, CallSid logged. (If the phone does not
   ring, demo is dead in the water; debug here before proceeding.)
5. **Audio bridge healthy**: operator picks up, hears the greeting
   clearly. Operator says *"say hello in French"*; model replies in
   French audibly. End-to-end audio is intelligible both ways; first
   reply lands within ~2 s.
6. **Robot moves on phone command**: operator says **"wave your right
   hand"**. Bridge log shows `gesture(name="wave_right")` →
   SafetySupervisor passed → vision_risk_gate passed → DDS dispatched.
   G1 in MuJoCo visibly waves. Realtime says *"Done."* Operator then
   says *"goodbye"*; model calls `end_call()`; call tears down; voice
   lease released.

A 7th nice-to-have: trigger the call via voice instead of CLI.
*"Hi Sparky, call me"* → `start_phone_call` skill → step 4 onward.

Verification evidence is recorded to
`/tmp/twilio_bridge_verify_<date>.log` with timestamped event
snippets, CallSid, measured round-trip latency, and a MuJoCo screenshot
at step 6.

---

## 3. System architecture

### 3.1 Topology view

```
                                           ┌──────────────────────────────────────────────┐
   ☎ +61411706848  ◄────PSTN────► Twilio   │  WSL2 laptop (single host, single python)    │
                                  Voice    │                                              │
                                    │      │  ┌────────────────┐                          │
                                    │      │  │ MuJoCo sim     │ ◄── DDS ──┐              │
                                  TwiML    │  │ unitree_mujoco │           │              │
                                  <Connect>│  └────────────────┘           │              │
                                  <Stream/>│                                │              │
                                    │      │  ┌────────────────────────────┴──────────┐   │
                                    │      │  │ g1_brain process (agent_main.py)      │   │
                                    ▼      │  │                                       │   │
                            Media Streams  │  │  ┌─────────────────────────────────┐  │   │
                              wss bidir    │  │  │ NEW: phone/bridge_server.py     │  │   │
                  ┌─────────► μ-law/8k     │  │  │  - aiohttp WS on :8787          │  │   │
                  │                        │  │  │  - validate X-Twilio-Signature  │  │   │
       reverse    │      ┌─────────────────┼──┼──┤  - validate caller-id whitelist │  │   │
       proxy      │      │                 │  │  │  - μlaw8k ⇄ PCM16-24k transcode │  │   │
       (TLS)      │      │                 │  │  └──┬──────────────────────────┬───┘  │   │
  ┌──────────────┐│      │                 │  │     │                          │      │   │
  │ Public host  ├┘      │                 │  │     ▼                          ▼      │   │
  │  e.g.        │ wss ──┘                 │  │  ┌─────────────────┐  ┌────────────────┐ │
  │  sparky-     │                         │  │  │ phone/realtime_ │  │ skills/        │ │
  │  bridge.     │ ◄──── REST dial-out ────┼──┤  │ session.py      │  │ skill_server.py│ │
  │  example     │                         │  │  │ subclass of     │  │  (existing)    │ │
  │  ─────────►  │                         │  │  │ BrainRealtime   │──►│ ─► DDS ─►sim   │ │
  │ nginx / cf   │                         │  │  │ Agent           │  │                │ │
  │ tunnel       │                         │  │  └─────┬───────────┘  └────────────────┘ │
  └──────┬───────┘                         │  │        │                                  │
         ▲                                 │  │        ▼                                  │
         │                                 │  │  ┌────────────────────┐                  │
  ┌──────┴───────┐                         │  │  │ safety/supervisor  │ + vision_risk    │
  │ phone/       │                         │  │  │ (existing, shared) │   gate (existing)│
  │ twilio_dialer│                         │  │  └────────────────────┘                  │
  └──────────────┘                         │  └───────────────────────────────────────────┘
        ▲
        │
  Triggers:
   • CLI: python -m g1_brain.phone.call_me
   • Skill: start_phone_call() called by va-demo Realtime
```

### 3.2 Process view

There is **one Python process** on the WSL2 laptop:
`g1_brain.apps.agent_main`. It is the same process that runs today;
`--enable-phone` adds two background asyncio tasks:

```
agent_main.py (one process)
│
├── perception loop          (existing)
├── safety supervisor        (existing)
├── skill server / DDS       (existing)
├── memory daemon            (existing)
├── local va-demo realtime   (existing — paused while phone lease held)
│
├── NEW: phone.bridge_server.run()         ── aiohttp app on :8787
└── NEW: phone.voice_lease.singleton       ── tiny shared-state object
```

MuJoCo sim is a separate process (`unitree_mujoco.py`), and a third
terminal optionally runs `estop_listener` (unchanged). The local
va-demo is also a separate process when used (`python -m va_demo.main`);
the voice lease object is shared via a small IPC file
(`/tmp/g1_brain_voice_lease`) — simplest cross-process mutex that
works between two Python apps without spinning up extra services.

### 3.3 Sequence view (happy path)

```
Operator      CLI            Twilio       Public         Bridge        OpenAI       SkillServer       Robot
                              REST/PSTN    Proxy         (WSL2)         Realtime    + Safety           (sim)
   │           │                │            │             │              │              │              │
   │           │  call_me       │            │             │              │              │              │
   │           │───────POST─────►│            │             │              │              │              │
   │           │                │  CallSid   │             │              │              │              │
   │           │◄───────────────│            │             │              │              │              │
   │           │ exit 0         │            │             │              │              │              │
   │           │                │ rings phone│             │              │              │              │
   │◄─────────────PSTN ringing──│            │             │              │              │              │
   │ picks up                    │            │             │              │              │              │
   │─────────────PSTN──────────►│            │             │              │              │              │
   │                            │   WS upgrade to bridge URL              │              │              │
   │                            │────────────►│ ────WS───►  │              │              │              │
   │                            │            │             │ validate sig │              │              │
   │                            │            │             │ acquire lease│              │              │
   │                            │            │             │              │              │              │
   │                            │            │             │ open RT WS  │              │              │
   │                            │            │             │─────────────►│              │              │
   │                            │            │             │ session.update              │              │
   │                            │            │             │─────────────►│              │              │
   │                            │            │             │ greeting "Hi, this is..."   │              │
   │                            │            │             │◄─────────────│              │              │
   │                            │            │             │ pcm24k→μlaw8k                              │
   │                            │            │             │────media─────►              │              │
   │                            │←──────RTP──│             │              │              │              │
   │◄────PSTN──"Hi, this is..."─│            │             │              │              │              │
   │ "wave your right hand"     │            │             │              │              │              │
   │──────PSTN─────────────────►│            │             │              │              │              │
   │                            │──RTP──────►│ ─────media──►│ μlaw8k→pcm24k              │              │
   │                            │            │             │─audio.append─►│              │              │
   │                            │            │             │              │ ASR + reason │              │
   │                            │            │             │              │ → tool call  │              │
   │                            │            │             │ function_call_arguments.done │              │
   │                            │            │             │◄─────────────│              │              │
   │                            │            │             │ execute(gesture, wave_right)               │
   │                            │            │             │─────────────────────────────►│              │
   │                            │            │             │              │              │ supervisor.check
   │                            │            │             │              │              │ vision_gate.review
   │                            │            │             │              │              │──DDS──────►│
   │                            │            │             │              │              │            │ wave!
   │                            │            │             │ {"ok":true}  │              │            │
   │                            │            │             │◄─────────────────────────────│            │
   │                            │            │             │ conversation.item.create     │            │
   │                            │            │             │ + response.create            │            │
   │                            │            │             │─────────────►│              │              │
   │                            │            │             │ "Done." audio                │              │
   │                            │            │             │◄─────────────│              │              │
   │                            │            │             │────media────►│              │              │
   │◄──PSTN──"Done."────────────│            │             │              │              │              │
   │ "goodbye"                  │            │             │              │              │              │
   │──────PSTN─────────────────►│ ──media───►│ ────media──►│ ─audio.append►│              │              │
   │                            │            │             │              │ end_call tool│              │
   │                            │            │             │◄─────────────│              │              │
   │                            │ POST /Calls/{sid} status=completed                                    │
   │                            │◄────────────│ ◄───REST──── │              │              │              │
   │                            │ hangs up   │             │              │              │              │
   │◄──PSTN call ended──────────│            │             │              │              │              │
   │                            │ stop event │             │              │              │              │
   │                            │ ──────────►│ ──stop───►  │ defensive stop()           │              │
   │                            │            │             │─────────────────────────────►│              │
   │                            │            │             │ release lease               │              │
```

### 3.4 Why this shape

- **One process, in-process tool dispatch.** Putting the bridge inside
  the brain process means tool calls become direct python method
  invocations on the same `SkillServer` instance the local mic path
  already uses. No extra HTTP, no extra serialisation, no second
  safety supervisor to keep in sync. This is the single most important
  property — it preserves safety guarantees we already have.
- **Public host as dumb reverse proxy.** The WSL2 laptop has no public
  IP; we cannot route Twilio directly to it. The minimum-complexity
  solution is a TLS-terminating proxy on a host the operator already
  controls. The bridge code doesn't know or care which option
  (Cloudflare named tunnel vs nginx + autossh) sits in front of it,
  because the contract is the same: forward exactly `/twilio` (with
  WebSocket Upgrade headers intact) and `/healthz` to the WSL2
  backend.
- **Reusing `BrainRealtimeAgent`.** That class already wires the
  OpenAI Realtime event stream to the `SkillServer.execute` API and
  the safety/logging hooks. The phone session subclasses it and
  overrides only the audio transport. The diff is small precisely
  because the brain side is already correctly abstracted.

---

## 4. Component catalogue

### 4.1 New files

```
g1_brain/g1_brain/phone/                          # NEW package
├── __init__.py
├── config.py                  # Pydantic TwilioConfig + PhoneConfig
├── audio_codec.py             # μ-law/8k ⇄ PCM16/24k
├── voice_lease.py             # cross-process LOCAL_MIC | PHONE lease
├── tunnel_health.py           # /healthz + Twilio sig verification
├── twilio_dialer.py           # REST dial, TwiML, REST hangup, dry_run
├── twilio_transport.py        # Twilio Media Streams WS protocol adapter
├── realtime_session.py        # PhoneRealtimeSession (subclass)
├── bridge_server.py           # aiohttp WS app + per-call orchestration
└── call_me.py                 # CLI entry: python -m g1_brain.phone.call_me

g1_brain/g1_brain/skills/skill_server.py          # +1 skill: start_phone_call
g1_brain/g1_brain/apps/agent_main.py              # +--enable-phone flag
g1_brain/g1_brain/brain/prompts.py                # +REALTIME_SYSTEM_PROMPT_PHONE
g1_brain/configs/g1_brain.yaml                    # +phone: section
g1_brain/.env.example                             # +TWILIO_* + PUBLIC_BRIDGE_URL

g1_brain/tests/phone/                             # NEW test dir
├── __init__.py
├── conftest.py
├── test_audio_codec.py
├── test_twilio_dialer.py
├── test_twilio_transport.py
├── test_bridge_session.py
├── test_signature_verify.py
├── test_voice_lease.py
├── test_safety_passthrough.py
├── test_phone_session_run_mode.py
└── test_estop_during_call.py
```

### 4.2 Per-module contracts

#### `phone/config.py`

```python
class TwilioConfig(BaseModel):
    account_sid: str            # AC...
    auth_token: SecretStr       # used for signature validation only
    api_key_sid: str            # SK...
    api_key_secret: SecretStr   # used for REST auth (preferred over auth_token)
    from_number: str            # E.164, e.g. +14232502873

class PhoneConfig(BaseModel):
    enabled: bool = False
    bind_host: str = "0.0.0.0"
    bind_port: int = 8787
    public_bridge_url: HttpUrl  # wss://<host>/twilio
    allowed_callers: list[str] = []   # E.164 list
    call_idle_timeout_s: float = 30.0
    tool_timeout_s: float = 5.0
    realtime_model: str = "gpt-realtime"
    realtime_voice: str = "alloy"
    greeting: str = "Hi, this is Sparky. What would you like me to do?"

def load_from_env() -> tuple[TwilioConfig, PhoneConfig]: ...
```

- Fails LOUDLY at boot if required env vars missing; never silently
  defaults a secret.
- Used by both `bridge_server` and `twilio_dialer` (single source of
  truth for Twilio credentials).

#### `phone/audio_codec.py`

```python
def mulaw8k_to_pcm24k(b64_payload: str) -> bytes:
    """Decode μ-law 8 kHz → PCM16 24 kHz. 160 B in → 1920 B out per 20 ms."""

def pcm24k_to_mulaw8k(pcm16_24k: bytes) -> str:
    """Encode PCM16 24 kHz → μ-law 8 kHz base64. 1920 B in → 160 B out per 20 ms."""

class StreamingResampler:
    """Stateful resampler for chunks that don't align to 20 ms boundaries.

    OpenAI Realtime emits audio deltas in arbitrary chunk sizes (~100–600 ms);
    Twilio Media Streams wants exactly 160-byte μ-law payloads per 20 ms.
    StreamingResampler buffers the residual and emits whole-frame chunks.
    """
    def feed_pcm24k(self, pcm: bytes) -> Iterator[str]: ...   # yields μ-law b64
    def feed_mulaw8k(self, b64: str) -> Iterator[bytes]: ...  # yields pcm24k
```

- Decode: `audioop.ulaw2lin(b, 2)` → `scipy.signal.resample_poly(up=3, down=1)`.
- Encode: `resample_poly(up=1, down=3)` → `audioop.lin2ulaw(b, 2)` → base64.
- All numpy `int16` end-to-end (no float intermediate to avoid clipping).
- Unit-tested with a 1 kHz sine: round-trip THD < -40 dB.

#### `phone/voice_lease.py`

```python
class VoiceLeaseManager:
    """Process-and-file-backed mutex for {LOCAL_MIC, PHONE}.

    A simple JSON file at /tmp/g1_brain_voice_lease holds the current
    holder + acquire timestamp. Acquire is fcntl.flock-protected so
    two processes (va-demo + g1_brain) coordinate safely.
    """
    def acquire(self, name: Literal["LOCAL_MIC", "PHONE"], owner: str,
                timeout: float = 1.0) -> bool: ...
    def release(self, name: str, owner: str) -> None: ...
    def current_holder(self) -> Optional[tuple[str, str, float]]: ...
    def watch(self, callback) -> None: ...   # invoked on holder change
```

- The va-demo wake-word loop calls `current_holder()` each iteration;
  when the holder is `PHONE` and not its own owner-id, it skips wake
  detect and waits.
- Lease file format: `{"holder":"PHONE","owner":"call-<uuid>","since":1716...}`.
- `flock(LOCK_EX | LOCK_NB)` on the file for atomic acquire.
- Stale leases (>1 h) are reclaimable.

#### `phone/tunnel_health.py`

```python
def validate_twilio_signature(
    full_url: str, post_params: dict[str, str], header_signature: str,
    auth_token: str
) -> bool:
    """RFC: https://www.twilio.com/docs/usage/security#validating-requests

    Build signed string = full_url + sorted(k+v) for each param;
    HMAC-SHA1(signed_string, auth_token); base64 encode; constant-time
    compare to header_signature.
    """

async def healthz_handler(request) -> Response:
    """Returns {"ok": true, "version": "...", "calls_active": N,
                "openai_reachable": bool, "twilio_creds_ok": bool}.
    """
```

#### `phone/twilio_dialer.py`

```python
class TwilioDialer:
    def __init__(self, config: TwilioConfig, public_bridge_url: str): ...

    async def dial(self, to: str, brain_session_id: str | None = None) -> str:
        """POST /2010-04-01/Accounts/{sid}/Calls.json.
        Returns CallSid. Raises TwilioDialError on 4xx/5xx."""

    async def hangup(self, call_sid: str) -> None:
        """POST /2010-04-01/Accounts/{sid}/Calls/{sid}.json with Status=completed."""

    async def dry_run(self) -> dict:
        """GET /2010-04-01/Accounts/{sid}.json. Used for cred check."""

    def build_twiml(self, brain_session_id: str) -> str:
        """<Response>
              <Connect>
                <Stream url="{public_bridge_url}">
                  <Parameter name="brain_session_id" value="{brain_session_id}"/>
                </Stream>
              </Connect>
            </Response>"""
```

- Auth: prefer API Key SID + Secret (HTTP basic) over Account SID +
  Auth Token (Twilio's own recommendation; rotating API keys is
  cheap, rotating account auth token nukes everything).
- Uses `aiohttp.ClientSession` (we are already inside an asyncio loop).

#### `phone/twilio_transport.py`

```python
class TwilioMediaStreamTransport:
    """Adapter between aiohttp WebSocketResponse (Twilio side) and the
    bytes-in / bytes-out interface PhoneRealtimeSession consumes.

    Twilio events:
      - {"event":"connected", "protocol":"...", "version":"..."}
      - {"event":"start",
         "start":{"streamSid":"...","callSid":"...","tracks":["inbound"],
                  "mediaFormat":{"encoding":"audio/x-mulaw","sampleRate":8000,"channels":1},
                  "customParameters":{"brain_session_id":"..."}}}
      - {"event":"media",
         "media":{"track":"inbound","chunk":"N","timestamp":"...","payload":"<b64>"}}
      - {"event":"mark", "mark":{"name":"..."}}
      - {"event":"stop", "stop":{"accountSid":"...","callSid":"..."}}

    Outbound (we send):
      - {"event":"media", "streamSid":"<sid>", "media":{"payload":"<b64>"}}
      - {"event":"mark",  "streamSid":"<sid>", "mark":{"name":"<id>"}}
      - {"event":"clear", "streamSid":"<sid>"}   # cancel pending audio
    """
    async def start(self, ws: WebSocketResponse) -> StartEvent: ...
    async def iter_inbound_pcm24k(self) -> AsyncIterator[bytes]: ...
    async def send_outbound_pcm24k(self, pcm: bytes) -> None: ...
    async def clear_outbound(self) -> None: ...   # for barge-in
    async def close(self) -> None: ...
```

- Reads the first `connected` + `start` events synchronously; returns
  the `start.customParameters` so the bridge can validate the
  `brain_session_id` and look up the call's `From` for caller-id
  whitelisting.
- Internally uses `audio_codec.StreamingResampler` to handle chunking
  in both directions.
- On barge-in (user starts speaking while assistant audio is still
  playing), sends Twilio `{"event":"clear"}` to flush pending outbound
  audio.

#### `phone/realtime_session.py`

```python
class PhoneRealtimeSession(BrainRealtimeAgent):
    """Reuses 95% of BrainRealtimeAgent. Overrides only:
      - audio source (read from TwilioMediaStreamTransport instead of mic)
      - audio sink   (write to TwilioMediaStreamTransport instead of speaker)
      - the system prompt (prepend phone-call preamble)
      - the tool surface (add end_call, hide start_phone_call)
    """
    transport: TwilioMediaStreamTransport
    dialer: TwilioDialer   # so end_call can hang up
    call_sid: str

    def _resolve_instructions(self) -> str:
        return PHONE_PREAMBLE + super()._resolve_instructions()

    def _resolve_tool_schemas(self) -> list[dict]:
        base = super()._resolve_tool_schemas()
        return [s for s in base if s["name"] != "start_phone_call"] + [END_CALL_SCHEMA]

    async def _execute_tool(self, name: str, args: dict) -> dict:
        if name == "end_call":
            await self.dialer.hangup(self.call_sid)
            return {"ok": True, "summary": "ending call"}
        return await super()._execute_tool(name, args)

    async def _read_user_audio_loop(self) -> None:
        async for pcm in self.transport.iter_inbound_pcm24k():
            await self._send_audio_chunk(pcm)   # parent helper

    async def _write_assistant_audio(self, pcm: bytes) -> None:
        await self.transport.send_outbound_pcm24k(pcm)
```

Three boundaries override the parent; everything else (tool dispatch
via `SkillServer.execute`, safety hooks, conversation logging, plan
state machine, barge-in handling) is inherited.

#### `phone/bridge_server.py`

```python
class BridgeServer:
    def __init__(self, app_ctx: AppContext, phone_cfg: PhoneConfig,
                 twilio_cfg: TwilioConfig): ...

    async def run(self) -> None:
        """Mounts aiohttp app on phone_cfg.bind_host:bind_port."""

    async def _ws_handler(self, request) -> WebSocketResponse:
        # 1. validate Twilio signature
        # 2. accept WS upgrade
        # 3. read Twilio start event
        # 4. validate caller-id against allowed_callers
        # 5. validate brain_session_id (recency, not-already-used)
        # 6. acquire VoiceLeaseManager.PHONE
        # 7. build PhoneRealtimeSession(transport, skill_server, ...)
        # 8. session.run() — blocks until call ends
        # 9. finally: release lease, defensive skill_server.execute("stop", {})

    async def _healthz_handler(self, request) -> Response: ...
```

- One `BridgeServer` instance per `agent_main` process. Holds
  references to the shared `SkillServer` / `SafetySupervisor` /
  `SceneStateBus` (passed in as `AppContext`).
- One concurrent call at a time — enforced both by VoiceLease and by a
  per-server semaphore (defence in depth).

#### `phone/call_me.py`

```python
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default=None,
                        help="defaults to first PHONE_ALLOWED_CALLERS entry")
    parser.add_argument("--config", default="configs/g1_brain.yaml")
    args = parser.parse_args()

    twilio_cfg, phone_cfg = load_from_env()
    to = args.to or (phone_cfg.allowed_callers[0] if phone_cfg.allowed_callers else None)
    if to is None:
        sys.exit("no --to and PHONE_ALLOWED_CALLERS empty")

    dialer = TwilioDialer(twilio_cfg, str(phone_cfg.public_bridge_url))
    sid = await dialer.dial(to)
    print(f"call placed; CallSid={sid}")
```

Single-shot. Does NOT start the bridge; the bridge must already be
running inside `agent_main --enable-phone`.

#### `agent_main.py` (modifications)

```python
parser.add_argument("--enable-phone", action="store_true",
                    help="mount Twilio bridge on phone.bind_port")

# inside main():
if args.enable_phone or cfg.phone.enabled:
    twilio_cfg, phone_cfg = load_from_env()
    bridge = BridgeServer(app_ctx, phone_cfg, twilio_cfg)
    asyncio.create_task(bridge.run())
```

#### `skills/skill_server.py` (one new skill)

```python
async def _start_phone_call(self, args: dict) -> dict:
    to = args.get("to") or self._phone_default_to
    if to is None:
        return {"ok": False, "reason": "no destination configured"}
    if self._dialer is None:
        return {"ok": False, "reason": "phone bridge not enabled"}
    sid = await self._dialer.dial(to)
    return {"ok": True, "summary": f"calling {to}", "call_sid": sid}

# tool schema (added to tool_schemas.py):
START_PHONE_CALL_SCHEMA = {
    "name": "start_phone_call",
    "description": "Place an outbound phone call so the operator can talk to "
                   "Sparky from anywhere. Returns when the call is dialled, "
                   "not when answered.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string",
                   "description": "E.164 number; if omitted, uses the default operator number."}
        }
    }
}
```

Exposed to the **local** Realtime (`BrainRealtimeAgent`), NOT to the
phone Realtime (`PhoneRealtimeSession` filters it out — self-recursion
makes no sense).

---

## 5. Audio pipeline

### 5.1 Sample-rate and codec choices

| Side | Format | Rate | Channels | Frame |
|---|---|---|---|---|
| Twilio Media Streams | G.711 μ-law | 8 kHz | mono | 160 B per 20 ms |
| OpenAI Realtime input | PCM16 LE | 24 kHz | mono | arbitrary |
| OpenAI Realtime output | PCM16 LE | 24 kHz | mono | varies (delta) |

Twilio also supports L16/16k under `<Stream track="..." codec="audio/L16;rate=16000">`,
but the default μ-law/8k is universally compatible and well-tested.
We use the default. (If we ever need lower latency or better quality
later, we can switch to L16/16k by adding `mediaFormat` to the TwiML.)

### 5.2 Resampling math

- Upsample 8k → 24k: integer ratio 1:3, `resample_poly(up=3, down=1)`
  uses an FIR Kaiser window; cheap on CPU (<1 ms per 20 ms frame).
- Downsample 24k → 8k: 3:1, `resample_poly(up=1, down=3)`.
- We keep `int16` end-to-end; scipy converts internally as needed but
  we coerce back to `int16` for the next stage.

### 5.3 Framing & chunking

Inbound (Twilio → OpenAI):

```
Twilio media event → b64.decode → 160 B μ-law (20 ms)
                  → audioop.ulaw2lin → 320 B PCM16-8k
                  → resample_poly 1:3 → 960 B PCM16-24k  (still 20 ms wall time)
                  → b64.encode    → ~1.3 KB
                  → OpenAI evt input_audio_buffer.append {"audio": "<b64>"}
```

Outbound (OpenAI → Twilio):

```
OpenAI evt response.output_audio.delta → b64.decode → N bytes PCM16-24k
                                       (N is variable; typical ~12 KB = 250 ms)
                                       → StreamingResampler.feed_pcm24k(pcm)
                                       → yields whole-frame chunks of 320 B PCM16-8k
                                                 (40 B = 5 ms residual held over)
                                       → resample_poly 3:1 inside the helper
                                       → audioop.lin2ulaw → 160 B μ-law
                                       → b64.encode → Twilio media event
```

`StreamingResampler` is necessary because OpenAI deltas don't align to
20 ms boundaries; without it, every delta would create a tail of
non-frame-aligned audio that either gets dropped (clicks) or padded
with silence (chops).

### 5.4 Clocking

- Twilio sends inbound media every 20 ms (carrier-paced).
- We forward inbound to OpenAI as fast as we decode (no buffering on
  our side — OpenAI's server-VAD does the rate management).
- Outbound to Twilio: Twilio buffers up to a few hundred ms; we send
  whole-frame chunks as the resampler yields them. No need for a
  20 ms-paced send loop — Twilio's playout buffer absorbs jitter.

### 5.5 Barge-in

When OpenAI's server-VAD detects user speech while assistant audio is
still being sent, we get `input_audio_buffer.speech_started`. We then:

1. Call `transport.clear_outbound()` → Twilio `{"event":"clear"}` →
   Twilio drops queued playout audio.
2. (Parent's `RealtimeAgent` already sends `response.cancel` +
   `input_audio_buffer.clear` to OpenAI as part of its barge-in
   handling — we inherit that.)

### 5.6 Echo and self-trigger

The phone path has natural acoustic isolation (the operator's phone
earpiece doesn't acoustically couple to the operator's mouth the way a
laptop's speakers and mic do). We do not need the AEC / wake-word RMS
gate that va-demo uses for the local mic. The Twilio side handles
echo cancellation in the network. We rely on OpenAI's server-VAD for
turn detection.

---

## 6. Twilio integration

### 6.1 Outbound dial REST call

```http
POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Calls.json
Authorization: Basic base64(API_KEY_SID:API_KEY_SECRET)
Content-Type: application/x-www-form-urlencoded

To=%2B61411706848
&From=%2B14232502873
&Twiml=<urlencoded TwiML>
&StatusCallback=https://<host>/twilio/callbacks (optional, v2)
&StatusCallbackEvent=initiated+ringing+answered+completed
&StatusCallbackMethod=POST
```

Response on success:

```json
{ "sid": "CA...", "status": "queued",
  "to": "+61411706848", "from": "+14232502873", ... }
```

We log the `sid` and return it from `dial()`. The `Status` field
goes through `queued → ringing → in-progress → completed`; if you want
in-flight observability you set `StatusCallback` to a webhook
(v2 feature; v1 logs from the Media Streams `start`/`stop` events
suffice).

### 6.2 TwiML payload

```xml
<Response>
  <Connect>
    <Stream url="wss://<host>/twilio">
      <Parameter name="brain_session_id" value="<uuid>"/>
    </Stream>
  </Connect>
</Response>
```

- `<Connect><Stream>` (not `<Start><Stream>`) — Connect terminates
  TwiML execution and hands the call over to the Stream. This is
  what we want; we don't need anything else from TwiML.
- `<Parameter>` values surface in the `start.customParameters`
  payload Twilio sends on WS connect, so we can correlate the
  inbound WS to the outbound dial we placed.

### 6.3 Media Streams WebSocket protocol

Direction: Twilio → us:

| event | when | payload fields |
|---|---|---|
| `connected` | immediately after handshake | `protocol`, `version` |
| `start` | once, after `connected` | `streamSid`, `callSid`, `tracks`, `mediaFormat`, `customParameters` |
| `media` | every 20 ms | `track`, `chunk`, `timestamp`, `payload` (base64 μ-law) |
| `mark` | when we sent a `mark` and Twilio finished playing through it | `name` |
| `stop` | call ended (operator hung up, error, etc.) | `accountSid`, `callSid` |

Direction: us → Twilio:

| event | when | payload fields |
|---|---|---|
| `media` | as fast as resampler yields frames | `streamSid`, `media: {payload}` |
| `mark` | optionally, to learn when a phrase finished playing | `streamSid`, `mark: {name}` |
| `clear` | barge-in | `streamSid` |

### 6.4 Signature validation

Twilio signs each request to our webhook with HMAC-SHA1 over
`URL + sorted(k+v) for k,v in POST params`, key = AuthToken,
result base64 encoded, placed in `X-Twilio-Signature`.

For a WS upgrade, the signature is over the URL (no POST params).
The constant-time compare is mandatory; the bytes are short, but the
auth token is the secret and timing leaks are real.

### 6.5 Hangup REST call

```http
POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Calls/{CallSid}.json
Authorization: Basic ...
Content-Type: application/x-www-form-urlencoded

Status=completed
```

Used by the `end_call` tool. The Media Streams WS will receive a
`stop` event shortly after.

---

## 7. OpenAI Realtime integration

### 7.1 Connection

```
WSS wss://api.openai.com/v1/realtime?model=gpt-realtime
Header  Authorization: Bearer ${OPENAI_API_KEY}
Header  OpenAI-Beta: realtime=v1     # only if needed by model version
```

### 7.2 session.update payload

```json
{
  "type": "session.update",
  "session": {
    "type": "realtime",
    "model": "gpt-realtime",
    "voice": "alloy",
    "instructions": "<phone preamble> + <base brain prompt>",
    "input_audio_format":  "pcm16",
    "output_audio_format": "pcm16",
    "input_audio_transcription": {"model": "gpt-4o-transcribe"},
    "turn_detection": {
      "type": "server_vad",
      "threshold": 0.5,
      "prefix_padding_ms": 300,
      "silence_duration_ms": 700
    },
    "tools": [<tool schemas: walk, gesture, stop, describe_scene, end_call>]
  }
}
```

We deliberately keep `input_audio_format=pcm16` (not `g711_ulaw`) so
all OpenAI-side computations stay in the high-quality domain; the
Twilio-side μ-law lives only on the bridge ↔ Twilio edge.

### 7.3 Events we handle

Inherited from parent (BrainRealtimeAgent already handles these):

- `session.created`, `session.updated`, `rate_limits.updated` — log only.
- `input_audio_buffer.speech_started` → trigger barge-in handling.
- `input_audio_buffer.committed` / `.speech_stopped` — log only.
- `conversation.item.input_audio_transcription.completed` → user
  transcript hook → conversation logger.
- `response.created` → mark plan-in-flight.
- `response.output_audio.delta` → pipe PCM24k into outbound resampler →
  Twilio.
- `response.output_audio.done` → optionally send a `mark` to Twilio.
- `response.output_audio_transcript.delta` / `.done` → assistant
  transcript hook.
- `response.function_call_arguments.done` → tool dispatch.
- `response.done` → if no pending function-call outputs, plan complete.
- `error` → log + reason; cancel the call gracefully.

Added by `PhoneRealtimeSession`:

- (none — we override behaviour, not events)

### 7.4 Tool result protocol

```json
// after we execute the tool client-side:
{
  "type": "conversation.item.create",
  "item": {
    "type": "function_call_output",
    "call_id": "call_abc123",
    "output": "{\"ok\":true,\"summary\":\"waved right hand for 1.2s\"}"
  }
}
{ "type": "response.create" }   // tells model to speak the result
```

We always serialize the tool result as a JSON string (per the Realtime
spec). The model reads it, decides whether to speak or call another
tool, and either way produces a new `response.created` →
`response.output_audio.delta` → ... cycle.

### 7.5 Tool call timeout

Each `SkillServer.execute()` call is wrapped:

```python
try:
    result = await asyncio.wait_for(
        self.skill_server.execute(name, args),
        timeout=self.phone_cfg.tool_timeout_s,
    )
except asyncio.TimeoutError:
    result = {"ok": False, "reason": f"tool {name} timed out after {timeout}s"}
```

The model receives the timeout reason and can either retry, escalate,
or speak the failure to the operator.

---

## 8. Tool surface

### 8.1 Phone-session toolset

| Tool | Source | Notes |
|---|---|---|
| `walk(vx, vy, wz, duration_s)` | existing | Capped by `safety.walk.*` |
| `gesture(name)` | existing | wave_*, bow, punch_combo, etc. |
| `stop()` | existing | Zero walk velocity, abort gesture |
| `describe_scene()` | existing | Head-cam JPEG → GPT-5.5 → text |
| `end_call()` | NEW (phone-only) | Calls `dialer.hangup(call_sid)` |
| `say(...)` | NOT exposed | Realtime speaks directly |
| `start_phone_call(...)` | NOT exposed | Would recurse |

### 8.2 Local va-demo toolset

The existing toolset plus exactly one new entry:

| Tool | Notes |
|---|---|
| ... existing skills ... | unchanged |
| `start_phone_call(to)` | NEW; dials, acquires PHONE lease, local mic loop quietly steps aside |

### 8.3 Tool schema imports

`phone/realtime_session.py` does NOT redefine tool schemas — it
imports from `g1_brain/skills/tool_schemas.py`, filters
`start_phone_call` out, appends `END_CALL_SCHEMA`. This guarantees the
model behaves identically across phone and local paths for shared
tools.

---

## 9. Safety architecture

### 9.1 Layered defence

```
Layer 0 — Transport: TLS at proxy (terminates Twilio's WSS)
Layer 1 — Twilio signature: HMAC-SHA1 verified at bridge accept
Layer 2 — Caller-ID whitelist: From-number must be in PHONE_ALLOWED_CALLERS
Layer 3 — Voice lease: only one Realtime session controls the robot at a time
Layer 4 — Run mode: phone session forces run_mode=active for its duration
Layer 5 — SafetySupervisor.check(): pose, watchdog, scene, walk caps, E-stop
Layer 6 — vision_risk_gate.review(): GPT-5.5 vision pre-flight on motion
Layer 7 — Skill server: defensive defaults inside each skill
Layer 8 — DDS / ComboController: enforces final torque/velocity limits
Layer 9 — MuJoCo / hardware: physical limits
```

Layers 5–8 are unchanged from the local-mic path. We add nothing
new in robot safety code — the phone path is just another caller of
the same `SkillServer.execute()` API.

### 9.2 Threat model

| Threat | Mitigation |
|---|---|
| Attacker discovers public URL, opens WS | Layer 1 (Twilio signature) — they don't have the AuthToken |
| Attacker spoofs the From-number | Layer 2 + Twilio carrier checks; for personal demo, single-caller whitelist is sufficient |
| Operator says something dangerous ("punch the wall") | Layer 5 (scene check) + Layer 6 (vision gate) — gate rejects with reason |
| Compromised public host | Layer 1 still requires AuthToken; compromised host cannot fake Twilio signature; can DoS the bridge by rejecting our 502s, but cannot make the robot move |
| OpenAI Realtime hallucinates a tool call with wild args | Layer 5 caps walk vx/vy/wz/duration; vision gate rejects gestures in dangerous proximity |
| Local mic also active during call | Layer 3 (voice lease) — only one issuer |
| Twilio compromised | Out of scope; rotate creds, trust Twilio's incident response |
| OpenAI compromised | Out of scope; same |
| Operator's phone stolen | E-stop file + estop_listener key still works locally; long-term mitigation is to add a per-call passphrase (out of v1) |

### 9.3 E-stop during call

The existing `/tmp/g1_brain_estop` file + `estop_listener` (ESC key)
work unchanged. New behaviour: when E-stop trips mid-call, the
bridge:

1. Notices via `SafetySupervisor` reporting the E-stop reason on the
   next motion call.
2. Injects a Realtime message:
   `{"type":"conversation.item.create", "item":{"type":"message","role":"system",
     "content":[{"type":"text","text":"Emergency stop engaged — refuse all motion commands until cleared."}]}}`
   followed by `response.create` so the model audibly says
   "Emergency stop engaged" to the operator.
3. Continues rejecting motion until the file is removed.

### 9.4 Vision gate as y/N replacement

Local va-demo `confirm` mode prompts a y/N at the terminal for each
motion call. On a phone call, that terminal is unreachable. We force
`active` for the session (no terminal prompts) and rely on the
`vision_risk_gate` (GPT-5.5 reviews the head-cam JPEG plus the
proposed tool call) as the gate. If the gate returns `RISK`, the
motion is rejected, the reason is returned to the model, and the
model speaks the reason to the operator.

**Hard requirement**: `safety.vision_gate.enabled=true` in
`g1_brain.yaml`. Bridge boot-checks this; if false, bridge refuses to
start phone sessions and logs why. Fail-closed.

---

## 10. Concurrency model

### 10.1 VoiceLeaseManager

A single named mutex with exactly two possible holders: `LOCAL_MIC` or
`PHONE`. Default state: held by `LOCAL_MIC` (so a freshly started
va-demo can transmit immediately).

Backed by `/tmp/g1_brain_voice_lease` JSON file with `fcntl.flock`.
Cross-process because va-demo and g1_brain are separate processes.

```python
LeaseFile = {
  "holder": "LOCAL_MIC" | "PHONE",
  "owner":  "<process-tag>:<uuid>",
  "since":  <unix timestamp>
}
```

Operations:

- `acquire(name, owner)`: takes `LOCK_EX | LOCK_NB`; if file holder ==
  name, returns True (idempotent). If holder is the OTHER name and
  the lease is stale (>1 h since `since`), reclaims. Otherwise
  returns False.
- `release(name, owner)`: only the recorded owner can release;
  prevents accidental release by another process.
- `current_holder()`: reads the file under shared lock.
- `watch(callback)`: starts an asyncio task polling current_holder()
  at 5 Hz; calls `callback(new_holder)` on change.

### 10.2 va-demo coordination

The va-demo wake-word loop already polls scene_bus etc. at ~10 Hz.
Adding a `VoiceLeaseManager.current_holder()` check costs ~1 ms per
iteration. If the holder is `PHONE`, the loop:

1. Skips wake-word detection (no `Hi Sparky` interrupts the call).
2. Discards any in-flight utterance buffer.
3. Mutes its output to the local speaker (so the model's local
   responses don't bleed onto the phone in some pathological case).
4. Waits.

When the holder flips back to `LOCAL_MIC`, the loop resumes
identically to a fresh startup.

### 10.3 asyncio task tree inside the bridge

```
BridgeServer.run
└── aiohttp app server (one task)
    └── per WS connection:
        ws_handler (one task per call)
        ├── PhoneRealtimeSession.run (one task)
        │   ├── _read_from_twilio_loop  (Twilio → OpenAI)
        │   ├── _read_from_openai_loop  (OpenAI events)
        │   ├── _write_to_twilio_loop   (OpenAI audio → Twilio)
        │   └── _idle_watchdog          (auto end_call on silence)
        └── on close: defensive stop(), release lease
```

All four loops share the `aiohttp.WebSocketResponse` and the OpenAI
`ClientWebSocketResponse`. Cancellation cascades through the
`async with TaskGroup` pattern (Python 3.11+).

---

## 11. Call lifecycle state machine

```
       ┌─────────────────┐
       │ IDLE            │ ◄────────┐
       │ (no call)       │          │
       └────────┬────────┘          │
                │ dial requested    │
                ▼                   │
       ┌─────────────────┐          │
       │ DIALING         │          │
       │ (REST in flight)│          │
       └────────┬────────┘          │
                │ Twilio 200 / sid  │
                ▼                   │
       ┌─────────────────┐          │
       │ RINGING         │          │
       │ (waiting for WS │          │
       │  upgrade)       │          │
       └────────┬────────┘          │
                │ WS connected      │
                │ signature OK      │
                │ caller-id OK      │
                │ lease acquired    │
                ▼                   │
       ┌─────────────────┐          │
       │ GREETING        │          │
       │ (Realtime sends │          │
       │  hello msg)     │          │
       └────────┬────────┘          │
                │ first user audio  │
                ▼                   │
       ┌─────────────────┐          │
       │ ACTIVE          │          │
       │ (steady audio + │          │
       │  tool calls)    │          │
       └────────┬────────┘          │
                │ stop / end_call / │
                │ error / timeout   │
                ▼                   │
       ┌─────────────────┐          │
       │ CLEANUP         │          │
       │ - defensive stop│          │
       │ - close RT WS   │          │
       │ - release lease │          │
       └────────┬────────┘          │
                │                   │
                └───────────────────┘
```

Failure transitions: any state can move to CLEANUP on error/timeout.
Reentry from IDLE is gated by `VoiceLeaseManager.current_holder()`
being LOCAL_MIC (or no holder).

---

## 12. Configuration

### 12.1 Environment variables

| Var | Required | Example | Notes |
|---|---|---|---|
| `TWILIO_ACCOUNT_SID` | yes | `AC68df...` | |
| `TWILIO_AUTH_TOKEN` | yes | `2de0d6...` | Used for signature validation |
| `TWILIO_API_KEY_SID` | yes | `SK9e5a...` | Used for REST basic auth |
| `TWILIO_API_KEY_SECRET` | yes | `aHagqz...` | Same |
| `TWILIO_FROM_NUMBER` | yes | `+14232502873` | E.164 |
| `PUBLIC_BRIDGE_URL` | yes | `wss://sparky-bridge.example.com/twilio` | Filled in TwiML |
| `PHONE_ALLOWED_CALLERS` | yes | `+61411706848` | Comma-separated E.164 list |
| `OPENAI_API_KEY` | yes | `sk-...` | Already used by va-demo |

`.env` is gitignored. `.env.example` is committed with placeholders.

### 12.2 g1_brain.yaml additions

```yaml
phone:
  enabled: false              # set true OR pass --enable-phone on agent_main
  bind_host: "0.0.0.0"
  bind_port: 8787
  call_idle_timeout_s: 30     # auto end_call if caller silent
  tool_timeout_s: 5.0         # wrap SkillServer.execute
  realtime_model: "gpt-realtime"
  realtime_voice: "alloy"
  greeting: "Hi, this is Sparky. What would you like me to do?"
```

### 12.3 CLI flags

- `python -m g1_brain.apps.agent_main --enable-phone` — boots bridge.
- `python -m g1_brain.phone.call_me --to +61...` — one-shot dial.
- `python -m g1_brain.phone.call_me --dry-run` — credential check
  only, no call.

### 12.4 Boot-time fail-closed checks

`agent_main --enable-phone` boots only if ALL true:

1. `OPENAI_API_KEY` set.
2. All `TWILIO_*` env vars set and parseable.
3. `PUBLIC_BRIDGE_URL` parses as a `wss://` URL.
4. `PHONE_ALLOWED_CALLERS` non-empty.
5. `safety.vision_gate.enabled` is `true` in the yaml.
6. Bind port `:8787` not in use.

Any failure → log the specific reason → exit non-zero.

---

## 13. Error handling matrix

| Failure | Detection | Recovery |
|---|---|---|
| Twilio WS drops mid-call | aiohttp WS close event | `finally`: defensive `stop()`, close OpenAI WS, release lease |
| OpenAI Realtime WS drops | aiohttp WS close event | Inject `<Say>` "lost the AI", close Twilio WS, cleanup |
| Bridge crash | external (the process dies) | aiohttp app supervisor restarts; in-flight call dies; PSTN side hangs up on WS silence (~15 s); supervisor watchdog stops robot regardless |
| Public tunnel dies | curl /healthz fails externally | Twilio retries WS briefly, then ends call; nothing the bridge can do |
| Tool call hangs >5 s | `asyncio.wait_for` timeout | `{"ok":false,"reason":"timeout"}` → model speaks reason |
| Caller silent >30 s | bridge timer in `_idle_watchdog` | auto-`end_call`, cleanup |
| `OPENAI_API_KEY` missing at boot | env check in `load_from_env` | Refuse to boot bridge; `/healthz` returns 503 |
| Vision gate dependency down | `vision_risk_gate.review()` raises | Per existing fail-closed behaviour: reject motion → model speaks reason |
| Bad TwiML / wrong URL | Twilio call status → `failed` | StatusCallback (v2) surfaces it; v1: dial returns 200 then call never connects → CallSid present but no WS arrives within 60 s → log warning |
| Signature mismatch | `tunnel_health.validate_twilio_signature` | 403 close immediately |
| Caller not whitelisted | first `start` event check | Close WS with reason; log |
| Brain_session_id stale / unknown | first `start` event check | Close WS with reason; log |
| Lease contention | `VoiceLeaseManager.acquire` returns False | Inject "busy, try again" `<Say>`, close call |
| `End_call` while still mid-tool | tool task cancelled | `finally` defensive stop runs; lease released |
| Audio resampler underrun | (cannot happen — pure compute) | n/a |
| Audio resampler overrun (memory) | buffer cap on `StreamingResampler` | drop oldest frames (better than OOM); log warning |

---

## 14. Testing strategy

### 14.1 Unit tests (CI; no network, no Twilio, no robot)

All in `g1_brain/tests/phone/`. CI runs them with the same constraints
the existing CI already meets (`pytest -q tests/phone/`).

| Test | Pins |
|---|---|
| `test_audio_codec.py` | 1 kHz sine round-trip THD < -40 dB; frame lengths 160 B in → 1920 B out (and inverse); `StreamingResampler` emits whole frames + retains residual |
| `test_twilio_dialer.py` | mocked `aiohttp` POST; URL, Basic auth header, TwiML body shape, `<Parameter>` embedded; raises on 4xx; `dry_run` calls correct GET |
| `test_twilio_transport.py` | fake aiohttp WS replay of `connected/start/media×N/stop` → `iter_inbound_pcm24k` yields N decoded chunks; `send_outbound_pcm24k(big_chunk)` emits N `media` events of 160 B each; `close()` is idempotent |
| `test_signature_verify.py` | Known vectors from Twilio docs HMAC matches; tampered URL or single param flipped → reject |
| `test_bridge_session.py` | full happy path against fake transport + fake `SkillServer`; injected `function_call_arguments.done` for `gesture(wave_right)` → `skill_server.execute` called with right args → `function_call_output` event sent back |
| `test_voice_lease.py` | two threads (simulating two processes via temp lease file + fcntl): only one acquires; release re-enables; stale lease (mtime > 1 h) reclaimable; bad owner cannot release |
| `test_safety_passthrough.py` | feed `walk(vx=1.5)` tool call; assert `SafetySupervisor.check` rejects, rejection text propagates into `function_call_output`'s output JSON |
| `test_phone_session_run_mode.py` | session start records prior `run_mode`, sets `active`, restores on close even on exception |
| `test_estop_during_call.py` | touch `/tmp/g1_brain_estop` mid-test; next motion tool call rejected with E-stop reason text |

### 14.2 Manual integration tests (no Twilio, no robot)

These cost nothing and catch wiring bugs before the live E2E:

- `make integration-phone-fake`: starts the bridge against an aiohttp
  echo-server that pretends to be Twilio. A test client connects with
  pre-recorded μ-law audio of "wave your right hand", asserts the
  bridge produces a tool call.
- `make integration-phone-rt`: same but talks to a real OpenAI
  Realtime session. Requires `OPENAI_API_KEY`. Asserts the tool call
  comes through (without needing actual robot or Twilio).

### 14.3 Live E2E (the done gate)

See §15.

---

## 15. Live E2E verification protocol

The six steps from §2.3, with explicit evidence-capture per step.
All evidence goes to `/tmp/twilio_bridge_verify_<YYYY-MM-DD-HHMM>.log`,
with each step's start and end stamped.

### Step 1 — tunnel reachable

```bash
curl -i https://${HOST}/healthz
# Expect:
#   HTTP/2 200 (if backend already up)
#   OR HTTP/2 502 (proxy fine, backend down)
# Must NOT be:
#   - DNS failure
#   - TLS error (cert invalid)
#   - 404 (proxy misconfigured)
```

Run from a network OTHER than the WSL2 laptop's network (phone
hotspot is fine). Log the full curl response.

### Step 2 — Twilio creds valid

```bash
python -m g1_brain.phone.call_me --dry-run
# Expect:
#   "Twilio credentials valid; account: <FriendlyName>"
```

If this fails, fix env vars before continuing.

### Step 3 — system up

Three terminals:

```bash
# T1 — sim
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# in viewer: press 7 (set down), 9 (release elastic band)

# T2 — estop
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener

# T3 — brain + bridge
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --enable-phone --mode active
# Wait for log line: "phone bridge listening on 0.0.0.0:8787"
```

Verify in T3:
- combo policy active
- bridge listening
- `safety.vision_gate.enabled` true (otherwise bridge would refuse)

### Step 4 — outbound dial

```bash
# T4 (one-shot)
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.phone.call_me
# Expect: "call placed; CallSid=CA..."
# Phone should ring within ~5 s.
```

If phone does not ring within 15 s → investigate before proceeding:

- Check Twilio console call log: is the call status `failed`? Check
  reason (geo permission, From-number not bought, etc.).
- Check `/healthz` again — backend reachable?
- Check `agent_main` log — did the WS attempt come and fail?

### Step 5 — audio bridge healthy

Pick up the phone. Hear the greeting. Say:
*"Say hello to me in French."*

Expected:
- Audible reply in French within ~2 s.
- No audible artifacts (clicks, gaps, robotic distortion).
- No echo/feedback.

Latency measurement: from the **end** of your speech to the **start**
of the reply audio. Aim ≤ 2 s. Log the measurement.

### Step 6 — robot moves on phone command

Say: **"Wave your right hand."**

Expected sequence (watch T3 log + MuJoCo viewer simultaneously):

1. T3 log: `tool: gesture(name="wave_right")`.
2. T3 log: `safety.check: pass`.
3. T3 log: `vision_gate.review: SAFE`.
4. T3 log: `DDS dispatched`.
5. MuJoCo viewer: G1 visibly waves right hand for ~1 s.
6. Phone audio: *"Done."* or similar.

Then say: *"Stop and goodbye."*

Expected:
1. T3 log: `tool: end_call`.
2. T3 log: `Twilio REST hangup CA... status=completed`.
3. Phone shows call ended.
4. T3 log: `voice lease released`.
5. If va-demo was running, it resumes.

Capture a MuJoCo screenshot at the moment G1 is mid-wave. Save to
`/tmp/twilio_bridge_verify_<date>_step6.png`. The screenshot is the
canonical evidence of step 6.

### Step 7 — nice-to-have (voice trigger)

Only after step 6 has passed cleanly:

```bash
# T5 — local va-demo
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a
python -m va_demo.main --mode active
```

Say to laptop mic: **"Hi Sparky, call me."**

Expected: wake-word triggers → local Realtime calls
`start_phone_call` → phone rings → continue as steps 5–6.

### What "done" claims I will NOT make

- "Latency is good on your network" unless I measured it in step 5.
- "Multi-call works" — we test with 1.
- "Cellular handoff is graceful" — we test on a stable connection.
- "Real robot is verified" — sim only in v1.

---

## 16. Deployment topology

### 16.1 The single host

WSL2 laptop runs everything that matters:

- MuJoCo sim (one process)
- g1_brain process (with `--enable-phone`)
- optionally: estop listener
- optionally: va-demo (separate process if you also want local mic)

All in `agi` conda env. No new system packages required beyond
what's already in `requirements.txt`; we'll add `twilio` and `aiohttp`
(if not already present) and `scipy` (if not already present).

### 16.2 The public host

Provisioned by the VPS-side agent per `TWILIO_BRIDGE_PUBLIC_ENDPOINT.md`.
The bridge does not care which solution is picked — it only needs
the resulting `wss://<host>/twilio` to forward correctly.

Hand-off file the VPS agent must produce:

- `PUBLIC_BRIDGE_URL` — exact `wss://<host>/twilio`
- `HEALTH_URL`       — `https://<host>/healthz`
- What WSL2 must run to bring up the tunnel side
- Restart-after-reboot mechanism
- Where to look on failure

### 16.3 Network paths

Outbound (REST dial-out, OpenAI WS): WSL2 → internet directly.
Standard egress, no inbound holes punched on the laptop.

Inbound (Twilio Media Streams WS): Twilio → public host (DNS resolves)
→ tunnel/proxy → WSL2's `127.0.0.1:8787`. The laptop never accepts
direct internet traffic.

---

## 17. Public endpoint provisioning (VPS-agent contract)

See `TWILIO_BRIDGE_PUBLIC_ENDPOINT.md` (provisioned by the VPS-side
agent based on the prompt below). The bridge code's only dependency
on the public host is the `PUBLIC_BRIDGE_URL` env var.

For reference, the prompt handed to the VPS agent specifies:

- Two routes: `/healthz` (GET) and `/twilio` (GET + WS Upgrade).
- TLS valid cert required (Let's Encrypt or Cloudflare).
- WS Upgrade headers passed verbatim; idle timeout ≥ 600 s; no path
  rewriting (Twilio HMAC validates over the URL).
- No auth at the proxy layer.
- Two acceptable solutions: Cloudflare named tunnel (preferred) or
  nginx + reverse SSH tunnel.

Verification by the VPS agent before hand-off:

```bash
curl -i https://${HOST}/healthz             # 200 or 502, never DNS/TLS/404
curl -i -N -H "Connection: Upgrade" \
        -H "Upgrade: websocket" \
        -H "Sec-WebSocket-Version: 13" \
        -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
        https://${HOST}/twilio              # 101 or 502, not 200/400/404
# Reboot proxy host; re-run step 1; endpoint must auto-recover.
```

---

## 18. Operational runbook

### 18.1 First-time setup (after VPS agent returns)

```bash
cd ~/unitree/unitree-notes/g1_brain
# 1. Drop the values into .env (gitignored)
echo "TWILIO_ACCOUNT_SID=AC68df..." >> .env
echo "TWILIO_AUTH_TOKEN=..." >> .env
echo "TWILIO_API_KEY_SID=SK9e5a..." >> .env
echo "TWILIO_API_KEY_SECRET=..." >> .env
echo "TWILIO_FROM_NUMBER=+14232502873" >> .env
echo "PUBLIC_BRIDGE_URL=wss://<vps-supplied-host>/twilio" >> .env
echo "PHONE_ALLOWED_CALLERS=+61411706848" >> .env

# 2. Cred check
set -a; source .env; set +a
python -m g1_brain.phone.call_me --dry-run

# 3. Bring up tunnel side per TWILIO_BRIDGE_PUBLIC_ENDPOINT.md
#    (cloudflared run / autossh wrapper / whatever the agent chose)

# 4. /healthz sanity
curl -i https://<host>/healthz
```

### 18.2 Each-time-you-demo runbook

Terminals 1–3 (sim, estop, brain) as in §15 step 3.

Then either:

```bash
# T4 — CLI dial
python -m g1_brain.phone.call_me
```

OR:

```bash
# T5 — local va-demo and speak "Hi Sparky, call me"
python -m va_demo.main --mode active
```

### 18.3 Monitoring during a call

Tail T3 log; key lines to look for:

- `twilio.signature: valid`
- `twilio.caller: +61411706848 whitelisted`
- `lease: acquired PHONE owner=call-<uuid>`
- `openai.session.updated`
- `tool: gesture(name=wave_right)`
- `skill.execute: ok summary="..."`
- `tool_result sent; response.create`
- `twilio.stop received`
- `lease: released`

### 18.4 Common failures

| Symptom | First check |
|---|---|
| Phone doesn't ring | Twilio console → calls → status / error |
| Rings but immediately hangs up | T3 log → signature / caller-id / lease errors |
| Connected but silent both ways | resampler errors / OpenAI WS connection failed |
| Voice OK but no tool call | model not seeing tool schemas? log session.update payload |
| Tool call but robot doesn't move | safety supervisor reason / vision_gate RISK |
| Robot moves but voice says nothing | response.create not sent → check `_execute_tool` return |

### 18.5 Credential rotation

Twilio console → API keys → revoke + create new SID/Secret. Update
`.env`. Restart `agent_main`. No code changes required.

For `TWILIO_AUTH_TOKEN` rotation: same — but every active call would
need to be re-established because in-flight signature validation
would start failing on the next request.

---

## 19. Future work / out of scope (v1)

- **Inbound calls**: add `/twiml/inbound` route returning the same
  `<Connect><Stream>` TwiML; configure Twilio number's Voice URL to
  point at it. Caller-id whitelist still applies.
- **Recording**: Twilio `<Record>` or media-stream side capture. Today,
  the memory daemon already logs Realtime turns; phone turns flow
  through the same code path because they share the brain.
- **DTMF**: Twilio sends `dtmf` events on the media stream when the
  caller presses a key — easy add for "press 0 to E-stop".
- **Multi-call**: two operators simultaneously. Today the
  VoiceLeaseManager allows only one PHONE holder; we'd extend to N
  with explicit per-call ownership.
- **Real robot**: same `SkillServer` API; flip `mode: real` in
  `g1_brain.yaml` after testing.
- **Twilio MCP**: register the Twilio MCP server as a tool for the
  local Realtime so the model itself can initiate SMS, conference,
  etc. — Twilio MCP is then *additional capability*, not infrastructure.
- **Geographic failover**: today, `PUBLIC_BRIDGE_URL` is a single
  hostname; could be a Cloudflare load-balancer in front of two
  named tunnels for resilience.

---

## 20. Decisions log

| Decision | Considered | Chosen | Why |
|---|---|---|---|
| Where bridge runs | (a) WSL2 alongside brain (b) public server with reverse channel | (a) | In-process tool dispatch preserves existing safety guarantees; no extra IPC layer to harden |
| Public host shape | (a) cloudflared (b) nginx+autossh (c) tailscale exit node | delegated to VPS agent | Bridge doesn't care; agent picks best fit for VPS at hand |
| MCP server vs REST | Twilio MCP server / direct Twilio REST | direct REST | One REST call to dial; MCP adds a moving part for no v1 benefit. MCP earns its keep when the *model* needs to dial mid-conversation |
| Code home | (a) new `g1_brain/phone/` (b) extend va-demo (c) standalone microservice | (a) | Smallest blast radius; va-demo stays a local-mic loop; standalone forces re-implementing safety boundary |
| `PhoneRealtimeSession` shape | (a) fresh class (b) subclass BrainRealtimeAgent | (b) | Parent already wires tools+safety; we override 3 methods, no duplication |
| Audio format on OpenAI side | (a) pcm16 (b) g711_ulaw | (a) | Keep model in high-quality domain; μ-law lives only on Twilio edge |
| Resampling library | (a) scipy.signal.resample_poly (b) librosa (c) sox bindings | (a) | Already in deps, integer ratios, fast |
| Turn detection | (a) server VAD (b) push-to-talk (c) client VAD | (a) | Phone calls expect natural turn-taking; server VAD handles barge-in |
| Run mode during phone | (a) confirm (b) active (c) observe | (b) | Can't reach a terminal y/N on a phone; vision gate replaces it |
| Caller auth | (a) None (b) Caller-id whitelist (c) PIN/passphrase | (b) | Single-personal-phone demo; PIN noise outweighs value for v1 |
| Cross-process lease backing | (a) file+fcntl (b) socket service (c) redis | (a) | Zero new processes / deps; simplest correct |
| Tool surface size | as large as local va-demo / minimal | minimal-plus-end_call | YAGNI; expand later if operator hits limits |
| Codec on Twilio leg | (a) μ-law/8k default (b) L16/16k | (a) | Universally supported; quality is fine for voice |
| When to start bridge | (a) always (b) `--enable-phone` flag | (b) | Don't open a port unless explicitly requested; safer default |
| End-call origin | (a) operator hangup only (b) `end_call` tool (c) both | (c) | Operator hangup is unavoidable; model `end_call` enables polite "goodbye" |
| Idle timeout | none / 30 s / 60 s | 30 s | Bounds runaway minutes if WS dies silently |

---

## 21. Appendices

### A. OpenAI Realtime event payload reference (subset we use)

```jsonc
// Sent by us
{ "type": "session.update", "session": {...} }
{ "type": "input_audio_buffer.append", "audio": "<b64 pcm16-24k>" }
{ "type": "input_audio_buffer.clear" }
{ "type": "response.cancel" }
{ "type": "conversation.item.create",
  "item": { "type": "function_call_output",
            "call_id": "...", "output": "{\"ok\":true,...}" } }
{ "type": "response.create" }

// Received by us
{ "type": "session.created", "session": {...} }
{ "type": "session.updated", "session": {...} }
{ "type": "input_audio_buffer.speech_started" }
{ "type": "input_audio_buffer.speech_stopped" }
{ "type": "input_audio_buffer.committed", "item_id": "..." }
{ "type": "conversation.item.input_audio_transcription.completed",
  "item_id": "...", "transcript": "..." }
{ "type": "response.created", "response": {"id": "..."} }
{ "type": "response.output_audio.delta", "response_id": "...",
  "item_id": "...", "delta": "<b64 pcm16-24k>" }
{ "type": "response.output_audio.done", "response_id": "..." }
{ "type": "response.output_audio_transcript.delta",
  "response_id": "...", "delta": "..." }
{ "type": "response.output_audio_transcript.done", "transcript": "..." }
{ "type": "response.function_call_arguments.done",
  "call_id": "...", "name": "...", "arguments": "{...}" }
{ "type": "response.done", "response": {"id": "...", "output": [...]} }
{ "type": "rate_limits.updated", "rate_limits": [...] }
{ "type": "error", "error": {"type":"...", "message":"..."} }
```

### B. Twilio Media Streams sample payloads

```jsonc
// Twilio → us
{ "event": "connected", "protocol": "Call", "version": "1.0.0" }

{ "event": "start",
  "sequenceNumber": "1",
  "start": {
    "streamSid": "MZ...",
    "accountSid": "AC...",
    "callSid": "CA...",
    "tracks": ["inbound"],
    "mediaFormat": {
      "encoding": "audio/x-mulaw",
      "sampleRate": 8000,
      "channels": 1
    },
    "customParameters": {
      "brain_session_id": "<uuid>"
    }
  },
  "streamSid": "MZ..." }

{ "event": "media",
  "sequenceNumber": "2",
  "media": {
    "track": "inbound",
    "chunk": "1",
    "timestamp": "5",
    "payload": "<base64 160 bytes mulaw>"
  },
  "streamSid": "MZ..." }

{ "event": "stop",
  "sequenceNumber": "199",
  "stop": { "accountSid": "AC...", "callSid": "CA..." },
  "streamSid": "MZ..." }

// us → Twilio
{ "event": "media",
  "streamSid": "MZ...",
  "media": { "payload": "<base64 160 bytes mulaw>" } }

{ "event": "mark",
  "streamSid": "MZ...",
  "mark": { "name": "greeting-done" } }

{ "event": "clear",
  "streamSid": "MZ..." }
```

### C. Sample TwiML emitted by twilio_dialer

```xml
<Response>
  <Connect>
    <Stream url="wss://sparky-bridge.example.com/twilio">
      <Parameter name="brain_session_id" value="3a2c4e91-..."/>
    </Stream>
  </Connect>
</Response>
```

### D. Sample tool-call cycle (from logs)

```
[14:02:13] twilio.ws.start streamSid=MZ... callSid=CA... bsid=3a2c4e91
[14:02:13] caller +61411706848 whitelisted
[14:02:13] lease.acquire PHONE owner=call-3a2c
[14:02:13] openai.ws connected
[14:02:13] openai.session.updated
[14:02:14] openai.response.created id=resp_aa
[14:02:14] openai.audio.delta 12kB → resampler → twilio.media (62×160B)
[14:02:14] twilio.media sent
[14:02:14] openai.response.done id=resp_aa (no tool calls)
[14:02:17] openai.input.speech_started
[14:02:18] openai.input.speech_stopped
[14:02:18] openai.transcript.user: "wave your right hand"
[14:02:18] openai.response.created id=resp_bb
[14:02:18] openai.function_call_args.done call_xyz gesture {"name":"wave_right"}
[14:02:18] skill.execute gesture(wave_right)
[14:02:18] safety.check pass
[14:02:18] vision_gate.review SAFE (latency 320ms)
[14:02:18] dds.dispatched
[14:02:19] skill.execute → {"ok":true,"summary":"waved right hand 1.2s"}
[14:02:19] openai.function_call_output sent + response.create
[14:02:20] openai.audio.delta 8kB → twilio.media
[14:02:20] openai.response.done id=resp_bb
[14:02:21] openai.transcript.assistant: "Done."
[14:02:25] openai.input.speech_started
[14:02:26] openai.transcript.user: "goodbye"
[14:02:26] openai.function_call_args.done call_xy2 end_call {}
[14:02:26] tool: end_call
[14:02:26] twilio.rest.hangup CA... → 200
[14:02:26] twilio.stop received
[14:02:26] defensive skill.execute stop()
[14:02:26] openai.ws closed
[14:02:26] lease.release PHONE owner=call-3a2c
```

### E. Glossary

| Term | Meaning |
|---|---|
| **Bridge** | The new process logic in `g1_brain/phone/` that wires Twilio audio to OpenAI Realtime and dispatches tool calls to the existing SkillServer |
| **BrainRealtimeAgent** | Existing class in `g1_brain/brain/realtime_agent.py`; subclasses va-demo's `RealtimeAgent`; the **phone** path adds a third sibling class `PhoneRealtimeSession` |
| **CallSid** | Twilio's identifier for an outbound (or inbound) phone call; format `CA<32 hex>` |
| **DDS** | Data Distribution Service; cyclonedds is what `g1_brain/skills/skill_server.py` uses to actuate the robot |
| **E.164** | International phone-number format: leading `+`, country code, subscriber number (e.g. `+61411706848`) |
| **G.711 μ-law** | The classic 8 kHz / 8-bit-companded voice codec; Twilio Media Streams default |
| **MCP** | Model Context Protocol; Twilio MCP server exposes Twilio's REST API as tools usable by an LLM agent |
| **Media Streams** | Twilio's WebSocket interface that ships call audio bidirectionally as base64-encoded μ-law frames |
| **PCM16** | 16-bit linear PCM, little-endian, mono; OpenAI Realtime's preferred format |
| **PhoneRealtimeSession** | New subclass of `BrainRealtimeAgent` with audio source/sink + prompt + toolset adapted for a phone call |
| **PSTN** | Public Switched Telephone Network; what your phone connects to before Twilio takes over |
| **streamSid** | Twilio's identifier for a Media Streams session; format `MZ<32 hex>` |
| **TwiML** | Twilio's XML schema for telling Twilio how to handle a call; we return `<Connect><Stream>` |
| **vision_risk_gate** | Existing `g1_brain/safety/vision_risk_gate.py`; GPT-5.5 reviews a head-cam JPEG before each motion call and returns SAFE/RISK |
| **VoiceLeaseManager** | New cross-process mutex enforcing single-owner (LOCAL_MIC or PHONE) over the robot |
