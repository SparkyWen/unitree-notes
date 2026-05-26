// CodexAgentRegistry — in-memory map of role → role definition. Built
// once at startup from the team manifest plus the prompt loader.

import type {
  CodexAgentRole,
  CodexAgentTeamManifest,
} from "../medical/medicalSchemas";
import type { CodexPromptLoader } from "./codexPromptLoader";

export type RoleDefinition = {
  role: CodexAgentRole;
  prompt: string;
  promptVersion: string;
  schemaName: string;
  schemaVersion: string;
  threadPolicy: "persistent_per_team" | "transient";
  sandboxPolicy: "read_only_runtime";
  agentConfigPath?: string;
};

export class CodexAgentRegistry {
  private byRole = new Map<CodexAgentRole, RoleDefinition>();

  static async fromManifest(
    manifest: CodexAgentTeamManifest,
    loader: CodexPromptLoader,
  ): Promise<CodexAgentRegistry> {
    const reg = new CodexAgentRegistry();
    for (const a of manifest.agents) {
      const prompt = await loader.load(a.prompt_file);
      reg.byRole.set(a.role, {
        role: a.role,
        prompt,
        promptVersion: a.prompt_version,
        schemaName: a.schema_name,
        schemaVersion: a.schema_version,
        threadPolicy: a.thread_policy,
        sandboxPolicy: a.sandbox_policy,
        agentConfigPath: a.agent_config_path,
      });
    }
    return reg;
  }

  getRole(role: CodexAgentRole): RoleDefinition {
    const r = this.byRole.get(role);
    if (!r) throw new Error(`role not registered: ${role}`);
    return r;
  }

  list(): RoleDefinition[] {
    return [...this.byRole.values()];
  }
}
