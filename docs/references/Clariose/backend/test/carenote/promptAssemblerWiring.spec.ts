// CLARIOSE_V01 §6 — verify the assembler's user message actually reaches the
// codex runtime via pre_built_user_message. Uses the stub runtime's override
// hook to capture the input that would have hit codex.

import { resolve } from "node:path";

import { ConfigService } from "@nestjs/config";

import { CareNoteService } from "../../src/modules/carenote/api/carenote.service";
import { assembleHarness } from "../../src/modules/carenote/api/codexHarnessApi";
import type { CodexAgentRunInput } from "../../src/modules/carenote/codex-harness/codexRuntime";
import type { StubRuntime } from "../../src/modules/carenote/codex-harness/stubRuntime";
import { makeFakePrisma } from "./fakePrisma";

const repoRoot = resolve(__dirname, "../../..");

describe("CLARIOSE_V01 §6 — assembler user-message reaches codex runtime", () => {
  test("pre_built_user_message contains visit_context + recent_transcript blocks", async () => {
    const harness = await assembleHarness({ repoRoot, forceStub: true });
    const cfg = new ConfigService();
    const { CarenoteEventBus } = await import(
      "../../src/modules/carenote/swarm/eventBus"
    );
    const svc = new CareNoteService(
      cfg,
      new CarenoteEventBus(),
      makeFakePrisma(),
    );
    svc.setHarnessForTest(harness);

    // Capture the input every stub.run() receives. We only inspect role
    // medical_instruction_extractor since it gets called early.
    const captured: CodexAgentRunInput[] = [];
    const stub = harness.bootstrap.runtime.runtime as unknown as StubRuntime;
    stub.setOverride("medical_instruction_extractor", (input) => {
      captured.push(input);
      return JSON.stringify({ facts: [], summary: "stub" });
    });

    try {
      const { visit_id } = await svc.createVisit({
        ownerUserId: "u1",
        consent_recorded: true,
      });
      await svc.ingestRealtimeEvent(visit_id, {
        type: "input_audio_buffer.committed",
        item_id: "i1",
        previous_item_id: null,
      });
      await svc.ingestRealtimeEvent(visit_id, {
        type: "conversation.item.input_audio_transcription.completed",
        item_id: "i1",
        transcript: "饭后吃一次，连续三天",
      });
      await svc.waitForQueueIdle();

      expect(captured.length).toBeGreaterThan(0);
      const inp = captured[0]!;

      // Pre-built user message went in (this is what the assembler produced).
      expect(inp.pre_built_user_message).toBeTruthy();
      const msg = inp.pre_built_user_message!;

      // Structured blocks per §6 dynamic template.
      expect(msg).toContain("<visit_context>");
      expect(msg).toContain(`visit_id: ${visit_id}`);
      expect(msg).toContain('<recent_transcript window="5">');
      expect(msg).toContain("饭后吃一次");
      expect(msg).toContain("<inbox>");
      expect(msg).toContain("(empty)"); // Week 3 wires the real mailbox
      expect(msg).toContain("<blackboard>");
      expect(msg).toContain("<event>");
      expect(msg).toContain("<expected_output_schema_name>");
      expect(msg).toContain("medical_instruction_extractor");
    } finally {
      await harness.queue.stop();
    }
  });
});
