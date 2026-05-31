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
