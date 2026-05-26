// 4-phase dream prompt builder tests.

import {
  buildDreamPrompt,
  type DreamPromptInput,
} from "../../src/modules/carenote/swarm/dream/dream.prompts";

const baseInput: DreamPromptInput = {
  phase: "orient",
  workspaceRoot: "/data/users/u1",
  stagingDir: "/data/users/u1/.dream-staging/d1",
  visits: [
    { visitId: "v_a", endedAt: "2026-04-29T10:00:00Z" },
    { visitId: "v_b", endedAt: "2026-04-30T11:00:00Z" },
  ],
  scope: { kind: "all" },
};

describe("buildDreamPrompt", () => {
  it("orient prompt mentions workspace + visit list + 'DO NOT edit'", () => {
    const p = buildDreamPrompt(baseInput);
    expect(p).toContain("/data/users/u1");
    expect(p).toContain("Phase 1 — Orient");
    expect(p).toContain("v_a");
    expect(p).toContain("v_b");
    expect(p).toContain("DO NOT edit");
  });

  it("gather prompt references staging dir and lists visit ids", () => {
    const p = buildDreamPrompt({ ...baseInput, phase: "gather" });
    expect(p).toContain("Phase 2 — Gather");
    expect(p).toContain("/data/users/u1/.dream-staging/d1");
    expect(p).toContain("v_a.md");
    expect(p).toContain("v_b.md");
  });

  it("consolidate prompt enumerates target files", () => {
    const p = buildDreamPrompt({ ...baseInput, phase: "consolidate" });
    expect(p).toContain("memory_summary.md");
    expect(p).toContain("rollout_summaries/");
    expect(p).toContain("allergies.md");
    expect(p).toContain("conditions.md");
    expect(p).toContain("skills/");
  });

  it("prune prompt enforces MEMORY.md size cap", () => {
    const p = buildDreamPrompt({ ...baseInput, phase: "prune" });
    expect(p).toContain("MEMORY.md");
    expect(p).toMatch(/80 lines/);
    expect(p).toMatch(/25 ?KB/i);
  });

  it("scope=visit narrows the consolidate instructions to that single rollout", () => {
    const p = buildDreamPrompt({
      ...baseInput,
      phase: "consolidate",
      scope: { kind: "visit", visitId: "v_a" },
      visits: [{ visitId: "v_a", endedAt: "2026-04-29T10:00:00Z" }],
    });
    expect(p).toContain("rollout_summaries/v_a.md");
    expect(p).toContain("DO NOT modify memory_summary.md");
    expect(p).toContain("DO NOT modify allergies.md");
  });
});
