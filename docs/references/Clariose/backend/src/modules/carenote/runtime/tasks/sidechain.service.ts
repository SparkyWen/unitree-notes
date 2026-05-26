import { promises as fs } from "node:fs";
import { dirname } from "node:path";
import { Injectable, Logger } from "@nestjs/common";

/**
 * SidechainService — append-only JSONL log for one runtime task.
 *
 * Mirrors Claude Code's `sidechain.jsonl` per-task file
 * (~/.claude/sessions/<sessionId>/subagents/<agentId>/sidechain.jsonl). Each
 * line is one event the task wants to remember: a tool turn, an LLM message,
 * a queued user message, a child-task spawn record. Parents tail this file
 * to reconstruct progress without holding a reference to the live task.
 *
 * Why a file instead of a DB table:
 *   - Tasks emit on the order of dozens of events per turn; appending to a
 *     local file is O(1) and survives process restart.
 *   - Tail-reads use byte offsets, so resuming the read cursor after a UI
 *     reconnect is cheap (no SQL pagination).
 *   - Sidechain files are addressed by `taskId`; cleanup is a single rmdir.
 */
@Injectable()
export class SidechainService {
  private readonly logger = new Logger("Sidechain");

  /** Append a JSON line. Creates parent dirs as needed. Errors are logged. */
  async append(path: string, line: unknown): Promise<void> {
    try {
      await fs.mkdir(dirname(path), { recursive: true });
      const payload = JSON.stringify(line) + "\n";
      await fs.appendFile(path, payload, "utf-8");
    } catch (err) {
      // Sidechain failures must never break a codex run; just log.
      this.logger.warn(
        `sidechain append failed for ${path}: ${(err as Error).message}`,
      );
    }
  }

  /** Read the file from `offset` to EOF; return parsed JSON lines + new offset. */
  async tail(
    path: string,
    offset: number,
  ): Promise<{ entries: unknown[]; offset: number }> {
    try {
      const stat = await fs.stat(path);
      if (offset >= stat.size) return { entries: [], offset };
      const fh = await fs.open(path, "r");
      try {
        const buf = Buffer.alloc(stat.size - offset);
        await fh.read(buf, 0, buf.length, offset);
        const lines = buf
          .toString("utf-8")
          .split("\n")
          .filter((l) => l.length > 0);
        const entries = lines
          .map((l) => {
            try {
              return JSON.parse(l) as unknown;
            } catch {
              return { _unparsable: l };
            }
          });
        return { entries, offset: stat.size };
      } finally {
        await fh.close();
      }
    } catch (err) {
      // Missing file is normal (task hasn't written anything yet).
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        return { entries: [], offset };
      }
      this.logger.warn(
        `sidechain tail failed for ${path}: ${(err as Error).message}`,
      );
      return { entries: [], offset };
    }
  }

  /** Best-effort delete (used on visit deletion). */
  async unlink(path: string): Promise<void> {
    try {
      await fs.unlink(path);
    } catch {
      /* ignore */
    }
  }
}
