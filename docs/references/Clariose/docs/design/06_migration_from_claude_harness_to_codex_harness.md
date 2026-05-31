# 06 — Migration from Claude Harness to Codex Harness

Date: 2026-04-29

## 1. Scope

This document is the bridge between Qagent (the existing Claude harness
under `~/Zai/docs/openai_hackathon/Qagent`) and the new CareNote
Codex-only harness (under `backend/src/modules/carenote/`).

We do **not** migrate Qagent in place. Qagent stays as a reference
implementation. The Codex harness is built fresh under the existing
Clariose backend, taking the patterns that survive and explicitly leaving
the Claude-specific patterns behind.

## 2. Concept-by-concept mapping

| Qagent / Claude concept | Codex harness replacement | Strategy |
|---|---|---|
| `@anthropic-ai/claude-agent-sdk` | `@openai/codex-sdk` | Replace. |
| `ClaudeRuntimeService.kickOffTurn()` | `CodexRunManager.process(job)` + `CodexRuntime.run()` | Rewrite, keep async-generator shape. |
| `sdk.query({ prompt, options })` async iterable | `thread.runStreamed(prompt, { outputSchema })` | Direct mapping. |
| `sdk-translator.ts` (SDKMessage → ServerEvent) | Internal to runtime; harness consumes parsed JSON | Discard intermediate translator. |
| Per-agent CLAUDE.md persona | `prompts/codex-agents/<role>.md` (English) | Rewrite. |
| `teams/<team>/<slug>/.claude/settings.json` | Team manifest + per-role TOML in `.codex/agents/` | Rewrite. |
| Mailbox between agents | Synchronous orchestrator fan-out (MVP); mailbox optional later | Defer. |
| `EventBusService` (RxJS Subject) | `TranscriptEventBus` (RxJS Subject) | Reuse pattern; rename + scope. |
| `MemoryRecallService` (4-step pipeline) | `MemoryRetrievalService.retrieve(allowed_memory_status: "confirmed_only")` | Simplify. Drop side-channel selector LLM for MVP. |
| `__recall__` internal team | Not ported. Codex roles read from `memory_entries` directly. | Discard. |
| `Agent` table (Prisma) | `codex_agent_threads` | Rename + reshape. |
| `AgentRun` table | `agent_runs` | Reuse name pattern. |
| `Session` table (Claude session) | (none — Codex stores session itself) | Discard. |
| `WorkspaceService.ensure()` (per-agent file workspace) | Not needed; Codex agents are read-only and have no workspace artefacts | Discard. |
| `SkillCatalogService` 4-tier skill discovery | Not ported. CareNote agents do not run user-facing skills. | Discard. |
| `PermissionDecisionEngine` | `sandboxMode = "read-only"` on every agent + reducer-side rule enforcement | Replace. |
| `dangerous-patterns.ts` | Not needed; agents cannot run shell. | Discard. |
| `auto-dream` idle agent triggers | Not ported. | Discard. |
| `claude-runtime/system-prompt.ts` (persona/kairos/house-rules) | Single prompt file per role; user payload is structured XML-ish; no per-turn prompt rebuilds | Simplify. |
| Claude prompt-cache strategy | Codex auto-handles via thread; no manual cache markers needed | Discard. |
| `~/.claude/projects/*.jsonl` transcripts | `~/.codex/sessions/*.jsonl` (managed by Codex, not us) | Trust the runtime. |

## 3. What we reuse (and how)

### 3.1 The async-generator turn pattern

The shape of `claude-runtime.service.ts` — start a run row, drive an
iterable, translate events, finalise the run row — is exactly what
`CodexRunManager` does. We keep that shape and substitute Codex calls.

### 3.2 The role manifest on disk

Qagent's `teams/<team>/<slug>/CLAUDE.md` is a healthy idea: each role
has its own readable prompt file, in source control. CareNote uses the
same shape but English filenames under `prompts/codex-agents/` and a
JSON team manifest at `config/codex-teams/`.

### 3.3 The agent_runs audit pattern

Qagent's `AgentRun` row with token usage, prompt-state hashes, and
status transitions is a good audit primitive. We keep it and add
`prompt_version` and `schema_version` columns.

### 3.4 Defence-in-depth at the reducer

Qagent already does most safety work in code, not in the prompt. We
keep that discipline: the reducer is the last line and rejects unsafe
output even if the prompt slipped. This is doubly important for medical
content.

## 4. What we explicitly do not reuse

### 4.1 No provider abstraction

Qagent has no formal abstraction, but several Claude-specific
assumptions leak into `claude-runtime/`. We do **not** introduce a
provider abstraction in the Codex harness either. The `CodexRuntime`
interface only has Codex implementations. Naming is intentional: it
will be obvious if anyone tries to add a non-Codex implementation and
we will refuse it at review.

### 4.2 No mailbox in MVP

Qagent's mailbox model is good but excessive for our 11-agent fan-out
where every role's input comes from the orchestrator. Adding a mailbox
would couple roles together and complicate concurrency. We leave the
hook in `CodexRunManager` (a `dispatch(role, payload)` seam) so a
future iteration can wire a mailbox on top.

### 4.3 No skill catalogue / tool dispatch

Qagent / Claude has rich tool support. CareNote agents do **not** call
tools at all in MVP. The Codex `sandbox_mode = "read-only"` enforces
this. Any side-effect (confirm a draft, write memory, save a reminder)
is explicit user-side API, not an agent tool.

### 4.4 No `__recall__` internal team

Qagent's internal librarian/coordinator/summariser/verifier is overkill
for confirmed-only memory. We replace it with a simple SQL query
(`memory_entries WHERE active AND patient_id = ?`) plus an optional
top-k filter by recency in MVP.

## 5. Adapter strategy (not adopted)

We considered building a `CodexClaudeAdapter` so existing Qagent code
could call Codex via the SDKMessage shape. We rejected this:

- The shapes do not align well (Codex's `ThreadEvent` vs. Claude's
  `SDKMessage`).
- It would import Claude SDK types, which we want gone.
- It would tempt future devs to "just port one Qagent module".

Instead, the migration is a **clean fork**: CareNote is a new top-level
module under `backend/src/modules/carenote/` and never imports Qagent.

## 6. Migration stages

### Stage 0 — done by this design pass

- Discovery report (00).
- Design docs 01–08.
- Directory skeleton.

### Stage 1 — MVP scaffold (this PR)

- Schemas, prompts, manifest.
- `CodexRuntime` interface + SDK runtime + CLI runtime + stub runtime.
- Realtime broker stub + transcript assembler + event bus.
- `CodexRunManager` with mock-turn flow.
- Safety tests.

### Stage 2 — Realtime integration

- Wire the broker to a real Clariose `realtime` controller endpoint.
- Frontend `useRealtime` adapter.
- Live end-to-end demo with `gpt-realtime-1.5`.

### Stage 3 — UI

- Confirm / reject flows.
- Final-summary UI.
- Memory + reminders pages.

### Stage 4 — Production hardening

- E2E privacy review.
- BullMQ-backed CodexJobQueue.
- Multi-tenant isolation (visits per user).
- Persistence migration (Postgres-only).

## 7. Compatibility tests

The mock-turn fixtures (Doc 08) are cross-compatible: the same
transcript text, fed to Qagent or to CareNote, should produce the
same shape of *user-facing safety behaviour*:

- Medication reminders in `pending` status.
- Source-cited facts.
- No diagnoses.

We do not run Qagent in CI for CareNote; we copy any test fixtures we
want to share into `backend/test/carenote/fixtures/` (Clariose uses Jest).

## 8. Removal plan for Claude dependencies

In the CareNote module, we never import:

- `@anthropic-ai/claude-agent-sdk` (and friends).
- `@anthropic-ai/sdk`.
- Anything under `Qagent/`.

A lint rule (added in Stage 4) banning these imports under
`backend/src/modules/carenote/**` enforces the boundary.

The Clariose base (the existing `backend/src/`) does **not** currently
import Claude either. The agents module that exists (`modules/agents/`)
uses the OpenAI SDK and produces deterministic fixtures when no key is
set — see `OpenAiService` in
`backend/src/modules/agents/openai.service.ts`. CareNote does not depend
on that module either.

## 9. Two-codepath risk

While CareNote and the existing `modules/agents/` (Clariose consult agent
fan-out) coexist, we keep them isolated:

- Different schemas. Clariose `MedicationPlan` ≠ CareNote
  `MedicationInstruction`.
- Different DB tables. Clariose uses `MedicationPlan`, `FollowUp`, etc.
  CareNote uses `extracted_facts`, `draft_tasks`, etc.
- Different API namespace. Clariose uses `/api/sessions/...`. CareNote
  uses `/api/visits/...`.

A future consolidation merges the two; for the hackathon, isolation is
the simpler choice.

## 10. Naming hygiene

Where Qagent uses generic names, CareNote uses Codex-prefixed names so
greps can tell them apart immediately:

- `AgentRegistry` → `CodexAgentRegistry`
- `Runtime` → `CodexRuntime`
- `ThreadStore` → `CodexThreadStore`
- `JobQueue` → `CodexJobQueue`

This is the cheapest possible safeguard against accidental
"provider-agnostic" creep.
