// codexAppServerRuntime — placeholder.
//
// app-server is a JSON-RPC 2.0 protocol over stdio (or experimental
// WebSocket) used by the VS Code extension and Codex Desktop. It
// exposes richer streaming events and approval workflows. We do not
// adopt it in MVP; this stub exists so the runtime factory has a
// recognised name and so a future port has a clear target.
//
// To implement: spawn a long-running `codex app-server` subprocess,
// handshake on the protocol from
// docs/CDXLearn/openai-codex-source/codex/codex-rs/app-server-protocol,
// expose `start_thread` / `run` / `resume_thread` over the JSON-RPC
// channel.

import type { CodexAgentRole } from "../medical/medicalSchemas";
import type {
  CodexAgentRunInput,
  CodexAgentRunOutput,
  CodexAuthMode,
  CodexRuntime,
} from "./codexRuntime";

export class CodexAppServerRuntime implements CodexRuntime {
  readonly name = "codex-app-server" as const;

  async startOrResumeThread(_input: {
    team_id: string;
    role: CodexAgentRole;
    existing_thread_id?: string | null;
  }): Promise<{ thread_id: string | null }> {
    throw new Error("CodexAppServerRuntime is not implemented in MVP");
  }

  async run(_input: CodexAgentRunInput): Promise<CodexAgentRunOutput> {
    throw new Error("CodexAppServerRuntime is not implemented in MVP");
  }

  async healthCheck(): Promise<{
    ok: boolean;
    runtime: "codex-app-server";
    auth_mode?: CodexAuthMode;
    details?: string;
  }> {
    return {
      ok: false,
      runtime: "codex-app-server",
      auth_mode: "unknown",
      details: "not implemented in MVP",
    };
  }
}
