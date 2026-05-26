// Mock-turn CLI: feeds a single transcript turn into the harness and
// prints the resulting VisitState slice plus per-agent run reports.
//
// Runtime selection follows the normal CodexRuntimeFactory rules: it
// auto-selects codex-sdk / codex-cli when available and authenticated,
// and falls back to stub otherwise. Pass `--stub` (or set
// CARENOTE_CODEX_RUNTIME=stub) to force the deterministic stub runtime.
//
// Exit codes:
//   0 — success
//   2 — bad CLI args
//   3 — real (codex-cli/sdk) runtime produced an entirely empty VisitState
//       AND every agent run failed/was rejected. Pass --allow-empty to
//       suppress this guard during exploration.
//
// Usage:
//   npm run carenote:codex:mock-turn -- backend/src/modules/carenote/fixtures/transcripts/fixture-1-missing-dose.json
//   npm run carenote:codex:mock-turn -- --inline "我对青霉素过敏。"
//   npm run carenote:codex:mock-turn -- --stub fixture.json

import { readFile } from "node:fs/promises";

import { assembleHarness } from "./codexHarnessApi";
import type { AgentRunRecorded } from "../codex-harness/codexRunManager";
import { preview } from "../codex-harness/codexDebugCapture";

type FixtureTurn = {
  item_id: string;
  previous_item_id?: string | null;
  speaker_label?: "doctor" | "patient" | "family" | "unknown";
  transcript: string;
};

type Fixture = {
  name?: string;
  language?: "zh" | "en" | "mixed";
  turns: FixtureTurn[];
};

async function main(): Promise<void> {
  const rawArgs = process.argv.slice(2);
  let forceStub = false;
  let allowEmpty = false;
  const args: string[] = [];
  for (const a of rawArgs) {
    if (a === "--stub") forceStub = true;
    else if (a === "--allow-empty") allowEmpty = true;
    else args.push(a);
  }

  let fixture: Fixture;
  if (args[0] === "--inline" && args[1]) {
    fixture = {
      name: "inline",
      language: "zh",
      turns: [{ item_id: "itm-1", previous_item_id: null, transcript: args[1] }],
    };
  } else if (args[0]) {
    const raw = await readFile(args[0], "utf8");
    fixture = JSON.parse(raw) as Fixture;
  } else {
    console.error(
      "usage: mock-turn [--stub] [--allow-empty] <fixture.json>  |  mock-turn [--stub] --inline \"<transcript>\"",
    );
    process.exit(2);
    return;
  }

  const harness = await assembleHarness({ forceStub });
  const runtimeName = harness.bootstrap.runtime.runtime.name;
  const visit_id = `visit-${Date.now()}`;
  harness.visits.ensure(visit_id, fixture.language ?? "zh");

  for (const t of fixture.turns) {
    harness.bus.publish({
      event_type: "doctor_visit.transcript_turn.completed",
      event_id: `evt-${t.item_id}`,
      visit_id,
      turn: {
        item_id: t.item_id,
        previous_item_id: t.previous_item_id ?? null,
        transcript: t.transcript,
        speaker_label: t.speaker_label,
        ordering_confidence: "high",
      },
      source: {
        provider: "openai",
        api: "realtime",
        realtime_model: "gpt-realtime-1.5",
        transcription_model: "gpt-4o-transcribe",
      },
      created_at: new Date().toISOString(),
    });
  }

  // Wait for the bus → queue handoff to settle, then drain.
  await new Promise((r) => setTimeout(r, 50));
  while (harness.queue.pendingCount() > 0 || harness.queue.inFlightCount() > 0) {
    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, 50));
  }
  await new Promise((r) => setTimeout(r, 100));

  const final = await harness.visits.get(visit_id);
  const blocked = harness.analyzed.flatMap((a) => a.blocked);
  const agentRuns = harness.runs.map((r) => projectRun(r));

  const isRealRuntime = runtimeName === "codex-cli" || runtimeName === "codex-sdk";
  const stateEmpty =
    final.facts.length === 0 &&
    final.draft_tasks.length === 0 &&
    final.draft_reminders.length === 0 &&
    final.clarifying_questions.length === 0 &&
    final.family_summary_deltas.length === 0 &&
    final.memory_candidates.length === 0 &&
    final.safety_flags.length === 0;
  const allRunsBad = agentRuns.length > 0 && agentRuns.every(
    (r) => r.validation_status === "failed" || r.validation_status === "invalid",
  );

  console.log(JSON.stringify(
    {
      runtime: runtimeName,
      runtime_reason: harness.bootstrap.runtime.reason,
      visit_state: final,
      blocked_items: blocked,
      agent_runs: agentRuns,
    },
    null,
    2,
  ));

  if (isRealRuntime && stateEmpty && allRunsBad && !allowEmpty) {
    console.error(
      `\n[carenote mock-turn] runtime=${runtimeName} produced empty VisitState and every agent run failed.`,
    );
    console.error("Pass --allow-empty to silence this guard.");
    process.exit(3);
  }
}

function projectRun(r: AgentRunRecorded): Record<string, unknown> {
  const extra = (r.extra ?? {}) as {
    command?: string;
    exit_code?: number | null;
    stdout?: string;
    stderr?: string;
    debug_dir?: string;
  };
  return {
    role: r.role,
    runtime: extra.command ? "codex-cli" : undefined,
    thread_id: r.thread_id,
    validation_status: r.validation_status,
    schema_name: r.schema_name,
    repair_attempted: r.repair_attempted ?? false,
    errors: [...(r.errors ?? []), ...(r.validation_errors ?? [])],
    raw_output_preview: preview(r.raw_output_preview ?? r.raw_text),
    stdout_preview: preview(extra.stdout),
    stderr_preview: preview(extra.stderr),
    exit_code: extra.exit_code,
    debug_dir: extra.debug_dir,
  };
}

main().catch((err) => {
  console.error("[carenote mock-turn] fatal:", err);
  process.exit(1);
});
