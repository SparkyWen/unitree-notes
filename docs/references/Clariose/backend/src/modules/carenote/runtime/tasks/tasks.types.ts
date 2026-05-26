/**
 * Layer-1 Runtime Task — the unit of multi-agent work.
 *
 * Per CCLearn note 4 (`多agent4层通信机制和通信隔离`), Tasks are Layer 1: the
 * collaboration bus that every other layer (mailbox, blackboard, eventBus,
 * pretext) hangs off. Each codex role-run gets exactly one RuntimeTask. The
 * task tracks lifecycle, parent-child links, sidechain log offsets, and a
 * pending-message mailbox (Claude's `pendingMessages` pattern from
 * source/src/tasks/LocalAgentTask/LocalAgentTask.tsx).
 *
 * NOT to be confused with the user-facing `CarenoteTask` Prisma model, which
 * stores medical follow-up drafts the patient confirms or rejects.
 */

import type { CodexAgentRole } from "../../medical/medicalSchemas";
import type { WorkloadKind } from "../als/types";

export type RuntimeTaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "killed";

export type RuntimeTaskKind =
  /** Top-level container for a transcript-turn fan-out (parent of role tasks). */
  | "analyze_turn"
  /** A single codex role-run inside a turn fan-out. */
  | "role_run"
  /** Stage / final visit summary. */
  | "stage_summary"
  | "final_summary"
  /** On-demand single-role re-run triggered by a subscription. */
  | "on_demand_role"
  /** Auto-dream consolidation. */
  | "dream"
  /** A subagent forked off another role (future use). */
  | "subagent";

export interface RuntimeTaskProgress {
  toolUseCount: number;
  tokensIn: number;
  tokensOut: number;
  lastActivity: number;
  recentActivities: string[]; // last N tool-name+args summaries
}

export interface RuntimeTask {
  id: string;
  kind: RuntimeTaskKind;
  status: RuntimeTaskStatus;
  visitId: string;
  ownerUserId?: string;
  role?: CodexAgentRole;
  workload: WorkloadKind;
  /** parent task in the runtime tree, if any. */
  parentTaskId?: string;
  /** human-readable label rendered by the UI. */
  label: string;
  description: string;
  /** Original task creator (role name for child tasks; "system" for top-level). */
  createdBy: string;
  /** Layer-1 mailbox: messages parents push to this task between turns. */
  pendingMessages: Array<{ from: string; text: string; ts: number }>;
  /** Append-only sidechain log file for this task (turn-by-turn JSONL). */
  sidechainPath: string;
  /** Read cursor into the sidechain — caller increments on each tail. */
  sidechainOffset: number;
  /** Lifecycle abort controller (rotated per turn by TeammateContext). */
  abortController: AbortController;
  /** Mid-flight progress snapshot, updated on every codex turn. */
  progress: RuntimeTaskProgress;
  /** Final output bag (parsed_json, raw_text, validation_status, …). */
  output?: Record<string, unknown>;
  /** Error message when status === "failed". */
  errorMessage?: string;
  startedAt: number;
  finishedAt?: number;
  /** Telemetry: when set, indicates GC after this deadline. */
  evictAfter?: number;
}

export type RuntimeTaskEvent =
  | { type: "task_started"; task: RuntimeTaskSnapshot }
  | { type: "task_progress"; task: RuntimeTaskSnapshot; recent?: string }
  | { type: "task_completed"; task: RuntimeTaskSnapshot }
  | { type: "task_failed"; task: RuntimeTaskSnapshot; error: string }
  | { type: "task_killed"; task: RuntimeTaskSnapshot; reason?: string }
  | { type: "task_message_queued"; taskId: string; from: string; text: string };

/** Public DTO — strips abortController + sidechain internals. */
export interface RuntimeTaskSnapshot {
  id: string;
  kind: RuntimeTaskKind;
  status: RuntimeTaskStatus;
  visitId: string;
  role?: CodexAgentRole;
  workload: WorkloadKind;
  parentTaskId?: string;
  label: string;
  description: string;
  createdBy: string;
  progress: RuntimeTaskProgress;
  output?: Record<string, unknown>;
  errorMessage?: string;
  startedAt: number;
  finishedAt?: number;
  pendingMessageCount: number;
  sidechainOffset: number;
}
