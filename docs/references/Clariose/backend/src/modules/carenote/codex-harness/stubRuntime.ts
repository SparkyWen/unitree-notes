// stubRuntime — deterministic in-process implementation used for tests
// and for the no-Codex local-dev case.
//
// The stub is *not* trying to replace Codex. It returns minimally-valid,
// schema-conforming outputs so the harness's reducers, guardrail, and
// pipeline can be exercised end-to-end without external dependencies.
//
// Design choices:
//  - Each role returns a fixed-shape JSON for the role's expected schema.
//  - Medication-related outputs always carry requires_user_confirmation =
//    true and confirmation_status = "pending" (this is the safety
//    contract the stub respects so tests don't false-pass).
//  - Memory candidates always have requires_user_confirmation = true.
//  - The compliance guardrail returns is_safe = true with no rewrites.
//  - The medical_instruction_extractor stub does basic keyword matching
//    on the transcript text so a few of the safety fixtures pass without
//    a real model.

import { randomUUID } from "node:crypto";

import type { CodexAgentRole } from "../medical/medicalSchemas";
import type {
  CodexAgentRunInput,
  CodexAgentRunOutput,
  CodexAuthMode,
  CodexRuntime,
} from "./codexRuntime";

export class StubRuntime implements CodexRuntime {
  readonly name = "stub" as const;

  // Optional override: callers (mostly tests) can register a function
  // that returns the raw_text Codex would have returned.
  private overrides = new Map<string, (input: CodexAgentRunInput) => string>();

  setOverride(role: CodexAgentRole, fn: (input: CodexAgentRunInput) => string): void {
    this.overrides.set(role, fn);
  }

  async startOrResumeThread(input: {
    team_id: string;
    role: CodexAgentRole;
    existing_thread_id?: string | null;
  }): Promise<{ thread_id: string | null }> {
    return {
      thread_id: input.existing_thread_id ?? `stub-${input.role}-${randomUUID()}`,
    };
  }

  async run(input: CodexAgentRunInput): Promise<CodexAgentRunOutput> {
    const started_at = new Date().toISOString();
    const run_id = randomUUID();
    const override = this.overrides.get(input.role);
    const raw = override
      ? override(input)
      : JSON.stringify(buildStubOutput(input));
    return {
      team_id: input.team_id,
      visit_id: input.visit_id,
      role: input.role,
      thread_id: input.thread_id ?? `stub-${input.role}`,
      run_id,
      raw_text: raw,
      validation_status: "valid",
      started_at,
      completed_at: new Date().toISOString(),
    };
  }

  async healthCheck(): Promise<{
    ok: boolean;
    runtime: "stub";
    auth_mode?: CodexAuthMode;
    details?: string;
  }> {
    return {
      ok: true,
      runtime: "stub",
      auth_mode: "unknown",
      details: "in-memory deterministic stub; do not use in production",
    };
  }
}

// ---------------------------------------------------------------------------
// Stub output builders
// ---------------------------------------------------------------------------

type StubEvent = {
  event_kind?: string;
  visit_id?: string;
  turn?: { item_id: string; transcript: string };
  // for orchestrator stage:
  pass1?: Record<string, unknown>;
  pass2?: Record<string, unknown>;
  // for compliance stage:
  envelope?: Record<string, unknown>;
  // for transcript_noise_filter (pause-time whole-transcript pass):
  full_transcript?: { item_id: string; transcript: string }[];
};

function getEventTurn(input: CodexAgentRunInput): { item_id: string; transcript: string } | null {
  const ev = input.event as StubEvent;
  if (ev?.turn) return ev.turn;
  return null;
}

function buildStubOutput(input: CodexAgentRunInput): unknown {
  const turn = getEventTurn(input);
  const itemId = turn?.item_id ?? "itm-unknown";
  const text = turn?.transcript ?? "";

  switch (input.role) {
    case "transcript_noise_filter":
      return stubNoiseFilter(input);
    case "transcript_quality":
      return stubTranscriptQuality(itemId, text);
    case "speaker_role":
      return stubSpeakerRole(itemId, text);
    case "medical_instruction_extractor":
      return stubMedicalInstructionExtractor(itemId, text);
    case "safety_clarification":
      return stubSafetyClarification(itemId, text);
    case "medication_reminder_draft":
      return stubMedicationReminderDraft(input);
    case "follow_up_task_draft":
      return stubFollowUpTaskDraft(input);
    case "family_summary":
      return stubFamilySummary(itemId, text);
    case "memory_update":
      return stubMemoryUpdate(input);
    case "compliance_guardrail":
      return stubComplianceGuardrail();
    case "final_visit_summary":
      return stubFinalVisitSummary(input);
    case "visit_orchestrator":
      return stubVisitOrchestrator(input);
    default:
      return {};
  }
}

function stubTranscriptQuality(itemId: string, text: string) {
  const uncertainTerms: { text: string; reason: string; severity: string }[] = [];
  if (/[a-zA-Z]/.test(text) && /[一-龥]/.test(text)) {
    // mixed Chinese-English content — flag drug-name uncertainty conservatively.
    uncertainTerms.push({ text, reason: "drug_name_uncertain", severity: "low" });
  }
  const missing: string[] = [];
  const mentionsDrug = /药|tablet|capsule|阿莫西林|抗生素|antibiotic/i.test(text);
  if (mentionsDrug && !/(mg|毫克|片|粒)/i.test(text)) missing.push("dose");
  if (mentionsDrug && !/(每天|一次|times|daily)/i.test(text)) missing.push("frequency");
  return {
    quality: missing.length === 0 ? "high" : "medium",
    uncertain_terms: uncertainTerms,
    missing_critical_fields: missing,
    recommended_action:
      missing.length > 0
        ? "Confirm dose and frequency with the doctor or pharmacist."
        : "",
    source_turn_ids: [itemId],
  };
}

function stubSpeakerRole(itemId: string, text: string) {
  let label: "doctor" | "patient" | "family" | "unknown" = "unknown";
  let conf: "high" | "medium" | "low" = "low";
  let reason = "ambiguous";
  if (/我(觉得|感|疼|痛|有点|今天)/.test(text) || /^I (feel|have)/i.test(text)) {
    label = "patient";
    conf = "medium";
    reason = "first-person symptom report";
  } else if (
    /(prescribe|every day|once daily|每天|饭后|开|复诊|follow-up)/i.test(text)
  ) {
    label = "doctor";
    conf = "medium";
    reason = "instruction phrasing";
  } else if (/我(妈|爸|母亲|父亲|孩子)/.test(text)) {
    label = "family";
    conf = "medium";
    reason = "family-relationship reference";
  }
  return {
    speaker_label: label,
    confidence: conf,
    reason,
    source_turn_ids: [itemId],
  };
}

function stubMedicalInstructionExtractor(itemId: string, text: string) {
  const facts: Record<string, unknown>[] = [];

  // Frequency / duration / timing extraction (very simple).
  if (/(每天|每日|each day|daily|once daily|once a day)/i.test(text) ||
      /饭后/.test(text)) {
    const freq = /每天饭后吃一次/.test(text)
      ? "每天饭后吃一次"
      : /每天.*?一次/.exec(text)?.[0] ?? "daily";
    const duration = /连续吃([一二三四五六七八九十]+|\d+)天/.exec(text)?.[0] ?? null;
    facts.push({
      fact_type: "frequency",
      original_text: text,
      normalized: {
        medication_name: extractDrugName(text),
        dose: null,
        frequency: freq,
        timing: /饭后/.test(text) ? "饭后" : null,
        duration,
        route: null,
        date: null,
        test_name: null,
        condition: null,
      },
      missing_fields: [
        ...(extractDrugName(text) ? [] : ["medication_name"]),
        "dose",
      ],
      confidence: "medium",
      requires_confirmation: true,
      source_turn_ids: [itemId],
    });
  }

  // Allergy.
  if (/过敏|allergic/i.test(text)) {
    const m = /对(.+?)过敏/.exec(text);
    facts.push({
      fact_type: "allergy",
      original_text: text,
      normalized: {
        medication_name: null,
        dose: null,
        frequency: null,
        timing: null,
        duration: null,
        route: null,
        date: null,
        test_name: null,
        condition: m?.[1] ?? null,
      },
      missing_fields: [],
      confidence: "high",
      requires_confirmation: true,
      source_turn_ids: [itemId],
    });
  }

  // Follow-up.
  if (/(复诊|follow.?up|周[一二三四五六日])/i.test(text)) {
    facts.push({
      fact_type: "follow_up",
      original_text: text,
      normalized: {
        medication_name: null,
        dose: null,
        frequency: null,
        timing: null,
        duration: null,
        route: null,
        date: /周[一二三四五六日]/.exec(text)?.[0] ?? null,
        test_name: null,
        condition: null,
      },
      missing_fields: [],
      confidence: "medium",
      requires_confirmation: false,
      source_turn_ids: [itemId],
    });
  }

  // Symptoms (patient-side).
  if (/恶心|nausea|疼|pain|发烧|fever|咳嗽|cough/i.test(text)) {
    facts.push({
      fact_type: "symptom",
      original_text: text,
      normalized: {
        medication_name: null,
        dose: null,
        frequency: null,
        timing: null,
        duration: null,
        route: null,
        date: null,
        test_name: null,
        condition: null,
      },
      missing_fields: [],
      confidence: "medium",
      requires_confirmation: false,
      source_turn_ids: [itemId],
    });
  }

  return { facts };
}

function stubSafetyClarification(itemId: string, text: string) {
  const questions: { question: string; reason: string; priority: string; source_turn_ids: string[] }[] = [];
  const flags: { flag_type: string; severity: string; message: string; recommended_user_action: string; source_turn_ids: string[] }[] = [];
  const drugMentioned = /药|tablet|阿莫西林|antibiotic/i.test(text);
  if (drugMentioned && !/(mg|毫克|片|粒)/i.test(text)) {
    flags.push({
      flag_type: "missing_dose",
      severity: "medium",
      message: "Medication mentioned without an explicit dose.",
      recommended_user_action: "Confirm this with the doctor or pharmacist.",
      source_turn_ids: [itemId],
    });
    questions.push({
      question: "What is the exact dose for this medication?",
      reason: "transcript did not record a dose",
      priority: "high",
      source_turn_ids: [itemId],
    });
  }
  if (/过敏|allergic/i.test(text)) {
    flags.push({
      flag_type: "allergy_needs_confirmation",
      severity: "high",
      message: "Possible allergy mentioned; confirm with clinician.",
      recommended_user_action: "Confirm this with the doctor or pharmacist.",
      source_turn_ids: [itemId],
    });
  }
  if (/紧急|emergency|chest pain|呼吸困难/i.test(text)) {
    flags.push({
      flag_type: "possible_emergency",
      severity: "high",
      message: "Emergency-sounding content detected.",
      recommended_user_action:
        "Please contact a doctor or your local emergency service.",
      source_turn_ids: [itemId],
    });
  }
  return { clarifying_questions: questions, safety_flags: flags };
}

function stubMedicationReminderDraft(input: CodexAgentRunInput) {
  const ev = input.event as StubEvent;
  const pass1 = (ev.pass1 ?? {}) as {
    medical_instruction_extractor?: { facts?: { source_turn_ids: string[] }[] };
  };
  const facts = pass1.medical_instruction_extractor?.facts ?? [];
  const turn = getEventTurn(input);
  const itemId = turn?.item_id ?? "itm-unknown";
  const med = facts.find((f) => true) as
    | (typeof facts)[number] & {
        fact_type: string;
        normalized?: { medication_name?: string | null; dose?: string | null; frequency?: string | null; timing?: string | null; duration?: string | null };
      }
    | undefined;
  if (!med || med.fact_type !== "frequency") {
    return { draft_reminders: [], confirmation_tasks: [] };
  }
  const missing = ["medication_name", "dose", "frequency", "timing", "duration"]
    .filter((k) => !med.normalized?.[k as keyof typeof med.normalized]);
  return {
    draft_reminders: [
      {
        task_type: "medication_reminder",
        title: "Medication reminder (needs confirmation)",
        description:
          "Draft medication reminder. Missing fields must be confirmed with the doctor or pharmacist before activation.",
        medication_name: med.normalized?.medication_name ?? null,
        dose: med.normalized?.dose ?? null,
        frequency: med.normalized?.frequency ?? null,
        timing: med.normalized?.timing ?? null,
        duration: med.normalized?.duration ?? null,
        start_date: null,
        end_date: null,
        recurrence: null,
        status: missing.length > 0 ? "needs_user_confirmation" : "complete_pending_confirmation",
        requires_user_confirmation: true,
        confirmation_status: "pending",
        blocking_missing_fields: missing,
        source_fact_ids: [],
        source_turn_ids: med.source_turn_ids ?? [itemId],
      },
    ],
    confirmation_tasks: missing.length > 0
      ? [
          {
            task_type: "question",
            title: "Confirm medication details",
            description:
              "Please confirm the following missing fields with your doctor or pharmacist: " +
              missing.join(", "),
            requires_user_confirmation: true,
            confirmation_status: "pending",
            source_fact_ids: [],
            source_turn_ids: med.source_turn_ids ?? [itemId],
          },
        ]
      : [],
  };
}

function stubFollowUpTaskDraft(input: CodexAgentRunInput) {
  const ev = input.event as StubEvent;
  const pass1 = (ev.pass1 ?? {}) as {
    medical_instruction_extractor?: {
      facts?: { fact_type: string; original_text: string; normalized?: { date?: string | null }; source_turn_ids: string[] }[];
    };
  };
  const facts = pass1.medical_instruction_extractor?.facts ?? [];
  const followUps = facts.filter((f) => f.fact_type === "follow_up");
  return {
    draft_tasks: followUps.map((f) => ({
      task_type: "follow_up",
      title: "Follow-up appointment (needs confirmation)",
      description: f.original_text,
      due_at: null,
      date_confidence: f.normalized?.date ? "relative" : "unclear",
      requires_user_confirmation: true,
      confirmation_status: "pending",
      source_turn_ids: f.source_turn_ids,
    })),
  };
}

function stubFamilySummary(itemId: string, text: string) {
  return {
    family_summary:
      "本次就诊摘要（草稿，需要用户确认）：" + text.slice(0, 120),
    important_to_confirm: ["药物名称", "剂量", "复诊时间"],
    next_actions: ["与医生或药师确认药物剂量"],
    source_turn_ids: [itemId],
  };
}

function stubMemoryUpdate(input: CodexAgentRunInput) {
  const turn = getEventTurn(input);
  const itemId = turn?.item_id ?? "itm-unknown";
  const text = turn?.transcript ?? "";
  const candidates: Record<string, unknown>[] = [];
  if (/过敏|allergic/i.test(text)) {
    const m = /对(.+?)过敏/.exec(text);
    candidates.push({
      memory_type: "allergy",
      content: m ? `Allergy to ${m[1]}` : "Allergy mentioned in transcript",
      confidence: "high",
      requires_user_confirmation: true,
      confirmation_status: "pending",
      source_turn_ids: [itemId],
    });
  }
  return { memory_candidates: candidates };
}

function stubNoiseFilter(input: CodexAgentRunInput) {
  // Deterministic offline classifier used when no API key is configured.
  // Heuristics mirror the prompt's calibration rules: short standalone
  // utterances with no clinical content are noise_high_conf; filler words
  // are noise_low_conf; everything else is clean. Default to clean.
  const ev = input.event as StubEvent;
  const turns = ev.full_transcript ?? [];
  const FILLER = /^(yeah|ok|okay|hmm|uh|um|right|got it|thanks|thank you)[\s.!?,]*$/i;
  const ASR_MARKER = /^\[(music|inaudible|noise|silence)\][\s.!?,]*$/i;
  const CLINICAL = /(mg|tablet|capsule|pill|fever|cough|allergic|allergy|prescription|prescribe|dose|symptom|test|x-?ray|blood|fasting|follow.?up|appointment|药|剂量|过敏|复诊|症状|检查)/i;
  const counters = {
    total_turns: turns.length,
    clean: 0,
    partial: 0,
    duplicate: 0,
    noise_low_conf: 0,
    noise_high_conf: 0,
  };
  let prev: string | null = null;
  const turn_tags = turns.map((t) => {
    const raw = (t.transcript ?? "").trim();
    const wordCount = raw ? raw.split(/\s+/).length : 0;
    let tag: "clean" | "partial" | "duplicate" | "noise_low_conf" | "noise_high_conf" = "clean";
    let category:
      | "clean"
      | "asr_artifact"
      | "filler"
      | "chitchat"
      | "implausible_word"
      | "partial_utterance"
      | "duplicate_segment" = "clean";
    let confidence: "low" | "medium" | "high" = "medium";
    let reason = "Coherent on-topic content.";
    if (raw.length === 0) {
      tag = "noise_high_conf";
      category = "asr_artifact";
      confidence = "high";
      reason = "Empty turn.";
    } else if (ASR_MARKER.test(raw)) {
      tag = "noise_high_conf";
      category = "asr_artifact";
      confidence = "high";
      reason = "Transcription marker.";
    } else if (FILLER.test(raw)) {
      tag = "noise_low_conf";
      category = "filler";
      confidence = "medium";
      reason = "Conversational filler — may be a meaningful confirmation.";
    } else if (wordCount <= 2 && !CLINICAL.test(raw)) {
      tag = "noise_high_conf";
      category = "asr_artifact";
      confidence = "high";
      reason = "Standalone short turn with no clinical content.";
    } else if (prev && raw === prev) {
      tag = "duplicate";
      category = "duplicate_segment";
      confidence = "high";
      reason = "Identical to previous turn.";
    } else if (raw.endsWith("—") || raw.endsWith("--") || raw.endsWith("…")) {
      tag = "partial";
      category = "partial_utterance";
      confidence = "high";
      reason = "Cut off mid-sentence.";
    }
    counters[tag] += 1;
    prev = raw;
    return {
      turn_id: t.item_id,
      tag,
      category,
      confidence,
      reason,
      phonetic_neighbor: null,
    };
  });
  return { turn_tags, summary: counters };
}

function stubComplianceGuardrail() {
  return {
    is_safe: true,
    blocked_items: [],
    required_user_confirmations: [],
    safe_output_patch: {},
  };
}

function stubFinalVisitSummary(input: CodexAgentRunInput) {
  return {
    visit_summary: {
      plain_language_summary:
        "这是一次就诊的纯文本摘要草稿。所有药物与复诊信息均需与医生或药师确认。",
      doctor_mentioned: [],
      medications: [],
      follow_ups: [],
      tests: [],
      questions_to_ask: [],
      family_summary: "（家属版摘要草稿。）",
      disclaimer:
        "This summary is for memory and organization only. It is not diagnosis or treatment advice. Please confirm medication, dose, timing, and follow-up instructions with your doctor or pharmacist.",
    },
  };
}

function stubVisitOrchestrator(input: CodexAgentRunInput) {
  const turn = getEventTurn(input);
  return {
    visit_id: input.visit_id,
    turn_id: turn?.item_id ?? "itm-unknown",
    facts: [],
    draft_tasks: [],
    clarifying_questions: [],
    family_summary_delta: "",
    memory_candidates: [],
    safety_flags: [],
    guardrail_notes: [],
  };
}

function extractDrugName(text: string): string | null {
  if (/阿莫西林/.test(text)) return "阿莫西林";
  if (/(amoxicillin)/i.test(text)) return "amoxicillin";
  return null;
}
