import {
  dedupVisitState,
  reduceTurn,
} from "../../src/modules/carenote/medical/medicalReducers";
import type { TurnEnvelope } from "../../src/modules/carenote/codex-harness/codexGuardrailReducer";
import type { VisitState } from "../../src/modules/carenote/medical/medicalSchemas";
import { VisitStateSchema } from "../../src/modules/carenote/medical/medicalSchemas";

function emptyVisit(visit_id = "v1"): VisitState {
  return VisitStateSchema.parse({
    visit_id,
    language: "zh",
    status: "recording",
    turns: [],
    facts: [],
    draft_tasks: [],
    draft_reminders: [],
    clarifying_questions: [],
    family_summary_deltas: [],
    memory_candidates: [],
    safety_flags: [],
    guardrail_blocked: [],
  });
}

describe("VisitStateReducer", () => {
  test("forces requires_user_confirmation=true on draft tasks", () => {
    const env: TurnEnvelope = {
      visit_id: "v1",
      turn_id: "t1",
      facts: [],
      draft_tasks: [
        {
          task_id: "t-1",
          task_type: "follow_up",
          title: "follow up",
          description: "",
          due_at: null,
          recurrence: null,
          source_fact_ids: [],
          source_turn_ids: ["t1"],
          // Adversarial input: agent tried to opt out.
          requires_user_confirmation: false as never,
          confirmation_status: "confirmed" as never,
          created_at: new Date().toISOString(),
        },
      ],
      draft_reminders: [],
      clarifying_questions: [],
      memory_candidates: [],
      safety_flags: [],
    };
    const { next } = reduceTurn(emptyVisit(), env);
    expect(next.draft_tasks).toHaveLength(1);
    expect(next.draft_tasks[0]!.requires_user_confirmation).toBe(true);
    expect(next.draft_tasks[0]!.confirmation_status).toBe("pending");
  });

  test("rejects facts without source_turn_ids", () => {
    const env: TurnEnvelope = {
      visit_id: "v1",
      turn_id: "t1",
      facts: [
        {
          fact_id: "f1",
          fact_type: "medication",
          original_text: "x",
          normalized: {
            medication_name: "x",
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
          confidence: "high",
          requires_confirmation: true,
          source_turn_ids: [], // empty -> rejected
          created_by_agent: "medical_instruction_extractor",
          created_at: new Date().toISOString(),
        },
      ] as never,
      draft_tasks: [],
      draft_reminders: [],
      clarifying_questions: [],
      memory_candidates: [],
      safety_flags: [],
    };
    const { next, rejected } = reduceTurn(emptyVisit(), env);
    expect(next.facts).toHaveLength(0);
    expect(rejected).toEqual([{ kind: "fact", reason: "missing source_turn_ids" }]);
  });

  test("medication reminder missing fields gets needs_user_confirmation", () => {
    const env: TurnEnvelope = {
      visit_id: "v1",
      turn_id: "t1",
      facts: [],
      draft_tasks: [],
      draft_reminders: [
        {
          task_id: "r1",
          task_type: "medication_reminder",
          title: "med",
          description: "",
          medication_name: null,
          dose: null,
          frequency: "每天饭后吃一次",
          timing: "饭后",
          duration: "三天",
          start_date: null,
          end_date: null,
          recurrence: null,
          status: "complete_pending_confirmation",
          requires_user_confirmation: true,
          confirmation_status: "pending",
          blocking_missing_fields: [],
          source_fact_ids: [],
          source_turn_ids: ["t1"],
          created_at: new Date().toISOString(),
        },
      ] as never,
      clarifying_questions: [],
      memory_candidates: [],
      safety_flags: [],
    };
    const { next } = reduceTurn(emptyVisit(), env);
    expect(next.draft_reminders).toHaveLength(1);
    const r = next.draft_reminders[0]!;
    expect(r.status).toBe("needs_user_confirmation");
    expect(r.blocking_missing_fields).toEqual(expect.arrayContaining(["medication_name", "dose"]));
    // A confirmation task should have been auto-created.
    const cq = next.draft_tasks.find((t) => t.task_type === "question");
    expect(cq).toBeTruthy();
  });

  // Regression: a batched analyze_turn ran 4 commit-partial passes; each
  // pass stripped only the canonical turn_id and re-reduced the same
  // envelope, so items the LLM attributed to non-canonical members
  // accumulated 4× copies. The reducer now dedupes by content fingerprint.
  test("dedupes facts re-emitted across multiple commits within a turn", () => {
    const fact = {
      fact_id: "f-canonical-1",
      fact_type: "symptom",
      original_text: "I had a fever and a cough for three days",
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
      confidence: "high",
      requires_confirmation: true,
      // The LLM attributed the fact to a non-canonical (earlier) turn,
      // which is exactly what removeTurnContributions(canonicalTurnId)
      // does NOT clean up.
      source_turn_ids: ["t-non-canonical"],
      created_by_agent: "medical_instruction_extractor",
      created_at: new Date().toISOString(),
    };
    const env: TurnEnvelope = {
      visit_id: "v1",
      turn_id: "t-canonical",
      facts: [fact] as never,
      draft_tasks: [],
      draft_reminders: [],
      clarifying_questions: [],
      memory_candidates: [],
      safety_flags: [],
    };
    let state = emptyVisit();
    // Simulate the four passes (pass1, pass1.5, pass2, final) re-emitting
    // the same envelope without removeTurnContributions stripping it.
    for (let i = 0; i < 4; i++) {
      const out = reduceTurn(state, env);
      state = out.next;
    }
    expect(state.facts).toHaveLength(1);
    expect(state.facts[0]!.original_text).toBe(
      "I had a fever and a cough for three days",
    );
  });

  test("dedupVisitState collapses pre-existing duplicate accumulators", () => {
    const baseFact = {
      fact_id: "f1",
      fact_type: "symptom" as const,
      original_text: "fever for three days",
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
      confidence: "high" as const,
      requires_confirmation: true,
      source_turn_ids: ["t1"],
      created_by_agent: "medical_instruction_extractor" as const,
      created_at: new Date().toISOString(),
    };
    const polluted: VisitState = {
      ...emptyVisit(),
      facts: [
        baseFact,
        { ...baseFact, fact_id: "f2" },
        { ...baseFact, fact_id: "f3" },
        { ...baseFact, fact_id: "f4" },
      ],
    } as VisitState;
    const cleaned = dedupVisitState(polluted);
    expect(cleaned.facts).toHaveLength(1);
    expect(cleaned.facts[0]!.fact_id).toBe("f1");
  });

  test("memory candidates always require user confirmation", () => {
    const env: TurnEnvelope = {
      visit_id: "v1",
      turn_id: "t1",
      facts: [],
      draft_tasks: [],
      draft_reminders: [],
      clarifying_questions: [],
      memory_candidates: [
        {
          memory_candidate_id: "mc1",
          memory_type: "allergy",
          content: "Allergy to penicillin",
          confidence: "high",
          source_turn_ids: ["t1"],
          requires_user_confirmation: true,
          confirmation_status: "pending",
        },
      ] as never,
      safety_flags: [],
    };
    const { next } = reduceTurn(emptyVisit(), env);
    expect(next.memory_candidates).toHaveLength(1);
    expect(next.memory_candidates[0]!.requires_user_confirmation).toBe(true);
    expect(next.memory_candidates[0]!.confirmation_status).toBe("pending");
  });
});
