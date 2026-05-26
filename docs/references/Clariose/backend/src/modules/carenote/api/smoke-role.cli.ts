// Smoke CLI for a single role.
//
// Runs ONE role end-to-end against an inline transcript turn and prints
// the runtime/command/thread/parse/validation status with previews. The
// goal is to make codex-cli failures impossible to miss when the full
// 11-role pipeline produces an empty VisitState.
//
// Usage:
//   npm run carenote:codex:smoke-role -- <role> --inline "<transcript>"
//
// PHI: outputs are redacted unless DEBUG_CARENOTE_PHI=true. When
// DEBUG_CARENOTE_CODEX=true, full per-run debug artifacts also land at
// .data/carenote/debug/codex-runs/<ts>-<role>-<runId>/ for each run.

import { resolve } from "node:path";

import {
  CodexAgentRoleSchema,
  RoleOutputSchemas,
  VisitStateSchema,
  type CodexAgentRole,
} from "../medical/medicalSchemas";
import { bootstrapCareNoteTeam } from "../codex-harness/codexTeamBootstrap";
import { parseCodexJson } from "../codex-harness/codexOutputParser";
import { validateRoleOutput } from "../codex-harness/codexSchemaValidator";
import { zodToJsonSchema } from "../codex-harness/zodToJsonSchemaShim";
import { preview } from "../codex-harness/codexDebugCapture";

// M7.6 — accept the user-facing aliases so the team redesign vocabulary
// works on the CLI even though the internal role names are unchanged.
const ROLE_ALIASES: Record<string, string> = {
  transcript_verification: "transcript_quality",
  clarification_question: "safety_clarification",
  medication_schedule_draft: "medication_reminder_draft",
  caregiver_notification: "family_summary",
  safety_guardrail: "compliance_guardrail",
};

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  let forceStub = false;
  let role: CodexAgentRole | null = null;
  let inline: string | null = null;
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!;
    if (a === "--stub") forceStub = true;
    else if (a === "--inline") {
      inline = args[++i] ?? null;
    } else if (!role) {
      const aliased = ROLE_ALIASES[a] ?? a;
      const r = CodexAgentRoleSchema.safeParse(aliased);
      if (!r.success) {
        console.error(`unknown role: ${a}`);
        console.error(
          `valid: ${CodexAgentRoleSchema.options.join(", ")} (aliases: ${Object.keys(ROLE_ALIASES).join(", ")})`,
        );
        process.exit(2);
      }
      role = r.data;
    }
  }
  if (!role || !inline) {
    console.error(
      'usage: smoke-role <role> [--stub] --inline "<transcript text>"',
    );
    process.exit(2);
    return;
  }

  const repoRoot = resolve(__dirname, "../../../../..");
  const debugDir = resolve(repoRoot, ".data/carenote/debug/codex-runs");
  const boot = await bootstrapCareNoteTeam({
    repoRoot,
    runtime: forceStub ? { force: "stub", debugDir } : { debugDir },
  });

  const visit_id = `smoke-${Date.now()}`;
  const turn_id = "itm-smoke-1";
  const turnEvent = {
    event_kind: "analyze_turn",
    visit_id,
    turn: { item_id: turn_id, transcript: inline },
  };

  const out = await boot.team.run(role, {
    team_id: boot.team.teamId,
    visit_id,
    role,
    prompt_version: "1.0.0",
    schema_version: "1.0.0",
    event: turnEvent,
    visit_state_snapshot: VisitStateSchema.parse({
      visit_id,
      language: "zh",
      status: "recording",
    }),
    memory_context: [],
    instructions: "",
    expected_output_schema_name: role,
    expected_output_schema: zodToJsonSchema(RoleOutputSchemas[role]),
  });

  const parsed = parseCodexJson(out.raw_text);
  let validation_status: string;
  let validation_errors: string[] = [];
  let parsed_json: unknown = undefined;
  if (parsed.ok) {
    parsed_json = parsed.value;
    const v = validateRoleOutput(role, parsed.value);
    validation_status = v.ok ? "valid" : "invalid";
    if (!v.ok) validation_errors = v.errors;
  } else {
    validation_status = "failed";
    validation_errors = [parsed.error];
  }

  const extra = (out.extra ?? {}) as {
    command?: string;
    stdout?: string;
    stderr?: string;
    exit_code?: number | null;
    debug_dir?: string;
  };

  const report = {
    runtime: boot.runtime.runtime.name,
    runtime_reason: boot.runtime.reason,
    role,
    thread_id: out.thread_id,
    command: extra.command ?? "(runtime did not provide command)",
    exit_code: extra.exit_code ?? null,
    stdout_preview: preview(extra.stdout),
    stderr_preview: preview(extra.stderr),
    raw_output: preview(out.raw_text),
    parsed_json,
    validation_status,
    errors: [...(out.errors ?? []), ...validation_errors],
    debug_dir: extra.debug_dir,
  };
  console.log(JSON.stringify(report, null, 2));

  if (validation_status === "failed" || validation_status === "invalid") {
    process.exit(4);
  }
}

main().catch((err) => {
  console.error("[carenote smoke-role] fatal:", err);
  process.exit(1);
});
