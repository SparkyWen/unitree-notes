# Clariose v02 — Week 1–4 Implementation Record

> **Date**: 2026-04-30
> **Status**: All 4 weeks landed and deployed at `https://zai.gold`
> **Owner**: wenxuner@gmail.com
> **Companion**: `clariose-v01-0430.md` (the running design + decision log; this v02 is the post-implementation record)
> **Scope**: every file added or changed in the 2026-04-29 → 2026-04-30 work session

---

## 0. TL;DR

We rebuilt Clariose's voice consultation pipeline around the **carenote / codex-harness** subsystem and bolted on the four-layer multi-agent communication primitives the user proved on Claude in **Qagent**. The legacy `/consult` + `agents` + `sessions` line is fenced off (no more in-flight changes — slated for deletion when carenote UI parity lands).

**What's running in production now** (`pm2 list` shows `clariose-backend` + `clariose-frontend` online):

- All carenote endpoints behind JWT + per-visit ownership check.
- Visit metadata + VisitState persisted to Postgres (browser refresh + PM2 reload no longer wipe transcripts).
- Per-visit codex thread isolation (`(team, visit, role)` cache key — visit B can't see visit A's hidden chain-of-thought).
- 4-phase memory recall (scan → sideQuery → surface → inject) with `gpt-5.4-mini-2026-03-17`, 2.2 s timeout, 96 KB visit budget, 16 KB per-file cap.
- Dynamic prompt assembler emits structured `<visit_context>` / `<recent_transcript>` / `<inbox>` / `<blackboard>` / `<event>` / `<expected_output_schema_name>` blocks; each role gets the same recall result on the same turn.
- 9-typed mailbox (file `proper-lockfile` + DB mirror), versioned blackboard, on-demand subscriber triggers (cooldown 2 s, MAX_HOPS = 3), reducer→blackboard wiring so agent outputs really drive sibling re-runs.
- SSE stream `GET /api/visits/:id/events` with `?token=…` auth; nginx access_log suppressed on this path.
- Auto-dream daily cron at 03:00 — `gpt-4o-mini` via OpenAI Chat consolidates ENDED visits into per-user `users/<u>/{MEMORY.md, memory_summary.md, allergies.md, conditions.md, rollout_summaries/, skills/}`.
- 16 security findings closed (3 High / 4 Med / 5 Low), 2 acknowledged, 0 npm vulnerabilities.

**Test stat**: 19 carenote test suites, **88 / 88 passing**.

---

## 1. The three bugs that started all this

From the user's 2026-04-29 session on visit `cmok489p`:

1. **Browser refresh wipes transcript.** Local `useRealtime.utterances` ref was the only state; no `GET /sessions/:id/utterances`; `sessionId` not in `sessionStorage`.
2. **End & review → blank summary forever.** Family agent fired only on `n % 3 === 0` (fire-and-forget); navigation raced ahead; summary page did one-shot `useAsyncData` with no polling.
3. **No codex agent results in the UI.** The `/consult` page called `/api/sessions/:id/agents/run` → OpenAI Chat (`gpt-4o-mini`), **not codex**. The 60+ rollout files in `~/.codex/sessions/2026/04/29/` came from the parallel `carenote/codex-harness` subsystem (CLI smoke tests) the user wasn't using.

After v02:
1. ✅ Visit metadata + VisitState persisted to `consult_sessions`. Hydrate on cold start.
2. ✅ End & review races SSE `agent_run_completed{role:final_visit_summary}` against an 8 s safety timeout before navigating.
3. ✅ User uses `/carenote/visit/<cuid>`. The codex pipeline drives every panel; SSE pushes per-turn updates immediately.

---

## 2. Architectural decisions

| # | Decision | Why |
|---|---|---|
| D1 | Standardize on carenote/codex-harness; fence off legacy `/consult` line | User confirmed; codex pipeline already 90% there |
| D2 | `ConsultSession.visitState JSONB` (one column, whole-blob) instead of 12 child tables | We only ever read it as a whole; cheap migration |
| D3 | Mailbox = file source of truth + DB mirror | File enables proper-lockfile cross-process; DB enables SSE + UI queries |
| D4 | Codex thread cache key = `(team, visit, role)` not `(team, role)` | Per-visit isolation; user OK'd higher token cost |
| D5 | sideQuery model = `gpt-5.4-mini-2026-03-17` (env override) | User-specified |
| D6 | Memory folders use Codex naming convention (MEMORY.md, memory_summary.md, rollout_summaries/, skills/, read_path.md) | Per CDXLearn note 5 diagram |
| D7 | Memory mechanics use Qagent (scan → sideQuery → surface → inject), NOT Codex Phase 1/2 SQLite | Demo scale; auto-dream cron is sufficient |
| D8 | Auto-dream daily cron, not real-time | Visit ≤ 1 h; no need for stream consolidation |
| D9 | Inter-agent triggers are event-driven (bus → enqueue), not polling | Per CCLearn note 4 + user req |
| D10 | Dynamic prompt template, NOT static-cache-optimized | User cross-checked with OpenAI eng; SDK handles cache; clean contract preferred |
| D11 | Per-visit byte budget 96 KB (raised from Qagent's 64 KB) | "Best effect, don't worry about token usage" |
| D12 | `MAX_BYTES_PER_FILE` 16 KB (raised from Qagent's 8 KB) | Same reason |
| D13 | Cycle breaker: max 3 hops, 2 s cooldown per (visit, role) | Defense against on-demand trigger loops |
| D14 | Auto-dream uses OpenAI Chat (gpt-4o-mini), NOT a dedicated codex thread | Per-user-per-day codex thread is overkill; auth quota |
| D15 | Old `/consult` + `/sessions` + `/agents` modules **not deleted** in v02 | Wait until carenote UI is at parity, drop in one cleanup PR |

---

## 3. End-to-end pipeline (what happens on every turn)

```
browser  ←──── EventSource /api/visits/:id/events?token=… ────┐
   │                                                          │
   │ POST /api/realtime/sessions  (mints client_secret,        │
   │                               binds to visit; gpt-realtime)│
   │ ─── WebRTC SDP w/ OpenAI Realtime ─────                  │
   │                                                          │
   │ POST /api/visits/:id/realtime-events (each ws frame)      │
   ▼                                                          │
CareNoteService.ingestRealtimeEvent                           │
   ├── hydrateVisit (DB rehydrate if cold start)              │
   ├── applyRealtimeEventToVisitState → VisitState.turns++    │
   ├── persistVisitState (async; Postgres ConsultSession.visitState)
   ├── eventBus.emit transcript_turn_completed ──────────────►│
   └── enqueue analyze_turn job in CodexJobQueue               │
                                                              │
CodexRunManager.analyzeTurn (per-visit serial)                │
   ├── recall.prefetch(visit, user, query)        [Week 2]    │
   │     └── manifest cache → sideQuery (gpt-5.4-mini, 2.2s)  │
   │     └── surface (16KB cap) → toAppendBlock                │
   ├── for each of 11 roles, runRole():                        │
   │     a. mailbox.drainUnread(visit, role)      [Week 3]    │
   │     b. blackboard.readMany(visit, subscribedKeysFor(role)) │
   │     c. assembleCodexPrompt → pre_built_user_message       │
   │     d. team.run(role, { instructions: registry+recall.append, │
   │                          pre_built_user_message })         │
   │     e. eventBus.emit agent_run_started/completed ────────►│
   │     f. codex SDK runs in thread (team, visit, role)        │
   ├── reduceTurn → VisitState.set                              │
   └── publishToBlackboard(envelope)              [Week 4]      │
         └── for each canonical key (allergies, medication_plan_draft,
             follow_up_tasks, safety_flags, family_brief):       │
             - deep-equal vs current                             │
             - if changed → blackboard.write → emit ────────────►│
                                                                │
Bus events fanned out:                                          │
   - SSE controller pipes them to subscribed browsers ─────────►│
   - SubscriptionRegistry checks subs → enqueue single_role     │
       job (cooldown 2s; MAX_HOPS 3)                             │
   - CodexRunManager.runOneRoleOnDemand handles single_role      │
                                                                │
Frontend reacts to each event type:                             │
   - transcript_turn_completed → refresh()                      │
   - agent_run_completed       → refresh()                      │
   - blackboard_updated        → refresh()                      │
   - visit_status_changed      → refresh()                      │
   - heartbeat (15s)           → keep proxy alive               │
```

Daily at 03:00 local time:

```
DreamCron @Cron('0 3 * * *') ──► AutoDreamService.runDailyConsolidation
   for each User w/ ENDED visit in last 24h:
      ├── 5-gate filter (kairos / enabled / time / scan-throttle / sessions / lock)
      ├── consolidationLock.acquire(userId)  (O_EXCL file + UserDreamLock row)
      ├── load { transcript, summary } per visit
      ├── OpenAI Chat (gpt-4o-mini) with strict JSON schema
      ├── apply patch → users/<u>/{MEMORY.md, memory_summary.md, allergies.md,
      │                            conditions.md, rollout_summaries/<vid>.md,
      │                            skills/<name>.md}
      ├── User.lastDreamedAt = now
      ├── eventBus.emit dream_completed
      └── consolidationLock.release(userId)
```

---

## 4. Module map (what's where)

```
backend/src/modules/carenote/
├── api/
│   ├── carenote.controller.ts          [Week 1, 4]    HTTP surface, SSE, admin auto-dream
│   ├── carenote.module.ts              [Week 1, 2, 3, 4]  Nest wiring (12 providers)
│   ├── carenote.service.ts             [Week 1, 2, 3, 4]  visit lifecycle, persistence,
│   │                                                       hydrate, harness lazy-load
│   ├── carenoteRealtime.controller.ts  [Week 1]       /api/realtime/session (ensureOwner)
│   ├── codexHarnessApi.ts              [Week 2, 3, 4] assembleHarness factory
│   └── (existing) bootstrap.cli.ts, redactPhi.ts, smoke-role.cli.ts, …
│
├── codex-harness/
│   ├── codexAgentRegistry.ts           (existing)
│   ├── codexAgentTeam.ts               [Week 2]       extra_instructions concat
│   ├── codexCliRuntime.ts              (existing)
│   ├── codexJobQueue.ts                [Week 3]       added single_role job kind
│   ├── codexPromptAssembler.ts         [Week 2 NEW]   §6 dynamic template
│   ├── codexRunManager.ts              [Week 2, 3, 4] recall + mailbox + blackboard
│   │                                                   + on-demand + lifecycle events
│   ├── codexRuntime.ts                 [Week 2]       added pre_built_user_message
│   ├── codexSdkRuntime.ts              [Week 1, 2]    per-visit thread cache key,
│   │                                                   prefer pre_built_user_message
│   ├── codexThreadStore.ts             (existing)
│   ├── stubRuntime.ts                  (existing; setOverride used for tests)
│   └── …
│
├── medical/
│   ├── medicalSchemas.ts               (existing)     VisitState, role outputs
│   ├── medicalReducers.ts              (existing)
│   ├── memoryRetrieval.ts              (existing stub; superseded by recall/)
│   └── visitStateStore.ts              (existing)
│
├── recall/                             [Week 2 NEW DIR]
│   ├── recall.constants.ts             gpt-5.4-mini default, 2.2 s, 96 KB, 16 KB
│   ├── recall.types.ts                 ManifestEntry, SurfacedFile, RecallResult
│   ├── recallCache.ts                  Redis + in-memory fallback
│   ├── memoryScan.ts                   walks visits/<v>/ + users/<u>/, frontmatter parser
│   ├── memorySideQuery.ts              gpt-5.4-mini-2026-03-17, JSON {selected:[]} contract
│   ├── memorySurface.ts                file read, UTF-8 safe slice, traversal-guarded
│   ├── recallBudget.ts                 incrBy + sismember on Redis
│   └── memoryRecall.ts                 4-phase orchestrator, never-throw contract
│
├── swarm/                              [Week 3, 4 NEW DIR]
│   ├── eventBus.ts                     [Week 1]       RxJS Subject + 9 event types
│   ├── mailboxMessages.ts              [Week 3]       9 typed protocol messages
│   ├── mailboxFile.ts                  [Week 3]       proper-lockfile, path-traversal-safe
│   ├── mailboxService.ts               [Week 3]       file + DB mirror + bus emit
│   ├── blackboard.ts                   [Week 3]       versioned KV upsert
│   ├── tasks.ts                        [Week 3]       CarenoteTask CRUD
│   ├── subscriptionRegistry.ts         [Week 3]       on-demand triggers + cooldown + hop counter
│   ├── consolidationLock.ts            [Week 4]       O_EXCL file lock + UserDreamLock row
│   ├── autoDream.ts                    [Week 4]       5-gate consolidator + atomic file writes
│   └── dreamCron.ts                    [Week 4]       @Cron('0 3 * * *')
│
├── realtime/                           (existing, unchanged in v02)
└── prompts/                            (existing, unchanged)

backend/src/
├── main.ts                             [Week 4]       json-limit 256kb,
│                                                       forbidNonWhitelisted, prod-CORS
├── modules/auth/jwt.strategy.ts        [Week 1]       Bearer + ?token=… extractors
├── common/decorators/current-user.ts   (existing)
└── …

backend/prisma/schema.prisma            [Week 1]       +User.{autoDreamEnabled,lastDreamedAt}
                                                       +ConsultSession.{language,consentRecorded,
                                                                         rawAudioSaved,visitState}
                                                       +CarenoteTask, CarenoteBlackboard,
                                                        CarenoteMailbox, CarenoteAgentRun,
                                                        UserDreamLock

frontend/
├── pages/carenote/
│   ├── index.vue                       [Week 1]       useAuth(), no localStorage guest IDs
│   └── visit/[id].vue                  [Week 1, 4]    SSE subscribe, End & review wait race
├── composables/
│   └── useCareNote.ts                  [Week 1]       removed user_id from CreateVisitInput
└── …

nginx-zai.gold.conf                     [Week 4]       +location ~ events$ access_log off,
                                                       proxy_read_timeout 24h
```

---

## 5. The 4-layer communication mechanism (Codex edition)

Direct port of CCLearn note 4 patterns onto codex thread isolation.

### Layer 0 — Codex thread (private chain of thought)

| Aspect | Implementation |
|---|---|
| Purpose | Per-(team, visit, role) private context |
| Storage | `~/.codex/sessions/.../<thread_id>.jsonl` (codex-managed) |
| Pointer | `.data/carenote/threads/<team>/<visit>/<role>.json` (codexThreadStore) |
| Cache key | `${team_id}:${visit_id}:${role}` — fixes pre-v01 cross-visit leak |
| Contract | A role NEVER sees another role's codex transcript. Cross-role data flows only through Layer 1–3. |

### Layer 1 — File-backed mailbox (typed async signaling)

| Aspect | Implementation |
|---|---|
| File | `.data/carenote/teams/<visit_id>/inboxes/<role>.json` |
| Lock | `proper-lockfile { retries: { retries: 5, factor: 2, minTimeout: 100, maxTimeout: 30000 }, stale: 30000 }` |
| Atomic write | `mkdir -p` → `writeFile flag:'wx'` seed `[]` → `lock` → `readFile` → push → `writeFile pretty` → `release` |
| Mark read | flag flip; messages NEVER deleted (audit-friendly) |
| DB mirror | `CarenoteMailbox` table; `INSERT` after each file append; `updateMany` after each drain |
| Path safety | `safeSegment()` strips non-`[A-Za-z0-9_-]`; `resolve()` verifies path stays in root |
| 9 message types | `task_assignment`, `task_notification`, `permission_request`, `permission_response`, `idle_notification`, `plan_approval_request`, `plan_approval_response`, `recall_request`, `recall_response` |
| Wire format | `{ from, text, timestamp, read, color?, summary? }` with structured payload JSON-encoded in `text` |
| Prompt injection helper | `formatTeammateMessages()` wraps in `<teammate_message teammate_id="..." color="..." summary="...">` XML |

### Layer 2 — Permission bridge (worker ↔ leader handshake)

Protocol messages exist (`permission_request`, `permission_response`, `plan_approval_request/response`); the bridge service is **deferred to v01.1** because it needs human-in-loop UI to send responses. Mailbox is wired to carry these without further surgery.

### Layer 3 — Lifecycle handshakes

`idle_notification` and the plan-approval messages are typed and routable today; their consumers are pending (same v01.1 unblock).

### Cross-cutting — Blackboard (versioned shared state)

| Aspect | Implementation |
|---|---|
| Storage | `CarenoteBlackboard` Postgres table, `(visitId, key)` UNIQUE |
| Version | bumped on every write; opaque to consumers; used for ordering/telemetry |
| Read | `read(visit, key)` or `readMany(visit, [keys])` |
| Write | upsert in tx, version+1, emits `blackboard_updated` to bus |
| Subscriber pattern | roles register `{onBlackboardKeys: [...]}` in `SubscriptionRegistry` |
| On-demand trigger | bus `blackboard_updated` → registry → enqueue `single_role` job (cooldown 2 s, MAX_HOPS 3, self-bounce filter) |
| Reducer wiring (Week 4) | `analyzeTurn → publishToBlackboard(envelope)` writes 5 canonical keys (allergies, medication_plan_draft, follow_up_tasks, safety_flags, family_brief) with deep-equal change detection |

### Default subscriptions seeded by `registerDefaultsFor`

| Role | onBlackboardKeys | onMailboxFromAnyone |
|---|---|---|
| `medication_reminder_draft` | allergies, medication_plan_draft | true |
| `safety_clarification` | safety_flags | true |
| `family_summary` | family_brief, safety_flags | false |

### Cycle-breaker rules

- **Cooldown**: per-(visit, role) = 2 000 ms.
- **Hop counter**: each `single_role` job carries `hop`; each enqueue increments; `MAX_HOPS = 3` → log `cycle_breaker_engaged` and drop.
- **Self-bounce filter**: `writtenBy === role` → registry doesn't fire; a role can't trigger itself.

---

## 6. Recall pipeline (file-only, Codex folder convention)

### Folder layout

```
.data/carenote/memory/
├── visits/
│   └── <visit_id>/
│       ├── MEMORY.md
│       ├── memory_summary.md
│       ├── rollout_summaries/<turn_window>.md
│       ├── skills/*.md
│       └── read_path.md
└── users/
    └── <user_id>/
        ├── MEMORY.md
        ├── memory_summary.md
        ├── rollout_summaries/<visit_id>.md
        ├── allergies.md
        ├── conditions.md
        └── caregiver_prefs.md
```

Frontmatter (parsed by tiny inline YAML reader, no `gray-matter` dep):

```yaml
---
name: penicillin_allergy
type: clinical_fact
keywords: [allergy, antibiotic, penicillin, amoxicillin]
last_used: 2026-04-29
source_visit: cmok489p
---
```

### 4 phases

| # | Phase | Class | Key behavior |
|---|---|---|---|
| 1 | Scan | `MemoryScanService` | walks both roots, parses frontmatter, builds manifest; cached in Redis 300 s |
| 2 | sideQuery | `MemorySideQueryService` | calls `gpt-5.4-mini-2026-03-17` (configurable), JSON `{selected:[]}` contract, raced against 2.2 s outer timeout |
| 3 | Surface | `MemorySurfaceService` | reads selected files; UTF-8-safe slice to `MAX_BYTES_PER_FILE = 16 KB`; resolves & verifies path stays in root |
| 4 | Inject | `toAppendBlock` | wraps as Markdown `## Patient Memory Context`; appended to role's `instructions` (system prompt side) via `extra_instructions` |

### Budget + dedup

- Per-visit byte budget: `MAX_VISIT_BYTES = 96 KB` (Redis `carenote:recall:budget:<visit_id>`, TTL 24 h).
- Per-(visit, file@mtime) dedup set (Redis): same file with same mtime never re-injected within a visit.

### Skip rules — `prefetch()` returns `{append:null, skipped:'X'}` for:

- `subagent` — `opts.isSubagentFork === true`
- `disabled` — `CARENOTE_RECALL_ENABLED=false` or no `OPENAI_API_KEY`
- `no_visit` — missing visit_id
- `visit_budget` — budget exhausted
- `empty` — manifest empty OR sideQuery returned 0 OR all dedup-blocked
- `sidequery_timeout` — > 2 200 ms LLM call
- `sidequery_failed` — JSON parse fail / LLM error

### Telemetry

Per turn, `[recall] visit=… turn=… latency=Xms files=N bytes=Y manifestSize=M selected=K` to `pm2 logs`.

---

## 7. Auto-dream daily consolidation

### Trigger

`@Cron('0 3 * * *')` — daily 03:00 local time.
Manual: `POST /api/admin/auto-dream/run` (role=ADMIN gated).

### Per-user 5-gate filter

| # | Gate | Constant |
|---|---|---|
| 1 | enabled | `CARENOTE_DREAM_ENABLED !== "false"` AND `User.autoDreamEnabled === true` AND `OPENAI_API_KEY` set |
| 2 | time since last | `>= 20 h` since `User.lastDreamedAt` |
| 3 | scan throttle | `>= 10 min` since this user's last in-process scan |
| 4 | sessions count | `>= 1` ENDED visit since `User.lastDreamedAt` |
| 5 | lock | `consolidationLock.acquire(userId)` succeeded |

### Algorithm

1. Acquire lock (`O_EXCL` file `.consolidation.lock` + `UserDreamLock` DB row, 30 min TTL, stale-break).
2. List ENDED visits since `lastDreamedAt - 1h` (overlap for late closures).
3. Build per-visit `{ visit_id, started_at, ended_at, summary, transcript (capped at 32 KB) }`.
4. Call OpenAI Chat (`gpt-4o-mini` default, override via `CARENOTE_DREAM_MODEL`) with strict JSON schema:
   ```json
   {
     "memory_summary": "...",
     "rollout_summaries": [{"visit_id":"...","markdown":"..."}],
     "skills": [{"name":"snake_case","markdown":"..."}],
     "allergies": ["..."] | null,
     "conditions": ["..."] | null
   }
   ```
5. Apply patch (atomic per file):
   - `memory_summary.md`, `allergies.md`, `conditions.md` (if present)
   - `rollout_summaries/<sanitized_visit_id>.md` per entry
   - `skills/<sanitized_name>.md` per entry
   - `MEMORY.md` (regenerated index)
6. `User.lastDreamedAt = now`; emit `dream_completed`; release lock.
7. On failure: log error, release lock; current files left in place (no rollback in v02 — atomic per-file writes mean partial state is at worst a partial update).

### Filename safety

`sanitizeFilename()`: lowercase, `[a-z0-9_-]` only, length ≤ 64; `null` → entry dropped.

### Why OpenAI Chat instead of a 12th codex role

A dedicated codex thread per user per day is overkill — auth quota burn for no quality gain. Auto-dream is one schema-bound LLM call; the openai SDK with `response_format: json_object` is sufficient. Captured as D14.

---

## 8. Dynamic prompt assembly

### Why dynamic, not static-cache-optimized

Per the user (cross-checked with OpenAI eng): codex SDK handles prompt cache internally. We don't design around stable byte prefixes. We get instead:

- Easier reasoning about what each role sees
- No "do not edit, will break cache" landmines
- Truthful prompts — every byte was selected for this turn

### The standard template

`assembleCodexPrompt(args) → { instructions, userMessage, recall }`

**`instructions`** (codex SDK system prompt) — composed by `CodexAgentTeam.run`:
```
[A. Role definition — static, from prompts/codex-agents/<role>.md]

[B. Memory context — recall.append for this turn]
```

**`userMessage`** (codex SDK user turn input):
```
<visit_context>
visit_id: …
language: zh
status: recording
turn_count: 17
</visit_context>

<recent_transcript window="5">
[doctor i14] …
[patient i15] …
</recent_transcript>

<inbox>
<teammate_message teammate_id="speaker_role" kind="task_assignment">
{"type":"task_assignment", …}
</teammate_message>
</inbox>

<blackboard>
{ "allergies": ["penicillin"], … }
</blackboard>

<event>
{"event_kind":"analyze_turn","visit_id":"…","turn":{…}}
</event>

<expected_output_schema_name>
medical_instruction_extractor
</expected_output_schema_name>
```

### What's NEVER in the prompt (CCLearn note 4 §"DON'T")

- Other roles' raw codex transcripts
- Other visits' blackboard / mailbox / memory
- Other users' memory
- Anything from the legacy `/sessions` / `/agents` line

### Wire details

`CodexAgentRunInput.pre_built_user_message?: string | null` carries the assembler's `userMessage`. `codexSdkRuntime.run` prefers it over the legacy `buildUserMessage`. Legacy path still runs for `json_repair` and `summarise` jobs.

`CodexAgentRunInput.extra_instructions?: string | null` carries `recall.append`. `CodexAgentTeam.run` concatenates after `def.prompt` from registry.

---

## 9. Persistence model

### Tables added in v02

```
ConsultSession  +language String?
                +consentRecorded Boolean @default(false)
                +rawAudioSaved   Boolean @default(false)
                +visitState      Json    @default("{}")

User            +autoDreamEnabled Boolean @default(true)
                +lastDreamedAt    DateTime?
                +relation dreamLock UserDreamLock?

CarenoteTask        — durable shared work units (Layer 2)
CarenoteBlackboard  — versioned KV per visit (cross-cutting)
CarenoteMailbox     — DB mirror of file inboxes (Layer 1)
CarenoteAgentRun    — per-codex-run telemetry (visitId or userId for dream)
UserDreamLock       — per-user dream lock visibility row
```

Schema applied via `npx prisma db push` (no `prisma/migrations/` directory in this repo). Future: baseline with `prisma migrate diff --from-empty --to-schema-datamodel … > 0_init.sql` + `prisma migrate resolve --applied 0_init`.

### File vs DB split

| Data | File | DB | Why |
|---|---|---|---|
| Visit metadata | — | `consult_sessions` | queryable list + joins |
| Transcript utterances | — | `transcript_utterances` | already there, indexed |
| VisitState snapshot | — | `consult_sessions.visitState` JSON | whole-blob read on cold start |
| Blackboard | — | `carenote_blackboard` | per-key queryable, versioned, SSE fanout |
| Mailbox | `.data/carenote/teams/<v>/inboxes/<role>.json` | `carenote_mailbox` (mirror) | **file = source of truth + lock**; DB = SSE + UI |
| Agent runs | — | `carenote_agent_runs` | (table exists; not yet written — Week 5) |
| Codex thread pointers | `.data/carenote/threads/<team>/<visit>/<role>.json` | — | codex SDK consumes JSON, no need to query |
| Memory files | `.data/carenote/memory/{visits,users}/...` | — | Markdown, recall pipeline reads them |
| Codex rollouts | `~/.codex/sessions/.../<thread_id>.jsonl` | — | codex-managed |
| Auto-dream lock | `.data/carenote/memory/users/<u>/.consolidation.lock` | `user_dream_locks` | file = inter-process safety; DB = ops visibility |

### Hydrate-on-cold-start

`CareNoteService.hydrateVisit(visit_id)`:
1. Cache hit? Return.
2. SELECT `consult_sessions WHERE id = visit_id` (404 if not found).
3. Build `CareNoteVisitMeta` from row.
4. `VisitStateSchema.safeParse(row.visitState)` — on success, hydrate harness's in-memory store; on parse failure, log + start fresh.
5. Cache the meta in `this.visits` Map for next call.

`persistVisitState(visit_id)`: fire-and-forget after `ingestRealtimeEvent`. Writes `consult_sessions.visitState = <state>` and `utteranceCount = state.turns.length`. Errors logged, never propagated to client.

### Soft delete

`deleteVisit` sets `status = ARCHIVED`, removes in-memory map. `getVisit` then returns 404 even though the DB row stays for audit.

---

## 10. EventBus + SSE

### Bus

`CarenoteEventBus` — single RxJS Subject (in-process). 9 event types:

```ts
| { type: "transcript_turn_committed"; visitId; turnId; text; speaker }
| { type: "transcript_turn_completed"; visitId; turnId; transcript }
| { type: "agent_run_started";        visitId; role; runId }
| { type: "agent_run_completed";      visitId; role; runId; status: "valid"|"repaired"|"failed" }
| { type: "blackboard_updated";       visitId; key; writtenBy; version }
| { type: "mailbox_message";          visitId; from; to; payloadKind }
| { type: "permission_response";      visitId; requestId; behavior }
| { type: "visit_status_changed";     visitId; status }
| { type: "dream_completed";          userId; filesUpdated }
```

Filters: `streamForVisit(visitId)`, `streamForUser(userId)`, `stream()` (the `SubscriptionRegistry` uses the unfiltered stream).

### SSE endpoint

```
GET /api/visits/:visitId/events?token=…

@Sse decorator → Observable<MessageEvent>
  filter by visitId
  + heartbeat every 15s

merge → Express SSE response
```

Auth: `streamEvents` is `@UseGuards(AuthGuard("jwt"))` and calls `ensureOwner(visitId, user.id)` BEFORE returning the observable. JWT comes from `?token=` (Bearer header is impossible for `EventSource`). Stream is filtered server-side by `visitId` so a leaked URL still can't peek other visits' events.

nginx config:
```
location ~ ^/api/visits/[^/]+/events$ {
    access_log off;                # no JWT in nginx logs
    proxy_pass http://clariose_backend;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 24h;        # SSE keep-alive
}
```

Frontend (`pages/carenote/visit/[id].vue`):
```ts
const token = useCookie("clariose_token").value;
const url = `/api/visits/${visitId}/events?token=${encodeURIComponent(token)}`;
eventSource = new EventSource(url);
eventSource.addEventListener("transcript_turn_completed", () => refresh());
eventSource.addEventListener("agent_run_completed",       () => refresh());
eventSource.addEventListener("blackboard_updated",        () => refresh());
eventSource.addEventListener("visit_status_changed",      () => refresh());
// 30s polling fallback for mobile sleep / dropped SSE
pollTimer = setInterval(refresh, 30_000);
```

---

## 11. Per-visit isolation

`codexSdkRuntime.run` cache key:

```diff
- const key = `${input.team_id}:${input.role}`;
+ const key = `${input.team_id}:${input.visit_id}:${input.role}`;
```

Cost: per visit, up to 11 codex threads (12 with auto-dream when codex variant lands). User OK'd this in D11. Cleanup is currently manual (`find ~/.codex/sessions -mtime +7 -delete` cron entry recommended).

Per-visit ownership enforcement on every endpoint:

```
POST   /api/visits                         CurrentUser → owner
GET    /api/visits                         list owned
GET    /api/visits/:id                     ensureOwner
GET    /api/visits/:id/events              ensureOwner (SSE)
POST   /api/visits/:id/realtime-events     ensureOwner
POST   /api/visits/:id/stage-summary       ensureOwner
POST   /api/visits/:id/final-summary       ensureOwner
POST   /api/visits/:id/draft-tasks/:tid/{confirm,reject}     ensureOwner
POST   /api/visits/:id/memory-candidates/:cid/{confirm,reject}  ensureOwner
DELETE /api/visits/:id                     ensureOwner
POST   /api/realtime/session               ensureOwner (was unguarded → S2)
POST   /api/admin/auto-dream/run           role === "ADMIN" only
```

`ensureOwner(visitId, userId)` returns 404 (not 403) on miss to avoid existence leak.

---

## 12. Security review (16 findings, audited 2026-04-30)

### Closed

| # | Finding | Severity | Fix |
|---|---|---|---|
| S1 | `POST /api/visits` accepted `user_id` from body → horizontal-priv | **High** | DTO field removed; `@CurrentUser` is the owner |
| S2 | `POST /api/realtime/session` did not verify visit ownership | **High** | `ensureOwner` added |
| S3 | SSE endpoint had auth guard but EventSource can't send Bearer → effectively open | **High** | JWT strategy `?token=…` extractor; route calls `ensureOwner` before bus subscribe |
| S4 | mailbox file path traversal via `visit_id` / `role` | **Med** | `safeSegment()` + `resolve()` keep path inside root |
| S5 | recall surface path traversal via cached `relPath` | **Med** | `memorySurface` resolves & verifies prefix |
| S6 | auto-dream LLM-controlled `skills.name` / `visit_id` could write outside user dir | **Med** | `sanitizeFilename()` enforces `[a-z0-9_-]{1,64}` |
| S7 | no JSON body size cap → trivial OOM via realtime-events | **Med** | `app.use(json({ limit: '256kb' }))` |
| S8 | `forbidNonWhitelisted: false` silently accepts unknown fields, masks bugs | **Low** | flipped to `true`; fixed `RealtimeEventDto.event` to declare `@IsObject` |
| S9 | CORS `origin: true` reflects any origin | **Low** | locked to `APP_BASE_URL` (default `https://zai.gold`) in production |
| S10 | SSE `?token=…` in URL would land in nginx access_log | **Low** | nginx `events$` location adds `access_log off` |
| S13 | auto-dream double-run on cron tick collision | **Low** | `O_EXCL` file lock + 30 min TTL stale-break + `UserDreamLock` row |

### Verified clean

| # | Finding | Result |
|---|---|---|
| S11 | `npm audit --omit dev` (backend + frontend) | 0 vulnerabilities |
| S12 | PHI in logs | only dev CLI `replay-transcript.cli.ts` prints raw transcripts; all Nest service logs use `redactPhi()` or log only IDs/counts |
| S16 | CSRF | N/A — Bearer auth, no cookies for `/api/*`; SSE token-in-URL not exploitable cross-origin |

### Acknowledged, not fixed in v02

| # | Finding | Severity | Reason |
|---|---|---|---|
| S14 | Realtime ephemeral key not bound to visit_id | Acknowledged | OpenAI API doesn't expose binding; mitigated by ≤60 s TTL + HTTPS |
| S15 | `/auth/login` rate-limit at 120/min/IP could allow brute force | Low | pre-existing `@Throttle` in auth.controller; out of v02 scope |

### Defense-in-depth

- `ValidationPipe { whitelist: true, forbidNonWhitelisted: true, transform: true }` — all DTOs explicit; unknown fields → 400.
- All carenote endpoints `@UseGuards(AuthGuard("jwt"))` + `ensureOwner`.
- `consult_sessions.ownerUserId` FK → `users(id)` ON DELETE CASCADE; `user_dream_locks.userId` ditto.
- `app.listen(port, '127.0.0.1')` — Nest binds loopback only; nginx is sole external surface.
- `helmet` provides default security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy).
- 9 typed events go through `EventBus`; unknown field shapes can't sneak past the discriminated union.

---

## 13. Test coverage

```
backend/test/carenote/
├── carenoteApi.spec.ts                 (existing)        7 tests
├── transcriptIngestService.spec.ts     (existing)        4 tests
├── transcriptVisibility.spec.ts        (existing)
├── teamPersistence.spec.ts             (existing)
├── promptAssembler.spec.ts             [Week 2 NEW]      5 tests
├── memoryRecall.spec.ts                [Week 2 NEW]      6 tests
├── promptAssemblerWiring.spec.ts       [Week 2 NEW]      1 test (E2E with stub runtime)
├── swarmCommunication.spec.ts          [Week 3 NEW]      8 tests
├── autoDreamGates.spec.ts              [Week 4 NEW]      5 tests
├── fakePrisma.ts                       [Week 1 NEW]      test helper (in-memory Prisma)
└── (other suites)
```

**Result**: 19 suites, **88 / 88 tests passing**.

Helpers:
- `fakePrisma.ts` — in-memory Prisma stub for tests that need DB shape without real Postgres.
- `StubRuntime.setOverride(role, fn)` — used in `promptAssemblerWiring.spec.ts` to capture the input each role would have sent to codex.

---

## 14. Operations runbook

### Environment variables

```bash
# Database / cache (existing)
DATABASE_URL=postgresql://…
REDIS_URL=redis://127.0.0.1:6379

# Auth (existing)
JWT_SECRET=<openssl rand -hex 48>

# OpenAI (existing)
OPENAI_API_KEY=sk-…
OPENAI_REALTIME_MODEL=gpt-realtime
OPENAI_AGENT_MODEL=gpt-4o-mini

# CLARIOSE_V01 carenote — Week 2
CARENOTE_SIDEQUERY_MODEL=gpt-5.4-mini-2026-03-17
CARENOTE_RECALL_ENABLED=true
CARENOTE_MEMORY_ROOT=/home/ubuntu/Zai/.data/carenote/memory

# CLARIOSE_V01 carenote — Week 3
CARENOTE_TEAMS_ROOT=/home/ubuntu/Zai/.data/carenote/teams

# CLARIOSE_V01 carenote — Week 4
CARENOTE_DREAM_ENABLED=true
CARENOTE_DREAM_HOUR=3        # informational only; cron is hard-coded to 0 3 * * *
CARENOTE_DREAM_MINUTE=0      # informational only
# CARENOTE_DREAM_MODEL=gpt-4o-mini   # optional override
```

### PM2

```bash
pm2 list                                    # clariose-backend, clariose-frontend should be online
pm2 reload clariose-backend --update-env       # after .env edit
pm2 logs clariose-backend --lines 100          # check Bootstrap, DreamCron, [recall] lines
```

### Nginx

```
sudo cp /home/ubuntu/Zai/nginx-zai.gold.conf /etc/nginx/sites-available/zai.gold
sudo nginx -t && sudo systemctl reload nginx
```

### Health checks

```bash
curl -s -i http://127.0.0.1:4400/api/health | head -1     # 200 OK
pm2 logs clariose-backend --lines 20 --nostream | grep -E "Bootstrap|DreamCron|RouterExplorer"
```

### Auto-dream manual run

```bash
# Admin user JWT in $TOKEN
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:4400/api/admin/auto-dream/run | jq
```

### Daily cron

```
@Cron('0 3 * * *')   →   AutoDreamService.runDailyConsolidation()
```

Logs to `pm2 logs clariose-backend`:
```
[DreamCron] scheduled daily auto-dream at 0 3 * * *
[DreamCron] cron tick complete: users=N ok=N failed=N
[recall] visit=… turn=… latency=Xms files=N bytes=Y manifestSize=M selected=K
```

---

## 15. What was deferred (v01.1 / v01.2 backlog)

| Item | Why deferred | Difficulty to land |
|---|---|---|
| `/consult` + `sessions/` + `agents/` modules deletion | wait until carenote UI is at parity | M (1 PR cleanup) |
| `/consult` visual asset port to `/carenote/visit/[id]` | substantial frontend | L (1–2 days) |
| 4 agent cards UI binding to blackboard | `GET /api/visits/:id` already returns the data; just rebind | S (few hours) |
| `PermissionBridge` worker↔leader handshake | needs human-in-loop UI to send responses | M (1 PR + UI) |
| 12th `memory_consolidator` codex role | OpenAI Chat is sufficient at scale; revisit if quality regresses | M (manifest + prompt + integration) |
| Visit thread cleanup cron (7-day) | manual `find … -mtime +7` is fine for v01 | XS (1 file) |
| `CarenoteAgentRun` table writes (per-run telemetry) | table exists but writer not wired; useful for ops dashboard | S |
| Codex Phase 1 / Phase 2 background memory pipeline | auto-dream cron is sufficient at demo scale | L |
| `read_path.md` explicit-path-pull semantic | scanned as ordinary file today; the explicit-path-pull is a Codex-native feature we don't replicate | M |
| `prisma/migrations/` baseline | currently using `prisma db push`; should baseline before any future migration PR | XS |
| Multi-machine deployment (Postgres advisory locks instead of file locks) | single-host today; captured in §3 of v01 | M |

---

## 16. Glossary of in-source markers

To keep the source and this doc in sync:

```
// CLARIOSE_V01: implements §X.Y       — implemented per spec
// CLARIOSE_V01_PENDING: planned for §X.Y — stub or unimplemented
// CLARIOSE_V01_DEFERRED: see §X.Y, not in v01 — captured but not in scope
// CLARIOSE_V01 §security              — security-hardening change
```

`grep -rn "CLARIOSE_V01" backend/src` returns the live audit trail.

---

## 17. File index

### New files (24)

```
backend/src/modules/carenote/swarm/eventBus.ts                              [Week 1]
backend/src/modules/carenote/recall/recall.constants.ts                     [Week 2]
backend/src/modules/carenote/recall/recall.types.ts                         [Week 2]
backend/src/modules/carenote/recall/recallCache.ts                          [Week 2]
backend/src/modules/carenote/recall/memoryScan.ts                           [Week 2]
backend/src/modules/carenote/recall/memorySideQuery.ts                      [Week 2]
backend/src/modules/carenote/recall/memorySurface.ts                        [Week 2]
backend/src/modules/carenote/recall/recallBudget.ts                         [Week 2]
backend/src/modules/carenote/recall/memoryRecall.ts                         [Week 2]
backend/src/modules/carenote/codex-harness/codexPromptAssembler.ts          [Week 2]
backend/src/modules/carenote/swarm/mailboxMessages.ts                       [Week 3]
backend/src/modules/carenote/swarm/mailboxFile.ts                           [Week 3]
backend/src/modules/carenote/swarm/mailboxService.ts                        [Week 3]
backend/src/modules/carenote/swarm/blackboard.ts                            [Week 3]
backend/src/modules/carenote/swarm/tasks.ts                                 [Week 3]
backend/src/modules/carenote/swarm/subscriptionRegistry.ts                  [Week 3]
backend/src/modules/carenote/swarm/consolidationLock.ts                     [Week 4]
backend/src/modules/carenote/swarm/autoDream.ts                             [Week 4]
backend/src/modules/carenote/swarm/dreamCron.ts                             [Week 4]
backend/test/carenote/fakePrisma.ts                                         [Week 1]
backend/test/carenote/promptAssembler.spec.ts                               [Week 2]
backend/test/carenote/memoryRecall.spec.ts                                  [Week 2]
backend/test/carenote/promptAssemblerWiring.spec.ts                         [Week 2]
backend/test/carenote/swarmCommunication.spec.ts                            [Week 3]
backend/test/carenote/autoDreamGates.spec.ts                                [Week 4]
docs/design/clariose-v01-0430.md                                            [running spec]
docs/design/clariose-v02-0430.md                                            [this doc]
.data/carenote/memory/users/_sample/MEMORY.md                               [Week 2]
```

### Modified files

```
backend/prisma/schema.prisma              +5 tables, +6 columns
backend/src/main.ts                       json-limit 256kb, forbidNonWhitelisted, prod-CORS
backend/src/modules/auth/jwt.strategy.ts  +?token=… extractor
backend/src/modules/carenote/api/carenote.controller.ts            +SSE, +list, +admin auto-dream, +ensureOwner everywhere
backend/src/modules/carenote/api/carenote.module.ts                +12 providers
backend/src/modules/carenote/api/carenote.service.ts               +hydrateVisit, +persistVisitState, +listVisitsForUser, +ensureOwner; injects 7 services
backend/src/modules/carenote/api/carenoteRealtime.controller.ts    +ensureOwner
backend/src/modules/carenote/api/codexHarnessApi.ts                accepts recall/mailbox/blackboard/subscriptions/eventBus; registerDefaultsFor
backend/src/modules/carenote/codex-harness/codexAgentTeam.ts       extra_instructions concat
backend/src/modules/carenote/codex-harness/codexJobQueue.ts        +single_role job kind
backend/src/modules/carenote/codex-harness/codexRunManager.ts      recall + mailbox + blackboard + on-demand + lifecycle events + reducer→blackboard
backend/src/modules/carenote/codex-harness/codexRuntime.ts         +pre_built_user_message, +extra_instructions
backend/src/modules/carenote/codex-harness/codexSdkRuntime.ts      per-visit thread cache key, prefer pre_built_user_message
backend/test/carenote/carenoteApi.spec.ts                          ctor signature, ownerUserId rename
backend/test/carenote/transcriptIngestService.spec.ts              ctor signature, ownerUserId rename
backend/.env.example                                               +CARENOTE_*, +CARENOTE_DREAM_*, +CARENOTE_TEAMS_ROOT
backend/.env                                                       same vars set
backend/package.json                                               +proper-lockfile, +cron, +@types/proper-lockfile
frontend/pages/carenote/index.vue                                  useAuth gate, drop guest IDs, drop user_id from createVisit
frontend/pages/carenote/visit/[id].vue                             SSE subscription, End & review wait race
frontend/composables/useCareNote.ts                                CreateVisitInput dropped user_id
nginx-zai.gold.conf                                                +location ~ events$ access_log off, 24h proxy_read_timeout
```

---

## 18. Status as of 2026-04-30

| Category | Stat |
|---|---|
| Weeks landed | 4 / 4 |
| New files | 24 |
| Modified files | ~22 |
| New backend modules / services | 18 |
| New Prisma tables | 5 |
| New Prisma columns | 6 |
| Test suites | 19 |
| Tests passing | **88 / 88** |
| TypeScript errors | 0 |
| `npm audit` vulnerabilities (prod deps) | 0 backend / 0 frontend |
| Security findings closed | 11 / 16 (5 acknowledged or N/A) |
| User-reported bugs from Apr 29 fixed | 3 / 3 |
| Live deployment | `pm2 list` shows clariose-backend + clariose-frontend ONLINE; `/api/health` returns 200 |
| Daily auto-dream | scheduled (`[DreamCron] scheduled daily auto-dream at 0 3 * * *` confirmed in startup logs) |

---

## 19. References

- `clariose-v01-0430.md` — running spec + decision log + week-by-week status with deferral notes
- `docs/openai_hackathon/Qagent/backend/src/orchestrator/` — Claude-side reference implementation the user built
- `docs/openai_hackathon/docs/CCLearn/notes/notes_integrated/{3,4,5,8}.md` — multi-agent comm + recall + context notes
- `docs/openai_hackathon/docs/CDXLearn/cdx_notes/{5,6}.md` — codex-side recall + multi-agent notes
- `docs/openai_hackathon/docs/CDXLearn/openai-codex-source/` — codex CLI source (Phase 1/Phase 2 reference)
- `docs/openai_hackathon/docs/CCLearn/source/src/` — Claude Code source (auto-dream reference)
