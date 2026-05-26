// CodexAgentTeam — binds a manifest, registry, runtime, and store into
// one object the run manager can talk to.

import type {
  CodexAgentRole,
  CodexAgentTeamManifest,
} from "../medical/medicalSchemas";
import type { CodexAgentRegistry } from "./codexAgentRegistry";
import type {
  CodexAgentRunInput,
  CodexAgentRunOutput,
  CodexRuntime,
} from "./codexRuntime";
import type { CodexThreadStore } from "./codexThreadStore";

export class CodexAgentTeam {
  constructor(
    private readonly manifestRef: CodexAgentTeamManifest,
    private readonly registry: CodexAgentRegistry,
    private readonly runtime: CodexRuntime,
    private readonly store: CodexThreadStore,
  ) {}

  get teamId(): string {
    return this.manifestRef.team_id;
  }

  manifest(): CodexAgentTeamManifest {
    return this.manifestRef;
  }

  /**
   * Idempotent. For each role, ensure a thread state record exists. We
   * do NOT pre-create Codex threads; the SDK runtime allocates one on the
   * first run and we capture the assigned id then.
   */
  async ensureThreads(): Promise<void> {
    for (const role of this.registry.list()) {
      const existing = await this.store.get(this.teamId, role.role);
      if (
        existing &&
        existing.status === "active" &&
        existing.prompt_version === role.promptVersion &&
        existing.schema_version === role.schemaVersion &&
        existing.runtime === this.runtime.name
      ) {
        continue; // up to date
      }
      const reset_reason = !existing
        ? null
        : existing.runtime !== this.runtime.name
        ? `runtime_changed:${existing.runtime}->${this.runtime.name}`
        : existing.prompt_version !== role.promptVersion
        ? "prompt_version_changed"
        : existing.schema_version !== role.schemaVersion
        ? "schema_version_changed"
        : null;

      await this.store.upsert({
        team_id: this.teamId,
        role: role.role,
        thread_id: null,
        runtime: this.runtime.name,
        prompt_version: role.promptVersion,
        schema_version: role.schemaVersion,
        status: "active",
        last_run_at: null,
        last_summary: null,
        reset_reason,
        created_at: existing?.created_at ?? new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    }
  }

  async resetThread(role: CodexAgentRole, reason: string): Promise<void> {
    await this.store.reset(this.teamId, role, reason);
  }

  async run(role: CodexAgentRole, input: CodexAgentRunInput): Promise<CodexAgentRunOutput> {
    const def = this.registry.getRole(role);
    const stored = await this.store.get(this.teamId, role);
    // CLARIOSE_V01 §6: registry prompt is mandatory and immutable; per-turn
    // memory-recall append (and any future per-turn additions) come in via
    // input.extra_instructions and are concatenated, never replace the role
    // definition.
    const composedInstructions = input.extra_instructions
      ? `${def.prompt}\n\n${input.extra_instructions}`
      : def.prompt;
    const merged: CodexAgentRunInput = {
      ...input,
      thread_id: stored?.thread_id ?? null,
      prompt_version: def.promptVersion,
      schema_version: def.schemaVersion,
      instructions: composedInstructions,
      expected_output_schema_name: def.schemaName,
    };
    const out = await this.runtime.run(merged);
    if (out.thread_id && out.thread_id !== stored?.thread_id) {
      await this.store.upsert({
        team_id: this.teamId,
        role,
        thread_id: out.thread_id,
        runtime: this.runtime.name,
        prompt_version: def.promptVersion,
        schema_version: def.schemaVersion,
        status: "active",
        last_run_at: new Date().toISOString(),
        last_summary: stored?.last_summary ?? null,
        reset_reason: null,
        created_at: stored?.created_at ?? new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    } else if (stored) {
      await this.store.recordRun(this.teamId, role, "");
    }
    return out;
  }
}
