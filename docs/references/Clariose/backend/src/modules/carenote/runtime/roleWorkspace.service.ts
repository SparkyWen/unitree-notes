// RoleWorkspaceService — gives every Codex role an isolated on-disk
// workspace, mirroring Qzone's per-agent layout.
//
//   <CARENOTE_TEAMS_ROOT>/<role>/
//     ├─ CLAUDE.md            persona + house rules (mirror of prompts/codex-agents/<role>.md)
//     ├─ memory/
//     │    ├─ MEMORY.md       index of long-term notes (loaded into prompt)
//     │    └─ <topic>.md      durable notes the role accumulates
//     ├─ artifacts/           any files the role authors
//     ├─ skills/              private SKILL.md files only this role can see
//     └─ inboxes/             per-visit mailboxes (one .json per visit)
//
// MailboxFileService still owns inbox writes; this service only
// guarantees the directory is there. ensureAll() is idempotent and runs
// at module init so a fresh deployment has the layout before the first
// codex run lands.

import { Injectable, Logger, OnModuleInit } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import {
  CodexAgentDisplayNames,
  CodexAgentRoleSchema,
  type CodexAgentRole,
} from "../medical/medicalSchemas";

const TEAMS_ROOT_DEFAULT = "/home/ubuntu/Zai/.data/carenote/teams";
const REPO_ROOT_DEFAULT = "/home/ubuntu/Zai";

function safeSegment(s: string): string {
  return (s ?? "").replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 64) || "_";
}

export type RoleWorkspacePaths = {
  root: string;
  claudeMd: string;
  memoryDir: string;
  memoryIndex: string;
  artifactsDir: string;
  skillsDir: string;
  inboxesDir: string;
};

@Injectable()
export class RoleWorkspaceService implements OnModuleInit {
  private readonly logger = new Logger("RoleWorkspace");
  private readonly memoryCache = new Map<string, { content: string; mtime: number }>();

  constructor(private readonly cfg: ConfigService) {}

  /** Resolved root (env override → default). */
  root(): string {
    return resolve(
      this.cfg.get<string>("CARENOTE_TEAMS_ROOT") ?? TEAMS_ROOT_DEFAULT,
    );
  }

  private repoRoot(): string {
    return resolve(this.cfg.get<string>("CARENOTE_REPO_ROOT") ?? REPO_ROOT_DEFAULT);
  }

  pathsFor(role: CodexAgentRole): RoleWorkspacePaths {
    const root = resolve(join(this.root(), safeSegment(role)));
    if (!root.startsWith(this.root() + "/") && root !== this.root()) {
      throw new Error(`role workspace path traversal: ${role}`);
    }
    return {
      root,
      claudeMd: join(root, "CLAUDE.md"),
      memoryDir: join(root, "memory"),
      memoryIndex: join(root, "memory", "MEMORY.md"),
      artifactsDir: join(root, "artifacts"),
      skillsDir: join(root, "skills"),
      inboxesDir: join(root, "inboxes"),
    };
  }

  /** Idempotent: create every directory + seed CLAUDE.md/MEMORY.md if missing. */
  async ensureRole(role: CodexAgentRole): Promise<RoleWorkspacePaths> {
    const p = this.pathsFor(role);
    await mkdir(p.memoryDir, { recursive: true });
    await mkdir(p.artifactsDir, { recursive: true });
    await mkdir(p.skillsDir, { recursive: true });
    await mkdir(p.inboxesDir, { recursive: true });

    if (!(await exists(p.claudeMd))) {
      await writeFile(p.claudeMd, await this.seedClaudeMd(role), "utf-8");
    }
    if (!(await exists(p.memoryIndex))) {
      await writeFile(p.memoryIndex, this.seedMemoryIndex(role), "utf-8");
    }

    // Drop a README into skills/ so users see the path is a real
    // discovery target (Qzone's WorkspaceService does the same).
    const skillsReadme = join(p.skillsDir, "README.md");
    if (!(await exists(skillsReadme))) {
      await writeFile(skillsReadme, this.seedSkillsReadme(role), "utf-8");
    }
    return p;
  }

  async ensureAll(): Promise<RoleWorkspacePaths[]> {
    const out: RoleWorkspacePaths[] = [];
    for (const role of CodexAgentRoleSchema.options) {
      out.push(await this.ensureRole(role));
    }
    this.logger.log(
      `role workspaces ready: ${out.length} roles under ${this.root()}`,
    );
    return out;
  }

  /**
   * Load this role's MEMORY.md (and any directly-listed sub-notes) for
   * injection into the codex prompt. Lightweight cache keyed by mtime so
   * subsequent role runs in the same turn don't re-read the file.
   * Returns null when the index file is empty (avoid bloating the prompt
   * with empty headers).
   */
  async loadMemoryForPrompt(role: CodexAgentRole): Promise<string | null> {
    const p = this.pathsFor(role);
    let raw: string;
    let mtime: number;
    try {
      const st = await stat(p.memoryIndex);
      mtime = st.mtimeMs;
      const cached = this.memoryCache.get(role);
      if (cached && cached.mtime === mtime) return cached.content || null;
      raw = await readFile(p.memoryIndex, "utf-8");
    } catch {
      return null;
    }
    const trimmed = raw.trim();
    if (!trimmed) {
      this.memoryCache.set(role, { content: "", mtime });
      return null;
    }
    // Cap the injected memory at ~6 KB to keep prompt tokens predictable.
    const capped = trimmed.length > 6000 ? trimmed.slice(0, 6000) + "\n…[truncated]" : trimmed;
    const block =
      `## Your private memory (role: ${role})\n` +
      `These notes were saved by you in past visits. Use them as durable context.\n\n` +
      capped;
    this.memoryCache.set(role, { content: block, mtime });
    return block;
  }

  /**
   * Append a one-line note to MEMORY.md. Used when a role wants to
   * remember something across visits (compaction is a future job).
   */
  async appendMemoryNote(role: CodexAgentRole, line: string): Promise<void> {
    const p = this.pathsFor(role);
    await mkdir(dirname(p.memoryIndex), { recursive: true });
    const ts = new Date().toISOString();
    const entry = `- ${ts} ${line.trim()}\n`;
    try {
      await writeFile(p.memoryIndex, entry, { flag: "a", encoding: "utf-8" });
    } catch (err) {
      this.logger.warn(
        `appendMemoryNote ${role} failed: ${(err as Error).message}`,
      );
    }
    this.memoryCache.delete(role);
  }

  // ─── seeding helpers ──────────────────────────────────────────────────

  private async seedClaudeMd(role: CodexAgentRole): Promise<string> {
    // Try to copy the canonical role prompt from prompts/codex-agents/<role>.md
    // so the workspace CLAUDE.md mirrors the registry prompt. If the source
    // is missing we fall back to a minimal stub; ensureRole stays idempotent.
    const candidates = [
      join(this.repoRoot(), "prompts", "codex-agents", `${role}.md`),
      // Older naming variants kept for safety; harmless if absent.
      join(this.repoRoot(), "prompts", "codex-agents", `${role.replace(/_/g, "-")}.md`),
    ];
    for (const c of candidates) {
      try {
        const body = await readFile(c, "utf-8");
        return (
          `# ${CodexAgentDisplayNames[role] ?? role}\n\n` +
          `Role slug: \`${role}\`\n\n` +
          `Workspace: \`<CARENOTE_TEAMS_ROOT>/${role}/\` ` +
          `(memory/, artifacts/, skills/, inboxes/)\n\n` +
          `---\n\n${body}`
        );
      } catch { /* try next */ }
    }
    return (
      `# ${CodexAgentDisplayNames[role] ?? role}\n\n` +
      `Role slug: \`${role}\`\n\n` +
      `_Prompt source not found. Edit \`prompts/codex-agents/${role}.md\` and ` +
      `re-seed this workspace, or delete this CLAUDE.md and restart the backend._\n`
    );
  }

  private seedMemoryIndex(role: CodexAgentRole): string {
    return (
      `# ${CodexAgentDisplayNames[role] ?? role} — memory index\n\n` +
      `Long-term notes this role accumulates across visits.\n` +
      `Each entry is one short line; topics live as their own \`<topic>.md\` ` +
      `files alongside this index when they grow beyond a sentence.\n\n` +
      `<!-- entries appended by RoleWorkspaceService.appendMemoryNote -->\n`
    );
  }

  private seedSkillsReadme(role: CodexAgentRole): string {
    return (
      `# Skills — ${CodexAgentDisplayNames[role] ?? role}\n\n` +
      `Drop \`SKILL.md\` files in this directory to give this role private ` +
      `skills it can call. Other roles never see this folder.\n\n` +
      `Layout: \`skills/<skill-name>/SKILL.md\` (front-matter: \`name\`, ` +
      `\`description\`, \`when_to_use\`).\n`
    );
  }

  async onModuleInit(): Promise<void> {
    try {
      await this.ensureAll();
    } catch (err) {
      this.logger.error(
        `RoleWorkspace init failed: ${(err as Error).message}`,
      );
    }
  }
}

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}
