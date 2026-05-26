import { resolve } from "node:path";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { bootstrapCareNoteTeam } from "../../src/modules/carenote/codex-harness/codexTeamBootstrap";
import { CodexRunManager } from "../../src/modules/carenote/codex-harness/codexRunManager";
import { InMemoryCodexJobQueue } from "../../src/modules/carenote/codex-harness/codexJobQueue";
import { JsonFileCodexThreadStore } from "../../src/modules/carenote/codex-harness/codexThreadStore";
import { InMemoryMemoryRetrievalService } from "../../src/modules/carenote/medical/memoryRetrieval";
import { InMemoryVisitStateStore } from "../../src/modules/carenote/medical/visitStateStore";

const repoRoot = resolve(__dirname, "../../..");

async function buildHarness(repo: string, statePath: string) {
  const boot = await bootstrapCareNoteTeam({
    repoRoot: repo,
    threadStatePath: statePath,
    runtime: { force: "stub" },
    store: new JsonFileCodexThreadStore(statePath),
  });
  const visits = new InMemoryVisitStateStore();
  const memory = new InMemoryMemoryRetrievalService();
  const queue = new InMemoryCodexJobQueue();
  const manager = new CodexRunManager({
    team: boot.team,
    queue,
    visitStateGet: (id) => visits.get(id),
    visitStateSet: (id, n) => visits.set(id, n),
    memory,
  });
  return { boot, visits, queue, manager };
}

describe("End-to-end mock turn (stub runtime)", () => {
  test("missing-dose transcript produces medication reminder pending and missing-fields safety flag", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "carenote-e2e-"));
    try {
      const { manager, visits } = await buildHarness(repoRoot, join(tmp, "state.json"));
      const result = await manager.analyzeTurn({
        kind: "analyze_turn",
        visit_id: "v1",
        turn_id: "itm-1",
        transcript: "这个药每天饭后吃一次，连续吃三天。",
        previous_item_id: null,
      });
      const v = await visits.get("v1");

      // Reminder created and pending.
      expect(result.envelope.draft_reminders.length).toBeGreaterThan(0);
      const r = result.envelope.draft_reminders[0]!;
      expect(r.requires_user_confirmation).toBe(true);
      expect(r.confirmation_status).toBe("pending");

      // Reduced state contains the same reminder, also pending.
      expect(v.draft_reminders.length).toBeGreaterThan(0);
      expect(v.draft_reminders[0]!.requires_user_confirmation).toBe(true);
      expect(v.draft_reminders[0]!.status).toBe("needs_user_confirmation");

      // A safety flag for missing dose was emitted.
      const hasMissingDose = v.safety_flags.some((s) => s.flag_type === "missing_dose");
      expect(hasMissingDose).toBe(true);

      // No diagnosis text in any user-facing field.
      const allText = JSON.stringify(v);
      expect(/(diagnosed with|has pneumonia|has the flu)/i.test(allText)).toBe(false);
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  });

  test("allergy transcript produces a memory candidate that requires confirmation", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "carenote-e2e-"));
    try {
      const { manager, visits } = await buildHarness(repoRoot, join(tmp, "state.json"));
      await manager.analyzeTurn({
        kind: "analyze_turn",
        visit_id: "v2",
        turn_id: "itm-1",
        transcript: "我对青霉素过敏。",
        previous_item_id: null,
      });
      const v = await visits.get("v2");
      expect(v.memory_candidates.length).toBeGreaterThan(0);
      for (const m of v.memory_candidates) {
        expect(m.requires_user_confirmation).toBe(true);
        expect(m.confirmation_status).toBe("pending");
      }
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  });

  test("patient-side symptom does not become a medication reminder", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "carenote-e2e-"));
    try {
      const { manager, visits } = await buildHarness(repoRoot, join(tmp, "state.json"));
      await manager.analyzeTurn({
        kind: "analyze_turn",
        visit_id: "v3",
        turn_id: "itm-1",
        transcript: "我昨天吃了药以后有点恶心。",
        previous_item_id: null,
      });
      const v = await visits.get("v3");
      expect(v.draft_reminders.length).toBe(0);
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  });
});
