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
  DreamProgressEvent,
  DreamScope,
  DreamTriggerKind,
} from "./dream.types";

interface RunOptions {
  scope: DreamScope;
  trigger: DreamTriggerKind;
  bypassTimeGate: boolean;
}

interface RunResult {
  outcome:
    | "started"
    | "no_eligible_visits"
    | "busy"
    | "disabled"
    | "forbidden"
    | "empty_visit";
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
const VISIT_FETCH_LIMIT = 50;
const DEFAULT_LOOKBACK_DAYS = 7;

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

    if (!opts.bypassTimeGate) {
      const u = await this.prisma.user.findUnique({
        where: { id: userId },
        select: { lastDreamedAt: true },
      });
      if (u?.lastDreamedAt) {
        const hoursSince = (Date.now() - u.lastDreamedAt.getTime()) / 3_600_000;
        if (hoursSince < MIN_HOURS_SINCE_LAST) {
          return { outcome: "no_eligible_visits" };
        }
      }
    }

    if (opts.scope.kind === "all") {
      // Cron honors `lastDreamedAt` so it does not redundantly re-process
      // the same window every night. Manual ("Dream now") doesn't — the
      // user is explicitly asking us to consolidate, so we accept any
      // ENDED visit ever. Without this, a user who has dreamed once and
      // then has no new visits is permanently stuck on `no_eligible_visits`.
      const since = opts.bypassTimeGate
        ? null
        : (
            await this.prisma.user.findUnique({
              where: { id: userId },
              select: { lastDreamedAt: true },
            })
          )?.lastDreamedAt ?? null;
      const ok = await this.gates.hasEligibleVisits(userId, since);
      if (!ok) return { outcome: "no_eligible_visits" };
    } else {
      const ok = await this.gates.isVisitOwnedAndEnded(opts.scope.visitId, userId);
      if (!ok) return { outcome: "forbidden" };
    }

    const acquired = await this.lock.acquire(userId);
    if (!acquired) return { outcome: "busy" };

    const visits = await this.collectVisits(userId, opts.scope, opts.bypassTimeGate);
    // After collection: if every candidate visit was filtered out by the
    // empty-content rule, there's nothing for the codex agent to read —
    // running the 4-phase pipeline would just produce stub
    // rollout_summaries that say "no clinical content". Bail early with
    // a distinct outcome so the controller can return a useful 422 and
    // the user sees "empty_visit" / "no_eligible_visits" cleanly.
    if (visits.length === 0) {
      await this.lock.release(userId);
      return {
        outcome: opts.scope.kind === "visit" ? "empty_visit" : "no_eligible_visits",
      };
    }
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

    void this.executeAsync(
      userId,
      dreamId,
      dreamRun.id,
      opts.scope,
      visits,
      opts.bypassTimeGate,
    ).catch((err) => {
      this.logger.error(
        `dream ${dreamId} unhandled: ${(err as Error).message}`,
      );
    });

    return { outcome: "started", dreamId };
  }

  private async executeAsync(
    userId: string,
    dreamId: string,
    dreamRunId: string,
    scope: DreamScope,
    visits: DreamVisitDescriptor[],
    manual: boolean,
  ): Promise<void> {
    const events: DreamProgressEvent[] = [];
    const root = await this.workspace.ensureRoot(userId);
    const stagingDir = join(root, ".dream-staging", dreamId);
    let threadId: string | null = null;
    let filesTouchedBefore = 0;
    let filesTouchedAfter = 0;

    try {
      await mkdir(stagingDir, { recursive: true });
      await this.stashTranscripts(stagingDir, scope, userId, manual);
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

        if (out.exitCode !== 0) {
          // Surface the codex CLI's own error tail so failures like
          // "unexpected argument '--sandbox'" don't degrade to a bare
          // "phase X failed" string in the SSE/UI.
          const tail = out.stderrTail
            ? out.stderrTail.split("\n").find((l) => l.trim().length > 0) ??
              out.stderrTail
            : "";
          throw new Error(
            tail
              ? `phase ${phase} failed: ${tail.slice(0, 200)}`
              : `phase ${phase} failed (exit ${out.exitCode})`,
          );
        }
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
  async runDailyConsolidation(): Promise<{
    users: number;
    ok: number;
    failed: number;
  }> {
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
        this.logger.warn(
          `cron user=${u.id} threw: ${(err as Error).message}`,
        );
        return { outcome: "no_eligible_visits" } as RunResult;
      });
      if (r.outcome === "started") ok++;
      else if (r.outcome === "busy") failed++;
    }
    return { users: candidates.length, ok, failed };
  }

  /** Lookback cutoff for which visits a `scope: "all"` run pulls in.
   *  - manual: always 7 days back from now (the user is explicitly asking
   *    to consolidate; honoring `lastDreamedAt` would silently produce
   *    empty runs after the first dream)
   *  - cron:   `lastDreamedAt` if present, else 7 days back (so the first
   *    cron pass on a fresh user still has scope) */
  private async lookbackSince(userId: string, manual: boolean): Promise<Date> {
    const fallback = new Date(Date.now() - DEFAULT_LOOKBACK_DAYS * 86_400_000);
    if (manual) return fallback;
    const u = await this.prisma.user.findUnique({
      where: { id: userId },
      select: { lastDreamedAt: true },
    });
    return u?.lastDreamedAt ?? fallback;
  }

  private async collectVisits(
    userId: string,
    scope: DreamScope,
    manual: boolean,
  ): Promise<DreamVisitDescriptor[]> {
    if (scope.kind === "visit") {
      const v = await this.prisma.consultSession.findUnique({
        where: { id: scope.visitId },
        select: {
          id: true,
          endedAt: true,
          summaryMd: true,
          // Use the relational count, not consult_sessions.utteranceCount,
          // which has been observed to drift (counter incremented during
          // a live session, then rows got purged on disconnect without
          // decrementing). See dream.controller.ts:visits() for context.
          _count: { select: { utterances: true } },
        },
      });
      if (!v || !v.endedAt) return [];
      // Per-visit dream on a visit with no transcript and no summary
      // would just produce a stub. Reject it so the user sees a clean
      // "empty_visit" outcome instead of a wasted codex run.
      if (v._count.utterances === 0 && !v.summaryMd) return [];
      return [{ visitId: v.id, endedAt: v.endedAt.toISOString() }];
    }
    const since = await this.lookbackSince(userId, manual);
    const rows = await this.prisma.consultSession.findMany({
      where: {
        ownerUserId: userId,
        status: "ENDED",
        endedAt: { gte: since },
        OR: [
          { utterances: { some: {} } },
          { summaryMd: { not: null } },
        ],
      },
      select: { id: true, endedAt: true },
      orderBy: { endedAt: "asc" },
      take: VISIT_FETCH_LIMIT,
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
    manual: boolean,
  ): Promise<void> {
    const visitIds: string[] = [];
    if (scope.kind === "visit") {
      visitIds.push(scope.visitId);
    } else {
      const since = await this.lookbackSince(userId, manual);
      const rows = await this.prisma.consultSession.findMany({
        where: {
          ownerUserId: userId,
          status: "ENDED",
          endedAt: { gte: since },
        },
        select: { id: true },
        orderBy: { endedAt: "asc" },
        take: VISIT_FETCH_LIMIT,
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
        .map(
          (u) =>
            `[${u.speaker.toLowerCase()} @${u.startedAtMs}ms] ${u.text}`,
        )
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
            if (s.size > 0) n++;
          } catch {
            /* ignore unreadable file */
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

function triggerEnum(
  t: DreamTriggerKind,
): "MANUAL_USER" | "MANUAL_VISIT" | "CRON" {
  if (t === "manual_user") return "MANUAL_USER";
  if (t === "manual_visit") return "MANUAL_VISIT";
  return "CRON";
}
