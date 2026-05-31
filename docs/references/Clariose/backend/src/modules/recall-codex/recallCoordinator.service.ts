// RecallCoordinatorService — spawns the codex CLI in read-only sandbox at
// the user's memories root and streams JSONL events back to the SSE
// channel via an EventEmitter. This deliberately does NOT reuse the
// existing CodexCliRuntime: that runtime is structured around JSON-schema
// agent outputs (carenote analysis turns); this coordinator returns prose.
//
// Hard-coded invariants the caller cannot override:
//   - sandbox-mode = read-only
//   - approval-policy = never
//   - --skip-git-repo-check
//   - cwd = memoriesRoot (path-confined)
//   - shell allowlist enforced by the read_path.md system prompt
//   - per-turn wall-clock cap = RECALL_TURN_TIMEOUT_MS env (default 120s)
//   - `web_search` tool toggled via RECALL_WEB_SEARCH_ENABLED (default on)

import { Injectable, Logger, ServiceUnavailableException } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { ChildProcess, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { FilesystemBootstrapper } from "./filesystemBootstrapper";
import { RecallSessionStore } from "./recallSession.store";
import { buildReadPathPrompt } from "./templates/readPath";
import {
  RECALL_CODEX_BYPASS_SANDBOX_DEFAULT,
  RECALL_COORDINATOR_MODEL_DEFAULT,
  RECALL_TURN_TIMEOUT_MS_DEFAULT,
  RECALL_WEB_SEARCH_ENABLED_DEFAULT,
} from "./recall.constants";
import type {
  RecallCitationView,
  RecallSseEvent,
  RecallToolCall,
  RecallUsage,
} from "./recall.types";

/** One in-flight turn. Held in a per-user map so abort() can SIGTERM. */
type RunningTurn = {
  child: ChildProcess;
  killed: boolean;
};

@Injectable()
export class RecallCoordinatorService {
  private readonly logger = new Logger("RecallCoordinator");
  /** Fan-out channel for SSE subscribers, keyed by sessionId. */
  private readonly emitters = new Map<string, EventEmitter>();
  /** In-flight runs, keyed by sessionId. */
  private readonly running = new Map<string, RunningTurn>();

  constructor(
    private readonly cfg: ConfigService,
    private readonly bootstrapper: FilesystemBootstrapper,
    private readonly store: RecallSessionStore,
  ) {}

  /** Subscribe to a session's SSE stream. Returns an unsubscribe fn. */
  subscribe(sessionId: string, on: (e: RecallSseEvent) => void): () => void {
    const emitter = this.ensureEmitter(sessionId);
    emitter.on("event", on);
    return () => emitter.off("event", on);
  }

  /** Whether the codex binary is available. Used by the chat controller to
   *  return a friendly 503 when it isn't. */
  async healthCheck(): Promise<{ ok: boolean; details?: string }> {
    const binary = this.binary();
    return new Promise((resolve) => {
      const child = spawn(binary, ["--version"], { env: this.safeEnv() });
      let stderr = "";
      child.stderr.on("data", (b) => { stderr += b.toString("utf8"); });
      child.on("close", (code) => {
        if (code === 0) resolve({ ok: true });
        else resolve({ ok: false, details: stderr || `exit ${code}` });
      });
      child.on("error", (err) => resolve({ ok: false, details: err.message }));
    });
  }

  /** Drive one user turn against the coordinator. Persists the user message,
   *  spawns codex, streams JSONL events to subscribers, persists the
   *  assistant message + citations + usage when the turn completes. */
  async runTurn(args: {
    userId: string;
    sessionId: string;
    prompt: string;
  }): Promise<{ messageId: string }> {
    const health = await this.healthCheck();
    if (!health.ok) {
      throw new ServiceUnavailableException(`codex unavailable: ${health.details ?? ""}`);
    }

    const { root } = await this.bootstrapper.ensure(args.userId);
    const emitter = this.ensureEmitter(args.sessionId);

    await this.store.appendUserMessage(args.sessionId, args.prompt);
    const existingThread = await this.store.getCodexThreadId(args.sessionId);

    const userMessage = wrapUserMessage(args.prompt, existingThread != null);
    // The codex CLI's flag set differs between `exec` and `exec resume`:
    //   - `exec resume` does NOT accept `--sandbox <mode>` or `--cd` (Clap
    //     rejects them); the resumed session keeps the cwd and policy from
    //     its first turn… EXCEPT the policy is silently re-derived per-turn,
    //     so we must re-pass `--dangerously-bypass-approvals-and-sandbox`
    //     on resume too or the second turn falls back to bwrap and dies on
    //     hosts where bwrap is unusable.
    //   - `exec` accepts the full set and we want it all on the first turn.
    // Branch carefully — getting this wrong surfaces as either
    // "unexpected argument '--sandbox' found" or
    // "bwrap: loopback: Failed RTM_NEWADDR" on every follow-up turn.
    const baseArgs: string[] = ["exec"];
    // Always-on config overrides — must come BEFORE the `resume` subcommand
    // (resume is a subcommand of exec, so positional args after it are
    // forwarded to the resume sub-parser, which doesn't know `-c`).
    const configOverrides = this.configOverrides();
    if (existingThread) {
      baseArgs.push(...configOverrides);
      baseArgs.push("resume", existingThread);
      baseArgs.push("--json", "--skip-git-repo-check");
      if (this.bypassSandbox()) {
        baseArgs.push("--dangerously-bypass-approvals-and-sandbox");
      }
    } else {
      baseArgs.push(
        ...configOverrides,
        "--json",
        "--skip-git-repo-check",
        ...this.sandboxArgs(),
        "--cd", root,
      );
    }
    const model = this.cfg.get<string>("RECALL_COORDINATOR_MODEL")
      ?? RECALL_COORDINATOR_MODEL_DEFAULT;
    if (model) baseArgs.push("--model", model);
    baseArgs.push("-"); // prompt from stdin

    const systemPrompt = buildReadPathPrompt({
      memoriesRoot: root,
      notesRelPath: "notes",
      rolloutSummariesRelPath: "rollout_summaries",
      skillsRelPath: "skills",
    });

    const stdinPayload = `${systemPrompt}\n\n---\n\n${userMessage}\n`;

    const startedAt = Date.now();
    emitter.emit("event", {
      type: "session_started",
      sessionId: args.sessionId,
      codexThreadId: existingThread,
      timestamp: new Date().toISOString(),
    } satisfies RecallSseEvent);

    const child = spawn(this.binary(), baseArgs, {
      env: this.safeEnv(),
      stdio: ["pipe", "pipe", "pipe"],
      // Pin the child cwd to the user's namespace dir even on resume. Without
      // this codex inherits the backend's cwd (e.g. /home/ubuntu/Zai), which
      // bwrap then refuses to add to the sandbox FS allowlist with
      // "Unable to add filesystem: <illegal path>".
      cwd: root,
    });
    this.running.set(args.sessionId, { child, killed: false });

    const turnTimeoutMs = this.turnTimeoutMs();
    const killer = setTimeout(() => {
      const slot = this.running.get(args.sessionId);
      if (!slot) return;
      slot.killed = true;
      try { child.kill("SIGKILL"); } catch { /* ignore */ }
    }, turnTimeoutMs);

    let stdoutBuf = "";
    let stderrBuf = "";
    let assistantText = "";
    let threadId = existingThread;
    let usage: RecallUsage | undefined;
    const toolCalls: RecallToolCall[] = [];
    /** Per-shell-call accumulators keyed by call id. */
    const inFlightShell = new Map<string, { command: string; startedMs: number }>();

    child.stdout.on("data", (b) => {
      stdoutBuf += b.toString("utf8");
      // Flush complete lines.
      let nl: number;
      while ((nl = stdoutBuf.indexOf("\n")) >= 0) {
        const line = stdoutBuf.slice(0, nl).trim();
        stdoutBuf = stdoutBuf.slice(nl + 1);
        if (!line) continue;
        try {
          const ev = JSON.parse(line) as Record<string, unknown>;
          this.handleEvent(args.sessionId, ev, {
            onAssistantDelta: (delta) => { assistantText += delta; },
            // codex `--json` sometimes only emits `item.completed` for short
            // turns (no preceding `item.delta` events). Without this guard
            // the SSE channel sees zero `message_delta` frames and the UI
            // jumps straight from blank to the full message at `done` time —
            // exactly the "all at once" symptom. Fan out the missing tail
            // as one final `message_delta` before locking in the text.
            onAssistantFinal: (text) => {
              if (text.length > assistantText.length) {
                const tail = text.slice(assistantText.length);
                emitter.emit("event", {
                  type: "message_delta",
                  sessionId: args.sessionId,
                  delta: tail,
                  timestamp: new Date().toISOString(),
                } satisfies RecallSseEvent);
              }
              assistantText = text;
            },
            onThreadStarted: (tid) => { threadId = tid; },
            onShellStart: (id, cmd) => {
              inFlightShell.set(id, { command: cmd, startedMs: Date.now() });
            },
            onShellEnd: (id, exit, snippet) => {
              const start = inFlightShell.get(id);
              const cmd = start?.command ?? "";
              const durationMs = start ? Date.now() - start.startedMs : undefined;
              inFlightShell.delete(id);
              toolCalls.push({ command: cmd, exit, snippet, durationMs });
            },
            onUsage: (u) => { usage = u; },
          });
        } catch {
          /* non-json log line — skip */
        }
      }
    });
    child.stderr.on("data", (b) => { stderrBuf += b.toString("utf8"); });
    child.stdin.write(stdinPayload);
    child.stdin.end();

    const exitCode: number | null = await new Promise((resolve) => {
      child.on("close", (code) => resolve(code));
      child.on("error", () => resolve(null));
    });
    clearTimeout(killer);
    const slot = this.running.get(args.sessionId);
    this.running.delete(args.sessionId);

    const durationMs = Date.now() - startedAt;
    if (usage && usage.durationMs == null) usage.durationMs = durationMs;

    if (slot?.killed) {
      const ev: RecallSseEvent = {
        type: "error",
        sessionId: args.sessionId,
        code: "timeout",
        message: `coordinator killed after ${turnTimeoutMs}ms`,
        timestamp: new Date().toISOString(),
      };
      emitter.emit("event", ev);
      // Do NOT persist threadId on a killed turn — codex may not have
      // finished writing its rollout file, and the next `exec resume <id>`
      // will fail with "thread … not found". Cheaper to start a fresh
      // codex thread than to inherit a half-written one.
      const { messageId } = await this.store.appendAssistantMessage(
        args.sessionId,
        `[error] coordinator timed out after ${turnTimeoutMs}ms`,
        { codexThreadId: undefined, usage, toolCalls },
      );
      return { messageId };
    }

    if (exitCode !== 0 || !assistantText) {
      const message = stderrBuf.trim().slice(0, 500) || `codex exec exited ${exitCode}`;
      const ev: RecallSseEvent = {
        type: "error",
        sessionId: args.sessionId,
        code: "codex_failed",
        message,
        timestamp: new Date().toISOString(),
      };
      emitter.emit("event", ev);
      // Same rationale as the timeout branch — see above.
      const { messageId } = await this.store.appendAssistantMessage(
        args.sessionId,
        `[error] ${message}`,
        { codexThreadId: undefined, usage, toolCalls },
      );
      return { messageId };
    }

    const citations = parseCitations(assistantText);
    if (citations.length) {
      for (const c of citations) {
        emitter.emit("event", {
          type: "citation",
          sessionId: args.sessionId,
          relPath: c.relPath,
          startLine: c.startLine,
          endLine: c.endLine,
          excerpt: c.excerpt,
          timestamp: new Date().toISOString(),
        } satisfies RecallSseEvent);
      }
    }

    const { messageId } = await this.store.appendAssistantMessage(
      args.sessionId,
      assistantText,
      { codexThreadId: threadId, usage, toolCalls, citations },
    );

    emitter.emit("event", {
      type: "done",
      sessionId: args.sessionId,
      messageId,
      timestamp: new Date().toISOString(),
    } satisfies RecallSseEvent);

    return { messageId };
  }

  /** SIGTERM the in-flight coordinator for a session, if any. */
  abort(sessionId: string): boolean {
    const slot = this.running.get(sessionId);
    if (!slot) return false;
    slot.killed = true;
    try { slot.child.kill("SIGTERM"); } catch { /* ignore */ }
    return true;
  }

  // ─── helpers ────────────────────────────────────────────────────────────

  private ensureEmitter(sessionId: string): EventEmitter {
    let emitter = this.emitters.get(sessionId);
    if (!emitter) {
      emitter = new EventEmitter();
      // Many SSE subscribers may attach over a session's life; raise the
      // default cap so we don't get warnings on a busy chat.
      emitter.setMaxListeners(64);
      this.emitters.set(sessionId, emitter);
    }
    return emitter;
  }

  private binary(): string {
    return this.cfg.get<string>("RECALL_CODEX_BINARY") ?? "codex";
  }

  /** Whether to bypass codex's bundled bwrap sandbox. On hosts where bwrap
   *  is unusable (Ubuntu 24.04 with apparmor_restrict_unprivileged_userns=1)
   *  this must be true — see recall.constants for the safety argument. Set
   *  RECALL_CODEX_BYPASS_SANDBOX=0 to force the kernel sandbox back on. */
  private bypassSandbox(): boolean {
    const raw = this.cfg.get<string>("RECALL_CODEX_BYPASS_SANDBOX");
    if (raw == null) return RECALL_CODEX_BYPASS_SANDBOX_DEFAULT;
    return raw !== "0" && raw.toLowerCase() !== "false";
  }

  /** Sandbox flags for the FIRST turn of a session. */
  private sandboxArgs(): string[] {
    return this.bypassSandbox()
      ? ["--dangerously-bypass-approvals-and-sandbox"]
      : ["--sandbox", "read-only"];
  }

  /** Always-on `-c key=value` overrides. Keep this list deliberately tiny;
   *  every flip here is a global behavior change. */
  private configOverrides(): string[] {
    const out: string[] = [];
    if (this.webSearchEnabled()) {
      // codex's `--search` flag only exists on the top-level invocation;
      // `exec` rejects it. The same toggle is exposed through this config
      // key, which works on `exec` AND `exec resume`.
      out.push("-c", "tools.web_search=true");
    }
    return out;
  }

  private webSearchEnabled(): boolean {
    const raw = this.cfg.get<string>("RECALL_WEB_SEARCH_ENABLED");
    if (raw == null) return RECALL_WEB_SEARCH_ENABLED_DEFAULT;
    return raw !== "0" && raw.toLowerCase() !== "false";
  }

  private turnTimeoutMs(): number {
    const raw = this.cfg.get<string>("RECALL_TURN_TIMEOUT_MS");
    if (raw == null) return RECALL_TURN_TIMEOUT_MS_DEFAULT;
    const n = Number.parseInt(raw, 10);
    if (!Number.isFinite(n) || n <= 0) return RECALL_TURN_TIMEOUT_MS_DEFAULT;
    return n;
  }

  private safeEnv(): NodeJS.ProcessEnv {
    const allowApiKey = this.cfg.get<string>("RECALL_CODEX_ALLOW_API_KEY") === "1";
    if (allowApiKey) return process.env;
    // Strip the API key so codex prefers the chatgpt subscription auth at
    // ~/.codex/auth.json (matches carenote/codex-harness convention).
    const { OPENAI_API_KEY: _strip, ...rest } = process.env;
    return rest;
  }

  /** Translate one codex JSONL event into an SSE event + side effects. */
  private handleEvent(
    sessionId: string,
    ev: Record<string, unknown>,
    cbs: {
      onAssistantDelta: (delta: string) => void;
      onAssistantFinal: (text: string) => void;
      onThreadStarted: (id: string) => void;
      onShellStart: (id: string, command: string) => void;
      onShellEnd: (id: string, exit: number | null, snippet: string) => void;
      onUsage: (usage: RecallUsage) => void;
    },
  ): void {
    const emitter = this.ensureEmitter(sessionId);
    const t = String(ev.type ?? "");
    if (t === "thread.started") {
      const tid = String((ev as { thread_id?: string }).thread_id ?? "");
      if (tid) cbs.onThreadStarted(tid);
      return;
    }
    if (t === "item.delta") {
      const item = (ev as { item?: { type?: string; delta?: string } }).item;
      if (item?.type === "agent_message" && item.delta) {
        cbs.onAssistantDelta(item.delta);
        emitter.emit("event", {
          type: "message_delta",
          sessionId,
          delta: item.delta,
          timestamp: new Date().toISOString(),
        } satisfies RecallSseEvent);
      }
      return;
    }
    if (t === "item.completed") {
      const item = (ev as {
        item?: { type?: string; text?: string; id?: string; command?: string; exit_code?: number; output?: string };
      }).item;
      if (!item) return;
      if (item.type === "agent_message" && typeof item.text === "string") {
        cbs.onAssistantFinal(item.text);
        return;
      }
      if (item.type === "command_execution" || item.type === "shell") {
        const id = String(item.id ?? randomUUID());
        const command = String(item.command ?? "");
        const exit = typeof item.exit_code === "number" ? item.exit_code : null;
        const snippet = String(item.output ?? "").slice(0, 600);
        cbs.onShellEnd(id, exit, snippet);
        emitter.emit("event", {
          type: "tool_result",
          sessionId,
          command,
          exit,
          snippet,
          timestamp: new Date().toISOString(),
        } satisfies RecallSseEvent);
      }
      return;
    }
    if (t === "shell.start" || t === "command_execution.start") {
      const id = String((ev as { id?: string }).id ?? randomUUID());
      const command = String((ev as { command?: string }).command ?? "");
      cbs.onShellStart(id, command);
      emitter.emit("event", {
        type: "tool_call",
        sessionId,
        command,
        timestamp: new Date().toISOString(),
      } satisfies RecallSseEvent);
      return;
    }
    if (t === "turn.completed") {
      const u = (ev as { usage?: Record<string, number> }).usage ?? {};
      const usage: RecallUsage = {
        inputTokens: numOrUndef(u.input_tokens),
        outputTokens: numOrUndef(u.output_tokens),
        cacheReadTokens: numOrUndef(u.cached_input_tokens),
        cacheCreationTokens: numOrUndef(u.cache_creation_input_tokens),
        totalTokens: numOrUndef(u.total_tokens),
      };
      const inputSide = (usage.inputTokens ?? 0) + (usage.cacheReadTokens ?? 0) + (usage.cacheCreationTokens ?? 0);
      usage.cacheHitRate = inputSide > 0
        ? ((usage.cacheReadTokens ?? 0) + (usage.cacheCreationTokens ?? 0)) / inputSide
        : null;
      cbs.onUsage(usage);
      emitter.emit("event", {
        type: "usage",
        sessionId,
        totalTokens: usage.totalTokens,
        cacheHitRate: usage.cacheHitRate,
        durationMs: usage.durationMs,
        timestamp: new Date().toISOString(),
      } satisfies RecallSseEvent);
    }
  }
}

// ─── pure helpers ────────────────────────────────────────────────────────

function numOrUndef(n: number | undefined): number | undefined {
  if (typeof n === "number" && Number.isFinite(n)) return n;
  return undefined;
}

function wrapUserMessage(prompt: string, isResume: boolean): string {
  if (isResume) {
    return `[resume of recall session; earlier turns are above]\n\n${prompt}`;
  }
  return prompt;
}

/** Find `<file>:<line>` or `<file>:<startLine>-<endLine>` patterns in the
 *  assistant text. We're conservative: only match paths that look like
 *  one of the known memory layout files (no absolute paths, no weird
 *  characters). False negatives are fine; false positives would surface
 *  bogus citations in the UI. */
function parseCitations(text: string): RecallCitationView[] {
  const out: RecallCitationView[] = [];
  const re = /(?:^|\s|\(|\[|`)([A-Za-z0-9_./\-一-鿿]+\.(?:md|txt|jsonl)):(\d+)(?:-(\d+))?/g;
  const seen = new Set<string>();
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const relPath = m[1];
    if (relPath.startsWith("/") || relPath.includes("..")) continue;
    const startLine = parseInt(m[2], 10);
    const endLine = m[3] ? parseInt(m[3], 10) : undefined;
    const key = `${relPath}:${startLine}-${endLine ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ relPath, startLine, endLine });
  }
  return out;
}

// Keep a reference to homedir/join/existsSync so a future refactor that
// wants to also probe for ~/.codex/auth.json before spawning has them.
void homedir;
void join;
void existsSync;
