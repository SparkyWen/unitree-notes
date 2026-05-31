# 07 — MVP Implementation Plan

Date: 2026-04-29

## 1. Milestones

| ID | Milestone | Owner | Acceptance |
|---|---|---|---|
| M0 | Design docs land | this PR | `docs/design/00..08.md` exist |
| M1 | Codex harness scaffold | this PR | `npm run carenote:codex:health` returns ok with stub or real runtime |
| M2 | Persistent team manifest + thread store | this PR | `npm run carenote:codex:bootstrap` is idempotent |
| M3 | Realtime broker + transcript assembler + bus | this PR | mock-turn flows end-to-end |
| M4 | Agent prompt pack + schemas | this PR | every role has a prompt + schema + Zod validator |
| M5 | Mock transcript end-to-end | this PR | `npm run carenote:codex:mock-turn` produces a guardrail-checked envelope |
| M6 | Safety test fixtures | this PR | 10 fixtures pass with stub runtime |
| M7 | Realtime live demo wiring | follow-up | live `gpt-realtime-1.5` session works |
| M8 | Confirm / reject UI | follow-up | user can confirm a draft |
| M9 | Production hardening | follow-up | BullMQ + lint rule + multi-tenant |

The current PR delivers M0–M6.

## 2. Implementation order (this PR)

The order matters because each step unblocks the next:

1. **Schemas** (`medical/medicalSchemas.ts`).
2. **Agent prompts** (11 files under `prompts/codex-agents/`).
3. **Team manifest** (`config/codex-teams/...json`).
4. **Custom-agent TOMLs** (under `.codex/agents/`).
5. **Realtime types + transcript assembler + event bus**.
6. **CodexRuntime interface + factory + SDK runtime + CLI runtime +
   stub runtime**.
7. **CodexThreadStore (JSON mirror first; Postgres table is future)**.
8. **CodexAgentRegistry + CodexAgentTeam + CodexJobQueue +
   CodexRunManager**.
9. **CodexOutputParser + CodexSchemaValidator + CodexGuardrailReducer +
   VisitStateReducer**.
10. **Mock-turn CLI** (`npm run carenote:codex:mock-turn`).
11. **Tests** (10 fixtures).
12. **README + npm scripts**.
13. **API skeleton** (`backend/src/modules/carenote/api/*`) — stubs
    only; full wiring is M7+.

## 3. Tasks (granular)

### 3.1 Schemas (Zod)

File: `backend/src/modules/carenote/medical/medicalSchemas.ts`.
Schemas:

- `TranscriptTurn`
- `VisitState`
- `ExtractedFact`
- `MedicationInstructionNormalized`
- `DraftTask`
- `DraftMedicationReminder`
- `FollowUpTaskDraft`
- `ClarifyingQuestion`
- `FamilySummary`
- `MemoryCandidate`
- `SafetyFlag`
- `AgentRunRecord`
- `CodexAgentTeamManifest`
- `CodexAgentThreadState`

Per-role output schemas:

- `VisitOrchestratorOutput`
- `TranscriptQualityOutput`
- `SpeakerRoleOutput`
- `MedicalInstructionExtractorOutput`
- `MedicationReminderDraftOutput`
- `FollowUpTaskDraftOutput`
- `SafetyClarificationOutput`
- `FamilySummaryOutput`
- `MemoryUpdateOutput`
- `ComplianceGuardrailOutput`
- `FinalVisitSummaryOutput`

Each schema is a Zod schema and a derived JSON Schema (via
`zod-to-json-schema`) for `TurnOptions.outputSchema`.

### 3.2 Agent prompts

11 markdown files under `prompts/codex-agents/`.

### 3.3 Team manifest

`config/codex-teams/carenote-doctor-visit.team.json`. Validate at
startup with a Zod schema (`CodexAgentTeamManifest`).

### 3.4 Custom-agent TOMLs

`.codex/agents/carenote_*.toml`. We ship 11 files. They are not
load-bearing in MVP (the harness sends prompts directly), but they
document the intent and become load-bearing if Codex starts honouring
them.

### 3.5 Realtime types

`realtime/realtimeEventTypes.ts` — typed events for delta /
completed / committed.

### 3.6 TranscriptAssembler

`realtime/transcriptAssembler.ts`. Pure class. Given an event, returns
a (possibly empty) list of `DoctorVisitTranscriptTurnCompleted`
events to emit. Pure; no I/O.

### 3.7 TranscriptEventBus

`realtime/transcriptEventBus.ts`. Wraps an RxJS `Subject` plus a
`subscribe(visit_id, handler)` helper. Persists turns through a
`TranscriptStore` (in-memory map for MVP, swappable).

### 3.8 CodexRuntime

`codex-harness/codexRuntime.ts` — interface + types.
`codex-harness/codexSdkRuntime.ts` — uses `@openai/codex-sdk` if
available; falls back to a stub if not.
`codex-harness/codexCliRuntime.ts` — uses `child_process.spawn` to
call `codex exec --json --output-schema ...`.
`codex-harness/codexAppServerRuntime.ts` — placeholder; throws
`NotImplemented`.
`codex-harness/codexRuntimeFactory.ts` — chooses based on env + binary
detection.

### 3.9 CodexThreadStore

`codex-harness/codexThreadStore.ts`. Stores in
`.data/carenote/codex-agent-team-state.json` as MVP. Provides a
DB-shaped interface so we can move to Postgres later.

### 3.10 CodexAgentRegistry, Team, JobQueue, RunManager

Files in `codex-harness/`. RunManager owns the orchestration
described in Doc 03.

### 3.11 Output parser, validator, reducer

`codex-harness/codexOutputParser.ts`,
`codex-harness/codexSchemaValidator.ts`,
`codex-harness/codexGuardrailReducer.ts`,
`medical/medicalReducers.ts` (the `VisitStateReducer`).

### 3.12 Mock-turn CLI

`backend/src/modules/carenote/api/mock-turn.cli.ts`. Imports
`CodexRunManager` and `TranscriptEventBus`, accepts a JSON file with a
turn, emits the event, prints the resulting `VisitState` slice.

Wired as `npm run carenote:codex:mock-turn -- path/to/turn.json`.

### 3.13 Tests

`backend/test/carenote/*.spec.ts`. Use Jest (Clariose's existing test
framework). Use the stub runtime so tests don't depend on Codex
binaries.

### 3.14 README + scripts

`docs/CODEx_HARNESS_README.md`. Add scripts to `backend/package.json`:

- `carenote:codex:health`
- `carenote:codex:bootstrap`
- `carenote:codex:mock-turn`
- `carenote:realtime:dev` (placeholder; full wiring is M7)
- `carenote:test`

## 4. API endpoints (stubs in this PR)

Implemented as stubs that wire the harness to the schemas; full
controllers come in M7/M8.

```
POST   /api/visits
GET    /api/visits/:visitId
DELETE /api/visits/:visitId
POST   /api/realtime/session
POST   /api/visits/:visitId/realtime-events
POST   /api/visits/:visitId/stage-summary
POST   /api/visits/:visitId/final-summary
POST   /api/visits/:visitId/draft-tasks/:taskId/confirm
POST   /api/visits/:visitId/draft-tasks/:taskId/reject
POST   /api/visits/:visitId/memory-candidates/:candidateId/confirm
POST   /api/visits/:visitId/memory-candidates/:candidateId/reject

GET    /api/codex-team
POST   /api/codex-team/reload
POST   /api/codex-team/reset
GET    /api/codex-team/health
```

## 5. Acceptance criteria for this PR

1. `docs/design/00..08.md` and `docs/CODEx_HARNESS_README.md` exist.
2. The harness has zero imports of Claude SDK, Anthropic SDK, OpenAI
   Agents SDK, LangChain, LangGraph.
3. `CodexRuntime` interface and at least one runtime (stub is
   acceptable) are implemented.
4. The team manifest exists and is validated at startup.
5. `codex_agent_threads` JSON mirror is created on bootstrap.
6. The 11 prompt files exist.
7. The 11 schemas exist as Zod types.
8. The mock-turn CLI runs end-to-end with the stub runtime.
9. Tests pass (`npm run carenote:test`).
10. The reducer rejects an output with `requires_user_confirmation =
    false`, an output without `source_turn_ids`, and a memory write.

## 6. Out of scope (this PR)

- Live Realtime → harness wiring (frontend changes).
- Real Codex CLI installation (the SDK runtime falls back to stub if
  the binary isn't there).
- Postgres migrations for the new tables (we ship Zod schemas; the
  Prisma schema diff is M7).
- Family share / export endpoints.
- Memory page UI.
