// VisitStateReducer — deterministic, code-only merge from a TurnEnvelope
// (post-guardrail) into the persistent VisitState.
//
// Hard rules enforced here regardless of agent output:
//   1. Facts without source_turn_ids are dropped.
//   2. Every draft task / reminder / memory candidate is forced to
//      requires_user_confirmation = true and confirmation_status = "pending".
//   3. Direct memory writes are not allowed; only memory candidates flow in.
//   4. Medication reminders missing any of {medication_name, dose,
//      frequency, timing, duration} have status = "needs_user_confirmation"
//      and a parallel confirmation_task is appended if absent.

import { randomUUID } from "node:crypto";

import type {
  ClarifyingQuestion,
  DraftMedicationReminder,
  DraftTask,
  ExtractedFact,
  MemoryCandidate,
  NoiseFilterOutput,
  NoiseTagsRecord,
  SafetyFlag,
  VisitState,
} from "./medicalSchemas";
import type { TurnEnvelope } from "../codex-harness/codexGuardrailReducer";

export type ReduceResult = {
  next: VisitState;
  rejected: { kind: string; reason: string }[];
};

// Content fingerprints for dedup. The agent-generated fact_id/task_id/etc.
// are regenerated on every re-emission so they're useless as identity keys;
// instead we hash the semantic content + source attribution. The reducer
// uses these to drop already-seen items inside `mergeUnique`.
//
// Why this is needed: analyze_turn batches several transcript turns into one
// job whose canonical turn_id is the LAST member's id. The multi-pass
// commit-partial flow strips by canonical turn_id then re-reduces; items the
// LLM attributed to non-canonical members survive every strip and would
// otherwise accumulate one copy per pass (4× duplication).
function srcKey(ids: readonly string[] | undefined | null): string {
  return [...(ids ?? [])].sort().join(",");
}
function factKey(f: ExtractedFact): string {
  return `${f.fact_type}|${f.original_text}|${srcKey(f.source_turn_ids)}`;
}
function taskKey(t: DraftTask): string {
  return `${t.task_type}|${t.title}|${t.description}|${srcKey(t.source_turn_ids)}`;
}
function reminderKey(r: DraftMedicationReminder): string {
  return [
    r.medication_name ?? "",
    r.dose ?? "",
    r.frequency ?? "",
    r.timing ?? "",
    r.duration ?? "",
    srcKey(r.source_turn_ids),
  ].join("|");
}
function questionKey(q: ClarifyingQuestion): string {
  return `${q.question}|${srcKey(q.source_turn_ids)}`;
}
function memoryKey(m: MemoryCandidate): string {
  return `${m.memory_type}|${m.content}|${srcKey(m.source_turn_ids)}`;
}
function flagKey(s: SafetyFlag): string {
  return `${s.flag_type}|${s.message}|${srcKey(s.source_turn_ids)}`;
}

// Merge `incoming` onto `prev`, dropping duplicates by content fingerprint.
// We also collapse duplicates within `prev` itself, so any state that was
// polluted before this reducer learned to dedup gets cleaned the next time
// anything reduces against it (no migration script needed).
function mergeUnique<T>(prev: T[], incoming: T[], keyFn: (t: T) => string): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  let dropped = 0;
  for (const item of prev) {
    const k = keyFn(item);
    if (seen.has(k)) {
      dropped += 1;
      continue;
    }
    seen.add(k);
    result.push(item);
  }
  for (const item of incoming) {
    const k = keyFn(item);
    if (seen.has(k)) continue;
    seen.add(k);
    result.push(item);
  }
  if (dropped === 0 && result.length === prev.length) return prev;
  return result;
}

const REQUIRED_MED_FIELDS: (keyof DraftMedicationReminder)[] = [
  "medication_name",
  "dose",
  "frequency",
  "timing",
  "duration",
];

export function reduceTurn(prev: VisitState, env: TurnEnvelope): ReduceResult {
  const rejected: { kind: string; reason: string }[] = [];

  const facts: ExtractedFact[] = [];
  for (const f of env.facts) {
    if (!f.source_turn_ids || f.source_turn_ids.length === 0) {
      rejected.push({ kind: "fact", reason: "missing source_turn_ids" });
      continue;
    }
    facts.push({
      ...f,
      fact_id: f.fact_id ?? `f-${randomUUID()}`,
      requires_confirmation: f.fact_type === "medication" || f.fact_type === "dosage" || f.fact_type === "allergy" ? true : f.requires_confirmation,
      created_at: f.created_at ?? new Date().toISOString(),
    });
  }

  const draft_tasks: DraftTask[] = [];
  for (const t of env.draft_tasks) {
    draft_tasks.push(forceDraft(t));
  }

  const draft_reminders: DraftMedicationReminder[] = [];
  const synthesizedConfirmTasks: DraftTask[] = [];
  for (const r of env.draft_reminders) {
    const reminder = forceDraft(r) as DraftMedicationReminder;
    const missing = REQUIRED_MED_FIELDS.filter((k) => {
      const v = (reminder as unknown as Record<string, unknown>)[k as string];
      return v == null || v === "";
    }) as string[];
    reminder.blocking_missing_fields = missing;
    reminder.status =
      missing.length > 0
        ? "needs_user_confirmation"
        : (reminder.status ?? "complete_pending_confirmation");
    draft_reminders.push(reminder);

    if (
      missing.length > 0 &&
      !env.draft_tasks.some(
        (t: DraftTask) =>
          t.task_type === "question" &&
          t.source_fact_ids?.some((s: string) => reminder.source_fact_ids.includes(s)),
      )
    ) {
      synthesizedConfirmTasks.push(
        forceDraft({
          task_id: `t-${randomUUID()}`,
          task_type: "question",
          title: "Confirm medication details",
          description:
            "Please confirm the following missing fields with your doctor or pharmacist: " +
            missing.join(", "),
          source_fact_ids: reminder.source_fact_ids,
          source_turn_ids: reminder.source_turn_ids,
          requires_user_confirmation: true,
          confirmation_status: "pending",
          created_at: new Date().toISOString(),
        }),
      );
    }
  }

  const clarifying_questions: ClarifyingQuestion[] = env.clarifying_questions.map(
    (q: ClarifyingQuestion) => ({
      ...q,
      question_id: q.question_id ?? `q-${randomUUID()}`,
      source_turn_ids: q.source_turn_ids?.length ? q.source_turn_ids : [env.turn_id],
    }),
  );

  const memory_candidates: MemoryCandidate[] = [];
  for (const m of env.memory_candidates) {
    if (!m.source_turn_ids || m.source_turn_ids.length === 0) {
      rejected.push({ kind: "memory_candidate", reason: "missing source_turn_ids" });
      continue;
    }
    memory_candidates.push({
      ...m,
      memory_candidate_id: m.memory_candidate_id ?? `mc-${randomUUID()}`,
      requires_user_confirmation: true,
      confirmation_status: "pending",
      created_at: m.created_at ?? new Date().toISOString(),
    });
  }

  const safety_flags: SafetyFlag[] = env.safety_flags.map((s: SafetyFlag) => ({
    ...s,
    flag_id: s.flag_id ?? `sf-${randomUUID()}`,
    source_turn_ids: s.source_turn_ids?.length ? s.source_turn_ids : [env.turn_id],
  }));

  // M7.6: transcript_verifications + caregiver_notifications.
  const transcript_verifications = env.transcript_verification
    ? [...prev.transcript_verifications, env.transcript_verification]
    : prev.transcript_verifications;

  const caregiver_notifications = env.caregiver_notification
    ? [
        ...prev.caregiver_notifications,
        {
          ...env.caregiver_notification,
          // Force-pin draft semantics regardless of agent output.
          requires_user_confirmation: true as const,
          confirmation_status: "pending" as const,
        },
      ]
    : prev.caregiver_notifications;

  const next: VisitState = {
    ...prev,
    facts: mergeUnique(prev.facts, facts, factKey),
    draft_tasks: mergeUnique(
      prev.draft_tasks,
      [...draft_tasks, ...synthesizedConfirmTasks],
      taskKey,
    ),
    draft_reminders: mergeUnique(prev.draft_reminders, draft_reminders, reminderKey),
    clarifying_questions: mergeUnique(
      prev.clarifying_questions,
      clarifying_questions,
      questionKey,
    ),
    transcript_verifications,
    caregiver_notifications,
    family_summary_deltas: env.family_summary_delta
      ? [...prev.family_summary_deltas, env.family_summary_delta]
      : prev.family_summary_deltas,
    memory_candidates: mergeUnique(prev.memory_candidates, memory_candidates, memoryKey),
    safety_flags: mergeUnique(prev.safety_flags, safety_flags, flagKey),
  };

  return { next, rejected };
}

function forceDraft<T extends Partial<DraftTask>>(t: T): DraftTask {
  // Spread the input first, then OVERWRITE the safety-critical fields. The
  // order matters: agent output cannot opt out of confirmation.
  return {
    ...(t as object),
    task_id: t.task_id ?? `t-${randomUUID()}`,
    task_type: (t.task_type ?? "other") as DraftTask["task_type"],
    title: t.title ?? "(draft)",
    description: t.description ?? "",
    due_at: t.due_at ?? null,
    recurrence: t.recurrence ?? null,
    source_fact_ids: t.source_fact_ids ?? [],
    source_turn_ids: t.source_turn_ids ?? [],
    requires_user_confirmation: true,
    confirmation_status: "pending",
    created_at: t.created_at ?? new Date().toISOString(),
  } as unknown as DraftTask;
}

/**
 * Apply a transcript_noise_filter result to VisitState:
 *   1. Strip every noise_high_conf turn's contributions from facts /
 *      drafts / clarifying_questions / verifications / family_summary_deltas
 *      / caregiver_notifications / memory_candidates / safety_flags so the
 *      panels stop showing noise-amplified content.
 *   2. Drop any source_turn_ids entries that point at quarantined turns
 *      from items that are otherwise clean (the item itself stays).
 *   3. Persist the filter result as `noise_tags` so the UI can hide the
 *      quarantined turns and downstream agents can read the tags.
 *
 * Idempotent: re-applying the same filter (or a stricter one) is safe.
 * Calling with an empty `turn_tags` is a no-op (noise_tags still updates).
 */
export function applyNoiseFilter(
  prev: VisitState,
  filter: NoiseFilterOutput,
  opts: { round_index?: number | null } = {},
): VisitState {
  const quarantined = new Set(
    filter.turn_tags
      .filter((t) => t.tag === "noise_high_conf")
      .map((t) => t.turn_id),
  );

  let next = prev;
  for (const id of quarantined) {
    next = removeTurnContributions(next, id);
  }

  // Strip quarantined ids from the source_turn_ids of survivors. Drop items
  // whose only sources are now gone — that catches cases where a clean turn
  // produced an output that referenced a quarantined turn alongside itself.
  const cleanSources = <T extends { source_turn_ids?: string[] }>(arr: T[]): T[] =>
    arr
      .map((it) => ({
        ...it,
        source_turn_ids: (it.source_turn_ids ?? []).filter(
          (id) => !quarantined.has(id),
        ),
      }))
      .filter((it) => (it.source_turn_ids ?? []).length > 0);

  next = {
    ...next,
    facts: cleanSources(next.facts),
    draft_tasks: cleanSources(next.draft_tasks),
    draft_reminders: cleanSources(next.draft_reminders),
    clarifying_questions: cleanSources(next.clarifying_questions),
    memory_candidates: cleanSources(next.memory_candidates),
    safety_flags: cleanSources(next.safety_flags),
    transcript_verifications: next.transcript_verifications
      .map((v) => ({
        ...v,
        ambiguities: v.ambiguities
          .map((a) => ({
            ...a,
            source_turn_ids: a.source_turn_ids.filter((id) => !quarantined.has(id)),
          }))
          .filter((a) => a.source_turn_ids.length > 0),
        source_turn_ids: v.source_turn_ids.filter((id) => !quarantined.has(id)),
      }))
      .filter((v) => !quarantined.has(v.turn_id)),
    caregiver_notifications: next.caregiver_notifications
      .map((n) => ({
        ...n,
        source_turn_ids: n.source_turn_ids.filter((id) => !quarantined.has(id)),
      }))
      .filter((n) => !(n.turn_id && quarantined.has(n.turn_id))),
    family_summary_deltas: next.family_summary_deltas
      .map((d) => ({
        ...d,
        source_turn_ids: d.source_turn_ids.filter((id) => !quarantined.has(id)),
      }))
      .filter((d) => !quarantined.has(d.turn_id)),
  };

  const record: NoiseTagsRecord = {
    turn_tags: filter.turn_tags,
    summary: filter.summary,
    round_index: opts.round_index ?? null,
    applied_at: new Date().toISOString(),
  };
  return { ...next, noise_tags: record };
}

/** Rejects a memory write attempt; the harness must use memory_candidates. */
export function rejectMemoryWrite(): never {
  throw new Error(
    "VisitStateReducer rejects direct memory writes. Use memory_candidates only.",
  );
}

/**
 * Collapse duplicates inside the accumulator arrays of a VisitState. Used to
 * heal state that was written before the reducer learned to dedup (those
 * blobs persisted with up-to-4× copies of the same fact / question / flag).
 * Pure function; returns the same reference when nothing was deduped so
 * callers can cheaply detect "unchanged" via identity.
 */
export function dedupVisitState(state: VisitState): VisitState {
  const facts = mergeUnique(state.facts, [], factKey);
  const draft_tasks = mergeUnique(state.draft_tasks, [], taskKey);
  const draft_reminders = mergeUnique(state.draft_reminders, [], reminderKey);
  const clarifying_questions = mergeUnique(
    state.clarifying_questions,
    [],
    questionKey,
  );
  const memory_candidates = mergeUnique(state.memory_candidates, [], memoryKey);
  const safety_flags = mergeUnique(state.safety_flags, [], flagKey);
  if (
    facts === state.facts &&
    draft_tasks === state.draft_tasks &&
    draft_reminders === state.draft_reminders &&
    clarifying_questions === state.clarifying_questions &&
    memory_candidates === state.memory_candidates &&
    safety_flags === state.safety_flags
  ) {
    return state;
  }
  return {
    ...state,
    facts,
    draft_tasks,
    draft_reminders,
    clarifying_questions,
    memory_candidates,
    safety_flags,
  };
}

/**
 * Strip every contribution attributed to one turn_id. Used by the
 * incremental-streaming reducer in CodexRunManager: each pass writes a
 * partial envelope so the visit page panels populate progressively, and
 * the next pass calls this helper to clear the previous partial before
 * re-reducing with a richer envelope. The final guardrail step replaces
 * the partial with the safe (filtered) envelope.
 *
 * Match rule: any item whose `source_turn_ids` contains `turn_id`, plus
 * records keyed directly by `turn_id` (transcript_verifications,
 * caregiver_notifications, family_summary_deltas).
 */
export function removeTurnContributions(
  prev: VisitState,
  turn_id: string,
): VisitState {
  const sourceMatch = (item: { source_turn_ids?: string[] }) =>
    !(item.source_turn_ids?.includes(turn_id) ?? false);
  return {
    ...prev,
    facts: prev.facts.filter(sourceMatch),
    draft_tasks: prev.draft_tasks.filter(sourceMatch),
    draft_reminders: prev.draft_reminders.filter(sourceMatch),
    clarifying_questions: prev.clarifying_questions.filter(sourceMatch),
    transcript_verifications: prev.transcript_verifications.filter(
      (v) => v.turn_id !== turn_id,
    ),
    caregiver_notifications: prev.caregiver_notifications.filter(
      (n) => n.turn_id !== turn_id,
    ),
    family_summary_deltas: prev.family_summary_deltas.filter(
      (d) => d.turn_id !== turn_id,
    ),
    memory_candidates: prev.memory_candidates.filter(sourceMatch),
    safety_flags: prev.safety_flags.filter(sourceMatch),
  };
}
