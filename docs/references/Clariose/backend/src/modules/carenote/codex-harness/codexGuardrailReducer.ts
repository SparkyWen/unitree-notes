// CodexGuardrailReducer — applies a ComplianceGuardrailOutput to a
// merged turn envelope, dropping blocked items and adding required user
// confirmations to clarifying_questions.

import type {
  ComplianceGuardrailOutput,
  VisitState,
} from "../medical/medicalSchemas";

export type TurnEnvelope = {
  visit_id: string;
  turn_id: string;
  facts: VisitState["facts"];
  draft_tasks: VisitState["draft_tasks"];
  draft_reminders: VisitState["draft_reminders"];
  clarifying_questions: VisitState["clarifying_questions"];
  family_summary_delta?: { turn_id: string; text: string; source_turn_ids: string[] };
  memory_candidates: VisitState["memory_candidates"];
  safety_flags: VisitState["safety_flags"];
  transcript_verification?: VisitState["transcript_verifications"][number];
  caregiver_notification?: VisitState["caregiver_notifications"][number];
};

export function applyGuardrail(
  envelope: TurnEnvelope,
  result: ComplianceGuardrailOutput,
): { envelope: TurnEnvelope; blocked: ComplianceGuardrailOutput["blocked_items"] } {
  if (
    result.is_safe &&
    result.blocked_items.length === 0 &&
    result.required_user_confirmations.length === 0
  ) {
    return { envelope, blocked: [] };
  }

  const blockedTexts = new Set(
    result.blocked_items.map((b: { item: string }) => b.item.toLowerCase().trim()),
  );

  const filterByText = <T extends { title?: string; description?: string; content?: string; question?: string; message?: string; original_text?: string }>(
    arr: T[],
  ): T[] =>
    arr.filter((it) => {
      const candidates = [it.title, it.description, it.content, it.question, it.message, it.original_text]
        .filter(Boolean)
        .map((s) => (s as string).toLowerCase().trim());
      return !candidates.some((s) => blockedTexts.has(s));
    });

  const next: TurnEnvelope = {
    ...envelope,
    facts: filterByText(envelope.facts),
    draft_tasks: filterByText(envelope.draft_tasks),
    draft_reminders: filterByText(envelope.draft_reminders),
    clarifying_questions: filterByText(envelope.clarifying_questions),
    memory_candidates: filterByText(envelope.memory_candidates),
    safety_flags: envelope.safety_flags.slice(),
  };

  for (const q of result.required_user_confirmations) {
    next.clarifying_questions.push({
      question_id: `gr-${next.clarifying_questions.length + 1}`,
      question: q,
      reason: "compliance_guardrail",
      priority: "high",
      source_turn_ids: [envelope.turn_id],
    });
  }

  for (const b of result.blocked_items) {
    next.safety_flags.push({
      flag_id: `gr-${next.safety_flags.length + 1}`,
      flag_type: "guardrail_blocked",
      severity: "medium",
      message: `Blocked: ${b.item} (${b.reason})`,
      recommended_user_action: b.suggested_rewrite || "Confirm this with the doctor or pharmacist.",
      source_turn_ids: [envelope.turn_id],
    });
  }

  return { envelope: next, blocked: result.blocked_items };
}
