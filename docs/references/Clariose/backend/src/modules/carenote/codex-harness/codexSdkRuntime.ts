// codexSdkRuntime — uses @openai/codex-sdk to drive each role's thread.
//
// The SDK shells to the `codex` CLI binary. Therefore this runtime
// requires:
//   - `@openai/codex-sdk` resolvable at runtime;
//   - `codex` binary on PATH;
//   - either ChatGPT subscription auth at ~/.codex/auth.json
//     (run `codex login --device-auth` once) or `OPENAI_API_KEY` env.
//
// Subscription auth is preferred. If both are present, the CLI will pick
// API-key by default; we therefore intentionally do NOT inject
// OPENAI_API_KEY into the child unless the operator opts in via
// CARENOTE_CODEX_ALLOW_API_KEY=1.

import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import type { CodexAgentRole } from "../medical/medicalSchemas";
import type {
  CodexAgentRunInput,
  CodexAgentRunOutput,
  CodexAuthMode,
  CodexRuntime,
} from "./codexRuntime";

type SdkModule = {
  Codex: new (opts?: {
    apiKey?: string;
    baseUrl?: string;
    codexPathOverride?: string;
    env?: Record<string, string>;
    config?: Record<string, unknown>;
  }) => SdkCodex;
};

type SdkCodex = {
  startThread(opts?: SdkThreadOptions): SdkThread;
  resumeThread(id: string, opts?: SdkThreadOptions): SdkThread;
};

type SdkThreadOptions = {
  model?: string;
  sandboxMode?: "read-only" | "workspace-write" | "danger-full-access";
  workingDirectory?: string;
  skipGitRepoCheck?: boolean;
  approvalPolicy?: "never" | "untrusted" | "on-request" | "on-failure";
  modelReasoningEffort?: "minimal" | "low" | "medium" | "high";
  networkAccessEnabled?: boolean;
};

type SdkTurnOptions = {
  outputSchema?: Record<string, unknown>;
  signal?: AbortSignal;
};

type SdkThread = {
  readonly id: string | null;
  run(input: string, opts?: SdkTurnOptions): Promise<{
    items: unknown[];
    finalResponse: string;
    usage: unknown;
  }>;
};

export type CodexSdkRuntimeOptions = {
  workingDirectory?: string;
  defaultModel?: string;
};

export class CodexSdkRuntime implements CodexRuntime {
  readonly name = "codex-sdk" as const;

  private mod: SdkModule | null = null;
  private codex: SdkCodex | null = null;

  // role-derived thread cache so we don't recreate the SDK Thread on every run.
  private threadByRole = new Map<string, SdkThread>();

  private opts: CodexSdkRuntimeOptions;

  constructor(opts: CodexSdkRuntimeOptions = {}) {
    this.opts = opts;
  }

  async startOrResumeThread(input: {
    team_id: string;
    role: CodexAgentRole;
    existing_thread_id?: string | null;
    agent_config_path?: string;
  }): Promise<{ thread_id: string | null }> {
    await this.ensureSdk();
    const key = `${input.team_id}:${input.role}`;
    if (this.threadByRole.has(key)) {
      const t = this.threadByRole.get(key)!;
      return { thread_id: t.id };
    }
    if (input.existing_thread_id) {
      const t = this.codex!.resumeThread(input.existing_thread_id, this.threadOptions());
      this.threadByRole.set(key, t);
      return { thread_id: t.id };
    }
    const t = this.codex!.startThread(this.threadOptions());
    this.threadByRole.set(key, t);
    return { thread_id: t.id };
  }

  async run(input: CodexAgentRunInput): Promise<CodexAgentRunOutput> {
    await this.ensureSdk();
    // CLARIOSE_V01 §10: thread cache key is (team, visit, role) so visits
    // never share a codex thread for the same role. Fixes a real isolation
    // bug — visit B used to inherit visit A's hidden chain-of-thought
    // because the cache key was just `(team, role)`.
    const key = `${input.team_id}:${input.visit_id}:${input.role}`;
    let thread = this.threadByRole.get(key);
    if (!thread) {
      thread = input.thread_id
        ? this.codex!.resumeThread(input.thread_id, this.threadOptions())
        : this.codex!.startThread(this.threadOptions());
      this.threadByRole.set(key, thread);
    }

    // CLARIOSE_V01 §6: prefer the assembler's pre-built message when provided;
    // fall back to the legacy buildUserMessage shape for code paths that
    // haven't been migrated (json_repair, summarise) yet.
    const userMessage =
      input.pre_built_user_message?.trim() ?? buildUserMessage(input);
    const started_at = new Date().toISOString();
    const run_id = randomUUID();

    try {
      const turn = await thread.run(userMessage, {
        outputSchema: input.expected_output_schema,
      });
      return {
        team_id: input.team_id,
        visit_id: input.visit_id,
        role: input.role,
        thread_id: thread.id,
        run_id,
        raw_text: turn.finalResponse,
        validation_status: "valid",
        started_at,
        completed_at: new Date().toISOString(),
      };
    } catch (err) {
      return {
        team_id: input.team_id,
        visit_id: input.visit_id,
        role: input.role,
        thread_id: thread.id,
        run_id,
        raw_text: "",
        validation_status: "failed",
        errors: [(err as Error).message],
        started_at,
        completed_at: new Date().toISOString(),
      };
    }
  }

  async healthCheck(): Promise<{
    ok: boolean;
    runtime: "codex-sdk";
    auth_mode?: CodexAuthMode;
    details?: string;
  }> {
    const auth_mode: CodexAuthMode = detectAuthMode();
    try {
      await this.ensureSdk();
      return { ok: true, runtime: "codex-sdk", auth_mode };
    } catch (err) {
      return {
        ok: false,
        runtime: "codex-sdk",
        auth_mode,
        details: (err as Error).message,
      };
    }
  }

  private async ensureSdk(): Promise<void> {
    if (this.codex) return;
    if (!this.mod) {
      try {
        // The SDK is an optional runtime dependency. We hide the import
        // from the TypeScript compiler so the harness still type-checks
        // when @openai/codex-sdk is not installed; the factory selects
        // another runtime in that case.
        const req = Function("name", "return require(name)") as (n: string) => unknown;
        this.mod = req("@openai/codex-sdk") as SdkModule;
      } catch (err) {
        throw new Error(
          `@openai/codex-sdk is not installed: ${(err as Error).message}`,
        );
      }
    }
    const env = this.buildSafeEnv();
    this.codex = new this.mod.Codex({ env });
  }

  private threadOptions(): SdkThreadOptions {
    return {
      model: this.opts.defaultModel ?? "gpt-5-codex",
      sandboxMode: "read-only",
      approvalPolicy: "never",
      networkAccessEnabled: false,
      skipGitRepoCheck: true,
      workingDirectory: this.opts.workingDirectory ?? process.cwd(),
    };
  }

  private buildSafeEnv(): Record<string, string> {
    // Default: prefer ChatGPT subscription. Strip OPENAI_API_KEY from the
    // child's environment unless the operator opted in.
    const allowApiKey = process.env.CARENOTE_CODEX_ALLOW_API_KEY === "1";
    const env: Record<string, string> = {};
    for (const [k, v] of Object.entries(process.env)) {
      if (v === undefined) continue;
      if (k === "OPENAI_API_KEY" && !allowApiKey) continue;
      env[k] = v;
    }
    return env;
  }
}

function detectAuthMode(): CodexAuthMode {
  const authPath = join(homedir(), ".codex", "auth.json");
  if (existsSync(authPath)) return "chatgpt_subscription";
  if (process.env.CARENOTE_CODEX_ALLOW_API_KEY === "1" && process.env.OPENAI_API_KEY) {
    return "api_key";
  }
  return "unknown";
}

function buildUserMessage(input: CodexAgentRunInput): string {
  // We send a structured but plain-text envelope; Codex parses it as a
  // single user message. The role's persona / rules are loaded onto the
  // thread separately (first-turn instructions or custom-agent TOML), so
  // we do not repeat them here.
  const lines: string[] = [];
  lines.push("<event_kind>analyze_turn</event_kind>");
  lines.push(`<visit_id>${input.visit_id}</visit_id>`);
  lines.push(`<schema_name>${input.expected_output_schema_name}</schema_name>`);
  lines.push(`<schema_version>${input.schema_version}</schema_version>`);
  lines.push(`<prompt_version>${input.prompt_version}</prompt_version>`);
  lines.push(`<role>${input.role}</role>`);
  lines.push("");
  lines.push("<instructions>");
  lines.push(input.instructions.trim());
  lines.push("</instructions>");
  lines.push("");
  lines.push("<event>");
  lines.push(JSON.stringify(input.event, null, 2));
  lines.push("</event>");
  lines.push("");
  lines.push("<visit_state_snapshot>");
  lines.push(JSON.stringify(input.visit_state_snapshot, null, 2));
  lines.push("</visit_state_snapshot>");
  if (input.memory_context && input.memory_context.length > 0) {
    lines.push("");
    lines.push("<memory_context>");
    lines.push(JSON.stringify(input.memory_context, null, 2));
    lines.push("</memory_context>");
  }
  lines.push("");
  lines.push("Return JSON only.");
  return lines.join("\n");
}
