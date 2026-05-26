import { AsyncLocalStorage } from "node:async_hooks";
import { Injectable } from "@nestjs/common";

import type { WorkloadContext, WorkloadKind } from "./types";

/**
 * WorkloadContextService — orthogonal tag store.
 *
 * Records the *kind* of work the current async chain is doing
 * (`turn` | `stage_summary` | `final_summary` | `dream` | `on_demand` | `cron`),
 * so quota / rate-limit / telemetry can discriminate without threading another
 * argument through every codex call. Mirrors Claude's WorkloadContext, where
 * the cron scheduler tags itself `'cron'` and downstream API headers route
 * accordingly.
 */
@Injectable()
export class WorkloadContextService {
  private readonly storage = new AsyncLocalStorage<WorkloadContext>();

  run<T>(workload: WorkloadKind, fn: () => T): T {
    return this.storage.run({ workload }, fn);
  }

  current(): WorkloadKind | undefined {
    return this.storage.getStore()?.workload;
  }
}
