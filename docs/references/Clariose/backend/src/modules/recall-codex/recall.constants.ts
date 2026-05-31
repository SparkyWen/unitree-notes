// recall-codex — knob centre. Tunable via env without code change. See
// docs/design/09_codex_memory_recall_design.md §3.4 / §6 for the rationale
// behind every value here.

import { homedir } from "node:os";
import { join } from "node:path";

/** Filesystem root for per-user memory workspaces. Each user gets a
 *  subdirectory `<MEMORY_ROOT>/<recallNamespace>/`. */
export const MEMORY_ROOT_DEFAULT = join(homedir(), ".zai", "memories");

// Model names are intentionally NOT pinned here. With ChatGPT-account auth
// (the default — see RecallCoordinatorService.safeEnv), the only models the
// codex CLI accepts are the ones tied to the account; passing `--model` with
// anything else returns a 400 "model is not supported when using Codex with
// a ChatGPT account". Letting codex pick its built-in default is the only
// reliable path. Override via `RECALL_*_MODEL` env only if you also set
// `RECALL_CODEX_ALLOW_API_KEY=1` and have OPENAI_API_KEY in scope.
export const RECALL_COORDINATOR_MODEL_DEFAULT = "";
export const RECALL_PHASE1_MODEL_DEFAULT = "";
export const RECALL_PHASE2_MODEL_DEFAULT = "";

// Codex's bundled bwrap sandbox needs unprivileged user namespaces. On
// Ubuntu 24.04 this is gated by `kernel.apparmor_restrict_unprivileged_userns=1`,
// and bwrap fails with "loopback: Failed RTM_NEWADDR: Operation not permitted"
// — every shell call the model issues then dies before running. The recall
// coordinator's defenses-in-depth (cwd-confined per-user namespace dir,
// stripped OPENAI_API_KEY, read-only system prompt, 25s wall-clock cap) make
// it acceptable to bypass codex's sandbox on hosts where bwrap is unusable.
// Set RECALL_CODEX_BYPASS_SANDBOX=0 to keep the kernel sandbox (only works
// after `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`).
export const RECALL_CODEX_BYPASS_SANDBOX_DEFAULT = true;

/** Per-turn shell-call cap. Codex sandbox honours this server-side; we also
 *  remind the model in the read_path prompt. */
export const RECALL_SHELL_MAX_CALLS = 30;

/** Wall-clock budget for one coordinator turn. Anything longer is killed
 *  and surfaced to the SSE channel as a timeout error. Override with the
 *  RECALL_TURN_TIMEOUT_MS env var. The default is generous because a single
 *  turn may chain rg/sed reads AND a `web_search` call (each round-trip is
 *  ~1–3s), and the 25s cap we shipped first was failing real prompts. */
export const RECALL_TURN_TIMEOUT_MS_DEFAULT = 120_000;

/** Whether the coordinator turns on codex's native `web_search` tool
 *  (`-c tools.web_search=true`). When on, the model can answer questions
 *  whose answer isn't in the user's memories — useful for "search the web
 *  for X and combine with my notes" prompts. Override with
 *  RECALL_WEB_SEARCH_ENABLED=0 to keep the runtime fully offline. */
export const RECALL_WEB_SEARCH_ENABLED_DEFAULT = true;

/** Per-day cost ceiling per user. Bumped only when codex usage events
 *  arrive; refusal is at the controller, not inside the runtime. */
export const RECALL_DAILY_CAP_USD = 5.0;

/** Max upload size per note. Matches the Qagent value — the front-end
 *  rejects anything larger client-side too. */
export const NOTE_MAX_BYTES = 2 * 1024 * 1024;

/** Allowed note extensions. */
export const NOTE_ALLOWED_KINDS = ["md", "txt", "jsonl"] as const;
export type NoteKind = (typeof NOTE_ALLOWED_KINDS)[number];

/** Minimum hours a session must be idle before Phase-1 will pick it up.
 *  Mirrors Codex source's `memories.min_rollout_idle_hours = 6`. */
export const PHASE1_MIN_IDLE_HOURS = 6;

/** Cap on how many sessions Phase-1 will claim per cron firing. Mirrors
 *  Codex source's `memories.max_rollouts_per_startup = 16`. */
export const PHASE1_MAX_PER_RUN = 16;

/** Max age of an eligible rollout. Older sessions are skipped, mirroring
 *  Codex source's `memories.max_rollout_age_days = 30`. */
export const PHASE1_MAX_ROLLOUT_AGE_DAYS = 30;

/** Lease lifetime for a Phase-1 worker on a single job. Stale leases
 *  (older than this) are reclaimable by the next worker. */
export const PHASE1_LEASE_MS = 5 * 60 * 1000;

/** Phase-1 max attempts before marking a job failed. */
export const PHASE1_MAX_ATTEMPTS = 5;

/** Phase-2 lock lifetime. Single global lock per user — only one
 *  consolidation may write the workspace at a time. */
export const PHASE2_LOCK_MS = 15 * 60 * 1000;

/** Cap on stage-1 outputs Phase-2 will consider in one consolidation run.
 *  Matches Codex's `memories.max_raw_memories_for_consolidation = 256`. */
export const PHASE2_MAX_RAW_MEMORIES = 256;

/** Stage-1 outputs unused for more than this are excluded from
 *  consolidation. */
export const PHASE2_MAX_UNUSED_DAYS = 30;

/** When `RECALL_PHASE2_DRY_RUN` is on, Phase-2 writes to `<root>/.dryrun/`
 *  instead of the live workspace. Default behaviour for the first two
 *  rollout weeks per the design doc §9.6. */
export const PHASE2_DRY_RUN_DIRNAME = ".dryrun";

/** Baseline directory used by Phase-2 to compute workspace diffs. */
export const PHASE2_BASELINE_DIRNAME = ".baseline";

/** Cron expression for the Phase-1 scheduler. 03:15 UTC daily. */
export const RECALL_CRON_EXPR = "15 3 * * *";
