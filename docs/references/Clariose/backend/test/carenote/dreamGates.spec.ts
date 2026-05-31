// Pure-policy gate logic tests.

import { ConfigService } from "@nestjs/config";
import { DreamGates } from "../../src/modules/carenote/swarm/dream/dream.gates";

function makePrisma(
  visits: Array<{ id: string; ownerUserId: string; status: string; endedAt: Date | null }>,
) {
  return {
    consultSession: {
      count: async ({ where }: any) =>
        visits.filter((v) => {
          if (v.ownerUserId !== where.ownerUserId) return false;
          if (where.status && v.status !== where.status) return false;
          if (where.endedAt?.gte) {
            if (!v.endedAt) return false;
            if (v.endedAt < where.endedAt.gte) return false;
          }
          return true;
        }).length,
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
      {
        id: "v1",
        ownerUserId: "u1",
        status: "ENDED",
        endedAt: new Date(Date.now() - 1 * 3600_000),
      },
    ]);
    const g = new DreamGates(cfg(), prisma);
    expect(await g.hasEligibleVisits("u1", last)).toBe(true);
  });

  it("hasEligibleVisits false when no recent ENDED visits", async () => {
    const last = new Date(Date.now() - 1 * 3600_000);
    const prisma = makePrisma([
      {
        id: "v1",
        ownerUserId: "u1",
        status: "ENDED",
        endedAt: new Date(Date.now() - 4 * 3600_000),
      },
    ]);
    const g = new DreamGates(cfg(), prisma);
    expect(await g.hasEligibleVisits("u1", last)).toBe(false);
  });

  it("hasEligibleVisits with since=null counts every ENDED visit (manual path)", async () => {
    // Regression: the manual "Dream now" runner passes `since=null` so
    // the user can re-consolidate any time after dreaming once. Prior
    // behavior used `lastDreamedAt` and stranded users on
    // `no_eligible_visits` once they'd dreamed at least once.
    const prisma = makePrisma([
      {
        id: "v_old",
        ownerUserId: "u1",
        status: "ENDED",
        endedAt: new Date(Date.now() - 30 * 24 * 3600_000),
      },
    ]);
    const g = new DreamGates(cfg(), prisma);
    expect(await g.hasEligibleVisits("u1", null)).toBe(true);
  });

  it("isVisitOwnedAndEnded enforces ownership and ENDED state", async () => {
    const prisma = makePrisma([
      { id: "v1", ownerUserId: "u1", status: "ENDED", endedAt: new Date() },
      { id: "v2", ownerUserId: "u2", status: "ENDED", endedAt: new Date() },
      { id: "v3", ownerUserId: "u1", status: "ACTIVE", endedAt: null },
    ]);
    const g = new DreamGates(cfg(), prisma);
    expect(await g.isVisitOwnedAndEnded("v1", "u1")).toBe(true);
    expect(await g.isVisitOwnedAndEnded("v2", "u1")).toBe(false);
    expect(await g.isVisitOwnedAndEnded("v3", "u1")).toBe(false);
    expect(await g.isVisitOwnedAndEnded("vX", "u1")).toBe(false);
  });
});
