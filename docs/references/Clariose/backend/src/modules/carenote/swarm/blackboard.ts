// CLARIOSE_V01 §3 cross-cutting — versioned KV per visit.
//
// All roles can read; writes are attributed to a specific role for audit.
// Every write emits `blackboard_updated` to the EventBus, which is what the
// CodexRunManager on-demand-trigger registry listens for.
//
// Storage: `carenote_blackboard` (visitId, key) UNIQUE; bumps `version` on
// each write. Version is opaque to consumers — used only for telemetry.

import { Injectable, Logger } from "@nestjs/common";

import { PrismaService } from "../../../common/prisma/prisma.service";
import { CarenoteEventBus } from "./eventBus";

export type BlackboardEntry = {
  key: string;
  value: unknown;
  writtenBy: string;
  version: number;
  updatedAt: string;
};

@Injectable()
export class BlackboardService {
  private readonly logger = new Logger("Blackboard");

  constructor(
    private readonly prisma: PrismaService,
    private readonly bus: CarenoteEventBus,
  ) {}

  async write(args: {
    visit_id: string;
    key: string;
    value: unknown;
    writtenBy: string;
  }): Promise<BlackboardEntry> {
    // Atomic upsert with version bump. Prisma doesn't expose `nextVersion =
    // version + 1` natively, so do it in a tx.
    const next = await this.prisma.$transaction(async (tx) => {
      const cur = await tx.carenoteBlackboard.findUnique({
        where: { visitId_key: { visitId: args.visit_id, key: args.key } },
      });
      const nextVersion = (cur?.version ?? 0) + 1;
      return tx.carenoteBlackboard.upsert({
        where: { visitId_key: { visitId: args.visit_id, key: args.key } },
        create: {
          visitId: args.visit_id,
          key: args.key,
          value: args.value as unknown as object,
          writtenBy: args.writtenBy,
          version: nextVersion,
        },
        update: {
          value: args.value as unknown as object,
          writtenBy: args.writtenBy,
          version: nextVersion,
        },
      });
    });

    this.bus.emit({
      type: "blackboard_updated",
      visitId: args.visit_id,
      key: args.key,
      writtenBy: args.writtenBy,
      version: next.version,
    });

    return {
      key: next.key,
      value: next.value,
      writtenBy: next.writtenBy,
      version: next.version,
      updatedAt: next.updatedAt.toISOString(),
    };
  }

  async read(visit_id: string, key: string): Promise<BlackboardEntry | null> {
    const r = await this.prisma.carenoteBlackboard.findUnique({
      where: { visitId_key: { visitId: visit_id, key } },
    });
    if (!r) return null;
    return {
      key: r.key,
      value: r.value,
      writtenBy: r.writtenBy,
      version: r.version,
      updatedAt: r.updatedAt.toISOString(),
    };
  }

  /** Fetch a subset of keys as a {key:value} map. Missing keys are omitted. */
  async readMany(
    visit_id: string,
    keys: string[],
  ): Promise<Record<string, unknown>> {
    if (keys.length === 0) return {};
    const rows = await this.prisma.carenoteBlackboard.findMany({
      where: { visitId: visit_id, key: { in: keys } },
    });
    const out: Record<string, unknown> = {};
    for (const r of rows) out[r.key] = r.value;
    return out;
  }

  /** Snapshot the entire blackboard for one visit (for debug / final summary). */
  async snapshot(visit_id: string): Promise<BlackboardEntry[]> {
    const rows = await this.prisma.carenoteBlackboard.findMany({
      where: { visitId: visit_id },
      orderBy: { key: "asc" },
    });
    return rows.map((r) => ({
      key: r.key,
      value: r.value,
      writtenBy: r.writtenBy,
      version: r.version,
      updatedAt: r.updatedAt.toISOString(),
    }));
  }
}
