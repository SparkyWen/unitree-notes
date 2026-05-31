// Thin client for the CareNote backend.
// Lives separately from useApi() so the consult product is unaffected.

export type Language = "zh" | "en" | "mixed";

// CLARIOSE_V01: user_id removed — owner is the JWT subject. The API rejects
// any payload that includes user_id (whitelist=true on the global pipe).
export type CreateVisitInput = {
  language?: Language;
  // CLARIOSE_V02 — language the user wants to READ (different from the
  // language they speak with the doctor). Defaults server-side to language.
  output_language?: Language;
  consent_recorded: true;
  raw_audio_saved?: boolean;
};

// CLARIOSE_V02 — visit "rounds": each pause-cycle is its own slice.
export type VisitRound = {
  index: number;
  started_at: string;
  ended_at: string | null;
  turn_item_ids: string[];
  recap_headline: string | null;
  recap_generated_at: string | null;
};

export type AskDoctorLog = {
  ask_id: string;
  round_index: number;
  source_language: string;
  source_text: string;
  translated_text: string;
  audio_relpath: string;
  duration_ms: number;
  created_at: string;
};

export type AskDoctorResult = {
  ask_id: string;
  source_language: string;
  source_text: string;
  translated_text: string;
  audio_relpath: string;
  audio_url: string;
  duration_ms: number;
  created_at: string;
};

export type VisitTurnPersisted = {
  visit_id: string;
  item_id: string;
  previous_item_id: string | null;
  status: "committed" | "partial" | "completed" | "failed";
  partial_transcript: string | null;
  transcript: string | null;
  speaker_label: "doctor" | "patient" | "family" | "unknown" | null;
  ordering_confidence: "high" | "medium" | "low";
  source_model: "gpt-realtime-1.5";
  transcription_model: string;
  error?: string | null;
  created_at: string;
  completed_at: string | null;
};

export type TranscriptStats = {
  committed_count: number;
  partial_count: number;
  delta_count: number;
  completed_count: number;
  failed_count: number;
  last_event_type: string | null;
  last_completed_transcript: string | null;
  last_completed_transcript_at: string | null;
  last_partial_transcript: string | null;
  last_error: string | null;
  last_failed_at: string | null;
};

export type TranscriptVerificationRecord = {
  verification_id: string;
  turn_id: string;
  quality: "high" | "medium" | "low";
  safe_to_extract: boolean;
  ambiguities: {
    ambiguity_id: string;
    ambiguity_type: string;
    text: string;
    reason: string;
    severity: "low" | "medium" | "high";
    suggested_confirmation_question: string;
    source_turn_ids: string[];
  }[];
  source_turn_ids: string[];
  created_at: string;
};

export type CaregiverNotificationDraft = {
  notification_id: string;
  turn_id: string | null;
  title: string;
  message: string;
  needs_confirmation: string[];
  next_actions: string[];
  requires_user_confirmation: true;
  confirmation_status: "pending" | "confirmed" | "rejected";
  source_turn_ids: string[];
  created_at: string;
};

export type VisitState = {
  visit_id: string;
  language: Language;
  output_language: Language;
  status: "new" | "recording" | "analysing" | "ended";
  current_round_index: number;
  rounds: VisitRound[];
  ask_doctor_logs: AskDoctorLog[];
  turns: VisitTurnPersisted[];
  transcript_stats: TranscriptStats;
  facts: any[];
  draft_tasks: any[];
  draft_reminders: any[];
  clarifying_questions: any[];
  transcript_verifications: TranscriptVerificationRecord[];
  caregiver_notifications: CaregiverNotificationDraft[];
  family_summary_deltas: { turn_id: string; text: string }[];
  family_summary_final?: string;
  memory_candidates: any[];
  safety_flags: any[];
  guardrail_blocked: any[];
  analyzed_item_ids: string[];
};

export type VisitMeta = {
  visit_id: string;
  user_id: string;
  patient_id: string | null;
  language: Language;
  consent_recorded: boolean;
  raw_audio_saved: boolean;
  status: "active" | "ended" | "deleted";
  created_at: string;
  ended_at?: string | null;
};

export type RecapBullet = { text: string; emphasis: "normal" | "warning" };

export type TeamRecap = {
  visit_id: string;
  /** Which pause-cycle this recap describes. */
  round_index: number | null;
  generated_at: string;
  headline: string;
  highlight_facts: RecapBullet[];
  watch_outs: RecapBullet[];
  must_ask: string[];
  next_steps: string[];
  image_path: string | null;
  image_status: "ready" | "skipped" | "failed";
  image_error: string | null;
};

export type VisitFull = {
  meta: VisitMeta;
  state: VisitState;
  confirmed_tasks: any[];
  confirmed_memories: any[];
  job_status: { pending: number; in_flight: number };
  /** Latest recap (back-compat). Prefer `team_recaps`. */
  team_recap?: TeamRecap | null;
  /** Every per-round recap on disk, ascending by round_index.
   *  Lets the UI render every pause-cycle's image+digest in order. */
  team_recaps?: TeamRecap[];
};

// CLARIOSE_V03 — multi-agent collaboration timeline. The frontend uses this
// to draw a sequence of "Scribe Lin → Pharmacist Apo: I noticed X" cards so
// the user can SEE the swarm coordinating, not just the final outputs.
export type TeamMessage = {
  from: string;
  to: string;
  timestamp: string;
  summary: string | null;
  kind: string;
  text: string;
};

export type BlackboardWrite = {
  key: string;
  /** The actual value the agent wrote — may be any JSON shape depending on
   *  the key (e.g. medication_plan_draft is an object, allergies is an array
   *  of strings). The UI pretty-prints it on demand. */
  value: unknown;
  writtenBy: string;
  version: number;
  updatedAt: string;
};

export type AgentRunRecord = {
  id: string;
  role: string;
  kind: string;
  status: string;
  validation_status: string | null;
  latency_ms: number | null;
  started_at: string;
  ended_at: string | null;
  error: string | null;
  prompt?: string | null;
  prompt_truncated?: boolean;
  parsed_json?: unknown;
  model_name?: string | null;
};

export type TeamActivity = {
  messages: TeamMessage[];
  blackboard: BlackboardWrite[];
  agent_runs: AgentRunRecord[];
};

export function useCareNote() {
  const api = useApi();

  return {
    createVisit: (input: CreateVisitInput) =>
      api.post<{ visit_id: string; status: "active" }>("/visits", input),
    getVisit: (visitId: string) => api.get<VisitFull>(`/visits/${visitId}`),
    stageSummary: (visitId: string, lastN = 10) =>
      api.post<{ queued: true; job_id: string }>(`/visits/${visitId}/stage-summary`, {
        last_n_turns: lastN,
        mode: "patient_plain_language",
      }),
    finalSummary: (visitId: string) =>
      api.post<{ queued: true; job_id: string }>(`/visits/${visitId}/final-summary`),
    runTeamRecap: (visitId: string) =>
      api.post<TeamRecap>(`/visits/${visitId}/team-recap`),
    teamActivity: (visitId: string) =>
      api.get<TeamActivity>(`/visits/${visitId}/team-activity`),
    // CLARIOSE_V02 — close the current round, open a new one. Use this
    // on Pause so the next batch of speech doesn't overwrite the recap.
    endRound: (visitId: string) =>
      api.post<{ closed_round_index: number; new_round_index: number }>(
        `/visits/${visitId}/round/end`,
      ),
    // CLARIOSE_V02 — reverse translate-TTS: patient writes in native
    // language → English audio for the doctor.
    askDoctor: (
      visitId: string,
      input: { source_text: string; source_language?: string },
    ) => api.post<AskDoctorResult>(`/visits/${visitId}/ask-doctor`, input),
    askAudioUrl: (visitId: string, askId: string) =>
      `/api/visits/${encodeURIComponent(visitId)}/asks/${encodeURIComponent(askId)}/audio`,
    confirmTask: (visitId: string, taskId: string) =>
      api.post(`/visits/${visitId}/draft-tasks/${taskId}/confirm`),
    rejectTask: (visitId: string, taskId: string) =>
      api.post(`/visits/${visitId}/draft-tasks/${taskId}/reject`),
    confirmMemory: (visitId: string, candidateId: string) =>
      api.post(`/visits/${visitId}/memory-candidates/${candidateId}/confirm`),
    rejectMemory: (visitId: string, candidateId: string) =>
      api.post(`/visits/${visitId}/memory-candidates/${candidateId}/reject`),
    deleteVisit: (visitId: string) => api.delete(`/visits/${visitId}`),
  };
}
