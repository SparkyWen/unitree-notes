# 03 — Codex-only Harness Architecture

Date: 2026-04-29

## 1. Goals & non-goals

Goals:

- Run a fixed team of 11 named CareNote agents on top of Codex only.
- Persist each role's Codex thread across process restarts.
- Validate every agent output against a schema before merging into
  patient state.
- Apply a guardrail pass before any output reaches the user or the DB.
- Keep the harness fully decoupled from the Realtime pipeline so that
  Codex latency cannot stall recording.

Non-goals:

- We will not use the OpenAI Agents SDK.
- We will not use Anthropic / Claude SDK.
- We will not put a generic "ModelProvider" abstraction on top — the
  abstraction we keep, `CodexRuntime`, has only Codex implementations.
- We will not run agents inside the Realtime audio loop.

## 2. Components

```
┌────────────────────────────────────────────────────────────────┐
│ TranscriptEventBus                                            │
│  publish(doctor_visit.transcript_turn.completed)              │
└──────────────────────────────┬─────────────────────────────────┘
                               │
                               ▼
                       ┌────────────────┐
                       │ CodexJobQueue  │  enqueue(job)
                       └───────┬────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │     CodexRunManager      │
                  └──────────────────────────┘
                    │ ┌──────────────────────────────┐
                    │ │ CodexAgentTeam               │
                    │ │  - team manifest (json)      │
                    │ │  - 11 roles                  │
                    │ └──────────────────────────────┘
                    │
                    ▼ for each role
            ┌──────────────────┐         ┌────────────────────┐
            │ CodexAgentRegistry├───────▶│ CodexThreadStore   │
            │ role → thread_id │         │ persisted in DB    │
            └────────┬─────────┘         └────────────────────┘
                     │
                     ▼
            ┌──────────────────────────┐
            │ CodexRuntime (one of)    │
            │  - codex-sdk runtime     │
            │  - codex-cli runtime     │
            │  - app-server runtime    │
            └──────────┬───────────────┘
                       │ JSON output
                       ▼
            ┌──────────────────────────┐
            │ CodexOutputParser        │ strip fences, parse JSON
            │ CodexSchemaValidator     │ Zod check; one repair pass
            └──────────┬───────────────┘
                       │ valid parsed_json
                       ▼
            ┌──────────────────────────┐
            │ CodexGuardrailReducer    │ compliance_guardrail role
            └──────────┬───────────────┘
                       │ safe payload
                       ▼
            ┌──────────────────────────┐
            │ VisitStateReducer        │ deterministic merge
            └──────────────────────────┘
                       │
                       ▼
            visits / extracted_facts / draft_tasks /
            memory_candidates / safety_flags
```

## 3. Roles (the team)

| Role | Purpose | Output schema |
|---|---|---|
| `visit_orchestrator` | Decide which other roles to run; merge their outputs into a structured turn-level result. | `VisitOrchestratorOutput` |
| `transcript_quality` | Mark uncertainty in the latest turn (drug names, doses, dates). | `TranscriptQualityOutput` |
| `speaker_role` | Classify speaker (doctor/patient/family/unknown). | `SpeakerRoleOutput` |
| `medical_instruction_extractor` | Extract explicitly stated facts. | `MedicalInstructionExtractorOutput` |
| `medication_reminder_draft` | Convert medication facts into reminder drafts. | `MedicationReminderDraftOutput` |
| `follow_up_task_draft` | Convert follow-up / test / referral facts into task drafts. | `FollowUpTaskDraftOutput` |
| `safety_clarification` | Clarifying questions + safety flags. | `SafetyClarificationOutput` |
| `family_summary` | Plain-language family-facing summary. | `FamilySummaryOutput` |
| `memory_update` | Long-term memory candidates. | `MemoryUpdateOutput` |
| `compliance_guardrail` | Inspect everything before VisitState mutation. | `ComplianceGuardrailOutput` |
| `final_visit_summary` | End-of-visit summary. | `FinalVisitSummaryOutput` |

Each role has:

- a Codex custom-agent file (`.codex/agents/carenote_<role>.toml`),
- a prompt file (`prompts/codex-agents/<role>.md`),
- a Zod schema (`backend/src/modules/carenote/medical/medicalSchemas.ts`),
- a persistent Codex thread (one per role per team).

## 4. CodexRuntime abstraction

The harness has one knob: which Codex transport to use.

```ts
export interface CodexRuntime {
  name: "codex-sdk" | "codex-cli" | "codex-app-server" | "stub";

  startOrResumeThread(input: {
    team_id: string;
    role: CodexAgentRole;
    existing_thread_id?: string;
    agent_config_path?: string;
  }): Promise<{ thread_id: string }>;

  run(input: CodexAgentRunInput): Promise<CodexAgentRunOutput>;

  healthCheck(): Promise<{
    ok: boolean;
    runtime: string;
    auth_mode?: "chatgpt_subscription" | "api_key" | "unknown";
    details?: string;
  }>;
}
```

Implementations:

- **`codexSdkRuntime`** (primary). Wraps `@openai/codex-sdk` with the
  fixed sandbox / approval / network settings. Holds a per-role `Thread`
  in an in-memory map keyed by `thread_id`; on cold start it lazily
  resumes via `codex.resumeThread(id)`.
- **`codexCliRuntime`** (fallback). Spawns
  `codex exec --json --sandbox read-only --cd <cwd> --output-schema <path> "<prompt>"`
  and parses the JSONL stream.
- **`codexAppServerRuntime`** (future). Speaks JSON-RPC 2.0 to a long-
  running app-server child process.
- **`stubRuntime`** (CI / no-codex). Returns deterministic fixtures
  keyed by role. Used in tests and when neither subscription auth nor
  `OPENAI_API_KEY` is configured.

`CodexRuntimeFactory` picks one based on:

1. `CARENOTE_CODEX_RUNTIME` env override; else
2. If `@openai/codex-sdk` resolves AND `codex` CLI is on `PATH` AND
   either `~/.codex/auth.json` or `OPENAI_API_KEY` is configured →
   `codex-sdk`.
3. Else if `codex` CLI is on `PATH` → `codex-cli`.
4. Else `stub` with a loud warning.

## 5. CodexThreadStore

Persistent map: `(team_id, role) → thread_id` plus prompt / schema
versions, runtime name, lifecycle status.

DB table: `codex_agent_threads` (Doc 04).

API:

```ts
interface CodexThreadStore {
  get(teamId: string, role: CodexAgentRole): Promise<ThreadRecord | null>;
  upsert(rec: ThreadRecord): Promise<void>;
  reset(teamId: string, role: CodexAgentRole, reason: string): Promise<void>;
  recordRun(teamId: string, role: CodexAgentRole, summary: string): Promise<void>;
  list(teamId: string): Promise<ThreadRecord[]>;
}
```

For the hackathon we also keep a JSON mirror at
`.data/carenote/codex-agent-team-state.json` so the system survives if
Postgres is down. The DB is authoritative when both are present.

## 6. CodexAgentRegistry

In-memory registry built at startup from the team manifest plus the
prompts directory. Provides:

```ts
interface CodexAgentRegistry {
  getRole(role: CodexAgentRole): RoleDefinition;
  list(): RoleDefinition[];
}

type RoleDefinition = {
  role: CodexAgentRole;
  prompt: string;          // full prompt body
  promptVersion: string;
  schemaName: string;
  schemaVersion: string;
  threadPolicy: "persistent_per_team" | "transient";
  sandboxPolicy: "read_only_runtime";
  agentConfigPath?: string; // .codex/agents/*.toml
};
```

## 7. CodexAgentTeam

A `CodexAgentTeam` is a configuration object (Doc 04) bound to a
specific runtime. It exposes:

```ts
interface CodexAgentTeam {
  teamId: string;
  ensureThreads(): Promise<void>;             // resume or create
  resetThread(role: CodexAgentRole, reason: string): Promise<void>;
  run(role: CodexAgentRole, input: CodexAgentRunInput): Promise<CodexAgentRunOutput>;
  manifest(): TeamManifest;
}
```

Bootstrap is idempotent: starting twice with the same manifest does not
allocate new threads.

## 8. CodexJobQueue & CodexRunManager

`CodexJobQueue` is an in-memory queue for MVP, with a clean interface so
we can swap to BullMQ (Redis is already present in Clariose). Only one job
runs at a time per visit, to keep agent state coherent.

```ts
type CodexJob =
  | { kind: "analyze_turn"; visit_id: string; turn_id: string }
  | { kind: "stage_summary"; visit_id: string }
  | { kind: "final_summary"; visit_id: string };
```

`CodexRunManager.process(job)` is the orchestrator entry point. For
`analyze_turn`:

1. Load `VisitState`.
2. Load confirmed memory via `MemoryRetrievalService.retrieve()`.
3. Run **Pass 1** in parallel:
   `transcript_quality`, `speaker_role`, `medical_instruction_extractor`,
   `safety_clarification`.
4. Run **Pass 2** in parallel, using Pass 1 results as input:
   `medication_reminder_draft`, `follow_up_task_draft`,
   `family_summary`, `memory_update`.
5. Merge Pass 1 + Pass 2 into a draft envelope and pass to
   `compliance_guardrail`.
6. Apply `CodexGuardrailReducer` and `VisitStateReducer`.

For `final_summary`, run `final_visit_summary` once over the merged
state, then guardrail, then expose to UI.

Concurrency knob: per-visit serial; cross-visit parallel up to
`CARENOTE_CODEX_MAX_PARALLEL_VISITS` (default 4).

## 9. CodexOutputParser

Steps:

1. If the raw text starts with a code fence (` ```json` or `` ``` ``),
   strip it.
2. Trim whitespace.
3. `JSON.parse`.
4. If parse fails, ask Codex once to repair, with the JSON repair
   prompt pinned in `prompts/codex-agents/_json_repair.md` (note: this
   re-uses the same role's thread; we add an instruction header that
   the next message is a repair-only request).
5. If still invalid, mark `validation_status = "failed"` and skip the
   reducer.

## 10. CodexSchemaValidator

We use Zod schemas mirroring the JSON Schema we send via
`TurnOptions.outputSchema`. Defence in depth: Codex *should* return
schema-conformant JSON, but we re-validate on receipt.

Status values:

- `"valid"` — parsed and matched the schema.
- `"repaired"` — required exactly one repair pass, then matched.
- `"invalid"` — failed both passes; output discarded.
- `"failed"` — parse error or runtime error.

## 11. CodexGuardrailReducer

Wraps the merged Pass 1 + Pass 2 output and submits it to the
`compliance_guardrail` role. Result:

```ts
type ComplianceResult = {
  is_safe: boolean;
  blocked_items: { item: string; reason: string; suggested_rewrite: string }[];
  required_user_confirmations: string[];
  safe_output_patch: Partial<TurnEnvelope>;
};
```

The reducer:

- Drops any `blocked_items` from the envelope.
- Applies `safe_output_patch` on top of the remaining envelope.
- Adds `required_user_confirmations` to the envelope's
  `clarifying_questions`.
- Forwards the cleaned envelope to `VisitStateReducer`.

## 12. VisitStateReducer (deterministic, code only — no LLM)

Hard rules, enforced in code regardless of what Codex returned:

1. **Reject facts without `source_turn_ids`.** Drop them.
2. **Force `requires_user_confirmation = true`** on every draft task and
   every memory candidate.
3. **Force `confirmation_status = "pending"`** on every draft task and
   memory candidate.
4. **Reject direct memory writes.** The reducer can only insert into
   `memory_candidates`; only the user-side confirm endpoint promotes a
   candidate to `memory_entries`.
5. **For medication reminders**, if any of `medication_name`, `dose`,
   `frequency`, `timing`, `duration` is missing, set
   `status = "needs_user_confirmation"` and create a parallel
   `confirmation_task` if the agent did not.
6. Append to `safety_flags` any guardrail-blocked items as
   `flag_type = "guardrail_blocked"`.
7. Persist `agent_runs` rows for every Codex call.

## 13. VisitState shape

```ts
type VisitState = {
  visit_id: string;
  language: "zh" | "en" | "mixed";
  status: "new" | "recording" | "analysing" | "ended";
  turns: TranscriptTurn[];
  facts: ExtractedFact[];
  draft_tasks: DraftTask[];
  draft_reminders: DraftMedicationReminder[];
  clarifying_questions: ClarifyingQuestion[];
  family_summary_deltas: { turn_id: string; text: string; source_turn_ids: string[] }[];
  family_summary_final?: string;
  memory_candidates: MemoryCandidate[];
  safety_flags: SafetyFlag[];
  guardrail_blocked: ComplianceResult["blocked_items"];
};
```

## 14. Mapping Realtime → Codex jobs

| Trigger | Job |
|---|---|
| `doctor_visit.transcript_turn.completed` | `analyze_turn` |
| User taps "Generate stage summary" | `stage_summary` (uses final-summary role with stage flag) |
| User taps "What should I ask?" | `analyze_turn` re-run for the latest turn (if needed) |
| User taps "End visit" | `final_summary` |

## 15. Concurrency & idempotency

- `analyze_turn` jobs are idempotent on `(visit_id, turn_id)`. If the
  same turn arrives twice we drop the duplicate.
- Per-visit jobs run serially.
- Codex `Thread` objects are cached in the SDK runtime by `thread_id`;
  we evict on idle timeout (default 30 min) to bound memory.

## 16. Failure handling

| Failure | Behaviour |
|---|---|
| Codex `turn.failed` | Store `validation_status = "failed"` in `agent_runs`. Do not merge. UI shows a "transient analysis error" banner. |
| Schema invalid after repair pass | Same — discard. The user still sees the transcript. |
| Guardrail blocks the entire envelope | Persist `safety_flags` only; no facts / drafts merged. |
| Health check fails on cold start | The harness refuses to enqueue new jobs and surfaces a config error to the user. |

## 17. Auditability

Every Codex call is logged in `agent_runs` with: input JSON,
raw output, parsed output, validation status, errors, started/completed
timestamps. The `prompt_version` and `schema_version` columns let us
attribute behaviour changes to specific prompt / schema diffs.

## 18. What the harness deliberately does NOT do

- It does not write to the patient's reminder list.
- It does not update long-term memory.
- It does not send anything to family.
- It does not produce free-form medical opinion outside its schemas.
- It does not call out to network resources during a Codex turn
  (`networkAccessEnabled = false`).

These are user-confirmed actions that live behind explicit API
endpoints (Doc 07 §API).
