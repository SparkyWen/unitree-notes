# CareNote v0.3 — 2026-04-29

**Milestone:** M7.6 — Transcript Visibility + Codex Agent Team Expansion
**Branch:** `main`
**Constraints honored:** Codex-only harness; model `gpt-5.5`; no Claude
SDK / Anthropic SDK / OpenAI Agents SDK / LangChain / LangGraph; no
Postgres / JWT / SSE (M8 deferred); no raw audio storage by default;
PHI redaction default-on.

---

## 1. Problem statement (entering this round)

Realtime chain was connected end-to-end:

- Browser opening WebRTC peer to `api.openai.com`
- `gpt-realtime-1.5` accepting the SDP exchange
- Codex CLI authenticated via ChatGPT subscription
- `CARENOTE_CODEX_RUNTIME=codex-cli` working
- `smoke-role medical_instruction_extractor` passing with real codex
- `mock-turn fixture-1-missing-dose.json` passing
- Frontend `useRealtimeVisit.ts` forwarding every event to
  `POST /api/visits/:id/realtime-events`
- Backend assembler accepting events

…**but `GET /api/visits/:id` returned `state.turns: []`.** The
transcript was invisible to the page after reload, the multi-agent
pipeline could be re-triggered by duplicate events, and the agent
team's vocabulary did not match the product (the "auditor" was
described as auditing the doctor instead of auditing the transcript).

---

## 2. Root cause

`TranscriptAssembler` keeps an internal
`Map<visit_id, Map<item_id, TurnState>>` for ordering reconstruction —
this map is **not** part of `VisitState`. The HTTP API only exposes
`VisitState`. Nothing was writing to `VisitState.turns`. The browser's
local `useRealtimeVisit.turns` ref was the only place transcript was
visible, and it was lost on page reload.

There were also no per-event-type counters, no `last_error`, no
`failed_count`, and no `analyzed_item_ids`, so a duplicate
`completed` event would have re-triggered the full Codex pipeline.

---

## 3. Tasks completed

### 3.1 Backend — transcript visibility fix

- **Created** `backend/src/modules/carenote/realtime/applyRealtimeEvent.ts`
  — pure reducer mirroring every Realtime event into `VisitState`.
  Handles `input_audio_buffer.committed`, `.speech_started`,
  `.speech_stopped`, `conversation.item.input_audio_transcription.delta`,
  `.completed`, `.failed`, and top-level `error`. Tolerates unknown
  event types (records `last_event_type` only).
- **Updated** `CareNoteService.ingestRealtimeEvent` to:
  1. Apply each event to VisitState immediately.
  2. Push the event into the assembler only for the four canonical
     transcript types.
  3. Track `analyzed_item_ids` in VisitState **before** publishing to
     the bus, so the analyze-turn job sees the dedup set on read.
  4. Return `{ accepted, emitted_transcript_turn, job_id, duplicate }`.
- **Idempotency rules enforced**:
  - Same `completed` event posted twice → `duplicate: true`, no Codex job.
  - Late `delta` after `completed` → final transcript preserved.
  - `completed` before `committed` → turn created with
    `ordering_confidence: "low"`.
  - `failed` after `completed` → turn flips to `failed`,
    `last_error` set.

### 3.2 Backend — schema additions

In `backend/src/modules/carenote/medical/medicalSchemas.ts`:

- `OrderingConfidenceSchema` (`high|medium|low`).
- `TranscriptTurnSchema` extended: `ordering_confidence`, nullable
  `transcript`, nullable `partial_transcript`, nullable `error`,
  nullable `speaker_label`, nullable `completed_at`.
- `TranscriptStatsSchema` — `committed_count`, `partial_count`,
  `delta_count`, `completed_count`, `failed_count`,
  `last_event_type`, `last_completed_transcript`,
  `last_completed_transcript_at`, `last_partial_transcript`,
  `last_error`, `last_failed_at`.
- `TranscriptVerificationAmbiguitySchema` — typed ambiguity items
  with `ambiguity_type`, `severity`, `suggested_confirmation_question`,
  `source_turn_ids`.
- `TranscriptVerificationRecordSchema` — per-turn verification.
- `CaregiverNotificationDraftSchema` — `{ title, message,
  needs_confirmation, next_actions, requires_user_confirmation: true,
  confirmation_status: "pending", source_turn_ids }`.
- `TranscriptQualityOutputSchema` — replaces `uncertain_terms` with
  structured `ambiguities[]`, adds `safe_to_extract`.
- `FamilySummaryOutputSchema` — adds optional structured
  `caregiver_notification` field.
- `ComplianceGuardrailOutputSchema` — adds blocking reasons:
  `doctor_audit`, `medication_change`, `automatic_reminder`,
  `automatic_caregiver_send`, `unconfirmed_memory_write`.
- `VisitStateSchema` — adds `transcript_stats`,
  `transcript_verifications`, `caregiver_notifications`,
  `analyzed_item_ids`.
- `CodexAgentDisplayNames` — UI/doc-facing labels for the redesigned
  roles.

All optional fields are nullable so the existing strict-normalizer
(`openAiStrictSchema.spec.ts`) keeps producing valid `outputSchema` JSON.

### 3.3 Backend — agent team redesign

Internal role names kept unchanged (preserves thread-state file and
avoids 50-file rename diff). User-facing redesign lands via prompts +
UI labels + smoke-CLI aliases.

| Internal role                    | UI / docs name                  | Pipeline pass |
| -------------------------------- | ------------------------------- | ------------- |
| `visit_orchestrator`             | Visit Orchestrator              | reserved      |
| `transcript_quality`             | **Transcript Verification**     | 1 (parallel)  |
| `speaker_role`                   | Speaker Role                    | 1 (parallel)  |
| `medical_instruction_extractor`  | Medical Instruction Extractor   | 1 (parallel)  |
| `safety_clarification`           | **Clarification Question**      | 1.5 (post-1)  |
| `medication_reminder_draft`      | **Medication Schedule Draft**   | 2 (parallel)  |
| `follow_up_task_draft`           | Follow-up Task                  | 2 (parallel)  |
| `family_summary`                 | **Caregiver Notification**      | 2 (parallel)  |
| `memory_update`                  | Memory Candidate                | 2 (parallel)  |
| `compliance_guardrail`           | **Safety Guardrail**            | last          |
| `final_visit_summary`            | Final Visit Summary             | end-of-visit  |

**New prompt files** under `prompts/codex-agents/`:

- `transcript_verification.md` — flags ASR-level uncertainty only;
  never audits the doctor; emits structured ambiguities with
  suggested confirmation questions.
- `clarification_question.md` — receives ambiguities + missing fields;
  produces patient-friendly questions; cites `source_turn_ids` on
  every question.
- `medication_schedule_draft.md` — drafts only; missing field →
  `needs_user_confirmation`; no inferred dose/frequency/timing.
- `caregiver_notification.md` — draft only; structured
  `caregiver_notification` field embedded; never auto-sent.
- `safety_guardrail.md` — blocks `doctor_audit`, `diagnosis`,
  `treatment_advice`, `medication_change`, `automatic_reminder`,
  `automatic_caregiver_send`, `unconfirmed_memory_write`,
  `unsupported_inference`, `missing_source`.

**Manifest** (`config/codex-teams/carenote-doctor-visit.team.json`)
points to the new prompt files and bumps `prompt_version` to `2.0.0`
for the redesigned roles. `model: "gpt-5.5"` unchanged.

### 3.4 Backend — pipeline reordering

`CodexRunManager.analyzeTurn` now runs:

1. **Pass 1 (parallel):** `transcript_verification`, `speaker_role`,
   `medical_instruction_extractor`.
2. **Pass 1.5:** `clarification_question` — fed
   `transcript_ambiguities`, `missing_critical_fields`, and
   `extractor_missing_fields`.
3. **Pass 2 (parallel):** `medication_schedule_draft`,
   `follow_up_task_draft`, `caregiver_notification`,
   `memory_candidate`.
4. **Guard:** `safety_guardrail` over the merged envelope.
5. **Reducer:** `reduceTurn` merges into VisitState (force-pins all
   draft semantics regardless of agent output).

`buildEnvelope` now emits `transcript_verification` and
`caregiver_notification` envelope fields. `reduceTurn` merges them
into `VisitState.transcript_verifications` and
`VisitState.caregiver_notifications`, force-pinning
`requires_user_confirmation: true` and
`confirmation_status: "pending"` on every notification.

### 3.5 Frontend — composable + page

**`frontend/composables/useRealtimeVisit.ts`**

- New `diagnostics` ref: `dataChannelState`, `lastEventType`,
  per-event-type counts (`committed`, `delta`, `completed`, `failed`),
  `lastCompletedTranscript`, `lastIngestStatus`, `lastIngestError`,
  `lastTranscriptionFailedError`, `lastOpenAiError`, `lastDuplicate`.
- Forwards top-level `error` events to the backend so
  `transcript_stats.last_error` lights up server-side too.
- Captures `dc.onclose` / `dc.onerror`.

**`frontend/composables/useCareNote.ts`**

- Strongly typed: `VisitTurnPersisted`, `TranscriptStats`,
  `TranscriptVerificationRecord`, `CaregiverNotificationDraft`,
  extended `VisitState`.

**`frontend/pages/carenote/visit/[id].vue`**

- Realtime Transcript Debug strip — counts + last transcript text +
  ingest status + duplicate flag + last error sources.
- Transcript section now renders **server-confirmed turns first** with
  `item_id`, `status`, `ordering_confidence`, optional `speaker_label`
  badge, optional ASR error. Falls back to local optimistic mirror
  only when the server has not caught up.
- New panels: **Transcript Verification** (quality + per-ambiguity
  card with suggested confirmation question), **Doctor / pharmacist
  questions** (priority + reason + source turns), **Medication
  schedule drafts** (full field grid + missing fields), **Caregiver
  notification draft** (with copy button, draft/pending tag, never
  auto-sent).

### 3.6 Tests

- **New** `backend/test/carenote/transcriptVisibility.spec.ts` — 7
  reducer cases (committed → delta → completed; late delta after
  completed; duplicate completed; failed event; error event;
  completed-before-committed; partial-only).
- **New** `backend/test/carenote/transcriptIngestService.spec.ts` —
  4 service-level cases (turns persisted; duplicate completed does
  NOT enqueue a second analyze; `failed` event surfaces in
  `transcript_stats`; `error` event records `last_error`).
- **Updated** `backend/test/carenote/teamPersistence.spec.ts` to
  assert manifest-derived versions rather than hard-coded `"1.0.0"`
  (some agents are now `2.0.0`).
- **All previously passing tests still pass.**

### 3.7 Smoke CLI

- **New script** `npm run carenote:smoke:replay-transcript` — drives
  a full `committed → delta×N → completed` Realtime sequence through
  the harness exactly the way the browser does, then prints a JSON
  summary covering turns, `transcript_stats`,
  `transcript_verifications`, `clarifying_questions`,
  `draft_reminders`, `caregiver_notifications`, and
  `analyzed_item_ids`.
- **Updated** `smoke-role.cli.ts` to accept the new aliases:
  `transcript_verification`, `clarification_question`,
  `medication_schedule_draft`, `caregiver_notification`,
  `safety_guardrail` (each maps to its internal role name).

### 3.8 Documentation

- **New** `docs/design/10_m7_6_transcript_visibility_and_agent_team.md`
  — root cause, fixed flow, full agent team table, schemas,
  idempotency rules, debug-panel field-by-field map, smoke runbook,
  remaining limitations.
- **Updated** `docs/CODEx_HARNESS_README.md` — appended §16
  "Transcript visibility (M7.6)" with where transcripts live, how to
  verify on a running session, how to run the replay smoke, and how
  to interpret the debug panel.

---

## 4. Verification (this round, all green)

```text
npx tsc --noEmit        ⇒ clean
npx nest build          ⇒ clean
npm run carenote:test   ⇒ 14 suites · 63 tests · all passed
npm run carenote:codex:health
                        ⇒ runtime: codex-cli, auth: chatgpt_subscription
npm run carenote:codex:smoke-role -- transcript_verification --inline "..."
                        ⇒ runtime: codex-cli, role: transcript_quality,
                          parsed_json.quality: medium,
                          ambiguities[0].ambiguity_type: drug_name,
                          validation_status: valid
npm run carenote:smoke:replay-transcript -- --inline "..."
                        ⇒ turn_count: 1, completed_turns: 1
                          transcript_stats.completed_count: 1
                          transcript_verifications[0].quality: medium
                          ambiguity_types: ["drug_name"]
                          7 clarifying_questions
                          draft_reminders[0].status: needs_user_confirmation
                          draft_reminders[0].blocking_missing_fields:
                            ["medication_name", "dose"]
                          caregiver_notifications[0].requires_user_confirmation: true
                          caregiver_notifications[0].confirmation_status: pending
                          analyzed_item_ids: ["itm-..."]
frontend/npm run build  ⇒ clean (postbuild: pm2 reload clariose-frontend ✓)
backend/npm run build   ⇒ clean (postbuild: pm2 reload clariose-backend ✓)
```

PM2 status after deploy:

```text
clariose-backend     online   (reloaded with M7.6 code)
clariose-frontend    online   (reloaded with M7.6 code)
```

---

## 5. Files touched

### Created (10)

```
backend/src/modules/carenote/realtime/applyRealtimeEvent.ts
backend/src/modules/carenote/api/replay-transcript.cli.ts
backend/test/carenote/transcriptVisibility.spec.ts
backend/test/carenote/transcriptIngestService.spec.ts
prompts/codex-agents/transcript_verification.md
prompts/codex-agents/clarification_question.md
prompts/codex-agents/medication_schedule_draft.md
prompts/codex-agents/caregiver_notification.md
prompts/codex-agents/safety_guardrail.md
docs/design/10_m7_6_transcript_visibility_and_agent_team.md
```

### Modified (12)

```
backend/src/modules/carenote/medical/medicalSchemas.ts
backend/src/modules/carenote/medical/medicalReducers.ts
backend/src/modules/carenote/api/carenote.service.ts
backend/src/modules/carenote/api/smoke-role.cli.ts
backend/src/modules/carenote/codex-harness/codexRunManager.ts
backend/src/modules/carenote/codex-harness/codexGuardrailReducer.ts
backend/test/carenote/teamPersistence.spec.ts
backend/package.json
config/codex-teams/carenote-doctor-visit.team.json
frontend/composables/useRealtimeVisit.ts
frontend/composables/useCareNote.ts
frontend/pages/carenote/visit/[id].vue
docs/CODEx_HARNESS_README.md
```

---

## 6. Acceptance criteria — status

| #   | Criterion                                                              | Status |
| --- | ---------------------------------------------------------------------- | ------ |
| 1   | Realtime completed transcript is visible in frontend                   | ✅      |
| 2   | `GET /api/visits/:id` returns `turns`                                  | ✅      |
| 3   | Synthetic replay creates turns and Codex analysis                      | ✅      |
| 4   | Completed transcript turn triggers Codex CLI multi-agent pipeline      | ✅      |
| 5   | TranscriptVerificationAgent does not audit doctors; flags ASR only     | ✅      |
| 6   | ClarificationQuestionAgent receives ambiguity + missing-field info     | ✅      |
| 7   | MedicationScheduleDraftAgent produces draft-only reminders             | ✅      |
| 8   | CaregiverNotificationAgent produces draft-only messages                | ✅      |
| 9   | SafetyGuardrailAgent blocks diagnosis / doctor-audit / med-change /    |        |
|     | auto-reminder / auto-caregiver-send                                    | ✅      |
| 10  | All schemas pass strict normalization                                  | ✅      |
| 11  | All tests pass (`14 suites · 63 tests`)                                | ✅      |
| 12  | No Claude SDK / Anthropic SDK / OpenAI Agents SDK / LangChain /        |        |
|     | LangGraph                                                              | ✅      |
| 13  | Model stays `gpt-5.5`                                                  | ✅      |
| 14  | No raw audio storage by default                                        | ✅      |
| 15  | PHI redaction remains default                                          | ✅      |

---

## 7. Remaining limitations

- `speaker_label` is not yet propagated from the `speaker_role` agent
  into `VisitState.turns[].speaker_label` — the field is in the schema
  and the UI is already rendering it; wiring lands when M8 introduces
  persistent diarization storage.
- Caregiver Notification draft is currently per-turn; an aggregated
  end-of-visit version belongs to `final_visit_summary`.
- M8 (Postgres / JWT-scoped persistence / SSE) intentionally not
  implemented this round.
- Raw audio storage stays default-off.

## 8. Next step

Real browser microphone test on `https://zai.gold/carenote/visit/<id>`
should now show:

- Realtime Transcript Debug counters growing in lockstep with the
  server's `state.transcript_stats`.
- Server-confirmed turn list growing as each `completed` event lands.
- Transcript Verification panel populating within ~10 s of each
  completed turn.
- Medication-schedule and caregiver-notification panels populating
  with `requires_user_confirmation: true` drafts.

After that, M8 (Postgres + JWT-scoped persistence + SSE) is the next
milestone.
