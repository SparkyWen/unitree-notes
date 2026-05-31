// Run-reporting tests. Two invariants:
//   1. Failed runtime calls do NOT silently produce empty VisitState —
//      the run manager records each failed run with errors and a preview.
//   2. The harness's `runs` accumulator collects every recorded run so
//      mock-turn can print agent_runs.

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
import type { CodexAgentRunInput } from "../../src/modules/carenote/codex-harness/codexRuntime";

const repoRoot = resolve(__dirname, "../../..");

describe("Agent run reporting", () => {
  test("each role's run is recorded via recordAgentRun, including failures", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "carenote-runs-"));
    try {
      const statePath = join(tmp, "state.json");
      const boot = await bootstrapCareNoteTeam({
        repoRoot,
        threadStatePath: statePath,
        runtime: { force: "stub" },
        store: new JsonFileCodexThreadStore(statePath),
      });
      // Inject failure for one role to confirm it's reported, not silently
      // dropped. The stub runtime exposes setOverride.
      const stub = boot.runtime.runtime as unknown as {
        setOverride: (
          role: string,
          fn: (i: CodexAgentRunInput) => string,
        ) => void;
      };
      stub.setOverride(
        "transcript_quality",
        () => "this is not json — the model went off-script",
      );

      const visits = new InMemoryVisitStateStore();
      const memory = new InMemoryMemoryRetrievalService();
      const queue = new InMemoryCodexJobQueue();
      const collected: { role: string; status: string; errors?: string[] }[] = [];
      const manager = new CodexRunManager({
        team: boot.team,
        queue,
        visitStateGet: (id) => visits.get(id),
        visitStateSet: (id, n) => visits.set(id, n),
        memory,
        recordAgentRun: async (r) => {
          collected.push({
            role: r.role,
            status: r.validation_status,
            errors: r.errors,
          });
        },
      });
      await manager.analyzeTurn({
        kind: "analyze_turn",
        visit_id: "v-rep",
        turn_id: "itm-1",
        transcript: "我对青霉素过敏。",
        previous_item_id: null,
      });
      // 9 roles excluding visit_orchestrator + final_visit_summary.
      expect(collected.length).toBeGreaterThanOrEqual(9);
      const tq = collected.filter((c) => c.role === "transcript_quality");
      // The first run failed; either the repair pass also failed (status=failed)
      // or the repair succeeded ("repaired"). Both prove the failure was not
      // silent — at least one entry is non-valid.
      expect(tq.length).toBeGreaterThan(0);
      const sawNonValid = tq.some((c) => c.status !== "valid");
      expect(sawNonValid).toBe(true);
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  });
});
