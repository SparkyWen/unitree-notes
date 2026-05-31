// Central PHI redaction helper for CareNote logs.
//
// Default behavior (production / unset env):
//  - Drop transcript text.
//  - Drop raw event bodies (delta/transcript fields).
//  - Keep structural fields: event type, item_id, visit_id, timestamps.
//
// When DEBUG_CARENOTE_PHI=true the helper passes input through unchanged so
// developers can see real transcripts during local debugging. A startup
// warning is printed by `assertPhiDebugWarningPrinted()` once per process.

const PHI_FIELDS = new Set([
  "transcript",
  "delta",
  "partial_transcript",
  "text",
  "content",
  "raw_text",
  "logprobs",
  "raw_events",
]);

export type RedactInput = unknown;

export function isPhiDebugEnabled(): boolean {
  return process.env.DEBUG_CARENOTE_PHI === "true";
}

export function redactPhi<T extends RedactInput>(input: T): T {
  if (isPhiDebugEnabled()) return input;
  return walk(input) as T;
}

function walk(value: unknown): unknown {
  if (value == null) return value;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (Array.isArray(value)) return value.map((v) => walk(v));
  if (typeof value === "object") {
    const src = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(src)) {
      if (PHI_FIELDS.has(k)) {
        if (typeof v === "string") out[k] = `[redacted:${v.length}]`;
        else if (Array.isArray(v)) out[k] = `[redacted:array(${v.length})]`;
        else if (v == null) out[k] = null;
        else out[k] = "[redacted]";
      } else {
        out[k] = walk(v);
      }
    }
    return out;
  }
  return value;
}

let warned = false;
export function assertPhiDebugWarningPrinted(logger: { warn: (m: string) => void }): void {
  if (warned) return;
  warned = true;
  if (isPhiDebugEnabled()) {
    logger.warn(
      "DEBUG_CARENOTE_PHI=true — transcript content WILL be written to logs. Local development only.",
    );
  }
}
