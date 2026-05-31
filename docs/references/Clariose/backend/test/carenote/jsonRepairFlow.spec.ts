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
import { StubRuntime } from "../../src/modules/carenote/codex-harness/stubRuntime";

const repoRoot = resolve(__dirname, "../../..");

describe("Codex output parser + repair flow", () => {
  test("fenced JSON is stripped before validation", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "carenote-repair-"));
    try {
      const statePath = join(tmp, "state.json");
      const boot = await bootstrapCareNoteTeam({
        repoRoot,
        threadStatePath: statePath,
        runtime: { force: "stub" },
        store: new JsonFileCodexThreadStore(statePath),
      });
      const runtime = boot.runtime.runtime as StubRuntime;
      runtime.setOverride("medical_instruction_extractor", () =>
        "```json\n" + JSON.stringify({ facts: [] }) + "\n```",
      );
      runtime.setOverride("transcript_quality", () =>
        JSON.stringify({
          quality: "high",
          uncertain_terms: [],
          missing_critical_fields: [],
          recommended_action: "",
          source_turn_ids: ["itm-1"],
        }),
      );
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
      const result = await manager.analyzeTurn({
        kind: "analyze_turn",
        visit_id: "v1",
        turn_id: "itm-1",
        transcript: "随便说点什么。",
        previous_item_id: null,
      });
      const ext = result.runs.find((r) => r.role === "medical_instruction_extractor");
      expect(ext?.validation_status).toBe("valid");
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  });

  test("invalid JSON marks the run as failed and does not merge", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "carenote-repair-"));
    try {
      const statePath = join(tmp, "state.json");
      const boot = await bootstrapCareNoteTeam({
        repoRoot,
        threadStatePath: statePath,
        runtime: { force: "stub" },
        store: new JsonFileCodexThreadStore(statePath),
      });
      const runtime = boot.runtime.runtime as StubRuntime;
      // Always emit unparseable garbage for the extractor.
      runtime.setOverride("medical_instruction_extractor", () => "definitely not json :(");
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
      const result = await manager.analyzeTurn({
        kind: "analyze_turn",
        visit_id: "v1",
        turn_id: "itm-1",
        transcript: "无关紧要的输入。",
        previous_item_id: null,
      });
      const ext = result.runs.find((r) => r.role === "medical_instruction_extractor");
      expect(ext?.validation_status === "failed" || ext?.validation_status === "invalid").toBe(true);
      // Visit state has no facts merged from this run.
      const v = await visits.get("v1");
      expect(v.facts.length).toBe(0);
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  });
});
