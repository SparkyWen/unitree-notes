import { AsyncLocalStorage } from "node:async_hooks";
import { Injectable } from "@nestjs/common";

import type { AgentContext } from "./types";

/**
 * AgentContextService — Layer-1 identity backpack.
 *
 * Mirrors Claude Code's `runWithAgentContext` (source/src/utils/agentContext.ts)
 * and Qagent's `AgentContextService`. The store is consulted by every
 * downstream layer (Tasks → Mailbox → Blackboard → EventBus) so a single
 * codex tool turn never has to thread `(visitId, role, taskId, …)` through
 * its argument list — `agentCtx.current()` is enough.
 *
 * Why AsyncLocalStorage and not a request-scoped provider:
 *   Multiple agents run concurrently in the same Node event loop (analyze_turn
 *   fans out 4 roles in parallel). NestJS request scope would create one
 *   instance per HTTP request, but our concurrency unit is the codex run, not
 *   the HTTP request — and many runs are background-driven (subscriptions,
 *   dream cron, on-demand). AsyncLocalStorage isolates each async chain
 *   regardless of how it was kicked off.
 */
@Injectable()
export class AgentContextService {
  private readonly storage = new AsyncLocalStorage<AgentContext>();

  /** Run `fn` with `ctx` bound to the current async chain. */
  run<T>(ctx: AgentContext, fn: () => T): T {
    return this.storage.run(ctx, fn);
  }

  /** The current bag, or `undefined` outside an `als.run()` scope. */
  current(): AgentContext | undefined {
    return this.storage.getStore();
  }

  /** Throws if called outside an `als.run()` scope. */
  require(): AgentContext {
    const ctx = this.storage.getStore();
    if (!ctx) {
      throw new Error(
        "AgentContext is not bound — call agentCtx.run(...) before invoking work that reads from it",
      );
    }
    return ctx;
  }

  /**
   * Telemetry one-shot: returns `invokingToolUseId` exactly once per scope, so
   * the spawn edge is logged on the first turn but not repeated. Mutates the
   * bag in place; safe because the bag belongs to exactly one async chain.
   */
  consumeInvokingToolUseId(): string | undefined {
    const ctx = this.storage.getStore();
    if (!ctx || !ctx.invokingToolUseId || ctx.invocationEmitted) return undefined;
    ctx.invocationEmitted = true;
    return ctx.invokingToolUseId;
  }
}
