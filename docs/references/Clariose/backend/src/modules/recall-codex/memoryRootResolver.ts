// MemoryRootResolver — maps a userId to a stable filesystem path under
// MEMORY_ROOT. The actual sha256-derived namespace lives on the User row
// (`recallNamespace` column); this service backfills it lazily on first
// touch so existing users don't need a migration step.

import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { createHash } from "node:crypto";
import { join } from "node:path";

import { PrismaService } from "../../common/prisma/prisma.service";
import { MEMORY_ROOT_DEFAULT } from "./recall.constants";

@Injectable()
export class MemoryRootResolver {
  constructor(
    private readonly prisma: PrismaService,
    private readonly cfg: ConfigService,
  ) {}

  /** Filesystem root for ALL users' memories. Single config knob via
   *  `RECALL_MEMORY_ROOT`; defaults to `~/.zai/memories`. */
  rootDir(): string {
    return this.cfg.get<string>("RECALL_MEMORY_ROOT") ?? MEMORY_ROOT_DEFAULT;
  }

  /** Returns the memories directory for a single user, ensuring the
   *  user has a `recallNamespace` set. The directory itself is created
   *  by FilesystemBootstrapper, not here. */
  async resolveForUser(userId: string): Promise<{ namespace: string; root: string }> {
    const user = await this.prisma.user.findUnique({
      where: { id: userId },
      select: { recallNamespace: true },
    });
    if (!user) throw new Error(`recall: user ${userId} not found`);

    let ns = user.recallNamespace;
    if (!ns) {
      ns = createHash("sha256").update(userId).digest("hex").slice(0, 16);
      // Race-safe: if another request stamped first, fetch the winner.
      try {
        await this.prisma.user.update({
          where: { id: userId },
          data: { recallNamespace: ns },
        });
      } catch {
        const fresh = await this.prisma.user.findUnique({
          where: { id: userId },
          select: { recallNamespace: true },
        });
        ns = fresh?.recallNamespace ?? ns;
      }
    }

    return { namespace: ns, root: join(this.rootDir(), ns) };
  }
}
