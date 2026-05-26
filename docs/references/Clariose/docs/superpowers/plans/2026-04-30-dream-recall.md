# Dream + Recall Sidebar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing single-OpenAI-call `AutoDreamService` with a CC-style 4-phase forked-agent dream runner, expose user-facing manual + per-visit triggers with SSE progress, and add a read-only memory file tree to `/recall`.

**Architecture:** Backend NestJS module `carenote/swarm/dream/` orchestrates a 4-phase codex CLI fork against `~/Zai/.data/carenote/memory/users/<userId>/`. Both manual `POST /api/carenote/dream/run[/visit/:vid]` and the existing daily cron go through the same `DreamRunner`. SSE via the existing `CarenoteEventBus.streamForUser`. Frontend `useDream` composable drives a new sidebar/viewer on `/recall`.

**Tech Stack:** NestJS 11, Prisma 6, Postgres, RxJS, Codex CLI (existing `CodexCliRuntime`), Vue 3 + Nuxt 3, EventSource.

**Spec:** `docs/superpowers/specs/2026-04-30-dream-recall-design.md`

---

## File map

**Backend create:**
- `backend/src/modules/carenote/swarm/dream/dream.types.ts`
- `backend/src/modules/carenote/swarm/dream/dream.gates.ts`
- `backend/src/modules/carenote/swarm/dream/dream.workspace.ts`
- `backend/src/modules/carenote/swarm/dream/dream.session.ts`
- `backend/src/modules/carenote/swarm/dream/dream.prompts.ts`
- `backend/src/modules/carenote/swarm/dream/dream.codexFork.ts`
- `backend/src/modules/carenote/swarm/dream/dream.runner.ts`
- `backend/src/modules/carenote/swarm/dream/dream.controller.ts`
- `backend/test/carenote/dreamGates.spec.ts`
- `backend/test/carenote/dreamWorkspace.spec.ts`
- `backend/test/carenote/dreamSession.spec.ts`
- `backend/test/carenote/dreamPrompts.spec.ts`

**Backend modify:**
- `backend/prisma/schema.prisma` — add `DreamRun`, `DreamStatus`, `DreamTrigger`, `User.dreamRuns` back-relation
- `backend/src/modules/carenote/swarm/eventBus.ts` — add `dream_started`, `dream_progress`, `dream_failed` event types
- `backend/src/modules/carenote/swarm/dreamCron.ts` — depend on `DreamRunner` instead of `AutoDreamService`
- `backend/src/modules/carenote/api/carenote.module.ts` — drop `AutoDreamService`, register new providers, mount `DreamController`
- `backend/src/modules/carenote/api/carenote.controller.ts` — remove the admin `POST /admin/auto-dream/run` endpoint and the `AutoDreamService` injection

**Backend delete:**
- `backend/src/modules/carenote/swarm/autoDream.ts` (logic absorbed into runner)
- `backend/test/carenote/autoDreamGates.spec.ts` (replaced by `dreamGates.spec.ts`)

**Frontend create:**
- `frontend/composables/useDream.ts`
- `frontend/components/recall/DreamSidebar.vue`
- `frontend/components/recall/DreamTreeNode.vue`
- `frontend/components/recall/DreamViewer.vue`

**Frontend modify:**
- `frontend/pages/recall/index.vue` — swap left filter chips for `DreamSidebar`, add center-pane viewer route

---

## Task 1: Prisma — DreamRun model + enums

**Files:**
- Modify: `backend/prisma/schema.prisma`

- [ ] **Step 1: Add the model + enums + back-relation**

Append below `UserDreamLock` (around line 466):

```prisma
// Dream run history. One row per manual or cron consolidation pass; SSE
// channels replay from `progressJson` so a late-mounting page can pick up
// an in-flight run.
model DreamRun {
  id           String       @id @default(cuid())
  userId       String
  scope        String       // "all" | "visit:<visitId>"
  trigger      DreamTrigger
  status       DreamStatus  @default(RUNNING)
  startedAt    DateTime     @default(now())
  endedAt      DateTime?
  visitCount   Int          @default(0)
  filesUpdated Int          @default(0)
  errorMessage String?
  progressJson Json         @default("[]")

  user User @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@index([userId, startedAt(sort: Desc)])
  @@map("dream_runs")
}

enum DreamStatus {
  RUNNING
  SUCCEEDED
  FAILED
  CANCELLED
}

enum DreamTrigger {
  MANUAL_USER
  MANUAL_VISIT
  CRON
}
```

In the `User` model (around line 60), add the back-relation in the relations block:

```prisma
  dreamRuns        DreamRun[]
```

- [ ] **Step 2: Apply schema with `prisma db push`**

Run: `cd backend && npm run prisma:push`
Expected: `🚀 Your database is now in sync with your Prisma schema.`

- [ ] **Step 3: Regenerate Prisma client**

Run: `cd backend && npm run prisma:generate`
Expected: `✔ Generated Prisma Client`

- [ ] **Step 4: Verify by importing**

Run: `cd backend && node -e "const { PrismaClient } = require('@prisma/client'); const p = new PrismaClient(); console.log(typeof p.dreamRun.findMany)"`
Expected: `function`

- [ ] **Step 5: Commit**

```bash
git add backend/prisma/schema.prisma
git commit -m "feat(dream): add DreamRun model and enums"
```

---

## Task 2: EventBus — add dream_started / dream_progress / dream_failed

**Files:**
- Modify: `backend/src/modules/carenote/swarm/eventBus.ts`

- [ ] **Step 1: Replace the existing `dream_completed` union member with the four-event family**

Find:
```ts
  | {
      type: "dream_completed";
      userId: string;
      filesUpdated: number;
    }
```

Replace with:
```ts
  | {
      type: "dream_started";
      userId: string;
      dreamId: string;
      scope: string;
      visitCount: number;
      at: number;
    }
  | {
      type: "dream_progress";
      userId: string;
      dreamId: string;
      phase: "orient" | "gather" | "consolidate" | "prune";
      pct: number;
      note?: string;
      at: number;
    }
  | {
      type: "dream_completed";
      userId: string;
      dreamId: string;
      filesUpdated: number;
      at: number;
    }
  | {
      type: "dream_failed";
      userId: string;
      dreamId: string;
      reason: string;
      at: number;
    }
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd backend && npx tsc -p tsconfig.json --noEmit`
Expected: errors only in `swarm/autoDream.ts` (which still emits `dream_completed` with the old shape — fixed in Task 9 when we delete that file). Note these errors and proceed.

- [ ] **Step 3: Commit**

```bash
git add backend/src/modules/carenote/swarm/eventBus.ts
git commit -m "feat(dream): add dream_started/progress/failed event types"
```

---

## Task 3: dream.types.ts — DTOs

**Files:**
- Create: `backend/src/modules/carenote/swarm/dream/dream.types.ts`

- [ ] **Step 1: Write the file**

```ts
// Shared types for the dream runner + controller + frontend contract.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §6.

export type DreamPhase = "orient" | "gather" | "consolidate" | "prune";

export type DreamScope = { kind: "all" } | { kind: "visit"; visitId: string };

export type DreamTriggerKind = "manual_user" | "manual_visit" | "cron";

export interface DreamProgressEvent {
  at: number;            // ms epoch
  phase: DreamPhase;
  pct: number;           // 0..100
  note?: string;
}

export interface TreeNode {
  name: string;
  path: string;          // workspace-relative
  kind: "dir" | "file";
  children?: TreeNode[];
  mtime?: string;        // ISO; file only
  bytes?: number;        // file only
  visitId?: string;      // file only — present for files under rollout_summaries/
}

export interface DreamTreeResponse {
  root: string;          // absolute (server-side debug only); UI renders "memory/users/<u>/"
  lastDreamedAt: string | null;
  nodes: TreeNode[];
}

export interface DreamFileResponse {
  path: string;
  content: string;
  mtime: string;
  bytes: number;
}

export interface DreamRunSummary {
  id: string;
  scope: string;
  trigger: DreamTriggerKind;
  status: "running" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  endedAt: string | null;
  visitCount: number;
  filesUpdated: number;
  errorMessage: string | null;
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd backend && npx tsc -p tsconfig.json --noEmit src/modules/carenote/swarm/dream/dream.types.ts`
Expected: no errors (or unrelated pre-existing errors only).

- [ ] **Step 3: Commit**

```bash
git add backend/src/modules/carenote/swarm/dream/dream.types.ts
git commit -m "feat(dream): shared types"
```

---

## Task 4: dream.gates.ts — eligibility checks (TDD)

**Files:**
- Create: `backend/src/modules/carenote/swarm/dream/dream.gates.ts`
- Create: `backend/test/carenote/dreamGates.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
// backend/test/carenote/dreamGates.spec.ts
import { ConfigService } from "@nestjs/config";
import { DreamGates } from "../../src/modules/carenote/swarm/dream/dream.gates";

function makePrisma(visits: Array<{ id: string; ownerUserId: string; status: string; endedAt: Date | null }>) {
  return {
    consultSession: {
      count: async ({ where }: any) =>
        visits.filter(
          (v) =>
            v.ownerUserId === where.ownerUserId &&
            v.status === where.status &&
            (!where.endedAt?.gte || (v.endedAt && v.endedAt >= where.endedAt.gte)),
        ).length,
      findUnique: async ({ where }: any) =>
        visits.find((v) => v.id === where.id) ?? null,
    },
  } as any;
}

function cfg(map: Record<string, string> = {}): ConfigService {
  return { get: (k: string) => map[k] } as any;
}

describe("DreamGates", () => {
  it("isEnabled honors CARENOTE_DREAM_ENABLED=false", () => {
    const g = new DreamGates(cfg({ CARENOTE_DREAM_ENABLED: "false" }), {} as any);
    expect(g.isEnabled()).toBe(false);
  });

  it("isEnabled defaults true when env unset", () => {
    const g = new DreamGates(cfg(), {} as any);
    expect(g.isEnabled()).toBe(true);
  });

  it("hasEligibleVisits true when ENDED visits exist since lastDreamedAt", async () => {
    const last = new Date(Date.now() - 24 * 3600_000);
    const prisma = makePrisma([
      { id: "v1", ownerUserId: "u1", status: "ENDED", endedAt: new Date(Date.now() - 1 * 3600_000) },
    ]);
    const g = new DreamGates(cfg(), prisma);
    expect(await g.hasEligibleVisits("u1", last)).toBe(true);
  });

  it("hasEligibleVisits false when no recent ENDED visits", async () => {
    const last = new Date(Date.now() - 1 * 3600_000);
    const prisma = makePrisma([
      { id: "v1", ownerUserId: "u1", status: "ENDED", endedAt: new Date(Date.now() - 4 * 3600_000) },
    ]);
    const g = new DreamGates(cfg(), prisma);
    expect(await g.hasEligibleVisits("u1", last)).toBe(false);
  });

  it("isVisitOwnedAndEnded enforces ownership and ENDED state", async () => {
    const prisma = makePrisma([
      { id: "v1", ownerUserId: "u1", status: "ENDED", endedAt: new Date() },
      { id: "v2", ownerUserId: "u2", status: "ENDED", endedAt: new Date() },
      { id: "v3", ownerUserId: "u1", status: "ACTIVE", endedAt: null },
    ]);
    const g = new DreamGates(cfg(), prisma);
    expect(await g.isVisitOwnedAndEnded("v1", "u1")).toBe(true);
    expect(await g.isVisitOwnedAndEnded("v2", "u1")).toBe(false); // wrong owner
    expect(await g.isVisitOwnedAndEnded("v3", "u1")).toBe(false); // not ENDED
    expect(await g.isVisitOwnedAndEnded("vX", "u1")).toBe(false); // missing
  });
});
```

- [ ] **Step 2: Run test, expect failure**

Run: `cd backend && npx jest test/carenote/dreamGates.spec.ts`
Expected: `Cannot find module '.../dream/dream.gates'` or similar — test file imports a non-existent module.

- [ ] **Step 3: Write the implementation**

```ts
// backend/src/modules/carenote/swarm/dream/dream.gates.ts
//
// Pure-policy gates for whether a dream run is allowed *for a given user
// or visit*. The lock gate is owned by ConsolidationLockService; the
// time gate (manual override) is owned by DreamRunner.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §3 / §9.

import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { PrismaService } from "../../../../common/prisma/prisma.service";

@Injectable()
export class DreamGates {
  constructor(
    private readonly cfg: ConfigService,
    private readonly prisma: PrismaService,
  ) {}

  /** Master switch. CARENOTE_DREAM_ENABLED=false makes every gate fail. */
  isEnabled(): boolean {
    return this.cfg.get<string>("CARENOTE_DREAM_ENABLED") !== "false";
  }

  /** True iff the user has at least one ENDED ConsultSession with endedAt
   *  >= lastDreamedAt (or any ENDED session if lastDreamedAt is null). */
  async hasEligibleVisits(userId: string, since: Date | null): Promise<boolean> {
    const where: Record<string, unknown> = {
      ownerUserId: userId,
      status: "ENDED",
    };
    if (since) where.endedAt = { gte: since };
    const n = await this.prisma.consultSession.count({ where });
    return n > 0;
  }

  /** True iff visitId belongs to userId AND is ENDED. */
  async isVisitOwnedAndEnded(visitId: string, userId: string): Promise<boolean> {
    const v = await this.prisma.consultSession.findUnique({
      where: { id: visitId },
    });
    return !!v && v.ownerUserId === userId && v.status === "ENDED";
  }
}
```

- [ ] **Step 4: Run test, expect pass**

Run: `cd backend && npx jest test/carenote/dreamGates.spec.ts`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/modules/carenote/swarm/dream/dream.gates.ts backend/test/carenote/dreamGates.spec.ts
git commit -m "feat(dream): gate policies + tests"
```

---

## Task 5: dream.workspace.ts — userRoot + tree walk + safe read (TDD)

**Files:**
- Create: `backend/src/modules/carenote/swarm/dream/dream.workspace.ts`
- Create: `backend/test/carenote/dreamWorkspace.spec.ts`

- [ ] **Step 1: Write failing test**

```ts
// backend/test/carenote/dreamWorkspace.spec.ts
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ConfigService } from "@nestjs/config";

import { DreamWorkspace } from "../../src/modules/carenote/swarm/dream/dream.workspace";

function cfg(root: string): ConfigService {
  return { get: (k: string) => (k === "CARENOTE_MEMORY_ROOT" ? root : undefined) } as any;
}

describe("DreamWorkspace", () => {
  let tmp: string;
  beforeEach(async () => { tmp = await mkdtemp(join(tmpdir(), "dream-ws-")); });
  afterEach(async () => { await rm(tmp, { recursive: true, force: true }); });

  it("walkTree returns sorted dir-then-file structure", async () => {
    const root = join(tmp, "users", "u1");
    await mkdir(join(root, "rollout_summaries"), { recursive: true });
    await mkdir(join(root, "skills"), { recursive: true });
    await writeFile(join(root, "MEMORY.md"), "# index\n");
    await writeFile(join(root, "memory_summary.md"), "# summary\n");
    await writeFile(join(root, "rollout_summaries", "v_abc.md"), "# v_abc\n");
    await writeFile(join(root, "skills", "med.md"), "# skill\n");

    const ws = new DreamWorkspace(cfg(tmp));
    const nodes = await ws.walkTree("u1");

    const names = nodes.map((n) => n.name);
    expect(names).toEqual(["rollout_summaries", "skills", "MEMORY.md", "memory_summary.md"]);
    const rs = nodes.find((n) => n.name === "rollout_summaries")!;
    expect(rs.kind).toBe("dir");
    expect(rs.children!.map((c) => c.name)).toEqual(["v_abc.md"]);
    expect(rs.children![0].visitId).toBe("v_abc");
  });

  it("walkTree on missing root returns empty array (no throw)", async () => {
    const ws = new DreamWorkspace(cfg(tmp));
    expect(await ws.walkTree("nonexistent")).toEqual([]);
  });

  it("readFile returns content for in-bounds .md path", async () => {
    const root = join(tmp, "users", "u1");
    await mkdir(root, { recursive: true });
    await writeFile(join(root, "MEMORY.md"), "hello\n");

    const ws = new DreamWorkspace(cfg(tmp));
    const r = await ws.readFile("u1", "MEMORY.md");
    expect(r.content).toBe("hello\n");
    expect(r.bytes).toBe(6);
  });

  it("readFile rejects path traversal", async () => {
    const root = join(tmp, "users", "u1");
    await mkdir(root, { recursive: true });
    await writeFile(join(tmp, "secret.md"), "nope\n");

    const ws = new DreamWorkspace(cfg(tmp));
    await expect(ws.readFile("u1", "../secret.md")).rejects.toThrow(/outside workspace/i);
  });

  it("readFile rejects non-md extensions", async () => {
    const root = join(tmp, "users", "u1");
    await mkdir(root, { recursive: true });
    await writeFile(join(root, "secret.txt"), "nope\n");

    const ws = new DreamWorkspace(cfg(tmp));
    await expect(ws.readFile("u1", "secret.txt")).rejects.toThrow(/extension/i);
  });
});
```

- [ ] **Step 2: Run test, expect fail**

Run: `cd backend && npx jest test/carenote/dreamWorkspace.spec.ts`
Expected: module-not-found error.

- [ ] **Step 3: Write the implementation**

```ts
// backend/src/modules/carenote/swarm/dream/dream.workspace.ts
//
// Resolves a user's dream output directory and exposes safe read primitives.
// Path-sandboxed: every readFile call resolves through realpath and rejects
// anything that escapes the user's root. Only .md files are surfaced.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §6.2.

import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { promises as fs, Stats } from "node:fs";
import { realpath } from "node:fs/promises";
import { extname, join, relative, resolve } from "node:path";

import type { TreeNode } from "./dream.types";

const MEMORY_ROOT_DEFAULT = "/home/ubuntu/Zai/.data/carenote/memory";
const MAX_FILE_BYTES = 512 * 1024;

@Injectable()
export class DreamWorkspace {
  constructor(private readonly cfg: ConfigService) {}

  rootForUser(userId: string): string {
    const root = this.cfg.get<string>("CARENOTE_MEMORY_ROOT") ?? MEMORY_ROOT_DEFAULT;
    return join(root, "users", userId);
  }

  async ensureRoot(userId: string): Promise<string> {
    const root = this.rootForUser(userId);
    await fs.mkdir(root, { recursive: true });
    return root;
  }

  /** Recursive directory walk. Returns dirs-first then files, both sorted by name. */
  async walkTree(userId: string): Promise<TreeNode[]> {
    const root = this.rootForUser(userId);
    try {
      await fs.access(root);
    } catch {
      return [];
    }
    return this.walk(root, "");
  }

  private async walk(absDir: string, relDir: string): Promise<TreeNode[]> {
    let entries: Array<{ name: string; isDir: boolean; isFile: boolean }>;
    try {
      const dirents = await fs.readdir(absDir, { withFileTypes: true });
      entries = dirents
        .filter((d) => !d.name.startsWith(".")) // hide .consolidation.lock, .dream-staging
        .map((d) => ({ name: d.name, isDir: d.isDirectory(), isFile: d.isFile() }));
    } catch {
      return [];
    }
    entries.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });

    const out: TreeNode[] = [];
    for (const e of entries) {
      const childRel = relDir ? `${relDir}/${e.name}` : e.name;
      const childAbs = join(absDir, e.name);
      if (e.isDir) {
        out.push({
          name: e.name,
          path: childRel,
          kind: "dir",
          children: await this.walk(childAbs, childRel),
        });
      } else if (e.isFile && e.name.endsWith(".md")) {
        const stat = await fs.stat(childAbs);
        const node: TreeNode = {
          name: e.name,
          path: childRel,
          kind: "file",
          mtime: stat.mtime.toISOString(),
          bytes: stat.size,
        };
        if (childRel.startsWith("rollout_summaries/")) {
          node.visitId = e.name.replace(/\.md$/, "");
        }
        out.push(node);
      }
    }
    return out;
  }

  async readFile(
    userId: string,
    relPath: string,
  ): Promise<{ content: string; mtime: string; bytes: number; absPath: string }> {
    if (extname(relPath) !== ".md") {
      throw new Error(`disallowed extension: ${relPath}`);
    }
    const root = this.rootForUser(userId);
    const requested = resolve(root, relPath);
    let realRoot: string;
    let realFile: string;
    try {
      realRoot = await realpath(root);
    } catch {
      throw new Error(`workspace not initialized for user ${userId}`);
    }
    try {
      realFile = await realpath(requested);
    } catch {
      throw new Error(`file not found: ${relPath}`);
    }
    const rel = relative(realRoot, realFile);
    if (rel.startsWith("..") || rel.startsWith("/")) {
      throw new Error(`path outside workspace: ${relPath}`);
    }
    let stat: Stats;
    try {
      stat = await fs.stat(realFile);
    } catch {
      throw new Error(`file not found: ${relPath}`);
    }
    if (stat.size > MAX_FILE_BYTES) {
      throw new Error(`file too large: ${relPath}`);
    }
    const content = await fs.readFile(realFile, "utf-8");
    return {
      content,
      mtime: stat.mtime.toISOString(),
      bytes: stat.size,
      absPath: realFile,
    };
  }
}
```

- [ ] **Step 4: Run tests, expect pass**

Run: `cd backend && npx jest test/carenote/dreamWorkspace.spec.ts`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/modules/carenote/swarm/dream/dream.workspace.ts backend/test/carenote/dreamWorkspace.spec.ts
git commit -m "feat(dream): workspace path-sandbox + tree walk"
```

---

## Task 6: dream.session.ts — in-memory state + ring buffer (TDD)

**Files:**
- Create: `backend/src/modules/carenote/swarm/dream/dream.session.ts`
- Create: `backend/test/carenote/dreamSession.spec.ts`

- [ ] **Step 1: Write failing test**

```ts
// backend/test/carenote/dreamSession.spec.ts
import { DreamSessionRegistry } from "../../src/modules/carenote/swarm/dream/dream.session";

describe("DreamSessionRegistry", () => {
  it("openSession produces unique dreamIds and registers under userId", () => {
    const r = new DreamSessionRegistry();
    const a = r.openSession("u1", "all", 3);
    const b = r.openSession("u1", "visit:v_x", 1);
    expect(a.dreamId).not.toEqual(b.dreamId);
    expect(r.listForUser("u1").map((s) => s.dreamId).sort()).toEqual([a.dreamId, b.dreamId].sort());
  });

  it("recordEvent appends and ringBuffer caps at 20 entries", () => {
    const r = new DreamSessionRegistry();
    const s = r.openSession("u1", "all", 1);
    for (let i = 0; i < 30; i++) {
      r.recordEvent(s.dreamId, { phase: "gather", pct: i, at: i, note: `n${i}` });
    }
    const buf = r.replayBuffer(s.dreamId);
    expect(buf).toHaveLength(20);
    expect(buf[0].pct).toBe(10);  // first 10 dropped
    expect(buf[19].pct).toBe(29);
  });

  it("closeSession marks ended and replayBuffer still works", () => {
    const r = new DreamSessionRegistry();
    const s = r.openSession("u1", "all", 1);
    r.recordEvent(s.dreamId, { phase: "orient", pct: 10, at: 0 });
    r.closeSession(s.dreamId, "succeeded");
    const open = r.findOpen("u1");
    expect(open).toBeNull();
    expect(r.replayBuffer(s.dreamId)).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run, expect fail**

Run: `cd backend && npx jest test/carenote/dreamSession.spec.ts`
Expected: module not found.

- [ ] **Step 3: Write implementation**

```ts
// backend/src/modules/carenote/swarm/dream/dream.session.ts
//
// In-memory state for active dream runs. Holds:
//   - dreamId → user / scope / status / phase
//   - per-dream ring buffer of last 20 progress events (for SSE replay-on-connect)
// Survives only as long as the Nest process. Persistence is in DreamRun rows.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §6.

import { Injectable } from "@nestjs/common";
import { randomUUID } from "node:crypto";

import type { DreamProgressEvent } from "./dream.types";

const RING_BUFFER_MAX = 20;

interface InternalSession {
  dreamId: string;
  userId: string;
  scope: string;
  visitCount: number;
  status: "running" | "succeeded" | "failed" | "cancelled";
  ringBuffer: DreamProgressEvent[];
  startedAt: number;
}

@Injectable()
export class DreamSessionRegistry {
  private readonly byId = new Map<string, InternalSession>();

  openSession(userId: string, scope: string, visitCount: number): { dreamId: string } {
    const dreamId = randomUUID();
    this.byId.set(dreamId, {
      dreamId,
      userId,
      scope,
      visitCount,
      status: "running",
      ringBuffer: [],
      startedAt: Date.now(),
    });
    return { dreamId };
  }

  recordEvent(dreamId: string, ev: DreamProgressEvent): void {
    const s = this.byId.get(dreamId);
    if (!s) return;
    s.ringBuffer.push(ev);
    if (s.ringBuffer.length > RING_BUFFER_MAX) {
      s.ringBuffer.splice(0, s.ringBuffer.length - RING_BUFFER_MAX);
    }
  }

  closeSession(dreamId: string, status: "succeeded" | "failed" | "cancelled"): void {
    const s = this.byId.get(dreamId);
    if (!s) return;
    s.status = status;
  }

  replayBuffer(dreamId: string): DreamProgressEvent[] {
    return this.byId.get(dreamId)?.ringBuffer.slice() ?? [];
  }

  listForUser(userId: string): InternalSession[] {
    return [...this.byId.values()].filter((s) => s.userId === userId);
  }

  /** Returns the most recent still-running session for this user, or null. */
  findOpen(userId: string): InternalSession | null {
    const open = this.listForUser(userId).filter((s) => s.status === "running");
    if (open.length === 0) return null;
    open.sort((a, b) => b.startedAt - a.startedAt);
    return open[0];
  }
}
```

- [ ] **Step 4: Run, expect pass**

Run: `cd backend && npx jest test/carenote/dreamSession.spec.ts`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/modules/carenote/swarm/dream/dream.session.ts backend/test/carenote/dreamSession.spec.ts
git commit -m "feat(dream): in-memory session registry"
```

---

## Task 7: dream.prompts.ts — 4-phase prompt builder (TDD)

**Files:**
- Create: `backend/src/modules/carenote/swarm/dream/dream.prompts.ts`
- Create: `backend/test/carenote/dreamPrompts.spec.ts`

- [ ] **Step 1: Failing test**

```ts
// backend/test/carenote/dreamPrompts.spec.ts
import {
  buildDreamPrompt,
  type DreamPromptInput,
} from "../../src/modules/carenote/swarm/dream/dream.prompts";

const baseInput: DreamPromptInput = {
  phase: "orient",
  workspaceRoot: "/data/users/u1",
  stagingDir: "/data/users/u1/.dream-staging/d1",
  visits: [
    { visitId: "v_a", endedAt: "2026-04-29T10:00:00Z" },
    { visitId: "v_b", endedAt: "2026-04-30T11:00:00Z" },
  ],
  scope: { kind: "all" },
};

describe("buildDreamPrompt", () => {
  it("orient prompt mentions workspace + visit list + 'DO NOT edit'", () => {
    const p = buildDreamPrompt(baseInput);
    expect(p).toContain("/data/users/u1");
    expect(p).toContain("Phase 1 — Orient");
    expect(p).toContain("v_a");
    expect(p).toContain("v_b");
    expect(p).toContain("DO NOT edit");
  });

  it("gather prompt references staging dir and lists visit ids", () => {
    const p = buildDreamPrompt({ ...baseInput, phase: "gather" });
    expect(p).toContain("Phase 2 — Gather");
    expect(p).toContain("/data/users/u1/.dream-staging/d1");
    expect(p).toContain("v_a.md");
    expect(p).toContain("v_b.md");
  });

  it("consolidate prompt enumerates target files", () => {
    const p = buildDreamPrompt({ ...baseInput, phase: "consolidate" });
    expect(p).toContain("memory_summary.md");
    expect(p).toContain("rollout_summaries/");
    expect(p).toContain("allergies.md");
    expect(p).toContain("conditions.md");
    expect(p).toContain("skills/");
  });

  it("prune prompt enforces MEMORY.md size cap", () => {
    const p = buildDreamPrompt({ ...baseInput, phase: "prune" });
    expect(p).toContain("MEMORY.md");
    expect(p).toMatch(/80 lines/);
    expect(p).toMatch(/25 ?KB/i);
  });

  it("scope=visit narrows the consolidate instructions to that single rollout", () => {
    const p = buildDreamPrompt({
      ...baseInput,
      phase: "consolidate",
      scope: { kind: "visit", visitId: "v_a" },
      visits: [{ visitId: "v_a", endedAt: "2026-04-29T10:00:00Z" }],
    });
    expect(p).toContain("rollout_summaries/v_a.md");
    expect(p).toContain("DO NOT modify memory_summary.md");
    expect(p).toContain("DO NOT modify allergies.md");
  });
});
```

- [ ] **Step 2: Run, expect fail**

Run: `cd backend && npx jest test/carenote/dreamPrompts.spec.ts`
Expected: module not found.

- [ ] **Step 3: Implement**

```ts
// backend/src/modules/carenote/swarm/dream/dream.prompts.ts
//
// 4-phase dream prompt — modeled on Claude Code's
// services/autoDream/consolidationPrompt.ts but adapted for the per-user
// medical-memory schema (memory_summary / allergies / conditions /
// rollout_summaries / skills / MEMORY.md).
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §7.

import type { DreamPhase, DreamScope } from "./dream.types";

export interface DreamVisitDescriptor {
  visitId: string;
  endedAt: string;
}

export interface DreamPromptInput {
  phase: DreamPhase;
  workspaceRoot: string;
  stagingDir: string;
  visits: DreamVisitDescriptor[];
  scope: DreamScope;
}

export function buildDreamPrompt(input: DreamPromptInput): string {
  const { phase, workspaceRoot, stagingDir, visits, scope } = input;
  const visitList = visits
    .map((v) => `- ${v.visitId} (ended ${v.endedAt})`)
    .join("\n");

  const header = `# Dream — Memory Consolidation (phase ${phaseNumber(phase)}/4)

You are performing a *dream*: a reflective pass over this user's medical
memory. Your output is a small set of edited / created / pruned Markdown
files under the workspace.

Workspace (your cwd): ${workspaceRoot}
Visit transcripts staged at: ${stagingDir}

Visits to review (${visits.length}):
${visitList || "- (none)"}
`;

  let body: string;
  switch (phase) {
    case "orient":
      body = ORIENT_BODY;
      break;
    case "gather":
      body = gatherBody(stagingDir, visits);
      break;
    case "consolidate":
      body = consolidateBody(scope);
      break;
    case "prune":
      body = PRUNE_BODY;
      break;
  }

  return `${header}\n${body}`;
}

function phaseNumber(p: DreamPhase): number {
  return { orient: 1, gather: 2, consolidate: 3, prune: 4 }[p];
}

const ORIENT_BODY = `## Phase 1 — Orient

- \`ls\` the workspace.
- Read MEMORY.md to understand the current index.
- Skim memory_summary.md, allergies.md, conditions.md if they exist.
- List files under rollout_summaries/ and skills/.

Report what you found. **DO NOT edit anything in this phase.**
`;

function gatherBody(stagingDir: string, visits: DreamVisitDescriptor[]): string {
  const reads = visits.map((v) => `- ${stagingDir}/${v.visitId}.md`).join("\n");
  return `## Phase 2 — Gather

For each visit listed above, read its staged transcript file:

${reads}

Note new facts that contradict, extend, or duplicate existing memory.
**DO NOT edit any .md files in this phase** — only read.
`;
}

function consolidateBody(scope: DreamScope): string {
  if (scope.kind === "visit") {
    return `## Phase 3 — Consolidate (single visit: ${scope.visitId})

Update **only** \`rollout_summaries/${scope.visitId}.md\` to capture this
visit's summary. Use this frontmatter at the top:

\`\`\`
---
name: visit ${scope.visitId}
type: rollout_summary
last_used: <today YYYY-MM-DD>
keywords: [auto_dream, visit_${scope.visitId}]
---
\`\`\`

**DO NOT modify memory_summary.md.**
**DO NOT modify allergies.md.**
**DO NOT modify conditions.md.**
**DO NOT touch skills/.**
The rest of the workspace is read-only for this run.
`;
  }
  return `## Phase 3 — Consolidate

For each thing worth remembering:
- Update \`memory_summary.md\` for cross-visit insight (≤ 4 KB).
- Append/replace \`rollout_summaries/<visit_id>.md\` for per-visit summaries.
- Update \`allergies.md\` and \`conditions.md\` only on explicit, sourced facts.
- Add \`skills/<snake_case_name>.md\` only for genuine task patterns.

Every .md file MUST start with frontmatter:

\`\`\`
---
name: <human-readable name>
type: summary | rollout_summary | facts | skill
last_used: <today YYYY-MM-DD>
keywords: [auto_dream, ...]
---
\`\`\`

Convert relative dates ("yesterday", "last week") to absolute dates.
Do NOT include PHI like full names, contact info, or addresses.
`;
}

const PRUNE_BODY = `## Phase 4 — Prune and index

Rewrite **MEMORY.md** as a thin index:
- Keep it under **80 lines** AND under **~25 KB**.
- Each entry is one line under ~150 characters:
  \`- [Title](file.md) — one-line hook\`
- Drop pointers to deleted/superseded files.
- Demote verbose lines (>200 chars) by moving the detail back into the
  topic file and shortening the index entry.
- Resolve contradictions; if two files disagree, fix the wrong one.

End with a one-paragraph plain-text summary of what changed.
`;
```

- [ ] **Step 4: Run, expect pass**

Run: `cd backend && npx jest test/carenote/dreamPrompts.spec.ts`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/modules/carenote/swarm/dream/dream.prompts.ts backend/test/carenote/dreamPrompts.spec.ts
git commit -m "feat(dream): 4-phase prompt builder + tests"
```

---

## Task 8: dream.codexFork.ts — codex CLI wrapper

**Files:**
- Create: `backend/src/modules/carenote/swarm/dream/dream.codexFork.ts`

No unit test — this is a thin wrapper around `child_process.spawn` and the existing CLI semantics; integration is exercised through Task 9's runner. It returns deterministic shapes so the runner can inspect outcomes.

- [ ] **Step 1: Implement**

```ts
// backend/src/modules/carenote/swarm/dream/dream.codexFork.ts
//
// Spawns one `codex exec` invocation against a per-user workspace.
//
// Auth/sandbox match the existing carenote codex-cli runtime:
//   - no --model (ChatGPT-account auth restricts it server-side)
//   - --skip-git-repo-check (the memory dir is not a git repo)
//   - --json (emit JSONL events on stdout)
//   - --output-last-message <file> (capture the final assistant message)
//   - --sandbox depends on phase: orient/gather → "read-only";
//                                  consolidate/prune → "workspace-write"
//   - cwd = workspaceRoot
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §7.

import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { DreamPhase } from "./dream.types";

const PER_PHASE_TIMEOUT_MS_DEFAULT = 120_000;

export interface DreamForkInput {
  phase: DreamPhase;
  prompt: string;
  workspaceRoot: string;
  /** Pass thread_id from a prior phase to resume that conversation. */
  threadId: string | null;
  abort?: AbortSignal;
}

export interface DreamForkOutput {
  exitCode: number | null;
  threadId: string | null;
  finalMessage: string;
  durationMs: number;
}

@Injectable()
export class DreamCodexFork {
  private readonly logger = new Logger("DreamCodexFork");

  constructor(private readonly cfg: ConfigService) {}

  async run(input: DreamForkInput): Promise<DreamForkOutput> {
    const binary = this.cfg.get<string>("CODEX_CLI_BIN") ?? "codex";
    const timeoutMs =
      Number(this.cfg.get<string>("CARENOTE_DREAM_PHASE_TIMEOUT_MS")) ||
      PER_PHASE_TIMEOUT_MS_DEFAULT;
    const sandbox =
      input.phase === "orient" || input.phase === "gather"
        ? "read-only"
        : "workspace-write";
    const workdir = await mkdtemp(join(tmpdir(), "dream-out-"));
    const lastMessageFile = join(workdir, "last.txt");
    const args = [
      "exec",
      "--json",
      "--skip-git-repo-check",
      "--sandbox",
      sandbox,
      "--output-last-message",
      lastMessageFile,
      "-C",
      input.workspaceRoot,
      "-",
    ];
    if (input.threadId && input.phase !== "orient") {
      // resume requires the `resume` subcommand AND a SESSION_ID arg
      args.splice(0, 1, "exec", "resume", input.threadId);
    }

    const start = Date.now();
    let threadId: string | null = input.threadId ?? null;
    let exitCode: number | null = null;
    let finalMessage = "";

    try {
      const proc = spawn(binary, args, {
        cwd: input.workspaceRoot,
        env: { ...process.env },
        stdio: ["pipe", "pipe", "pipe"],
      });
      proc.stdin.write(input.prompt);
      proc.stdin.end();

      const onAbort = (): void => proc.kill("SIGTERM");
      input.abort?.addEventListener("abort", onAbort);

      const stdoutBuf: string[] = [];
      const stderrBuf: string[] = [];
      proc.stdout.setEncoding("utf-8");
      proc.stderr.setEncoding("utf-8");
      proc.stdout.on("data", (d: string) => {
        stdoutBuf.push(d);
        for (const line of d.split("\n")) {
          if (!line.trim()) continue;
          try {
            const ev = JSON.parse(line);
            if (ev.type === "thread.started" && typeof ev.thread_id === "string") {
              threadId = ev.thread_id;
            }
          } catch {
            // not a JSON line — ignore, codex CLI mixes plain noise
          }
        }
      });
      proc.stderr.on("data", (d: string) => stderrBuf.push(d));

      const timer = setTimeout(() => proc.kill("SIGTERM"), timeoutMs);

      exitCode = await new Promise<number | null>((resolveExit) => {
        proc.once("exit", (code) => {
          clearTimeout(timer);
          input.abort?.removeEventListener("abort", onAbort);
          resolveExit(code);
        });
      });

      try {
        finalMessage = await readFile(lastMessageFile, "utf-8");
      } catch {
        // no message file written
      }

      if (exitCode !== 0) {
        this.logger.warn(
          `dream phase=${input.phase} exit=${exitCode} stderr=${stderrBuf
            .join("")
            .slice(-400)}`,
        );
      }
    } finally {
      await rm(workdir, { recursive: true, force: true }).catch(() => undefined);
    }

    return {
      exitCode,
      threadId,
      finalMessage,
      durationMs: Date.now() - start,
    };
  }
}
```

- [ ] **Step 2: TypeScript check**

Run: `cd backend && npx tsc -p tsconfig.json --noEmit`
Expected: errors only in autoDream.ts (still present, fixed in Task 9).

- [ ] **Step 3: Commit**

```bash
git add backend/src/modules/carenote/swarm/dream/dream.codexFork.ts
git commit -m "feat(dream): codex CLI fork wrapper"
```

---

## Task 9: dream.runner.ts — orchestrator + delete autoDream.ts

**Files:**
- Create: `backend/src/modules/carenote/swarm/dream/dream.runner.ts`
- Delete: `backend/src/modules/carenote/swarm/autoDream.ts`
- Delete: `backend/test/carenote/autoDreamGates.spec.ts`
- Modify: `backend/src/modules/carenote/swarm/dreamCron.ts`

- [ ] **Step 1: Write the runner**

```ts
// backend/src/modules/carenote/swarm/dream/dream.runner.ts
//
// Orchestrates one dream pass:
//   1. Gates (enabled / eligible-visits or visit-owned)
//   2. Acquire ConsolidationLockService
//   3. Stash transcripts to <userRoot>/.dream-staging/<dreamId>/
//   4. Persist DreamRun (status=RUNNING)
//   5. Run 4 codex CLI phases, emit progress events, count files touched
//   6. Persist DreamRun (status=SUCCEEDED|FAILED), emit dream_completed/failed
//   7. Release lock
//
// Manual + cron + per-visit all enter through `run()` with different scopes.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §4 / §9.

import { Injectable, Logger } from "@nestjs/common";
import { mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { PrismaService } from "../../../../common/prisma/prisma.service";
import { ConsolidationLockService } from "../consolidationLock";
import { CarenoteEventBus } from "../eventBus";
import { DreamCodexFork } from "./dream.codexFork";
import { DreamGates } from "./dream.gates";
import {
  buildDreamPrompt,
  type DreamPromptInput,
  type DreamVisitDescriptor,
} from "./dream.prompts";
import { DreamSessionRegistry } from "./dream.session";
import { DreamWorkspace } from "./dream.workspace";
import type {
  DreamPhase,
  DreamScope,
  DreamTriggerKind,
  DreamProgressEvent,
} from "./dream.types";

interface RunOptions {
  scope: DreamScope;
  trigger: DreamTriggerKind;
  bypassTimeGate: boolean;
}

interface RunResult {
  outcome: "started" | "no_eligible_visits" | "busy" | "disabled" | "forbidden";
  dreamId?: string;
}

const PHASES: DreamPhase[] = ["orient", "gather", "consolidate", "prune"];

const PHASE_PCT: Record<DreamPhase, number> = {
  orient: 15,
  gather: 40,
  consolidate: 80,
  prune: 100,
};

const MIN_HOURS_SINCE_LAST = 20;

@Injectable()
export class DreamRunner {
  private readonly logger = new Logger("DreamRunner");

  constructor(
    private readonly prisma: PrismaService,
    private readonly lock: ConsolidationLockService,
    private readonly bus: CarenoteEventBus,
    private readonly gates: DreamGates,
    private readonly workspace: DreamWorkspace,
    private readonly sessions: DreamSessionRegistry,
    private readonly fork: DreamCodexFork,
  ) {}

  async run(userId: string, opts: RunOptions): Promise<RunResult> {
    if (!this.gates.isEnabled()) return { outcome: "disabled" };

    // Cron path honors the time gate; manual paths bypass.
    if (!opts.bypassTimeGate) {
      const u = await this.prisma.user.findUnique({
        where: { id: userId },
        select: { lastDreamedAt: true },
      });
      if (u?.lastDreamedAt) {
        const hoursSince = (Date.now() - u.lastDreamedAt.getTime()) / 3_600_000;
        if (hoursSince < MIN_HOURS_SINCE_LAST) return { outcome: "no_eligible_visits" };
      }
    }

    if (opts.scope.kind === "all") {
      const u = await this.prisma.user.findUnique({
        where: { id: userId },
        select: { lastDreamedAt: true },
      });
      const ok = await this.gates.hasEligibleVisits(userId, u?.lastDreamedAt ?? null);
      if (!ok) return { outcome: "no_eligible_visits" };
    } else {
      const ok = await this.gates.isVisitOwnedAndEnded(opts.scope.visitId, userId);
      if (!ok) return { outcome: "forbidden" };
    }

    const acquired = await this.lock.acquire(userId);
    if (!acquired) return { outcome: "busy" };

    const visits = await this.collectVisits(userId, opts.scope);
    const session = this.sessions.openSession(
      userId,
      scopeToString(opts.scope),
      visits.length,
    );
    const dreamId = session.dreamId;

    const dreamRun = await this.prisma.dreamRun.create({
      data: {
        userId,
        scope: scopeToString(opts.scope),
        trigger: triggerEnum(opts.trigger),
        status: "RUNNING",
        visitCount: visits.length,
      },
    });

    this.bus.emit({
      type: "dream_started",
      userId,
      dreamId,
      scope: scopeToString(opts.scope),
      visitCount: visits.length,
      at: Date.now(),
    });

    void this.executeAsync(userId, dreamId, dreamRun.id, opts.scope, visits).catch(
      (err) => {
        this.logger.error(`dream ${dreamId} unhandled: ${(err as Error).message}`);
      },
    );

    return { outcome: "started", dreamId };
  }

  private async executeAsync(
    userId: string,
    dreamId: string,
    dreamRunId: string,
    scope: DreamScope,
    visits: DreamVisitDescriptor[],
  ): Promise<void> {
    const events: DreamProgressEvent[] = [];
    const root = await this.workspace.ensureRoot(userId);
    const stagingDir = join(root, ".dream-staging", dreamId);
    let threadId: string | null = null;
    let filesTouchedBefore = 0;
    let filesTouchedAfter = 0;
    try {
      await mkdir(stagingDir, { recursive: true });
      await this.stashTranscripts(stagingDir, scope, userId);
      filesTouchedBefore = await this.countMd(root);

      for (const phase of PHASES) {
        const promptInput: DreamPromptInput = {
          phase,
          workspaceRoot: root,
          stagingDir,
          visits,
          scope,
        };
        const prompt = buildDreamPrompt(promptInput);
        const out = await this.fork.run({
          phase,
          prompt,
          workspaceRoot: root,
          threadId,
        });
        if (out.threadId) threadId = out.threadId;
        const ev: DreamProgressEvent = {
          at: Date.now(),
          phase,
          pct: PHASE_PCT[phase],
          note: out.exitCode === 0 ? undefined : `phase exit ${out.exitCode}`,
        };
        events.push(ev);
        this.sessions.recordEvent(dreamId, ev);
        this.bus.emit({
          type: "dream_progress",
          userId,
          dreamId,
          phase,
          pct: ev.pct,
          note: ev.note,
          at: ev.at,
        });
        if (out.exitCode !== 0) throw new Error(`phase ${phase} failed`);
      }

      filesTouchedAfter = await this.countMd(root);
      const filesUpdated = Math.max(0, filesTouchedAfter - filesTouchedBefore);

      await this.prisma.$transaction([
        this.prisma.dreamRun.update({
          where: { id: dreamRunId },
          data: {
            status: "SUCCEEDED",
            endedAt: new Date(),
            filesUpdated,
            progressJson: events as never,
          },
        }),
        this.prisma.user.update({
          where: { id: userId },
          data: { lastDreamedAt: new Date() },
        }),
      ]);

      this.sessions.closeSession(dreamId, "succeeded");
      this.bus.emit({
        type: "dream_completed",
        userId,
        dreamId,
        filesUpdated,
        at: Date.now(),
      });
    } catch (err) {
      const reason = (err as Error).message ?? "unknown";
      await this.prisma.dreamRun
        .update({
          where: { id: dreamRunId },
          data: {
            status: "FAILED",
            endedAt: new Date(),
            errorMessage: reason,
            progressJson: events as never,
          },
        })
        .catch(() => undefined);
      this.sessions.closeSession(dreamId, "failed");
      this.bus.emit({
        type: "dream_failed",
        userId,
        dreamId,
        reason,
        at: Date.now(),
      });
    } finally {
      await rm(stagingDir, { recursive: true, force: true }).catch(() => undefined);
      await this.lock.release(userId);
    }
  }

  /** Daily-cron entry — runs across all enabled users. */
  async runDailyConsolidation(): Promise<{ users: number; ok: number; failed: number }> {
    if (!this.gates.isEnabled()) return { users: 0, ok: 0, failed: 0 };
    const candidates = await this.prisma.user.findMany({
      where: { autoDreamEnabled: true },
      select: { id: true },
    });
    let ok = 0;
    let failed = 0;
    for (const u of candidates) {
      const r = await this.run(u.id, {
        scope: { kind: "all" },
        trigger: "cron",
        bypassTimeGate: false,
      }).catch((err) => {
        this.logger.warn(`cron user=${u.id} threw: ${(err as Error).message}`);
        return { outcome: "no_eligible_visits" } as RunResult;
      });
      if (r.outcome === "started") ok++;
      else if (r.outcome === "busy") failed++;
    }
    return { users: candidates.length, ok, failed };
  }

  private async collectVisits(
    userId: string,
    scope: DreamScope,
  ): Promise<DreamVisitDescriptor[]> {
    if (scope.kind === "visit") {
      const v = await this.prisma.consultSession.findUnique({
        where: { id: scope.visitId },
        select: { id: true, endedAt: true },
      });
      return v && v.endedAt
        ? [{ visitId: v.id, endedAt: v.endedAt.toISOString() }]
        : [];
    }
    const u = await this.prisma.user.findUnique({
      where: { id: userId },
      select: { lastDreamedAt: true },
    });
    const since = u?.lastDreamedAt ?? new Date(Date.now() - 7 * 86_400_000);
    const rows = await this.prisma.consultSession.findMany({
      where: {
        ownerUserId: userId,
        status: "ENDED",
        endedAt: { gte: since },
      },
      select: { id: true, endedAt: true },
      orderBy: { endedAt: "asc" },
      take: 50,
    });
    return rows.map((r) => ({
      visitId: r.id,
      endedAt: r.endedAt!.toISOString(),
    }));
  }

  private async stashTranscripts(
    stagingDir: string,
    scope: DreamScope,
    userId: string,
  ): Promise<void> {
    const visitIds: string[] = [];
    if (scope.kind === "visit") visitIds.push(scope.visitId);
    else {
      const u = await this.prisma.user.findUnique({
        where: { id: userId },
        select: { lastDreamedAt: true },
      });
      const since = u?.lastDreamedAt ?? new Date(Date.now() - 7 * 86_400_000);
      const rows = await this.prisma.consultSession.findMany({
        where: { ownerUserId: userId, status: "ENDED", endedAt: { gte: since } },
        select: { id: true },
        orderBy: { endedAt: "asc" },
        take: 50,
      });
      visitIds.push(...rows.map((r) => r.id));
    }
    for (const vid of visitIds) {
      const visit = await this.prisma.consultSession.findUnique({
        where: { id: vid },
        select: {
          id: true,
          startedAt: true,
          endedAt: true,
          summaryMd: true,
          utterances: { orderBy: { startedAtMs: "asc" } },
        },
      });
      if (!visit) continue;
      const transcript = visit.utterances
        .map((u) => `[${u.speaker.toLowerCase()} @${u.startedAtMs}ms] ${u.text}`)
        .join("\n");
      const md = `# Visit ${vid}

- started: ${visit.startedAt.toISOString()}
- ended:   ${visit.endedAt?.toISOString() ?? "(open)"}

## Summary

${visit.summaryMd ?? "(no summary)"}

## Transcript

\`\`\`
${transcript.slice(0, 32_000)}
\`\`\`
`;
      await writeFile(join(stagingDir, `${vid}.md`), md, "utf-8");
    }
  }

  private async countMd(root: string): Promise<number> {
    let n = 0;
    const walk = async (dir: string): Promise<void> => {
      let dirents;
      try {
        dirents = await readdir(dir, { withFileTypes: true });
      } catch {
        return;
      }
      for (const d of dirents) {
        if (d.name.startsWith(".")) continue;
        const p = join(dir, d.name);
        if (d.isDirectory()) await walk(p);
        else if (d.isFile() && d.name.endsWith(".md")) {
          try {
            const s = await stat(p);
            n += s.size > 0 ? 1 : 0;
          } catch {
            /* ignore */
          }
        }
      }
    };
    await walk(root);
    return n;
  }
}

function scopeToString(scope: DreamScope): string {
  return scope.kind === "all" ? "all" : `visit:${scope.visitId}`;
}

function triggerEnum(t: DreamTriggerKind): "MANUAL_USER" | "MANUAL_VISIT" | "CRON" {
  if (t === "manual_user") return "MANUAL_USER";
  if (t === "manual_visit") return "MANUAL_VISIT";
  return "CRON";
}
```

- [ ] **Step 2: Update DreamCronService to use the runner**

Replace `backend/src/modules/carenote/swarm/dreamCron.ts` body with:

```ts
// CLARIOSE_V01 §5.1 — daily auto-dream cron.
//
// Cron tick fires DreamRunner.runDailyConsolidation(). The cron expression
// is hard-coded; CARENOTE_DREAM_HOUR is a deprecated env that we still
// log a warning for if set, to avoid silent drift.

import { Injectable, Logger, OnModuleInit } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { Cron } from "@nestjs/schedule";

import { DreamRunner } from "./dream/dream.runner";

const DAILY_AT_0300 = "0 3 * * *";

@Injectable()
export class DreamCronService implements OnModuleInit {
  private readonly logger = new Logger("DreamCron");

  constructor(
    private readonly cfg: ConfigService,
    private readonly runner: DreamRunner,
  ) {}

  onModuleInit(): void {
    const hour = this.cfg.get<string>("CARENOTE_DREAM_HOUR") ?? "3";
    if (hour !== "3") {
      this.logger.warn(
        `CARENOTE_DREAM_HOUR=${hour} but cron is hard-coded to 03:00. Ignoring.`,
      );
    }
    if (this.cfg.get<string>("CARENOTE_DREAM_ENABLED") === "false") {
      this.logger.log("auto-dream disabled — cron will tick but no-op");
    } else {
      this.logger.log(`scheduled daily auto-dream at ${DAILY_AT_0300}`);
    }
  }

  @Cron(DAILY_AT_0300, { name: "carenote.autoDream.daily" })
  async tick(): Promise<void> {
    try {
      const r = await this.runner.runDailyConsolidation();
      this.logger.log(
        `cron tick complete: users=${r.users} ok=${r.ok} failed=${r.failed}`,
      );
    } catch (err) {
      this.logger.error(`cron tick threw: ${(err as Error).message}`);
    }
  }
}
```

- [ ] **Step 3: Delete autoDream.ts and old test**

```bash
rm backend/src/modules/carenote/swarm/autoDream.ts
rm backend/test/carenote/autoDreamGates.spec.ts
```

- [ ] **Step 4: TypeScript check**

Run: `cd backend && npx tsc -p tsconfig.json --noEmit`
Expected: errors only in `carenote.module.ts` and `carenote.controller.ts` (still importing `AutoDreamService` — fixed in Task 11).

- [ ] **Step 5: Commit**

```bash
git add -A backend/src/modules/carenote/swarm/ backend/test/carenote/
git commit -m "feat(dream): runner replaces autoDream; cron now calls runner"
```

---

## Task 10: dream.controller.ts — HTTP + SSE endpoints

**Files:**
- Create: `backend/src/modules/carenote/swarm/dream/dream.controller.ts`

- [ ] **Step 1: Implement controller**

```ts
// backend/src/modules/carenote/swarm/dream/dream.controller.ts
//
// HTTP + SSE surface for the dream runner. All endpoints are JWT-guarded
// and scoped to the current user.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §6.

import {
  Body,
  Controller,
  Get,
  HttpCode,
  HttpException,
  HttpStatus,
  MessageEvent,
  Param,
  Post,
  Query,
  Sse,
  UseGuards,
} from "@nestjs/common";
import { AuthGuard } from "@nestjs/passport";
import { Observable, interval, map, merge, from, concat } from "rxjs";

import {
  AuthedUser,
  CurrentUser,
} from "../../../../common/decorators/current-user.decorator";
import { PrismaService } from "../../../../common/prisma/prisma.service";
import { CarenoteEventBus } from "../eventBus";
import { DreamRunner } from "./dream.runner";
import { DreamSessionRegistry } from "./dream.session";
import { DreamWorkspace } from "./dream.workspace";
import type {
  DreamFileResponse,
  DreamRunSummary,
  DreamTreeResponse,
} from "./dream.types";

@UseGuards(AuthGuard("jwt"))
@Controller("carenote/dream")
export class DreamController {
  constructor(
    private readonly runner: DreamRunner,
    private readonly bus: CarenoteEventBus,
    private readonly sessions: DreamSessionRegistry,
    private readonly workspace: DreamWorkspace,
    private readonly prisma: PrismaService,
  ) {}

  @Post("run")
  @HttpCode(202)
  async runAll(@CurrentUser() user: AuthedUser): Promise<{ dreamId: string }> {
    const r = await this.runner.run(user.id, {
      scope: { kind: "all" },
      trigger: "manual_user",
      bypassTimeGate: true,
    });
    if (r.outcome === "started" && r.dreamId) return { dreamId: r.dreamId };
    if (r.outcome === "no_eligible_visits") {
      throw new HttpException(
        { reason: "no_eligible_visits" },
        HttpStatus.LOCKED,
      );
    }
    if (r.outcome === "busy") {
      throw new HttpException({ reason: "busy" }, HttpStatus.CONFLICT);
    }
    if (r.outcome === "disabled") {
      throw new HttpException(
        { reason: "disabled" },
        HttpStatus.SERVICE_UNAVAILABLE,
      );
    }
    throw new HttpException({ reason: r.outcome }, HttpStatus.BAD_REQUEST);
  }

  @Post("run/visit/:visitId")
  @HttpCode(202)
  async runVisit(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ): Promise<{ dreamId: string }> {
    const r = await this.runner.run(user.id, {
      scope: { kind: "visit", visitId },
      trigger: "manual_visit",
      bypassTimeGate: true,
    });
    if (r.outcome === "started" && r.dreamId) return { dreamId: r.dreamId };
    if (r.outcome === "forbidden") {
      throw new HttpException({ reason: "forbidden" }, HttpStatus.FORBIDDEN);
    }
    if (r.outcome === "busy") {
      throw new HttpException({ reason: "busy" }, HttpStatus.CONFLICT);
    }
    if (r.outcome === "disabled") {
      throw new HttpException(
        { reason: "disabled" },
        HttpStatus.SERVICE_UNAVAILABLE,
      );
    }
    throw new HttpException({ reason: r.outcome }, HttpStatus.BAD_REQUEST);
  }

  @Get("runs")
  async listRuns(@CurrentUser() user: AuthedUser): Promise<DreamRunSummary[]> {
    const rows = await this.prisma.dreamRun.findMany({
      where: { userId: user.id },
      orderBy: { startedAt: "desc" },
      take: 20,
    });
    return rows.map((r) => ({
      id: r.id,
      scope: r.scope,
      trigger: triggerToKind(r.trigger),
      status: r.status.toLowerCase() as DreamRunSummary["status"],
      startedAt: r.startedAt.toISOString(),
      endedAt: r.endedAt?.toISOString() ?? null,
      visitCount: r.visitCount,
      filesUpdated: r.filesUpdated,
      errorMessage: r.errorMessage ?? null,
    }));
  }

  @Get("tree")
  async tree(@CurrentUser() user: AuthedUser): Promise<DreamTreeResponse> {
    const root = this.workspace.rootForUser(user.id);
    const u = await this.prisma.user.findUnique({
      where: { id: user.id },
      select: { lastDreamedAt: true },
    });
    const nodes = await this.workspace.walkTree(user.id);
    return {
      root,
      lastDreamedAt: u?.lastDreamedAt?.toISOString() ?? null,
      nodes,
    };
  }

  @Get("file")
  async file(
    @CurrentUser() user: AuthedUser,
    @Query("path") path?: string,
  ): Promise<DreamFileResponse> {
    if (!path || typeof path !== "string") {
      throw new HttpException({ reason: "missing_path" }, HttpStatus.BAD_REQUEST);
    }
    try {
      const r = await this.workspace.readFile(user.id, path);
      return {
        path,
        content: r.content,
        mtime: r.mtime,
        bytes: r.bytes,
      };
    } catch (err) {
      throw new HttpException(
        { reason: (err as Error).message },
        HttpStatus.BAD_REQUEST,
      );
    }
  }

  @Sse("events")
  events(@CurrentUser() user: AuthedUser): Observable<MessageEvent> {
    const open = this.sessions.findOpen(user.id);
    const replay = open
      ? from(
          this.sessions.replayBuffer(open.dreamId).map(
            (ev) =>
              ({
                type: "dream_progress",
                data: {
                  type: "dream_progress",
                  dreamId: open.dreamId,
                  userId: user.id,
                  phase: ev.phase,
                  pct: ev.pct,
                  note: ev.note,
                  at: ev.at,
                },
              }) as MessageEvent,
          ),
        )
      : from([] as MessageEvent[]);

    const live = this.bus.streamForUser(user.id).pipe(
      map(
        (e): MessageEvent => ({
          type: e.type,
          data: e,
        }),
      ),
    );

    const heartbeat = interval(15_000).pipe(
      map(
        (): MessageEvent => ({
          type: "heartbeat",
          data: { ts: Date.now() },
        }),
      ),
    );

    return merge(concat(replay, live), heartbeat);
  }
}

function triggerToKind(t: string): DreamRunSummary["trigger"] {
  if (t === "MANUAL_USER") return "manual_user";
  if (t === "MANUAL_VISIT") return "manual_visit";
  return "cron";
}
```

- [ ] **Step 2: TypeScript check**

Run: `cd backend && npx tsc -p tsconfig.json --noEmit`
Expected: only the carenote.module.ts and carenote.controller.ts errors persisting.

- [ ] **Step 3: Commit**

```bash
git add backend/src/modules/carenote/swarm/dream/dream.controller.ts
git commit -m "feat(dream): HTTP + SSE controller"
```

---

## Task 11: Module wiring + remove old admin endpoint

**Files:**
- Modify: `backend/src/modules/carenote/api/carenote.module.ts`
- Modify: `backend/src/modules/carenote/api/carenote.controller.ts`

- [ ] **Step 1: Edit `carenote.module.ts`**

Replace the auto-dream section (the imports + the providers array entries):

Find:
```ts
// CLARIOSE_V01 §5 — auto-dream daily memory consolidation.
import { ConsolidationLockService } from "../swarm/consolidationLock";
import { AutoDreamService } from "../swarm/autoDream";
import { DreamCronService } from "../swarm/dreamCron";
```

Replace with:
```ts
// CLARIOSE_V03 §dream — auto + manual memory consolidation.
import { ConsolidationLockService } from "../swarm/consolidationLock";
import { DreamCronService } from "../swarm/dreamCron";
import { DreamGates } from "../swarm/dream/dream.gates";
import { DreamWorkspace } from "../swarm/dream/dream.workspace";
import { DreamSessionRegistry } from "../swarm/dream/dream.session";
import { DreamCodexFork } from "../swarm/dream/dream.codexFork";
import { DreamRunner } from "../swarm/dream/dream.runner";
import { DreamController } from "../swarm/dream/dream.controller";
```

In the `controllers` array, append `DreamController`:

```ts
  controllers: [
    CareNoteVisitsController,
    CareNoteRealtimeController,
    TasksController,
    DreamController,
  ],
```

In the `providers` array, find:
```ts
    // auto-dream
    ConsolidationLockService,
    AutoDreamService,
    DreamCronService,
```

Replace with:
```ts
    // dream (auto + manual)
    ConsolidationLockService,
    DreamGates,
    DreamWorkspace,
    DreamSessionRegistry,
    DreamCodexFork,
    DreamRunner,
    DreamCronService,
```

In the `exports` array, replace `AutoDreamService,` with `DreamRunner,`:

```ts
  exports: [
    CareNoteService,
    CarenoteEventBus,
    MemoryRecallService,
    MailboxService,
    BlackboardService,
    DraftTasksService,
    DreamRunner,
    TeamRecapService,
    CarenoteRuntimeModule,
  ],
```

- [ ] **Step 2: Edit `carenote.controller.ts` — remove old admin route**

Remove the line:
```ts
import { AutoDreamService } from "../swarm/autoDream";
```

Remove the constructor injection:
```ts
    private readonly autoDream: AutoDreamService,
```

Remove the route:
```ts
  // CLARIOSE_V01 §5 — manual auto-dream trigger. Admin-only; the daily cron
  // is the normal path. Useful when seeding a new user's memory or during
  // ops debugging.
  @Post("admin/auto-dream/run")
  async runAutoDream(@CurrentUser() user: AuthedUser) {
    if (user.role !== "ADMIN") {
      throw new ForbiddenException("admin only");
    }
    return this.autoDream.runDailyConsolidation();
  }
```

- [ ] **Step 3: TypeScript check**

Run: `cd backend && npx tsc -p tsconfig.json --noEmit`
Expected: 0 errors.

- [ ] **Step 4: Run all carenote tests**

Run: `cd backend && npm run carenote:test`
Expected: dream tests pass; everything else still passes.

- [ ] **Step 5: Commit**

```bash
git add backend/src/modules/carenote/api/carenote.module.ts backend/src/modules/carenote/api/carenote.controller.ts
git commit -m "feat(dream): wire DreamController + DreamRunner; drop AutoDreamService"
```

---

## Task 12: Frontend useDream composable

**Files:**
- Create: `frontend/composables/useDream.ts`

- [ ] **Step 1: Implement composable**

```ts
// frontend/composables/useDream.ts
//
// Drives the dream sidebar + viewer:
//   - run / runVisit POSTs to /api/carenote/dream/run[/visit/:vid]
//   - subscribes to /api/carenote/dream/events SSE for progress
//   - reloads /tree on dream_completed; opens individual files via /file
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §8.2.

import { computed, onBeforeUnmount, ref } from "vue";
import { useApi } from "./useApi";

export type DreamStatus = "idle" | "running" | "success" | "failed";

export interface DreamProgressView {
  dreamId: string;
  phase: "orient" | "gather" | "consolidate" | "prune";
  pct: number;
  visitCount: number;
  note?: string;
}

export interface DreamRunSummary {
  id: string;
  scope: string;
  trigger: "manual_user" | "manual_visit" | "cron";
  status: "running" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  endedAt: string | null;
  visitCount: number;
  filesUpdated: number;
  errorMessage: string | null;
}

export interface DreamTreeNode {
  name: string;
  path: string;
  kind: "dir" | "file";
  children?: DreamTreeNode[];
  mtime?: string;
  bytes?: number;
  visitId?: string;
}

export function useDream() {
  const api = useApi();

  const status = ref<DreamStatus>("idle");
  const current = ref<DreamProgressView | null>(null);
  const lastFinishedAt = ref<string | null>(null);
  const lastFilesUpdated = ref(0);
  const lastError = ref<string | null>(null);

  const tree = ref<DreamTreeNode[]>([]);
  const treeRoot = ref<string>("");
  const lastDreamedAt = ref<string | null>(null);

  const selectedPath = ref<string | null>(null);
  const selectedContent = ref<string | null>(null);
  const selectedMeta = ref<{ mtime: string; bytes: number } | null>(null);
  const viewerLoading = ref(false);
  const viewerError = ref<string | null>(null);

  const runs = ref<DreamRunSummary[]>([]);

  let eventSource: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  async function refreshTree(): Promise<void> {
    const r = await api.call<{ root: string; lastDreamedAt: string | null; nodes: DreamTreeNode[] }>(
      "/carenote/dream/tree",
      { method: "GET" },
    );
    tree.value = r.nodes;
    treeRoot.value = r.root;
    lastDreamedAt.value = r.lastDreamedAt;
  }

  async function refreshRuns(): Promise<void> {
    runs.value = await api.call<DreamRunSummary[]>("/carenote/dream/runs", { method: "GET" });
  }

  async function openFile(path: string): Promise<void> {
    selectedPath.value = path;
    selectedContent.value = null;
    selectedMeta.value = null;
    viewerError.value = null;
    viewerLoading.value = true;
    try {
      const r = await api.call<{ content: string; mtime: string; bytes: number }>(
        `/carenote/dream/file?path=${encodeURIComponent(path)}`,
        { method: "GET" },
      );
      selectedContent.value = r.content;
      selectedMeta.value = { mtime: r.mtime, bytes: r.bytes };
    } catch (err) {
      viewerError.value = (err as Error).message;
    } finally {
      viewerLoading.value = false;
    }
  }

  async function run(): Promise<void> {
    lastError.value = null;
    try {
      const r = await api.call<{ dreamId: string }>("/carenote/dream/run", { method: "POST" });
      status.value = "running";
      current.value = {
        dreamId: r.dreamId,
        phase: "orient",
        pct: 0,
        visitCount: 0,
      };
    } catch (err) {
      status.value = "failed";
      lastError.value = (err as Error).message;
    }
  }

  async function runVisit(visitId: string): Promise<void> {
    lastError.value = null;
    try {
      const r = await api.call<{ dreamId: string }>(
        `/carenote/dream/run/visit/${encodeURIComponent(visitId)}`,
        { method: "POST" },
      );
      status.value = "running";
      current.value = {
        dreamId: r.dreamId,
        phase: "orient",
        pct: 0,
        visitCount: 1,
      };
    } catch (err) {
      status.value = "failed";
      lastError.value = (err as Error).message;
    }
  }

  function connect(): void {
    if (typeof window === "undefined") return;
    const token = api.getToken();
    if (!token) return;
    eventSource?.close();
    const url = `/api/carenote/dream/events?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    eventSource = es;

    es.addEventListener("dream_started", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      status.value = "running";
      current.value = {
        dreamId: d.dreamId,
        phase: "orient",
        pct: 0,
        visitCount: d.visitCount,
      };
    });
    es.addEventListener("dream_progress", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      if (current.value && current.value.dreamId === d.dreamId) {
        current.value.phase = d.phase;
        current.value.pct = d.pct;
        current.value.note = d.note;
      } else {
        current.value = {
          dreamId: d.dreamId,
          phase: d.phase,
          pct: d.pct,
          visitCount: 0,
          note: d.note,
        };
        status.value = "running";
      }
    });
    es.addEventListener("dream_completed", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      status.value = "success";
      lastFinishedAt.value = new Date(d.at).toISOString();
      lastFilesUpdated.value = d.filesUpdated;
      current.value = null;
      void refreshTree();
      void refreshRuns();
      if (selectedPath.value) void openFile(selectedPath.value);
    });
    es.addEventListener("dream_failed", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      status.value = "failed";
      lastError.value = d.reason;
      current.value = null;
    });

    es.onerror = () => {
      es.close();
      eventSource = null;
      reconnectTimer = setTimeout(connect, 2_000);
    };
  }

  function disconnect(): void {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    eventSource?.close();
    eventSource = null;
  }

  onBeforeUnmount(disconnect);

  return {
    status: computed(() => status.value),
    current: computed(() => current.value),
    lastFinishedAt: computed(() => lastFinishedAt.value),
    lastFilesUpdated: computed(() => lastFilesUpdated.value),
    lastError: computed(() => lastError.value),
    tree: computed(() => tree.value),
    treeRoot: computed(() => treeRoot.value),
    lastDreamedAt: computed(() => lastDreamedAt.value),
    runs: computed(() => runs.value),
    selectedPath: computed(() => selectedPath.value),
    selectedContent: computed(() => selectedContent.value),
    selectedMeta: computed(() => selectedMeta.value),
    viewerLoading: computed(() => viewerLoading.value),
    viewerError: computed(() => viewerError.value),
    run,
    runVisit,
    refreshTree,
    refreshRuns,
    openFile,
    connect,
    disconnect,
  };
}
```

- [ ] **Step 2: Verify `useApi` exposes `getToken` (or add it)**

Run: `grep -n "getToken\|return\s\+{" /home/ubuntu/Zai/frontend/composables/useApi.ts | head -10`
If `getToken` is missing, add a thin wrapper that returns the auth-store token. The existing `useRecallChat.ts` already uses an `EventSource` with `?token=`; mirror its approach. (If `useApi` exposes `token` directly, replace `api.getToken()` with `api.token.value` in the composable above.)

- [ ] **Step 3: Commit**

```bash
git add frontend/composables/useDream.ts
git commit -m "feat(dream): useDream composable (SSE + tree + viewer)"
```

---

## Task 13: Frontend DreamSidebar + DreamTreeNode + DreamViewer

**Files:**
- Create: `frontend/components/recall/DreamSidebar.vue`
- Create: `frontend/components/recall/DreamTreeNode.vue`
- Create: `frontend/components/recall/DreamViewer.vue`

- [ ] **Step 1: DreamTreeNode.vue (recursive)**

```vue
<script setup lang="ts">
import type { DreamTreeNode } from "~/composables/useDream";

defineProps<{
  node: DreamTreeNode;
  depth: number;
  selectedPath: string | null;
  busy: boolean;
}>();
const emit = defineEmits<{
  open: [path: string];
  redream: [visitId: string];
}>();

function clickFile(path: string): void {
  emit("open", path);
}
function clickRedream(visitId: string): void {
  emit("redream", visitId);
}
</script>

<template>
  <li class="dream-tree-node">
    <template v-if="node.kind === 'dir'">
      <details open class="dream-tree-dir">
        <summary :style="{ paddingLeft: `${depth * 12}px` }">
          <span aria-hidden="true">📁</span>
          <span class="dream-tree-name">{{ node.name }}</span>
          <span v-if="node.children" class="dream-tree-count">({{ node.children.length }})</span>
        </summary>
        <ul class="dream-tree-children">
          <DreamTreeNode
            v-for="c in node.children ?? []"
            :key="c.path"
            :node="c"
            :depth="depth + 1"
            :selected-path="selectedPath"
            :busy="busy"
            @open="(p) => emit('open', p)"
            @redream="(v) => emit('redream', v)"
          />
        </ul>
      </details>
    </template>
    <template v-else>
      <button
        class="dream-tree-file"
        :class="{ 'is-selected': selectedPath === node.path }"
        :style="{ paddingLeft: `${depth * 12 + 6}px` }"
        @click="clickFile(node.path)"
      >
        <span aria-hidden="true">📄</span>
        <span class="dream-tree-name">{{ node.name }}</span>
        <button
          v-if="node.visitId"
          type="button"
          class="dream-redream-btn"
          :disabled="busy"
          :title="busy ? 'Another dream is running' : `Re-dream ${node.visitId}`"
          @click.stop="clickRedream(node.visitId!)"
        >↻</button>
      </button>
    </template>
  </li>
</template>

<style scoped>
.dream-tree-node { list-style: none; }
.dream-tree-children { list-style: none; padding: 0; margin: 0; }
.dream-tree-dir summary {
  cursor: pointer;
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 0.86rem;
  padding: 2px 4px;
}
.dream-tree-file {
  appearance: none;
  background: transparent;
  border: 0;
  display: flex;
  gap: 6px;
  align-items: center;
  width: 100%;
  text-align: left;
  font-size: 0.86rem;
  padding: 3px 6px;
  cursor: pointer;
  border-radius: 4px;
  color: inherit;
}
.dream-tree-file.is-selected { background: rgba(99, 102, 241, 0.15); }
.dream-tree-file:hover { background: rgba(0, 0, 0, 0.04); }
.dream-tree-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dream-tree-count { color: rgba(0, 0, 0, 0.4); font-size: 0.78rem; }
.dream-redream-btn {
  appearance: none;
  background: transparent;
  border: 1px solid rgba(0, 0, 0, 0.15);
  border-radius: 4px;
  font-size: 0.7rem;
  padding: 0 5px;
  cursor: pointer;
  color: inherit;
}
.dream-redream-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
```

- [ ] **Step 2: DreamSidebar.vue**

```vue
<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useDream } from "~/composables/useDream";
import DreamTreeNode from "./DreamTreeNode.vue";

const dream = useDream();

const isBusy = computed(() => dream.status.value === "running");

const lastDreamedLabel = computed(() => {
  const t = dream.lastDreamedAt.value;
  if (!t) return "never";
  const ms = Date.now() - new Date(t).getTime();
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
});

const progressLabel = computed(() => {
  const c = dream.current.value;
  if (!c) return null;
  return `${c.phase} · ${c.pct}%`;
});

onMounted(async () => {
  dream.connect();
  await Promise.all([dream.refreshTree(), dream.refreshRuns()]);
});

function onOpen(path: string): void {
  void dream.openFile(path);
}
function onRedream(visitId: string): void {
  if (isBusy.value) return;
  void dream.runVisit(visitId);
}
async function onDreamNow(): Promise<void> {
  if (isBusy.value) return;
  await dream.run();
}
</script>

<template>
  <aside class="dream-sidebar">
    <div class="dream-sidebar-head">
      <button
        class="dream-now-btn"
        :disabled="isBusy"
        :title="isBusy ? 'Already running' : 'Dream all my recent visits'"
        @click="onDreamNow"
      >
        <span aria-hidden="true">✨</span>
        <span>{{ isBusy ? "Dreaming…" : "Dream now" }}</span>
      </button>
      <p class="dream-sidebar-meta">
        <span>Last: <strong>{{ lastDreamedLabel }}</strong></span>
        <span v-if="progressLabel"> · {{ progressLabel }}</span>
        <span v-else-if="dream.lastFilesUpdated.value > 0"> · {{ dream.lastFilesUpdated.value }} files</span>
      </p>
      <p v-if="dream.lastError.value" class="dream-sidebar-error">
        {{ dream.lastError.value }}
      </p>
    </div>
    <ul class="dream-sidebar-tree">
      <DreamTreeNode
        v-for="n in dream.tree.value"
        :key="n.path"
        :node="n"
        :depth="0"
        :selected-path="dream.selectedPath.value"
        :busy="isBusy"
        @open="onOpen"
        @redream="onRedream"
      />
    </ul>
    <p v-if="dream.tree.value.length === 0" class="dream-sidebar-empty">
      No memory yet. Click "Dream now" after a visit ends.
    </p>
  </aside>
</template>

<style scoped>
.dream-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  padding: 14px 12px;
  border-right: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.5);
}
.dream-sidebar-head { display: flex; flex-direction: column; gap: 6px; }
.dream-now-btn {
  appearance: none;
  border: 0;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  padding: 9px 12px;
  border-radius: 8px;
  font-weight: 600;
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.dream-now-btn:disabled { opacity: 0.55; cursor: progress; }
.dream-sidebar-meta { font-size: 0.78rem; color: rgba(0, 0, 0, 0.55); margin: 0; }
.dream-sidebar-error { font-size: 0.78rem; color: #b91c1c; margin: 0; }
.dream-sidebar-tree { list-style: none; padding: 0; margin: 0; overflow-y: auto; flex: 1; }
.dream-sidebar-empty { font-size: 0.82rem; color: rgba(0, 0, 0, 0.5); margin: 12px 6px; }
</style>
```

- [ ] **Step 3: DreamViewer.vue**

```vue
<script setup lang="ts">
import { computed } from "vue";
import { onMarkdownCopyClick, renderMarkdown } from "~/utils/recallMarkdown";
import { useDream } from "~/composables/useDream";

const dream = useDream();

const html = computed(() => {
  const c = dream.selectedContent.value;
  if (!c) return "";
  return renderMarkdown(c);
});

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString();
}
</script>

<template>
  <section class="dream-viewer">
    <header v-if="dream.selectedPath.value" class="dream-viewer-head">
      <h2>{{ dream.selectedPath.value }}</h2>
      <p v-if="dream.selectedMeta.value" class="dream-viewer-meta">
        {{ fmtTime(dream.selectedMeta.value.mtime) }} · {{ fmtBytes(dream.selectedMeta.value.bytes) }}
      </p>
    </header>
    <div v-if="dream.viewerLoading.value" class="dream-viewer-empty">Loading…</div>
    <div v-else-if="dream.viewerError.value" class="dream-viewer-empty is-error">
      {{ dream.viewerError.value }}
    </div>
    <div
      v-else-if="dream.selectedPath.value && html"
      class="dream-viewer-body"
      v-html="html"
      @click="onMarkdownCopyClick"
    />
    <div v-else class="dream-viewer-empty">
      Select a memory file from the left to view.
    </div>
  </section>
</template>

<style scoped>
.dream-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 18px 22px;
  overflow-y: auto;
}
.dream-viewer-head { margin-bottom: 12px; border-bottom: 1px solid rgba(0, 0, 0, 0.08); padding-bottom: 8px; }
.dream-viewer-head h2 { font-size: 1rem; margin: 0; font-family: ui-monospace, monospace; color: rgba(0, 0, 0, 0.7); }
.dream-viewer-meta { font-size: 0.74rem; color: rgba(0, 0, 0, 0.45); margin: 4px 0 0 0; }
.dream-viewer-body { line-height: 1.55; font-size: 0.92rem; }
.dream-viewer-body :deep(h1) { font-size: 1.4rem; margin-top: 0; }
.dream-viewer-body :deep(pre) { background: rgba(0, 0, 0, 0.045); padding: 10px 12px; border-radius: 6px; overflow-x: auto; }
.dream-viewer-empty { color: rgba(0, 0, 0, 0.45); font-size: 0.88rem; padding: 40px 0; text-align: center; }
.dream-viewer-empty.is-error { color: #b91c1c; }
</style>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/components/recall/DreamSidebar.vue frontend/components/recall/DreamTreeNode.vue frontend/components/recall/DreamViewer.vue
git commit -m "feat(dream): sidebar + tree node + viewer components"
```

---

## Task 14: Frontend pages/recall/index.vue — wire new sidebar + viewer

**Files:**
- Modify: `frontend/pages/recall/index.vue`

The existing page uses `useRecallNotes` for left filters and the middle column for a notes browser; the right column hosts the codex chat. We rewire:
- Left rail → `<DreamSidebar />`
- Middle column → `<DreamViewer />` (when a dream file is selected) OR existing notes browser (default)
- Right rail → unchanged (codex chat)

We **keep** the notes upload path because users may still want to upload custom MD; the dream viewer simply takes priority when a dream file is selected.

- [ ] **Step 1: Edit `frontend/pages/recall/index.vue`**

Add imports near the top of `<script setup>`:

```ts
import DreamSidebar from "~/components/recall/DreamSidebar.vue";
import DreamViewer from "~/components/recall/DreamViewer.vue";
import { useDream } from "~/composables/useDream";

const dream = useDream();
const showDreamViewer = computed(() => !!dream.selectedPath.value);
```

In the template, replace the existing left-rail (filter chips) with `<DreamSidebar />`. The exact selector of the left rail is the first `<aside>` or column wrapper in the existing template — replace its inner content with the component while keeping the outer column container. If the existing notes filter UI lives inline (not as a sub-component), wrap it in a `v-if="false"` block first so the bisect is small, then delete on commit.

In the middle column, render `<DreamViewer v-if="showDreamViewer" />` BEFORE the existing notes browser; existing notes UI stays as the fallback (`v-else`).

- [ ] **Step 2: Smoke**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/recall/index.vue
git commit -m "feat(dream): wire DreamSidebar + DreamViewer into /recall"
```

---

## Task 15: Final verification + smoke

- [ ] **Step 1: Backend type-check + tests**

```bash
cd backend
npx tsc -p tsconfig.json --noEmit
npm run carenote:test
```

Expected: 0 type errors; all carenote tests (existing + new dream tests) pass.

- [ ] **Step 2: Frontend build**

```bash
cd frontend
npm run build
```

Expected: build succeeds.

- [ ] **Step 3: Local end-to-end (dev)**

In two terminals:
```bash
cd backend && npm run dev
cd frontend && npm run dev
```

Browser: log in as a patient who has at least one ENDED visit, navigate to `/recall`, click ✨ Dream now, watch the SSE progress. After completion the left tree shows MEMORY.md / memory_summary.md / rollout_summaries/. Click a file → middle pane renders. Click `[↻]` on a `rollout_<vid>.md` → only that file's mtime advances.

If `OPENAI_API_KEY` is unset OR `codex` CLI is not installed, the dream phase will fail with a non-zero exit code and the SSE stream emits `dream_failed`. That's expected; verify the UI shows the error.

- [ ] **Step 4: Commit any incidental fixes**

```bash
git status
git add -A
git commit -m "chore(dream): smoke fixes" || echo "nothing to commit"
```

---

## Self-review notes (filled by author)

- **Spec coverage**: §1 manual entry → Task 10. §1 sidebar → Tasks 12-14. §3 architecture decisions → all reflected. §4 component graph → Tasks 4-10. §5 module structure → Tasks 3-11. §5.1 schema → Task 1. §6 API → Task 10. §7 4-phase prompt → Task 7. §8 frontend → Tasks 12-14. §9 error handling → controller HTTP statuses + SSE error event. §10 test strategy → unit tests in 4-7, e2e is the manual smoke in Task 15.
- **Placeholder scan**: no TBD/TODO/"add appropriate"; every code step is a complete code block.
- **Type consistency**: `DreamPhase`, `DreamScope`, `DreamProgressEvent`, `TreeNode`, `DreamTreeNode` (frontend echo) all defined once and reused. `DreamRunner.run` returns `RunResult` with `outcome` enum used identically in `DreamController`.
