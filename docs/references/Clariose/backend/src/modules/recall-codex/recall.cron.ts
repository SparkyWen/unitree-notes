// RecallCron — daily scheduler for Phase 1 / Phase 2 across all users.
// Runs once a day (default 03:15) but is also exposed as a manual
// `runOnce()` so an admin endpoint or test can trigger it.
//
// Eligibility rule (matches Codex source defaults):
//   - session.endedAt IS NOT NULL OR session.lastTurnAt < NOW() - 6h
//   - session created within the last 30 days
//   - no Phase1Job row yet (or one in 'failed' that's older than 24h)

import { Injectable, Logger } from "@nestjs/common";
import { Cron } from "@nestjs/schedule";

import { PrismaService } from "../../common/prisma/prisma.service";
import {
  PHASE1_MAX_PER_RUN,
  PHASE1_MAX_ROLLOUT_AGE_DAYS,
  PHASE1_MIN_IDLE_HOURS,
  RECALL_CRON_EXPR,
} from "./recall.constants";
import { Phase1Worker } from "./phase1.worker";
import { Phase2Worker } from "./phase2.worker";

@Injectable()
export class RecallCron {
  private readonly logger = new Logger("RecallCron");

  constructor(
    private readonly prisma: PrismaService,
    private readonly phase1: Phase1Worker,
    private readonly phase2: Phase2Worker,
  ) {}

  @Cron(RECALL_CRON_EXPR, { name: "recall:phase1+phase2" })
  async tick(): Promise<void> {
    await this.runOnce();
  }

  /** Public so an admin route or test can fire the pipeline on demand. */
  async runOnce(): Promise<{ enqueued: number; usersTouched: number }> {
    const enqueued = await this.enqueueEligible();

    // Process Phase-1 jobs per user, then trigger Phase-2 once per user
    // that had at least one done job. Doing it sequentially per user keeps
    // resource use bounded; with one user this is moot.
    const users = await this.prisma.user.findMany({
      where: { recallSessions: { some: { rolloutJobs: { some: { state: { in: ["pending", "leased"] } } } } } },
      select: { id: true },
    });
    let touched = 0;
    for (const u of users) {
      try {
        const processed = await this.phase1.processBatch(u.id, PHASE1_MAX_PER_RUN);
        if (processed > 0) {
          await this.phase2.run(u.id).catch((err) => {
            this.logger.warn(`phase2 user=${u.id}: ${(err as Error).message}`);
          });
        }
        touched++;
      } catch (err) {
        this.logger.warn(`recall cron user=${u.id}: ${(err as Error).message}`);
      }
    }
    return { enqueued, usersTouched: touched };
  }

  private async enqueueEligible(): Promise<number> {
    const now = new Date();
    const idleSince = new Date(now.getTime() - PHASE1_MIN_IDLE_HOURS * 60 * 60 * 1000);
    const ageCutoff = new Date(now.getTime() - PHASE1_MAX_ROLLOUT_AGE_DAYS * 24 * 60 * 60 * 1000);

    const eligible = await this.prisma.recallSession.findMany({
      where: {
        createdAt: { gte: ageCutoff },
        OR: [
          { endedAt: { not: null } },
          { lastTurnAt: { lt: idleSince } },
        ],
        messageCount: { gte: 2 }, // need at least one user + one assistant turn
        rolloutJobs: { none: {} },
      },
      select: { id: true, userId: true },
      take: 256,
    });

    let n = 0;
    for (const s of eligible) {
      try {
        await this.prisma.phase1Job.create({
          data: {
            userId: s.userId,
            sessionId: s.id,
            // For now the rollout source IS our recall_messages table.
            // The path is informational — Phase1Worker reads from Prisma.
            rolloutPath: `prisma:recall_messages/${s.id}`,
            state: "pending",
          },
        });
        n++;
      } catch {
        // Unique constraint (userId, sessionId) — already enqueued; skip.
      }
    }
    return n;
  }
}
