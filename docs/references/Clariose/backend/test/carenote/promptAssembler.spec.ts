// CLARIOSE_V01 §6 — codexPromptAssembler tests. Verifies dynamic template
// shape, memory injection, isolation contract.

import { assembleCodexPrompt } from "../../src/modules/carenote/codex-harness/codexPromptAssembler";
import {
  VisitStateSchema,
  type VisitState,
} from "../../src/modules/carenote/medical/medicalSchemas";
import type { RecallResult } from "../../src/modules/carenote/recall/recall.types";

function emptyVisit(visit_id = "v-1"): VisitState {
  return VisitStateSchema.parse({
    visit_id,
    language: "zh",
    status: "recording",
    turns: [
      {
        visit_id,
        item_id: "i1",
        previous_item_id: null,
        status: "completed",
        partial_transcript: null,
        transcript: "doctor speaking — start of visit",
        speaker_label: "doctor",
        ordering_confidence: "high",
        source_model: "gpt-realtime-1.5",
        transcription_model: "gpt-4o-transcribe",
        error: null,
        created_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
      },
    ],
  });
}

const NO_RECALL: RecallResult = {
  append: null,
  files: [],
  bytesInjected: 0,
  manifestSize: 0,
  selectedCount: 0,
  latencyMs: 0,
  skipped: "empty",
};

describe("CLARIOSE_V01 §6 — codex prompt assembler", () => {
  test("instructions = role prompt only when recall is empty", () => {
    const out = assembleCodexPrompt({
      role: "medication_reminder_draft",
      rolePrompt: "You are the medication reminder agent.",
      expectedOutputSchemaName: "medication_reminder_draft",
      visitState: emptyVisit(),
      event: { event_kind: "analyze_turn" },
      recall: NO_RECALL,
    });
    expect(out.instructions).toBe("You are the medication reminder agent.");
    expect(out.userMessage).toContain("<visit_context>");
    expect(out.userMessage).toContain("language: zh");
  });

  test("recall.append is concatenated to instructions, not user message", () => {
    const recall: RecallResult = {
      ...NO_RECALL,
      skipped: undefined,
      append: "## Patient Memory Context\n\n# allergies\nPenicillin allergy.",
      files: ["users/u-1/allergies.md"],
      bytesInjected: 60,
      manifestSize: 1,
      selectedCount: 1,
    };
    const out = assembleCodexPrompt({
      role: "medication_reminder_draft",
      rolePrompt: "You are the medication reminder agent.",
      expectedOutputSchemaName: "medication_reminder_draft",
      visitState: emptyVisit(),
      event: { event_kind: "analyze_turn" },
      recall,
    });
    expect(out.instructions).toContain("medication reminder agent");
    expect(out.instructions).toContain("Penicillin allergy");
    expect(out.userMessage).not.toContain("Penicillin allergy");
  });

  test("recent_transcript window respects size", () => {
    const v = emptyVisit();
    for (let i = 2; i <= 10; i++) {
      v.turns.push({
        ...v.turns[0],
        item_id: `i${i}`,
        previous_item_id: `i${i - 1}`,
        transcript: `turn ${i}`,
      });
    }
    const out = assembleCodexPrompt({
      role: "transcript_quality",
      rolePrompt: "x",
      expectedOutputSchemaName: "transcript_quality",
      visitState: v,
      event: {},
      recall: NO_RECALL,
      windowTurns: 3,
    });
    // Only the last 3 turns appear.
    expect(out.userMessage).toContain("turn 10");
    expect(out.userMessage).toContain("turn 9");
    expect(out.userMessage).toContain("turn 8");
    expect(out.userMessage).not.toContain("turn 7");
  });

  test("inbox + blackboard render placeholders when empty (Week 3 wiring)", () => {
    const out = assembleCodexPrompt({
      role: "compliance_guardrail",
      rolePrompt: "x",
      expectedOutputSchemaName: "compliance_guardrail",
      visitState: emptyVisit(),
      event: {},
      recall: NO_RECALL,
    });
    expect(out.userMessage).toContain("<inbox>\n(empty)\n</inbox>");
    expect(out.userMessage).toContain("<blackboard>\n(empty)\n</blackboard>");
  });

  test("inbox messages are rendered in teammate_message tags", () => {
    const out = assembleCodexPrompt({
      role: "medication_reminder_draft",
      rolePrompt: "x",
      expectedOutputSchemaName: "medication_reminder_draft",
      visitState: emptyVisit(),
      event: {},
      recall: NO_RECALL,
      inbox: [
        {
          from: "speaker_role",
          payloadKind: "task_assignment",
          payload: { task: "verify dose" },
        },
      ],
    });
    expect(out.userMessage).toContain('teammate_id="speaker_role"');
    expect(out.userMessage).toContain('kind="task_assignment"');
    expect(out.userMessage).toContain("verify dose");
  });
});
