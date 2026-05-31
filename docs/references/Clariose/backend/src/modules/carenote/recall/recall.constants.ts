// CLARIOSE_V01 §4 — recall constants. Tunable via env without code change.

export const RECALL_KEY_PREFIX = "carenote:recall";

/** Manifest cache TTL in Redis. Re-scan disk after expiry. */
export const MANIFEST_CACHE_TTL_SEC = 300;

/** Per-visit cumulative byte budget. Once exceeded, prefetch returns empty
 *  with `skipped: 'visit_budget'`. Raised vs Qagent's 64KB because demo
 *  prioritizes recall quality over token thrift. */
export const MAX_VISIT_BYTES = 96 * 1024;

/** Per-file truncation. Anything over this size is sliced and marked truncated. */
export const MAX_BYTES_PER_FILE = 16 * 1024;

/** Outer race timeout for sideQuery. The LLM call inside has its own internal
 *  timeout (2000ms) — this is the safety net. */
export const SIDEQUERY_TIMEOUT_MS = 2200;

/** sideQuery model. User-specified; configurable via env so we can swap fast. */
export const SIDEQUERY_MODEL_DEFAULT = "gpt-5.4-mini-2026-03-17";

/** sideQuery output cap. We're asking for a JSON array of file paths, not prose. */
export const SIDEQUERY_MAX_OUTPUT_TOKENS = 1000;

/** Top-N selection from sideQuery. */
export const SIDEQUERY_MAX_RESULTS = 5;

/** Memory-file root on disk. Visits live under /visits/<visitId>/, users
 *  under /users/<userId>/. Codex-style file naming inside each (MEMORY.md,
 *  memory_summary.md, rollout_summaries/, skills/, read_path.md). */
export const MEMORY_ROOT_DEFAULT = "/home/ubuntu/Zai/.data/carenote/memory";

/** Visit-budget Redis key TTL. 24h covers the longest realistic visit. */
export const VISIT_BUDGET_TTL_SEC = 24 * 60 * 60;
