// Argv layout for the dream codex fork. The `codex exec resume` subcommand
// rejects `--sandbox` and `-C/--cd` (those exist only on the parent `exec`),
// so the resume path must use `-c sandbox_mode="..."` and rely on spawn's
// cwd. Regression test for "phase gather failed" (real cause: stderr
// "unexpected argument '--sandbox' found"; usage: codex exec resume --json
// --skip-git-repo-check <SESSION_ID> [PROMPT]).

import {
  buildDreamCodexArgs,
  dreamBypassSandboxDefault,
  dreamSandboxFor,
} from "../../src/modules/carenote/swarm/dream/dream.codexFork";

describe("dreamBypassSandboxDefault", () => {
  it("defaults to true when env unset", () => {
    expect(dreamBypassSandboxDefault(null)).toBe(true);
    expect(dreamBypassSandboxDefault(undefined)).toBe(true);
  });
  it("forces false on '0'/'false'/'no'", () => {
    expect(dreamBypassSandboxDefault("0")).toBe(false);
    expect(dreamBypassSandboxDefault("false")).toBe(false);
    expect(dreamBypassSandboxDefault("FALSE")).toBe(false);
    expect(dreamBypassSandboxDefault("no")).toBe(false);
  });
  it("anything else stays true", () => {
    expect(dreamBypassSandboxDefault("1")).toBe(true);
    expect(dreamBypassSandboxDefault("true")).toBe(true);
    expect(dreamBypassSandboxDefault("yes")).toBe(true);
  });
});

describe("dreamSandboxFor", () => {
  it("orient and gather are read-only", () => {
    expect(dreamSandboxFor("orient")).toBe("read-only");
    expect(dreamSandboxFor("gather")).toBe("read-only");
  });
  it("consolidate and prune are workspace-write", () => {
    expect(dreamSandboxFor("consolidate")).toBe("workspace-write");
    expect(dreamSandboxFor("prune")).toBe("workspace-write");
  });
});

describe("buildDreamCodexArgs", () => {
  const file = "/tmp/last.txt";

  it("phase=orient (no thread): uses `exec` with --sandbox read-only", () => {
    const args = buildDreamCodexArgs({
      phase: "orient",
      threadId: null,
      lastMessageFile: file,
      bypassSandbox: false,
    });
    expect(args[0]).toBe("exec");
    expect(args).not.toContain("resume");
    expect(args).toContain("--sandbox");
    const i = args.indexOf("--sandbox");
    expect(args[i + 1]).toBe("read-only");
    expect(args).toContain("--output-last-message");
    expect(args).toContain(file);
    expect(args[args.length - 1]).toBe("-");
    // resume-only flag must not leak into the non-resume path
    expect(args).not.toContain("resume");
    // -C is NEVER passed: cwd is set by spawn(), and resume rejects it.
    expect(args).not.toContain("-C");
    expect(args).not.toContain("--cd");
  });

  it("phase=gather with threadId: uses `exec resume` and -c sandbox_mode", () => {
    const args = buildDreamCodexArgs({
      phase: "gather",
      threadId: "thread-abc",
      lastMessageFile: file,
      bypassSandbox: false,
    });
    expect(args[0]).toBe("exec");
    expect(args[1]).toBe("resume");
    // The bug: --sandbox on resume is rejected by codex CLI.
    expect(args).not.toContain("--sandbox");
    // The fix: TOML config override. Ensure value is read-only for gather.
    expect(args).toContain("-c");
    const ci = args.indexOf("-c");
    expect(args[ci + 1]).toBe('sandbox_mode="read-only"');
    expect(args).toContain("--json");
    expect(args).toContain("--skip-git-repo-check");
    expect(args).toContain("--output-last-message");
    expect(args).toContain(file);
    expect(args).toContain("thread-abc");
    expect(args[args.length - 1]).toBe("-");
    expect(args).not.toContain("-C");
    expect(args).not.toContain("--cd");
  });

  it("phase=consolidate with threadId: resume + -c sandbox_mode workspace-write", () => {
    const args = buildDreamCodexArgs({
      phase: "consolidate",
      threadId: "t1",
      lastMessageFile: file,
      bypassSandbox: false,
    });
    expect(args[1]).toBe("resume");
    const ci = args.indexOf("-c");
    expect(args[ci + 1]).toBe('sandbox_mode="workspace-write"');
  });

  it("phase=prune with threadId: resume + -c sandbox_mode workspace-write", () => {
    const args = buildDreamCodexArgs({
      phase: "prune",
      threadId: "t1",
      lastMessageFile: file,
      bypassSandbox: false,
    });
    expect(args[1]).toBe("resume");
    const ci = args.indexOf("-c");
    expect(args[ci + 1]).toBe('sandbox_mode="workspace-write"');
  });

  it("phase=consolidate without a threadId: falls back to fresh exec", () => {
    // If the orient phase never produced a thread_id (e.g., codex died
    // before emitting `thread.started`), later phases must still run as
    // a fresh `exec` rather than `exec resume <null>`.
    const args = buildDreamCodexArgs({
      phase: "consolidate",
      threadId: null,
      lastMessageFile: file,
      bypassSandbox: false,
    });
    expect(args[0]).toBe("exec");
    expect(args).not.toContain("resume");
    expect(args).toContain("--sandbox");
    const i = args.indexOf("--sandbox");
    expect(args[i + 1]).toBe("workspace-write");
  });

  describe("bypassSandbox=true (default for this host)", () => {
    // Regression: with sandbox enabled but bwrap broken on the host,
    // every shell command fails before it runs, the agent gives up,
    // codex exits 0, and the runner records "phase succeeded" with
    // zero files written. Bypass replaces --sandbox with
    // --dangerously-bypass-approvals-and-sandbox so the agent's tools
    // actually execute. Same trade-off as recall-codex.

    it("phase=orient (no thread): drops --sandbox, adds bypass flag", () => {
      const args = buildDreamCodexArgs({
        phase: "orient",
        threadId: null,
        lastMessageFile: file,
        bypassSandbox: true,
      });
      expect(args[0]).toBe("exec");
      expect(args).not.toContain("resume");
      expect(args).not.toContain("--sandbox");
      expect(args).toContain("--dangerously-bypass-approvals-and-sandbox");
      expect(args[args.length - 1]).toBe("-");
    });

    it("phase=consolidate with threadId: resume + bypass flag, no -c sandbox_mode", () => {
      const args = buildDreamCodexArgs({
        phase: "consolidate",
        threadId: "t1",
        lastMessageFile: file,
        bypassSandbox: true,
      });
      expect(args[0]).toBe("exec");
      expect(args[1]).toBe("resume");
      expect(args).not.toContain("--sandbox");
      // Resume does NOT inherit the parent session's bypass flag — it
      // must be re-passed (mirrors recall-codex/recallCoordinator).
      expect(args).toContain("--dangerously-bypass-approvals-and-sandbox");
      // No -c sandbox_mode override either, since bypass overrides.
      const sandboxModeRef = args.find((a) =>
        a.startsWith?.("sandbox_mode="),
      );
      expect(sandboxModeRef).toBeUndefined();
      expect(args).toContain("t1");
      expect(args[args.length - 1]).toBe("-");
    });
  });
});
