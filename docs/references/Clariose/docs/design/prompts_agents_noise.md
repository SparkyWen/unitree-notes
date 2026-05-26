# Transcript Noise Filter & Agent Prompt Hardening

Date: 2026-04-30
Branch: `fix/update-prompt`
Commits: `758b18d` (prompts), `9eb1558` (wiring)
Spec: `docs/superpowers/specs/2026-04-30-transcript-noise-filter-design.md`

## 1. Problem

The CareNote multi-agent team treats every transcript turn as equal-weight signal. ASR errors (e.g. `"doctor"` mis-heard as `"water"`), conversational filler (`"yeah"`, `"okay"`), and off-topic chitchat are amplified by the team because each agent independently flags the same fragment. A real consult that produced three meaningful turns plus one mis-heard `"water"` generated:

- 27 questions from the question-helper agent,
- 6 verifier ambiguity flags,
- 4 independent agents each asking "Was 'water' part of care?",
- noise-laden family / nurse / postie outputs,
- a guardrail block on a memory candidate built from the noise.

Two compounding causes:

1. **No upstream noise classifier.** Every agent sees raw turns and decides for itself whether a fragment is meaningful, so the team over-reacts to junk.
2. **No cross-agent deduplication.** When the Transcript Verifier already asks "Was 'water' part of care?", four other agents independently regenerate the same question.

## 2. Goals

1. Add a Pass-0 noise filter that runs once at manual pause, classifies every turn, and tags the result so downstream agents can skip noise without judging it themselves.
2. Update every existing agent prompt so quarantined turns (a) cannot appear in their outputs and (b) cannot generate duplicate questions / flags already produced by the Transcript Verifier.
3. UI hides high-confidence noise turns by default with a "Show hidden" toggle — never permanently delete.
4. Keep all prompts in English, JSON-only, with explicit `source_turn_ids` discipline.

## 3. Design decisions

| Q | Decision | Rationale |
| - | -------- | --------- |
| 1. What does the filter do to a noisy turn? | **Quarantine (tag, don't remove)** with confidence | Reversible; matches existing "draft + requires_user_confirmation" pattern. |
| 2. When does the filter run? | **Only at manual pause, whole-transcript pass** | A single global pass sees `"water"` against the surrounding fever / penicillin / dosing context; per-turn judgments are noisier. |
| 3. What counts as noise? | a (ASR garbage) + b (filler) + c (chitchat) with severity tiers; d (phonetically-implausible) high-precision-only; e (partial) + f (duplicate) get a tag, not a quarantine | Maximizes recall on real noise without false-quarantining clinical content. |
| 4. How do downstream agents and the UI behave? | **Hidden-but-recoverable** UI; **hard skip** for `noise_high_conf`, **corroboration-required** for `noise_low_conf`; cross-agent dedup against the Verifier | Kills the 4×-repeated-question cascade by construction. |
| 5. What about already-committed per-turn outputs? | **Strip quarantined-turn contributions from VisitState** (option C) | Re-uses existing `removeTurnContributions`; recap + final summary read the cleaned state. No per-turn re-runs. |

## 4. Pipeline at manual pause

```
user pauses
  → flush analyze_turn jobs for the closing round
  → wait queue idle (180s budget)
  ──────────────────────────────────────────────────────
  Pass 0: transcript_noise_filter (NEW, whole transcript)
    input:  every completed turn in the round
    output: NoiseFilterOutput { turn_tags[], summary }
  ──────────────────────────────────────────────────────
  Reducer: applyNoiseFilter(visit_state, output)
    1. for each turn tagged noise_high_conf:
         removeTurnContributions(visit_state, turn_id)
    2. drop quarantined turn_ids from survivors'
       source_turn_ids[] arrays
    3. drop items whose source_turn_ids[] becomes empty
    4. persist visit_state.noise_tags
  ──────────────────────────────────────────────────────
  recap (existing) reads cleaned state → infographic
  final_visit_summary (existing) sees noise_tags + cleaned envelope
  UI re-renders panels from the cleaned state
```

Total new LLM cost at pause: **1 call** (the noise filter).
The strip+reduce path means we do NOT re-pay for per-turn agents — they already produced outputs per surviving turn during the live consult; cleaning their contributions is free.

Failure mode: if `transcript_noise_filter` returns invalid JSON or errors, the orchestrator falls back to **default-clean** — every turn implicitly tagged `clean`, the rest of the pause-time flow proceeds. The filter is additive; it can only improve quality, never degrade below today.

## 5. Tag taxonomy

Per-turn tag with confidence and category.

| Tag | Behavior | UI |
| --- | -------- | -- |
| `clean` | Used normally | Renders as today |
| `partial` | Usable as supporting context, not sole evidence | Rendered with chip |
| `duplicate` | One copy canonical, the other suppressed | Rendered with chip |
| `noise_low_conf` | **Soft skip** — usable only when corroborated by ≥1 `clean` turn | Greyed-out, always visible |
| `noise_high_conf` | **Hard skip** — invisible to downstream agents | Hidden by default, recoverable via toggle |

Categories surfaced under each tag (telemetry + UI tooltips):

- `asr_artifact` — single-word or stub turns that don't fit the conversation (`"water"` standalone, `[inaudible]`, `"uh"`)
- `filler` — `"yeah"`, `"okay"`, `"got it"`, `"right"` — defaults to `noise_low_conf`
- `chitchat` — coherent off-clinical-topic content
- `implausible_word` — phonetically near a clinical term but standalone with no supporting context
- `partial_utterance` — cut-off content; emits `partial` not noise
- `duplicate_segment` — segmentation duplicate; emits `duplicate` not noise
- `clean` — default

## 6. New agent: `transcript_noise_filter`

File: `prompts/codex-agents/transcript_noise_filter.md`

**Calibration** (the single most important rule): err in the direction of *keeping* content that *might* be clinical. False quarantines hurt patient safety; false positives only add UI clutter.

A turn is `noise_high_conf` ONLY when ALL of:

1. It does not introduce a new clinical fact (no symptom / medication / dose / follow-up / test / allergy / diagnosis_mentioned / lifestyle advice / warning sign).
2. It is short (≤3 words) OR a transcription marker (`[Music]`, `[inaudible]`) OR coherent but unambiguously non-clinical AND not a confirmation of a clinical instruction.
3. Removing it does not break the meaning of surrounding turns.
4. For `implausible_word`: standalone AND no plausible reading where it is a real clinical term in context.

Default to `noise_low_conf` over `noise_high_conf` whenever uncertain. Default to `clean` over `noise_low_conf` for filler that *could* be a confirmation.

**Forbidden**: diagnose, prescribe, judge the doctor, guess the intended word and substitute it into the transcript text (the `phonetic_neighbor` hint is telemetry-only), modify or merge turns, quarantine a turn naming a real medication / dose / frequency / duration / follow-up date / test / allergy / symptom.

**Output schema** (`NoiseFilterOutputSchema`):

```jsonc
{
  "turn_tags": [
    {
      "turn_id": "string (item_id)",
      "tag": "clean | partial | duplicate | noise_low_conf | noise_high_conf",
      "category": "clean | asr_artifact | filler | chitchat | implausible_word | partial_utterance | duplicate_segment",
      "confidence": "low | medium | high",
      "reason": "one short sentence",
      "phonetic_neighbor": "string | null"
    }
  ],
  "summary": {
    "total_turns": 0,
    "clean": 0,
    "partial": 0,
    "duplicate": 0,
    "noise_low_conf": 0,
    "noise_high_conf": 0
  }
}
```

## 7. Shared prompt deltas (applied to every non-filter agent)

Two sections appended verbatim where they apply.

### 7.1 Noise tag awareness

```
You receive each transcript turn with a noise tag assigned by the
upstream Transcript Noise Filter:
  - clean, partial, duplicate, noise_low_conf, noise_high_conf

Hard rules:
- Turns tagged `noise_high_conf` are EXCLUDED. Do not read,
  reference, cite, flag, or generate any output mentioning them.
  For your purposes they do not exist.
- Turns tagged `noise_low_conf` may only be used when their content
  is corroborated by at least one `clean` turn. If not corroborated,
  treat them as `noise_high_conf`.
- Turns tagged `partial` or `duplicate` may be used as supporting
  context but must not be the sole `source_turn_ids` for a fact.
- Never emit `source_turn_ids` that point at a `noise_high_conf` turn.
- Never generate a clarifying question, safety flag, missing-field
  note, or family-summary line whose only evidence is a quarantined
  turn.
```

### 7.2 Cross-agent deduplication

```
The Transcript Verifier (transcript_quality / transcript_verification)
runs before you and may have already produced confirmation questions
or ambiguity flags. You receive its output in your input context.

Hard rules:
- Do NOT regenerate a confirmation question for the same
  (source_turn_id, ambiguity field) pair the Verifier has already
  covered. Reference the Verifier's question id in
  `references_question_ids[]` instead of re-asking.
- Do NOT echo Verifier ambiguity flags as your own safety flags.
  Each agent must add its own value (e.g. medication-specific dosing
  concern, family notification implications) — never restate what
  the Verifier said.
- If you have nothing to add beyond what the Verifier produced,
  return an empty array for the corresponding output field. Empty
  is correct.
```

## 8. Per-agent prompt changes

| Prompt file | Change summary |
| ----------- | -------------- |
| `transcript_noise_filter.md` | NEW — whole-transcript classifier (see §6) |
| `transcript_quality.md` | Adds Noise tag awareness; will not raise `asr_uncertain` against turns the filter already classified `noise_high_conf` |
| `transcript_verification.md` | Same as `transcript_quality.md`; explicitly notes it is the FIRST question-generating agent and sets the dedup baseline |
| `speaker_role.md` | Adds Noise tag awareness; if all evidence is quarantined, returns `unknown` |
| `medical_instruction_extractor.md` | Adds Noise tag awareness; never extracts a fact whose `source_turn_ids` is only `noise_high_conf` |
| `safety_clarification.md` | Adds both shared sections; rewritten to enforce dedup against Verifier output (this is the agent that produced the 27-question cascade) |
| `clarification_question.md` | Same as `safety_clarification.md` (paired) |
| `medication_reminder_draft.md` | Adds both shared sections; never lists a medication whose only evidence is a quarantined turn; new `references_question_ids[]` field on confirmation tasks |
| `medication_schedule_draft.md` | Same as `medication_reminder_draft.md` (paired) |
| `follow_up_task_draft.md` | Adds both shared sections; new `references_question_ids[]` on draft tasks |
| `family_summary.md` | Adds both shared sections; never references quarantined content in patient-facing language |
| `caregiver_notification.md` | Same as `family_summary.md` (paired); `needs_confirmation[]` focuses on caregiver actions, not doctor-patient questions |
| `memory_update.md` | Adds Noise tag awareness; **two clean corroborations required** for `noise_low_conf` evidence (stricter — memory writes are durable); confidence forced to `low` for any candidate with `noise_low_conf` evidence |
| `compliance_guardrail.md` | Adds two new block reasons: `references_quarantined_turn`, `duplicate_question` |
| `safety_guardrail.md` | Same as `compliance_guardrail.md` (paired) |
| `final_visit_summary.md` | Adds Noise tag awareness; emits a one-line Chinese disclaimer note when ≥1 `noise_high_conf` turn was filtered |
| `visit_orchestrator.md` | Adds the new Pass-0 step in the orchestration overview |

## 9. Backend wiring

### 9.1 Schemas (`backend/src/modules/carenote/medical/medicalSchemas.ts`)

- New role enum value: `transcript_noise_filter`.
- New display name: `"Transcript Noise Filter"`.
- New schemas: `NoiseTagSchema`, `NoiseCategorySchema`, `NoiseTurnTagSchema`, `NoiseFilterSummarySchema`, `NoiseFilterOutputSchema`, `NoiseTagsRecordSchema`.
- `VisitState.noise_tags: NoiseTagsRecord | null` (default `null`).
- `ComplianceGuardrailOutputSchema.blocked_items[].reason` gains `references_quarantined_turn` and `duplicate_question`.
- `RoleOutputSchemas` map gets `transcript_noise_filter: NoiseFilterOutputSchema`.

### 9.2 Reducer (`backend/src/modules/carenote/medical/medicalReducers.ts`)

New `applyNoiseFilter(prev, filter, opts)`:

1. For every turn tagged `noise_high_conf`, calls `removeTurnContributions(prev, turn_id)` (existing helper) — strips that turn's facts, drafts, clarifying_questions, transcript_verifications, caregiver_notifications, family_summary_deltas, memory_candidates, safety_flags.
2. Drops quarantined ids from survivors' `source_turn_ids[]` arrays. Items whose array becomes empty are dropped.
3. Persists the result as `visit_state.noise_tags` with `applied_at` and `round_index`.

Idempotent: re-applying the same filter (or a stricter one) is safe.

### 9.3 Orchestrator (`backend/src/modules/carenote/codex-harness/codexRunManager.ts`)

New `runPauseNoiseFilter({ visit_id, round_index })`:

1. Reads completed turns for the round (or all completed turns when `round_index` is null).
2. Builds an event with `event_kind: "pause_noise_filter"` and `full_transcript: [{ item_id, transcript }]`.
3. Calls `runRole<NoiseFilterOutput>("transcript_noise_filter", ...)`.
4. Falls back to default-clean if the agent returns invalid JSON.
5. Calls `applyNoiseFilter(visit, filter, { round_index })`.
6. Persists the cleaned state.
7. Emits `blackboard_updated { key: "noise_tags" }` so the SSE-subscribed UI refreshes.

### 9.4 Prompt assembler (`backend/src/modules/carenote/codex-harness/codexPromptAssembler.ts`)

`<visit_context>` now includes:

```
noise_filter: total=N clean=N noise_high_conf=N noise_low_conf=N partial=N duplicate=N
quarantined_turn_ids: <ids> | (none)
```

Downstream agents consume these lines per their "Noise tag awareness" sections; `final_visit_summary` uses the count for its disclaimer line.

### 9.5 Stub runtime (`backend/src/modules/carenote/codex-harness/stubRuntime.ts`)

When no API key is configured, a deterministic offline classifier mirrors the prompt's calibration:

- empty turn → `noise_high_conf` / `asr_artifact`
- transcription marker (`[Music]`, `[inaudible]`, …) → `noise_high_conf` / `asr_artifact`
- regex filler (`yeah / ok / okay / hmm / uh / um / right / got it / thanks / thank you`) → `noise_low_conf` / `filler`
- ≤2 words AND no clinical keyword → `noise_high_conf` / `asr_artifact`
- identical to previous turn → `duplicate` / `duplicate_segment`
- ends with `—`, `--`, or `…` → `partial` / `partial_utterance`
- otherwise → `clean`

Clinical keyword regex: `mg | tablet | capsule | pill | fever | cough | allergic | allergy | prescription | prescribe | dose | symptom | test | x-?ray | blood | fasting | follow.?up | appointment | 药 | 剂量 | 过敏 | 复诊 | 症状 | 检查`.

### 9.6 Service (`backend/src/modules/carenote/api/carenote.service.ts`)

Two integration points:

- `endRound(visit_id)` — after the per-round flush + queue-idle wait, calls `manager.runPauseNoiseFilter({ visit_id, round_index: currentIdx })`. Errors are logged but do not block the recap. Runs in the existing fire-and-forget snapshot promise.
- `prepareRoundForRecap(visit_id, round_index)` — same call, runs synchronously before returning so the standalone "Recap current round" path also benefits. New `quarantined_turn_count` field added to the return type.

## 10. Frontend wiring

`frontend/pages/carenote/visit/[id].vue`:

- New `noiseTagMap` computed: `{ [item_id]: { tag, category, reason } }` derived from `state.noise_tags.turn_tags`.
- `showHiddenNoise` ref (default `false`).
- `visibleTurnsForRound(r)` — hides `noise_high_conf` turns when `showHiddenNoise` is false.
- `hiddenNoiseCountForRound(r)` — count for the toggle banner.
- Transcript-block summary header now shows `(N turns · M hidden)` and includes a "Show hidden" / "Hide noise" toggle.
- Per-turn rendering:
  - `noise_high_conf` → amber tinted background, opacity 60%, amber tag chip
  - `noise_low_conf` → neutral background, opacity 75%, grey tag chip
  - `partial` / `duplicate` → sky-blue tag chip, normal styling
  - `clean` → no chip, no opacity change

## 11. Config & manifest

- `config/codex-teams/carenote-doctor-visit.team.json` — new `transcript_noise_filter` agent entry with `thread_policy: "transient"` (whole-transcript pass, no per-turn thread reuse).
- `.codex/agents/carenote_transcript_noise_filter.toml` — codex agent definition with `sandbox_mode = "read-only"`, `network_access = false`.
- `backend/src/modules/carenote/prompts/codexAgentPrompts.ts` — prompt-file path entry.

## 12. Verification

Run from repo root:

```bash
cd backend && npx tsc --noEmit         # clean
cd backend && npm run build            # nest build → dist/main.js
cd frontend && npm run build           # nuxt build → .output/
```

Smoke tests run against the bug-report transcript (3 turns: `"water"` + fever-cough-allergy + dosing-instructions):

- `NoiseFilterOutputSchema` validates a hand-crafted output ✓
- `applyNoiseFilter()`:
  - facts: 2 → 1 (the `water` symptom fact is stripped, the penicillin-allergy fact survives) ✓
  - clarifying_questions: 2 → 1 (the "Was 'water' part of care?" question is stripped, the medication-name question survives) ✓
  - `noise_tags.summary.noise_high_conf == 1` ✓

## 13. Files changed

```
NEW:
  prompts/codex-agents/transcript_noise_filter.md
  .codex/agents/carenote_transcript_noise_filter.toml
  docs/superpowers/specs/2026-04-30-transcript-noise-filter-design.md
  docs/design/prompts_agents_noise.md (this file)

MODIFIED — prompts (16):
  prompts/codex-agents/transcript_quality.md
  prompts/codex-agents/transcript_verification.md
  prompts/codex-agents/speaker_role.md
  prompts/codex-agents/medical_instruction_extractor.md
  prompts/codex-agents/safety_clarification.md
  prompts/codex-agents/clarification_question.md
  prompts/codex-agents/medication_reminder_draft.md
  prompts/codex-agents/medication_schedule_draft.md
  prompts/codex-agents/follow_up_task_draft.md
  prompts/codex-agents/family_summary.md
  prompts/codex-agents/caregiver_notification.md
  prompts/codex-agents/memory_update.md
  prompts/codex-agents/compliance_guardrail.md
  prompts/codex-agents/safety_guardrail.md
  prompts/codex-agents/final_visit_summary.md
  prompts/codex-agents/visit_orchestrator.md

MODIFIED — backend wiring:
  backend/src/modules/carenote/medical/medicalSchemas.ts
  backend/src/modules/carenote/medical/medicalReducers.ts
  backend/src/modules/carenote/codex-harness/codexRunManager.ts
  backend/src/modules/carenote/codex-harness/codexPromptAssembler.ts
  backend/src/modules/carenote/codex-harness/stubRuntime.ts
  backend/src/modules/carenote/api/carenote.service.ts
  backend/src/modules/carenote/prompts/codexAgentPrompts.ts

MODIFIED — config:
  config/codex-teams/carenote-doctor-visit.team.json

MODIFIED — frontend:
  frontend/pages/carenote/visit/[id].vue
```

Two commits on `fix/update-prompt`:

- `758b18d feat: add transcript noise filter and harden agent prompts`
- `9eb1558 feat: wire transcript_noise_filter into pause-time pipeline`
