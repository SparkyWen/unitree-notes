// Health-check CLI for the Codex runtime.
//
//   npm run carenote:codex:health
//
// Returns 0 if a runtime is selected (even stub) and prints a JSON
// description; returns 1 if bootstrap fails outright.

import { resolve } from "node:path";
import { createCodexRuntime } from "../codex-harness/codexRuntimeFactory";
import { bootstrapCareNoteTeam } from "../codex-harness/codexTeamBootstrap";

async function main(): Promise<void> {
  const repoRoot = resolve(__dirname, "../../../../..");
  const selection = await createCodexRuntime({ workingDirectory: repoRoot });
  const health = await selection.runtime.healthCheck();
  let manifestOk = false;
  let manifestErr: string | undefined;
  try {
    await bootstrapCareNoteTeam({ repoRoot, runtime: { force: selection.runtime.name } });
    manifestOk = true;
  } catch (err) {
    manifestErr = (err as Error).message;
  }
  const out = {
    runtime: selection.runtime.name,
    selection_reason: selection.reason,
    detected: selection.detected,
    runtime_health: health,
    manifest_ok: manifestOk,
    manifest_error: manifestErr,
  };
  console.log(JSON.stringify(out, null, 2));
}

main().catch((err) => {
  console.error(JSON.stringify({ ok: false, error: (err as Error).message }, null, 2));
  process.exit(1);
});
