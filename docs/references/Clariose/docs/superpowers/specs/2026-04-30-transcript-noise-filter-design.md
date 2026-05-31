# Transcript Noise Filter & Agent Prompt Hardening — Design

Date: 2026-04-30
Branch: `fix/update-prompt`
Status: design approved (brainstorming complete) — ready for implementation

## Problem

The CareNote multi-agent team (per-turn pipeline in `codexRunManager.ts`) treats every transcript turn as equal-weight signal. ASR errors (e.g. `"doctor"` mis-heard as `"water"`), conversational filler (`"yeah"`, `"okay"`), and off-topic chitchat are amplified by the team because each agent independently flags the same fragment. A single mis-heard word in a real consult produced **27 questions** from the question helper, **6 verifier flags**, and noise-laden family / nurse / postie outputs.

Two compounding causes:

1. **No upstream noise classifier.** Every agent sees raw turns and decides for itself whether a fragment is meaningful, which causes the team to over-react to junk.
2. **No cross-agent deduplication.** When the Transcript Verifier already asks "Was 'water' part of care?", four other agents independently regenerate the same question.

## Goals

1. Add a **Pass 0** noise filter that runs once at manual pause, classifies every turn, and tags the results so downstream agents can skip noise without judging it themselves.
2. Update every existing agent prompt so quarantined turns (a) cannot appear in their outputs and (b) cannot generate duplicate questions/flags already produced by the Transcript Verifier.
3. UI hides high-confidence noise turns by default with a "show hidden" affordance — never permanently delete.
4. Keep all prompts in English, JSON-only, with explicit `source_turn_ids` discipline.

## Non-goals

- No streaming-time noise filter this iteration (per-turn stays unchanged; filter only runs at pause).
- No active rewrite/correction of mis-heard words (we only tag — option B from brainstorming, not option C).
- No re-running the entire per-turn pipeline at pause; we strip noise contributions and run a one-shot regenerate over the cumulative agents.

## Architecture

### Pause-time flow

```
[user clicks Pause/End]
   │
   ▼  Pass 0 (NEW) — transcript_noise_filter
   │  Whole-transcript classifier; emits per-turn tags + summary
   │
   ▼  Reducer — strip contributions of every `noise_high_conf` turn
   │  Persist NoiseFilterResult on visit_state.noise_tags
   │  UI re-renders panels from cleaned VisitState
   │
   ▼  One-shot regenerate (parallel × 4) on cleaned envelope:
   │   - safety_clarification  (dedup-aware, sees verifier output)
   │   - medication_reminder_draft
   │   - family_summary
   │   - memory_update
   │
   ▼  compliance_guardrail (re-run on regenerated envelope)
   │
   ▼  final_visit_summary (sees noise_tags + cleaned envelope)
```

Total new LLM cost at pause: 1 (filter) + 4 (regenerate) + 1 (guardrail) + 1 (final summary) = **7 calls**.

### Failure mode

If `transcript_noise_filter` returns invalid JSON or errors, fall back to **no-op**: every turn implicitly tagged `clean`, the rest of the pause-time flow proceeds. The filter is additive — it can only improve quality, never make it worse than today.

## Tag taxonomy

Per-turn tag with confidence. Categories aligned with brainstorming Q3:

| Tag                 | When                                                                              | Downstream behavior                              |
| ------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------ |
| `clean`             | Coherent clinical or relevant patient/family content                              | Used normally                                    |
| `partial`           | Cut-off mid-sentence (e.g., "and the dose should be—")                            | Usable as supporting context, not sole evidence  |
| `duplicate`         | Near-identical to an adjacent turn from same speaker (segmentation artifact)      | One copy is canonical, the other is suppressed   |
| `noise_low_conf`    | Filler / chitchat / weak ASR signal — possibly meaningful in context              | **Soft skip**: usable only when corroborated     |
| `noise_high_conf`   | ASR garbage / standalone implausible words / clear non-content                    | **Hard skip**: invisible to downstream agents    |

Categories surfaced under each tag (for telemetry and UI tooltips):

- `asr_artifact` — single-word or stub turns that don't fit the conversation (`"water"` standalone, `[inaudible]`, `"uh"`).
- `filler` — `"yeah"`, `"okay"`, `"got it"`, `"right"`. Default to `noise_low_conf` because filler can be a meaningful confirmation.
- `chitchat` — coherent but off-clinical-topic (weather, parking, billing).
- `implausible_word` — phonetically near a clinical term but standing alone with no surrounding context that supports it. Only `noise_high_conf` when both standalone AND phonetically close to a real clinical term.
- `partial_utterance` — cut-off content; emits `partial` not noise.
- `duplicate_segment` — segmentation duplicate; emits `duplicate` not noise.
- `clean` — default.

## New agent: `transcript_noise_filter`

Whole-transcript classifier. Receives the full ordered transcript with `item_id`s, returns per-turn tags. Calibration goal: **not too lenient, not too strict** — the prompt encodes explicit rules for when to escalate from `noise_low_conf` to `noise_high_conf` (corroboration / standaloneness / phonetic neighborhood test).

Output schema (JSON only):

```jsonc
{
  "turn_tags": [
    {
      "turn_id": "item_id",
      "tag": "clean | partial | duplicate | noise_low_conf | noise_high_conf",
      "category": "clean | asr_artifact | filler | chitchat | implausible_word | partial_utterance | duplicate_segment",
      "confidence": "low | medium | high",
      "reason": "one short sentence",
      "phonetic_neighbor": "string | null"
    }
  ],
  "summary": {
    "total_turns": "integer",
    "clean": "integer",
    "noise_high_conf": "integer",
    "noise_low_conf": "integer",
    "partial": "integer",
    "duplicate": "integer"
  }
}
```

## Shared prompt deltas (added to every non-filter agent)

Two shared sections appended verbatim to each prompt — they encode the hard-skip rule and the cross-agent dedup rule.

### Section: Noise tag awareness

```
You receive each transcript turn with a noise tag assigned by the upstream
transcript noise filter:
  - clean
  - partial
  - duplicate
  - noise_low_conf
  - noise_high_conf

Hard rules:
- Turns tagged `noise_high_conf` are EXCLUDED. Do not read, reference, cite,
  flag, or generate any output mentioning them. For your purposes they do
  not exist.
- Turns tagged `noise_low_conf` may only be used when their content is
  corroborated by at least one `clean` turn (same fact, same intent). If not
  corroborated, treat them as `noise_high_conf`.
- Turns tagged `partial` or `duplicate` may be used as supporting context but
  must not be the sole `source_turn_ids` for a fact — pair them with a
  `clean` turn.
- Never emit a `source_turn_ids` value that points at a `noise_high_conf`
  turn.
- Never generate a clarifying question, safety flag, missing-field note, or
  family-summary line whose only evidence is a quarantined turn.
```

### Section: Cross-agent deduplication

```
The Transcript Verifier (transcript_quality / transcript_verification) runs
before you and may have already produced confirmation questions or
ambiguity flags. You will receive its output in your input context.

Hard rules:
- Do NOT regenerate a confirmation question for the same
  (source_turn_id, ambiguity field) pair the Verifier has already covered.
  Reference the Verifier's question id in `references_question_ids[]`
  instead of re-asking.
- Do NOT echo Verifier ambiguity flags as your own safety flags. Each agent
  must add its own value (e.g. medication-specific dosing concern, family
  notification implications) — never restate what the Verifier said.
- If you have nothing to add beyond what the Verifier produced, return an
  empty array for the corresponding output field. Empty is correct.
```

## Per-agent prompt changes

| Prompt file                         | Change                                                                                                                                                       |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `transcript_noise_filter.md` (NEW)  | New whole-transcript classifier (see schema above)                                                                                                           |
| `transcript_quality.md`             | Add Noise tag awareness; keep verifier role but explicitly note it should not flag content already classified `noise_high_conf`                              |
| `transcript_verification.md`        | Same as `transcript_quality.md` (paired)                                                                                                                     |
| `speaker_role.md`                   | Add Noise tag awareness; if all evidence comes from quarantined turns, return `unknown`                                                                      |
| `medical_instruction_extractor.md`  | Add Noise tag awareness; never extract a fact whose `source_turn_ids` is only `noise_high_conf`                                                              |
| `safety_clarification.md`           | Add both shared sections; rewrite to enforce dedup against verifier output (this is the agent that produced the 27-question cascade)                         |
| `clarification_question.md`         | Same as `safety_clarification.md` (paired)                                                                                                                   |
| `medication_reminder_draft.md`      | Add both shared sections; never list a medication whose only evidence is a quarantined turn                                                                  |
| `medication_schedule_draft.md`      | Same as `medication_reminder_draft.md` (paired)                                                                                                              |
| `follow_up_task_draft.md`           | Add both shared sections                                                                                                                                     |
| `family_summary.md`                 | Add both shared sections; never reference quarantined content in patient-facing language                                                                     |
| `caregiver_notification.md`         | Same as `family_summary.md` (paired)                                                                                                                         |
| `memory_update.md`                  | Add both shared sections; never propose a long-term memory candidate from a quarantined turn                                                                 |
| `compliance_guardrail.md`           | Add a new block reason `references_quarantined_turn`                                                                                                         |
| `safety_guardrail.md`               | Same as `compliance_guardrail.md` (paired)                                                                                                                   |
| `final_visit_summary.md`            | Add Noise tag awareness; surface `noise_tags.summary` as a one-line note at the end (e.g. "N hidden segments excluded as transcription noise")               |
| `visit_orchestrator.md`             | Add a sentence describing the new Pass 0 in the orchestration overview                                                                                       |

## Schema & code wiring (out of scope for the prompt PR, but listed for the follow-up plan)

The prompts can ship independently. The orchestration changes that activate them require:

1. New role enum value `transcript_noise_filter` in `medicalSchemas.ts`.
2. Entry in `CODEX_AGENT_PROMPT_FILES`.
3. New schema `NoiseFilterOutput` (matches the JSON shape above).
4. `VisitState.noise_tags` field (per-turn tag map).
5. Pause-time orchestration in `codexRunManager.ts`:
   - new `analyzeAtPause()` function that runs the Pass-0 → strip → regenerate-4 → guardrail → final-summary flow
   - reuse existing `removeTurnContributions()`
6. Frontend hide-toggle for quarantined turns in transcript & team panels.

## UI behavior

- Quarantined `noise_high_conf` turns: hidden by default, with a small "Show N hidden segments" toggle that reveals them greyed out with a tooltip explaining the reason.
- `noise_low_conf` turns: always rendered greyed out with a tooltip.
- `partial` / `duplicate` turns: rendered normally with a small icon.
- All quarantined turns must remain stored in the DB (`TranscriptUtterance` row untouched) — only the rendering and the agent input is filtered.

## Calibration test plan (manual)

Test the prompt's strict/lenient balance against three fixtures stored under `backend/test-fixtures/noise-filter/`:

1. The `"water" / fever / penicillin / dosing` example from the bug report → expect: `water` → `noise_high_conf`, three other turns → `clean`.
2. A clean consult with no noise → expect: every turn `clean`, zero quarantines.
3. A noisy consult with `"yeah"`, `"okay"`, `"thank you"` interspersed in genuine clinical content → expect: filler `noise_low_conf`, clinical content `clean`, no `noise_high_conf` (because none of the filler is ASR garbage).

Calibration succeeds when:
- Zero clinical content is misclassified as `noise_high_conf`.
- ≥80% of obvious ASR artifacts (single-word standalone turns that don't fit) are classified as `noise_high_conf`.
- All filler is `noise_low_conf` and downstream agents do not generate questions about them when uncorroborated.
