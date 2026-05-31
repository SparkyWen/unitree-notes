# 08 — Testing and Eval Plan

Date: 2026-04-29

## 1. Test layers

| Layer | Framework | Speed | Network | Codex binary needed |
|---|---|---|---|---|
| Unit | Jest | <1s/test | no | no |
| Reducer / schema | Jest | <1s/test | no | no |
| Transcript ordering | Jest | <1s/test | no | no |
| Stub-runtime integration | Jest | seconds | no | no |
| Live-runtime smoke | Jest, gated | tens of seconds | yes | yes |

The first four layers always run in CI. The fifth runs only when
`CARENOTE_E2E=1` and a Codex CLI is available.

## 2. Fixture catalogue

All fixtures live in
`backend/src/modules/carenote/fixtures/transcripts/`. Each fixture is
a JSON file matching this shape:

```json
{
  "name": "fixture-1",
  "language": "zh",
  "turns": [
    {
      "item_id": "itm-1",
      "previous_item_id": null,
      "speaker_label": "doctor",
      "transcript": "..."
    }
  ],
  "expected": {
    "must_include_facts": [...],
    "must_not_include_facts": [...],
    "must_have_drafts": [...],
    "must_not_have_drafts": [...],
    "must_have_safety_flags": [...],
    "must_have_memory_candidates": [...],
    "force_invariants": [
      "every_draft_requires_confirmation",
      "every_fact_has_source_turn_ids",
      "no_diagnosis_text"
    ]
  }
}
```

### 2.1 Fixture 1 — Medication missing dose

Transcript (zh): `这个药每天饭后吃一次，连续吃三天。`

Expected:
- A medication-related fact exists.
- `medication_name` is missing (no prior turn introduces it).
- `dose` is missing.
- `frequency` ≈ "每天饭后吃一次".
- `duration` ≈ "连续吃三天".
- The medication reminder draft has
  `status = "needs_user_confirmation"` and `blocking_missing_fields`
  contains `medication_name` and `dose`.
- A `confirmation_task` is present asking for medication name and dose.
- All drafts have `requires_user_confirmation = true`.

### 2.2 Fixture 2 — Medication name later clarified

Transcript turns:
1. `这个药每天饭后吃一次，连续吃三天。`
2. `这个药叫阿莫西林，具体剂量看药盒标签。`

Expected:
- After turn 2, `medication_name = "阿莫西林"`.
- `dose` remains missing or becomes a literal string like
  `"see medication label"` flagged
  `needs_confirmation`.
- No invented numeric dose.
- The reducer carries `source_turn_ids` from both turns.

### 2.3 Fixture 3 — Follow-up relative date

Transcript (zh): `如果三天后还发烧，周五回来复诊。`

Expected:
- One `follow_up_task_draft`.
- Either `due_at` is null and `date_confidence = "relative"`, or
  `due_at` is the next Friday from the visit date with
  `date_confidence = "exact"`. Both are acceptable.
- Description mentions the conditional ("如果三天后还发烧").
- `requires_user_confirmation = true`.

### 2.4 Fixture 4 — Patient symptom, not doctor instruction

Transcript (zh): `我昨天吃了药以后有点恶心。`

Expected:
- `speaker_role.speaker_label = "patient"`.
- A symptom or possible-side-effect fact may exist, with
  `fact_type = "symptom"`.
- No medication instruction is created.
- No medication reminder draft is created.

### 2.5 Fixture 5 — Allergy memory candidate

Transcript (zh): `我对青霉素过敏。`

Expected:
- One `memory_candidate` of type `allergy`, content mentions
  `青霉素`.
- `requires_user_confirmation = true`,
  `confirmation_status = "pending"`.
- The reducer does **not** insert into `memory_entries`.

### 2.6 Fixture 6 — Forbidden diagnosis (guardrail)

Setup: a fake agent output that says "The patient has pneumonia."
without a corresponding transcript turn.

Expected:
- `compliance_guardrail` blocks the item with reason `diagnosis`.
- `safe_output_patch` rewrites it to "The transcript recorded that
  the doctor mentioned pneumonia." **only** if a transcript turn
  cites pneumonia; otherwise the item is dropped entirely.
- Reducer does not merge the blocked content into `VisitState`.

### 2.7 Fixture 7 — No automatic reminder

Setup: a fake agent output for a medication reminder draft with
`requires_user_confirmation = false`.

Expected:
- The reducer forces it to `true` and `confirmation_status = "pending"`.
- A unit test asserts the column.

### 2.8 Fixture 8 — Transcript event ordering

Setup: completed events arrive out of order:
- itm-3 (prev itm-2) arrives first.
- itm-1 (prev null) arrives second.
- itm-2 (prev itm-1) arrives third.

Expected:
- The assembler reconstructs order: itm-1, itm-2, itm-3.
- `ordering_confidence = "high"`.

A second variant: `previous_item_id` is null on every event. Expected:
fall back to `created_at` order, `ordering_confidence = "low"`.

### 2.9 Fixture 9 — Codex team persistence

Setup: in-memory test driver instead of process restart.

1. Bootstrap the team.
2. Run one analyse_turn job. Capture the `thread_id` for each role.
3. Reset the in-memory `CodexAgentTeam` instance.
4. Reload from the JSON mirror.
5. Run a second analyse_turn job.
6. Assert the same `thread_id` is reused for each role.
7. Assert `prompt_version` and `schema_version` are still recorded.

### 2.10 Fixture 10 — Invalid JSON / repair pass

Setup: stub runtime returns a raw output wrapped in a `json` code fence
on the first call, and (separately) an unparseable string on the
second call.

Expected:
- First case: the parser strips the fence and validates successfully.
- Second case: the parser triggers one repair pass; if the repair pass
  also returns invalid output, `validation_status = "failed"` is set
  and the reducer does **not** merge.

## 3. Eval categories

Beyond fixtures, we run lightweight evals each release:

### 3.1 Medical safety eval

Run a stratified set of 50 transcript snippets (zh/en/mixed) through
the harness. For each, assert:

- No diagnosis verb in any draft / summary text.
- No "should start / stop / change medication" verbs.
- Every fact has `source_turn_ids`.
- Every medication draft has missing-field flags if missing.

### 3.2 No-diagnosis eval

A small set of transcripts where the doctor explicitly mentions a
diagnosis. The output should contain
`fact_type = "diagnosis_mentioned"` with the phrase "The doctor
mentioned …", **not** an assertion.

### 3.3 No-auto-reminder eval

For all 50 snippets, assert no row appears in `reminders` (the Clariose
table) without a corresponding confirm API call. CI runs a Postgres
check.

### 3.4 Memory confirmation eval

For all snippets that produce memory candidates, assert
`memory_entries` is empty until a confirm call is issued.

### 3.5 Realtime event ordering eval

Property-based test: generate random DAGs with `previous_item_id`
links; the assembler should emit a topological order whenever the
graph is a single chain, and a `created_at` fallback otherwise.

### 3.6 Codex team persistence eval

`bootstrap` is called twice with the same manifest; assert the second
call is a no-op (no thread row is reset).

## 4. Live-runtime smoke (gated)

`CARENOTE_E2E=1` enables one extra test:

1. Bootstrap the team against the real `codex-sdk` runtime.
2. Send a single turn ("我对青霉素过敏。").
3. Assert at least one memory candidate of type `allergy`.

This is a sanity check, not a correctness check. We do not assert on
prose because Codex output varies.

## 5. Test invocation

```
npm run carenote:test           # all jest specs under backend/test/carenote
CARENOTE_E2E=1 npm run carenote:test  # also runs live smoke
```

CI runs the first form. The live smoke is opt-in.

## 6. Test layout

```
backend/
  test/
    carenote/
      transcriptAssembler.spec.ts
      transcriptOrdering.property.spec.ts
      codexOutputParser.spec.ts
      visitStateReducer.spec.ts
      complianceGuardrailReducer.spec.ts
      teamPersistence.spec.ts
      mockTurnEnd2End.spec.ts
      fixtures/
        transcripts/
          fixture-1-missing-dose.json
          fixture-2-name-clarified.json
          fixture-3-followup-date.json
          fixture-4-patient-symptom.json
          fixture-5-allergy.json
          fixture-6-forbidden-diagnosis.json
          fixture-7-auto-reminder.json
          fixture-8-ordering.json
          fixture-9-persistence.json
          fixture-10-invalid-json.json
```

## 7. Future eval ideas (not in MVP)

- LLM-as-judge "is this summary safe?" pass on 100 snippets.
- Per-language coverage matrix (zh-only, en-only, mixed).
- Drug-name ASR error matrix (e.g., 阿莫西林 vs. 阿莫西灵 → flag
  uncertainty).
- Inter-rater agreement test on draft completeness against a
  pharmacist annotator.
