// CodexRuntime — the Codex-only abstraction the harness sits behind.
//
// Implementations: codexSdkRuntime (primary), codexCliRuntime (fallback),
// codexAppServerRuntime (placeholder), stubRuntime (CI/no-codex).
//
// There are deliberately no non-Codex implementations. The interface is
// scoped to Codex semantics (thread persistence, sandbox modes, JSON
// output schemas) and is not a "model provider abstraction".

import type { CodexAgentRole } from "../medical/medicalSchemas";

export type CodexAgentRunInput = {
  team_id: string;
  visit_id: string;
  role: CodexAgentRole;
  thread_id?: string | null;
  prompt_version: string;
  schema_version: string;
  /** The structured event payload that will be serialized into the user message. */
  event: unknown;
  visit_state_snapshot: unknown;
  memory_context?: unknown[];
  /** Persona text for this role. Sent on first turn; reused via thread thereafter. */
  instructions: string;
  /** Optional per-turn append to instructions. CLARIOSE_V01 §6: used by the
   *  prompt assembler to inject memory-recall results without polluting the
   *  registry-loaded role prompt. */
  extra_instructions?: string | null;
  /** CLARIOSE_V01 §6: pre-assembled user message. When provided, the runtime
   *  sends this as the codex turn input verbatim instead of constructing one
   *  from event/visit_state_snapshot/memory_context. The §6 dynamic-template
   *  contract (visit_context / recent_transcript / inbox / blackboard /
   *  event / expected_output_schema_name blocks) lives entirely in the
   *  prompt assembler, not in the runtime. */
  pre_built_user_message?: string | null;
  /** Schema name (used for repair-prompt context only; runtime sends JSON Schema below). */
  expected_output_schema_name: string;
  /** JSON Schema body that Codex will validate output against. */
  expected_output_schema: Record<string, unknown>;
};

export type CodexAgentRunOutput = {
  team_id: string;
  visit_id: string;
  role: CodexAgentRole;
  thread_id: string | null;
  run_id: string;
  raw_text: string;
  parsed_json?: unknown;
  validation_status: "valid" | "invalid" | "repaired" | "failed";
  errors?: string[];
  started_at: string;
  completed_at: string;
  /**
   * Runtime-specific debug payload. Optional; populated by codex-cli with
   * the spawned command, exit code, stdout/stderr previews, parsed JSONL
   * events, and (when DEBUG_CARENOTE_CODEX=true) the debug-artifact dir.
   * Surfaced through the run manager so agent_runs reporting can include
   * it without leaking PHI by default.
   */
  extra?: Record<string, unknown>;
};

export type CodexRuntimeName =
  | "codex-sdk"
  | "codex-cli"
  | "codex-app-server"
  | "stub";

export type CodexAuthMode = "chatgpt_subscription" | "api_key" | "unknown";

export interface CodexRuntime {
  readonly name: CodexRuntimeName;

  startOrResumeThread(input: {
    team_id: string;
    role: CodexAgentRole;
    existing_thread_id?: string | null;
    agent_config_path?: string;
  }): Promise<{ thread_id: string | null }>;

  /**
   * Run a single turn against a role's thread. The caller passes
   * `existing_thread_id`; the runtime returns the (possibly new) thread ID
   * in the output so the store can be updated.
   */
  run(input: CodexAgentRunInput): Promise<CodexAgentRunOutput>;

  healthCheck(): Promise<{
    ok: boolean;
    runtime: CodexRuntimeName;
    auth_mode?: CodexAuthMode;
    details?: string;
  }>;
}
