// CLARIOSE_V01 §5.2 — auto-dream consolidation lock.
//
// Two-tier lock to prevent two workers consolidating the same user at once:
//   1. File: <memory_root>/users/<userId>/.consolidation.lock created with
//      O_EXCL. Existing → another worker is in flight; bail.
//   2. DB row: UserDreamLock (PK userId) for ops visibility — who's holding
//      the lock and on what PID. Created best-effort after the file lock
//      succeeds; DB failure does NOT release the file lock.
//
// Lock TTL is 30 minutes. After that, a stale file is treated as broken
// (the holder PID likely crashed); the next acquirer will rm it and proceed.

import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { mkdir, open, stat, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { PrismaService } from "../../../common/prisma/prisma.service";

const MEMORY_ROOT_DEFAULT = "/home/ubuntu/Zai/.data/carenote/memory";
const LOCK_TTL_MS = 30 * 60 * 1000; // 30 min

@Injectable()
export class ConsolidationLockService {
  private readonly logger = new Logger("ConsolidationLock");

  constructor(
    private readonly cfg: ConfigService,
    private readonly prisma: PrismaService,
  ) {}

  private root(): string {
    return this.cfg.get<string>("CARENOTE_MEMORY_ROOT") ?? MEMORY_ROOT_DEFAULT;
  }

  private lockPath(user_id: string): string {
    return join(this.root(), "users", user_id, ".consolidation.lock");
  }

  /** Try to acquire. Returns true if held, false if someone else holds it.
   *  Implementation: O_EXCL create; if EEXIST and the file is stale (older
   *  than LOCK_TTL_MS), remove it and retry once. */
  async acquire(user_id: string): Promise<boolean> {
    const path = this.lockPath(user_id);
    await mkdir(join(this.root(), "users", user_id), { recursive: true });
    const tryCreate = async (): Promise<"acquired" | "exists"> => {
      try {
        // O_EXCL via flag 'wx': create or fail with EEXIST.
        const fh = await open(path, "wx");
        await fh.write(`${process.pid}\n${new Date().toISOString()}\n`);
        await fh.close();
        return "acquired";
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === "EEXIST") return "exists";
        throw err;
      }
    };
    let r = await tryCreate();
    if (r === "exists") {
      const st = await stat(path).catch(() => null);
      if (st && Date.now() - st.mtimeMs > LOCK_TTL_MS) {
        this.logger.warn(`stale lock for user=${user_id}, breaking`);
        await unlink(path).catch(() => undefined);
        r = await tryCreate();
      }
    }
    if (r !== "acquired") return false;

    // Best-effort DB row for ops visibility.
    void this.prisma.userDreamLock
      .upsert({
        where: { userId: user_id },
        create: {
          userId: user_id,
          acquiredAt: new Date(),
          expiresAt: new Date(Date.now() + LOCK_TTL_MS),
          acquiredByPid: process.pid,
        },
        update: {
          acquiredAt: new Date(),
          expiresAt: new Date(Date.now() + LOCK_TTL_MS),
          acquiredByPid: process.pid,
        },
      })
      .catch((err) =>
        this.logger.warn(`DB lock row upsert failed: ${(err as Error).message}`),
      );
    return true;
  }

  async release(user_id: string): Promise<void> {
    const path = this.lockPath(user_id);
    await unlink(path).catch(() => undefined);
    void this.prisma.userDreamLock
      .delete({ where: { userId: user_id } })
      .catch(() => undefined);
  }

  /** True if the file currently exists (and isn't stale). */
  async isHeld(user_id: string): Promise<boolean> {
    const path = this.lockPath(user_id);
    const st = await stat(path).catch(() => null);
    if (!st) return false;
    return Date.now() - st.mtimeMs <= LOCK_TTL_MS;
  }

  /** Write a snapshot of a file before mutation so a failed dream can roll
   *  back. Returns the snapshot path or null if the source doesn't exist. */
  async snapshotFile(absPath: string, suffix: string): Promise<string | null> {
    const fs = await import("node:fs/promises");
    try {
      const buf = await fs.readFile(absPath);
      const snap = `${absPath}.${suffix}.bak`;
      await fs.writeFile(snap, buf);
      return snap;
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw err;
    }
  }
}

/** Helper for callers that don't want to manage timestamps themselves. */
export async function safeWriteWithBackup(
  absPath: string,
  content: string,
): Promise<void> {
  const fs = await import("node:fs/promises");
  await fs.mkdir(join(absPath, ".."), { recursive: true });
  await fs.writeFile(absPath, content, "utf-8");
}
