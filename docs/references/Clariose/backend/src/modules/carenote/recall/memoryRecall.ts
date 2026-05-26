// CLARIOSE_V01 §4 — recall orchestrator. The single entry point the
// CodexPromptAssembler / CodexRunManager calls before each role's turn.
//
// prefetch() never throws; always returns a RecallResult, with `skipped` set
// when nothing was injected. The 4-phase pipeline is:
//   Phase 1: scan disk → manifest (cached in Redis 300s)
//   Phase 2: sideQuery LLM ranks manifest → top-N relPaths (Promise.race timeout)
//   Phase 3: surface — read full file content (truncated per file)
//   Phase 4: inject — assemble Markdown append block; consume budget; dedup

import { Injectable, Logger } from "@nestjs/common";

import {
  MANIFEST_CACHE_TTL_SEC,
  RECALL_KEY_PREFIX,
  SIDEQUERY_TIMEOUT_MS,
} from "./recall.constants";
import { MemoryScanService } from "./memoryScan";
import { MemorySideQueryService } from "./memorySideQuery";
import { MemorySurfaceService } from "./memorySurface";
import { RecallBudgetService } from "./recallBudget";
import { RecallCache } from "./recallCache";
import type {
  ManifestEntry,
  RecallResult,
  RecallSkipReason,
  ScanResult,
  SurfacedFile,
} from "./recall.types";

export type PrefetchOptions = {
  isSubagentFork?: boolean;
  recentTools?: readonly string[];
};

@Injectable()
export class MemoryRecallService {
  private readonly logger = new Logger("MemoryRecall");

  constructor(
    private readonly scan: MemoryScanService,
    private readonly sideQuery: MemorySideQueryService,
    private readonly surface: MemorySurfaceService,
    private readonly budget: RecallBudgetService,
    private readonly cache: RecallCache,
  ) {}

  isEnabled(): boolean {
    return this.sideQuery.isEnabled();
  }

  async prefetch(args: {
    visit_id: string | null;
    user_id: string | null;
    /** Free-text query — typically the latest transcript turn or a topic. */
    query: string;
    options?: PrefetchOptions;
  }): Promise<RecallResult> {
    const started = Date.now();
    const empty = (skipped: RecallSkipReason | undefined): RecallResult => ({
      append: null,
      files: [],
      bytesInjected: 0,
      manifestSize: 0,
      selectedCount: 0,
      latencyMs: Date.now() - started,
      skipped,
    });

    if (args.options?.isSubagentFork) return empty("subagent");
    if (!this.isEnabled()) return empty("disabled");
    if (!args.visit_id) return empty("no_visit");

    if (await this.budget.wouldExceed(args.visit_id, 1)) {
      return empty("visit_budget");
    }

    // Phase 1 — scan + cache.
    const scanResult = await this.getScan(args.visit_id, args.user_id);
    if (scanResult.manifest.length === 0) return empty("empty");

    // Phase 2 — sideQuery, racing the call against an outer timeout.
    let chosen: ManifestEntry[];
    let timedOut = false;
    try {
      chosen = await raceWithTimeout(
        this.sideQuery.select({
          query: args.query,
          manifest: scanResult.manifest,
          recentTools: args.options?.recentTools
            ? [...args.options.recentTools]
            : undefined,
        }),
        SIDEQUERY_TIMEOUT_MS,
        () => {
          timedOut = true;
        },
      );
    } catch {
      chosen = [];
    }

    if (chosen.length === 0) {
      const r = empty(timedOut ? "sidequery_timeout" : "empty");
      r.manifestSize = scanResult.manifest.length;
      return r;
    }

    // Filter out files that were already surfaced earlier in this visit
    // (and haven't been mutated since — we use mtimeMs as the freshness
    // gate for "still the same content"). Keeps the budget useful and
    // prevents repeating the same context turn after turn.
    const fresh: ManifestEntry[] = [];
    for (const c of chosen) {
      const dedupKey = `${c.relPath}@${c.mtimeMs}`;
      if (await this.budget.wasSurfaced(args.visit_id, dedupKey)) continue;
      fresh.push(c);
    }
    if (fresh.length === 0) {
      const r = empty("empty");
      r.manifestSize = scanResult.manifest.length;
      r.selectedCount = chosen.length;
      return r;
    }

    // Phase 3 — surface.
    const surfaced = await this.surface
      .readForSurfacing(fresh)
      .catch((err) => {
        this.logger.warn(`surface failed: ${(err as Error).message}`);
        return [] as SurfacedFile[];
      });

    // Phase 4 — inject. Build Markdown append block + consume budget.
    const append = toAppendBlock(surfaced);
    const bytesInjected = append ? Buffer.byteLength(append, "utf8") : 0;

    if (bytesInjected > 0 && (await this.budget.wouldExceed(args.visit_id, bytesInjected))) {
      return empty("visit_budget");
    }
    if (bytesInjected > 0) {
      await this.budget.consume(args.visit_id, bytesInjected);
      for (const f of surfaced) {
        await this.budget.markSurfaced(args.visit_id, `${f.relPath}@${pickMtime(f, fresh)}`);
      }
    }

    return {
      append,
      files: surfaced.map((f) => f.relPath),
      bytesInjected,
      manifestSize: scanResult.manifest.length,
      selectedCount: chosen.length,
      latencyMs: Date.now() - started,
    };
  }

  /** Force a re-scan on next prefetch (e.g., after auto-dream writes new files). */
  async invalidateManifest(visit_id: string): Promise<void> {
    await this.cache.del(`${RECALL_KEY_PREFIX}:manifest:${visit_id}`);
  }

  /** Manifest cache (Phase 1 result), keyed by visit_id. Memoization across
   *  rapid-fire turns within the manifest TTL window. */
  private async getScan(
    visit_id: string,
    user_id: string | null,
  ): Promise<ScanResult> {
    const key = `${RECALL_KEY_PREFIX}:manifest:${visit_id}`;
    const cached = await this.cache.get(key);
    if (cached) {
      try {
        const parsed = JSON.parse(cached) as ScanResult;
        if (parsed && Array.isArray(parsed.manifest)) return parsed;
      } catch { /* fall through */ }
    }
    const fresh = await this.scan.scanForVisit(visit_id, user_id);
    try {
      await this.cache.setEx(key, JSON.stringify(fresh), MANIFEST_CACHE_TTL_SEC);
    } catch { /* non-fatal */ }
    return fresh;
  }
}

// ─────────────────────────────────────────────────────────────────────────────

function toAppendBlock(surfaced: SurfacedFile[]): string | null {
  if (surfaced.length === 0) return null;
  const blocks = surfaced.map((f) => {
    const flags = [`${f.freshDays}d old`, f.scope];
    if (f.truncated) flags.push("truncated");
    return `# ${f.name} (${flags.join(", ")})\n_source: ${f.relPath}_\n\n${f.content.trim()}`;
  });
  return ["## Patient Memory Context", "", blocks.join("\n\n---\n\n")].join("\n");
}

function pickMtime(f: SurfacedFile, manifest: ManifestEntry[]): number {
  return manifest.find((m) => m.relPath === f.relPath)?.mtimeMs ?? 0;
}

async function raceWithTimeout<T>(
  p: Promise<T>,
  ms: number,
  onTimeout?: () => void,
): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const timeoutPromise = new Promise<T>((_resolve, reject) => {
    timer = setTimeout(() => {
      onTimeout?.();
      reject(new Error(`recall timeout ${ms}ms`));
    }, ms);
  });
  try {
    return await Promise.race([p, timeoutPromise]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
