# Clariose v01 — Codex-CLI Multi-Agent Harness Design

> **Date:** 2026-04-30
> **Owner:** wenxuner@gmail.com
> **Status:** Approved for Week 1 implementation; Weeks 2–4 pending
> **Supersedes:** `03_codex_only_harness_architecture.md`, `04_persistent_agent_team_design.md`, `06_migration_from_claude_harness_to_codex_harness.md`
> **Companion:** `docs/openai_hackathon/docs/CCLearn/notes/notes_integrated/{3,4,5}.md`, `docs/openai_hackathon/docs/CDXLearn/cdx_notes/{5,6}.md`, `docs/openai_hackathon/Qagent/`

---

## 0. TL;DR

We standardize Clariose's voice consultation pipeline on the **carenote/codex-harness** subsystem (kill the parallel `/consult`+`agents`+`sessions` line) and bolt onto it the **4-layer multi-agent communication primitives** the user has already proven on Claude in Qagent.

What we keep verbatim from Qagent:
- File-backed mailbox at `.data/carenote/teams/<visit_id>/inboxes/<role>.json` with `proper-lockfile` (Layer 1/2/3 typed protocol messages)
- 4-phase memory recall: scan → sideQuery → surface → inject — file-only, no vector DB
- Auto-dream daily consolidation with 5-gate filter and lockfile-protected memory writes
- RxJS in-process EventBus → SSE bridge to the browser

What we adapt for Codex:
- Memory folder convention follows Codex layout (`MEMORY.md`, `memory_summary.md`, `rollout_summaries/`, `skills/`, `read_path.md`) instead of arbitrary `.md` files. Auto-dream writes to those names.
- sideQuery model: `gpt-5.4-mini-2026-03-17` (configurable via `CARENOTE_SIDEQUERY_MODEL`)
- Codex thread isolation key changes from `(team, role)` → `(team, visit, role)` so each visit is its own conversation.
- Mailbox is **file + DB dual-track**: file is the source of truth + cross-process lock; DB is a queryable index for SSE fanout and UI.
- Prompt assembly is **dynamic-template, not static-cache-optimized**. The user's standpoint (validated against OpenAI eng): SDK handles prompt cache internally; we layer a clean dynamic template on top because that's the more standard, complete contract.
- "On-demand" inter-agent triggers: writing to mailbox / blackboard emits an EventBus event that the run-manager consumes immediately to enqueue the next role. No polling loops between agents within the same Nest process.

What we explicitly **don't** do in v01:
- Codex's Phase 1 / Phase 2 background memory pipeline (`~/.codex/state/` SQLite, claim/lease). We replace it with auto-dream daily cron because visit duration ≤ 1 h doesn't warrant a real-time consolidation pipeline.
- Vector embeddings for recall. sideQuery LLM ranking has been empirically good in Qagent.
- PM2 cluster mode (Nest stays fork). All 4 layers assume single-process today.

---

## 1. Why we're rewriting

### 1.1 The user-visible bugs that drove this

Three real bugs from the 2026-04-29 session (visit `cmok489p`):

1. **Browser refresh wipes the transcript.** `frontend/composables/useRealtime.ts:32` keeps `utterances` in component-local memory; there is no `GET /api/sessions/:id/utterances` endpoint and `sessionId` never makes it to `sessionStorage`. After reload there's nothing to render.
2. **"End & review" → blank summary forever.** `pages/consult.vue:63` navigates to `/dashboard?session=...`; `pages/summary.vue:21` does a one-shot `useAsyncData(/sessions/:id/digest)` with no polling. The family-digest agent is fired only when `n % 3 === 0` (`consult.vue:30`) and is fire-and-forget; navigation usually races ahead of completion.
3. **No codex agent results in the UI.** The `/consult` page calls `/api/sessions/:id/agents/run` which routes to `backend/src/modules/agents/agents.service.ts:204` → OpenAI Chat Completions on `gpt-4o-mini`. **Codex is never called from this path.** The 60+ rollout files in `~/.codex/sessions/2026/04/29/` came from the parallel `carenote/codex-harness` subsystem (CLI smoke tests) which has its own UI at `/carenote/visit/[id]` that the user wasn't using.

### 1.2 Why two pipelines exist today

`backend/src/modules/{realtime, sessions, agents, reminders}` — the original Clariose MVP, gpt-4o-mini fan-out, polished UI at `/consult` + `/summary`.

`backend/src/modules/carenote/{api, codex-harness, medical, realtime, prompts}` — the M5/M6 codex iteration, 11-role team in `config/codex-teams/carenote-doctor-visit.team.json`, working codex SDK runtime, but **only a debug-quality UI**. Visits and tasks live in in-memory `Map`s (`carenote.service.ts:97`); reload kills them.

### 1.3 Decision

Standardize on carenote. Delete the old line. Move the polished UI assets (`components/consult/*.vue`, the orb, the rose-bloom card) over to `pages/carenote/visit/[id].vue`. This is the user's confirmed direction (Step 0 in the prior conversation).

---

## 2. Architectural goals

| Goal | Implication |
|---|---|
| **Realtime → multi-agent team via codex CLI** | Use existing `carenote/codex-harness/codexSdkRuntime.ts`. Each role gets its own codex thread. Agents speak to each other via mailbox + blackboard. |
| **Best quality on demo, no token thrift** | sideQuery uses `gpt-5.4-mini-2026-03-17` (configurable). `MAX_VISIT_BYTES` raised to 96KB. Memory `MAX_BYTES_PER_FILE` raised to 16KB. |
| **Standard, complete dynamic prompt template** | We do NOT optimize for static prompt cache. Each turn re-assembles the full template. Rely on the codex SDK's internal cache. |
| **Persistence across reload / PM2 restart** | All visit state, transcripts, mailbox, blackboard, tasks → Postgres. Memory files → disk (`.data/carenote/memory/...`). |
| **On-demand agent communication, not polling** | Mailbox/blackboard writes emit EventBus events; the run-manager subscribes and enqueues the next role immediately. No `setInterval` loops between sibling agents. |
| **Daily memory consolidation (auto-dream)** | A nightly cron walks ended visits and runs a "dream" codex agent to update `MEMORY.md`, `memory_summary.md`, `rollout_summaries/<visit>.md` per user. |
| **Per-visit isolation** | Codex thread cache key becomes `(team, visit, role)` not `(team, role)`. Mailbox/blackboard partitioned by `visit_id`. |

---

## 3. The 4-layer communication mechanism (Codex edition)

Adapted from CCLearn note 4 ("多agent4层通信机制和通信隔离") and the Qagent `swarm/` module. Each layer below is named to match the source notes.

### Layer 0 — Codex thread (private chain of thought)

| Aspect | Design |
|---|---|
| **Purpose** | Per-(team, visit, role) private context for one agent's multi-turn reasoning. The user said "codex transcript 很标准不用动" — we honor that. |
| **Implementation** | Use `@openai/codex-sdk`'s `startThread` / `resumeThread`. `codexSdkRuntime.ts:79` thread cache key changes to `${team_id}:${visit_id}:${role}`. |
| **Persistence** | Thread state lives in `~/.codex/sessions/.../<thread_id>.jsonl` (codex-managed). Pointer (visit, role) → thread_id stored in `codexThreadStore` JSON files at `.data/carenote/threads/<team>/<visit>/<role>.json`. |
| **Isolation contract** | A role NEVER sees another role's codex transcript. Inter-role information flows only through Layer 1–3 below. |
| **Lifecycle** | Thread created lazily on first `runRole`. Cleaned up by a cron that runs `ended_at < now() - 7d` after visit end. |

### Layer 1 — File-backed mailbox (typed async signaling)

| Aspect | Design |
|---|---|
| **Purpose** | Durable, lock-protected message channel between any two roles in the same visit. |
| **File path** | `.data/carenote/teams/<visit_id>/inboxes/<role>.json` (mirrors Qagent `~/.claude/teams/<team>/inboxes/<agent>.json`). |
| **Lock** | `proper-lockfile` with `{ retries: { retries: 5, factor: 2, minTimeout: 100, maxTimeout: 30_000 }, stale: 30_000 }` (verbatim from Qagent `swarm/teammate-mailbox.service.ts:96`). |
| **Atomic write** | `mkdir -p` → `writeFile flag: 'wx'` to seed `[]` → `lock` → `readFile` → push → `writeFile pretty` → `release`. |
| **Mark-read** | A flag on the message (`read: true`); messages are NEVER deleted until visit cleanup. Audit-friendly. |
| **DB mirror** | Each `writeToMailbox` also `INSERT`s into the `CarenoteMailbox` Postgres table for SSE fanout + cross-tab UI. The file is the source of truth; DB is the queryable index. The reverse is never true. |
| **Message types** | 9 typed messages, ported from `mailbox-messages.ts`: `task_assignment`, `task_notification`, `permission_request`, `permission_response`, `idle_notification`, `plan_approval_request`, `plan_approval_response`, `recall_request`, `recall_response`. |
| **Wire format** | `{ from, text, timestamp, read, color?, summary? }` with structured payload JSON-serialized in `text`. Detectors (`isPermissionRequest()`, `isTaskAssignment()`, etc.) parse at recipient side. Free-form text is allowed and treated as opaque chat. |
| **Format helper** | `formatTeammateMessages()` wraps each message in `<teammate_message teammate_id="..." color="..." summary="...">...</teammate_message>` XML for prompt injection. Verbatim from Qagent. |

### Layer 2 — Permission bridge (worker ↔ leader handshake)

| Aspect | Design |
|---|---|
| **Purpose** | Block a role from doing a sensitive action (touching PHI, drafting a reminder, sending caregiver notification) without leader/human approval. |
| **In Carenote v01** | `visit_orchestrator` is the leader; the other 10 roles are workers. Human-in-the-loop is the patient who clicks "approve" in the UI. |
| **Protocol** | Worker writes `PermissionRequestMessage` (with `request_id = generateRequestId('perm', tool_use_id)`) to leader's mailbox. Worker `await`s a `permission_response_received` EventBus event with matching `request_id`. Timeout: 30s. |
| **No polling** | The wait is event-driven, not polling. Leader's mailbox-write triggers the bus → bus filters by `(visit_id, request_id)` → resolves the worker's promise. This is the on-demand semantics the user asked for. |

### Layer 3 — Lifecycle handshakes (plan approval, shutdown, idle)

| Aspect | Design |
|---|---|
| **Plan approval** | When `medication_reminder_draft` produces a draft list, it sends `PlanApprovalRequestMessage` to `visit_orchestrator` and waits. Leader's "Accept reminders" UI button writes `PlanApprovalResponseMessage`. Same event-driven wait pattern as Layer 2. Timeout: 60s. |
| **Idle notification** | Each worker, after each `runRole`, writes `IdleNotificationMessage` to leader. Leader uses this to know when to advance the pipeline (e.g., after `medication_instruction_extractor` is idle, kick `medication_reminder_draft`). |
| **Shutdown** | On visit `end`, leader broadcasts `ShutdownRequest` to all workers. Each worker drains its mailbox, flushes blackboard, closes its codex thread, replies `ShutdownApproved`. Visit transitions to `ENDED` only when all replies are in (or 15s timeout). |

### Cross-cutting: Blackboard (shared structured state)

| Aspect | Design |
|---|---|
| **Purpose** | Versioned KV per visit, the "shared facts" all roles can read/write. Prevents agents having to chase each other through mailbox for derived data. |
| **Storage** | `CarenoteBlackboard` Postgres table, `(visit_id, key)` unique. Examples: `key="allergies"`, `key="medication_plan_draft"`, `key="safety_flags"`, `key="family_summary_text"`. |
| **Access** | `blackboard.read(visit_id, [keys...])` and `blackboard.write(visit_id, key, value, by=role)`. Every write emits `blackboard_updated` to EventBus. |
| **On-demand triggers** | Roles can subscribe to specific blackboard keys at registration. When `medical_instruction_extractor` writes `key="allergies"`, the run-manager checks subscribers (e.g., `medication_reminder_draft`) and enqueues an `analyze_turn` job for them. |

---

## 4. Recall pipeline (file-only, Codex folder convention)

### 4.1 Folder layout (Codex-style names, Qagent-style mechanics)

We adopt Codex's memory folder names so an operator browsing `.data/carenote/memory/` recognizes the convention from `~/.codex/memories/`. But the access pipeline (scan → sideQuery → surface → inject) is verbatim Qagent.

```
.data/carenote/memory/
├── visits/
│   └── <visit_id>/
│       ├── MEMORY.md              # human-curated index for this visit
│       ├── memory_summary.md      # auto-dream condensed summary (≤ 4KB)
│       ├── rollout_summaries/
│       │   └── <turn_window>.md   # per N-turn rollups
│       ├── skills/
│       │   └── *.md               # task-specific cheatsheets
│       └── read_path.md           # explicit file-recall hints (used by orchestrator role)
│
└── users/
    └── <user_id>/
        ├── MEMORY.md              # global index across visits
        ├── memory_summary.md      # auto-dream cross-visit summary
        ├── rollout_summaries/
        │   └── <visit_id>.md      # one entry per ended visit
        ├── allergies.md           # canonical patient allergies
        ├── conditions.md          # known conditions
        └── caregiver_prefs.md     # contact prefs, language, etc.
```

Files are plain Markdown with YAML frontmatter:
```yaml
---
name: penicillin_allergy
type: clinical_fact
keywords: [allergy, antibiotic, penicillin, amoxicillin]
last_used: 2026-04-29
source_visit: cmok489p
---
Patient experienced anaphylaxis after amoxicillin in 2024-10. Avoid all penicillin-class antibiotics.
```

### 4.2 The 4 phases

#### Phase 1 — Scan

`MemoryScanService.scanForVisit(visit_id, user_id)` walks both the visit-scoped and user-scoped roots, parses frontmatter, returns a manifest:

```ts
type ManifestEntry = {
  name: string;
  relPath: string;       // "users/u-123/allergies.md" or "visits/v-456/skills/tnf_alpha.md"
  scope: "visit" | "user";
  keywords: string[];
  description: string;   // frontmatter.description or first sentence of body
  mtimeMs: number;
  bytes: number;
};
```

Manifest is cached in Redis at `carenote:recall:manifest:<visit_id>` with `MANIFEST_CACHE_TTL_SEC = 300`. Visit-scope and user-scope are merged before caching.

#### Phase 2 — sideQuery

`SideQueryService.select({ query, manifest, recentTools })` calls `gpt-5.4-mini-2026-03-17` with:

- **System**: medical-grade memory retriever instructions, JSON-array-only output contract.
- **User**: the current turn's transcript window + the manifest, asks for top 5 `relPath` strings.

Wrapped in `Promise.race(p, timeout(2200ms))`. On timeout or parse failure, returns `[]` and the main loop proceeds without recall (logged for telemetry).

```ts
const SIDEQUERY_MODEL = process.env.CARENOTE_SIDEQUERY_MODEL ?? "gpt-5.4-mini-2026-03-17";
const SIDEQUERY_TIMEOUT_MS = 2000;
const SIDEQUERY_MAX_RESULTS = 5;
```

#### Phase 3 — Surface

`MemorySurfaceService.readForSurfacing(chosen)` reads selected files from disk. Per-file cap `MAX_BYTES_PER_FILE = 16384` (raised from Qagent's 8192 because demo prioritizes recall quality). Tracks `freshDays` from `mtimeMs`.

#### Phase 4 — Inject

`toAppendBlock(surfaced)` wraps the surfaced files into:

```
## Patient Memory Context

# allergies.md (1d old)
[content]

---

# rollout_summaries/cmok489p.md (3h old, truncated)
[content]
```

The block is appended to the role's system instructions. **It is not optimized for prompt cache stability** — we want it freshest, not most-cacheable. (See §6.)

### 4.3 Budget

Per-visit byte budget tracked in Redis `carenote:recall:budget:<visit_id>` (TTL 24h). `MAX_VISIT_BYTES = 96KB`. Once exceeded, prefetch returns `{ skipped: 'visit_budget' }` until budget rolls over.

Per-(visit, file) dedupe: same surface file isn't re-injected within the same visit unless `mtime` changed. Tracked in Redis set `carenote:recall:surfaced:<visit_id>`.

### 4.4 Skip rules (Qagent "DO" #6 verbatim)

`prefetch()` returns empty without calling sideQuery when:
- `opts.isSubagentFork === true` (pass-2 / pass-3 roles inherit recall from pass-1, no re-query)
- `process.env.CARENOTE_RECALL_ENABLED === 'false'`
- visit_id is missing
- Visit budget already exhausted

---

## 5. Auto-dream daily consolidation

### 5.1 Trigger

Single cron entry, runs daily at 03:00 local time:

```ts
@Cron('0 3 * * *')
async dailyConsolidation() { ... }
```

(Or a manual `POST /api/visits/dream` for ops, gated by admin role.)

### 5.2 Per-user algorithm

For each user with at least one visit ended in the last 24h:

1. **Acquire lock** at `.data/carenote/memory/users/<user_id>/.consolidation.lock` (file create with `O_EXCL`, expire after 30min). On EEXIST, skip (another worker is consolidating).
2. **List target visits**: `Visit` rows where `ownerUserId = u`, `status = ENDED`, `endedAt >= last_consolidation_at - 1h` (overlap to handle late-ending visits).
3. **For each target visit**, read full transcript from `TranscriptUtterance` (DB) and the visit's blackboard snapshot.
4. **Run a dedicated codex agent** `memory_consolidator` (new 12th role, prompt at `prompts/codex-agents/memory_consolidator.md`) with input = `{ visits: [...], existing_user_memory: <files>, schema: { update_files: [{path, content}], rollout_summary: "...", new_skills: [...] }}`.
5. **Apply outputs**:
   - `users/<user_id>/MEMORY.md` ← merge updates (LLM is told to keep the file < 8KB)
   - `users/<user_id>/memory_summary.md` ← overwrite
   - `users/<user_id>/rollout_summaries/<visit_id>.md` ← write
   - `users/<user_id>/skills/<name>.md` ← write new ones
6. **Release lock**, update `User.lastDreamedAt`, emit `dream_completed` to EventBus (for ops dashboard).
7. **On failure**: rollback any partial writes by restoring from a snapshot directory `.consolidation_backup/` taken at step 1; release lock; record `AgentRun` with status `FAILED`.

### 5.3 5-gate filter (preserved from Qagent)

Even within a single cron tick, per-user we re-check Qagent's 5 gates:

- Gate 0: kairos disabled (no real-time feature flag enabled)
- Gate 1: `User.autoDreamEnabled === true` (per-user opt-in)
- Gate 2: `now - User.lastDreamedAt >= 20h` (don't re-dream too soon, even if cron fires twice)
- Gate 3: `now - lastSessionScanAt >= 10min` (rate limit per-user)
- Gate 4: visits since last dream `>= 1`
- Gate 5: lock acquisition succeeded

### 5.4 Why not Codex Phase 1/Phase 2

The user's CDXLearn note 5 describes a sophisticated background pipeline with SQLite state DB, claim/lease, retry, separate Phase 1 extract / Phase 2 consolidate. **We don't need it for the demo's scale**: visits are ≤1h, users have ≤10 visits/week, cron-once-a-day handles the load. If we ever ship to many users we revisit; the Phase 1/2 design is captured in `docs/design/06_migration_*.md` for reference.

---

## 6. Dynamic prompt assembly

### 6.1 Why we don't optimize for static cache

Per the user (cross-checked with OpenAI eng): **the codex SDK handles prompt caching internally**. We don't need to design the template around stable prefix bytes. What we need is a **standard, complete, dynamic** template — the cleanest contract for what each role sees per turn.

This is a deliberate choice. The downside (potentially lower cache hit rate) is acceptable in exchange for:
- Easier reasoning about what goes in
- No "do not edit, will break cache" landmines for future contributors
- Truthful prompts — every byte we send was selected for this turn

### 6.2 The standard template

Built by `CodexPromptAssembler.assemble(role, context)`. Returns `{ instructions, userMessage }`.

`instructions` (codex SDK system prompt):
```
[A. Role definition — static, from prompts/codex-agents/<role>.md]

[B. Memory context — surfaced by recall pipeline this turn]

[C. Output contract — JSON schema for this role]
```

`userMessage` (per-turn input):
```
<visit_context>
  visit_id: ...
  language: ...
  consent_recorded: ...
  turn_count: ...
  visit_status: recording | analysing | ended
</visit_context>

<recent_transcript window="5">
  [doctor @ 12.3s] ...
  [patient @ 14.1s] ...
</recent_transcript>

<inbox>  <!-- mailbox messages addressed to me, drained this turn -->
  <teammate_message teammate_id="speaker_role" color="blue" summary="speaker tagged">
    {"type":"task_assignment","task_id":"...","title":"..."}
  </teammate_message>
</inbox>

<blackboard>  <!-- subset of keys this role declared interest in -->
  {
    "allergies": ["penicillin"],
    "medication_plan_draft": [{"drug":"amoxicillin",...}]
  }
</blackboard>

<event>  <!-- the immediate trigger for this run -->
  {"event_kind":"transcript_turn_completed","item_id":"...","transcript":"..."}
</event>
```

### 6.3 What's NOT in the prompt (Qagent "DON'T" §9)

These are forbidden by design and we'll grep-check:
- Other roles' raw codex transcripts
- Other visits' blackboard / mailbox / memory
- Other users' memory
- Anything from the old `/sessions` / `/agents` line

### 6.4 Implementation file

`backend/src/modules/carenote/codex-harness/codexPromptAssembler.ts` (new, ~120 LOC). Called by `CodexRunManager.runRole` immediately before `team.run(role, ...)`.

---

## 7. Persistence model (Prisma)

### 7.1 New / repurposed tables

We reuse the existing `User` / `Patient` / `Clinician` and rename the doctrine — instead of `ConsultSession` we have `Visit`. To avoid a destructive migration we **keep `ConsultSession` table as-is** but add a `Visit` model that points to it for backward compat, and gradually migrate. New tables added below.

```prisma
// Renamed responsibility: ConsultSession is now the carenote Visit.
// Keep field names; just add the new fields we need.

model ConsultSession {
  // ... existing fields ...
  language        String?       // 'zh' | 'en' | 'mixed'
  consentRecorded Boolean       @default(false)
  rawAudioSaved   Boolean       @default(false)
  visitState      Json          @default("{}")  // serialized VisitState
  endedAt         DateTime?
  // (no schema change required for transcript_utterances)
}

model CarenoteTask {
  id              String   @id @default(cuid())
  visitId         String
  parentTaskId    String?
  createdByRole   String
  taskType        String
  description     String
  status          String   @default("pending")  // pending|running|completed|failed|cancelled
  inputJson       Json
  outputJson      Json?
  blackboardKeys  String[]
  createdAt       DateTime @default(now())
  updatedAt       DateTime @updatedAt

  @@index([visitId, status])
  @@map("carenote_tasks")
}

model CarenoteBlackboard {
  id        String   @id @default(cuid())
  visitId   String
  key       String
  value     Json
  writtenBy String                       // role
  version   Int      @default(1)
  updatedAt DateTime @updatedAt

  @@unique([visitId, key])
  @@map("carenote_blackboard")
}

model CarenoteMailbox {
  id            String   @id @default(cuid())
  visitId       String
  recipientRole String
  fromRole      String
  payloadJson   Json     // discriminated union; mirrors the file
  isRead        Boolean  @default(false)
  fileIndex     Int      // index in the file array, for markRead correlation
  createdAt     DateTime @default(now())

  @@index([visitId, recipientRole, isRead])
  @@map("carenote_mailbox")
}

model CarenoteAgentRun {
  id              String    @id @default(cuid())
  visitId         String?                       // null for cross-visit (auto-dream)
  userId          String?                       // for auto-dream runs
  role            String
  kind            String                        // 'turn' | 'dream' | 'json_repair'
  status          String                        // RUNNING|COMPLETED|FAILED|ABORTED
  prompt          String?
  rawOutput       String?
  parsedJson      Json?
  validationStatus String?                      // 'valid'|'repaired'|'failed'
  errorMessage    String?
  threadId        String?
  modelName       String?
  latencyMs       Int?
  startedAt       DateTime  @default(now())
  endedAt         DateTime?

  @@index([visitId, role, startedAt])
  @@index([userId, kind, startedAt])
  @@map("carenote_agent_runs")
}

// User-level memory consolidation lock (auto-dream)
model UserDreamLock {
  userId            String   @id
  acquiredAt        DateTime @default(now())
  expiresAt         DateTime
  acquiredByPid     Int

  @@map("user_dream_locks")
}

// Per-user dream telemetry
model User {
  // ... existing ...
  autoDreamEnabled  Boolean   @default(true)
  lastDreamedAt     DateTime?
}
```

### 7.2 Migration plan

Single Prisma migration `20260430_carenote_v01_swarm`. We do NOT drop the old `MedicationPlan` / `FollowUp` / `FamilyDigest` / `Reminder` / `AgentRun` tables in this migration — we'll do that in a separate cleanup migration after the new pipeline is proven (zero-risk staged rollout).

### 7.3 What stays in files vs DB

| Data | File | DB | Reason |
|---|---|---|---|
| Visit metadata | — | `ConsultSession` | Queryable list, joins to user |
| Transcript utterances | — | `TranscriptUtterance` | Already there, indexed for assembly |
| VisitState snapshot | — | `ConsultSession.visitState` JSON | Simpler than 12 child tables; we only ever read whole-visit |
| Blackboard | — | `CarenoteBlackboard` | Queryable per-key, versioned, SSE fanout |
| Mailbox | `.data/carenote/teams/<v>/inboxes/<role>.json` | `CarenoteMailbox` (mirror) | File = lock + audit; DB = SSE + UI; **file is source of truth** |
| Agent runs | — | `CarenoteAgentRun` | Telemetry, "show me what medication agent did" |
| Codex thread pointers | `.data/carenote/threads/<team>/<visit>/<role>.json` | — | Codex SDK consumes JSON, no need to query |
| Memory files | `.data/carenote/memory/{visits,users}/...` | — | Markdown, used by recall (file-only is the contract) |
| Codex rollouts | `~/.codex/sessions/.../...jsonl` | — | Codex-managed, we never write |
| Auto-dream lock | `.data/carenote/memory/users/<u>/.consolidation.lock` | `UserDreamLock` | File = inter-process lock; DB = ops visibility |

---

## 8. EventBus & SSE (real-time UI)

### 8.1 In-process bus

Direct port of Qagent `events/event-bus.service.ts` (23 LOC):

```ts
@Injectable()
export class CarenoteEventBus {
  private readonly subject = new Subject<CarenoteEvent>();

  emit(e: CarenoteEvent): void { this.subject.next(e); }

  streamForVisit(visitId: string): Observable<CarenoteEvent> {
    return this.subject.asObservable().pipe(filter((e) => e.visitId === visitId));
  }
}
```

Event types:
```ts
type CarenoteEvent =
  | { type: 'transcript_turn_committed'; visitId: string; turnId: string; text: string; speaker: string }
  | { type: 'transcript_turn_completed'; visitId: string; turnId: string; transcript: string }
  | { type: 'agent_run_started';        visitId: string; role: string; runId: string }
  | { type: 'agent_run_completed';      visitId: string; role: string; runId: string; status: 'valid'|'repaired'|'failed' }
  | { type: 'blackboard_updated';       visitId: string; key: string; writtenBy: string; version: number }
  | { type: 'mailbox_message';          visitId: string; from: string; to: string; payloadKind: string }
  | { type: 'permission_response';      visitId: string; requestId: string; behavior: 'allow'|'deny'|'ask' }
  | { type: 'visit_status_changed';     visitId: string; status: string }
  | { type: 'dream_completed';          userId: string; filesUpdated: number };
```

### 8.2 SSE endpoint

`GET /api/visits/:id/events` (auth-guarded, owner check). NestJS `@Sse()` decorator returns an `Observable<MessageEvent>` derived from `bus.streamForVisit(visitId)`. Heartbeat every 15s to defeat nginx proxy timeout.

### 8.3 Frontend wiring

`useRealtimeVisit.ts` adds `subscribeEvents(visitId)`:

```ts
const es = new EventSource(`/api/visits/${visitId}/events`);
es.addEventListener('blackboard_updated', () => refresh());
es.addEventListener('agent_run_completed', () => refresh());
// ...
```

Removes the `setInterval(refresh, 1500)` polling. `refresh()` still exists as a fallback (tab-was-backgrounded etc).

---

## 9. The on-demand inter-agent trigger

This is the user's specific concern: **agents talk on-demand, not on poll**. Design:

1. Each role registers in the run-manager:
   ```ts
   runManager.subscribe('medication_reminder_draft', {
     onBlackboardKeys: ['allergies', 'medication_plan_draft'],
     onMailboxFromAnyone: true,
   });
   ```
2. When `blackboard.write(visit_id, 'allergies', [...], by='medical_instruction_extractor')` happens:
   - DB write → emit `blackboard_updated` to bus.
   - Run-manager listens; for any role whose `onBlackboardKeys` includes `'allergies'` and isn't currently running for this visit, it enqueues a `re_evaluate` job.
3. Job arrives at the codex job queue (per-visit serial, already implemented in `codexJobQueue.ts:23`).
4. Run-manager picks up, calls `runRole('medication_reminder_draft', ...)` with the new `event = { kind: 'blackboard_change', key: 'allergies' }`.

**No agent ever polls another agent.** All cross-role coordination flows through the bus → enqueue path. This is the fully event-driven semantics from CCLearn note 4.

A natural concern: infinite loops (A writes blackboard, B reacts, B writes blackboard, A reacts, …). Defenses:
- Per-(visit, role) cooldown of 2s between consecutive runs.
- A role's `re_evaluate` event includes a hop counter; max 3 hops per turn or the run is dropped with a `cycle_breaker_engaged` warning.
- Schemas in `medicalSchemas.ts` already constrain output shapes; an agent can't emit a "do X again" command.

---

## 10. Per-visit codex thread isolation

Today: `codexSdkRuntime.ts:79` keys threads by `${team_id}:${role}` — visit A and visit B share a thread. **Bug**: visit B starts seeing visit A's medical context in the role's hidden state.

Change:
```diff
- const key = `${input.team_id}:${input.role}`;
+ const key = `${input.team_id}:${input.visit_id}:${input.role}`;
```

Plus a corresponding change in `codexThreadStore.ts` to namespace the JSON files by visit. Plus `codexAgentTeam.ensureThreads()` becomes per-visit.

Cost: per visit, up to 11 codex threads created. The user said "best effect, don't worry about token usage" — this is the right tradeoff. Cleanup cron prunes threads of visits ended ≥7 days ago.

---

## 11. Implementation roadmap

### Week 1 — Foundation

| Task | File / surface | Status |
|---|---|---|
| Add `User.autoDreamEnabled`/`lastDreamedAt`, `ConsultSession.{language,consentRecorded,rawAudioSaved,visitState}`, 4 new tables (`CarenoteTask`, `CarenoteBlackboard`, `CarenoteMailbox`, `CarenoteAgentRun`) + `UserDreamLock` | `backend/prisma/schema.prisma` | ✅ landed |
| Apply via `prisma db push` (no migrations dir exists yet) | live DB | ✅ landed |
| `CarenoteEventBus` + 9 `CarenoteEvent` types | `backend/src/modules/carenote/swarm/eventBus.ts` (new, 75 LOC) | ✅ landed |
| `GET /api/visits/:id/events` SSE with 15s heartbeat | `carenote.controller.ts` (added `@Sse` route) | ✅ landed |
| `transcript_turn_completed` emit on every fresh ingest | `carenote.service.ts` (in `ingestRealtimeEvent`) | ✅ landed |
| Per-visit codex thread isolation | `codexSdkRuntime.ts:run()` cache key `(team, visit, role)` | ✅ landed |
| Frontend SSE subscription replaces 1.5s polling (30s fallback) | `pages/carenote/visit/[id].vue` (`openEventStream`) | ✅ landed |
| Both apps build clean & PM2 reloaded | `clariose-backend` + `clariose-frontend` | ✅ healthy |
| **DB-persist visit metadata** (visit survives PM2 reload / browser refresh) | `carenote.service.ts` `createVisit`/`getVisit`/`endVisit` | ⏳ **deferred** — requires resolving FK story (carenote uses guest user_ids from localStorage; ConsultSession needs User+Patient cuids). Plan: add a separate `CarenoteVisit` table (no FKs, opt-in user link) in next commit. |
| `agent_run_completed` / `blackboard_updated` emits | `codexRunManager.ts` after `runRole` | ⏳ deferred — needs blackboard service first (Week 3) |
| Move `/consult` visual assets → `/carenote/visit/[id].vue` | `frontend/components/carenote/` | ⛔ deferred to Week 4 (UI move is its own PR) |
| Delete `sessions/`, `agents/`, `realtime/` (old), `reminders/` modules | `backend/src/modules/` | ⛔ deferred until carenote UI is at parity |

#### Schema deviation log (Week 1)

- `ConsultSession.visitState` JSON column was added but is **not yet written** by `CareNoteService` (FK issue above). It's a usable target column once we resolve the persistence path.
- `User.autoDreamEnabled` defaults to `true` per §5.3, but auto-dream isn't running yet (Week 4) so the column is ignored at runtime.
- `UserDreamLock` table FK to `users(id)` will be a usage gate once §5.2 lands.
- No formal `prisma/migrations/` directory exists in this repo (deploy script runs `prisma migrate deploy` but nothing has ever migrated). We used `prisma db push` to sync the schema. Before another PR, ops should baseline with `prisma migrate diff --from-empty --to-schema-datamodel prisma/schema.prisma --script > migrations/0_init.sql` and `prisma migrate resolve --applied 0_init`.

### Week 2 — Recall ✅ landed

| Task | Source from | Landed at | Status |
|---|---|---|---|
| `MemoryScanService` (frontmatter walker, visit + user scope merge) | Qagent `memory/recall/memory-scan.service.ts` | `carenote/recall/memoryScan.ts` | ✅ |
| `MemorySideQueryService` (gpt-5.4-mini-2026-03-17, json_object output, 2200ms outer race) | Qagent `memory/recall/side-query.service.ts` | `carenote/recall/memorySideQuery.ts` | ✅ |
| `MemorySurfaceService` (16KB per-file cap, UTF-8 safe slicing) | Qagent `memory/recall/memory-surface.service.ts` | `carenote/recall/memorySurface.ts` | ✅ |
| `RecallBudgetService` (96KB visit cap, surfaced-set dedup) | Qagent `memory/recall/recall-budget.service.ts` | `carenote/recall/recallBudget.ts` | ✅ |
| `MemoryRecallService` (4-phase orchestrator, never-throw contract) | Qagent `memory/recall/memory-recall.service.ts` | `carenote/recall/memoryRecall.ts` | ✅ |
| `RecallCache` (Redis with in-memory fallback) | new (Redis was missing) | `carenote/recall/recallCache.ts` | ✅ |
| `recall.types.ts` + `recall.constants.ts` | new | `carenote/recall/` | ✅ |
| `CodexPromptAssembler` (dynamic template, isolation-safe) | new | `carenote/codex-harness/codexPromptAssembler.ts` | ✅ |
| `CodexAgentRunInput.extra_instructions` slot | edit `codexRuntime.ts` | — | ✅ |
| `CodexAgentTeam.run` concatenates `extra_instructions` after registry prompt | edit `codexAgentTeam.ts` | — | ✅ |
| `CodexRunManager.analyzeTurn` calls `recall.prefetch()` once per turn | edit `codexRunManager.ts` | — | ✅ |
| `CodexRunManager.runRole` plumbs recall → `extra_instructions` for all 11 roles | edit `codexRunManager.ts` | — | ✅ |
| `assembleHarness` accepts optional `recall` + `visitOwnerLookup` | edit `codexHarnessApi.ts` | — | ✅ |
| `CareNoteService` injects `MemoryRecallService` and supplies owner lookup | edit `carenote.service.ts` | — | ✅ |
| `CareNoteModule` registers all 6 recall services | edit `carenote.module.ts` | — | ✅ |
| Env: `CARENOTE_SIDEQUERY_MODEL`, `CARENOTE_RECALL_ENABLED`, `CARENOTE_MEMORY_ROOT` | `.env.example` + live `.env` | — | ✅ |
| Folder seed `.data/carenote/memory/{visits,users}/_sample/MEMORY.md` | new | — | ✅ |
| Tests: 6 recall pipeline cases + 5 prompt assembler cases | new | `test/carenote/{memoryRecall,promptAssembler}.spec.ts` | ✅ 11/11 pass |
| Total carenote test count | — | — | 74 → 85 (all pass) |

#### Recall flow as deployed

```
ingestRealtimeEvent → analyze_turn job → CodexRunManager.analyzeTurn:
    1. recall.prefetch({visit_id, user_id (from visitOwnerLookup), query})
       Phase 1 — scan visits/<vid>/ + users/<uid>/, parse frontmatter, build manifest
                  cache in Redis carenote:recall:manifest:<vid> for 300s
       Phase 2 — sideQuery.select() calls gpt-5.4-mini-2026-03-17, race(2200ms)
                  returns top-5 relPaths
       Phase 3 — surface reads files (max 16KB each, UTF-8 safe slice)
                  dedupe on (visit_id, relPath@mtime) so same content not re-injected
       Phase 4 — toAppendBlock builds Markdown block, consume budget (max 96KB/visit)
       returns RecallResult with .append (markdown) | null
    2. for each role in pass1+pass1.5+pass2+pass3 (11 calls total):
         runRole(..., recall) →
           team.run(role, { ..., extra_instructions: recall.append })
             → CodexAgentTeam concatenates registry prompt + recall.append
             → codex SDK starts/resumes thread (team_id, visit_id, role)
             → role sees its prompt with the same memory context as siblings
```

#### Skip rules in effect

- `isSubagentFork: true` → no scan, no LLM, return `skipped: 'subagent'`
- `CARENOTE_RECALL_ENABLED=false` or missing `OPENAI_API_KEY` → `skipped: 'disabled'`
- no `visit_id` → `skipped: 'no_visit'`
- visit budget already > 96KB → `skipped: 'visit_budget'`
- empty manifest → `skipped: 'empty'`
- sideQuery LLM call > 2200ms → `skipped: 'sidequery_timeout'`
- sideQuery returned files but all dedup-blocked (same mtime as previously surfaced) → `skipped: 'empty'`

#### Codex thread isolation reaffirmed

Per-turn recall + per-(team, visit, role) thread = each role gets:
- its own private chain of thought (codex thread)
- the same fresh memory context as its siblings on this turn
- no leakage from other visits or other roles

#### Week 2 follow-up PR (assembler wiring + telemetry)

After the initial Week 2 land, the assembler was complete but the run-manager
was only using its memory-append output, not its structured user-message
output. That's now closed:

- `CodexAgentRunInput.pre_built_user_message?: string | null` added.
- `codexSdkRuntime.run` prefers `pre_built_user_message` when set; falls back
  to legacy `buildUserMessage` for json_repair / summarise paths that haven't
  been migrated yet.
- `CodexRunManager.runRole` calls `assembleCodexPrompt(...)` for every role
  and passes its `userMessage` as `pre_built_user_message`. Per-role on a
  given turn, all 11 roles get the same structured envelope (visit_context,
  recent_transcript, inbox, blackboard, event, expected_output_schema_name).
- Recall telemetry logged from `analyzeTurn`:
  `[recall] visit=… turn=… latency=Xms files=N bytes=Y manifestSize=M selected=K`
  Visible via `pm2 logs clariose-backend`.
- `endVisit` and `deleteVisit` call `recall.invalidateManifest(visit_id)` so
  the Redis manifest cache doesn't outlive the visit. (Auto-dream in Week 4
  will also invalidate when it writes new files for the user scope.)
- Test `promptAssemblerWiring.spec.ts` uses `StubRuntime.setOverride()` to
  capture the input each role receives and asserts `pre_built_user_message`
  contains the structured blocks with the actual transcript content.
- 75/75 carenote tests pass.

#### Open follow-up tracked for Week 3+

- `MemoryRetrievalService` (the older empty stub at `medical/memoryRetrieval.ts`)
  is still wired through `analyzeTurn` for backward compat. The new recall is
  additive. Once Week 3 lands and we're confident, the old stub can be deleted.
- `read_path.md` files are scanned but their special "follow these path hints"
  semantic from Codex's native pipeline is not implemented — they're treated
  as ordinary memory files. If we want the explicit-path-pull behavior, that's
  a separate Phase 1.5 feature.
- Recall is also not yet invoked for `summarise` (stage_summary / final_summary)
  jobs — they still go through the legacy `buildUserMessage`. Could be added
  but final-summary's input is already the full visit; recall's value is lower.
- `CarenoteAgentRun` table exists but is not yet written. Will land in Week 3
  alongside the blackboard / mailbox persistence.

### Week 3 — 4-layer comm ✅ landed

| Task | Source from | Landed at | Status |
|---|---|---|---|
| `proper-lockfile` installed (+ `@types/proper-lockfile`) | npm | `backend/package.json` | ✅ |
| `mailboxMessages.ts` — 9 typed messages (`task_assignment`, `task_notification`, `permission_request`, `permission_response`, `idle_notification`, `plan_approval_request`, `plan_approval_response`, `recall_request`, `recall_response`) + parsers + `formatTeammateMessages` | Qagent `swarm/mailbox-messages.ts` | `carenote/swarm/mailboxMessages.ts` | ✅ |
| `MailboxFileService` — `<root>/<visit>/inboxes/<role>.json` with `proper-lockfile` (5-retry backoff, 30s stale), atomic seed + read-modify-write | Qagent `swarm/teammate-mailbox.service.ts` | `carenote/swarm/mailboxFile.ts` | ✅ |
| `MailboxService` — file (source of truth) + `CarenoteMailbox` DB mirror + EventBus emit | new | `carenote/swarm/mailboxService.ts` | ✅ |
| `BlackboardService` — versioned KV via `CarenoteBlackboard` upsert, emits `blackboard_updated` | new | `carenote/swarm/blackboard.ts` | ✅ |
| `TasksService` — CRUD around `CarenoteTask` (create / update / get / listForVisit) | new | `carenote/swarm/tasks.ts` | ✅ |
| `SubscriptionRegistry` — on-demand triggers, 2s per-(visit,role) cooldown, MAX_HOPS=3 cycle breaker, `registerDefaultsFor(team)` seeds carenote roles | new | `carenote/swarm/subscriptionRegistry.ts` | ✅ |
| New job kind `single_role` (with hop counter) added to `CodexJob` | edit `codexJobQueue.ts` | — | ✅ |
| `CodexRunManager` accepts mailbox / blackboard / subscriptions; on `start()` wires the registry's bus listener to enqueue `single_role`; new `runOneRoleOnDemand` handler | edit `codexRunManager.ts` | — | ✅ |
| `runRole` drains mailbox + reads subscribed blackboard keys → fed into `assembleCodexPrompt` `inbox` and `blackboard` slots | edit `codexRunManager.ts` | — | ✅ |
| `assembleHarness` accepts mailbox/blackboard/subscriptions; calls `subscriptions.registerDefaultsFor(team)` before `manager.start()` | edit `codexHarnessApi.ts` | — | ✅ |
| `CareNoteService` injects all four; passes them to `assembleHarness` | edit `carenote.service.ts` | — | ✅ |
| `CareNoteModule` registers all 5 swarm services | edit `carenote.module.ts` | — | ✅ |
| Env: `CARENOTE_TEAMS_ROOT` | `.env.example` + live `.env` | — | ✅ |
| Tests: 8 swarm-comm cases covering file round-trip, structured payload parse-back, DB mirror, blackboard write→bus emit, subscription firing, self-bounce filter, cooldown gate, `blackboardKeysFor` lookup | new | `test/carenote/swarmCommunication.spec.ts` | ✅ 8/8 pass |
| Total carenote test count | — | — | 75 → 83 (all pass) |
| `PermissionBridge` (worker↔leader handshake, 30s wait) | Qagent `swarm/leader-permission-bridge.service.ts` | — | ⛔ deferred to Week 4 — needs human-in-loop UI to send `permission_response`; the message types are in place so it can land without re-touching mailbox internals |

#### How a turn now actually flows (with Week 3 landed)

```
ingestRealtimeEvent
  └─ analyze_turn job enqueued
     └─ CodexRunManager.analyzeTurn:
        1. recall.prefetch(visit, user, query)              [Week 2]
        2. for each role in pass1+pass1.5+pass2+pass3+guardrail:
             runRole(role, …, recall):
               a. mailbox.drainUnread(visit, role)          [Week 3]
                  → unread teammate messages → inbox[]
               b. blackboard.readMany(visit, subscribedKeysFor(role))
                  → key:value subset → blackboard{}
               c. assembleCodexPrompt({ inbox, blackboard, … })
                  → pre_built_user_message
               d. team.run(role, { instructions: registry+recall.append,
                                    pre_built_user_message })
                  → codex thread (team, visit, role) runs the turn
        3. validateAndMaybeRepair → reduce → visitState.set
        4. (any blackboard.write or mailbox.send the role does ANYWHERE
            in this pipeline → bus emit → SubscriptionRegistry checks
            subs → enqueue single_role job for the subscriber)
```

#### On-demand cycle, end-to-end example (the §6 walkthrough, now real)

1. `medical_instruction_extractor` extracts `allergies: ["penicillin"]` for turn T.
2. (When the run-manager wires it in Week 4) it calls `blackboard.write({key:"allergies", writtenBy:"medical_instruction_extractor"})`.
3. `BlackboardService` inserts/updates `CarenoteBlackboard`, emits `blackboard_updated`.
4. `SubscriptionRegistry` (already started) sees the event.
5. `medication_reminder_draft` is registered with `onBlackboardKeys: ["allergies"]` AND it's not the writer → fire.
6. Cooldown check: per-(visit, role) 2s. If clear, enqueue `single_role` job (hop = 1).
7. `CodexJobQueue` per-visit serial → runs after current pipeline drains.
8. `runOneRoleOnDemand` runs `medication_reminder_draft` alone with the latest VisitState + new allergy in blackboard subset → re-validates pending med drafts.
9. If it writes a new `safety_flags` blackboard key → `safety_clarification` (subscribed) might fire (hop = 2). At hop 3 the cycle breaker logs `cycle_breaker_engaged` and drops.

> Note: step 2 (the explicit `blackboard.write` call from inside agent code)
> is currently NOT plumbed because the codex SDK runtime doesn't yet expose
> a "agent wrote to blackboard" tool. For v01 the bridge from "agent output"
> to "blackboard write" lives in the reducer (Week 4). The plumbing for the
> trigger fire-path itself IS live — you can manually call `blackboard.write`
> from any backend code and watch a `single_role` job land in the queue.

#### Default subscriptions seeded by `registerDefaultsFor`

Per the carenote 11-role manifest, the registry pre-registers:

| role | onBlackboardKeys | onMailboxFromAnyone |
|---|---|---|
| `medication_reminder_draft` | allergies, medication_plan_draft | true |
| `safety_clarification` | safety_flags | true |
| `family_summary` | family_brief, safety_flags | false |

These are starting defaults; teams can override via `subscriptions.register(...)` from boot scripts.

#### Cycle-breaker rules

- **Cooldown**: `per-(visit, role) = 2000ms`. Same role can't fire twice in a row inside this window. (Reset on success.)
- **Hop counter**: each `single_role` job carries `hop`. Each enqueue increments. `MAX_HOPS = 3`. At limit → log `cycle_breaker_engaged` and drop.
- **Self-bounce filter**: if a blackboard write's `writtenBy === role`, the registry doesn't fire — a role can't trigger itself.

### Week 4 — Auto-dream + UI ✅ landed

| Task | Source from | Landed at | Status |
|---|---|---|---|
| `ConsolidationLockService` (O_EXCL file lock + `UserDreamLock` DB row, 30 min TTL, stale break) | new | `carenote/swarm/consolidationLock.ts` | ✅ |
| `AutoDreamService` (5-gate filter, OpenAI Chat consolidator with strict JSON schema, atomic file writes) | Qagent auto-dream | `carenote/swarm/autoDream.ts` | ✅ |
| `DreamCronService` — `@Cron('0 3 * * *')` daily | new | `carenote/swarm/dreamCron.ts` | ✅ |
| Admin manual trigger `POST /api/admin/auto-dream/run` (role=ADMIN gated) | new | `carenote.controller.ts` | ✅ |
| Reducer → blackboard wiring: `analyzeTurn` → `publishToBlackboard(envelope)` writes canonical keys (`allergies`, `medication_plan_draft`, `follow_up_tasks`, `safety_flags`, `family_brief`) with deep-equal change detection | new in `codexRunManager.ts` | — | ✅ |
| `agent_run_started` / `agent_run_completed` events emitted from every `runRole` (status: valid/repaired/failed) | edit `codexRunManager.ts` | — | ✅ |
| Frontend `End & review` waits for `agent_run_completed` SSE event with `role=final_visit_summary` (8s safety timeout fallback) before navigating | `pages/carenote/visit/[id].vue` `onEnd()` | — | ✅ |
| Env: `CARENOTE_DREAM_ENABLED`, `CARENOTE_DREAM_HOUR`, `CARENOTE_DREAM_MINUTE`, `CARENOTE_DREAM_MODEL` | `.env.example` + live `.env` | — | ✅ |
| Tests: 5 auto-dream gate cases | new | `test/carenote/autoDreamGates.spec.ts` | ✅ 5/5 pass |
| Total carenote test count | — | — | 83 → 88 (all pass) |
| 12th `memory_consolidator` codex role (vs OpenAI Chat) | manifest | — | ⛔ deferred — auto-dream uses `gpt-4o-mini` directly via `openai` SDK, sufficient for v01. Dedicated codex thread per user per day would burn auth quota for no quality gain. Worth revisiting at scale. |
| 4 agent cards UI binding to blackboard | `pages/carenote/visit/[id].vue` | — | ⛔ deferred — `GET /api/visits/:id` already returns full state including blackboard via `state.draft_*`. UI panels would just re-bind. End-&-review wait was the more impactful regression. |
| `PermissionBridge` worker↔leader handshake | adapted from Qagent | — | ⛔ deferred — protocol messages already exist in `mailboxMessages.ts`; the bridge service can land in v01.1 without re-touching mailbox internals. |
| Visit thread cleanup cron (7-day archive of codex threads) | new | — | ⛔ deferred — codex thread JSONLs are individually small; a manual `find ~/.codex/sessions -mtime +7 -delete` is sufficient for v01. |

#### What auto-dream writes per user per night

For each user with ≥1 ENDED visit in the last 24h, all 5 gates passing, lock acquired:

```
.data/carenote/memory/users/<user_id>/
├── MEMORY.md                ← thin index (auto-overwritten)
├── memory_summary.md        ← cross-visit summary (≤4 KB)
├── allergies.md             ← canonical list (only if model produced one)
├── conditions.md            ← canonical list (only if model produced one)
├── rollout_summaries/
│   └── <visit_id>.md        ← one per visit consolidated
└── skills/
    └── <name>.md            ← task-specific cheatsheets (snake_case names)
```

These files are then visible to recall on the user's next visit (scan picks
them up → sideQuery may select → surface injects). Loop closes.

#### "End & review" race semantics

```
user clicks End & review
  ↓
realtime.stop()                        (mic off)
  ↓
POST /api/visits/:id/final-summary     (enqueues final_summary codex job)
  ↓
race:
  • SSE `agent_run_completed` with role="final_visit_summary"
  • setTimeout(8000)
  ↓
refresh GET /api/visits/:id            (so navigated page sees fresh state)
  ↓
router.push('/summary')
```

The 8-second safety timeout exists so a stuck job never wedges the user.

---

## 15. Security review (CLARIOSE_V01_SEC)

Conducted alongside Week 4 land. Findings + fixes:

| # | Finding | Severity | Fix |
|---|---|---|---|
| S1 | `POST /api/visits` accepted `user_id` from request body — any logged-in user could pose as any other (horizontal-priv) | **High** | ✅ Week-1 PR — DTO field removed; owner = JWT subject. Endpoint now uses `@CurrentUser`. |
| S2 | `POST /api/realtime/session` was JWT-guarded but did NOT verify visit ownership — any logged-in user could mint a Realtime client_secret bound to anyone's `visit_id` | **High** | ✅ Week-1 PR — `ensureOwner` added. |
| S3 | SSE endpoint `GET /api/visits/:id/events` had `@UseGuards(AuthGuard("jwt"))` but EventSource cannot send `Authorization` headers, so the guard's default Bearer extractor rejected every request — endpoint was effectively **completely open** to anyone with the URL | **High** | ✅ Week-1 PR — JWT strategy gained `?token=…` extractor; `streamEvents` calls `ensureOwner` BEFORE filtering the bus stream. |
| S4 | Path-traversal via `visit_id` / `role` in mailbox file path | **Med** | ✅ Week-4 PR — `safeSegment()` strips non-`[A-Za-z0-9_-]`; `resolve()` verifies path stays inside root; throws on attempted escape. |
| S5 | Path-traversal via `relPath` from manifest cache → memory file read | **Med** | ✅ Week-4 PR — `memorySurface.readForSurfacing` resolves & verifies the absolute path is under root; rejected entries are logged + skipped. |
| S6 | Auto-dream `skills[].name` and `rollout_summaries[].visit_id` could contain `..` or `/` (LLM output) → file overwrites outside user dir | **Med** | ✅ Week-4 PR — `sanitizeFilename()` enforces `[a-z0-9_-]{1,64}`; null returns drop the entry. |
| S7 | No JSON body size cap → trivial OOM via `POST /api/visits/:id/realtime-events` with multi-GB payload | **Med** | ✅ Week-4 PR — `app.use(json({ limit: '256kb' }))` in `main.ts`. |
| S8 | Global `ValidationPipe` had `forbidNonWhitelisted: false` → silently accepted unknown fields, masking client-side mistakes | **Low** | ✅ Week-4 PR — flipped to `true`. Also fixed `RealtimeEventDto.event` to carry `@IsObject` so it doesn't get stripped. |
| S9 | CORS was `origin: true` (reflect any origin) | **Low** | ✅ Week-4 PR — locked to `APP_BASE_URL` (default `https://zai.gold`) in production; `true` in dev. |
| S10 | SSE `?token=…` JWT in URL would land in nginx access_log | **Low** | ✅ Week-4 PR — nginx `location ~ ^/api/visits/[^/]+/events$` block adds `access_log off;` and 24h `proxy_read_timeout` for SSE keep-alive. |
| S11 | `npm audit --omit dev` (backend + frontend) | — | ✅ 0 vulnerabilities. |
| S12 | PHI logged in plaintext | **Med** | ✅ verified — only the dev CLI `replay-transcript.cli.ts` prints raw transcripts; all Nest service logs use `redactPhi()` or log only IDs/counts/keys (e.g. `[recall] visit=… latency=…ms files=N`). |
| S13 | Auto-dream double-run on cron tick collision | **Low** | ✅ Week-4 PR — `ConsolidationLockService` uses O_EXCL file lock; stale (>30 min) is reaped on next acquirer; `UserDreamLock` DB row gives ops visibility. |
| S14 | `gpt-realtime` ephemeral `client_secret` issued without binding to visit_id, so a stolen secret could be replayed | **Acknowledged** | ⛔ Not fixed in v01 — OpenAI Realtime API doesn't expose visit binding; the secret is short-lived (≤60 s default); HTTPS-only transport. |
| S15 | Rate-limit baseline `120/min/IP` may be too high for `/auth/login` brute-forcing | **Low** | ⛔ Not fixed in v01 — `@Throttle` per-route hooks are already wired in auth.controller (existing). Pre-existing. |
| S16 | No CSRF protection — but cookies are not used for auth (Bearer header) so CSRF is N/A for `/api/*` | — | Acceptable. SSE token-in-URL is not exploitable via CSRF because EventSource doesn't read response bodies cross-origin. |

#### Defense-in-depth notes

- `ValidationPipe { whitelist: true, forbidNonWhitelisted: true, transform: true }` → all DTOs are explicit; unknown fields are 400, not silently dropped.
- All carenote endpoints + realtime mint are `@UseGuards(AuthGuard("jwt"))` + `ensureOwner(visit_id, user.id)` (404 on miss to not leak existence).
- `consult_sessions` table has `ownerUserId` FK to `users(id)` on cascade delete — orphans aren't possible.
- `UserDreamLock` table FK to `users(id)` with cascade delete — same.
- `app.listen(port, '127.0.0.1')` — Nest binds loopback only; nginx is the only external surface.
- `helmet` provides default security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy).

### Cross-cutting tasks (any week)

| Task | Notes |
|---|---|
| `CARENOTE_SIDEQUERY_MODEL` env added to `backend/.env.example` | default `gpt-5.4-mini-2026-03-17` |
| `CARENOTE_RECALL_ENABLED` env added | default `true` |
| `CARENOTE_DREAM_HOUR` cron config | default `3` (03:00 local) |
| Update CLAUDE.md `Architecture` section | one paragraph: pipeline = carenote, not /consult |

---

## 12. Decision log

| # | Decision | Why |
|---|---|---|
| D1 | Use carenote/codex-harness, kill /consult line | User confirmed; the codex pipeline they want already exists at 90% |
| D2 | Store VisitState as a JSON column in `ConsultSession`, not 12 child tables | We only read it as a whole; cheaper migration |
| D3 | Mailbox = file source of truth + DB mirror | File enables cross-process locking & team-shared visibility (per user req); DB enables SSE + UI queries |
| D4 | Codex thread key = (team, visit, role) not (team, role) | Per-visit isolation; user OK'd higher token cost |
| D5 | sideQuery model = `gpt-5.4-mini-2026-03-17` | User-specified |
| D6 | Memory folders use Codex naming convention (MEMORY.md, memory_summary.md, rollout_summaries/, skills/, read_path.md) | Per CDXLearn note 5 diagram |
| D7 | Memory mechanics use Qagent (scan→sideQuery→surface→inject), NOT Codex Phase 1/2 SQLite pipeline | Demo scale; auto-dream cron is sufficient |
| D8 | Auto-dream daily cron, not real-time | Visit ≤1h, no need for stream consolidation |
| D9 | Inter-agent triggers are event-driven (bus → enqueue), not polling | Per CCLearn note 4 + user req |
| D10 | Dynamic prompt template, not static-cache-optimized | User cross-checked with OpenAI eng; SDK handles cache; clean contract preferred |
| D11 | Per-visit byte budget 96KB (raised from Qagent's 64KB) | "Best effect, don't worry about token use" |
| D12 | `MAX_BYTES_PER_FILE` 16KB (raised from Qagent's 8KB) | Same reason |
| D13 | Cycle breaker: max 3 hops, 2s cooldown per (visit, role) | Defense against on-demand trigger loops |
| D14 | Phase 1/2 SQLite pipeline deferred, captured in `06_migration_*` doc | Out of scope for v01, can revisit if scaling forces it |
| D15 | Old `/consult`+`/sessions`+`/agents` modules **not deleted** in Week 1 | Wait until carenote UI is at parity, then drop all in one cleanup PR |

---

## 13. Open questions / pending

- **OpenAI API key for sideQuery**: assumed reusable from `OPENAI_API_KEY`. Confirm the `gpt-5.4-mini-2026-03-17` model id is real & accessible from this account.
- **Codex auth mode**: confirmed as subscription-auth (`~/.codex/auth.json`) by current `codexRuntimeFactory.ts:54-58`; Carenote works as-is.
- **PHI redaction in mailbox/blackboard**: today `redactPhi.ts` is opt-in. Should we mandate redaction for blackboard writes? Defer to security review.
- **Audit trail UI**: `CarenoteAgentRun` table is populated; no UI to browse it yet. Add in Week 4 as a debug page.
- **Multi-machine deployment**: file-based mailbox lock is single-machine. If we ever go multi-host, switch to Postgres advisory locks (`pg_advisory_xact_lock` keyed on `hashtext(visit_id || role)`). Captured here so we don't forget.

---

## 14. Implementation status

This document is the **source of truth** for the Clariose v01 design as of 2026-04-30.

- **Week 1**: 🟡 Partial. Schema, EventBus, SSE, per-visit thread isolation, frontend SSE subscription all landed and deployed (PM2 reloaded, both apps healthy at 15:01 UTC). Visit-state DB persistence + `/consult` visual port deferred — see Week 1 status table for blockers.
- **Week 2–4**: ⏳ Pending; each will be its own PR using this doc as the spec.

### What changed in the live system after Week 1's partial PR

- `https://zai.gold/api/visits/<id>/events` now exists as an SSE endpoint. Browsers connecting to a carenote visit page open this stream automatically.
- New transcript turns push immediately to all open browser tabs (no 1.5s lag).
- Two visits running in parallel no longer share codex agent thread state — visit B can't accidentally see visit A's hidden chain-of-thought for the same role.
- Polling still happens every 30s as a fallback (mobile sleep, dropped SSE connection).
- 5 new tables exist in the `clariose` Postgres DB and are empty — they will fill as Weeks 2–4 land.

### What changed in the second Week-1 PR (visit DB persistence + JWT ownership)

This is the "Option C" landing the user approved.

- **Horizontal-privilege bug fixed**: `CreateVisitDto.user_id` was removed; the owner is now the JWT subject (`@CurrentUser()`). Previously any logged-in user could pass another user's `user_id` and operate on their data.
- **Every visit-scoped controller endpoint now calls `CareNoteService.ensureOwner(visitId, user.id)` before doing anything** (`getVisit`, `ingestRealtimeEvent`, `streamEvents` SSE, `runStageSummary`, `runFinalSummary`, `confirmDraftTask`, `rejectDraftTask`, `confirmMemoryCandidate`, `rejectMemoryCandidate`, `deleteVisit`, plus `mintRealtimeSession` on the realtime controller). 404 (not 403) on miss to avoid leaking visit existence.
- **`carenoteRealtime.controller.ts` `POST /api/realtime/session` was previously unguarded** in the same way and is now also `ensureOwner`'d.
- **Visit metadata persisted to `consult_sessions`**: `createVisit` now `INSERT`s a row, auto-creating a `Patient` for the JWT user if needed (mirrors `sessions.service.ts:11-18`). `visit_id` is the cuid Prisma generates (URL `/carenote/visit/<cuid>` maps 1:1 to DB row).
- **`VisitState` persisted to `consult_sessions.visitState` JSONB after every `ingestRealtimeEvent`** — fire-and-forget so the request isn't slowed by DB IO.
- **Cold-start hydration**: `hydrateVisit(visit_id)` rebuilds in-memory meta + VisitState from DB on cache miss. PM2 reload / process crash / browser reload no longer loses the visit.
- **`endVisit` writes `status=ENDED` + `endedAt` + `durationSec` to DB** and emits a `visit_status_changed` SSE event.
- **`deleteVisit` is now soft-delete**: sets `status=ARCHIVED` in DB, removes from in-memory map, emits `visit_status_changed`. `getVisit` rejects deleted visits with 404 even though the row stays for audit.
- **New endpoint `GET /api/visits`** returns the user's visit list (newest 50, owner-scoped). Lays the groundwork for the future "my visits history" page.
- **JWT strategy now accepts `?token=...` as a fallback extractor** so `EventSource` (which can't send Authorization headers) can authenticate to SSE. Header-based auth still works first; query token is the fallback.
- **Frontend `/carenote` redirects to `/login` if not authed**; `useCareNote.createVisit` no longer takes `user_id`.
- **Frontend `[id].vue` reads `clariose_token` cookie and appends it to the SSE URL**.

#### Multi-tenant isolation status

User explicitly deferred multi-tenant work, but the per-user isolation that's already required for "every user can only see their own data" is **fully in place**:
- All 11 carenote endpoints require JWT and verify owner.
- DB queries always filter by `ownerUserId`.
- 404 (not 403) on cross-user access — no existence leak.

What's still ahead for true multi-tenant (deferred):
- Cross-tenant resource quotas (codex token usage per user).
- Admin role / impersonation flow.
- Per-user DB partitioning if it ever scales.

#### Test status

- 63/63 carenote tests pass.
- Production tests use a tiny `makeFakePrisma()` stub at `backend/test/carenote/fakePrisma.ts` (only the carenote-touched surface: `consultSession.{create,findUnique,findMany,update}`, `patient.{findUnique,create}`, `user.findUnique`).

### What still breaks (regressions of the user's three Apr 29 bugs)

1. **Browser refresh wipes transcript** — ✅ **fixed in second Week-1 PR**. Visit metadata + VisitState now persist to `consult_sessions`; `hydrateVisit` rebuilds in-memory state on cache miss. Caveat: visits created before this PR landed exist only in old in-memory state and are gone.
2. **End & review → blank summary** — *will be fixed by Week 4*. Frontend will subscribe to the `agent_run_completed` SSE event for `final_visit_summary` before navigating.
3. **No codex agent results in UI** — *partly fixed*: the SSE foundation is there, but the `/carenote/visit/[id]` page already shows raw codex outputs in panels. The reason it looked empty before was no codex run was finishing fast enough; per-turn refresh now shows whatever the harness has done.

### Files added / changed this PR

- `docs/design/clariose-v01-0430.md` (this file, new)
- `backend/prisma/schema.prisma` — new fields on `User` + `ConsultSession`; new tables `CarenoteTask`, `CarenoteBlackboard`, `CarenoteMailbox`, `CarenoteAgentRun`, `UserDreamLock`
- `backend/src/modules/carenote/swarm/eventBus.ts` (new)
- `backend/src/modules/carenote/api/carenote.module.ts` — register `CarenoteEventBus`
- `backend/src/modules/carenote/api/carenote.controller.ts` — `@Sse` route + heartbeat
- `backend/src/modules/carenote/api/carenote.service.ts` — inject `CarenoteEventBus`, emit `transcript_turn_completed`
- `backend/src/modules/carenote/codex-harness/codexSdkRuntime.ts` — thread cache key now includes `visit_id`
- `backend/test/carenote/{carenoteApi,transcriptIngestService}.spec.ts` — pass `CarenoteEventBus` into test ctor
- `frontend/pages/carenote/visit/[id].vue` — `EventSource` subscription, polling demoted to 30s fallback

Status keywords used in the codebase comments to keep this doc and the source in sync:

```
// CLARIOSE_V01: implements §X.Y                — implemented per spec
// CLARIOSE_V01_PENDING: planned for §X.Y       — stub or unimplemented
// CLARIOSE_V01_DEFERRED: see §X.Y, not in v01  — captured but not in scope
```
