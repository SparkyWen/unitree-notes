// CarenoteEventBus — in-process pub-sub for visit events.
//
// CLARIOSE_V01: implements §8.1.
//
// All carenote runtime side-effects (transcript turns, agent runs, blackboard
// writes, mailbox messages, permission responses) emit through this single
// RxJS Subject. Subscribers:
//   - SSE controller streams events for one visit to the browser
//   - CodexRunManager listens for blackboard_updated to fire on-demand re-runs
//   - PermissionBridge listens for permission_response to resolve waiting promises
//
// Pattern is a 1:1 port of Qagent's orchestrator/events/event-bus.service.ts.
// Single-process by design; if we ever go multi-host this becomes Redis Pub-Sub.

import { Injectable } from "@nestjs/common";
import { Observable, Subject, filter } from "rxjs";

export type CarenoteEvent =
  | {
      type: "transcript_turn_committed";
      visitId: string;
      turnId: string;
      text: string;
      speaker: string;
    }
  | {
      type: "transcript_turn_completed";
      visitId: string;
      turnId: string;
      transcript: string;
    }
  | {
      type: "agent_run_started";
      visitId: string;
      role: string;
      runId: string;
    }
  | {
      type: "agent_run_completed";
      visitId: string;
      role: string;
      runId: string;
      status: "valid" | "repaired" | "failed";
    }
  | {
      type: "blackboard_updated";
      visitId: string;
      key: string;
      writtenBy: string;
      version: number;
    }
  | {
      type: "mailbox_message";
      visitId: string;
      from: string;
      to: string;
      payloadKind: string;
    }
  | {
      type: "permission_response";
      visitId: string;
      requestId: string;
      behavior: "allow" | "deny" | "ask";
    }
  | {
      type: "visit_status_changed";
      visitId: string;
      status: string;
    }
  | {
      // Fired after each pass of analyze_turn writes a partial slice of the
      // safe envelope to VisitState. The frontend uses this to refresh()
      // mid-turn so panels populate progressively as agents complete,
      // instead of all at once after the guardrail finishes.
      type: "turn_partial_committed";
      visitId: string;
      turnId: string;
      pass: "pass1" | "pass1_5" | "pass2" | "final";
    }
  | {
      type: "dream_started";
      userId: string;
      dreamId: string;
      scope: string;
      visitCount: number;
      at: number;
    }
  | {
      type: "dream_progress";
      userId: string;
      dreamId: string;
      phase: "orient" | "gather" | "consolidate" | "prune";
      pct: number;
      note?: string;
      at: number;
    }
  | {
      type: "dream_completed";
      userId: string;
      dreamId: string;
      filesUpdated: number;
      at: number;
    }
  | {
      type: "dream_failed";
      userId: string;
      dreamId: string;
      reason: string;
      at: number;
    }
  | {
      // Layer-1 runtime task lifecycle. Mirrors Claude Code's task_started /
      // task_progress / task_notification events but collapsed into a single
      // event type so the SSE consumer can subscribe with one filter.
      type: "runtime_task";
      visitId: string;
      taskId: string;
      parentTaskId?: string;
      status: "running" | "completed" | "failed" | "killed";
      kind: string;
      role?: string;
      label: string;
      recent?: string;
      error?: string;
      reason?: string;
    };

@Injectable()
export class CarenoteEventBus {
  private readonly subject = new Subject<CarenoteEvent>();

  emit(event: CarenoteEvent): void {
    this.subject.next(event);
  }

  /** Stream every event for a given visit. */
  streamForVisit(visitId: string): Observable<CarenoteEvent> {
    return this.subject
      .asObservable()
      .pipe(filter((e) => "visitId" in e && e.visitId === visitId));
  }

  /** Stream every event for a given user (currently only dream_completed). */
  streamForUser(userId: string): Observable<CarenoteEvent> {
    return this.subject
      .asObservable()
      .pipe(filter((e) => "userId" in e && e.userId === userId));
  }

  /** Stream all events. Used by the codex run-manager for on-demand triggers. */
  stream(): Observable<CarenoteEvent> {
    return this.subject.asObservable();
  }
}
