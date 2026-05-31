// Bootstrap CLI — ensures the JSON team-state mirror exists and prints
// the team manifest.
//
//   npm run carenote:codex:bootstrap

import { resolve } from "node:path";
import { bootstrapCareNoteTeam } from "../codex-harness/codexTeamBootstrap";

async function main(): Promise<void> {
  const repoRoot = resolve(__dirname, "../../../../..");
  const result = await bootstrapCareNoteTeam({ repoRoot });
  const states = await result.store.list(result.manifest.team_id);
  console.log(JSON.stringify(
    {
      team_id: result.manifest.team_id,
      runtime: result.runtime.runtime.name,
      runtime_reason: result.runtime.reason,
      agents: result.manifest.agents.map((a: { role: string }) => a.role),
      thread_states: states,
    },
    null,
    2,
  ));
}

main().catch((err) => {
  console.error("[carenote bootstrap] fatal:", err);
  process.exit(1);
});
