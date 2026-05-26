// Tiny Redis wrapper used by the recall pipeline. Connects lazily; if Redis
// is unreachable, falls back to a per-process in-memory Map (the LRU is
// simple — entries expire by TTL, no size cap because keys are bounded by
// (manifest:<visitId>) + (budget:<visitId>) + (surfaced:<visitId>)).
//
// CLARIOSE_V01 §4.3 / §4.4 — cache + budget + dedup all funnel through here.

import { Injectable, Logger, OnModuleDestroy } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import IORedis, { type Redis } from "ioredis";

@Injectable()
export class RecallCache implements OnModuleDestroy {
  private readonly logger = new Logger("RecallCache");
  private client: Redis | null = null;
  private connectAttempted = false;
  private readonly local = new Map<string, { value: string; expiresAt: number }>();
  private readonly localSets = new Map<string, Map<string, number>>();

  constructor(private readonly cfg: ConfigService) {}

  async onModuleDestroy(): Promise<void> {
    if (this.client) {
      try { await this.client.quit(); } catch { /* ignore */ }
    }
  }

  private async ensureClient(): Promise<Redis | null> {
    if (this.client) return this.client;
    if (this.connectAttempted) return null;
    this.connectAttempted = true;
    const url = this.cfg.get<string>("REDIS_URL");
    if (!url) {
      this.logger.warn("REDIS_URL not set; recall cache will use in-process Map");
      return null;
    }
    try {
      this.client = new IORedis(url, {
        lazyConnect: true,
        maxRetriesPerRequest: 1,
        enableOfflineQueue: false,
      });
      this.client.on("error", (err) => {
        this.logger.warn(`redis error (degrading to local): ${err.message}`);
      });
      await this.client.connect();
    } catch (err) {
      this.logger.warn(`redis connect failed: ${(err as Error).message}`);
      this.client = null;
    }
    return this.client;
  }

  async get(key: string): Promise<string | null> {
    const c = await this.ensureClient();
    if (c) {
      try { return await c.get(key); } catch { /* fall through */ }
    }
    const ent = this.local.get(key);
    if (!ent) return null;
    if (ent.expiresAt < Date.now()) { this.local.delete(key); return null; }
    return ent.value;
  }

  async setEx(key: string, value: string, ttlSec: number): Promise<void> {
    const c = await this.ensureClient();
    if (c) {
      try { await c.set(key, value, "EX", ttlSec); return; } catch { /* fall through */ }
    }
    this.local.set(key, { value, expiresAt: Date.now() + ttlSec * 1000 });
  }

  async incrBy(key: string, by: number, ttlSec: number): Promise<number> {
    const c = await this.ensureClient();
    if (c) {
      try {
        const pipe = c.multi();
        pipe.incrby(key, by);
        pipe.expire(key, ttlSec);
        const res = await pipe.exec();
        return Number(res?.[0]?.[1] ?? 0);
      } catch { /* fall through */ }
    }
    const cur = Number((await this.get(key)) ?? 0);
    const next = cur + by;
    await this.setEx(key, String(next), ttlSec);
    return next;
  }

  async sAdd(key: string, member: string, ttlSec: number): Promise<void> {
    const c = await this.ensureClient();
    if (c) {
      try {
        const pipe = c.multi();
        pipe.sadd(key, member);
        pipe.expire(key, ttlSec);
        await pipe.exec();
        return;
      } catch { /* fall through */ }
    }
    let set = this.localSets.get(key);
    if (!set) {
      set = new Map();
      this.localSets.set(key, set);
    }
    set.set(member, Date.now() + ttlSec * 1000);
  }

  async sIsMember(key: string, member: string): Promise<boolean> {
    const c = await this.ensureClient();
    if (c) {
      try { return (await c.sismember(key, member)) === 1; } catch { /* fall through */ }
    }
    const set = this.localSets.get(key);
    if (!set) return false;
    const exp = set.get(member);
    if (!exp) return false;
    if (exp < Date.now()) { set.delete(member); return false; }
    return true;
  }

  async del(...keys: string[]): Promise<void> {
    const c = await this.ensureClient();
    if (c) {
      try { await c.del(...keys); return; } catch { /* fall through */ }
    }
    for (const k of keys) {
      this.local.delete(k);
      this.localSets.delete(k);
    }
  }
}
