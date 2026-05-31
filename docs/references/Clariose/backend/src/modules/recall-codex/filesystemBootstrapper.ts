// FilesystemBootstrapper — creates the per-user memories root with the
// canonical layout described in §3.5 of the design doc. Idempotent: every
// `ensure(userId)` call no-ops if the root already has the sentinel file.
//
// The skeleton is intentionally tiny — Phase-2 fills MEMORY.md /
// memory_summary.md with real content over time. The placeholders just
// give the coordinator something safe to read on the very first turn,
// before any history exists.

import { Injectable, Logger } from "@nestjs/common";
import { PrismaService } from "../../common/prisma/prisma.service";
import { promises as fs } from "node:fs";
import { join } from "node:path";

import { MemoryRootResolver } from "./memoryRootResolver";
import { buildAgentsMd } from "./templates/agentsMd";
import {
  PHASE2_BASELINE_DIRNAME,
} from "./recall.constants";

const SENTINEL = ".bootstrapped";

@Injectable()
export class FilesystemBootstrapper {
  private readonly logger = new Logger("RecallBootstrapper");

  constructor(
    private readonly resolver: MemoryRootResolver,
    private readonly prisma: PrismaService,
  ) {}

  /** Ensure the user's memories root exists with skeleton content. Returns
   *  the resolved root path either way. Safe to call concurrently. */
  async ensure(userId: string): Promise<{ namespace: string; root: string }> {
    const { namespace, root } = await this.resolver.resolveForUser(userId);

    // Fast path — skeleton already laid down.
    try {
      await fs.access(join(root, SENTINEL));
      // Refresh AGENTS.md if older than 1h (cheap O(1) DB calls).
      await this.maybeRefreshAgentsMd(userId, namespace, root);
      return { namespace, root };
    } catch {
      /* fall through — bootstrap below */
    }

    await fs.mkdir(root, { recursive: true });
    await fs.mkdir(join(root, "rollout_summaries"), { recursive: true });
    await fs.mkdir(join(root, "skills"), { recursive: true });
    await fs.mkdir(join(root, "notes"), { recursive: true });
    await fs.mkdir(join(root, PHASE2_BASELINE_DIRNAME), { recursive: true });

    await writeIfMissing(
      join(root, "memory_summary.md"),
      `# Memory summary

This workspace is empty. Recall coordinator: read MEMORY.md and notes/
to find anything the user has uploaded; otherwise answer from the
question alone.
`,
    );

    await writeIfMissing(
      join(root, "MEMORY.md"),
      `# MEMORY (registry)

| topic | source | freshness |
|-------|--------|-----------|
| _empty_ | _empty_ | _empty_ |
`,
    );

    await writeIfMissing(
      join(root, "raw_memories.md"),
      "<!-- Phase-1 stage outputs land here. Do not edit by hand. -->\n",
    );

    await writeIfMissing(
      join(root, "read_path.md"),
      `# Read path policy

This file is informational. The recall coordinator's read protocol is
delivered in its system prompt; this is a copy for human reference.

1. Skim memory_summary.md
2. Generate 1–3 keywords from the question
3. \`rg -n -i\` MEMORY.md
4. Open at most 2–3 referenced files with \`sed -n\`
5. Fall back to notes/ or raw_memories.md only if needed
6. Stop after 4–6 search steps
`,
    );

    await this.maybeRefreshAgentsMd(userId, namespace, root);
    await fs.writeFile(join(root, SENTINEL), new Date().toISOString(), "utf8");
    this.logger.log(`bootstrapped recall workspace: ${root}`);
    return { namespace, root };
  }

  private async maybeRefreshAgentsMd(
    userId: string,
    namespace: string,
    root: string,
  ): Promise<void> {
    const agentsPath = join(root, "AGENTS.md");
    const ttlMs = 60 * 60 * 1000;
    try {
      const stat = await fs.stat(agentsPath);
      if (Date.now() - stat.mtimeMs < ttlMs) return;
    } catch {
      /* missing — fall through and write */
    }
    const since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
    const [noteUploadsLast7d, recallSessionsLast7d] = await Promise.all([
      this.prisma.recallNote.count({
        where: { userId, createdAt: { gte: since } },
      }),
      this.prisma.recallSession.count({
        where: { userId, createdAt: { gte: since } },
      }),
    ]);
    const md = buildAgentsMd({
      userIdHash: namespace,
      noteUploadsLast7d,
      recallSessionsLast7d,
      todayIso: new Date().toISOString().slice(0, 10),
    });
    await fs.writeFile(agentsPath, md, "utf8");
  }
}

async function writeIfMissing(path: string, content: string): Promise<void> {
  try {
    await fs.access(path);
  } catch {
    await fs.writeFile(path, content, "utf8");
  }
}
