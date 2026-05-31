// CLARIOSE_V01 §4.3 — per-visit byte budget + per-(visit,file) dedup. Backed
// by Redis (with in-memory fallback through RecallCache).

import { createHash } from "node:crypto";
import { Injectable, Logger } from "@nestjs/common";

import {
  MAX_VISIT_BYTES,
  RECALL_KEY_PREFIX,
  VISIT_BUDGET_TTL_SEC,
} from "./recall.constants";
import { RecallCache } from "./recallCache";

@Injectable()
export class RecallBudgetService {
  private readonly logger = new Logger("RecallBudget");

  constructor(private readonly cache: RecallCache) {}

  private budgetKey(visit_id: string): string {
    return `${RECALL_KEY_PREFIX}:budget:${visit_id}`;
  }
  private surfacedKey(visit_id: string): string {
    return `${RECALL_KEY_PREFIX}:surfaced:${visit_id}`;
  }
  private hashRel(relPath: string): string {
    return createHash("sha1").update(relPath).digest("hex").slice(0, 16);
  }

  /** Returns the cumulative bytes already consumed in this visit. */
  async currentBytes(visit_id: string): Promise<number> {
    const raw = await this.cache.get(this.budgetKey(visit_id));
    return Number(raw ?? 0);
  }

  async wouldExceed(visit_id: string, nextBytes: number): Promise<boolean> {
    const cur = await this.currentBytes(visit_id);
    return cur + nextBytes > MAX_VISIT_BYTES;
  }

  async consume(visit_id: string, bytes: number): Promise<number> {
    if (bytes <= 0) return await this.currentBytes(visit_id);
    return this.cache.incrBy(
      this.budgetKey(visit_id),
      bytes,
      VISIT_BUDGET_TTL_SEC,
    );
  }

  async wasSurfaced(visit_id: string, relPath: string): Promise<boolean> {
    return this.cache.sIsMember(this.surfacedKey(visit_id), this.hashRel(relPath));
  }

  async markSurfaced(visit_id: string, relPath: string): Promise<void> {
    await this.cache.sAdd(
      this.surfacedKey(visit_id),
      this.hashRel(relPath),
      VISIT_BUDGET_TTL_SEC,
    );
  }

  async reset(visit_id: string): Promise<void> {
    await this.cache.del(this.budgetKey(visit_id), this.surfacedKey(visit_id));
  }
}
