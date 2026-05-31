// applyRealtimeEventToVisitState — pure reducer that turns a raw OpenAI
// Realtime event into a VisitState delta.
//
// Why this exists: TranscriptAssembler keeps its own per-instance map
// keyed by (visit_id, item_id), but VisitState is the only thing the
// HTTP API exposes. Before M7.6 the assembler state was hidden — the
// browser never saw transcript turns through `GET /api/visits/:id`,
// only through the local `useRealtimeVisit` ref. This reducer mirrors
// every event into VisitState so the transcript is visible
// independently of any Codex agent run.

import type { VisitState, TranscriptTurn, TranscriptStats } from "../medical/medicalSchemas";

const TRANSCRIPTION_MODEL = "gpt-4o-transcribe";

export type ApplyResult = {
  next: VisitState;
  /** True if this event mutated turn-level state (committed/delta/completed/failed). */
  mutatedTurn: boolean;
};

/**
 * Apply a single OpenAI Realtime event to VisitState. Returns a new
 * VisitState; never mutates the input.
 *
 * Tolerated event types:
 *   - input_audio_buffer.committed
 *   - input_audio_buffer.speech_started
 *   - input_audio_buffer.speech_stopped
 *   - conversation.item.input_audio_transcription.delta
 *   - conversation.item.input_audio_transcription.completed
 *   - conversation.item.input_audio_transcription.failed
 *   - error  (and any other event — recorded in transcript_stats only)
 */
export function applyRealtimeEventToVisitState(
  prev: VisitState,
  raw: unknown,
): ApplyResult {
  const evt = raw as { type?: unknown };
  const type = typeof evt?.type === "string" ? (evt.type as string) : null;
  const stats: TranscriptStats = {
    ...prev.transcript_stats,
    last_event_type: type ?? prev.transcript_stats.last_event_type,
  };

  if (!type) {
    return { next: { ...prev, transcript_stats: stats }, mutatedTurn: false };
  }

  if (type === "input_audio_buffer.committed") {
    const e = raw as { item_id?: string; previous_item_id?: string | null };
    if (!e.item_id) return { next: { ...prev, transcript_stats: stats }, mutatedTurn: false };
    const turns = upsertTurn(prev.turns, prev.visit_id, e.item_id, (t) => ({
      ...t,
      previous_item_id: e.previous_item_id ?? t.previous_item_id ?? null,
      status: t.status === "completed" ? "completed" : "committed",
      // ordering_confidence stays "high" by default; the assembler
      // reconstructs the chain on the read side.
      ordering_confidence: t.ordering_confidence ?? "high",
    }));
    stats.committed_count = (stats.committed_count ?? 0) + 1;
    // CLARIOSE_V02: associate this committed turn with the currently-open
    // round so the visit page can group transcripts/agent outputs per
    // pause-cycle. Idempotent — same item_id committed twice doesn't
    // re-add it to the round bucket.
    const rounds = upsertTurnInRound(prev.rounds, prev.current_round_index, e.item_id);
    return { next: { ...prev, turns, rounds, transcript_stats: stats }, mutatedTurn: true };
  }

  if (type === "conversation.item.input_audio_transcription.delta") {
    const e = raw as { item_id?: string; delta?: string };
    if (!e.item_id) return { next: { ...prev, transcript_stats: stats }, mutatedTurn: false };
    const delta = e.delta ?? "";
    const turns = upsertTurn(prev.turns, prev.visit_id, e.item_id, (t) => {
      // If completed already arrived, do NOT overwrite it. Late deltas
      // are silently dropped so the final transcript stands.
      if (t.status === "completed") return t;
      return {
        ...t,
        partial_transcript: (t.partial_transcript ?? "") + delta,
        status: "partial",
      };
    });
    stats.delta_count = (stats.delta_count ?? 0) + 1;
    stats.partial_count = (stats.partial_count ?? 0) + (delta ? 1 : 0);
    const updatedTurn = turns.find((t) => t.item_id === e.item_id);
    if (updatedTurn?.partial_transcript) {
      stats.last_partial_transcript = updatedTurn.partial_transcript;
    }
    return { next: { ...prev, turns, transcript_stats: stats }, mutatedTurn: true };
  }

  if (type === "conversation.item.input_audio_transcription.completed") {
    const e = raw as { item_id?: string; transcript?: string };
    if (!e.item_id) return { next: { ...prev, transcript_stats: stats }, mutatedTurn: false };
    const transcript = (e.transcript ?? "").trim();
    // If we never saw a `committed` for this item before, the chain
    // link is unknown — flag ordering_confidence as "low" so the UI
    // can warn.
    const wasUnseen = prev.turns.findIndex((t) => t.item_id === e.item_id) === -1;
    const turns = upsertTurn(prev.turns, prev.visit_id, e.item_id, (t) => {
      // Idempotency: a duplicate completed event must not overwrite the
      // first transcript with a different one.
      if (t.status === "completed" && t.transcript) return t;
      return {
        ...t,
        ordering_confidence: wasUnseen ? "low" : t.ordering_confidence,
        transcript,
        partial_transcript: null,
        status: "completed",
        completed_at: new Date().toISOString(),
      };
    });
    stats.completed_count = (stats.completed_count ?? 0) + 1;
    stats.last_completed_transcript = transcript || stats.last_completed_transcript;
    stats.last_completed_transcript_at = new Date().toISOString();
    return { next: { ...prev, turns, transcript_stats: stats }, mutatedTurn: true };
  }

  if (type === "conversation.item.input_audio_transcription.failed") {
    const e = raw as { item_id?: string; error?: { message?: string; type?: string } };
    if (!e.item_id) return { next: { ...prev, transcript_stats: stats }, mutatedTurn: false };
    const errMsg = e.error?.message ?? e.error?.type ?? "transcription failed";
    const turns = upsertTurn(prev.turns, prev.visit_id, e.item_id, (t) => ({
      ...t,
      status: "failed",
      error: errMsg,
    }));
    stats.failed_count = (stats.failed_count ?? 0) + 1;
    stats.last_error = errMsg;
    stats.last_failed_at = new Date().toISOString();
    return { next: { ...prev, turns, transcript_stats: stats }, mutatedTurn: true };
  }

  if (type === "error") {
    const e = raw as { error?: { message?: string; code?: string; type?: string } };
    const msg =
      e.error?.message ?? e.error?.code ?? e.error?.type ?? "realtime error";
    stats.last_error = msg;
    return { next: { ...prev, transcript_stats: stats }, mutatedTurn: false };
  }

  // Tolerated but uninteresting (speech_started, speech_stopped, etc.)
  return { next: { ...prev, transcript_stats: stats }, mutatedTurn: false };
}

/**
 * CLARIOSE_V02 — push an item_id into the currently open round's bucket if
 * not already present. If `rounds` is empty (legacy blob predates the
 * round model), seed round 0 implicitly so per-round grouping still works.
 */
function upsertTurnInRound(
  rounds: VisitState["rounds"],
  currentIdx: number,
  item_id: string,
): VisitState["rounds"] {
  const list = rounds && rounds.length > 0
    ? rounds
    : [
        {
          index: 0,
          started_at: new Date().toISOString(),
          ended_at: null,
          turn_item_ids: [],
          recap_headline: null,
          recap_generated_at: null,
        },
      ];
  const idx = list.findIndex((r) => r.index === currentIdx);
  if (idx === -1) {
    return [
      ...list,
      {
        index: currentIdx,
        started_at: new Date().toISOString(),
        ended_at: null,
        turn_item_ids: [item_id],
        recap_headline: null,
        recap_generated_at: null,
      },
    ];
  }
  const round = list[idx]!;
  if (round.turn_item_ids.includes(item_id)) return list;
  const next = { ...round, turn_item_ids: [...round.turn_item_ids, item_id] };
  return [...list.slice(0, idx), next, ...list.slice(idx + 1)];
}

function upsertTurn(
  prev: VisitState["turns"],
  visit_id: string,
  item_id: string,
  patch: (existing: TranscriptTurn) => TranscriptTurn,
): VisitState["turns"] {
  const idx = prev.findIndex((t) => t.item_id === item_id);
  if (idx === -1) {
    const seed: TranscriptTurn = {
      visit_id,
      item_id,
      previous_item_id: null,
      status: "committed",
      partial_transcript: null,
      transcript: null,
      speaker_label: null,
      ordering_confidence: "high",
      source_model: "gpt-realtime-1.5",
      transcription_model: TRANSCRIPTION_MODEL,
      error: null,
      created_at: new Date().toISOString(),
      completed_at: null,
    };
    return [...prev, patch(seed)];
  }
  const next = patch(prev[idx]!);
  return [...prev.slice(0, idx), next, ...prev.slice(idx + 1)];
}
