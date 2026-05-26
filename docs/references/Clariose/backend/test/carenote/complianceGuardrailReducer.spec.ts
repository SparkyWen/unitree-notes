import { applyGuardrail, type TurnEnvelope } from "../../src/modules/carenote/codex-harness/codexGuardrailReducer";

const baseEnv = (): TurnEnvelope => ({
  visit_id: "v1",
  turn_id: "t1",
  facts: [],
  draft_tasks: [],
  draft_reminders: [],
  clarifying_questions: [],
  memory_candidates: [],
  safety_flags: [],
});

describe("ComplianceGuardrailReducer", () => {
  test("safe envelope passes through unchanged", () => {
    const env = baseEnv();
    const out = applyGuardrail(env, {
      is_safe: true,
      blocked_items: [],
      required_user_confirmations: [],
      safe_output_patch: {},
    });
    expect(out.envelope).toEqual(env);
    expect(out.blocked).toEqual([]);
  });

  test("required_user_confirmations are appended as high-priority clarifying questions", () => {
    const env = baseEnv();
    const out = applyGuardrail(env, {
      is_safe: true,
      blocked_items: [],
      required_user_confirmations: ["Confirm the medication name with the pharmacist."],
      safe_output_patch: {},
    });
    expect(out.envelope.clarifying_questions).toHaveLength(1);
    expect(out.envelope.clarifying_questions[0]!.priority).toBe("high");
  });

  test("blocked items become guardrail_blocked safety flags", () => {
    const env = baseEnv();
    const out = applyGuardrail(env, {
      is_safe: false,
      blocked_items: [
        {
          item: "The patient has pneumonia.",
          reason: "diagnosis",
          suggested_rewrite: "The transcript recorded that the doctor mentioned pneumonia.",
        },
      ],
      required_user_confirmations: [],
      safe_output_patch: {},
    });
    expect(out.envelope.safety_flags).toHaveLength(1);
    expect(out.envelope.safety_flags[0]!.flag_type).toBe("guardrail_blocked");
  });
});
