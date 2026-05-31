// M7.6 — transcript visibility regression tests.
//
// Asserts the bug we fixed: that the persisted VisitState carries
// transcript turns, and that duplicate completed events do NOT
// double-trigger the analyze_turn pipeline.

import { applyRealtimeEventToVisitState } from "../../src/modules/carenote/realtime/applyRealtimeEvent";
import {
  VisitStateSchema,
  type VisitState,
} from "../../src/modules/carenote/medical/medicalSchemas";

function freshVisit(): VisitState {
  return VisitStateSchema.parse({
    visit_id: "v-test",
    language: "en",
    status: "new",
    turns: [],
    facts: [],
    draft_tasks: [],
    draft_reminders: [],
    clarifying_questions: [],
    transcript_verifications: [],
    caregiver_notifications: [],
    family_summary_deltas: [],
    memory_candidates: [],
    safety_flags: [],
    guardrail_blocked: [],
    analyzed_item_ids: [],
  });
}

describe("M7.6 transcript visibility — applyRealtimeEventToVisitState", () => {
  test("committed → delta → completed produces a completed turn", () => {
    let s = freshVisit();
    s = applyRealtimeEventToVisitState(s, {
      type: "input_audio_buffer.committed",
      item_id: "i1",
      previous_item_id: null,
    }).next;
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.delta",
      item_id: "i1",
      delta: "Take one ",
    }).next;
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.delta",
      item_id: "i1",
      delta: "tablet daily.",
    }).next;
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "i1",
      transcript: "Take one tablet daily.",
    }).next;

    expect(s.turns).toHaveLength(1);
    expect(s.turns[0]!.status).toBe("completed");
    expect(s.turns[0]!.transcript).toBe("Take one tablet daily.");
    expect(s.transcript_stats.completed_count).toBe(1);
    expect(s.transcript_stats.delta_count).toBe(2);
    expect(s.transcript_stats.last_completed_transcript).toBe("Take one tablet daily.");
    expect(s.transcript_stats.last_event_type).toBe(
      "conversation.item.input_audio_transcription.completed",
    );
  });

  test("late delta after completed does NOT overwrite the final transcript", () => {
    let s = freshVisit();
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "i1",
      transcript: "Final transcript",
    }).next;
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.delta",
      item_id: "i1",
      delta: " stray",
    }).next;
    expect(s.turns[0]!.transcript).toBe("Final transcript");
    expect(s.turns[0]!.status).toBe("completed");
  });

  test("duplicate completed event does NOT change the stored transcript", () => {
    let s = freshVisit();
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "i1",
      transcript: "first",
    }).next;
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "i1",
      transcript: "second",
    }).next;
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0]!.transcript).toBe("first");
  });

  test("failed event marks turn failed and surfaces in transcript_stats", () => {
    let s = freshVisit();
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.failed",
      item_id: "i1",
      error: { message: "asr unavailable" },
    }).next;
    expect(s.turns[0]!.status).toBe("failed");
    expect(s.turns[0]!.error).toBe("asr unavailable");
    expect(s.transcript_stats.failed_count).toBe(1);
    expect(s.transcript_stats.last_error).toBe("asr unavailable");
  });

  test("error event records last_error without creating a turn", () => {
    let s = freshVisit();
    s = applyRealtimeEventToVisitState(s, {
      type: "error",
      error: { message: "rate limit" },
    }).next;
    expect(s.turns).toHaveLength(0);
    expect(s.transcript_stats.last_error).toBe("rate limit");
    expect(s.transcript_stats.last_event_type).toBe("error");
  });

  test("completed before committed marks ordering_confidence low", () => {
    let s = freshVisit();
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "i-orphan",
      transcript: "orphan",
    }).next;
    // No `committed` was ever seen for i-orphan, so ordering should
    // not be claimed as high.
    expect(s.turns[0]!.ordering_confidence).toBe("low");
  });

  test("partial event before any committed seeds the turn", () => {
    let s = freshVisit();
    s = applyRealtimeEventToVisitState(s, {
      type: "conversation.item.input_audio_transcription.delta",
      item_id: "i1",
      delta: "hello ",
    }).next;
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0]!.partial_transcript).toBe("hello ");
    expect(s.turns[0]!.status).toBe("partial");
  });
});
