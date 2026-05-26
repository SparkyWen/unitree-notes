// codexCliRuntime — fallback runtime that shells to `codex exec` directly.
//
// This is the recovery path when @openai/codex-sdk is unavailable. It uses
// the same auth (subscription via ~/.codex/auth.json) and sandbox semantics
// as the SDK runtime, because under the hood the SDK already shells to this
// binary.
//
// CLI semantics (verified against the installed `codex` binary):
//   codex exec [--json] [--sandbox …] [--skip-git-repo-check]
//              [--output-schema FILE] [--output-last-message FILE]
//              [-m MODEL] [-C DIR] [PROMPT|-]
//
//   codex exec resume [--json] [--last|<SESSION_ID>] [PROMPT|-]
//
// There is NO `--thread-id` flag on `codex exec`; resume requires the
// `resume` subcommand. The previous implementation passed `--thread-id`
// which made resume calls exit immediately with `unexpected argument`.
//
// JSONL events we care about:
//   { type: "thread.started", thread_id }
//   { type: "item.completed", item: { type: "agent_message", text } }
//   { type: "turn.failed", error: { message } }
//   { type: "error", message }

import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { mkdtemp, rm, writeFile, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";

import type { CodexAgentRole } from "../medical/medicalSchemas";
import type {
  CodexAgentRunInput,
  CodexAgentRunOutput,
  CodexAuthMode,
  CodexRuntime,
} from "./codexRuntime";
import { writeDebugRun, debugEnabled } from "./codexDebugCapture";

export type CodexCliRuntimeOptions = {
  binary?: string; // default: "codex"
  defaultModel?: string;
  workingDirectory?: string;
  /** When set, debug artifacts land under <debugDir>/codex-runs/. */
  debugDir?: string;
  /** Per-run timeout in ms (default 90s). */
  timeoutMs?: number;
};

export type CodexCliExtra = {
  command: string;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  events: CliEvent[];
  debug_dir?: string;
};

type CliEvent =
  | { type: "thread.started"; thread_id?: string }
  | { type: "item.completed"; item?: { type?: string; text?: string } }
  | { type: "turn.completed"; usage?: unknown }
  | { type: "turn.failed"; error?: { message?: string } }
  | { type: "error"; message?: string }
  | { type: "thread.ended" }
  | { type: string; [k: string]: unknown };

export class CodexCliRuntime implements CodexRuntime {
  readonly name = "codex-cli" as const;

  private opts: CodexCliRuntimeOptions;

  // The CLI's `codex exec resume` requires the session to exist on disk;
  // we capture the thread_id from `thread.started` on first run, but the
  // session-rollout file isn't always emitted (we already see the
  // "thread NOT found" stderr noise). To keep behaviour predictable we
  // attempt resume only when the caller hands us an existing thread_id;
  // the run manager handles fresh starts.
  constructor(opts: CodexCliRuntimeOptions = {}) {
    this.opts = opts;
  }

  /**
   * The CLI does not preallocate threads. Returning the existing id (if
   * any) preserves the run manager's persistence flow; the first real
   * run() will capture the assigned thread_id from the JSONL stream.
   */
  async startOrResumeThread(input: {
    team_id: string;
    role: CodexAgentRole;
    existing_thread_id?: string | null;
  }): Promise<{ thread_id: string | null }> {
    return { thread_id: input.existing_thread_id ?? null };
  }

  async run(input: CodexAgentRunInput): Promise<CodexAgentRunOutput & { extra?: CodexCliExtra }> {
    const tmp = await mkdtemp(join(tmpdir(), "carenote-codex-"));
    const schemaPath = join(tmp, "schema.json");
    const lastPath = join(tmp, "last.txt");
    await writeFile(
      schemaPath,
      JSON.stringify(input.expected_output_schema),
      "utf8",
    );

    const binary = this.opts.binary ?? "codex";
    const userMessage = buildUserMessage(input);
    const started_at = new Date().toISOString();
    const run_id = randomUUID();
    const timeoutMs = this.opts.timeoutMs ?? 90_000;

    // Resume vs fresh.
    const resumeId = input.thread_id ?? null;
    const baseArgs: string[] = ["exec"];
    if (resumeId) baseArgs.push("resume", resumeId);
    baseArgs.push(
      "--json",
      "--skip-git-repo-check",
      "--output-last-message",
      lastPath,
    );
    if (!resumeId) {
      baseArgs.push("--output-schema", schemaPath);
    }
    if (this.opts.defaultModel) baseArgs.push("--model", this.opts.defaultModel);
    if (this.opts.workingDirectory && !resumeId) {
      baseArgs.push("--cd", this.opts.workingDirectory);
    }
    // Read prompt from stdin.
    baseArgs.push("-");

    const command = `${binary} ${baseArgs.map(quoteArg).join(" ")}`;

    const result = await new Promise<{
      code: number | null;
      stdout: string;
      stderr: string;
    }>((resolve) => {
      const child = spawn(binary, baseArgs, {
        env: this.buildSafeEnv(),
        stdio: ["pipe", "pipe", "pipe"],
      });
      let stdout = "";
      let stderr = "";
      const killTimer = setTimeout(() => {
        try {
          child.kill("SIGKILL");
        } catch {
          /* ignore */
        }
      }, timeoutMs);

      child.stdout.on("data", (b) => {
        stdout += b.toString("utf8");
      });
      child.stderr.on("data", (b) => {
        stderr += b.toString("utf8");
      });
      child.stdin.write(userMessage);
      child.stdin.end();
      child.on("close", (code) => {
        clearTimeout(killTimer);
        resolve({ code, stdout, stderr });
      });
      child.on("error", (err) => {
        clearTimeout(killTimer);
        resolve({ code: null, stdout: "", stderr: err.message });
      });
    });

    let lastMessage = "";
    try {
      lastMessage = await readFile(lastPath, "utf8");
    } catch {
      /* ignore — file may not exist if codex bailed early */
    }
    try {
      await rm(tmp, { recursive: true, force: true });
    } catch {
      /* ignore */
    }

    const events = parseJsonl(result.stdout);
    let threadId: string | null = resumeId;
    let agentMessageText = "";
    const errorMessages: string[] = [];
    for (const ev of events) {
      if (ev.type === "thread.started" && (ev as { thread_id?: string }).thread_id) {
        threadId = (ev as { thread_id?: string }).thread_id ?? threadId;
      }
      if (
        ev.type === "item.completed" &&
        (ev as { item?: { type?: string; text?: string } }).item?.type === "agent_message"
      ) {
        const text = (ev as { item?: { text?: string } }).item?.text;
        if (text) agentMessageText = text;
      }
      if (ev.type === "turn.failed") {
        const m = (ev as { error?: { message?: string } }).error?.message;
        if (m) errorMessages.push(m);
      }
      if (ev.type === "error") {
        const m = (ev as { message?: string }).message;
        if (m) errorMessages.push(m);
      }
    }

    const raw_text = agentMessageText || lastMessage.trim();
    const exit = result.code;
    const extra: CodexCliExtra = {
      command,
      exit_code: exit,
      stdout: result.stdout,
      stderr: result.stderr,
      events,
    };

    const completed_at = new Date().toISOString();
    let out: CodexAgentRunOutput & { extra?: CodexCliExtra };
    if (exit === 0 && raw_text && errorMessages.length === 0) {
      out = {
        team_id: input.team_id,
        visit_id: input.visit_id,
        role: input.role,
        thread_id: threadId,
        run_id,
        raw_text,
        validation_status: "valid",
        started_at,
        completed_at,
        extra,
      };
    } else {
      const errs: string[] = [];
      if (exit !== 0 && exit !== null) errs.push(`codex exec exited ${exit}`);
      if (errorMessages.length > 0) errs.push(...errorMessages);
      if (!raw_text && exit === 0) errs.push("codex produced no agent_message item");
      const stderrTrim = result.stderr.trim();
      if (stderrTrim && errs.length === 0) errs.push(stderrTrim.slice(0, 500));
      out = {
        team_id: input.team_id,
        visit_id: input.visit_id,
        role: input.role,
        thread_id: threadId,
        run_id,
        raw_text,
        validation_status: "failed",
        errors: errs,
        started_at,
        completed_at,
        extra,
      };
    }

    if (debugEnabled() && this.opts.debugDir) {
      const dir = await writeDebugRun(this.opts.debugDir, {
        role: input.role,
        run_id,
        command,
        input,
        schema: input.expected_output_schema,
        stdout: result.stdout,
        stderr: result.stderr,
        raw_output: raw_text,
        result: out,
      });
      if (dir && out.extra) out.extra.debug_dir = dir;
    }

    return out;
  }

  async healthCheck(): Promise<{
    ok: boolean;
    runtime: "codex-cli";
    auth_mode?: CodexAuthMode;
    details?: string;
  }> {
    const authPath = join(homedir(), ".codex", "auth.json");
    const auth_mode: CodexAuthMode = existsSync(authPath)
      ? "chatgpt_subscription"
      : process.env.OPENAI_API_KEY
      ? "api_key"
      : "unknown";

    return new Promise((resolve) => {
      const child = spawn(this.opts.binary ?? "codex", ["--version"], {
        env: this.buildSafeEnv(),
      });
      let stderr = "";
      child.stderr.on("data", (b) => {
        stderr += b.toString("utf8");
      });
      child.on("close", (code) => {
        if (code === 0) {
          resolve({ ok: true, runtime: "codex-cli", auth_mode });
        } else {
          resolve({
            ok: false,
            runtime: "codex-cli",
            auth_mode,
            details: stderr || `codex --version exited ${code}`,
          });
        }
      });
      child.on("error", (err) => {
        resolve({
          ok: false,
          runtime: "codex-cli",
          auth_mode,
          details: err.message,
        });
      });
    });
  }

  private buildSafeEnv(): NodeJS.ProcessEnv {
    const allowApiKey = process.env.CARENOTE_CODEX_ALLOW_API_KEY === "1";
    if (allowApiKey) return process.env;
    const { OPENAI_API_KEY: _strip, ...rest } = process.env;
    return rest;
  }
}

function parseJsonl(s: string): CliEvent[] {
  const out: CliEvent[] = [];
  for (const line of s.split(/\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      out.push(JSON.parse(trimmed) as CliEvent);
    } catch {
      /* non-json log line — ignore */
    }
  }
  return out;
}

function quoteArg(a: string): string {
  if (/^[a-zA-Z0-9_./:=-]+$/.test(a)) return a;
  return `'${a.replace(/'/g, `'\\''`)}'`;
}

function buildUserMessage(input: CodexAgentRunInput): string {
  return [
    "<event_kind>analyze_turn</event_kind>",
    `<visit_id>${input.visit_id}</visit_id>`,
    `<schema_name>${input.expected_output_schema_name}</schema_name>`,
    `<schema_version>${input.schema_version}</schema_version>`,
    `<prompt_version>${input.prompt_version}</prompt_version>`,
    `<role>${input.role}</role>`,
    "",
    "<instructions>",
    input.instructions.trim(),
    "</instructions>",
    "",
    "<event>",
    JSON.stringify(input.event, null, 2),
    "</event>",
    "",
    "<visit_state_snapshot>",
    JSON.stringify(input.visit_state_snapshot, null, 2),
    "</visit_state_snapshot>",
    "",
    "Return JSON only — no Markdown fences, no prose, just the JSON object that matches the schema above.",
  ].join("\n");
}
