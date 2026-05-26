// CodexOutputParser — extract a JSON payload from raw Codex output.
//
// Codex's `--output-schema` doesn't always make the model emit pure JSON.
// In practice we see four shapes in the wild:
//   1. pure JSON (the happy path)
//   2. a fenced ```json ... ``` block
//   3. a fenced ``` block (no language tag)
//   4. prose with one or more JSON objects embedded
// We try them in order. If everything fails we attempt a single
// "minimal repair" pass (strip trailing commas, normalise smart quotes)
// before giving up with an explicit error that includes a redacted
// preview so callers can log it.

export type ParseSource = "pure" | "fenced" | "extracted" | "repaired";

export type ParseResult =
  | { ok: true; value: unknown; cleaned: string; source: ParseSource }
  | { ok: false; error: string; cleaned: string; preview: string };

const FENCE_RE = /```(?:json|JSON)?\s*([\s\S]*?)\s*```/;

export function stripFences(raw: string): string {
  const trimmed = raw.trim();
  // Whole string is a fence:
  const wholeFence = /^```(?:json|JSON)?\s*([\s\S]*?)\s*```$/.exec(trimmed);
  if (wholeFence) return wholeFence[1]!.trim();
  return trimmed;
}

function tryParse(s: string): { ok: true; value: unknown } | { ok: false } {
  try {
    return { ok: true, value: JSON.parse(s) };
  } catch {
    return { ok: false };
  }
}

/**
 * Walk through the string finding balanced `{...}` and `[...]` regions,
 * trying to parse each. Returns the first that parses, or undefined.
 */
function extractFirstJson(input: string): string | undefined {
  const opens = ["{", "["];
  const close = { "{": "}", "[": "]" } as Record<string, string>;
  for (let i = 0; i < input.length; i++) {
    const c = input[i]!;
    if (!opens.includes(c)) continue;
    const want = close[c]!;
    let depth = 0;
    let inStr = false;
    let escape = false;
    for (let j = i; j < input.length; j++) {
      const ch = input[j]!;
      if (escape) {
        escape = false;
        continue;
      }
      if (ch === "\\") {
        escape = true;
        continue;
      }
      if (ch === '"') {
        inStr = !inStr;
        continue;
      }
      if (inStr) continue;
      if (ch === c) depth++;
      else if (ch === want) {
        depth--;
        if (depth === 0) {
          const candidate = input.slice(i, j + 1);
          const r = tryParse(candidate);
          if (r.ok) return candidate;
          break; // try a different opening position
        }
      }
    }
  }
  return undefined;
}

function minimalRepair(s: string): string {
  // Strip trailing commas before } or ] (a common LLM tic).
  let out = s.replace(/,(\s*[}\]])/g, "$1");
  // Smart quotes → straight quotes (only the truly disambiguous ones).
  out = out
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"');
  return out;
}

export function parseCodexJson(raw: string): ParseResult {
  const trimmed = raw.trim();
  const previewSrc = trimmed.length > 400 ? trimmed.slice(0, 400) + "…" : trimmed;

  if (!trimmed) {
    return { ok: false, error: "empty output", cleaned: "", preview: "" };
  }

  // 1. Pure JSON.
  {
    const r = tryParse(trimmed);
    if (r.ok) return { ok: true, value: r.value, cleaned: trimmed, source: "pure" };
  }

  // 2. Whole-string fence.
  const stripped = stripFences(trimmed);
  if (stripped !== trimmed) {
    const r = tryParse(stripped);
    if (r.ok) return { ok: true, value: r.value, cleaned: stripped, source: "fenced" };
  }

  // 3. Embedded fenced block somewhere in prose.
  const fenceMatch = FENCE_RE.exec(trimmed);
  if (fenceMatch) {
    const inner = fenceMatch[1]!.trim();
    const r = tryParse(inner);
    if (r.ok) return { ok: true, value: r.value, cleaned: inner, source: "fenced" };
  }

  // 4. First balanced JSON object/array in the text.
  const extracted = extractFirstJson(trimmed);
  if (extracted) {
    const r = tryParse(extracted);
    if (r.ok) return { ok: true, value: r.value, cleaned: extracted, source: "extracted" };
  }

  // 5. Single repair attempt over the most-promising candidate.
  const candidate = extracted ?? stripped ?? trimmed;
  const repaired = minimalRepair(candidate);
  if (repaired !== candidate) {
    const r = tryParse(repaired);
    if (r.ok) return { ok: true, value: r.value, cleaned: repaired, source: "repaired" };
  }

  return {
    ok: false,
    error:
      "could not extract JSON from Codex output (tried pure / fenced / embedded / repair)",
    cleaned: candidate,
    preview: previewSrc,
  };
}
