# 04 — Persistent Agent Team Design

Date: 2026-04-29

## 1. Why persistent

Each CareNote role has a stable identity (a stable persona prompt, a
stable schema) and a long-running conversation history (the role has
already seen N transcript turns from this visit, and possibly previous
visits if we ever extend memory).

The Codex-only harness needs to:

- Keep one Codex thread per (team, role) so the model has its own
  history per role.
- Survive process restarts. Threads must resume cleanly.
- Survive prompt edits. We version the prompt; if the version moves, we
  start a fresh thread.
- Avoid context rot. Long threads get periodic summary checkpoints.

## 2. Two artefacts

The persistent design is split between two artefacts:

1. **Team manifest (declarative, on disk, in git).**
   `config/codex-teams/carenote-doctor-visit.team.json`. Describes the
   team's identity: name, version, runtime preference, the list of
   roles, prompt files, schema names, sandbox policy.

2. **Thread state (operational, in DB + JSON mirror).**
   The `codex_agent_threads` table plus
   `.data/carenote/codex-agent-team-state.json`. Records the actual
   thread IDs assigned by Codex.

The manifest is the source of truth for *what the team is*. The state
is the source of truth for *what threads we currently own*.

## 3. Team manifest format

```json
{
  "team_id": "carenote-doctor-visit-v1",
  "team_name": "CareNote Doctor Visit Team",
  "version": "1.0.0",
  "schema_version": "1.0.0",
  "runtime_preference": ["codex-sdk", "codex-app-server", "codex-cli"],
  "default_runtime_options": {
    "model": "gpt-5-codex",
    "sandboxMode": "read-only",
    "approvalPolicy": "never",
    "networkAccessEnabled": false,
    "skipGitRepoCheck": true
  },
  "agents": [
    {
      "role": "visit_orchestrator",
      "name": "Visit Orchestrator",
      "prompt_file": "prompts/codex-agents/visit_orchestrator.md",
      "prompt_version": "1.0.0",
      "schema_name": "VisitOrchestratorOutput",
      "schema_version": "1.0.0",
      "thread_policy": "persistent_per_team",
      "sandbox_policy": "read_only_runtime",
      "agent_config_path": ".codex/agents/carenote_visit_orchestrator.toml",
      "can_write_files": false
    }
    // ... 10 more
  ]
}
```

The manifest is loaded once at startup. Editing it requires either a
process restart or an explicit `POST /api/codex-team/reload` endpoint.

## 4. Thread state schema (Postgres)

```sql
CREATE TABLE codex_agent_threads (
  id              uuid PRIMARY KEY,
  team_id         text NOT NULL,
  role            text NOT NULL,
  thread_id       text,                   -- nullable until first run
  runtime         text NOT NULL,          -- "codex-sdk" | "codex-cli" | ...
  prompt_version  text NOT NULL,
  schema_version  text NOT NULL,
  status          text NOT NULL,          -- "active" | "reset" | "retired"
  last_run_at     timestamptz,
  last_summary    text,
  reset_reason    text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (team_id, role)
);
```

JSON mirror format (`.data/carenote/codex-agent-team-state.json`):

```json
{
  "team_id": "carenote-doctor-visit-v1",
  "updated_at": "...",
  "agents": {
    "visit_orchestrator": {
      "thread_id": "thr_...",
      "runtime": "codex-sdk",
      "prompt_version": "1.0.0",
      "schema_version": "1.0.0",
      "status": "active",
      "last_run_at": "..."
    }
  }
}
```

## 5. Bootstrapping (idempotent)

`CodexTeamBootstrap.bootstrap(manifest)`:

1. For each role in the manifest:
   1. Look up the existing record in `codex_agent_threads`.
   2. If the record exists and `prompt_version` and `schema_version`
      match the manifest → keep it. Optionally call
      `runtime.startOrResumeThread({ existing_thread_id })` to confirm
      the thread is still alive on Codex's side; if Codex returns an
      "unknown thread" error we transition to step 4.
   3. If the record exists but versions differ → mark
      `status = "reset"`, set `reset_reason = "prompt_version_changed"`,
      then proceed to step 4.
   4. Create a new thread via the runtime. Insert/Upsert the record
      with `thread_id = null` and `status = "active"`. (We let
      `thread_id` populate on the first real run via the
      `thread.started` event from the SDK.)
2. Write the JSON mirror.

This is the function `npm run carenote:codex:bootstrap` invokes.

## 6. Resume on first run

The first `run()` for a freshly-created record passes
`existing_thread_id = null`, which makes the SDK `startThread()`. Once
the first turn yields a `thread.started` event, the runtime captures
the new ID and updates the store.

For a record where we already know the `thread_id`, the runtime calls
`codex.resumeThread(thread_id)` and the store does not change.

## 7. Avoiding prompt drift

Two safeguards:

1. **Prompt version pinning.** The prompt file's `prompt_version` is
   stamped in the manifest. If a developer edits the prompt without
   bumping the version, the team manifest schema validator fails
   loudly at startup (CI gate).
2. **Append-only role memory.** The role's working memory lives in
   the Codex thread itself. We never edit a previous turn; we only
   append the next one (a fresh transcript turn or a fresh user-action
   request).

If we *do* want to change a prompt, the operator bumps the version,
restarts the harness, and the next bootstrap resets the affected
threads with `reset_reason = "prompt_version_changed"`.

## 8. Summary checkpoints to fight context rot

Long visits accumulate many turns. We add a per-role summary
checkpoint:

- After every `CARENOTE_THREAD_SUMMARY_INTERVAL` turns (default 12) on
  a given role's thread, the harness inserts a single user message
  asking the role to "summarise everything you know so far in 200
  words; do not invent; do not diagnose; this summary will be
  preserved when older context is dropped".
- We persist the summary in `codex_agent_threads.last_summary`.
- On the next role invocation we prepend the stored summary to the
  user payload as a `<role_self_summary>...</role_self_summary>`
  block. Codex then keeps using the thread normally.

This is intentionally minimal. We do not try to truncate the Codex
thread itself — that is Codex's job.

## 9. Role thread reset / rotation

`CodexThreadStore.reset(team_id, role, reason)`:

1. Update the row to `status = "reset"`, `reset_reason = reason`.
2. Allocate a new thread on the next run.

Reasons we expect:

- `"prompt_version_changed"` — manifest bump.
- `"schema_version_changed"` — schema bump.
- `"manual_reset"` — operator forced it via API.
- `"runtime_changed"` — operator switched runtimes.
- `"thread_invalidated_by_codex"` — Codex returned an unknown-thread
  error.
- `"context_corrupted"` — operator decision after observing bad output.

We deliberately do **not** auto-rotate threads on schedule. A clean
thread loses information; rotation is opt-in.

## 10. Versioning

| Artefact | Version |
|---|---|
| Team manifest | `version` field, semver-ish. Patch bumps for cosmetic; minor for new role; major for breaking schema changes. |
| Each prompt | `prompt_version` per role. Bumped on any non-cosmetic edit. |
| Each schema | `schema_version` per role. Bumped on any backwards-incompatible field change. |
| Whole carenote module | npm `version` in the backend package, advanced on releases. |

A run record stamps `prompt_version` and `schema_version` so we can
diagnose "did this output come from the new prompt or the old one?"
weeks later.

## 11. Deletion / data lifecycle

- Visit deletion (`DELETE /api/visits/:id`) cascades to
  `transcript_turns`, `extracted_facts`, `draft_tasks`,
  `memory_candidates`, `safety_flags`, `agent_runs` for that visit.
- It does **not** delete `codex_agent_threads` rows; those are
  team-level, not visit-level. The thread retains the role's history
  but does not retain any patient-specific data structurally; the
  patient context that did flow through the thread is now in Codex's
  rollout JSONL on the host filesystem.
- For a complete patient wipe, an operator must reset all role
  threads (`POST /api/codex-team/reset?role=*`), which discards the
  Codex-side rollouts.

## 12. Project-level Codex custom-agent files

`.codex/agents/carenote_<role>.toml`. The TOML format Codex consumes
is still firming up in the OSS branch we have, so the harness does not
*depend* on Codex auto-discovering them; instead it always passes the
prompt explicitly via the `instructions` field of `CodexAgentRunInput`
(which becomes the system / developer message Codex sees).

We still ship the TOML files for two reasons:

1. They are the documented Codex extension point and may become
   load-bearing in a future Codex release.
2. They are good developer documentation: a single readable TOML per
   role.

If a future Codex version changes the schema, we update the TOML files
without touching the harness logic.

## 13. Patient memory vs role memory (the firewall)

This distinction is critical and easy to get wrong.

- **Role memory** is a Codex thread's accumulated conversation (the
  role's "self"). It is allowed to contain prior reasoning, prior
  partial decisions, prior schema-shaped outputs.
- **Patient memory** is `memory_entries` (see Doc 03/05). It contains
  user-confirmed allergies, conditions, medications. It is the *only*
  long-term medical memory.

A role thread is **not** a patient memory store. We must not look up
"what allergy does this patient have?" by asking the role's thread; we
must look it up via `MemoryRetrievalService.retrieve()` and inject it
as a payload field. The role's own memory is for its own working
state, not for medical facts about the patient.

The compliance_guardrail role enforces this: any output that asserts a
patient-level fact must cite `source_turn_ids` from the current
transcript or `memory_id`s from confirmed memory.

## 14. Prompt assembly per turn

Each `run()` call sends a single user message of the shape:

```
<role_self_summary>
  ...stored summary, if any...
</role_self_summary>

<event_kind>analyze_turn</event_kind>
<visit_id>vis_...</visit_id>
<turn_id>itm_...</turn_id>

<turn>
  <speaker_label>doctor</speaker_label>
  <text>...</text>
</turn>

<visit_state_snapshot>
  ...JSON of relevant slices...
</visit_state_snapshot>

<memory_context>
  ...confirmed memory hits, JSON...
</memory_context>

<expected_output_schema>VisitOrchestratorOutput</expected_output_schema>
<schema_version>1.0.0</schema_version>
<prompt_version>1.0.0</prompt_version>

Return JSON only.
```

The role's persona / rules are never repeated in the user message; they
live in the Codex thread (as the developer instructions of the custom
agent or as the first message). Repeating them every turn would waste
tokens and confuse the cache.

## 15. Operational endpoints

(Implemented in Doc 07 §API.)

- `GET  /api/codex-team` — view manifest + state.
- `POST /api/codex-team/reload` — re-read manifest, re-bootstrap.
- `POST /api/codex-team/reset?role=...` — reset one (or all) threads.
- `GET  /api/codex-team/health` — runtime health check.
