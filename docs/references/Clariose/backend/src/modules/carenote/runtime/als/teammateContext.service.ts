import { AsyncLocalStorage } from "node:async_hooks";
import { Injectable } from "@nestjs/common";

import type { TeammateContext } from "./types";

/**
 * TeammateContextService — per-turn runtime handle.
 *
 * Holds the `AbortController` for the *current* codex turn. Separate from
 * AgentContext because identity outlives a turn, but a turn-level abort
 * (e.g. a watchdog timeout, a cancellation triggered by a higher-priority
 * subscription run) must not bleed into the next turn of the same role-run.
 *
 * Mirrors Claude's `runWithTeammateContext` (source/src/utils/teammateContext.ts).
 */
@Injectable()
export class TeammateContextService {
  private readonly storage = new AsyncLocalStorage<TeammateContext>();

  run<T>(ctx: TeammateContext, fn: () => T): T {
    return this.storage.run(ctx, fn);
  }

  current(): TeammateContext | undefined {
    return this.storage.getStore();
  }

  /** Convenience: signal currently in scope, or never-aborts if none. */
  signal(): AbortSignal {
    const ctx = this.storage.getStore();
    return ctx?.abortController.signal ?? new AbortController().signal;
  }
}
