// M7 API tests. Drives CareNoteService directly (no HTTP layer) so the
// tests stay free of Nest test-bed scaffolding while still covering the
// full request → harness → reducer → state flow.

import { resolve } from "node:path";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ConfigService } from "@nestjs/config";
import {
  BadRequestException,
  ConflictException,
  NotFoundException,
} from "@nestjs/common";

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
  const tmp = await mkdtemp(join(tmpdir(), "carenote-api-"));
  // forceStub so tests don't shell out to codex-cli.
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
      await rm(tmp, { recursive: true, force: true });
    },
  };
}

describe("CareNote M7 API", () => {
  test("POST /api/visits requires consent_recorded=true", async () => {
    const { svc, cleanup } = await makeService();
    try {
      await expect(
        svc.createVisit({ ownerUserId: "u1", consent_recorded: false }),
      ).rejects.toBeInstanceOf(BadRequestException);
      const v = await svc.createVisit({ ownerUserId: "u1", consent_recorded: true });
      expect(v.status).toBe("active");
      // CLARIOSE_V01: visit_id is now the ConsultSession cuid (was `v-<uuid>`).
      expect(v.visit_id).toBeTruthy();
    } finally {
      await cleanup();
    }
  });

  test("POST /api/realtime/session rejects deleted/ended visits", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
      });
      await svc.endVisit(visit_id);
      await expect(
        svc.mintRealtimeSession(visit_id, "doctor_visit"),
      ).rejects.toBeInstanceOf(ConflictException);
    } finally {
      await cleanup();
    }
  });

  test("realtime-events: delta does not enqueue codex job, completed does", async () => {
    const { svc, harness, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
      });

      const r1 = await svc.ingestRealtimeEvent(visit_id, {
        type: "input_audio_buffer.committed",
        item_id: "i1",
        previous_item_id: null,
      });
      expect(r1.accepted).toBe(true);
      expect(r1.emitted_transcript_turn).toBe(false);
      expect(r1.job_id).toBeNull();

      const r2 = await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.delta",
        item_id: "i1",
        delta: "你好",
      });
      expect(r2.emitted_transcript_turn).toBe(false);
      expect(harness.queue.pendingCount() + harness.queue.inFlightCount()).toBe(0);

      const r3 = await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "i1",
        transcript: "这个药每天饭后吃一次，连续吃三天。",
      });
      expect(r3.emitted_transcript_turn).toBe(true);
      expect(r3.job_id).toMatch(/^analyze_turn:/);

      // Drain.
      await svc.waitForQueueIdle();
      const v = await svc.getVisit(visit_id);
      // Stub harness produces drafts in pending state.
      expect(v.state.draft_reminders.length).toBeGreaterThan(0);
      expect(v.state.draft_reminders[0]!.requires_user_confirmation).toBe(true);
      expect(v.state.draft_reminders[0]!.confirmation_status).toBe("pending");
    } finally {
      await cleanup();
    }
  });

  test("confirm draft task moves it from pending → confirmed and out of drafts", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
      });
      await svc.ingestRealtimeEvent(visit_id, {
        type: "input_audio_buffer.committed",
        item_id: "i1",
        previous_item_id: null,
      });
      await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "i1",
        transcript: "这个药每天饭后吃一次，连续吃三天。",
      });
      await svc.waitForQueueIdle();

      const before = await svc.getVisit(visit_id);
      const task = before.state.draft_reminders[0]!;
      const confirmed = await svc.confirmDraftTask(visit_id, task.task_id);
      expect(confirmed.confirmation_status).toBe("confirmed");

      const after = await svc.getVisit(visit_id);
      expect(after.state.draft_reminders.find((r) => r.task_id === task.task_id)).toBeUndefined();
      expect(after.confirmed_tasks.find((t) => t.task_id === task.task_id)).toBeDefined();
    } finally {
      await cleanup();
    }
  });

  test("reject draft task removes it without creating a confirmed entry", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
      });
      await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "i1",
        transcript: "这个药每天饭后吃一次，连续吃三天。",
      });
      await svc.waitForQueueIdle();
      const before = await svc.getVisit(visit_id);
      const task = before.state.draft_reminders[0]!;
      await svc.rejectDraftTask(visit_id, task.task_id);
      const after = await svc.getVisit(visit_id);
      expect(after.state.draft_reminders.find((r) => r.task_id === task.task_id)).toBeUndefined();
      expect(after.confirmed_tasks.find((t) => t.task_id === task.task_id)).toBeUndefined();
      await expect(
        svc.confirmDraftTask(visit_id, task.task_id),
      ).rejects.toBeInstanceOf(NotFoundException);
    } finally {
      await cleanup();
    }
  });

  test("memory candidate confirm creates a confirmed memory; reject does not", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
      });
      await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "i1",
        transcript: "我对青霉素过敏。",
      });
      await svc.waitForQueueIdle();
      const before = await svc.getVisit(visit_id);
      const cand = before.state.memory_candidates[0]!;
      expect(cand.confirmation_status).toBe("pending");
      const confirmed = await svc.confirmMemoryCandidate(visit_id, cand.memory_candidate_id);
      expect(confirmed.memory_id).toMatch(/^mem-/);
      const after = await svc.getVisit(visit_id);
      expect(after.confirmed_memories).toHaveLength(1);
      expect(after.state.memory_candidates.find((c) => c.memory_candidate_id === cand.memory_candidate_id)).toBeUndefined();

      await expect(
        svc.confirmMemoryCandidate(visit_id, cand.memory_candidate_id),
      ).rejects.toBeInstanceOf(NotFoundException);
    } finally {
      await cleanup();
    }
  });

  test("DELETE visit removes local visit state entirely", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
      });
      await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "i1",
        transcript: "这个药每天饭后吃一次，连续吃三天。",
      });
      await svc.waitForQueueIdle();
      await svc.deleteVisit(visit_id);
      await expect(svc.getVisit(visit_id)).rejects.toBeInstanceOf(NotFoundException);
    } finally {
      await cleanup();
    }
  });

  test("ingestRealtimeEvent on a non-active visit is rejected", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
      });
      await svc.endVisit(visit_id);
      await expect(
        svc.ingestRealtimeEvent(visit_id, {
          type: "conversation.item.input_audio_transcription.completed",
          item_id: "i1",
          transcript: "x",
        }),
      ).rejects.toBeInstanceOf(ConflictException);
    } finally {
      await cleanup();
    }
  });

  test("buildSessionConfig honours create_response=false and interrupt_response=false", async () => {
    const { svc, cleanup } = await makeService();
    try {
      const cfg = svc.buildSessionConfig("zh");
      expect(cfg.audio.input.turn_detection.create_response).toBe(false);
      expect(cfg.audio.input.turn_detection.interrupt_response).toBe(false);
      expect(cfg.output_modalities).toEqual(["text"]);
      expect(cfg.audio.input.transcription.model).toBe("gpt-4o-transcribe");
    } finally {
      await cleanup();
    }
  });
});
