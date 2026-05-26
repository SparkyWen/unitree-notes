// CLARIOSE_V01 §6 — dynamic prompt assembler.
//
// Builds the per-turn input for one codex role. Per the design doc we DO NOT
// optimize for static prompt cache; the codex SDK handles caching internally.
// This assembler favors a clean, complete, dynamic template.
//
// Output:
//   instructions = [A. role prompt] + [B. memory recall append (if any)]
//   userMessage  = structured XML-ish block with visit_context, recent_transcript,
//                  inbox (Layer 1 mailbox drain — Week 3), blackboard (Week 3),
//                  event, and expected_output_schema_name.
//
// Week 2 lands instructions + userMessage assembly with memory recall wired
// in. Inbox + blackboard sections render as empty placeholders until Week 3
// brings them online.

import type {
  CodexAgentRole,
  TranscriptTurn,
  VisitState,
} from "../medical/medicalSchemas";
import type { RecallResult } from "../recall/recall.types";

export type AssembledPrompt = {
  /** What the codex SDK uses as the role's "instructions" (≈ system prompt). */
  instructions: string;
  /** What the SDK passes as the user turn. */
  userMessage: string;
  /** Telemetry the run-manager logs into CarenoteAgentRun. */
  recall: RecallResult;
};

export type AssembleArgs = {
  role: CodexAgentRole;
  /** Static role prompt loaded from prompts/codex-agents/<role>.md */
  rolePrompt: string;
  /** Schema-name string the codex SDK output validator wants. */
  expectedOutputSchemaName: string;
  visitState: VisitState;
  /** The triggering event for this turn (turn_completed payload, json_repair, etc.) */
  event: unknown;
  /** Memory recall result from MemoryRecallService.prefetch. */
  recall: RecallResult;
  /** Recent transcript window size (turn count). */
  windowTurns?: number;
  /** Pre-drained mailbox messages addressed to this role (Layer 1, Week 3). */
  inbox?: Array<{
    from: string;
    payloadKind: string;
    payload: unknown;
  }>;
  /** Subset of blackboard keys this role declared interest in (Week 3). */
  blackboard?: Record<string, unknown>;
};

const DEFAULT_WINDOW = 5;

/**
 * Assemble one turn's prompt input.
 *
 * Per CCLearn note 4 §"DON'T":
 *  - never include another role's raw codex transcript
 *  - never include another visit's mailbox/blackboard
 * The visitState we receive is already scoped to one visit, and we only
 * ever read fields the role is supposed to see.
 */
export function assembleCodexPrompt(args: AssembleArgs): AssembledPrompt {
  const window = args.windowTurns ?? DEFAULT_WINDOW;

  // ── Instructions = role prompt + memory append ──────────────────────────
  let instructions = args.rolePrompt.trim();
  if (args.recall.append) {
    instructions += "\n\n" + args.recall.append.trim();
  }

  // ── User message: structured per-turn payload ───────────────────────────
  const sections: string[] = [];

  // Surface the pause-time noise-filter result so downstream agents can
  // honor their "noise tag awareness" sections — final_visit_summary uses
  // this for the disclaimer line, and any post-filter regenerate sees the
  // per-turn tags here without bloating the user message.
  const nt = args.visitState.noise_tags;
  const noiseSummaryLine = nt
    ? `noise_filter: total=${nt.summary.total_turns} clean=${nt.summary.clean} noise_high_conf=${nt.summary.noise_high_conf} noise_low_conf=${nt.summary.noise_low_conf} partial=${nt.summary.partial} duplicate=${nt.summary.duplicate}`
    : "noise_filter: not_applied";
  const quarantinedTurnIds = nt
    ? nt.turn_tags
        .filter((t) => t.tag === "noise_high_conf")
        .map((t) => t.turn_id)
    : [];
  const quarantinedLine = quarantinedTurnIds.length
    ? `quarantined_turn_ids: ${quarantinedTurnIds.join(", ")}`
    : "quarantined_turn_ids: (none)";

  sections.push(
    block("visit_context", [
      `visit_id: ${args.visitState.visit_id}`,
      `language: ${args.visitState.language}`,
      `status: ${args.visitState.status}`,
      `turn_count: ${args.visitState.turns.length}`,
      noiseSummaryLine,
      quarantinedLine,
    ].join("\n")),
  );

  sections.push(
    blockAttr(
      "recent_transcript",
      { window: String(window) },
      renderTranscriptWindow(args.visitState.turns, window),
    ),
  );

  sections.push(
    block(
      "inbox",
      (args.inbox ?? []).length === 0
        ? "(empty)"
        : args.inbox!
            .map(
              (m) =>
                `<teammate_message teammate_id="${escapeAttr(m.from)}" kind="${escapeAttr(m.payloadKind)}">\n${
                  typeof m.payload === "string"
                    ? m.payload
                    : JSON.stringify(m.payload)
                }\n</teammate_message>`,
            )
            .join("\n\n"),
    ),
  );

  sections.push(
    block(
      "blackboard",
      args.blackboard && Object.keys(args.blackboard).length > 0
        ? JSON.stringify(args.blackboard, null, 2)
        : "(empty)",
    ),
  );

  sections.push(
    block(
      "event",
      typeof args.event === "string"
        ? args.event
        : JSON.stringify(args.event ?? {}, null, 2),
    ),
  );

  sections.push(
    block(
      "expected_output_schema_name",
      args.expectedOutputSchemaName,
    ),
  );

  return {
    instructions,
    userMessage: sections.join("\n\n"),
    recall: args.recall,
  };
}

// ─────────────────────────────────────────────────────────────────────────────

function renderTranscriptWindow(turns: TranscriptTurn[], n: number): string {
  if (turns.length === 0) return "(no turns yet)";
  const tail = turns.slice(-n);
  return tail
    .map((t) => {
      const speaker = t.speaker_label ?? "unknown";
      const text = t.transcript ?? t.partial_transcript ?? "(no text)";
      return `[${speaker} ${t.item_id}] ${text}`;
    })
    .join("\n");
}

function block(tag: string, body: string): string {
  return `<${tag}>\n${body}\n</${tag}>`;
}

function blockAttr(
  tag: string,
  attrs: Record<string, string>,
  body: string,
): string {
  const attrStr = Object.entries(attrs)
    .map(([k, v]) => `${k}="${escapeAttr(v)}"`)
    .join(" ");
  return `<${tag}${attrStr ? " " + attrStr : ""}>\n${body}\n</${tag}>`;
}

function escapeAttr(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
