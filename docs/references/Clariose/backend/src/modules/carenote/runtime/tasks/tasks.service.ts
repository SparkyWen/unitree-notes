import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { homedir } from "node:os";
import { Inject, Injectable, Logger, NotFoundException, Optional } from "@nestjs/common";

import { CarenoteEventBus } from "../../swarm/eventBus";
import { SidechainService } from "./sidechain.service";
import type {
  RuntimeTask,
  RuntimeTaskEvent,
  RuntimeTaskKind,
  RuntimeTaskProgress,
  RuntimeTaskSnapshot,
  RuntimeTaskStatus,
} from "./tasks.types";
import type { CodexAgentRole } from "../../medical/medicalSchemas";
import type { WorkloadKind } from "../als/types";

const RECENT_ACTIVITY_CAP = 20;
const PANEL_GRACE_MS = 60 * 60 * 1000; // 1 hour, matches Claude

const ROOT =
  process.env.CARENOTE_TASKS_ROOT?.trim() ||
  join(homedir(), ".carenote", "tasks");

/**
 * TasksService — Layer-1 multi-agent collaboration bus.
 *
 * "Tasks 是多agent通信和任务的核心" — every codex role-run is wrapped in a
 * RuntimeTask. The task is registered before the codex call begins and
 * disposed when it terminates. While alive, parents and tools can:
 *
 *   - read its progress (`get`, `list`, `listForVisit`),
 *   - tail its sidechain log (`tail`),
 *   - push a message into its mailbox (`queueMessage`) — picked up at the
 *     next turn boundary à la Claude's SendMessage,
 *   - cancel it (`kill`).
 *
 * Parent-child links are honored — `analyze_turn` tasks own a tree of
 * `role_run` children; cancelling the parent cascades to children via the
 * shared abort pattern (see CodexRunManager integration).
 */
@Injectable()
export class TasksService {
  private readonly logger = new Logger("RuntimeTasks");
  private readonly tasks = new Map<string, RuntimeTask>();

  constructor(
    private readonly sidechain: SidechainService,
    @Optional() @Inject(CarenoteEventBus) private readonly bus?: CarenoteEventBus,
  ) {}

  // ── Lifecycle ─────────────────────────────────────────────────────────

  register(args: {
    kind: RuntimeTaskKind;
    visitId: string;
    role?: CodexAgentRole;
    workload: WorkloadKind;
    label: string;
    description: string;
    createdBy: string;
    parentTaskId?: string;
    ownerUserId?: string;
    abortController?: AbortController;
  }): RuntimeTask {
    const id = makeTaskId(args.kind);
    const task: RuntimeTask = {
      id,
      kind: args.kind,
      status: "running",
      visitId: args.visitId,
      ownerUserId: args.ownerUserId,
      role: args.role,
      workload: args.workload,
      parentTaskId: args.parentTaskId,
      label: args.label,
      description: args.description,
      createdBy: args.createdBy,
      pendingMessages: [],
      sidechainPath: join(ROOT, args.visitId, `${id}.jsonl`),
      sidechainOffset: 0,
      abortController: args.abortController ?? new AbortController(),
      progress: emptyProgress(),
      startedAt: Date.now(),
    };
    this.tasks.set(id, task);
    void this.sidechain.append(task.sidechainPath, {
      ts: task.startedAt,
      type: "task_started",
      taskId: id,
      kind: task.kind,
      visitId: task.visitId,
      role: task.role,
      parentTaskId: task.parentTaskId,
      label: task.label,
    });
    this.emit({ type: "task_started", task: snapshot(task) });
    return task;
  }

  /** Mid-flight progress update from inside a codex turn. */
  addTurn(
    taskId: string,
    turn: {
      toolUseCount?: number;
      tokensIn?: number;
      tokensOut?: number;
      lastTool?: string;
      message?: unknown;
    },
  ): void {
    const task = this.tasks.get(taskId);
    if (!task) return;
    const p = task.progress;
    if (turn.toolUseCount) p.toolUseCount += turn.toolUseCount;
    if (turn.tokensIn) p.tokensIn += turn.tokensIn;
    if (turn.tokensOut) p.tokensOut += turn.tokensOut;
    p.lastActivity = Date.now();
    if (turn.lastTool) {
      p.recentActivities.push(turn.lastTool);
      if (p.recentActivities.length > RECENT_ACTIVITY_CAP) {
        p.recentActivities.splice(0, p.recentActivities.length - RECENT_ACTIVITY_CAP);
      }
    }
    if (turn.message !== undefined) {
      void this.sidechain.append(task.sidechainPath, {
        ts: Date.now(),
        type: "turn",
        taskId,
        message: turn.message,
      });
    }
    this.emit({ type: "task_progress", task: snapshot(task), recent: turn.lastTool });
  }

  complete(taskId: string, output?: Record<string, unknown>): RuntimeTask | undefined {
    const task = this.tasks.get(taskId);
    if (!task) return undefined;
    task.status = "completed";
    task.output = output;
    task.finishedAt = Date.now();
    task.evictAfter = task.finishedAt + PANEL_GRACE_MS;
    void this.sidechain.append(task.sidechainPath, {
      ts: task.finishedAt,
      type: "task_completed",
      taskId,
      output,
    });
    this.emit({ type: "task_completed", task: snapshot(task) });
    return task;
  }

  fail(taskId: string, error: string): RuntimeTask | undefined {
    const task = this.tasks.get(taskId);
    if (!task) return undefined;
    task.status = "failed";
    task.errorMessage = error;
    task.finishedAt = Date.now();
    task.evictAfter = task.finishedAt + PANEL_GRACE_MS;
    void this.sidechain.append(task.sidechainPath, {
      ts: task.finishedAt,
      type: "task_failed",
      taskId,
      error,
    });
    this.emit({ type: "task_failed", task: snapshot(task), error });
    return task;
  }

  /**
   * Cooperative cancellation: aborts this task AND every descendant. The
   * codex turn loop checks `abortController.signal` between tool turns and
   * rejects with AbortError. Parents propagate so analyze_turn → role_run
   * cancels its whole fan-out.
   */
  kill(taskId: string, reason?: string): RuntimeTask | undefined {
    const task = this.tasks.get(taskId);
    if (!task) return undefined;
    task.status = "killed";
    task.finishedAt = Date.now();
    task.evictAfter = task.finishedAt + PANEL_GRACE_MS;
    try {
      task.abortController.abort(reason ?? "killed");
    } catch {
      /* ignore */
    }
    // Cascade
    for (const child of this.tasks.values()) {
      if (child.parentTaskId === taskId && child.status === "running") {
        this.kill(child.id, `parent ${taskId} killed`);
      }
    }
    void this.sidechain.append(task.sidechainPath, {
      ts: task.finishedAt,
      type: "task_killed",
      taskId,
      reason,
    });
    this.emit({ type: "task_killed", task: snapshot(task), reason });
    return task;
  }

  // ── Layer-1 mailbox (parent → task pending messages) ─────────────────

  /**
   * Push a message that the task will see at its next turn boundary. Mirrors
   * Claude's SendMessage tool — soft injection rather than a hard interrupt.
   */
  queueMessage(taskId: string, from: string, text: string): boolean {
    const task = this.tasks.get(taskId);
    if (!task || task.status !== "running") return false;
    task.pendingMessages.push({ from, text, ts: Date.now() });
    this.emit({ type: "task_message_queued", taskId, from, text });
    return true;
  }

  /** Drain pending messages — called by the role's turn loop. */
  drainPending(taskId: string): Array<{ from: string; text: string; ts: number }> {
    const task = this.tasks.get(taskId);
    if (!task) return [];
    const out = task.pendingMessages.slice();
    task.pendingMessages.length = 0;
    return out;
  }

  // ── Reads ────────────────────────────────────────────────────────────

  get(taskId: string): RuntimeTask {
    const t = this.tasks.get(taskId);
    if (!t) throw new NotFoundException(`runtime task ${taskId} not found`);
    return t;
  }

  snapshot(taskId: string): RuntimeTaskSnapshot {
    return snapshot(this.get(taskId));
  }

  listForVisit(
    visitId: string,
    opts: { status?: RuntimeTaskStatus; includeChildren?: boolean } = {},
  ): RuntimeTaskSnapshot[] {
    const out: RuntimeTaskSnapshot[] = [];
    for (const t of this.tasks.values()) {
      if (t.visitId !== visitId) continue;
      if (opts.status && t.status !== opts.status) continue;
      out.push(snapshot(t));
    }
    return out.sort((a, b) => a.startedAt - b.startedAt);
  }

  /** Tail the sidechain JSONL from `offset`. */
  async tail(taskId: string, offset?: number): Promise<{ entries: unknown[]; offset: number }> {
    const task = this.get(taskId);
    return this.sidechain.tail(task.sidechainPath, offset ?? task.sidechainOffset);
  }

  // ── GC ───────────────────────────────────────────────────────────────

  /** Drop terminal tasks past their grace window. Call from a cron tick. */
  evict(): number {
    const now = Date.now();
    let count = 0;
    for (const [id, t] of this.tasks) {
      if (t.evictAfter && now > t.evictAfter) {
        this.tasks.delete(id);
        count += 1;
      }
    }
    return count;
  }

  // ── Internals ────────────────────────────────────────────────────────

  private emit(ev: RuntimeTaskEvent) {
    if (!this.bus) return;
    try {
      switch (ev.type) {
        case "task_started":
          this.bus.emit({
            type: "runtime_task",
            visitId: ev.task.visitId,
            taskId: ev.task.id,
            parentTaskId: ev.task.parentTaskId,
            status: "running",
            kind: ev.task.kind,
            role: ev.task.role,
            label: ev.task.label,
          });
          break;
        case "task_progress":
          this.bus.emit({
            type: "runtime_task",
            visitId: ev.task.visitId,
            taskId: ev.task.id,
            parentTaskId: ev.task.parentTaskId,
            status: "running",
            kind: ev.task.kind,
            role: ev.task.role,
            label: ev.task.label,
            recent: ev.recent,
          });
          break;
        case "task_completed":
          this.bus.emit({
            type: "runtime_task",
            visitId: ev.task.visitId,
            taskId: ev.task.id,
            parentTaskId: ev.task.parentTaskId,
            status: "completed",
            kind: ev.task.kind,
            role: ev.task.role,
            label: ev.task.label,
          });
          break;
        case "task_failed":
          this.bus.emit({
            type: "runtime_task",
            visitId: ev.task.visitId,
            taskId: ev.task.id,
            parentTaskId: ev.task.parentTaskId,
            status: "failed",
            kind: ev.task.kind,
            role: ev.task.role,
            label: ev.task.label,
            error: ev.error,
          });
          break;
        case "task_killed":
          this.bus.emit({
            type: "runtime_task",
            visitId: ev.task.visitId,
            taskId: ev.task.id,
            parentTaskId: ev.task.parentTaskId,
            status: "killed",
            kind: ev.task.kind,
            role: ev.task.role,
            label: ev.task.label,
            reason: ev.reason,
          });
          break;
        case "task_message_queued": {
          const visitId = this.tasks.get(ev.taskId)?.visitId ?? "";
          this.bus.emit({
            type: "mailbox_message",
            visitId,
            from: ev.from,
            to: `task:${ev.taskId}`,
            payloadKind: "task_message",
          });
          break;
        }
      }
    } catch (err) {
      this.logger.warn(`emit failed: ${(err as Error).message}`);
    }
  }
}

function makeTaskId(kind: RuntimeTaskKind): string {
  // Short prefix mirrors Claude's 'a-uuid' / 'r-uuid' convention so the kind
  // is visible at a glance in logs without parsing the task body.
  const prefix =
    kind === "analyze_turn"
      ? "t"
      : kind === "role_run"
      ? "r"
      : kind === "stage_summary"
      ? "ss"
      : kind === "final_summary"
      ? "fs"
      : kind === "on_demand_role"
      ? "od"
      : kind === "dream"
      ? "d"
      : "s";
  return `${prefix}-${randomUUID()}`;
}

function emptyProgress(): RuntimeTaskProgress {
  return {
    toolUseCount: 0,
    tokensIn: 0,
    tokensOut: 0,
    lastActivity: Date.now(),
    recentActivities: [],
  };
}

function snapshot(t: RuntimeTask): RuntimeTaskSnapshot {
  return {
    id: t.id,
    kind: t.kind,
    status: t.status,
    visitId: t.visitId,
    role: t.role,
    workload: t.workload,
    parentTaskId: t.parentTaskId,
    label: t.label,
    description: t.description,
    createdBy: t.createdBy,
    progress: { ...t.progress, recentActivities: [...t.progress.recentActivities] },
    output: t.output,
    errorMessage: t.errorMessage,
    startedAt: t.startedAt,
    finishedAt: t.finishedAt,
    pendingMessageCount: t.pendingMessages.length,
    sidechainOffset: t.sidechainOffset,
  };
}
