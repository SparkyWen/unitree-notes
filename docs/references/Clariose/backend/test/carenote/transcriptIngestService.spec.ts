// M7.6 — service-level transcript ingest tests.
//
// Uses the same in-process harness as carenoteApi.spec.ts to drive the
// real `ingestRealtimeEvent` path end-to-end (without HTTP). Verifies
// that GET /api/visits/:id surfaces turns and that duplicate completed
// events do not double-trigger Codex.

import { resolve } from "node:path";

import { ConfigService } from "@nestjs/config";

import { CareNoteService } from "../../src/modules/carenote/api/carenote.service";
import { assembleHarness } from "../../src/modules/carenote/api/codexHarnessApi";
import type { CareNoteHarness } from "../../src/modules/carenote/api/codexHarnessApi";
import { makeFakePrisma } from "./fakePrisma";

const repoRoot = resolve(__dirname, "../../..");

async function makeService(): Promise<{
  svc: CareNoteService;
  harness: CareNoteHarness;
  cleanup: () => Promise<void>;
}> {
  const harness = await assembleHarness({ repoRoot, forceStub: true });
  const cfg = new ConfigService();
  const { CarenoteEventBus } = await import("../../src/modules/carenote/swarm/eventBus");
  const svc = new CareNoteService(cfg, new CarenoteEventBus(), makeFakePrisma());
  svc.setHarnessForTest(harness);
  return {
    svc,
    harness,
    cleanup: async () => {
      await harness.queue.stop();
    },
  };
}

describe("CareNote M7.6 — transcript visibility through the service", () => {
  test("committed + delta + completed are persisted into VisitState.turns", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
        language: "en",
      });

      await svc.ingestRealtimeEvent(visit_id, {
        type: "input_audio_buffer.committed",
        item_id: "i1",
        previous_item_id: null,
      });
      await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.delta",
        item_id: "i1",
        delta: "Take ",
      });
      const completed = await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "i1",
        transcript: "Take one tablet daily.",
      });
      expect(completed.emitted_transcript_turn).toBe(true);
      expect(completed.duplicate).toBe(false);

      const got = await svc.getVisit(visit_id);
      expect(got.state.turns).toHaveLength(1);
      expect(got.state.turns[0]!.transcript).toBe("Take one tablet daily.");
      expect(got.state.turns[0]!.status).toBe("completed");
      expect(got.state.transcript_stats.completed_count).toBe(1);
      expect(got.state.transcript_stats.last_completed_transcript).toBe(
        "Take one tablet daily.",
      );
      expect(got.state.transcript_stats.last_event_type).toBe(
        "conversation.item.input_audio_transcription.completed",
      );
      expect(got.state.analyzed_item_ids).toContain("i1");
    } finally {
      await cleanup();
    }
  });

  test("duplicate completed event does NOT enqueue a second analyze_turn", async () => {
    const { svc, harness, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
        language: "en",
      });

      await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "i1",
        transcript: "Take one tablet daily.",
      });
      // Drain so the first run completes.
      await svc.waitForQueueIdle(2000);
      const runsAfterFirst = harness.runs.length;
      expect(runsAfterFirst).toBeGreaterThan(0);

      const dup = await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "i1",
        transcript: "Take one tablet daily.",
      });
      expect(dup.duplicate).toBe(true);
      expect(dup.emitted_transcript_turn).toBe(false);
      await svc.waitForQueueIdle(2000);

      // No new agent runs should have happened.
      expect(harness.runs.length).toBe(runsAfterFirst);
    } finally {
      await cleanup();
    }
  });

  test("transcription failed event is visible in transcript_stats", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
        language: "en",
      });

      await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.failed",
        item_id: "i1",
        error: { message: "asr unavailable" },
      });

      const got = await svc.getVisit(visit_id);
      expect(got.state.transcript_stats.failed_count).toBe(1);
      expect(got.state.transcript_stats.last_error).toBe("asr unavailable");
      expect(got.state.turns[0]!.status).toBe("failed");
    } finally {
      await cleanup();
    }
  });

  test("realtime error event records last_error without crashing", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
        language: "en",
      });
      const r = await svc.ingestRealtimeEvent(visit_id, {
        type: "error",
        error: { message: "rate_limited" },
      });
      expect(r.accepted).toBe(true);
      const got = await svc.getVisit(visit_id);
      expect(got.state.transcript_stats.last_error).toBe("rate_limited");
    } finally {
      await cleanup();
    }
  });
});
