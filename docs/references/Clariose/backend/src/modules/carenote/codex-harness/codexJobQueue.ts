// CodexJobQueue — minimal in-memory queue with per-visit serial
// processing and a swappable interface (BullMQ in the future).

export type CodexJob =
  | { kind: "analyze_turn"; visit_id: string; turn_id: string; transcript: string; previous_item_id?: string | null }
  | { kind: "stage_summary"; visit_id: string }
  | { kind: "final_summary"; visit_id: string }
  | {
      // CLARIOSE_V01 §9 — on-demand single-role re-run triggered by the
      // SubscriptionRegistry (blackboard write or mailbox message). Carries
      // a hop counter so cycle-breaker can refuse hop > MAX_HOPS.
      kind: "single_role";
      visit_id: string;
      role: string;
      reason: string;
      hop: number;
    };

export interface CodexJobQueue {
  enqueue(job: CodexJob): Promise<void>;
  start(handler: (job: CodexJob) => Promise<void>): void;
  stop(): Promise<void>;
  pendingCount(): number;
  /** Jobs currently being processed by the handler (post-shift). */
  inFlightCount(): number;
}

export class InMemoryCodexJobQueue implements CodexJobQueue {
  private byVisit = new Map<string, CodexJob[]>();
  private busy = new Set<string>();
  private handler: ((job: CodexJob) => Promise<void>) | null = null;
  private stopped = false;

  async enqueue(job: CodexJob): Promise<void> {
    if (this.stopped) throw new Error("queue stopped");
    let arr = this.byVisit.get(job.visit_id);
    if (!arr) {
      arr = [];
      this.byVisit.set(job.visit_id, arr);
    }
    arr.push(job);
    this.tick(job.visit_id);
  }

  start(handler: (job: CodexJob) => Promise<void>): void {
    this.handler = handler;
    for (const v of this.byVisit.keys()) this.tick(v);
  }

  async stop(): Promise<void> {
    this.stopped = true;
  }

  pendingCount(): number {
    let n = 0;
    for (const arr of this.byVisit.values()) n += arr.length;
    return n;
  }

  inFlightCount(): number {
    return this.busy.size;
  }

  private tick(visit_id: string): void {
    if (!this.handler) return;
    if (this.busy.has(visit_id)) return;
    const arr = this.byVisit.get(visit_id);
    if (!arr || arr.length === 0) return;
    const job = arr.shift()!;
    this.busy.add(visit_id);
    void (async () => {
      try {
        await this.handler!(job);
      } catch {
        // swallow; the handler should record errors via agent_runs
      } finally {
        this.busy.delete(visit_id);
        this.tick(visit_id);
      }
    })();
  }
}
