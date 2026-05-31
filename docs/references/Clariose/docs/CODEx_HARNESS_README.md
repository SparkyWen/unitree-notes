# CareNote Codex-Only Harness — README

This is the operator-facing README for the CareNote Codex-only multi-agent
harness. The full design lives under `docs/design/00..08.md`. This file
covers the practical "how do I run it" surface.

CareNote is a doctor-visit memory assistant. It is **not** a diagnosis
engine. Read `docs/design/05_medical_safety_and_privacy.md` before you
ship anything to a real user.

---

## 1. Where the code lives

```
prompts/
  codex-agents/                      # 11 role prompts (English, Markdown)
  codex-agents/_json_repair.md       # repair-pass prompt
config/
  codex-teams/
    carenote-doctor-visit.team.json  # team manifest (versioned)
.codex/
  agents/carenote_*.toml             # per-role custom-agent configs
docs/
  design/00..08.md                   # design docs
  CODEx_HARNESS_README.md            # this file
backend/src/modules/carenote/
  realtime/                          # transcript ingest + assembler + bus
  codex-harness/                     # CodexRuntime, registry, team, queue, manager
  medical/                           # schemas, reducers, visit state, memory
  prompts/                           # session + transcription prompt strings
  api/                               # CLIs and harness assembly
  fixtures/                          # transcript fixtures used by mock-turn
backend/test/carenote/               # Jest specs
.data/carenote/                      # runtime state mirror (gitignored)
```

---

## 2. Install dependencies

The harness is part of the existing Clariose NestJS backend. From the repo
root:

```bash
cd backend
npm install
# Optional: install Jest for tests if not already present.
npm install --save-dev jest ts-jest @types/jest
# Optional: install the Codex SDK if you intend to use the codex-sdk runtime.
npm install --save @openai/codex-sdk
# Optional: install the Codex CLI so the SDK has a binary to spawn.
# Follow the openai/codex install instructions for your OS.
```

---

## 3. Authenticate Codex with the ChatGPT subscription (preferred)

```bash
codex login --device-auth
```

This writes `~/.codex/auth.json`. The harness picks this up automatically
and prefers it over `OPENAI_API_KEY`.

If you must use API-key auth instead:

```bash
export OPENAI_API_KEY=sk-...
export CARENOTE_CODEX_ALLOW_API_KEY=1
```

The opt-in env var is required so a stray `OPENAI_API_KEY` does not
silently downgrade your auth mode.

---

## 4. Verify Codex runtime health

```bash
npm run carenote:codex:health
```

The output is a JSON blob like:

```json
{
  "runtime": "codex-sdk",
  "selection_reason": "auto-selected codex-sdk",
  "detected": {
    "has_sdk": true,
    "has_cli": true,
    "has_subscription": true,
    "has_api_key_opt_in": false
  },
  "runtime_health": { "ok": true, "runtime": "codex-sdk", "auth_mode": "chatgpt_subscription" },
  "manifest_ok": true
}
```

If `runtime` is `stub`, the harness will still run but every Codex call
returns deterministic fixtures. That mode is fine for development and
tests; do not run it for real users.

---

## 5. Bootstrap the agent team

```bash
npm run carenote:codex:bootstrap
```

This:

1. Reads `config/codex-teams/carenote-doctor-visit.team.json`.
2. Validates it against the Zod schema.
3. Writes (or updates) the team-state mirror at
   `.data/carenote/codex-agent-team-state.json`.
4. Prints the agent list and current thread state per role.

The command is idempotent. Running it twice is a no-op unless prompt
versions or schema versions changed in the manifest.

---

## 6. Run a mock transcript event

The mock-turn CLI feeds a fixture file (or a `--inline` string) through
the entire harness, then prints the resulting `VisitState`. By default
it uses whatever runtime `CodexRuntimeFactory` auto-selects (codex-sdk
or codex-cli when available and authenticated, stub otherwise). Pass
`--stub` (or set `CARENOTE_CODEX_RUNTIME=stub`) to force the
deterministic stub runtime — useful for offline/local snapshots.

```bash
# Use a fixture file (auto-selects the live runtime when available)
npm run carenote:codex:mock-turn -- backend/src/modules/carenote/fixtures/transcripts/fixture-1-missing-dose.json

# Or inline:
npm run carenote:codex:mock-turn -- --inline "我对青霉素过敏。"

# Force the stub runtime for deterministic local output:
npm run carenote:codex:mock-turn -- --stub backend/src/modules/carenote/fixtures/transcripts/fixture-1-missing-dose.json
# or:
CARENOTE_CODEX_RUNTIME=stub npm run carenote:codex:mock-turn -- backend/src/modules/carenote/fixtures/transcripts/fixture-1-missing-dose.json
```

You should see:

- a `medication_reminder` draft with `requires_user_confirmation: true`,
  `confirmation_status: "pending"`, and `blocking_missing_fields`
  including `medication_name` and `dose`;
- a `safety_flag` of type `missing_dose`;
- a `confirmation_task` asking the user to confirm the missing fields;
- (for the allergy fixture) a `memory_candidate` of type `allergy` with
  `requires_user_confirmation: true`.

---

## 7. Run a Realtime demo (M7 — wired)

M7 connects the OpenAI Realtime transcript pipeline end-to-end:

```
mic → OpenAI Realtime (WebRTC, browser)
    → /api/visits/:id/realtime-events  (NestJS)
    → TranscriptAssembler
    → TranscriptEventBus
    → CodexJobQueue
    → CodexRunManager (11 agent roles)
    → schema validation + ComplianceGuardrailReducer
    → VisitStateReducer
    → /api/visits/:id  (frontend polls)
```

### Backend endpoints (live)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/visits` | Create visit (consent gate) |
| GET | `/api/visits/:id` | Get full VisitState + meta + jobs |
| POST | `/api/realtime/session` | Mint a per-visit Realtime client_secret |
| POST | `/api/visits/:id/realtime-events` | Ingest one Realtime event |
| POST | `/api/visits/:id/stage-summary` | Enqueue mid-visit summary |
| POST | `/api/visits/:id/final-summary` | End visit + final summary |
| POST | `/api/visits/:id/draft-tasks/:taskId/confirm` | Promote draft → confirmed |
| POST | `/api/visits/:id/draft-tasks/:taskId/reject` | Drop draft |
| POST | `/api/visits/:id/memory-candidates/:candidateId/confirm` | Save to memory |
| POST | `/api/visits/:id/memory-candidates/:candidateId/reject` | Drop candidate |
| DELETE | `/api/visits/:id` | Wipe local visit state |

The Realtime session config locks in the M7 safety defaults:

- `output_modalities: ["text"]`
- `turn_detection.create_response: false` — AI never auto-responds
- `turn_detection.interrupt_response: false` — AI never interrupts
- `audio.input.transcription.model: gpt-4o-transcribe`
- `audio.input.transcription.language: zh` (default)
- `audio.input.noise_reduction.type: near_field`
- `include: ["item.input_audio_transcription.logprobs"]`

### Frontend (Nuxt)

Pages (`frontend/pages/carenote/`):

- `index.vue` — consent + language + start visit
- `visit/[id].vue` — live recording, transcript, draft cards, queue status
- `visit/[id]/summary.vue` — final summary, confirm/reject, family copy

Composables (`frontend/composables/`):

- `useCareNote.ts` — typed wrapper over the visit/realtime API
- `useRealtimeVisit.ts` — owns mic, WebRTC peer, data-channel events,
  forwards each event to `/api/visits/:id/realtime-events`

### Run it

```bash
# Backend
cd backend
npm install
npm run carenote:codex:health
npm run carenote:codex:bootstrap
npm run dev          # nest start --watch (port 4400)

# Frontend (separate terminal)
cd frontend
npm install
npm run dev          # nuxt dev (port 3300)

# Open the start screen
open http://localhost:3300/carenote
```

Then on the Start-Visit page, tick consent and pick a language; the page
will navigate to `/carenote/visit/<id>` where the mic engages on the
**Start recording** button.

---

## 8. Run tests

```bash
# All CareNote specs (fast, stub runtime, no Codex required)
npm run carenote:test

# With the live Codex runtime smoke check enabled
CARENOTE_E2E=1 npm run carenote:test
```

Tests live under `backend/test/carenote/`. Fixtures live under
`backend/src/modules/carenote/fixtures/`.

---

## 9. Inspect agent runs

For now the harness records agent runs in memory only. The
`recordAgentRun` callback in `CodexRunManagerOptions` is a hook for
durable persistence; wire it to a Postgres `agent_runs` table when M7
ships the API layer.

The mock-turn CLI prints the `VisitState`; the
`runs[]` array on the result of `manager.analyzeTurn(job)` carries
per-role `validation_status`, `errors`, `parsed_json`, `started_at`, and
`completed_at`.

---

## 10. Reset Codex team threads

To rotate every role's thread:

```ts
import { bootstrapCareNoteTeam } from "carenote/codex-harness/codexTeamBootstrap";
const { team, store, manifest } = await bootstrapCareNoteTeam({ repoRoot });
for (const a of manifest.agents) {
  await store.reset(manifest.team_id, a.role, "manual_reset");
}
```

A future API endpoint (`POST /api/codex-team/reset`) will expose this.

---

## 11. Add a new agent role

1. Add the prompt file: `prompts/codex-agents/<role>.md`.
2. Add the Zod schema and append the role to the
   `RoleOutputSchemas` map in
   `backend/src/modules/carenote/medical/medicalSchemas.ts`.
3. Add an entry to `agents[]` in
   `config/codex-teams/carenote-doctor-visit.team.json`. Set
   `prompt_version` and `schema_version` to `"1.0.0"`.
4. (Optional) Add `.codex/agents/carenote_<role>.toml`.
5. Re-run `npm run carenote:codex:bootstrap`.
6. Wire the new role into `CodexRunManager` if it should be invoked
   during the analyse-turn flow.

---

## 12. Known limitations

- The Codex SDK is published as `@openai/codex-sdk@0.0.0-dev` at the time
  of writing. Treat the dependency as unstable and pin once you find a
  version that works for you.
- `Thread.id` is populated only after the first `runStreamed()` event
  (specifically `thread.started`). Brand-new threads return `null` until
  that point.
- The CLI runtime cannot pre-allocate threads; thread IDs surface on
  the first run and we record them after the fact.
- The app-server runtime is not implemented in MVP. The factory will
  refuse to auto-select it.
- The harness does not yet write `agent_runs` to Postgres; this is
  scheduled for M8 alongside the Postgres migration.
- The browser polls `/api/visits/:id` every 1.5–2s. SSE/WebSocket
  push lands in M8/M9.
- Visit metadata, drafts, confirmed tasks, and memory entries live in
  process memory (`InMemoryVisitStateStore` + small per-visit maps in
  `CareNoteService`). Restarting the API loses all visit state. The
  service interface is shaped so swapping in a Postgres-backed store is
  a one-file change.
- Tests require Jest; if Jest is not installed in the backend, install
  it (`npm install --save-dev jest ts-jest @types/jest`) before running
  `npm run carenote:test`.

---

## 13. M7 manual smoke test

1. `cd backend && npm install`
2. `npm run carenote:codex:health` — verifies Codex auth + model.
3. `npm run carenote:codex:bootstrap` — primes the team manifest and
   per-role thread state under `.data/carenote/`.
4. `npm run dev` — backend on `127.0.0.1:4400`.
5. In a second terminal: `cd frontend && npm install && npm run dev`
   — Nuxt on `:3300`.
6. Open `http://localhost:3300/carenote`, tick consent, pick `zh`,
   click **Start visit**.
7. On the visit page, click **Start recording** and grant mic
   permission.
8. Speak the seed phrase: *"这个药每天饭后吃一次，连续吃三天。"*
9. Verify the partial transcript appears within ~1s and that a
   completed turn card lands shortly after.
10. Watch the Codex queue indicator (`pending · running`) tick up and
    back down. The "Draft medication reminders" panel should show a
    card flagged with `missing: dose`.
11. Click **End visit** — you land on the summary screen.
12. On the summary screen: confirm one draft task, reject another, save
    one memory candidate. The state updates within one poll cycle.
13. (Optional) Click **Delete visit data** to wipe the visit and confirm
    `/api/visits/:id` returns 404.

For a fully automated smoke run that doesn't need a microphone:

```bash
# Stub runtime — no Codex CLI required.
npm run carenote:codex:mock-turn -- backend/src/modules/carenote/fixtures/transcripts/fixture-1-missing-dose.json --stub

# Real Codex CLI runtime (recommended after the Codex auth step).
npm run carenote:codex:mock-turn -- backend/src/modules/carenote/fixtures/transcripts/fixture-1-missing-dose.json
```

---

## 14. Privacy & PHI redaction

`CareNoteService` runs every ingest event through `redactPhi()` before
log emission. Free-text fields (`transcript`, `delta`, `partial_transcript`,
`text`, `content`, `raw_text`, `logprobs`, `raw_events`) are replaced with
`[redacted:N]` markers; everything else (event type, item_id, visit_id,
timestamps) is preserved for debuggability.

Set `DEBUG_CARENOTE_PHI=true` to disable redaction during local
development. The service prints a one-time startup warning whenever this
is enabled. **Never** set this in production.

```bash
# safe (default)
npm run dev

# DO NOT use in production
DEBUG_CARENOTE_PHI=true npm run dev
```

`raw_audio_saved` defaults to `false` on the create-visit endpoint and
the harness has no audio storage path; the toggle is wired through the
visit metadata and is currently a UI-level promise enforced by the
absence of any audio sink in the data plane.

---

## 15. Safety checklist before shipping a real user

- [ ] `CARENOTE_CODEX_RUNTIME` is `codex-sdk` or `codex-cli`, never `stub`.
- [ ] `~/.codex/auth.json` exists OR `CARENOTE_CODEX_ALLOW_API_KEY=1`.
- [ ] `DEBUG_CARENOTE_PHI` is unset or `false`.
- [ ] The user has accepted consent on the Start-Visit screen.
- [ ] No reminder, calendar event, or memory entry is created without an
      explicit confirm-API call.
- [ ] All medication drafts carry `requires_user_confirmation: true`.
- [ ] All facts carry `source_turn_ids`.
- [ ] The compliance_guardrail role's output is enforced by the reducer.

---

## 16. Transcript visibility (M7.6)

### Where transcript turns live

Transcript turns are persisted in `VisitState.turns`. They are NOT
hidden inside any agent output. The reducer that mirrors Realtime
events into `VisitState` is
`backend/src/modules/carenote/realtime/applyRealtimeEvent.ts`. This
runs inside `CareNoteService.ingestRealtimeEvent` for every event the
browser forwards via `POST /api/visits/:id/realtime-events`.

Per-turn fields:

```
turns: [{
  item_id, previous_item_id, status,            // committed|partial|completed|failed
  partial_transcript, transcript,
  speaker_label,                                // null until speaker_role wires up
  ordering_confidence,                          // high|medium|low
  source_model: "gpt-realtime-1.5",
  transcription_model: "gpt-4o-transcribe",
  error,                                        // ASR failure message or null
  created_at, completed_at
}]
```

Per-visit aggregate counters live in `VisitState.transcript_stats` —
`committed_count`, `partial_count`, `delta_count`, `completed_count`,
`failed_count`, `last_event_type`, `last_completed_transcript`,
`last_completed_transcript_at`, `last_partial_transcript`,
`last_error`, `last_failed_at`.

### How to verify transcript events on a running session

```bash
# 1) Boot the backend with codex-cli runtime selected.
cd ~/Zai/backend && npm run dev

# 2) From the browser console at /carenote/visit/<id>, watch the
#    Realtime Transcript Debug strip on the page itself.

# 3) Or hit the API directly:
TOKEN=...   # get from /api/auth/login
curl -sH "Authorization: Bearer $TOKEN" \
  http://localhost:4400/api/visits/<id> | jq .state.transcript_stats
curl -sH "Authorization: Bearer $TOKEN" \
  http://localhost:4400/api/visits/<id> | jq '.state.turns[]'
```

### How to run the replay smoke

```bash
# stub runtime — fast, deterministic, no network:
npm run carenote:smoke:replay-transcript -- --stub --inline \
  "Please take this medicine once a day after meals for three days."

# real codex-cli runtime — runs the full M7.6 pipeline through
# transcript_verification → clarification_question →
# medication_schedule_draft → caregiver_notification →
# safety_guardrail:
npm run carenote:smoke:replay-transcript -- --inline \
  "Please take this medicine once a day after meals for three days."
```

The smoke prints a JSON summary that proves: one persisted turn, one
verification record, drafted (not active) reminders with
`requires_user_confirmation: true`, drafted caregiver notification,
and `analyzed_item_ids` populated for idempotency.

### How to read the Realtime Transcript Debug panel

The panel on `/carenote/visit/[id]` shows:

| Row                  | What it tells you                                              |
| -------------------- | -------------------------------------------------------------- |
| `data channel`       | WebRTC datachannel readyState. Stuck on `connecting` = SDP fail. |
| `last event`         | Last Realtime event type the browser received.                 |
| `committed/delta/completed/failed` | Browser-side counters. Should grow during recording. |
| `server completed`   | What the backend has persisted. Lag = ingest is slow.          |
| `ingest`             | Last `POST /realtime-events` status (`ok` / `error`).          |
| `duplicate`          | True if the last `completed` was a no-op (already analyzed).   |
| `last transcript`    | Most recent finalized turn text.                               |
| `transcription failed` | OpenAI ASR failure message (rare).                           |
| `openai error`       | Top-level Realtime error event body.                           |
| `server last_error`  | Mirrors `transcript_stats.last_error` from the backend.        |

If the browser counters move but `server completed` stays at 0, the
ingest endpoint is down. If both counters move but the transcript
list is still empty, the reducer is misconfigured — re-read
`applyRealtimeEvent.ts`.
