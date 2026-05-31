// Phase1Worker — distill one historical recall session into a structured
// memory record. Runs in-process inside the API; called from RecallCron.
//
// Worker flow:
//   1. SELECT … FOR UPDATE SKIP LOCKED to claim a job (atomic via Postgres).
//   2. Fetch the session's messages → assemble a JSONL-like blob.
//   3. Spawn codex agent in read-only sandbox at a temp dir.
//   4. Parse the strict JSON {raw_memory, rollout_summary, rollout_slug}.
//   5. Persist the three fields back to Phase1Job.
//
// Concurrency: jobs are claimed by sessionId; multiple workers can run in
// parallel across different sessions, but never the same one. The Postgres
// lease (`leaseHolder`, `leaseExpires`) is the source of truth.

import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir, hostname } from "node:os";
import { join } from "node:path";

import { PrismaService } from "../../common/prisma/prisma.service";
import { PHASE1_LEASE_MS, PHASE1_MAX_ATTEMPTS, RECALL_PHASE1_MODEL_DEFAULT } from "./recall.constants";
import { PHASE1_SYSTEM_PROMPT } from "./templates/phase1System";
import type { Phase1Output } from "./recall.types";

const HOLDER = `${hostname()}:${process.pid}`;

@Injectable()
export class Phase1Worker {
  private readonly logger = new Logger("Phase1Worker");

  constructor(
    private readonly prisma: PrismaService,
    private readonly cfg: ConfigService,
  ) {}

  /** Process up to `max` jobs in this user's queue. Returns how many it
   *  finished (success OR fail; not skipped/leased). */
  async processBatch(userId: string, max: number): Promise<number> {
    let done = 0;
    for (let i = 0; i < max; i++) {
      const claimed = await this.claimNext(userId);
      if (!claimed) break;
      try {
        await this.runOne(claimed.id);
        done++;
      } catch (err) {
        this.logger.warn(`phase1 job ${claimed.id} failed: ${(err as Error).message}`);
        await this.markFailed(claimed.id, (err as Error).message);
        done++;
      }
    }
    return done;
  }

  /** Atomically claim one pending or stale-leased job for this user. */
  private async claimNext(userId: string): Promise<{ id: string } | null> {
    const now = new Date();
    const newExpiry = new Date(now.getTime() + PHASE1_LEASE_MS);
    // Single round-trip: SELECT … FOR UPDATE SKIP LOCKED + UPDATE in a tx.
    return this.prisma.$transaction(async (tx) => {
      const candidates = await tx.$queryRaw<{ id: string }[]>`
        SELECT id FROM "recall_phase1_jobs"
         WHERE "userId" = ${userId}
           AND ("state" = 'pending' OR ("state" = 'leased' AND "leaseExpires" < ${now}))
           AND "attemptCount" < ${PHASE1_MAX_ATTEMPTS}
         ORDER BY "createdAt" ASC
         LIMIT 1
         FOR UPDATE SKIP LOCKED
      `;
      const cand = candidates[0];
      if (!cand) return null;
      await tx.phase1Job.update({
        where: { id: cand.id },
        data: {
          state: "leased",
          leaseHolder: HOLDER,
          leaseExpires: newExpiry,
          attemptCount: { increment: 1 },
        },
      });
      return { id: cand.id };
    });
  }

  private async runOne(jobId: string): Promise<void> {
    const job = await this.prisma.phase1Job.findUnique({
      where: { id: jobId },
      include: {
        session: {
          include: {
            messages: { orderBy: { createdAt: "asc" } },
          },
        },
      },
    });
    if (!job) return;

    // Build the rollout-as-JSONL blob from RecallMessage rows. We mimic the
    // Codex rollout JSONL shape closely enough that the Phase 1 prompt
    // doesn't need to change.
    const lines: string[] = [];
    for (const m of job.session.messages) {
      lines.push(JSON.stringify({
        type: m.role === "user" ? "user_message" : "agent_message",
        text: m.content,
        ts: m.createdAt.toISOString(),
      }));
    }
    const blob = lines.join("\n");

    const tmp = await mkdtemp(join(tmpdir(), "recall-phase1-"));
    const inputPath = join(tmp, "rollout.jsonl");
    await writeFile(inputPath, blob, "utf8");

    const userMessage = [
      "Rollout JSONL (filtered to memory-relevant items):",
      "",
      "```jsonl",
      blob.slice(0, 200_000), // hard cap on prompt size
      "```",
      "",
      "Return JSON only. No markdown fences, no prose, just the object.",
    ].join("\n");

    const result = await this.spawnCodex(PHASE1_SYSTEM_PROMPT, userMessage, tmp);
    await rm(tmp, { recursive: true, force: true });

    if (!result.ok) {
      throw new Error(result.error ?? "codex spawn failed");
    }

    const parsed = parsePhase1(result.text);
    await this.prisma.phase1Job.update({
      where: { id: jobId },
      data: {
        state: "done",
        rawMemory: parsed.raw_memory,
        rolloutSummary: parsed.rollout_summary,
        rolloutSlug: parsed.rollout_slug ? slugify(parsed.rollout_slug) : null,
        generatedAt: new Date(),
        leaseHolder: null,
        leaseExpires: null,
        lastError: null,
      },
    });
  }

  private async markFailed(jobId: string, message: string): Promise<void> {
    const job = await this.prisma.phase1Job.findUnique({ where: { id: jobId } });
    if (!job) return;
    const isTerminal = job.attemptCount >= PHASE1_MAX_ATTEMPTS;
    await this.prisma.phase1Job.update({
      where: { id: jobId },
      data: {
        state: isTerminal ? "failed" : "pending",
        lastError: message.slice(0, 1000),
        leaseHolder: null,
        leaseExpires: null,
      },
    });
  }

  private async spawnCodex(
    systemPrompt: string,
    userMessage: string,
    cwd: string,
  ): Promise<{ ok: true; text: string } | { ok: false; error: string }> {
    const binary = this.cfg.get<string>("RECALL_CODEX_BINARY") ?? "codex";
    const model = this.cfg.get<string>("RECALL_PHASE1_MODEL") ?? RECALL_PHASE1_MODEL_DEFAULT;
    const args = [
      "exec",
      "--json",
      "--skip-git-repo-check",
      "--sandbox", "read-only",
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
      }, 60_000);
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
        const text = extractAgentMessage(stdout);
        if (!text) resolve({ ok: false, error: "no agent_message item" });
        else resolve({ ok: true, text });
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

function extractAgentMessage(stdout: string): string | null {
  let last = "";
  for (const line of stdout.split(/\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const ev = JSON.parse(trimmed) as { type?: string; item?: { type?: string; text?: string } };
      if (ev.type === "item.completed" && ev.item?.type === "agent_message" && ev.item.text) {
        last = ev.item.text;
      }
    } catch { /* ignore log lines */ }
  }
  return last || null;
}

function parsePhase1(text: string): Phase1Output {
  // Strip optional code fences.
  const cleaned = text.replace(/^```(?:json)?\s*|\s*```$/g, "").trim();
  try {
    const obj = JSON.parse(cleaned) as Partial<Phase1Output>;
    return {
      raw_memory: typeof obj.raw_memory === "string" && obj.raw_memory.trim() ? obj.raw_memory.trim() : null,
      rollout_summary: typeof obj.rollout_summary === "string" && obj.rollout_summary.trim() ? obj.rollout_summary.trim() : null,
      rollout_slug: typeof obj.rollout_slug === "string" && obj.rollout_slug.trim() ? obj.rollout_slug.trim() : null,
    };
  } catch {
    return { raw_memory: null, rollout_summary: null, rollout_slug: null };
  }
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9一-鿿]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}
