import { resolve } from "node:path";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { bootstrapCareNoteTeam } from "../../src/modules/carenote/codex-harness/codexTeamBootstrap";
import { JsonFileCodexThreadStore } from "../../src/modules/carenote/codex-harness/codexThreadStore";

const repoRoot = resolve(__dirname, "../../..");

describe("Codex team persistence", () => {
  test("bootstrap is idempotent and persists prompt/schema versions", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "carenote-state-"));
    const statePath = join(tmp, "team-state.json");
    try {
      const a = await bootstrapCareNoteTeam({
        repoRoot,
        threadStatePath: statePath,
        runtime: { force: "stub" },
        store: new JsonFileCodexThreadStore(statePath),
      });
      const list1 = await a.store.list(a.manifest.team_id);
      expect(list1.length).toBe(a.manifest.agents.length);
      // prompt + schema versions are recorded. M7.6 bumped some agents
      // to 2.0.0 — assert each role's recorded version matches the
      // manifest entry rather than a hard-coded 1.0.0.
      const byRole = new Map(a.manifest.agents.map((m) => [m.role, m]));
      for (const r of list1) {
        const m = byRole.get(r.role)!;
        expect(r.prompt_version).toBe(m.prompt_version);
        expect(r.schema_version).toBe(m.schema_version);
        expect(r.runtime).toBe("stub");
      }
      // Second bootstrap: no resets.
      const b = await bootstrapCareNoteTeam({
        repoRoot,
        threadStatePath: statePath,
        runtime: { force: "stub" },
        store: new JsonFileCodexThreadStore(statePath),
      });
      const list2 = await b.store.list(b.manifest.team_id);
      for (const r of list2) {
        expect(r.reset_reason).toBeFalsy();
      }
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  });
});
