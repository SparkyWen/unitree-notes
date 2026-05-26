// CareNote schemas. Zod is the source of truth; we derive JSON Schema for
// Codex `outputSchema` and Postgres-typed shapes from these.
//
// Safety invariants enforced at the schema level:
//  - Every fact requires `source_turn_ids`.
//  - Every draft task / memory candidate requires
//    `requires_user_confirmation: true` and `confirmation_status: "pending"`.
//  - Reducers re-enforce these rules in code (medicalReducers.ts).

import { z } from "zod";

// -----------------------------------------------------------------------------
// Roles
// -----------------------------------------------------------------------------

export const CodexAgentRoleSchema = z.enum([
  "visit_orchestrator",
  // Pause-time noise classifier. Runs once over the whole transcript when
  // the user clicks Pause, tags every turn (clean / partial / duplicate /
  // noise_low_conf / noise_high_conf), and the reducer strips contributions
  // of noise_high_conf turns from VisitState before the recap fires.
  "transcript_noise_filter",
  // M7.6: presented in UI/docs as "Transcript Verification Agent". The
  // internal name stays for backwards compatibility with existing code,
  // tests, and the codex thread-state file. The prompt now performs
  // transcript-uncertainty verification — it does NOT audit the doctor.
  "transcript_quality",
  "speaker_role",
  "medical_instruction_extractor",
  // M7.6: presented as "Medication Schedule Draft Agent".
  "medication_reminder_draft",
  "follow_up_task_draft",
  // M7.6: presented as "Clarification Question Agent". Receives ambiguities
  // from transcript_quality + missing_fields from medical_instruction_extractor.
  "safety_clarification",
  // M7.6: presented as "Caregiver Notification Agent". Drafts only.
  "family_summary",
  "memory_update",
  // M7.6: presented as "Safety Guardrail Agent".
  "compliance_guardrail",
  "final_visit_summary",
]);
export type CodexAgentRole = z.infer<typeof CodexAgentRoleSchema>;

/** UI/doc-facing labels for agents (M7.6 redesign). */
export const CodexAgentDisplayNames: Record<CodexAgentRole, string> = {
  visit_orchestrator: "Visit Orchestrator",
  transcript_noise_filter: "Transcript Noise Filter",
  transcript_quality: "Transcript Verification Agent",
  speaker_role: "Speaker Role Agent",
  medical_instruction_extractor: "Medical Instruction Extractor",
  medication_reminder_draft: "Medication Schedule Draft Agent",
  follow_up_task_draft: "Follow-up Task Agent",
  safety_clarification: "Clarification Question Agent",
  family_summary: "Caregiver Notification Agent",
  memory_update: "Memory Candidate Agent",
  compliance_guardrail: "Safety Guardrail Agent",
  final_visit_summary: "Final Visit Summary",
};

// -----------------------------------------------------------------------------
// Transcript
// -----------------------------------------------------------------------------

export const SpeakerLabelSchema = z.enum(["doctor", "patient", "family", "unknown"]);
export type SpeakerLabel = z.infer<typeof SpeakerLabelSchema>;

export const TranscriptTurnStatusSchema = z.enum([
  "committed",
  "partial",
  "completed",
  "failed",
]);
export type TranscriptTurnStatus = z.infer<typeof TranscriptTurnStatusSchema>;

export const OrderingConfidenceSchema = z.enum(["high", "medium", "low"]);

export const TranscriptTurnSchema = z.object({
  visit_id: z.string(),
  item_id: z.string(),
  previous_item_id: z.string().nullable().optional(),
  status: TranscriptTurnStatusSchema,
  partial_transcript: z.string().nullable().optional(),
  transcript: z.string().nullable().optional(),
  speaker_label: SpeakerLabelSchema.nullable().optional(),
  ordering_confidence: OrderingConfidenceSchema.default("high"),
  source_model: z.literal("gpt-realtime-1.5"),
  transcription_model: z.string(),
  error: z.string().nullable().optional(),
  raw_events: z.array(z.unknown()).optional(),
  created_at: z.string(),
  completed_at: z.string().nullable().optional(),
});
export type TranscriptTurn = z.infer<typeof TranscriptTurnSchema>;

export const TranscriptStatsSchema = z.object({
  committed_count: z.number().int().nonnegative().default(0),
  partial_count: z.number().int().nonnegative().default(0),
  delta_count: z.number().int().nonnegative().default(0),
  completed_count: z.number().int().nonnegative().default(0),
  failed_count: z.number().int().nonnegative().default(0),
  last_event_type: z.string().nullable().default(null),
  last_completed_transcript: z.string().nullable().default(null),
  last_completed_transcript_at: z.string().nullable().default(null),
  last_partial_transcript: z.string().nullable().default(null),
  last_error: z.string().nullable().default(null),
  last_failed_at: z.string().nullable().default(null),
});
export type TranscriptStats = z.infer<typeof TranscriptStatsSchema>;

// -----------------------------------------------------------------------------
// Extracted facts
// -----------------------------------------------------------------------------

export const FactTypeSchema = z.enum([
  "medication",
  "dosage",
  "frequency",
  "duration",
  "timing",
  "follow_up",
  "test",
  "symptom",
  "allergy",
  "diagnosis_mentioned",
  "lifestyle_advice",
  "warning_sign",
  "referral",
  "other",
]);
export type FactType = z.infer<typeof FactTypeSchema>;

export const ConfidenceSchema = z.enum(["high", "medium", "low"]);

export const MedicationInstructionNormalizedSchema = z.object({
  medication_name: z.string().nullable().optional(),
  dose: z.string().nullable().optional(),
  frequency: z.string().nullable().optional(),
  timing: z.string().nullable().optional(),
  duration: z.string().nullable().optional(),
  route: z.string().nullable().optional(),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
});
export type MedicationInstructionNormalized = z.infer<typeof MedicationInstructionNormalizedSchema>;

export const NormalizedFactSchema = z.object({
  medication_name: z.string().nullable().optional(),
  dose: z.string().nullable().optional(),
  frequency: z.string().nullable().optional(),
  timing: z.string().nullable().optional(),
  duration: z.string().nullable().optional(),
  route: z.string().nullable().optional(),
  date: z.string().nullable().optional(),
  test_name: z.string().nullable().optional(),
  condition: z.string().nullable().optional(),
});

export const ExtractedFactSchema = z.object({
  fact_id: z.string(),
  fact_type: FactTypeSchema,
  original_text: z.string(),
  normalized: NormalizedFactSchema,
  missing_fields: z.array(z.string()).default([]),
  confidence: ConfidenceSchema,
  requires_confirmation: z.boolean(),
  source_turn_ids: z.array(z.string()).min(1),
  created_by_agent: CodexAgentRoleSchema,
  created_at: z.string(),
});
export type ExtractedFact = z.infer<typeof ExtractedFactSchema>;

// -----------------------------------------------------------------------------
// Drafts
// -----------------------------------------------------------------------------

export const ConfirmationStatusSchema = z.enum(["pending", "confirmed", "rejected"]);

export const DraftTaskTypeSchema = z.enum([
  "medication_reminder",
  "follow_up",
  "test",
  "collect_report",
  "referral",
  "question",
  "other",
]);

export const DraftTaskSchema = z.object({
  task_id: z.string(),
  task_type: DraftTaskTypeSchema,
  title: z.string(),
  description: z.string(),
  due_at: z.string().nullable().optional(),
  recurrence: z.unknown().optional(),
  source_fact_ids: z.array(z.string()).default([]),
  source_turn_ids: z.array(z.string()).min(1),
  requires_user_confirmation: z.literal(true),
  confirmation_status: z.literal("pending"),
  created_at: z.string(),
});
export type DraftTask = z.infer<typeof DraftTaskSchema>;

export const DraftMedicationReminderSchema = DraftTaskSchema.extend({
  task_type: z.literal("medication_reminder"),
  medication_name: z.string().nullable(),
  dose: z.string().nullable(),
  frequency: z.string().nullable(),
  timing: z.string().nullable(),
  duration: z.string().nullable(),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  status: z.enum(["needs_user_confirmation", "complete_pending_confirmation"]),
  blocking_missing_fields: z.array(z.string()).default([]),
});
export type DraftMedicationReminder = z.infer<typeof DraftMedicationReminderSchema>;

export const FollowUpTaskDraftSchema = DraftTaskSchema.extend({
  task_type: z.enum(["follow_up", "test", "collect_report", "referral", "question", "other"]),
  date_confidence: z.enum(["exact", "relative", "unclear"]).optional(),
});
export type FollowUpTaskDraft = z.infer<typeof FollowUpTaskDraftSchema>;

export const ClarifyingQuestionSchema = z.object({
  question_id: z.string(),
  question: z.string(),
  reason: z.string(),
  priority: z.enum(["low", "medium", "high"]),
  source_turn_ids: z.array(z.string()).min(1),
});
export type ClarifyingQuestion = z.infer<typeof ClarifyingQuestionSchema>;

export const FamilySummarySchema = z.object({
  family_summary: z.string(),
  important_to_confirm: z.array(z.string()).default([]),
  next_actions: z.array(z.string()).default([]),
  source_turn_ids: z.array(z.string()).default([]),
});
export type FamilySummary = z.infer<typeof FamilySummarySchema>;

export const MemoryTypeSchema = z.enum([
  "allergy",
  "medication",
  "condition",
  "clinician",
  "preference",
  "visit_pattern",
  "other",
]);

export const MemoryCandidateSchema = z.object({
  memory_candidate_id: z.string(),
  memory_type: MemoryTypeSchema,
  content: z.string(),
  confidence: ConfidenceSchema,
  source_turn_ids: z.array(z.string()).min(1),
  requires_user_confirmation: z.literal(true),
  confirmation_status: z.literal("pending"),
  created_at: z.string().optional(),
});
export type MemoryCandidate = z.infer<typeof MemoryCandidateSchema>;

export const SafetyFlagSchema = z.object({
  flag_id: z.string(),
  flag_type: z.enum([
    "missing_dose",
    "missing_medication_name",
    "unclear_follow_up",
    "possible_emergency",
    "transcription_uncertain",
    "allergy_needs_confirmation",
    "guardrail_blocked",
    "other",
  ]),
  severity: z.enum(["low", "medium", "high"]),
  message: z.string(),
  source_turn_ids: z.array(z.string()).default([]),
  recommended_user_action: z.string(),
});
export type SafetyFlag = z.infer<typeof SafetyFlagSchema>;

// -----------------------------------------------------------------------------
// VisitState
// -----------------------------------------------------------------------------

export const TranscriptVerificationAmbiguitySchema = z.object({
  ambiguity_id: z.string(),
  ambiguity_type: z.enum([
    "drug_name",
    "dose",
    "frequency",
    "timing",
    "duration",
    "speaker",
    "test_name",
    "follow_up_date",
    "asr_uncertain",
    "other",
  ]),
  text: z.string(),
  reason: z.string(),
  severity: z.enum(["low", "medium", "high"]),
  suggested_confirmation_question: z.string(),
  source_turn_ids: z.array(z.string()).default([]),
  created_at: z.string(),
});
export type TranscriptVerificationAmbiguity = z.infer<typeof TranscriptVerificationAmbiguitySchema>;

export const TranscriptVerificationRecordSchema = z.object({
  verification_id: z.string(),
  turn_id: z.string(),
  quality: z.enum(["high", "medium", "low"]),
  safe_to_extract: z.boolean(),
  ambiguities: z.array(TranscriptVerificationAmbiguitySchema).default([]),
  source_turn_ids: z.array(z.string()).default([]),
  created_at: z.string(),
});
export type TranscriptVerificationRecord = z.infer<typeof TranscriptVerificationRecordSchema>;

// Noise filter — pause-time per-turn tag map. Persisted on VisitState as
// `noise_tags` so the UI can hide noise_high_conf turns and downstream
// agents can read the tag in their prompt context.
export const NoiseTagSchema = z.enum([
  "clean",
  "partial",
  "duplicate",
  "noise_low_conf",
  "noise_high_conf",
]);
export type NoiseTag = z.infer<typeof NoiseTagSchema>;

export const NoiseCategorySchema = z.enum([
  "clean",
  "asr_artifact",
  "filler",
  "chitchat",
  "implausible_word",
  "partial_utterance",
  "duplicate_segment",
]);
export type NoiseCategory = z.infer<typeof NoiseCategorySchema>;

export const NoiseTurnTagSchema = z.object({
  turn_id: z.string(),
  tag: NoiseTagSchema,
  category: NoiseCategorySchema,
  confidence: z.enum(["low", "medium", "high"]),
  reason: z.string().default(""),
  phonetic_neighbor: z.string().nullable().optional(),
});
export type NoiseTurnTag = z.infer<typeof NoiseTurnTagSchema>;

export const NoiseFilterSummarySchema = z.object({
  total_turns: z.number().int().nonnegative().default(0),
  clean: z.number().int().nonnegative().default(0),
  partial: z.number().int().nonnegative().default(0),
  duplicate: z.number().int().nonnegative().default(0),
  noise_low_conf: z.number().int().nonnegative().default(0),
  noise_high_conf: z.number().int().nonnegative().default(0),
});
export type NoiseFilterSummary = z.infer<typeof NoiseFilterSummarySchema>;

// Output schema for the transcript_noise_filter agent.
export const NoiseFilterOutputSchema = z.object({
  turn_tags: z.array(NoiseTurnTagSchema).default([]),
  summary: NoiseFilterSummarySchema.default({
    total_turns: 0,
    clean: 0,
    partial: 0,
    duplicate: 0,
    noise_low_conf: 0,
    noise_high_conf: 0,
  }),
});
export type NoiseFilterOutput = z.infer<typeof NoiseFilterOutputSchema>;

// Persisted on VisitState. Adds `applied_at` and `round_index` so the UI
// knows when the latest filter ran and which round it covered.
export const NoiseTagsRecordSchema = z.object({
  turn_tags: z.array(NoiseTurnTagSchema).default([]),
  summary: NoiseFilterSummarySchema,
  round_index: z.number().int().nonnegative().nullable().default(null),
  applied_at: z.string(),
});
export type NoiseTagsRecord = z.infer<typeof NoiseTagsRecordSchema>;

export const CaregiverNotificationDraftSchema = z.object({
  notification_id: z.string(),
  turn_id: z.string().nullable().optional(),
  title: z.string(),
  message: z.string(),
  needs_confirmation: z.array(z.string()).default([]),
  next_actions: z.array(z.string()).default([]),
  requires_user_confirmation: z.literal(true),
  confirmation_status: ConfirmationStatusSchema.default("pending"),
  source_turn_ids: z.array(z.string()).default([]),
  created_at: z.string(),
});
export type CaregiverNotificationDraft = z.infer<typeof CaregiverNotificationDraftSchema>;

// CLARIOSE_V02 — Round model.
// A visit is a sequence of "rounds" demarcated by user pause/resume. Each
// round has its own transcript window + recap so the per-pause team output
// stops stacking and stops being silently overwritten. Round 0 is opened at
// visit creation; "End visit" closes whatever round is open last.
export const VisitRoundSchema = z.object({
  index: z.number().int().nonnegative(),
  started_at: z.string(),
  ended_at: z.string().nullable().default(null),
  // item_ids of TranscriptTurn rows that belong to this round.
  turn_item_ids: z.array(z.string()).default([]),
  // Recap headline cached per-round so the visit page can show all of them
  // side-by-side instead of overwriting one with the next. Full recap text
  // + image live on disk under data/carenote/visits/<id>/round-<N>/.
  recap_headline: z.string().nullable().default(null),
  recap_generated_at: z.string().nullable().default(null),
});
export type VisitRound = z.infer<typeof VisitRoundSchema>;

// CLARIOSE_V02 — Reverse translate-TTS log.
// User types a follow-up question in their native language; backend
// translates to English and synthesizes audio with gpt-4o-mini-tts so the
// doctor can hear it. We log the source/translation/audio path here so the
// visit page can list past asks per-round and replay audio.
export const AskDoctorLogSchema = z.object({
  ask_id: z.string(),
  round_index: z.number().int().nonnegative(),
  source_language: z.string(),
  source_text: z.string(),
  translated_text: z.string(),
  // path is relative to the visit folder root (data/carenote/visits/<id>/...).
  audio_relpath: z.string(),
  duration_ms: z.number().int().nonnegative().default(0),
  created_at: z.string(),
});
export type AskDoctorLog = z.infer<typeof AskDoctorLogSchema>;

export const VisitStateSchema = z.object({
  visit_id: z.string(),
  language: z.enum(["zh", "en", "mixed"]),
  // What the user wants to READ. Differs from `language` (what is SPOKEN at
  // the visit) — many caregivers attend a Mandarin-speaking visit but want
  // the digest in English, or vice versa. Defaults to `language` at create
  // time. Falls back to "zh" when a legacy blob predates the field.
  output_language: z.enum(["zh", "en", "mixed"]).default("en"),
  status: z.enum(["new", "recording", "analysing", "ended"]),
  // Round model — see VisitRoundSchema.
  current_round_index: z.number().int().nonnegative().default(0),
  rounds: z.array(VisitRoundSchema).default([]),
  // Reverse translate-TTS asks (user → doctor in English audio).
  ask_doctor_logs: z.array(AskDoctorLogSchema).default([]),
  turns: z.array(TranscriptTurnSchema).default([]),
  transcript_stats: TranscriptStatsSchema.default({
    committed_count: 0,
    partial_count: 0,
    delta_count: 0,
    completed_count: 0,
    failed_count: 0,
    last_event_type: null,
    last_completed_transcript: null,
    last_completed_transcript_at: null,
    last_partial_transcript: null,
    last_error: null,
    last_failed_at: null,
  }),
  facts: z.array(ExtractedFactSchema).default([]),
  draft_tasks: z.array(DraftTaskSchema).default([]),
  draft_reminders: z.array(DraftMedicationReminderSchema).default([]),
  clarifying_questions: z.array(ClarifyingQuestionSchema).default([]),
  transcript_verifications: z.array(TranscriptVerificationRecordSchema).default([]),
  caregiver_notifications: z.array(CaregiverNotificationDraftSchema).default([]),
  family_summary_deltas: z
    .array(
      z.object({
        turn_id: z.string(),
        text: z.string(),
        source_turn_ids: z.array(z.string()).default([]),
      }),
    )
    .default([]),
  family_summary_final: z.string().optional(),
  memory_candidates: z.array(MemoryCandidateSchema).default([]),
  safety_flags: z.array(SafetyFlagSchema).default([]),
  guardrail_blocked: z
    .array(
      z.object({
        item: z.string(),
        reason: z.string(),
        suggested_rewrite: z.string(),
      }),
    )
    .default([]),
  /**
   * item_ids that have already triggered an analyze_turn job.
   * Idempotency guard for duplicated completed events.
   */
  analyzed_item_ids: z.array(z.string()).default([]),
  /**
   * Result of the most recent transcript_noise_filter pass. Populated when
   * the user pauses the consult; consumed by the UI (to hide
   * noise_high_conf turns) and by post-filter regenerate agents.
   */
  noise_tags: NoiseTagsRecordSchema.nullable().default(null),
});
export type VisitState = z.infer<typeof VisitStateSchema>;

// -----------------------------------------------------------------------------
// Per-role output schemas
// -----------------------------------------------------------------------------

export const VisitOrchestratorOutputSchema = z.object({
  visit_id: z.string(),
  turn_id: z.string(),
  facts: z.array(ExtractedFactSchema).default([]),
  draft_tasks: z.array(DraftTaskSchema).default([]),
  clarifying_questions: z.array(ClarifyingQuestionSchema).default([]),
  family_summary_delta: z.string().optional(),
  memory_candidates: z.array(MemoryCandidateSchema).default([]),
  safety_flags: z.array(SafetyFlagSchema).default([]),
  guardrail_notes: z.array(z.string()).default([]),
});
export type VisitOrchestratorOutput = z.infer<typeof VisitOrchestratorOutputSchema>;

// M7.6: this schema covers the "Transcript Verification Agent". It looks
// for transcription uncertainty only — never audits the doctor.
export const TranscriptQualityOutputSchema = z.object({
  quality: z.enum(["high", "medium", "low"]),
  safe_to_extract: z.boolean().default(true),
  ambiguities: z
    .array(
      z.object({
        ambiguity_type: z.enum([
          "drug_name",
          "dose",
          "frequency",
          "timing",
          "duration",
          "speaker",
          "test_name",
          "follow_up_date",
          "asr_uncertain",
          "other",
        ]),
        text: z.string(),
        reason: z.string(),
        severity: z.enum(["low", "medium", "high"]),
        suggested_confirmation_question: z.string(),
        source_turn_ids: z.array(z.string()).min(1),
      }),
    )
    .default([]),
  missing_critical_fields: z.array(z.string()).default([]),
  recommended_action: z.string().default(""),
  source_turn_ids: z.array(z.string()).min(1),
});
export type TranscriptQualityOutput = z.infer<typeof TranscriptQualityOutputSchema>;

export const SpeakerRoleOutputSchema = z.object({
  speaker_label: SpeakerLabelSchema,
  confidence: ConfidenceSchema,
  reason: z.string().default(""),
  source_turn_ids: z.array(z.string()).min(1),
});
export type SpeakerRoleOutput = z.infer<typeof SpeakerRoleOutputSchema>;

export const MedicalInstructionExtractorOutputSchema = z.object({
  facts: z
    .array(
      z.object({
        fact_type: FactTypeSchema,
        original_text: z.string(),
        normalized: NormalizedFactSchema,
        missing_fields: z.array(z.string()).default([]),
        confidence: ConfidenceSchema,
        requires_confirmation: z.boolean(),
        source_turn_ids: z.array(z.string()).min(1),
      }),
    )
    .default([]),
});
export type MedicalInstructionExtractorOutput = z.infer<
  typeof MedicalInstructionExtractorOutputSchema
>;

export const MedicationReminderDraftOutputSchema = z.object({
  draft_reminders: z
    .array(
      z.object({
        task_type: z.literal("medication_reminder"),
        title: z.string(),
        description: z.string(),
        medication_name: z.string().nullable(),
        dose: z.string().nullable(),
        frequency: z.string().nullable(),
        timing: z.string().nullable(),
        duration: z.string().nullable(),
        start_date: z.string().nullable().optional(),
        end_date: z.string().nullable().optional(),
        recurrence: z.unknown().optional(),
        status: z.enum(["needs_user_confirmation", "complete_pending_confirmation"]),
        requires_user_confirmation: z.boolean(),
        confirmation_status: z.enum(["pending", "confirmed", "rejected"]),
        blocking_missing_fields: z.array(z.string()).default([]),
        source_fact_ids: z.array(z.string()).default([]),
        source_turn_ids: z.array(z.string()).min(1),
      }),
    )
    .default([]),
  confirmation_tasks: z
    .array(
      z.object({
        task_type: z.literal("question"),
        title: z.string(),
        description: z.string(),
        requires_user_confirmation: z.boolean(),
        confirmation_status: z.enum(["pending", "confirmed", "rejected"]),
        source_fact_ids: z.array(z.string()).default([]),
        source_turn_ids: z.array(z.string()).min(1),
      }),
    )
    .default([]),
});
export type MedicationReminderDraftOutput = z.infer<typeof MedicationReminderDraftOutputSchema>;

export const FollowUpTaskDraftOutputSchema = z.object({
  draft_tasks: z
    .array(
      z.object({
        task_type: z.enum([
          "follow_up",
          "test",
          "collect_report",
          "referral",
          "question",
          "other",
        ]),
        title: z.string(),
        description: z.string(),
        due_at: z.string().nullable().optional(),
        date_confidence: z.enum(["exact", "relative", "unclear"]),
        requires_user_confirmation: z.boolean(),
        confirmation_status: z.enum(["pending", "confirmed", "rejected"]),
        source_turn_ids: z.array(z.string()).min(1),
      }),
    )
    .default([]),
});
export type FollowUpTaskDraftOutput = z.infer<typeof FollowUpTaskDraftOutputSchema>;

export const SafetyClarificationOutputSchema = z.object({
  clarifying_questions: z
    .array(
      z.object({
        question: z.string(),
        reason: z.string(),
        priority: z.enum(["low", "medium", "high"]),
        source_turn_ids: z.array(z.string()).min(1),
      }),
    )
    .default([]),
  safety_flags: z
    .array(
      z.object({
        flag_type: z.enum([
          "missing_dose",
          "missing_medication_name",
          "unclear_follow_up",
          "possible_emergency",
          "transcription_uncertain",
          "allergy_needs_confirmation",
          "other",
        ]),
        severity: z.enum(["low", "medium", "high"]),
        message: z.string(),
        recommended_user_action: z.string(),
        source_turn_ids: z.array(z.string()).min(1),
      }),
    )
    .default([]),
});
export type SafetyClarificationOutput = z.infer<typeof SafetyClarificationOutputSchema>;

// M7.6: this schema doubles as the "Caregiver Notification Agent" output.
// `family_summary` is the human-readable message; `caregiver_notification`
// is the structured draft form used by the UI.
export const FamilySummaryOutputSchema = z.object({
  family_summary: z.string(),
  important_to_confirm: z.array(z.string()).default([]),
  next_actions: z.array(z.string()).default([]),
  source_turn_ids: z.array(z.string()).default([]),
  caregiver_notification: z
    .object({
      title: z.string(),
      message: z.string(),
      needs_confirmation: z.array(z.string()).default([]),
      next_actions: z.array(z.string()).default([]),
      requires_user_confirmation: z.boolean().default(true),
      source_turn_ids: z.array(z.string()).default([]),
    })
    .nullable()
    .optional(),
});
export type FamilySummaryOutput = z.infer<typeof FamilySummaryOutputSchema>;

export const MemoryUpdateOutputSchema = z.object({
  memory_candidates: z
    .array(
      z.object({
        memory_type: MemoryTypeSchema,
        content: z.string(),
        confidence: ConfidenceSchema,
        requires_user_confirmation: z.boolean(),
        confirmation_status: z.enum(["pending", "confirmed", "rejected"]),
        source_turn_ids: z.array(z.string()).min(1),
      }),
    )
    .default([]),
});
export type MemoryUpdateOutput = z.infer<typeof MemoryUpdateOutputSchema>;

// M7.6: presented as the "Safety Guardrail Agent" in UI/docs.
export const ComplianceGuardrailOutputSchema = z.object({
  is_safe: z.boolean(),
  blocked_items: z
    .array(
      z.object({
        item: z.string(),
        reason: z.enum([
          "diagnosis",
          "treatment_advice",
          "doctor_audit",
          "medication_change",
          "automatic_reminder",
          "automatic_caregiver_send",
          "unsupported_inference",
          "missing_source",
          "missing_confirmation",
          "unconfirmed_memory_write",
          "privacy",
          // Output cites a source_turn_id quarantined by the noise filter.
          "references_quarantined_turn",
          // Question duplicates one already produced by the Verifier for
          // the same (source_turn_id, field) pair.
          "duplicate_question",
          "other",
        ]),
        suggested_rewrite: z.string(),
      }),
    )
    .default([]),
  required_user_confirmations: z.array(z.string()).default([]),
  safe_output_patch: z.record(z.string(), z.unknown()).default({}),
});
export type ComplianceGuardrailOutput = z.infer<typeof ComplianceGuardrailOutputSchema>;

export const FinalVisitSummaryOutputSchema = z.object({
  visit_summary: z.object({
    plain_language_summary: z.string(),
    doctor_mentioned: z
      .array(
        z.object({
          text: z.string(),
          source_turn_ids: z.array(z.string()).min(1),
        }),
      )
      .default([]),
    medications: z
      .array(
        z.object({
          name: z.string().nullable(),
          dose: z.string().nullable(),
          frequency: z.string().nullable(),
          timing: z.string().nullable(),
          duration: z.string().nullable(),
          status: z.enum(["confirmed", "needs_confirmation", "missing_info"]),
          source_turn_ids: z.array(z.string()).min(1),
        }),
      )
      .default([]),
    follow_ups: z.array(z.unknown()).default([]),
    tests: z.array(z.unknown()).default([]),
    questions_to_ask: z.array(z.string()).default([]),
    family_summary: z.string(),
    disclaimer: z.string(),
  }),
});
export type FinalVisitSummaryOutput = z.infer<typeof FinalVisitSummaryOutputSchema>;

// -----------------------------------------------------------------------------
// Team manifest + thread state
// -----------------------------------------------------------------------------

export const CodexAgentManifestEntrySchema = z.object({
  role: CodexAgentRoleSchema,
  name: z.string(),
  prompt_file: z.string(),
  prompt_version: z.string(),
  schema_name: z.string(),
  schema_version: z.string(),
  thread_policy: z.enum(["persistent_per_team", "transient"]),
  sandbox_policy: z.literal("read_only_runtime"),
  agent_config_path: z.string().optional(),
  can_write_files: z.literal(false),
});
export type CodexAgentManifestEntry = z.infer<typeof CodexAgentManifestEntrySchema>;

export const CodexAgentTeamManifestSchema = z.object({
  team_id: z.string(),
  team_name: z.string(),
  version: z.string(),
  schema_version: z.string(),
  runtime_preference: z
    .array(z.enum(["codex-sdk", "codex-app-server", "codex-cli", "stub"]))
    .min(1),
  default_runtime_options: z.object({
    model: z.string().default("gpt-5-codex"),
    sandboxMode: z.literal("read-only").default("read-only"),
    approvalPolicy: z.literal("never").default("never"),
    networkAccessEnabled: z.literal(false).default(false),
    skipGitRepoCheck: z.boolean().default(true),
  }),
  agents: z.array(CodexAgentManifestEntrySchema).min(1),
});
export type CodexAgentTeamManifest = z.infer<typeof CodexAgentTeamManifestSchema>;

export const CodexAgentThreadStateSchema = z.object({
  team_id: z.string(),
  role: CodexAgentRoleSchema,
  thread_id: z.string().nullable(),
  runtime: z.string(),
  prompt_version: z.string(),
  schema_version: z.string(),
  status: z.enum(["active", "reset", "retired"]),
  last_run_at: z.string().nullable().optional(),
  last_summary: z.string().nullable().optional(),
  reset_reason: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type CodexAgentThreadState = z.infer<typeof CodexAgentThreadStateSchema>;

// -----------------------------------------------------------------------------
// Agent run record
// -----------------------------------------------------------------------------

export const AgentRunRecordSchema = z.object({
  run_id: z.string(),
  team_id: z.string(),
  visit_id: z.string(),
  role: CodexAgentRoleSchema,
  thread_id: z.string().nullable(),
  runtime: z.string(),
  prompt_version: z.string(),
  schema_version: z.string(),
  input_summary: z.string(),
  raw_output: z.string(),
  parsed_output: z.unknown().nullable(),
  validation_status: z.enum(["valid", "repaired", "invalid", "failed"]),
  errors: z.array(z.string()).default([]),
  started_at: z.string(),
  completed_at: z.string(),
});
export type AgentRunRecord = z.infer<typeof AgentRunRecordSchema>;

// Map role → output schema for the validator.
export const RoleOutputSchemas: Record<CodexAgentRole, z.ZodSchema> = {
  visit_orchestrator: VisitOrchestratorOutputSchema,
  transcript_noise_filter: NoiseFilterOutputSchema,
  transcript_quality: TranscriptQualityOutputSchema,
  speaker_role: SpeakerRoleOutputSchema,
  medical_instruction_extractor: MedicalInstructionExtractorOutputSchema,
  medication_reminder_draft: MedicationReminderDraftOutputSchema,
  follow_up_task_draft: FollowUpTaskDraftOutputSchema,
  safety_clarification: SafetyClarificationOutputSchema,
  family_summary: FamilySummaryOutputSchema,
  memory_update: MemoryUpdateOutputSchema,
  compliance_guardrail: ComplianceGuardrailOutputSchema,
  final_visit_summary: FinalVisitSummaryOutputSchema,
};
