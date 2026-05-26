// codexRuntimeFactory — selects the runtime to use at startup.
//
// Selection order (overridable by CARENOTE_CODEX_RUNTIME):
//   1. codex-sdk if @openai/codex-sdk resolves AND `codex` CLI is on PATH
//      AND auth is configured (subscription auth.json or
//      CARENOTE_CODEX_ALLOW_API_KEY=1 + OPENAI_API_KEY).
//   2. codex-cli if `codex` is on PATH.
//   3. stub.
//
// codex-app-server is never auto-selected; ask for it explicitly.

import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import type { CodexRuntime, CodexRuntimeName } from "./codexRuntime";
import { CodexSdkRuntime } from "./codexSdkRuntime";
import { CodexCliRuntime } from "./codexCliRuntime";
import { CodexAppServerRuntime } from "./codexAppServerRuntime";
import { StubRuntime } from "./stubRuntime";

import { spawnSync } from "node:child_process";

export type CodexRuntimeFactoryOptions = {
  workingDirectory?: string;
  defaultModel?: string;
  /** Force a runtime regardless of detection. */
  force?: CodexRuntimeName;
  /** Debug-artifact directory passed to runtimes that support it (codex-cli). */
  debugDir?: string;
};

export type CodexRuntimeSelection = {
  runtime: CodexRuntime;
  detected: {
    has_sdk: boolean;
    has_cli: boolean;
    has_subscription: boolean;
    has_api_key_opt_in: boolean;
  };
  reason: string;
};

export async function createCodexRuntime(
  opts: CodexRuntimeFactoryOptions = {},
): Promise<CodexRuntimeSelection> {
  const force =
    opts.force ??
    (process.env.CARENOTE_CODEX_RUNTIME as CodexRuntimeName | undefined);

  const detected = {
    has_sdk: await detectSdk(),
    has_cli: detectCli(),
    has_subscription: existsSync(join(homedir(), ".codex", "auth.json")),
    has_api_key_opt_in:
      process.env.CARENOTE_CODEX_ALLOW_API_KEY === "1" &&
      !!process.env.OPENAI_API_KEY,
  };

  if (force === "stub") {
    return {
      runtime: new StubRuntime(),
      detected,
      reason: "forced via env to stub",
    };
  }

  if (force === "codex-app-server") {
    return {
      runtime: new CodexAppServerRuntime(),
      detected,
      reason: "forced via env to codex-app-server (not implemented in MVP)",
    };
  }

  const authOk = detected.has_subscription || detected.has_api_key_opt_in;

  if (force === "codex-sdk" || (!force && detected.has_sdk && detected.has_cli && authOk)) {
    return {
      runtime: new CodexSdkRuntime({
        workingDirectory: opts.workingDirectory,
        defaultModel: opts.defaultModel,
      }),
      detected,
      reason: force ? "forced via env to codex-sdk" : "auto-selected codex-sdk",
    };
  }

  if (force === "codex-cli" || (!force && detected.has_cli && authOk)) {
    return {
      runtime: new CodexCliRuntime({
        defaultModel: opts.defaultModel,
        workingDirectory: opts.workingDirectory,
        debugDir: opts.debugDir,
      }),
      detected,
      reason: force ? "forced via env to codex-cli" : "auto-selected codex-cli (sdk not available)",
    };
  }

  return {
    runtime: new StubRuntime(),
    detected,
    reason:
      "no Codex runtime available (sdk:" +
      detected.has_sdk +
      ", cli:" +
      detected.has_cli +
      ", auth:" +
      authOk +
      ") — falling back to stub. Run `codex login --device-auth` to enable subscription auth.",
  };
}

async function detectSdk(): Promise<boolean> {
  try {
    // Use Function('require') to avoid TypeScript trying to resolve the
    // module at compile time — the SDK is an optional runtime dependency.
    const req = Function("name", "return require(name)") as (n: string) => unknown;
    req("@openai/codex-sdk");
    return true;
  } catch {
    return false;
  }
}

function detectCli(): boolean {
  try {
    const r = spawnSync("codex", ["--version"], { encoding: "utf8" });
    return r.status === 0;
  } catch {
    return false;
  }
}
