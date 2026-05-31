---
title: Dream + Recall Sidebar — Design
status: draft
date: 2026-04-30
owner: wenxuner@gmail.com
applies_to: backend/src/modules/carenote, frontend/pages/recall, frontend/components/recall
---

# Dream + Recall Sidebar — Design

## 1. Goal

Two user-facing changes to Clariose's per-user medical memory pipeline:

1. **Manual Dream** — give the user a button to consolidate their recent
   ENDED visits into long-lived `.md` memory files on demand, instead of
   waiting for the 03:00 daily cron.
2. **Recall sidebar** — replace the existing "filter chips" left rail of
   `/recall` with a read-only file tree of the user's dream output
   directory, plus a click-to-view Markdown pane and per-rollout re-dream.

Both changes leave the per-user medical memory layout untouched. They do
**not** introduce per-team-agent memory; the 12 carenote team agents'
`teams/<role>/memory/` directories are out of scope.

## 2. Non-goals

- No team-agent memory (`teams/<role>/memory/`).
- No per-user memory edit/delete from the UI. Tree is read-only — only
  re-dream is exposed.
- No replacement of the existing `recall-codex` Phase1+Phase2 cron — that
  pipeline operates on Codex SDK rollouts and is orthogonal to carenote
  visits. They share filesystem space (`memory/users/<u>/`) but write
  distinct files (`raw_memories.md` vs `rollout_summaries/<vid>.md`).
- No multi-team / multi-tenant. Single user → single dream namespace.
- No authentication on SSE beyond the existing JWT used by other
  controllers.

## 3. Architecture decisions (locked by clarification)

| Dimension                  | Decision                                                                           |
|---------------------------|-------------------------------------------------------------------------------------|
| Dream output target        | per-user medical memory `~/Zai/.data/carenote/memory/users/<userId>/`              |
| Manual entry points        | `POST /api/carenote/dream/run` (all eligible visits) + `POST .../run/visit/:vid`   |
| Manual gate behaviour      | bypass time-gate; lock-gate / enabled-gate / visit-count-gate honored              |
| Per-visit re-dream         | rewrites `rollout_summaries/<vid>.md` and refreshes MEMORY.md index only           |
| Sidebar interaction        | read-only tree → click → Markdown viewer → optional `[↻]` re-dream on a file       |
| Progress feedback          | SSE: `dream_started` → N × `dream_progress` → `dream_completed` (or `dream_failed`)|
| LLM strategy               | CC-style 4-phase forked agent (Orient / Gather / Consolidate / Prune)              |
| Runtime                    | reuse existing `CodexCliRuntime` (codex-cli, ChatGPT-account auth)                 |
| Cron + manual unification  | both invoke the same `DreamRunner.run(userId, scope)`                              |

## 4. Component graph

```
                    DreamController
                  (HTTP + SSE entry)
                          │
                          ▼
                    DreamSession        ◀── in-memory map keyed by dreamId
                  (state machine)               + emits events to bus
                          │
                          ▼
                    DreamRunner ──── ConsolidationLockService (existing)
              (4-phase orchestrator)
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
  DreamPromptBuilder   DreamCodexFork    DreamWorkspace
  (4-phase prompt      (codex CLI fork   (resolves user
   variants)            w/ read-only      root, fs walks
                        bash + Edit/      for sidebar)
                        Write)
```

`DreamCronService` (unchanged shape, swap callee) → `DreamRunner.run`.
`AutoDreamService` is **deleted**; its 5-gate logic moves into
`DreamRunner` and `DreamGates` so manual + cron share one path.

## 5. Backend module structure

```
backend/src/modules/carenote/swarm/
├── autoDream.ts              ← DELETE (logic absorbed into runner)
├── dreamCron.ts              ← UPDATE: call DreamRunner instead of AutoDreamService
├── consolidationLock.ts      ← unchanged
├── eventBus.ts               ← unchanged (already supports dream_* events)
├── dream/                    ← NEW
│   ├── dream.controller.ts   ← POST /api/carenote/dream/run, /run/visit/:vid, GET /tree, GET /file, /events
│   ├── dream.runner.ts       ← orchestrator: gates → lock → 4-phase fork → release
│   ├── dream.session.ts      ← in-memory dreamId → state + recent events buffer for SSE replay
│   ├── dream.gates.ts        ← isEnabled / hasEligibleVisits / time gate
│   ├── dream.workspace.ts    ← resolve(userRoot), tree walk for sidebar, safe read for viewer
│   ├── dream.prompts.ts      ← buildOrientPrompt / Gather / Consolidate / Prune (data-driven)
│   ├── dream.codexFork.ts    ← thin wrapper around CodexCliRuntime targeting userRoot cwd
│   └── dream.types.ts        ← DTOs: DreamScope, DreamPhase, DreamProgress, TreeNode
└── …
```

Module wiring (`carenote.module.ts`): drop `AutoDreamService`, add the
six new providers + `DreamController`. `DreamCronService` keeps its
constructor injection but now depends on `DreamRunner`.

### 5.1 Prisma — keep the existing models, add one

`User.lastDreamedAt` and `UserDreamLock` already exist. We add a
**lightweight** run-history row so the SSE channel can replay the last
N events on reconnect and so the sidebar can show "last dream: 13s ago"
deterministically:

```prisma
// CLARIOSE_V03 §dream — manual + cron run history.
model DreamRun {
  id              String     @id @default(cuid())
  userId          String
  scope           String     // "all" | "visit:<vid>"
  startedAt       DateTime   @default(now())
  endedAt         DateTime?
  status          DreamStatus @default(RUNNING)
  trigger         DreamTrigger
  visitCount      Int        @default(0)
  filesUpdated    Int        @default(0)
  errorMessage    String?
  // Phase events compacted JSON, capped at ~16 KB.
  // Format: [{ at, phase, pct, note }]
  progressJson    Json       @default("[]")

  user            User       @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@index([userId, startedAt(sort: Desc)])
  @@map("dream_runs")
}

enum DreamStatus { RUNNING SUCCEEDED FAILED CANCELLED }
enum DreamTrigger { MANUAL_USER MANUAL_VISIT CRON }
```

A back-relation `dreamRuns DreamRun[]` is added on `User`. Schema change
ships via `prisma db push` (per CLAUDE.md — repo has no `migrations/`).

## 6. HTTP + SSE API

All under `/api/carenote/dream/*`, `JwtAuthGuard` + `CurrentUser`. No
admin role required — every authenticated user dreams their own visits.

| Method | Path                                | Body / params                       | Returns                                              |
|-------:|-------------------------------------|--------------------------------------|------------------------------------------------------|
|  POST  | `/dream/run`                        | —                                    | `202 { dreamId }` or `423 no_eligible_visits` or `409 busy` |
|  POST  | `/dream/run/visit/:visitId`         | `:visitId` must belong to current user | `202 { dreamId }` or `409 busy` |
|   GET  | `/dream/runs`                       | —                                    | `[{ id, scope, status, startedAt, endedAt, filesUpdated }]` (last 20) |
|   GET  | `/dream/runs/:id`                   | —                                    | full DreamRun row + parsed progress events           |
|   GET  | `/dream/events`                     | SSE                                  | live event stream, scoped to current user            |
|   GET  | `/dream/tree`                       | —                                    | `{ root, lastDreamedAt, nodes: TreeNode[] }`         |
|   GET  | `/dream/file?path=…`                | path is workspace-relative           | `{ path, content, mtime, bytes }` — sandboxed       |

`TreeNode` shape:

```ts
type TreeNode = {
  name: string;          // "rollout_summaries"
  path: string;          // "rollout_summaries"
  kind: "dir" | "file";
  children?: TreeNode[]; // only when kind="dir"
  mtime?: string;        // file only
  bytes?: number;        // file only
  visitId?: string;      // file only — present iff under rollout_summaries/
};
```

### 6.1 SSE event shape

```ts
type DreamEvent =
  | { type: "dream_started";   dreamId; scope; visitCount; at }
  | { type: "dream_progress";  dreamId; phase: "orient"|"gather"|"consolidate"|"prune"; pct: number; note?: string; at }
  | { type: "dream_completed"; dreamId; filesUpdated; at }
  | { type: "dream_failed";    dreamId; reason; at };
```

The existing `CarenoteEventBus` already broadcasts. The controller's
`/dream/events` endpoint subscribes per-userId, replays the last 20
events from the in-memory `DreamSession` buffer on connect (so a
late-mounting page still picks up "in progress" runs), and streams new
events from the bus.

### 6.2 Path-sandbox for `GET /dream/file`

Resolve `userRoot = /home/ubuntu/Zai/.data/carenote/memory/users/<userId>/`
(via `MemoryRootResolver`-equivalent) and require `realpath(userRoot ⊕ path)`
to start with `realpath(userRoot)`. Reject otherwise. Cap response at
512 KB. Allowed extensions: `.md` only.

## 7. 4-phase prompt (LLM-side)

The prompt is data-driven and rendered server-side per dream. Each
phase is a separate `codex exec` invocation; we save the thread_id
from phase 1 and resume it in phases 2-4 so context is shared.

Cwd of the codex agent is `userRoot`. Tools allowed:

- `Read`, `Edit`, `Write` (the agent uses these to mutate `*.md` files)
- read-only Bash (`ls`, `cat`, `grep`, `head`, `tail`, `wc`, `stat`,
  `find` — no redirection, no pipes that write, no destructive verbs)

The codex sandbox already enforces this on hosts where `bwrap` works;
on hosts where `RECALL_CODEX_BYPASS_SANDBOX=1` (existing default) the
prompt's tool-constraint preamble is the only line of defense, exactly
as in the existing `recall-codex` flow.

### 7.1 Prompt skeleton

```
# Dream — Memory Consolidation (phase ${N}/4)

You are performing a *dream*: a reflective pass over this user's medical
memory, synthesizing recent visits into durable .md files.

Workspace: ${userRoot} (your cwd)
Visits to review: ${visitDescriptors} (path each transcript blob)

## Phase 1 — Orient
- ls the workspace.
- Read MEMORY.md to understand the current index.
- Skim memory_summary.md, allergies.md, conditions.md.
- List files under rollout_summaries/ and skills/.
Report what you found. DO NOT edit anything in this phase.

## Phase 2 — Gather
For each visit listed above, read its transcript-summary file
(`${transcriptStashDir}/<visit_id>.md`). Note new facts that
contradict / extend existing memory. DO NOT edit yet.

## Phase 3 — Consolidate
For each thing worth remembering:
- Update memory_summary.md if cross-visit insight.
- Append/replace `rollout_summaries/<visit_id>.md` for per-visit summary.
- Update allergies.md / conditions.md only on explicit, sourced facts.
- Add `skills/<snake_case>.md` only for genuine task patterns.
Files MUST keep frontmatter `name / type / last_used / keywords`.

## Phase 4 — Prune and index
Rewrite MEMORY.md as a thin index (≤ 80 lines, ≤ 25 KB):
- One line per topic file: `- [Title](file.md) — one-line hook`.
- Drop pointers to deleted/superseded files.
Conclude with a one-paragraph summary of what changed.
```

For per-visit re-dream the scope shrinks to phases 2-4 over a single
visit, never touching memory_summary.md / allergies.md / conditions.md.

### 7.2 Visit transcript stash

Before phase 2 the runner stashes each ENDED visit's transcript +
final visitState as a single Markdown blob under
`<userRoot>/.dream-staging/<dreamId>/<visitId>.md` (gitignored, removed
on dream completion). The agent reads from this directory rather than
from Postgres directly — keeps the agent's context window bounded and
the runtime stateless.

## 8. Frontend — Recall page

`pages/recall/index.vue` keeps its three-column shell, but the **left
rail content** swaps from filter chips to the dream tree. The middle
column gains a Markdown viewer for selected files; the right rail
(codex coordinator chat) is unchanged.

```
┌─────────────────────┬──────────────────────────┬──────────────────┐
│  ✨ Dream now       │   Memory viewer          │   Codex chat     │
│  ─────────────────  │   (renders selected .md, │   (unchanged)    │
│  Last dream: 13s    │   shows mtime + size)    │                  │
│                     │                          │                  │
│  📁 MEMORY.md      │                          │                  │
│  📄 memory_summary  │                          │                  │
│  📄 allergies      │                          │                  │
│  📄 conditions     │                          │                  │
│  ▼ rollout_…  (5)  │                          │                  │
│   📄 visit-cmoks…  │                          │                  │
│   📄 visit-cmokt…  │                          │                  │
│  ▼ skills/  (2)    │                          │                  │
│   📄 medication_…  │                          │                  │
│   📄 followup_…    │                          │                  │
└─────────────────────┴──────────────────────────┴──────────────────┘
```

### 8.1 New files

```
frontend/components/recall/
  ├ DreamSidebar.vue       ← tree + Dream-now button + last-dream chip
  ├ DreamTreeNode.vue      ← recursive node component
  └ DreamViewer.vue        ← Markdown + frontmatter strip + size/mtime header
frontend/composables/
  └ useDream.ts            ← SSE connection, state machine, run/runVisit/cancel
```

`useRecallNotes` filter chips are removed from the page. `useRecallChat`
and `useRecallSessions` stay.

### 8.2 Composable contract

```ts
// useDream.ts
interface DreamState {
  status: 'idle' | 'running' | 'success' | 'failed';
  current: { dreamId; scope; phase; pct; visitCount } | null;
  lastFinishedAt: string | null;
  lastFilesUpdated: number;
  history: DreamRunSummary[];
  tree: TreeNode[];
  selectedPath: string | null;
  selectedContent: string | null;
}

const dream = useDream();
dream.run();                       // POST /run, then SSE
dream.runVisit(visitId);
dream.refreshTree();
dream.openFile(path);
```

The composable subscribes to `/api/carenote/dream/events` via
EventSource on `onMounted`, and disconnects on `onBeforeUnmount`. After
`dream_completed` it auto-refreshes the tree and any selected file.

### 8.3 Mobile

The existing recall page already has a `mobileSheet` state machine for
bottom-sheet nav. Add a `"tree"` sheet so on small screens the user
gets `[ Dream | History | Tree | Chat ]` bottom buttons.

## 9. Error handling + consistency

| Failure                                 | Behaviour                                                                        |
|-----------------------------------------|----------------------------------------------------------------------------------|
| `OPENAI_API_KEY` missing / codex CLI absent | manual: 503 `{reason: "runtime_unavailable"}`; cron: log + `runs.failed`        |
| Lock held                                | manual: 409 `{reason: "busy"}`; UI shows "Another dream in progress"             |
| No eligible visits                       | manual: 423 `{reason: "no_eligible_visits"}`; UI shows toast                     |
| Phase 1 succeeds but phase 2 throws      | runner aborts, `dream_failed` event, lock released, partial files left on disk   |
| Phase write to MEMORY.md fails           | snapshot via `safeWriteWithBackup`; rollback on phase failure (existing helper)  |
| User disabled (`autoDreamEnabled=false`) | manual still works (intent is explicit); cron skips                              |
| User clicks during cron run              | rejected with 409 `{reason: "busy"}`; UI shows running cron's dreamId            |
| SSE connection drops                     | composable re-connects with backoff; controller replays last 20 events on connect|
| Path traversal in `GET /dream/file`      | 400; logged as security event                                                    |

Idempotency: `dream_run` rows survive failures with `status=FAILED` so
the user can see what went wrong from `/runs`.

## 10. Test strategy

**Backend unit (Jest):**
- `dream.gates.spec.ts` — manual bypass-time, cron honors-time, no-eligible behaviour.
- `dream.workspace.spec.ts` — path-sandbox, tree walk, file read cap.
- `dream.session.spec.ts` — event ring buffer, replay-on-subscribe.
- `dream.prompts.spec.ts` — snapshot 4 phase prompts for `scope=all` and `scope=visit:<vid>`.

**Backend e2e (supertest, real Prisma, stubbed CodexCliRuntime):**
- `POST /run` → 202 → SSE → `dream_completed`, files written under tmp memory root.
- `POST /run/visit/:vid` → 202 → only `rollout_summaries/<vid>.md` + MEMORY.md changed.
- Concurrent two POSTs → first 202, second 409.
- `GET /tree` ↔ filesystem.
- `GET /file?path=../etc/passwd` → 400.

**Frontend unit (vitest):**
- `useDream.test.ts` — state machine on each event, reconnect on close.
- `DreamSidebar.test.ts` — tree renders, dream-now click triggers POST, disabled while running.

**Manual smoke:**
- Login → end a visit → `/recall` → click Dream now → watch progress → file appears in left tree → click → renders → click `[↻]` on a `rollout_<vid>.md` → only that file's mtime advances.

## 11. Rollout

1. Land schema + `prisma db push` to dev.
2. Land backend module + tests; existing `POST /admin/auto-dream/run` in
   `carenote.controller.ts` is removed (its replacement is `POST /dream/run`,
   no admin role).
3. Land frontend; deploy via `scripts/deploy.sh` (build-only — pm2 reload
   is a separate manual step per CLAUDE.md).
4. Cron continues to run nightly via `DreamCronService`; it will pick up
   the new runner without code change since it now depends on
   `DreamRunner` instead of `AutoDreamService`.
5. Manual smoke against prod on a test patient account.

## 12. Open questions deferred to implementation

- Visit transcript stash format details (markdown structure for phase 2).
- Codex CLI argv: `--sandbox workspace-write` vs `read-only` — phase 1
  needs read; phases 3-4 need write within `userRoot` only. Likely two
  invocations with different sandbox modes.
- SSE replay buffer size (currently planned 20; revisit after first dogfood).
