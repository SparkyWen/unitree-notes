// replay-transcript CLI — full Realtime replay smoke.
//
// Walks through the canonical OpenAI Realtime event sequence
// (committed → delta → completed) for one synthetic turn, mirroring
// what the browser sends through `/api/visits/:id/realtime-events`.
//
// Verifies the M7.6 transcript visibility fix: VisitState.turns must
// be populated AND the multi-agent pipeline must run exactly once.
//
// Usage:
//   npm run carenote:smoke:replay-transcript -- --inline "Please take this medicine once a day after meals for three days."
//   npm run carenote:smoke:replay-transcript -- --stub --inline "<transcript>"

import { assembleHarness } from "./codexHarnessApi";
import { applyRealtimeEventToVisitState } from "../realtime/applyRealtimeEvent";

async function main(): Promise<void> {
  const rawArgs = process.argv.slice(2);
  let forceStub = false;
  let inline: string | null = null;
  for (let i = 0; i < rawArgs.length; i++) {
    const a = rawArgs[i]!;
    if (a === "--stub") forceStub = true;
    else if (a === "--inline") inline = rawArgs[++i] ?? null;
  }
  if (!inline) {
    console.error('usage: replay-transcript [--stub] --inline "<transcript>"');
    process.exit(2);
    return;
  }

  const harness = await assembleHarness({ forceStub });
  const visit_id = `visit-${Date.now()}`;
  const item_id = `itm-${Date.now()}`;
  harness.visits.ensure(visit_id, "en");

  const events: unknown[] = [
    { type: "input_audio_buffer.speech_started", item_id },
    { type: "input_audio_buffer.committed", item_id, previous_item_id: null },
  ];
  // Split the inline transcript into ~5 deltas to exercise partial path.
  const chunks = chunkString(inline, Math.max(1, Math.ceil(inline.length / 5)));
  for (const c of chunks) {
    events.push({
      type: "conversation.item.input_audio_transcription.delta",
      item_id,
      delta: c,
    });
  }
  events.push({
    type: "conversation.item.input_audio_transcription.completed",
    item_id,
    transcript: inline,
  });

  // Mirror what the controller does: apply each event into VisitState
  // and (for the canonical four) feed the assembler. On completed,
  // publish to the bus to trigger Codex analysis.
  for (const evt of events) {
    const prev = await harness.visits.get(visit_id);
    const { next } = applyRealtimeEventToVisitState(prev, evt);
    await harness.visits.set(visit_id, next);
    const t = (evt as { type?: string }).type;
    if (
      t === "input_audio_buffer.committed" ||
      t === "conversation.item.input_audio_transcription.delta" ||
      t === "conversation.item.input_audio_transcription.completed" ||
      t === "conversation.item.input_audio_transcription.failed"
    ) {
      const emitted = harness.assembler.apply(visit_id, evt as never);
      // Idempotency: track analyzed_item_ids BEFORE publishing — the
      // bus → queue handoff is sync and the analyzer reads VisitState
      // at job-start time. Writing first ensures the reducer's `...prev`
      // spread carries analyzed_item_ids forward.
      const before = await harness.visits.get(visit_id);
      const fresh: typeof emitted = [];
      const seen = new Set(before.analyzed_item_ids);
      for (const e of emitted) {
        if (seen.has(e.turn.item_id)) continue;
        seen.add(e.turn.item_id);
        fresh.push(e);
      }
      await harness.visits.set(visit_id, { ...before, analyzed_item_ids: [...seen] });
      for (const e of fresh) harness.bus.publish(e);
    }
  }

  // Drain the queue.
  await new Promise((r) => setTimeout(r, 100));
  const start = Date.now();
  while (harness.queue.pendingCount() > 0 || harness.queue.inFlightCount() > 0) {
    if (Date.now() - start > 60_000) break;
    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, 100));
  }
  await new Promise((r) => setTimeout(r, 100));

  const final = await harness.visits.get(visit_id);

  const summary = {
    runtime: harness.bootstrap.runtime.runtime.name,
    visit_id,
    turn_count: final.turns.length,
    completed_turns: final.turns.filter((t) => t.status === "completed").length,
    transcript_stats: final.transcript_stats,
    sample_turn: final.turns[0],
    transcript_verifications: final.transcript_verifications.map((v) => ({
      verification_id: v.verification_id,
      quality: v.quality,
      ambiguity_count: v.ambiguities.length,
      ambiguity_types: v.ambiguities.map((a) => a.ambiguity_type),
    })),
    clarifying_questions: final.clarifying_questions.map((q) => ({
      priority: q.priority,
      question: q.question,
    })),
    draft_reminders: final.draft_reminders.map((r) => ({
      title: r.title,
      medication_name: r.medication_name,
      dose: r.dose,
      status: r.status,
      blocking_missing_fields: r.blocking_missing_fields,
      requires_user_confirmation: r.requires_user_confirmation,
      confirmation_status: r.confirmation_status,
    })),
    caregiver_notifications: final.caregiver_notifications.map((n) => ({
      title: n.title,
      requires_user_confirmation: n.requires_user_confirmation,
      confirmation_status: n.confirmation_status,
      needs_confirmation: n.needs_confirmation,
    })),
    analyzed_item_ids: final.analyzed_item_ids,
  };

  console.log(JSON.stringify(summary, null, 2));

  // Acceptance hints — non-fatal warnings.
  if (final.turns.length === 0) {
    console.error("[replay] WARN: VisitState.turns is empty");
  }
  if (!final.transcript_stats.last_completed_transcript) {
    console.error("[replay] WARN: transcript_stats.last_completed_transcript is null");
  }
}

function chunkString(s: string, size: number): string[] {
  const out: string[] = [];
  for (let i = 0; i < s.length; i += size) out.push(s.slice(i, i + size));
  return out;
}

main().catch((err) => {
  console.error("[carenote replay-transcript] fatal:", err);
  process.exit(1);
});
