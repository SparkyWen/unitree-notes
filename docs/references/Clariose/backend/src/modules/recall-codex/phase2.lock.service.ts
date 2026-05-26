// Phase2 lock — single advisory row per user. Mirrors Codex source's "single
// global phase-2 lock" trick. Implementation uses an UPDATE … WHERE
// (holder IS NULL OR expiresAt < NOW()) so two workers racing for the same
// user atomically resolve to a single winner.

import { Injectable, Logger } from "@nestjs/common";

import { PrismaService } from "../../common/prisma/prisma.service";
import { PHASE2_LOCK_MS } from "./recall.constants";

@Injectable()
export class Phase2LockService {
  private readonly logger = new Logger("Phase2Lock");

  constructor(private readonly prisma: PrismaService) {}

  /** Try to acquire the lock for one user. Returns true on success.
   *  Uses an upsert + race-conditional update so first call ever
   *  for a user creates the row. */
  async tryAcquire(userId: string, holder: string): Promise<boolean> {
    // Ensure the row exists (no-op if it does).
    await this.prisma.phase2Lock.upsert({
      where: { userId },
      create: { userId },
      update: {},
    });
    const now = new Date();
    const expiresAt = new Date(now.getTime() + PHASE2_LOCK_MS);
    const updated = await this.prisma.$executeRaw`
      UPDATE "recall_phase2_locks"
         SET holder = ${holder}, "acquiredAt" = ${now}, "expiresAt" = ${expiresAt}
       WHERE "userId" = ${userId}
         AND (holder IS NULL OR "expiresAt" < ${now})
    `;
    return updated > 0;
  }

  async release(userId: string, holder: string, ranSuccessfully: boolean): Promise<void> {
    await this.prisma.$executeRaw`
      UPDATE "recall_phase2_locks"
         SET holder = NULL,
             "expiresAt" = NULL,
             ${ranSuccessfully ? this.prisma.$queryRaw`"lastRunAt" = NOW(),` : this.prisma.$queryRaw``}
             "acquiredAt" = "acquiredAt"
       WHERE "userId" = ${userId}
         AND holder = ${holder}
    `.catch((err) => {
      // Fallback to a regular update if the conditional raw doesn't
      // round-trip well across all postgres versions.
      this.logger.warn(`raw release failed: ${(err as Error).message}; using update`);
      return this.prisma.phase2Lock.updateMany({
        where: { userId, holder },
        data: {
          holder: null,
          expiresAt: null,
          ...(ranSuccessfully ? { lastRunAt: new Date() } : {}),
        },
      });
    });
  }

  async lastRunAt(userId: string): Promise<Date | null> {
    const row = await this.prisma.phase2Lock.findUnique({ where: { userId } });
    return row?.lastRunAt ?? null;
  }
}
