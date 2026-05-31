// CLARIOSE_V01 §3 Layer 1 — file-backed inbox with proper-lockfile.
//
// Path: <root>/<visit_id>/inboxes/<role>.json (JSON array of TeammateMessage).
// Lock: proper-lockfile {retries: 5 backoff factor 2 100ms..30s, stale: 30s}.
//
// Atomic write: ensure dir → seed `[]` with flag 'wx' → lock → read → push →
// writeFile pretty → release. Same pattern as Qagent teammate-mailbox.service.ts.

import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { lock } from "proper-lockfile";

import type { TeammateMessage } from "./mailboxMessages";

const TEAMS_ROOT_DEFAULT = "/home/ubuntu/Zai/.data/carenote/teams";

const LOCK_OPTS = {
  retries: { retries: 5, factor: 2, minTimeout: 100, maxTimeout: 30_000 },
  stale: 30_000,
};

// CLARIOSE_V01 §security — path-component sanitizer. visit_id is a Prisma
// cuid and role is from a fixed enum, but defense-in-depth: anything that
// isn't [A-Za-z0-9_-] is replaced with '_'. Length-capped to 64 chars.
function safeSegment(s: string): string {
  return (s ?? "").replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 64) || "_";
}

@Injectable()
export class MailboxFileService {
  private readonly logger = new Logger("MailboxFile");

  constructor(private readonly cfg: ConfigService) {}

  private root(): string {
    return this.cfg.get<string>("CARENOTE_TEAMS_ROOT") ?? TEAMS_ROOT_DEFAULT;
  }

  private inboxPath(visit_id: string, role: string): string {
    // Agent-centric layout (matches Qzone): each role owns its inbox dir,
    // and the file inside is keyed by visit. The previous visit-centric
    // layout (`<visit>/inboxes/<role>.json`) scattered each agent's mail
    // across one folder per visit — making "show me everything in
    // medical_instruction_extractor's inbox" expensive. RoleWorkspaceService
    // creates `<role>/inboxes/` at startup so this directory always exists.
    //
    // Sanitize both segments AND verify the resolved path stays inside root.
    // Belt-and-suspenders: regex strips path separators / dots; resolve()
    // catches anything weird that slipped through.
    const root = resolve(this.root());
    const path = resolve(
      join(root, safeSegment(role), "inboxes", `${safeSegment(visit_id)}.json`),
    );
    if (!path.startsWith(root + "/") && path !== root) {
      throw new Error(`mailbox path traversal attempt: ${visit_id}/${role}`);
    }
    return path;
  }

  private lockPath(visit_id: string, role: string): string {
    return `${this.inboxPath(visit_id, role)}.lock`;
  }

  /** Ensure the inbox file exists with an empty array. EEXIST is fine; some
   *  other process (or our previous `wx`) seeded it. */
  private async ensureInbox(visit_id: string, role: string): Promise<string> {
    const path = this.inboxPath(visit_id, role);
    try {
      await mkdir(dirname(path), { recursive: true });
      await writeFile(path, "[]", { encoding: "utf-8", flag: "wx" });
    } catch (err) {
      const code = (err as NodeJS.ErrnoException).code;
      if (code !== "EEXIST") throw err;
    }
    return path;
  }

  /** Read the full inbox. Returns [] on any I/O or parse failure (defensive). */
  async read(visit_id: string, role: string): Promise<TeammateMessage[]> {
    const path = this.inboxPath(visit_id, role);
    try {
      const raw = await readFile(path, "utf-8");
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as TeammateMessage[]) : [];
    } catch (err) {
      const code = (err as NodeJS.ErrnoException).code;
      if (code === "ENOENT") return [];
      this.logger.warn(
        `read(${visit_id}/${role}) failed: ${(err as Error).message}`,
      );
      return [];
    }
  }

  /** Append one message under advisory lock. Returns the index it was
   *  written at — useful for DB mirror correlation. */
  async append(
    visit_id: string,
    role: string,
    message: Omit<TeammateMessage, "read"> & { read?: false },
  ): Promise<number> {
    const path = await this.ensureInbox(visit_id, role);
    const release = await lock(path, {
      lockfilePath: this.lockPath(visit_id, role),
      ...LOCK_OPTS,
    });
    try {
      const messages = await this.read(visit_id, role);
      const next: TeammateMessage = { ...message, read: false };
      messages.push(next);
      await writeFile(path, JSON.stringify(messages, null, 2), "utf-8");
      return messages.length - 1;
    } finally {
      await release();
    }
  }

  /** Mark one message as read by index. No-op if out of range. */
  async markRead(visit_id: string, role: string, index: number): Promise<void> {
    const path = this.inboxPath(visit_id, role);
    let release: (() => Promise<void>) | null = null;
    try {
      release = await lock(path, {
        lockfilePath: this.lockPath(visit_id, role),
        ...LOCK_OPTS,
      });
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return;
      throw err;
    }
    try {
      const messages = await this.read(visit_id, role);
      if (index < 0 || index >= messages.length) return;
      messages[index]!.read = true;
      await writeFile(path, JSON.stringify(messages, null, 2), "utf-8");
    } finally {
      await release();
    }
  }

  /** Mark all currently unread messages as read in a single locked pass.
   *  Returns the count of messages flipped. Used by runRole to drain inbox
   *  before assembling the prompt. */
  async drainUnread(
    visit_id: string,
    role: string,
  ): Promise<TeammateMessage[]> {
    const path = this.inboxPath(visit_id, role);
    let release: (() => Promise<void>) | null = null;
    try {
      release = await lock(path, {
        lockfilePath: this.lockPath(visit_id, role),
        ...LOCK_OPTS,
      });
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return [];
      throw err;
    }
    try {
      const messages = await this.read(visit_id, role);
      const drained: TeammateMessage[] = [];
      let mutated = false;
      for (const m of messages) {
        if (!m.read) {
          drained.push({ ...m });
          m.read = true;
          mutated = true;
        }
      }
      if (mutated) {
        await writeFile(path, JSON.stringify(messages, null, 2), "utf-8");
      }
      return drained;
    } finally {
      await release();
    }
  }
}
