/**
 * Backpack types for the carenote multi-agent runtime.
 *
 * The 4-layer communication model from CCLearn/notes_integrated/4 is realized
 * here through three nested AsyncLocalStorage stores. Each store carries a
 * different lifetime:
 *
 *   AgentContext    — identity that lasts for the whole role-run
 *   TeammateContext — runtime handle (abort, turn index) that rotates per turn
 *   WorkloadContext — orthogonal tag (turn, dream, cron, …) used for telemetry
 *
 * The bag is read via *.current() inside any deeply-nested codex tool turn
 * without parameter threading. This is the same pattern Claude Code uses in
 * source/src/utils/agentContext.ts to prevent cross-agent leakage when
 * multiple agents share a single Node event loop.
 */

import type { CodexAgentRole } from "../../medical/medicalSchemas";

export type AgentContextKind = "subagent" | "teammate" | "main";

/**
 * Shared identity for any role-run. `taskId` is the Layer-1 anchor — every
 * downstream layer (mailbox, blackboard, eventBus) reads it from here so
 * messages are always attributed to the right (visit, role, task) triple.
 */
export interface AgentContext {
  agentType: AgentContextKind;
  /** Stable per-run identifier. Equal to the codex run_id when known. */
  agentRunId: string;
  /** Layer-1 task id allocated by TasksService for this role-run. */
  taskId: string;
  /** Parent task id for nested role-runs (e.g. analyze_turn → role). */
  parentTaskId?: string;
  /** Visit / consult-session this run belongs to. */
  visitId: string;
  /** Owner of the visit; resolved once at task registration. */
  ownerUserId?: string;
  /** Codex role (e.g. medical_instruction_extractor). Optional for non-role tasks. */
  role?: CodexAgentRole;
  /** Display label for traces / SSE. */
  label: string;
  /** OpenTelemetry-style trace id; opaque to us. */
  traceId?: string;
  /** When set, indicates this run was triggered by a tool_use of the parent. */
  invokingToolUseId?: string;
  /** One-shot guard: telemetry consumes this on first emit. */
  invocationEmitted?: boolean;
}

/**
 * Per-turn runtime handle. Rotates on each codex turn so a turn-level abort
 * never bleeds into the next turn. Mirrors Claude's TeammateContext.
 */
export interface TeammateContext {
  taskId: string;
  abortController: AbortController;
  turnIndex: number;
  hopCount: number;
  deadlineMs?: number;
}

export type WorkloadKind =
  | "turn"
  | "stage_summary"
  | "final_summary"
  | "dream"
  | "on_demand"
  | "cron";

export interface WorkloadContext {
  workload: WorkloadKind;
}
