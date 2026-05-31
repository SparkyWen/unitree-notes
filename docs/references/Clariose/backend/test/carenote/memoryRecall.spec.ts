// CLARIOSE_V01 §4 — recall pipeline unit tests. No LLM round-trip; stubs
// the side-query so behaviour is deterministic.

import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ConfigService } from "@nestjs/config";

import { MemoryScanService } from "../../src/modules/carenote/recall/memoryScan";
import { MemorySurfaceService } from "../../src/modules/carenote/recall/memorySurface";
import { RecallBudgetService } from "../../src/modules/carenote/recall/recallBudget";
import { RecallCache } from "../../src/modules/carenote/recall/recallCache";
import { MemoryRecallService } from "../../src/modules/carenote/recall/memoryRecall";
import type { ManifestEntry } from "../../src/modules/carenote/recall/recall.types";

class StubSideQuery {
  isEnabled() { return true; }
  modelName() { return "stub"; }
  selectFn: (m: ManifestEntry[]) => ManifestEntry[] = (m) => m.slice(0, 3);
  async select(input: { manifest: ManifestEntry[] }) {
    return this.selectFn(input.manifest);
  }
}

async function setupRoot(): Promise<{
  root: string;
  cleanup: () => Promise<void>;
}> {
  const root = await mkdtemp(join(tmpdir(), "carenote-recall-"));
  await mkdir(join(root, "visits", "v-1"), { recursive: true });
  await mkdir(join(root, "users", "u-1"), { recursive: true });

  await writeFile(
    join(root, "users", "u-1", "allergies.md"),
    `---
name: penicillin_allergy
description: Patient is allergic to penicillin (anaphylaxis history).
keywords: [allergy, antibiotic, penicillin]
type: clinical_fact
---

Patient experienced anaphylaxis after amoxicillin in 2024-10. Avoid all penicillin-class antibiotics.
`,
  );

  await writeFile(
    join(root, "users", "u-1", "MEMORY.md"),
    `---
name: chronic_conditions
description: Asthma since 2018, controlled with budesonide inhaler.
keywords: [asthma, condition]
---

Asthma since 2018. Daily budesonide. Spacer used.
`,
  );

  await writeFile(
    join(root, "visits", "v-1", "read_path.md"),
    `---
name: visit_hint
description: For this visit, prioritize allergy history.
keywords: [hint]
---

Doctor mentioned starting an antibiotic.
`,
  );

  return {
    root,
    cleanup: async () => rm(root, { recursive: true, force: true }),
  };
}

function makeServices(root: string) {
  const cfg = new ConfigService({
    CARENOTE_MEMORY_ROOT: root,
    OPENAI_API_KEY: "sk-test", // satisfies isEnabled() gate
    REDIS_URL: undefined as unknown as string,
  });
  const cache = new RecallCache(cfg);
  const scan = new MemoryScanService(cfg);
  const sideQuery = new StubSideQuery();
  const surface = new MemorySurfaceService(cfg);
  const budget = new RecallBudgetService(cache);
  const recall = new MemoryRecallService(
    scan,
    sideQuery as unknown as import("../../src/modules/carenote/recall/memorySideQuery").MemorySideQueryService,
    surface,
    budget,
    cache,
  );
  return { recall, sideQuery, budget };
}

describe("CLARIOSE_V01 §4 — MemoryRecall pipeline", () => {
  test("scan merges visit + user manifests and surfaces selected files", async () => {
    const { root, cleanup } = await setupRoot();
    try {
      const { recall, sideQuery } = makeServices(root);
      sideQuery.selectFn = (m) =>
        m.filter((e) => e.relPath === "users/u-1/allergies.md");

      const result = await recall.prefetch({
        visit_id: "v-1",
        user_id: "u-1",
        query: "starting amoxicillin tonight",
      });

      expect(result.skipped).toBeUndefined();
      expect(result.manifestSize).toBe(3); // 2 user + 1 visit
      expect(result.selectedCount).toBe(1);
      expect(result.files).toEqual(["users/u-1/allergies.md"]);
      expect(result.append).toContain("Patient is allergic");
      expect(result.append).toContain("anaphylaxis");
      expect(result.append).toContain("## Patient Memory Context");
      expect(result.bytesInjected).toBeGreaterThan(0);
    } finally {
      await cleanup();
    }
  });

  test("isSubagentFork skip rule returns empty without scanning", async () => {
    const { root, cleanup } = await setupRoot();
    try {
      const { recall } = makeServices(root);
      const result = await recall.prefetch({
        visit_id: "v-1",
        user_id: "u-1",
        query: "anything",
        options: { isSubagentFork: true },
      });
      expect(result.skipped).toBe("subagent");
      expect(result.append).toBeNull();
      expect(result.bytesInjected).toBe(0);
    } finally {
      await cleanup();
    }
  });

  test("missing visit_id skips with no_visit", async () => {
    const { root, cleanup } = await setupRoot();
    try {
      const { recall } = makeServices(root);
      const result = await recall.prefetch({
        visit_id: null,
        user_id: "u-1",
        query: "x",
      });
      expect(result.skipped).toBe("no_visit");
    } finally {
      await cleanup();
    }
  });

  test("dedup: same file isn't surfaced twice in the same visit", async () => {
    const { root, cleanup } = await setupRoot();
    try {
      const { recall, sideQuery } = makeServices(root);
      sideQuery.selectFn = (m) =>
        m.filter((e) => e.relPath === "users/u-1/allergies.md");
      const r1 = await recall.prefetch({
        visit_id: "v-1",
        user_id: "u-1",
        query: "first",
      });
      expect(r1.files).toEqual(["users/u-1/allergies.md"]);

      const r2 = await recall.prefetch({
        visit_id: "v-1",
        user_id: "u-1",
        query: "second",
      });
      // Same file selected, but dedup blocks re-injection.
      expect(r2.skipped).toBe("empty");
      expect(r2.append).toBeNull();
      expect(r2.selectedCount).toBe(1);
    } finally {
      await cleanup();
    }
  });

  test("budget cap returns visit_budget once exceeded", async () => {
    const { root, cleanup } = await setupRoot();
    try {
      const { recall, budget } = makeServices(root);
      // Manually consume way over the budget (96KB).
      await budget.consume("v-1", 200 * 1024);
      const r = await recall.prefetch({
        visit_id: "v-1",
        user_id: "u-1",
        query: "x",
      });
      expect(r.skipped).toBe("visit_budget");
    } finally {
      await cleanup();
    }
  });

  test("disabled flag returns disabled skip without LLM", async () => {
    const { root, cleanup } = await setupRoot();
    try {
      const cfg = new ConfigService({
        CARENOTE_MEMORY_ROOT: root,
        OPENAI_API_KEY: "", // no key disables sideQuery → recall reports disabled
      });
      const cache = new RecallCache(cfg);
      const sideQuery = new (
        await import("../../src/modules/carenote/recall/memorySideQuery")
      ).MemorySideQueryService(cfg);
      const recall = new MemoryRecallService(
        new MemoryScanService(cfg),
        sideQuery,
        new MemorySurfaceService(cfg),
        new RecallBudgetService(cache),
        cache,
      );
      const r = await recall.prefetch({
        visit_id: "v-1",
        user_id: "u-1",
        query: "x",
      });
      expect(r.skipped).toBe("disabled");
    } finally {
      await cleanup();
    }
  });
});
