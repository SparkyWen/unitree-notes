// codexTeamBootstrap — load the manifest, build a registry, build the
// chosen runtime, build the team, and ensure thread-state records exist
// for every role. Idempotent.

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import {
  CodexAgentTeamManifestSchema,
  type CodexAgentTeamManifest,
} from "../medical/medicalSchemas";
import { CodexAgentRegistry } from "./codexAgentRegistry";
import { CodexAgentTeam } from "./codexAgentTeam";
import { CodexPromptLoader } from "./codexPromptLoader";
import {
  createCodexRuntime,
  type CodexRuntimeFactoryOptions,
  type CodexRuntimeSelection,
} from "./codexRuntimeFactory";
import {
  JsonFileCodexThreadStore,
  type CodexThreadStore,
} from "./codexThreadStore";

export type BootstrapInput = {
  repoRoot: string;
  manifestPath?: string;
  threadStatePath?: string;
  runtime?: CodexRuntimeFactoryOptions;
  store?: CodexThreadStore;
};

export type BootstrapResult = {
  manifest: CodexAgentTeamManifest;
  team: CodexAgentTeam;
  registry: CodexAgentRegistry;
  store: CodexThreadStore;
  runtime: CodexRuntimeSelection;
};

export async function bootstrapCareNoteTeam(
  input: BootstrapInput,
): Promise<BootstrapResult> {
  const manifestPath =
    input.manifestPath ??
    resolve(input.repoRoot, "config/codex-teams/carenote-doctor-visit.team.json");
  const threadStatePath =
    input.threadStatePath ??
    resolve(input.repoRoot, ".data/carenote/codex-agent-team-state.json");

  const raw = await readFile(manifestPath, "utf8");
  const parsed = JSON.parse(raw);
  const manifest = CodexAgentTeamManifestSchema.parse(parsed);

  const loader = new CodexPromptLoader(input.repoRoot);
  const registry = await CodexAgentRegistry.fromManifest(manifest, loader);

  const runtime = await createCodexRuntime({
    workingDirectory: input.repoRoot,
    defaultModel: manifest.default_runtime_options.model,
    ...(input.runtime ?? {}),
  });

  const store = input.store ?? new JsonFileCodexThreadStore(threadStatePath);

  const team = new CodexAgentTeam(manifest, registry, runtime.runtime, store);
  await team.ensureThreads();

  return { manifest, team, registry, store, runtime };
}
