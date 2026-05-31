// When CARENOTE_CODEX_RUNTIME changes from stub to codex-cli, the team
// bootstrap must mark stub-runtime thread state as needing reset rather
// than reusing it. Otherwise codex-cli runs may attempt to resume thread
// IDs that don't exist on the new runtime.

import { mkdtemp, rm, readFile, writeFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { bootstrapCareNoteTeam } from "../../src/modules/carenote/codex-harness/codexTeamBootstrap";
import { JsonFileCodexThreadStore } from "../../src/modules/carenote/codex-harness/codexThreadStore";

const repoRoot = resolve(__dirname, "../../..");

describe("Bootstrap runtime-mismatch handling", () => {
  test("ensureThreads resets thread state whose runtime doesn't match the active runtime", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "carenote-rt-"));
    try {
      const statePath = join(tmp, "state.json");
      await mkdir(tmp, { recursive: true });

      // Round 1: bootstrap with stub. Records stub thread state.
      await bootstrapCareNoteTeam({
        repoRoot,
        threadStatePath: statePath,
        runtime: { force: "stub" },
        store: new JsonFileCodexThreadStore(statePath),
      });

      // Hand-pollute with an old stub thread_id and a manual last_run_at,
      // simulating the user's mixed-runtime team-state file.
      const before = JSON.parse(await readFile(statePath, "utf8")) as {
        team_id: string;
        agents: Record<string, Record<string, unknown>>;
        updated_at: string;
      };
      for (const role of Object.keys(before.agents)) {
        before.agents[role]!.runtime = "stub";
        before.agents[role]!.thread_id = `stub-${role}`;
        before.agents[role]!.status = "active";
      }
      await writeFile(statePath, JSON.stringify(before, null, 2), "utf8");

      // Round 2: switch runtime. We don't actually need codex-cli installed
      // to test the mismatch logic — force "codex-cli" + manually pretend by
      // forcing stub but verifying the reset_reason code path needs runtime
      // change. Use force "codex-app-server" which is always available.
      const second = await bootstrapCareNoteTeam({
        repoRoot,
        threadStatePath: statePath,
        runtime: { force: "codex-app-server" },
        store: new JsonFileCodexThreadStore(statePath),
      });

      const after = await second.store.list(second.manifest.team_id);
      for (const rec of after) {
        expect(rec.runtime).toBe("codex-app-server");
        expect(rec.thread_id).toBeNull();
        expect(rec.reset_reason).toMatch(/runtime_changed:stub->codex-app-server/);
      }
    } finally {
      await rm(tmp, { recursive: true, force: true });
    }
  });
});
