// Phase2Worker — global consolidation. Single-writer per user, gated by
// Phase2LockService. Reads top-N stage-1 outputs, syncs raw_memories.md
// and rollout_summaries/, computes a workspace diff against .baseline/,
// then (only if non-empty diff) spawns a workspace-write codex agent
// using the consolidation system prompt.
//
// Defaults to DRY-RUN: writes land under <root>/.dryrun/ instead of the
// live workspace until RECALL_PHASE2_LIVE=1. This is exactly the §9.6
// rollout safeguard from the design doc.

import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import { hostname } from "node:os";
import { join } from "node:path";

import { PrismaService } from "../../common/prisma/prisma.service";
import { FilesystemBootstrapper } from "./filesystemBootstrapper";
import { Phase2LockService } from "./phase2.lock.service";
import {
  PHASE2_BASELINE_DIRNAME,
  PHASE2_DRY_RUN_DIRNAME,
  PHASE2_MAX_RAW_MEMORIES,
  PHASE2_MAX_UNUSED_DAYS,
  RECALL_PHASE2_MODEL_DEFAULT,
} from "./recall.constants";
import { PHASE2_SYSTEM_PROMPT } from "./templates/phase2System";
import type { Phase2SelectedJob } from "./recall.types";

const HOLDER = `${hostname()}:${process.pid}`;

@Injectable()
export class Phase2Worker {
  private readonly logger = new Logger("Phase2Worker");

  constructor(
    private readonly prisma: PrismaService,
    private readonly cfg: ConfigService,
    private readonly lock: Phase2LockService,
    private readonly bootstrapper: FilesystemBootstrapper,
  ) {}

  async run(userId: string): Promise<{ ran: boolean; reason: string }> {
    const acquired = await this.lock.tryAcquire(userId, HOLDER);
    if (!acquired) return { ran: false, reason: "locked" };

    let success = false;
    try {
      const { root } = await this.bootstrapper.ensure(userId);
      const liveMode = this.cfg.get<string>("RECALL_PHASE2_LIVE") === "1";
      const writeRoot = liveMode ? root : join(root, PHASE2_DRY_RUN_DIRNAME);
      if (!liveMode) {
        await fs.mkdir(writeRoot, { recursive: true });
      }

      const selected = await this.selectStageOutputs(userId);
      if (selected.length === 0) {
        success = true;
        return { ran: true, reason: "no_eligible_outputs" };
      }

      // 1. Sync raw_memories.md (concat) + rollout_summaries/<slug>.md.
      await this.syncRawMemoriesFile(writeRoot, selected);
      await this.syncRolloutSummaries(writeRoot, selected);

      // 2. Compute the workspace diff vs .baseline/.
      const baselineRoot = join(root, PHASE2_BASELINE_DIRNAME);
      const diff = await this.computeWorkspaceDiff(writeRoot, baselineRoot);
      const diffPath = join(writeRoot, "phase2_workspace_diff.md");
      await fs.writeFile(diffPath, diff || "(no changes since last consolidation)\n", "utf8");

      if (!diff) {
        success = true;
        return { ran: true, reason: "no_diff" };
      }

      // 3. Spawn the consolidation sub-agent. Workspace-write sandbox.
      const userMessage = [
        "Inputs (already up to date on disk under cwd):",
        "- raw_memories.md",
        "- rollout_summaries/",
        "- phase2_workspace_diff.md",
        "- MEMORY.md",
        "",
        "Read MEMORY.md, raw_memories.md, and phase2_workspace_diff.md.",
        "Then update MEMORY.md, memory_summary.md, and skills/ as needed.",
        "When done, reply with a one-paragraph summary of what changed.",
      ].join("\n");

      const result = await this.spawnConsolidator(PHASE2_SYSTEM_PROMPT, userMessage, writeRoot);

      if (!result.ok) {
        this.logger.warn(`phase2 consolidator failed for user=${userId}: ${result.error}`);
        return { ran: true, reason: `consolidator_failed:${result.error.slice(0, 80)}` };
      }

      // 4. Bump usageCount on selected jobs.
      const ids = selected.map((s) => s.jobId);
      await this.prisma.phase1Job.updateMany({
        where: { id: { in: ids } },
        data: {
          usageCount: { increment: 1 },
          lastUsageAt: new Date(),
        },
      });

      // 5. Update the baseline mirror (only when liveMode — dry-run preserves
      //    the previous baseline so the user can inspect the diff).
      if (liveMode) {
        await this.refreshBaseline(root, baselineRoot);
      }

      success = true;
      return { ran: true, reason: "ok" };
    } catch (err) {
      this.logger.warn(`phase2 run threw for user=${userId}: ${(err as Error).message}`);
      return { ran: true, reason: `error:${(err as Error).message.slice(0, 80)}` };
    } finally {
      await this.lock.release(userId, HOLDER, success);
    }
  }

  private async selectStageOutputs(userId: string): Promise<Phase2SelectedJob[]> {
    const cutoff = new Date(Date.now() - PHASE2_MAX_UNUSED_DAYS * 24 * 60 * 60 * 1000);
    const rows = await this.prisma.phase1Job.findMany({
      where: {
        userId,
        state: "done",
        OR: [
          { lastUsageAt: { gte: cutoff } },
          { lastUsageAt: null, generatedAt: { gte: cutoff } },
        ],
      },
      orderBy: [
        { usageCount: "desc" },
        { lastUsageAt: "desc" },
        { generatedAt: "desc" },
      ],
      take: PHASE2_MAX_RAW_MEMORIES,
    });
    return rows.map((r) => ({
      jobId: r.id,
      rolloutSlug: r.rolloutSlug,
      rolloutSummary: r.rolloutSummary,
      rawMemory: r.rawMemory,
      generatedAt: r.generatedAt?.toISOString() ?? null,
      usageCount: r.usageCount,
    }));
  }

  private async syncRawMemoriesFile(root: string, sel: Phase2SelectedJob[]): Promise<void> {
    const blocks: string[] = [
      "<!-- Auto-generated by Phase 2 consolidation. Do not edit by hand. -->",
      "",
    ];
    for (const r of sel) {
      if (!r.rawMemory) continue;
      blocks.push(`## ${r.rolloutSlug ?? r.jobId}`);
      blocks.push(`_generated_: ${r.generatedAt ?? "unknown"} · _used_: ${r.usageCount}`);
      blocks.push("");
      blocks.push(r.rawMemory);
      blocks.push("");
    }
    await atomicWrite(join(root, "raw_memories.md"), blocks.join("\n"));
  }

  private async syncRolloutSummaries(root: string, sel: Phase2SelectedJob[]): Promise<void> {
    const dir = join(root, "rollout_summaries");
    await fs.mkdir(dir, { recursive: true });
    for (const r of sel) {
      if (!r.rolloutSummary || !r.rolloutSlug) continue;
      const path = join(dir, `${r.rolloutSlug}.md`);
      const body = [
        "---",
        `slug: ${r.rolloutSlug}`,
        `generated_at: ${r.generatedAt ?? "unknown"}`,
        `usage_count: ${r.usageCount}`,
        "---",
        "",
        r.rolloutSummary,
        "",
      ].join("\n");
      await atomicWrite(path, body);
    }
  }

  /** Cheap manifest diff: list of (relPath, sha1) for both trees, then
   *  describe added / removed / changed in markdown. We avoid shelling
   *  out to git here to keep the dep surface small. */
  private async computeWorkspaceDiff(live: string, baseline: string): Promise<string> {
    const liveManifest = await manifestOf(live);
    const baselineManifest = await manifestOf(baseline);

    const added: string[] = [];
    const removed: string[] = [];
    const changed: string[] = [];

    for (const [path, hash] of liveManifest) {
      const b = baselineManifest.get(path);
      if (!b) added.push(path);
      else if (b !== hash) changed.push(path);
    }
    for (const path of baselineManifest.keys()) {
      if (!liveManifest.has(path)) removed.push(path);
    }
    if (!added.length && !removed.length && !changed.length) return "";

    const lines = ["# phase2 workspace diff", ""];
    if (added.length) {
      lines.push("## Added");
      for (const p of added) lines.push(`+ ${p}`);
      lines.push("");
    }
    if (removed.length) {
      lines.push("## Removed");
      for (const p of removed) lines.push(`- ${p}`);
      lines.push("");
    }
    if (changed.length) {
      lines.push("## Changed");
      for (const p of changed) lines.push(`~ ${p}`);
      lines.push("");
    }
    return lines.join("\n");
  }

  private async refreshBaseline(live: string, baseline: string): Promise<void> {
    // Wipe and rewrite. Cheap — Phase-2 only runs after Phase-1 events, and
    // memory roots are O(MB) at most.
    await fs.rm(baseline, { recursive: true, force: true });
    await fs.mkdir(baseline, { recursive: true });
    const entries = await listFiles(live, live);
    for (const rel of entries) {
      const src = join(live, rel);
      const dst = join(baseline, rel);
      await fs.mkdir(join(dst, ".."), { recursive: true });
      await fs.copyFile(src, dst);
    }
  }

  private async spawnConsolidator(
    systemPrompt: string,
    userMessage: string,
    cwd: string,
  ): Promise<{ ok: true; text: string } | { ok: false; error: string }> {
    const binary = this.cfg.get<string>("RECALL_CODEX_BINARY") ?? "codex";
    const model = this.cfg.get<string>("RECALL_PHASE2_MODEL") ?? RECALL_PHASE2_MODEL_DEFAULT;
    const args = [
      "exec",
      "--json",
      "--skip-git-repo-check",
      "--sandbox", "workspace-write",
      "--cd", cwd,
      "--model", model,
      "-",
    ];
    return new Promise((resolve) => {
      const child = spawn(binary, args, {
        env: this.safeEnv(),
        stdio: ["pipe", "pipe", "pipe"],
      });
      let stdout = "";
      let stderr = "";
      const killer = setTimeout(() => {
        try { child.kill("SIGKILL"); } catch { /* ignore */ }
      }, 5 * 60_000);
      child.stdout.on("data", (b) => { stdout += b.toString("utf8"); });
      child.stderr.on("data", (b) => { stderr += b.toString("utf8"); });
      child.stdin.write(`${systemPrompt}\n\n---\n\n${userMessage}\n`);
      child.stdin.end();
      child.on("close", (code) => {
        clearTimeout(killer);
        if (code !== 0) {
          resolve({ ok: false, error: stderr.trim().slice(0, 500) || `exit ${code}` });
          return;
        }
        // The agent's reply text isn't required for correctness — the writes
        // are the work. But surface it for telemetry.
        let text = "";
        for (const line of stdout.split(/\n/)) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          try {
            const ev = JSON.parse(trimmed) as { type?: string; item?: { type?: string; text?: string } };
            if (ev.type === "item.completed" && ev.item?.type === "agent_message" && ev.item.text) {
              text = ev.item.text;
            }
          } catch { /* skip */ }
        }
        resolve({ ok: true, text });
      });
      child.on("error", (err) => {
        clearTimeout(killer);
        resolve({ ok: false, error: err.message });
      });
    });
  }

  private safeEnv(): NodeJS.ProcessEnv {
    const allowApiKey = this.cfg.get<string>("RECALL_CODEX_ALLOW_API_KEY") === "1";
    if (allowApiKey) return process.env;
    const { OPENAI_API_KEY: _strip, ...rest } = process.env;
    return rest;
  }
}

// ─── helpers ────────────────────────────────────────────────────────────

async function atomicWrite(path: string, content: string): Promise<void> {
  const tmpPath = `${path}.tmp-${process.pid}-${Date.now()}`;
  await fs.writeFile(tmpPath, content, "utf8");
  await fs.rename(tmpPath, path);
}

async function manifestOf(root: string): Promise<Map<string, string>> {
  const manifest = new Map<string, string>();
  try {
    const entries = await listFiles(root, root);
    for (const rel of entries) {
      const buf = await fs.readFile(join(root, rel));
      manifest.set(rel, hashOf(buf));
    }
  } catch {
    /* missing root — empty manifest */
  }
  return manifest;
}

async function listFiles(root: string, base: string): Promise<string[]> {
  const out: string[] = [];
  let entries;
  try {
    entries = await fs.readdir(root, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    if (e.name.startsWith(".dryrun") || e.name.startsWith(".baseline") || e.name === ".bootstrapped") continue;
    const abs = join(root, e.name);
    if (e.isDirectory()) {
      const child = await listFiles(abs, base);
      out.push(...child);
    } else if (e.isFile()) {
      out.push(abs.slice(base.length + 1));
    }
  }
  return out;
}

function hashOf(buf: Buffer): string {
  // Tiny non-crypto hash; stable enough to detect changes.
  let h = 5381;
  for (let i = 0; i < buf.length; i++) {
    h = ((h << 5) + h + buf[i]) | 0;
  }
  return String(h >>> 0);
}
