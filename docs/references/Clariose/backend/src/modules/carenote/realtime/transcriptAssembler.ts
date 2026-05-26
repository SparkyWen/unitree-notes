// Pure transcript-event assembler.
//
// Responsibilities:
//  - Maintain per-(visit_id, item_id) state.
//  - Append delta to partial transcript.
//  - On completed, finalise the turn and reconstruct ordering using the
//    previous_item_id chain.
//  - Emit only completed turns (with high/medium/low ordering confidence).
//
// This module is pure: it does no I/O. The bus + persistence wrap it.

import { randomUUID } from "node:crypto";
import type {
  DoctorVisitTranscriptTurnCompleted,
  OrderingConfidence,
  RealtimeIngestEvent,
  RealtimeInputAudioBufferCommittedEvent,
  RealtimeTranscriptCompletedEvent,
  RealtimeTranscriptDeltaEvent,
  RealtimeTranscriptFailedEvent,
} from "./realtimeEventTypes";

type TurnState = {
  visit_id: string;
  item_id: string;
  previous_item_id: string | null | undefined;
  partial: string;
  transcript: string | null;
  status: "partial" | "completed" | "failed";
  created_at: string;
  completed_at: string | null;
  raw_events: unknown[];
};

export type AssemblerStats = {
  total_turns: number;
  completed_turns: number;
  failed_turns: number;
  ordering_confidence: OrderingConfidence;
};

export class TranscriptAssembler {
  // visit_id → item_id → state
  private byVisit = new Map<string, Map<string, TurnState>>();

  private opts: { transcriptionModel: string };

  constructor(opts?: { transcriptionModel?: string }) {
    this.opts = { transcriptionModel: opts?.transcriptionModel ?? "gpt-4o-transcribe" };
  }

  /**
   * Apply one ingest event. Returns the event(s) that should be published to
   * the bus right now (only after completed transcript events).
   */
  apply(
    visit_id: string,
    event: RealtimeIngestEvent,
  ): DoctorVisitTranscriptTurnCompleted[] {
    switch (event.type) {
      case "input_audio_buffer.committed":
        this.handleCommitted(visit_id, event);
        return [];
      case "conversation.item.input_audio_transcription.delta":
        this.handleDelta(visit_id, event);
        return [];
      case "conversation.item.input_audio_transcription.failed":
        this.handleFailed(visit_id, event);
        return [];
      case "conversation.item.input_audio_transcription.completed":
        return this.handleCompleted(visit_id, event);
      default: {
        const _exhaustive: never = event;
        return [];
      }
    }
  }

  /** Stats for tests + UI debug. */
  stats(visit_id: string): AssemblerStats {
    const m = this.byVisit.get(visit_id);
    if (!m) {
      return { total_turns: 0, completed_turns: 0, failed_turns: 0, ordering_confidence: "high" };
    }
    let completed = 0;
    let failed = 0;
    for (const t of m.values()) {
      if (t.status === "completed") completed += 1;
      if (t.status === "failed") failed += 1;
    }
    const ordering_confidence = this.computeOrderingConfidence(m);
    return {
      total_turns: m.size,
      completed_turns: completed,
      failed_turns: failed,
      ordering_confidence,
    };
  }

  /** Returns the chain order if the graph is a single chain; else null. */
  reconstructOrder(visit_id: string): string[] | null {
    const m = this.byVisit.get(visit_id);
    if (!m) return [];
    return this.walkChain(m);
  }

  private handleCommitted(
    visit_id: string,
    e: RealtimeInputAudioBufferCommittedEvent,
  ): void {
    const map = this.ensureVisit(visit_id);
    let st = map.get(e.item_id);
    if (!st) {
      st = this.makeState(visit_id, e.item_id, e.previous_item_id ?? null);
      map.set(e.item_id, st);
    } else if (st.previous_item_id == null && e.previous_item_id) {
      // Late-arriving link information.
      st.previous_item_id = e.previous_item_id;
    }
    st.raw_events.push(e);
  }

  private handleDelta(visit_id: string, e: RealtimeTranscriptDeltaEvent): void {
    const map = this.ensureVisit(visit_id);
    let st = map.get(e.item_id);
    if (!st) {
      st = this.makeState(visit_id, e.item_id, null);
      map.set(e.item_id, st);
    }
    st.partial += e.delta;
    st.raw_events.push(e);
  }

  private handleFailed(visit_id: string, e: RealtimeTranscriptFailedEvent): void {
    const map = this.ensureVisit(visit_id);
    let st = map.get(e.item_id);
    if (!st) {
      st = this.makeState(visit_id, e.item_id, null);
      map.set(e.item_id, st);
    }
    st.status = "failed";
    st.raw_events.push(e);
  }

  private handleCompleted(
    visit_id: string,
    e: RealtimeTranscriptCompletedEvent,
  ): DoctorVisitTranscriptTurnCompleted[] {
    const map = this.ensureVisit(visit_id);
    let st = map.get(e.item_id);
    if (!st) {
      st = this.makeState(visit_id, e.item_id, null);
      map.set(e.item_id, st);
    }
    st.transcript = e.transcript;
    st.status = "completed";
    st.completed_at = new Date().toISOString();
    st.raw_events.push(e);

    if (!st.transcript || st.transcript.length === 0) {
      // Do not emit empty turns.
      return [];
    }

    const orderingConfidence = this.computeOrderingConfidence(map);
    const out: DoctorVisitTranscriptTurnCompleted = {
      event_type: "doctor_visit.transcript_turn.completed",
      event_id: randomUUID(),
      visit_id,
      turn: {
        item_id: st.item_id,
        previous_item_id: st.previous_item_id ?? null,
        transcript: st.transcript,
        ordering_confidence: orderingConfidence,
      },
      source: {
        provider: "openai",
        api: "realtime",
        realtime_model: "gpt-realtime-1.5",
        transcription_model: this.opts.transcriptionModel,
      },
      created_at: st.completed_at ?? new Date().toISOString(),
    };
    return [out];
  }

  private ensureVisit(visit_id: string): Map<string, TurnState> {
    let m = this.byVisit.get(visit_id);
    if (!m) {
      m = new Map();
      this.byVisit.set(visit_id, m);
    }
    return m;
  }

  private makeState(
    visit_id: string,
    item_id: string,
    previous_item_id: string | null | undefined,
  ): TurnState {
    return {
      visit_id,
      item_id,
      previous_item_id,
      partial: "",
      transcript: null,
      status: "partial",
      created_at: new Date().toISOString(),
      completed_at: null,
      raw_events: [],
    };
  }

  private computeOrderingConfidence(
    states: Map<string, TurnState>,
  ): OrderingConfidence {
    const completed = [...states.values()].filter((s) => s.status === "completed");
    if (completed.length <= 1) return "high";

    const allHaveLink = completed.every(
      (s) => s.previous_item_id !== undefined && s.previous_item_id !== null,
    );
    const anyLink = completed.some(
      (s) => s.previous_item_id !== undefined && s.previous_item_id !== null,
    );

    if (!anyLink) return "low";

    // Build adjacency.
    const next = new Map<string | null, string>();
    for (const s of completed) {
      const key = s.previous_item_id ?? null;
      next.set(key, s.item_id);
    }

    // Find a head: completed turn whose previous_item_id is null OR points
    // to no completed item.
    const completedIds = new Set(completed.map((s) => s.item_id));
    const heads = completed.filter(
      (s) => s.previous_item_id == null || !completedIds.has(s.previous_item_id),
    );

    if (heads.length !== 1) return allHaveLink ? "medium" : "low";

    // Walk and see if it covers everything.
    const visited = new Set<string>();
    let cur: string | undefined = heads[0]!.item_id;
    while (cur && !visited.has(cur)) {
      visited.add(cur);
      cur = next.get(cur);
    }
    if (visited.size === completed.length) return "high";
    return allHaveLink ? "medium" : "low";
  }

  private walkChain(states: Map<string, TurnState>): string[] {
    const completed = [...states.values()].filter((s) => s.status === "completed");
    if (completed.length === 0) return [];

    const completedIds = new Set(completed.map((s) => s.item_id));
    const next = new Map<string, string>();
    for (const s of completed) {
      if (s.previous_item_id != null && completedIds.has(s.previous_item_id)) {
        next.set(s.previous_item_id, s.item_id);
      }
    }
    const heads = completed.filter(
      (s) => s.previous_item_id == null || !completedIds.has(s.previous_item_id),
    );

    if (heads.length === 1) {
      const order: string[] = [];
      const visited = new Set<string>();
      let cur: string | undefined = heads[0]!.item_id;
      while (cur && !visited.has(cur)) {
        order.push(cur);
        visited.add(cur);
        cur = next.get(cur);
      }
      // Append fragments (turns not in the walk) by created_at.
      const tail = completed
        .filter((s) => !visited.has(s.item_id))
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
        .map((s) => s.item_id);
      return [...order, ...tail];
    }
    // Fallback: created_at order.
    return completed
      .slice()
      .sort((a, b) => a.created_at.localeCompare(b.created_at))
      .map((s) => s.item_id);
  }
}
