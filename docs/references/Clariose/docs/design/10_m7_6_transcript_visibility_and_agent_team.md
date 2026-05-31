# M7.6 — Transcript Visibility + Codex Agent Team Expansion

## 1. Root cause of missing transcript

The Realtime chain was **fully connected** before M7.6: the browser was
opening a WebRTC peer to `api.openai.com`, OpenAI was emitting
`conversation.item.input_audio_transcription.{delta,completed}` events,
and `useRealtimeVisit.ts` was forwarding every event to
`POST /api/visits/:visitId/realtime-events`. The backend was applying
each event to a `TranscriptAssembler`. Yet
`GET /api/visits/:id` returned an empty `state.turns` array.

**Cause.** `TranscriptAssembler` keeps an internal `Map<visit_id,
Map<item_id, TurnState>>` for ordering reconstruction. That map is
**not** part of `VisitState`. The HTTP API only exposes
`VisitState.turns`, and *nothing* was writing to it. The frontend page
read `state.turns`, found it empty, and the only visible transcript
was the local `useRealtimeVisit.turns` ref, which is lost the instant
the user reloads the page.

There was also no per-event-type counter, no `last_error`, no
`failed_count`, and no `analyzed_item_ids`, so a duplicate `completed`
event would have re-triggered the full Codex pipeline.

| #   | Was it working pre-M7.6?                                          |
| --- | ----------------------------------------------------------------- |
| 1   | Frontend receiving `delta`? **Yes.**                              |
| 2   | Frontend receiving `completed`? **Yes.**                          |
| 3   | Frontend forwarding to backend? **Yes.**                          |
| 4   | Backend accepting? **Yes.**                                       |
| 5   | Assembler emitting `doctor_visit.transcript_turn.completed`? **Yes.** |
| 6   | VisitState storing turns? **No — the bug.**                       |
| 7   | `GET /api/visits/:id` returning turns? **No** (empty array).      |
| 8   | Frontend rendering turns? **Only locally**, lost on reload.       |
| 9   | `failed` events visible? **No** — assembler swallowed them.       |
| 10  | `error` events visible? **No** — only set local `error.value`.    |

## 2. The fix in a sentence

Mirror every Realtime event into `VisitState` directly via a pure
reducer (`backend/src/modules/carenote/realtime/applyRealtimeEvent.ts`)
inside `CareNoteService.ingestRealtimeEvent`, persist
`transcript_stats`, and use `analyzed_item_ids` to make duplicate
`completed` events idempotent.

## 3. Final transcript event flow

```
browser
  │  WebRTC data channel
  ▼
useRealtimeVisit.handleEvent
  │  POST /api/visits/:id/realtime-events
  ▼
CareNoteVisitsController.ingest
  ▼
CareNoteService.ingestRealtimeEvent
  ├── applyRealtimeEventToVisitState(prev, evt) ──► visits.set()  // persists turns + transcript_stats
  ├── if canonical transcript event:
  │     assembler.apply()  // only ordering / chain reconstruction
  │     for each emitted completed turn NOT in analyzed_item_ids:
  │       analyzed_item_ids.push(item_id)            // idempotency
  │       bus.publish(turn_completed)
  │
  ▼
bus subscriber  ──► queue.enqueue(analyze_turn job)
  ▼
CodexRunManager.analyzeTurn
  ├── pass 1 (parallel):  transcript_verification, speaker_role,
  │                        medical_instruction_extractor
  ├── pass 1.5:            clarification_question  (sees pass-1 ambiguities + missing fields)
  ├── pass 2 (parallel):   medication_schedule_draft,
  │                        follow_up_task_draft,
  │                        caregiver_notification,
  │                        memory_candidate
  ├── safety_guardrail (sees merged envelope)
  ▼
reduceTurn → visits.set(next)
```

`GET /api/visits/:id` now returns `state.turns`, `state.transcript_stats`,
`state.transcript_verifications`, `state.caregiver_notifications`, and
`state.analyzed_item_ids` in addition to the old fields.

## 4. Agent team — final design

| Internal role (unchanged)        | UI / docs name                  | Pipeline pass | Purpose                                                                           |
| -------------------------------- | ------------------------------- | ------------- | --------------------------------------------------------------------------------- |
| `visit_orchestrator`             | Visit Orchestrator              | n/a           | Reserved for future merge step                                                    |
| `transcript_quality`             | **Transcript Verification**     | 1 (parallel)  | Flags ASR-level uncertainty. Never audits the doctor.                             |
| `speaker_role`                   | Speaker Role                    | 1 (parallel)  | doctor / patient / family / unknown                                               |
| `medical_instruction_extractor`  | Medical Instruction Extractor   | 1 (parallel)  | Explicit facts only; no inference.                                                |
| `safety_clarification`           | **Clarification Question**      | 1.5 (post-1)  | Receives ambiguities + missing_fields and produces patient-friendly questions.    |
| `medication_reminder_draft`      | **Medication Schedule Draft**   | 2 (parallel)  | Drafts only. Missing fields → `needs_user_confirmation`.                          |
| `follow_up_task_draft`           | Follow-up Task                  | 2 (parallel)  | Follow-ups, tests, reports, referrals.                                            |
| `family_summary`                 | **Caregiver Notification**      | 2 (parallel)  | Draft only — `caregiver_notification` field embedded in output.                   |
| `memory_update`                  | Memory Candidate                | 2 (parallel)  | Long-term memory candidates with explicit confirmation.                           |
| `compliance_guardrail`           | **Safety Guardrail**            | last          | Blocks doctor-audit, diagnosis, treatment, auto-reminders, auto-caregiver-sends.  |
| `final_visit_summary`            | Final Visit Summary             | end-of-visit  | Triggered by `/final-summary`.                                                    |

**Why we kept internal role names.** The codex thread-state file, the
Codex run manager, the registry, the schemas, and the four other tests
all key off `CodexAgentRoleSchema` enum values. Renaming would have
forced thread-state migration and a 50-file diff with zero behavior
gain. The user-facing redesign (prompts, UI labels, smoke-CLI
aliases) lands cleanly on top of the existing role names.

The smoke-role CLI accepts the new aliases too:

```
npm run carenote:codex:smoke-role -- transcript_verification --inline "..."
npm run carenote:codex:smoke-role -- clarification_question  --inline "..."
npm run carenote:codex:smoke-role -- medication_schedule_draft --inline "..."
npm run carenote:codex:smoke-role -- caregiver_notification   --inline "..."
npm run carenote:codex:smoke-role -- safety_guardrail         --inline "..."
```

## 5. New / updated schemas (all strict-normalizer-clean)

- `TranscriptTurnSchema` — adds `ordering_confidence`, nullable `error`,
  nullable `transcript`, nullable `partial_transcript`.
- `TranscriptStatsSchema` — `committed_count`, `partial_count`,
  `delta_count`, `completed_count`, `failed_count`, `last_event_type`,
  `last_completed_transcript`, `last_completed_transcript_at`,
  `last_partial_transcript`, `last_error`, `last_failed_at`.
- `TranscriptVerificationAmbiguitySchema` — `{ambiguity_type, text,
  reason, severity, suggested_confirmation_question, source_turn_ids,
  ...}`.
- `TranscriptVerificationRecordSchema` — what we persist per analyzed
  turn.
- `CaregiverNotificationDraftSchema` — `{title, message,
  needs_confirmation, next_actions, requires_user_confirmation: true,
  confirmation_status: "pending", source_turn_ids}`.
- `TranscriptQualityOutputSchema` — replaces `uncertain_terms` with
  `ambiguities` + adds `safe_to_extract`.
- `FamilySummaryOutputSchema` — adds optional structured
  `caregiver_notification` field.
- `ComplianceGuardrailOutputSchema` — adds `doctor_audit`,
  `medication_change`, `automatic_reminder`,
  `automatic_caregiver_send`, `unconfirmed_memory_write` reasons.
- `VisitStateSchema` — adds `transcript_stats`,
  `transcript_verifications`, `caregiver_notifications`,
  `analyzed_item_ids`.

All optional fields are nullable so the OpenAI strict-schema
normalizer keeps producing valid `outputSchema` JSON.

## 6. Idempotency rules

| Race                                                | Behavior                                               |
| --------------------------------------------------- | ------------------------------------------------------ |
| Same `completed` event posted twice                 | Second call returns `duplicate: true` and emits no job |
| `delta` arriving after `completed`                  | Final `transcript` is preserved; delta is dropped      |
| `completed` arriving before `committed`             | Turn is created; `ordering_confidence: "low"`          |
| `failed` after `completed`                          | Turn flips to `failed`; `last_error` is set            |

## 7. Frontend Realtime Transcript Debug panel

Every figure is sourced from local `realtime.diagnostics` AND mirrored
against the server's `state.transcript_stats` so a divergence is
immediately visible.

| Field                | Source                                              |
| -------------------- | --------------------------------------------------- |
| data channel state   | local `RTCDataChannel.readyState`                   |
| last event type      | local listener                                      |
| committed / delta / completed / failed counts | local listener   |
| server completed     | `state.transcript_stats.completed_count`            |
| last transcript      | local **or** `state.transcript_stats.last_completed_transcript` |
| ingest status / error| `POST` response on `/realtime-events`               |
| transcription failed | `payload.error.message`                             |
| openai error         | `error` event body                                  |
| server `last_error`  | `state.transcript_stats.last_error`                 |

Server-confirmed turns are rendered first (they are what the harness
will analyze). The local optimistic mirror only shows when the server
has not caught up yet.

## 8. User confirmation rules (re-affirmed)

- Medication schedule drafts: `requires_user_confirmation: true`,
  `confirmation_status: "pending"`. Missing fields produce a parallel
  confirmation task.
- Caregiver notifications: draft only — never auto-sent. The UI
  exposes a "copy" button only.
- Memory candidates: never written until `/memory-candidates/:id/confirm`.
- Safety Guardrail blocks: doctor-audit, diagnosis, treatment advice,
  medication change, auto-reminder, auto-caregiver-send,
  unconfirmed memory write, unsupported inference, missing source.

## 9. Tests

- `transcriptVisibility.spec.ts` — 7 reducer-level cases (committed →
  delta → completed; late delta; duplicate completed; failed; error;
  completed-before-committed; partial-only).
- `transcriptIngestService.spec.ts` — service-level: GET returns
  turns; duplicate completed does not double-trigger Codex; failed
  event surfaces; error event records `last_error`.
- All previously passing tests still pass (`npm run carenote:test` —
  14 suites, 63 tests).

## 10. Smoke runbook

```bash
cd ~/Zai/backend

# health: confirms codex-cli runtime is selected, ChatGPT subscription auth.
npm run carenote:codex:health

# single role smoke (new alias works):
npm run carenote:codex:smoke-role -- transcript_verification --inline \
  "Please take this medicine once a day after meals for three days."
# expected: quality=medium, ambiguity:drug_name, suggested confirmation question.

# full Realtime replay through the harness:
npm run carenote:smoke:replay-transcript -- --inline \
  "Please take this medicine once a day after meals for three days."
# expected:
#   turn_count: 1, completed_turns: 1
#   transcript_stats.completed_count: 1
#   transcript_verifications[0].quality: high|medium  (with drug_name ambiguity)
#   clarifying_questions: include "What is the name of this medicine?" + dose questions
#   draft_reminders[0].status: needs_user_confirmation
#   draft_reminders[0].blocking_missing_fields: includes "medication_name" and "dose"
#   draft_reminders[0].requires_user_confirmation: true
#   caregiver_notifications[0].requires_user_confirmation: true
#   caregiver_notifications[0].confirmation_status: pending
#   analyzed_item_ids: ["itm-..."]

# all tests:
npm run carenote:test
npx tsc --noEmit
```

## 11. Limitations

- Speaker labels are not yet propagated from the
  `speaker_role` agent into `VisitState.turns[].speaker_label`. The
  field exists; wiring lands when M8 introduces persistent
  speaker-diarization storage.
- The Caregiver Notification draft is per-turn, not yet aggregated for
  end-of-visit. The `final_visit_summary` agent already exists and
  will own the end-of-visit version.
- M8 (Postgres / JWT / SSE / persistent visit storage) intentionally
  deferred.
- Raw audio storage stays default-off.
