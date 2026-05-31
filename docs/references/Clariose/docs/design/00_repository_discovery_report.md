# 00 — Repository & Notes Discovery Report

Date: 2026-04-29
Author: CareNote architecture pass (Codex-only harness migration)

This is the Phase 0 discovery report. It precedes any design or implementation.
The goal is to capture, in one place, what already exists locally that the
CareNote Codex-only harness can build on, learn from, or must explicitly avoid
porting.

The report is based on a deep read of:

- `~/Zai/docs/openai_hackathon/Qagent` — the existing NestJS+Claude-SDK harness.
- `~/Zai/docs/openai_hackathon/docs/CCLearn/source/src` — the reference Claude
  Code CLI source.
- `~/Zai/docs/openai_hackathon/docs/CCLearn/notes/notes_integrated` — the 10
  Chinese-language design notes derived from that source.
- `~/Zai/docs/openai_hackathon/docs/CDXLearn/openai-codex-source/codex` —
  Codex monorepo (Rust core, TypeScript SDK, app-server, app-server-protocol,
  MCP server, agent-identity, etc.).
- `~/Zai/docs/openai_hackathon/docs/CDXLearn/cdx_notes` — the 9 Chinese-language
  notes about Codex internals: state/logs/sqlite, transcript model, recall,
  multi-agent patterns, harness sketches.
- The current working repo `~/Zai` (the Clariose NestJS backend), which is where
  CareNote will land.

---

## 1. Current Qagent architecture (the existing Claude harness)

Qagent is a NestJS 11 + Prisma + RxJS service that drives the
`@anthropic-ai/claude-agent-sdk` to run a registry of named agents organised
into named teams. It is the pattern we are replacing.

### 1.1 Module shape

`backend/src/orchestrator/orchestrator.module.ts` bundles ~9 sub-modules:

| Folder | Role |
|---|---|
| `agents/` | NestJS controller + `AgentsService` registry. Seeds archetypes from `agent-archetypes.ts`, materialises workspaces. |
| `claude-runtime/` | Adapter to `@anthropic-ai/claude-agent-sdk`. ~1.2k LOC. Owns `kickOffTurn()`, lazy-loads SDK, streams `SDKMessage` → `ServerEvent`. |
| `swarm/` | Team file model (`teams/<team>/<slug>/`), in-process runner, mailbox protocol, permission bridge. |
| `memory/` + `memory/recall/` | File-based memory (under `runtime/memory/`), Redis-cached scan manifest, side-channel selector LLM, surface formatter. |
| `recall/` | The `__recall__` internal team (librarian / coordinator / summariser / verifier). Hidden from UI. |
| `events/` | `EventBusService` — single RxJS Subject, filtered per agent, used for SSE. |
| `security/` | `PermissionDecisionEngine`, dangerous-pattern deny lists, audit log. |
| `skills/` | Catalog of per-agent + per-team + global skill directories. |
| `usage/`, `artifacts/`, `workspace/`, `auto-dream/` | Token telemetry, artifact browser, workspace ensure, "auto-dream" idle agent triggers. |

### 1.2 Agent runtime (Claude SDK lifecycle)

The lifecycle is driven by `ClaudeRuntimeService.kickOffTurn()`:

1. Create `AgentRun` row in Postgres (run id, status, prompt hash, model).
2. Wrap in two `AsyncLocalStorage` contexts: agent context, workload context.
3. Call `driveTurnInner()`, which:
   - Lazy-loads the Claude SDK (`loadSdk()`).
   - Builds an `Options` payload via `buildSystemPromptAppend()` in
     `claude-runtime/system-prompt.ts`, layered as
     `persona → kairos → house-rules`.
   - Calls `sdk.query({ prompt, options })`, which yields an
     `AsyncIterable<SDKMessage>`.
   - Translates each message via `sdk-translator.ts` into a `ServerEvent`
     (`AssistantDelta`, `ToolUse`, `ToolResult`, `MemoryRecalled`, etc.) and
     emits to `EventBusService`.

Persistence split:

- **Postgres** holds metadata only: `Agent` rows, `AgentRun` rows with token
  usage and prompt-state hashes, `Session` rows for user auth.
- **Filesystem** holds everything else: the Claude transcript JSONL is
  written by the SDK itself to
  `~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl`. The backend reads it
  back through SDK helpers (`getSessionMessages()`, `listSessions()`).
- **Filesystem** also holds memory (`memory/`), artifacts (`artifacts/`),
  per-agent settings (`.claude/settings.json`), per-agent skills
  (`.claude/skills/`).
- **Redis** holds: scan manifest cache, per-session recall budgets,
  surfaced-path dedup sets.

### 1.3 Memory & recall (the "passive" pipeline)

Memory recall is a four-step pipeline run on every turn before the agent fires:

1. `MemoryScanService.getScan()` — walks each memory dir, builds a manifest
   (path, size, summary line), caches in Redis.
2. `SideQueryService.select()` — runs a fast secondary LLM call (≤2s) against
   the manifest to pick relevant files for the current prompt.
3. `MemorySurfaceService.readForSurfacing()` — reads chosen files from disk.
4. `toAppendBlock()` — formats the result as a `<system-reminder>` block
   pinned to the **tail of the user prompt** (deliberately not the system
   prompt, to keep the prompt cache prefix stable).

The `__recall__` team is a hidden internal team of four agents
(librarian / recall-coordinator / summariser / verifier) used for offline
maintenance of the memory store.

### 1.4 Communication protocol & teams

Teams live on disk under `teams/<team>/<slug>/`:

```
teams/default/coordinator/
  CLAUDE.md                # persona text
  .claude/settings.json    # permission deny list
  .claude/skills/          # private skills
  memory/                  # durable notes (human-edited)
  artifacts/               # outputs (visible in UI)
```

Inter-agent comms uses a file-backed **mailbox**:

- `TeammateMailboxService.sendMessage()` writes a JSON message into the
  recipient's mailbox file.
- `InProcessRunnerService` polls the mailbox (~500ms) for each agent and, on
  the next turn, prepends a `formatTeammateMessages()` block to the prompt.
- Some messages are "structured protocol" messages (permission requests,
  shutdown signals); the rest are sanitised text.

Cross-team Task calls are rejected at the dispatch layer
(`SwarmController.getTeamMember()`).

### 1.5 Prompt management

- Persona is the stable layer (cache friendly).
- Kairos / house-rules are dynamic (no cache promises).
- `system-prompt.ts` builds an explicit append block that the SDK appends
  to its built-in system prompt.
- `prompt-cache-break.ts` is a diagnostic helper to inspect why the cache
  prefix changed.

### 1.6 Tool execution

The Claude SDK does the actual tool dispatch. Qagent intervenes via:

- `Agent.allowedTools` / `Agent.disallowedTools` columns.
- Per-agent `.claude/settings.json` deny list (hard-coded examples:
  `Bash(rm -rf /*)`, `Bash(sudo rm*)`, `Bash(git push --force*)`).
- `PermissionDecisionEngine` for runtime decisions, with an optional
  `YoloClassifierService` LLM classifier for auto-mode decisions.
- `SwarmPermissionBridgeService` to make sub-Task calls go through the
  same engine.

### 1.7 Error handling

Errors surface as `ServerEvent`s on the bus and as `AgentRun.status`
transitions in Postgres. There is no broad `try/catch` in the runtime;
the philosophy is "fail visibly, store the failure in `AgentRun`".

### 1.8 Test coverage

Effectively none. The repo CLAUDE.md openly says it is at "scaffolding"
phase and that several Prisma tables are intentionally empty hooks.

### 1.9 Frontend

A separate Nuxt-style frontend exists (`frontend/`); not relevant to the
harness migration except as a consumer of SSE events from `EventBusService`.

---

## 2. Claude harness lessons from CCLearn

CCLearn is the reverse-engineered Claude Code CLI source plus 10 integrated
notes. Its architecture is much larger than Qagent's, but the relevant
patterns for the CareNote Codex harness are:

### 2.1 Reusable patterns

- **Async-generator turn loop.** Claude Code's `query.ts` is an async
  generator that yields stream events and tool calls. This pattern is
  provider-agnostic and is exactly what we want for the Codex harness's
  `runStreamed()` path. Reuse the shape, not the code.
- **Tool factory + permission gate.** `buildTool()` produces stateless tool
  definitions with Zod schemas; the executor partitions read-only vs. write
  tools and parallelises read-only ones. We will not run arbitrary tools
  inside CareNote agents (medical safety), but the pattern is useful for
  the small number of side-effect calls we *will* allow (e.g.,
  `confirm_draft_task`).
- **Cache-friendly system prompt layering.** `persona → kairos → dynamic`
  with explicit byte-stable boundaries. This translates 1:1 to Codex
  custom-agent prompts (frozen prompt file + dynamic per-turn payload).
- **Compaction / microcompact / autocompact.** The 3-tier strategy is the
  right shape for managing long doctor-visit transcripts. We do not need
  to port the implementation; we need the *trigger heuristic*.
- **Mailbox + in-process runner.** Useful even for a Codex-only harness
  if we want roles to send each other structured messages. For MVP we
  do not need this — the orchestrator owns the fan-out — but the door is
  left open in the architecture.
- **Permission deny-by-default with a small explicit allow set.** The
  permission engine taxonomy (default / auto / bypass) is portable and
  will be repurposed as `sandbox_policy` on each Codex custom agent.

### 2.2 Patterns to discard

- **Provider abstraction that keeps Claude live.** Qagent has no formal
  abstraction, but several Claude SDK assumptions leak into
  `claude-runtime/`. We do not port those.
- **Bridge / remote / cross-device transports.** Out of scope for the
  CareNote MVP and not Codex-shaped anyway.
- **Bash safety validators (25+).** Codex has its own sandbox model
  (`workspace-write`, `read-only`, `full-access`). We do not duplicate
  shell safety; we just declare each CareNote agent `read-only`.
- **Plugin / Ink UI / keybinding subsystems.** Not applicable to a
  server-side harness.

### 2.3 Mapping to Codex (preview — Doc 06 expands this)

| Claude concept | Codex replacement |
|---|---|
| `@anthropic-ai/claude-agent-sdk` query loop | `@openai/codex-sdk` `Thread.runStreamed()` |
| Sub-Task tool | Persistent per-role Codex thread, owned by orchestrator |
| Claude prompt files (CLAUDE.md per agent) | `prompts/codex-agents/*.md` + `.codex/agents/*.toml` |
| Mailbox between agents | Synchronous orchestrator fan-out (MVP) |
| Memory recall pipeline | Confirmed-only `MemoryRetrievalService` + transcript turns |
| Permission engine | Codex `sandbox_mode = "read-only"` on every CareNote agent |
| `~/.claude/projects/*.jsonl` | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |
| Prisma `AgentRun` row | Prisma `agent_runs` row (renamed, same shape) |

The key shift: Qagent treats agents as Claude *processes* with file
workspaces; the Codex harness treats agents as Codex *threads* with frozen
prompt files. The unit of identity moves from "filesystem workspace" to
"thread id + role".

---

## 3. Codex ecosystem findings (CDXLearn)

This is the most decision-relevant section. The Codex ecosystem is
substantially different from Claude Code's.

### 3.1 Codex SDK (TypeScript) — `@openai/codex-sdk`

Source confirmed at
`docs/CDXLearn/openai-codex-source/codex/sdk/typescript/src/`.

Public API surface:

```ts
class Codex {
  constructor(options?: CodexOptions);
  startThread(options?: ThreadOptions): Thread;
  resumeThread(id: string, options?: ThreadOptions): Thread;
}

class Thread {
  readonly id: string | null;        // populated after first turn
  run(input: Input, opts?: TurnOptions): Promise<Turn>;
  runStreamed(input: Input, opts?: TurnOptions): Promise<StreamedTurn>;
}

type Turn = { items: ThreadItem[]; finalResponse: string; usage: Usage | null };
type StreamedTurn = { events: AsyncGenerator<ThreadEvent> };
```

Key properties confirmed by reading `thread.ts`:

- `Thread.id` *is* exposed via a public getter, populated when the
  `thread.started` event arrives. This contradicts an earlier worry that
  thread IDs were not addressable. They are.
- The SDK does not call any HTTP API itself. It shells to the Codex CLI
  binary (`CodexExec` in `exec.ts`) and reads JSON events from the binary's
  stdout. So **the SDK requires the Codex CLI to be installed**.
- `TurnOptions.outputSchema` accepts a JSON Schema. The SDK serialises it
  to a temp file and passes `--output-schema` to the CLI. This gives us
  schema-validated JSON output natively.
- `ThreadOptions` includes `model`, `sandboxMode` (`"read-only" |
  "workspace-write" | "danger-full-access"`), `workingDirectory`,
  `skipGitRepoCheck`, `approvalPolicy`, `modelReasoningEffort`,
  `networkAccessEnabled`.
- Threads are persisted by the CLI, not the SDK, to
  `~/.codex/sessions/YYYY/MM/DD/rollout-<id>.jsonl` plus a SQLite index.
  Resume across process restarts is supported by passing the same `id` to
  `resumeThread()`.

Auth modes:

- If `~/.codex/auth.json` is present (i.e. the user has run
  `codex login`), the CLI uses the ChatGPT-subscription token by default.
- If `OPENAI_API_KEY` is set in the environment, the CLI falls back to
  API-key auth.
- The SDK can be told to *not* leak `OPENAI_API_KEY` into the child by
  passing an empty `env` block in `CodexOptions`.

### 3.2 Codex CLI

`codex exec --cd <dir> --json --sandbox <mode> "<prompt>"` is the canonical
non-interactive invocation. It writes structured JSONL events on stdout.

`codex login --device-auth` is the one-time login flow used for the
ChatGPT subscription path.

`codex resume --thread-id <id>` is referenced in cdx_notes but is not
fully documented in the source we have.

### 3.3 Codex app-server

`codex-rs/app-server*` implements a JSON-RPC 2.0 protocol over stdio
(experimental WebSocket also). It is the runtime used by the VS Code and
Codex Desktop clients. It exposes richer streaming events and approval
workflows but it does not introduce a new persistence layer — it reads
the same `~/.codex/sessions/*.jsonl` + `state_5.sqlite` as the CLI/SDK.

For our use case it is overkill: we do not need real-time UI streaming
through the harness, and adding JSON-RPC would only make the integration
more brittle.

### 3.4 Custom agents / project-level config

- `~/.codex/config.toml` and project-level `.codex/config.toml` are
  honoured by the CLI. Fields seen in source: `forced_login_method`,
  `sandbox_mode`, `approval_policy`, `model`, `model_reasoning_effort`.
- `AGENTS.md` is the natural-language project instruction file.
- Codex *does* have a notion of custom agents under `.codex/agents/*.toml`
  in some recent codex-rs branches; the schema is not yet stable in the
  source we have, but the convention is the same as the rest of Codex
  (TOML, name + description + developer instructions + sandbox).
- Codex subagents (the in-CLI `Agent` tool) are transient — they spawn a
  child run and report back. They are NOT a substitute for a persistent
  per-role thread, which is what CareNote needs.

### 3.5 Persistence on disk

From `cdx_notes/1. state_logs_capsid.md` and `cdx_notes/4. sqlite 和 jsonl.md`:

| Path | Purpose |
|---|---|
| `~/.codex/auth.json` | Login token. Sensitive. |
| `~/.codex/config.toml` | User config. |
| `~/.codex/sessions/YYYY/MM/DD/rollout-<id>.jsonl` | Per-thread transcript (append-only). |
| `~/.codex/state_5.sqlite` | Index of threads (id, title, cwd, archived, rollout_path, updated_at). |
| `~/.codex/session_index.jsonl` | Append-only thread name index. |
| `~/.codex/logs_2.sqlite` | App-server / streaming diagnostics. |
| `~/.codex/memories/MEMORY.md` | Optional Codex-internal memory store. |

We do **not** rely on any of these schemas for our application data. We
treat the rollout JSONL as opaque per-role transcript and we keep our own
state in the Clariose Postgres DB plus a small JSON file for the team
manifest.

### 3.6 Streaming events

Confirmed event types from `events.ts` (read via SDK source): `thread.started`,
`item.completed`, `turn.completed`, `turn.failed`, plus per-item subtypes
(`agent_message`, `tool_call`, `tool_result`, etc.). Our harness consumes
`runStreamed()` directly and only logs the events we care about.

### 3.7 Approval / sandbox limitations

- `sandboxMode = "read-only"` is the strictest mode. CareNote agents will
  use it across the board because they must not write files, run shells,
  or call out to the network.
- `approvalPolicy = "never"` lets us run non-interactively.
- The sandbox is enforced by the Rust CLI; there is no way to opt out from
  the SDK without explicitly choosing a more permissive mode.

### 3.8 Subscription-auth feasibility

Yes, achievable. If `codex login --device-auth` has been run on the host,
both the CLI and the SDK reuse `~/.codex/auth.json` automatically. Our
harness does not need to manage tokens itself; it just needs to refuse to
proceed if `auth.json` is missing and `OPENAI_API_KEY` is also absent.

---

## 4. Recommended Codex integration approach

### 4.1 Primary: `@openai/codex-sdk`

Reasons:

- Public, typed API (`Thread`, `Turn`, `ThreadEvent`).
- `Thread.id` is exposed and stable across `resumeThread()`.
- `outputSchema` gives us schema-validated JSON natively.
- Streaming is an `AsyncGenerator`, idiomatic for Node.
- Underneath, it shells to the Codex CLI — which means it inherits
  ChatGPT-subscription auth from `~/.codex/auth.json` for free.

### 4.2 Fallback: Codex CLI via `child_process`

Reasons to keep it as a fallback:

- The SDK is currently published as `0.0.0-dev` and may not be on npm at
  the time of building.
- If we hit an SDK-only bug, we can drop to `codex exec --cd ... --json`
  and parse JSONL ourselves.
- The CLI is the actual unit of execution either way, so the runtime
  semantics are identical.

### 4.3 Future option: app-server

We do not adopt app-server in v1. We will revisit it if and only if we
need:

- multi-client realtime streaming of the harness's internal events; or
- a richer approval flow that the SDK does not expose.

### 4.4 Trade-offs

- The SDK forces us to have the Codex CLI binary on PATH. This is an
  install-time concern, not a runtime one.
- The SDK is `0.0.0-dev`. Until it is published, we vendor our integration
  behind a `CodexRuntime` interface so we can swap implementations.

### 4.5 Exact commands / APIs

- One-time host setup: `codex login --device-auth`.
- Health check (programmatic): try to start a thread, run a no-op prompt,
  catch errors.
- Thread start: `const thread = codex.startThread({ sandboxMode: "read-only", workingDirectory: cwd, skipGitRepoCheck: true, approvalPolicy: "never" });`
- Thread run: `const turn = await thread.run(prompt, { outputSchema });`
- Thread resume: `const thread = codex.resumeThread(savedId, sameOptions);`

---

## 5. Risks

1. **Subscription auth blocks**. If `codex login` is not run, the SDK fails
   with an auth error. Our `healthCheck()` must surface this clearly.
2. **Latency**. Codex is engineering-tuned, not realtime-tuned. Expect
   each agent turn to take seconds. This is *why* the harness must be
   fully decoupled from the Realtime audio pipeline.
3. **Persistence**. Codex's session storage is on the local filesystem;
   if the host changes, we lose threads. Our DB stores the thread IDs but
   the actual state lives in `~/.codex/sessions/`. For a hackathon this is
   fine; for production it is a single-host bottleneck.
4. **Privacy**. Codex's rollout JSONL contains full transcripts. We must
   not put raw PHI into the prompt unless we accept that copy ends up in
   `~/.codex/sessions/`. The simple mitigation is to (a) keep the working
   directory at a non-shared path and (b) document that the CareNote host
   owner is responsible for that directory.
5. **Medical safety**. Codex is a coding agent by default. Without strong
   prompt and schema constraints it will happily diagnose, prescribe, or
   invent. The compliance guardrail agent is mandatory; reducer-side
   validation is mandatory; both belong in the harness.
6. **Transcript reliability**. Realtime ASR is noisy. Drug names and doses
   are the most failure-prone tokens. The Transcript Quality agent and
   the rule-based reducer (force `requires_user_confirmation = true` on
   every medication output) are the safety net.
7. **SDK churn**. `@openai/codex-sdk@0.0.0-dev` is by definition unstable.
   We pin behind a `CodexRuntime` interface and provide a `codex-cli`
   fallback runtime so any breakage is recoverable at the seam.

---

## 6. Decision summary

- **Harness runtime**: `@openai/codex-sdk` primary, `codex-cli` fallback,
  app-server optional future.
- **Auth**: ChatGPT subscription via `~/.codex/auth.json`; refuse to start
  if neither subscription nor `OPENAI_API_KEY` is configured.
- **Persistence**: Clariose Postgres for application state and thread-id
  registry; `~/.codex/sessions/` for opaque per-role rollouts; on-disk
  team manifest at `config/codex-teams/carenote-doctor-visit.team.json`.
- **Decoupling**: Realtime → TranscriptEventBus → CodexJobQueue → harness.
  No synchronous Codex call from the Realtime path.
- **Safety**: every CareNote agent runs in `sandbox_mode = "read-only"`,
  with `approvalPolicy = "never"` and `networkAccessEnabled = false`.
- **Schemas**: `TurnOptions.outputSchema` for native JSON validation, plus
  Zod re-validation in the reducer for defence in depth.

This concludes Phase 0. Phase 1 (`docs/design/01..08`) builds the design
documents on top of these findings.
