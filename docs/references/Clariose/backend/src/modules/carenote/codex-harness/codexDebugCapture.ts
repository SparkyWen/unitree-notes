// codexDebugCapture — write per-run debug artifacts when
// DEBUG_CARENOTE_CODEX=true, and centralize PHI redaction policy.
//
// Each run gets a directory:
//   <root>/<timestamp>-<role>-<run_id_short>/
//     command.txt
//     input.redacted.json
//     input.full.json   (only when DEBUG_CARENOTE_PHI=true)
//     stdout.txt
//     stderr.txt
//     parsed.json       (when JSON parse succeeded)
//     validation-errors.json (when schema validation failed)
//     result.json
//
// Nothing is written unless DEBUG_CARENOTE_CODEX=true. Callers should
// always be cheap when debug is off.

import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

export type CodexDebugRecord = {
  role: string;
  run_id: string;
  command?: string;
  input?: unknown;
  /** Strict JSON schema actually passed to Codex via --output-schema. */
  schema?: unknown;
  stdout?: string;
  stderr?: string;
  raw_output?: string;
  parsed_json?: unknown;
  validation_errors?: unknown;
  result?: unknown;
};

export const PREVIEW_LEN = 800;

export function debugEnabled(): boolean {
  return process.env.DEBUG_CARENOTE_CODEX === "true" ||
    process.env.DEBUG_CARENOTE_CODEX === "1";
}

export function phiAllowed(): boolean {
  return process.env.DEBUG_CARENOTE_PHI === "true" ||
    process.env.DEBUG_CARENOTE_PHI === "1";
}

/** Returns a stable preview that respects PHI redaction. */
export function preview(s: string | undefined | null, n = PREVIEW_LEN): string {
  if (!s) return "";
  if (!phiAllowed()) {
    return `[redacted; ${s.length} chars; set DEBUG_CARENOTE_PHI=true to see]`;
  }
  if (s.length <= n) return s;
  return s.slice(0, n) + `…[+${s.length - n} chars]`;
}

/** Safely-shallow redact a JSON-serializable input for logging. */
export function redactInput(value: unknown): unknown {
  if (phiAllowed()) return value;
  if (value == null) return value;
  if (typeof value !== "object") return "[redacted]";
  if (Array.isArray(value)) return `[redacted array; len=${value.length}]`;
  const obj = value as Record<string, unknown>;
  const safeKeys = new Set([
    "team_id",
    "visit_id",
    "role",
    "thread_id",
    "prompt_version",
    "schema_version",
    "expected_output_schema_name",
    "event_kind",
  ]);
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (safeKeys.has(k)) {
      out[k] = v;
    } else if (typeof v === "string") {
      out[k] = `[redacted string; ${v.length} chars]`;
    } else if (Array.isArray(v)) {
      out[k] = `[redacted array; len=${v.length}]`;
    } else if (v && typeof v === "object") {
      out[k] = "[redacted object]";
    } else {
      out[k] = v;
    }
  }
  return out;
}

export async function writeDebugRun(
  rootDir: string | undefined,
  rec: CodexDebugRecord,
): Promise<string | undefined> {
  if (!debugEnabled()) return undefined;
  if (!rootDir) return undefined;
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const short = rec.run_id.slice(0, 8);
  const dir = join(rootDir, `${ts}-${rec.role}-${short}`);
  await mkdir(dir, { recursive: true });
  const writes: Promise<unknown>[] = [];
  if (rec.command) writes.push(writeFile(join(dir, "command.txt"), rec.command, "utf8"));
  if (rec.schema !== undefined) {
    writes.push(
      writeFile(join(dir, "schema.json"), JSON.stringify(rec.schema, null, 2), "utf8"),
    );
  }
  if (rec.input !== undefined) {
    writes.push(
      writeFile(
        join(dir, "input.redacted.json"),
        JSON.stringify(redactInput(rec.input), null, 2),
        "utf8",
      ),
    );
    if (phiAllowed()) {
      writes.push(
        writeFile(join(dir, "input.full.json"), JSON.stringify(rec.input, null, 2), "utf8"),
      );
    }
  }
  if (rec.stdout !== undefined) writes.push(writeFile(join(dir, "stdout.txt"), rec.stdout, "utf8"));
  if (rec.stderr !== undefined) writes.push(writeFile(join(dir, "stderr.txt"), rec.stderr, "utf8"));
  if (rec.raw_output !== undefined) {
    writes.push(writeFile(join(dir, "raw_output.txt"), rec.raw_output, "utf8"));
  }
  if (rec.parsed_json !== undefined) {
    writes.push(
      writeFile(join(dir, "parsed.json"), JSON.stringify(rec.parsed_json, null, 2), "utf8"),
    );
  }
  if (rec.validation_errors !== undefined) {
    writes.push(
      writeFile(
        join(dir, "validation-errors.json"),
        JSON.stringify(rec.validation_errors, null, 2),
        "utf8",
      ),
    );
  }
  if (rec.result !== undefined) {
    writes.push(
      writeFile(join(dir, "result.json"), JSON.stringify(rec.result, null, 2), "utf8"),
    );
  }
  await Promise.all(writes);
  return dir;
}
