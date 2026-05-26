// Spawns one `codex exec` invocation against a per-user workspace.
//
// Auth/sandbox match the existing carenote codex-cli runtime:
//   - no --model (ChatGPT-account auth restricts it server-side)
//   - --skip-git-repo-check (the memory dir is not a git repo)
//   - --json (emit JSONL events on stdout)
//   - --output-last-message <file> (capture the final assistant message)
//   - sandbox depends on phase: orient/gather → "read-only";
//                                consolidate/prune → "workspace-write"
//   - cwd = workspaceRoot (set via spawn(), not -C, so it works for both
//     `exec` and `exec resume` — the latter does NOT accept -C/--cd)
//
// Phases 2-4 resume the thread captured from phase 1 via the `resume`
// subcommand, so the agent's context is shared across phases.
// `codex exec resume` does not accept `--sandbox` or `-C` (those exist
// only on the parent `exec` subcommand). For resume we pass the sandbox
// policy via `-c sandbox_mode="<mode>"` (config override), and rely on
// spawn's `cwd` for the working directory.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §7.

import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { DreamPhase } from "./dream.types";

const PER_PHASE_TIMEOUT_MS_DEFAULT = 120_000;

export interface DreamForkInput {
  phase: DreamPhase;
  prompt: string;
  workspaceRoot: string;
  /** Pass thread_id from a prior phase to resume that conversation. */
  threadId: string | null;
  abort?: AbortSignal;
}

export interface DreamForkOutput {
  exitCode: number | null;
  threadId: string | null;
  finalMessage: string;
  durationMs: number;
  /** Last ~400 chars of stderr — useful for surfacing codex CLI failures
   *  (e.g., "unexpected argument '--sandbox'") instead of a bare exit code. */
  stderrTail: string;
}

/** Sandbox policy per phase. Phases 1-2 are read-only by design (the
 *  prompt forbids writes); phases 3-4 must be able to mutate .md files. */
export function dreamSandboxFor(phase: DreamPhase): "read-only" | "workspace-write" {
  return phase === "orient" || phase === "gather" ? "read-only" : "workspace-write";
}

/** Build the argv for one phase. Pure function so the args layout (which
 *  is sensitive to which flags `codex exec resume` accepts) can be unit
 *  tested without spawning a real process.
 *
 *  `bypassSandbox` mirrors recall-codex's `RECALL_CODEX_BYPASS_SANDBOX`
 *  default (true): on hosts where `bwrap` cannot initialise (the common
 *  case in containers / WSL — every shell command fails with
 *  `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`), the
 *  `--sandbox <mode>` flag silently neutralises the agent — every Bash
 *  call fails before it runs, the agent gives up, codex exits 0, and the
 *  runner thinks the phase succeeded with zero files written. The flip
 *  side, `--dangerously-bypass-approvals-and-sandbox`, drops bwrap
 *  entirely and lets the prompt's "DO NOT edit" preamble be the only
 *  guard for the read-only phases — same trade recall-codex made. */
export function buildDreamCodexArgs(opts: {
  phase: DreamPhase;
  threadId: string | null;
  lastMessageFile: string;
  bypassSandbox: boolean;
}): string[] {
  const sandbox = dreamSandboxFor(opts.phase);
  const isResume = opts.threadId !== null && opts.phase !== "orient";
  if (isResume) {
    // `codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]`. The `resume`
    // subcommand rejects `--sandbox` and `-C`. Pass the sandbox policy
    // through the generic `-c key=value` config override; cwd is set via
    // spawn(). `-` instructs codex to read the prompt from stdin.
    //
    // Resume does NOT inherit the parent session's
    // `--dangerously-bypass-approvals-and-sandbox`, so we re-pass it
    // every phase (mirrors recall-codex/recallCoordinator.service.ts).
    const args = [
      "exec",
      "resume",
      "--json",
      "--skip-git-repo-check",
      "--output-last-message",
      opts.lastMessageFile,
    ];
    if (opts.bypassSandbox) {
      args.push("--dangerously-bypass-approvals-and-sandbox");
    } else {
      args.push("-c", `sandbox_mode="${sandbox}"`);
    }
    args.push(opts.threadId!, "-");
    return args;
  }
  // `codex exec [OPTIONS] [PROMPT]`. cwd is set via spawn() — `-C` would
  // be redundant and we keep both arg paths symmetric.
  const args = [
    "exec",
    "--json",
    "--skip-git-repo-check",
    "--output-last-message",
    opts.lastMessageFile,
  ];
  if (opts.bypassSandbox) {
    args.push("--dangerously-bypass-approvals-and-sandbox");
  } else {
    args.push("--sandbox", sandbox);
  }
  args.push("-");
  return args;
}

/** Read CARENOTE_DREAM_BYPASS_SANDBOX. Defaults to true to match
 *  recall-codex on this host (bwrap is broken). Set to "0" or "false"
 *  to force the kernel sandbox back on (useful in CI / hosts where
 *  bwrap actually works). */
export function dreamBypassSandboxDefault(
  raw: string | null | undefined,
): boolean {
  if (raw == null) return true;
  const v = raw.toLowerCase();
  return v !== "0" && v !== "false" && v !== "no";
}

@Injectable()
export class DreamCodexFork {
  private readonly logger = new Logger("DreamCodexFork");

  constructor(private readonly cfg: ConfigService) {}

  async run(input: DreamForkInput): Promise<DreamForkOutput> {
    const binary = this.cfg.get<string>("CODEX_CLI_BIN") ?? "codex";
    const timeoutMs =
      Number(this.cfg.get<string>("CARENOTE_DREAM_PHASE_TIMEOUT_MS")) ||
      PER_PHASE_TIMEOUT_MS_DEFAULT;

    const tmpDir = await mkdtemp(join(tmpdir(), "dream-out-"));
    const lastMessageFile = join(tmpDir, "last.txt");

    const bypassSandbox = dreamBypassSandboxDefault(
      this.cfg.get<string>("CARENOTE_DREAM_BYPASS_SANDBOX"),
    );
    const args = buildDreamCodexArgs({
      phase: input.phase,
      threadId: input.threadId,
      lastMessageFile,
      bypassSandbox,
    });

    const start = Date.now();
    let threadId: string | null = input.threadId ?? null;
    let exitCode: number | null = null;
    let finalMessage = "";
    const stderrBuf: string[] = [];

    try {
      const proc = spawn(binary, args, {
        cwd: input.workspaceRoot,
        env: { ...process.env },
        stdio: ["pipe", "pipe", "pipe"],
      });
      proc.stdin.write(input.prompt);
      proc.stdin.end();

      const onAbort = (): void => {
        proc.kill("SIGTERM");
      };
      input.abort?.addEventListener("abort", onAbort);

      proc.stdout.setEncoding("utf-8");
      proc.stderr.setEncoding("utf-8");
      proc.stdout.on("data", (d: string) => {
        for (const line of d.split("\n")) {
          if (!line.trim()) continue;
          try {
            const ev = JSON.parse(line);
            if (
              ev.type === "thread.started" &&
              typeof ev.thread_id === "string"
            ) {
              threadId = ev.thread_id;
            }
          } catch {
            // codex CLI mixes JSONL with non-JSON noise — ignore non-JSON lines
          }
        }
      });
      proc.stderr.on("data", (d: string) => stderrBuf.push(d));

      const timer = setTimeout(() => proc.kill("SIGTERM"), timeoutMs);

      exitCode = await new Promise<number | null>((resolveExit) => {
        proc.once("exit", (code) => {
          clearTimeout(timer);
          input.abort?.removeEventListener("abort", onAbort);
          resolveExit(code);
        });
      });

      try {
        finalMessage = await readFile(lastMessageFile, "utf-8");
      } catch {
        // last.txt not written — codex didn't reach a final assistant message
      }

      if (exitCode !== 0) {
        this.logger.warn(
          `dream phase=${input.phase} exit=${exitCode} stderr=${stderrBuf
            .join("")
            .slice(-400)}`,
        );
      } else {
        // Diagnostic for the silent-failure mode that this fork file
        // works around: codex exits 0 even when bwrap blocked every
        // command. If we ever see "loopback" / "Operation not permitted"
        // in the final message with bypass disabled, we know the host
        // changed.
        if (/bwrap|RTM_NEWADDR|Operation not permitted/.test(finalMessage)) {
          this.logger.warn(
            `dream phase=${input.phase} reported sandbox failure in final message; consider CARENOTE_DREAM_BYPASS_SANDBOX=1`,
          );
        }
      }
    } finally {
      await rm(tmpDir, { recursive: true, force: true }).catch(() => undefined);
    }

    return {
      exitCode,
      threadId,
      finalMessage,
      durationMs: Date.now() - start,
      stderrTail: stderrBuf.join("").slice(-400).trim(),
    };
  }
}
