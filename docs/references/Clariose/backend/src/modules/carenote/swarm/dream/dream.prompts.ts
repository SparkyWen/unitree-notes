// 4-phase dream prompt — modeled on Claude Code's
// services/autoDream/consolidationPrompt.ts but adapted for the per-user
// medical-memory schema (memory_summary / allergies / conditions /
// rollout_summaries / skills / MEMORY.md).
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §7.

import type { DreamPhase, DreamScope } from "./dream.types";

export interface DreamVisitDescriptor {
  visitId: string;
  endedAt: string;
}

export interface DreamPromptInput {
  phase: DreamPhase;
  workspaceRoot: string;
  stagingDir: string;
  visits: DreamVisitDescriptor[];
  scope: DreamScope;
}

export function buildDreamPrompt(input: DreamPromptInput): string {
  const { phase, workspaceRoot, stagingDir, visits, scope } = input;
  const visitList = visits
    .map((v) => `- ${v.visitId} (ended ${v.endedAt})`)
    .join("\n");

  const header = `# Dream — Memory Consolidation (phase ${phaseNumber(phase)}/4)

You are performing a *dream*: a reflective pass over this user's medical
memory. Your output is a small set of edited / created / pruned Markdown
files under the workspace.

Workspace (your cwd): ${workspaceRoot}
Visit transcripts staged at: ${stagingDir}

Visits to review (${visits.length}):
${visitList || "- (none)"}
`;

  let body: string;
  switch (phase) {
    case "orient":
      body = ORIENT_BODY;
      break;
    case "gather":
      body = gatherBody(stagingDir, visits);
      break;
    case "consolidate":
      body = consolidateBody(scope);
      break;
    case "prune":
      body = PRUNE_BODY;
      break;
  }

  return `${header}\n${body}`;
}

function phaseNumber(p: DreamPhase): number {
  return { orient: 1, gather: 2, consolidate: 3, prune: 4 }[p];
}

const ORIENT_BODY = `## Phase 1 — Orient

- \`ls\` the workspace.
- Read MEMORY.md to understand the current index.
- Skim memory_summary.md, allergies.md, conditions.md if they exist.
- List files under rollout_summaries/ and skills/.

Report what you found. **DO NOT edit anything in this phase.**
`;

function gatherBody(stagingDir: string, visits: DreamVisitDescriptor[]): string {
  const reads = visits.map((v) => `- ${stagingDir}/${v.visitId}.md`).join("\n");
  return `## Phase 2 — Gather

For each visit listed above, read its staged transcript file:

${reads}

Note new facts that contradict, extend, or duplicate existing memory.
**DO NOT edit any .md files in this phase** — only read.
`;
}

function consolidateBody(scope: DreamScope): string {
  if (scope.kind === "visit") {
    return `## Phase 3 — Consolidate (single visit: ${scope.visitId})

Write to **exactly** \`rollout_summaries/${scope.visitId}.md\` (one file
per visit — never any other path or filename pattern). Re-dreaming the
same visit overwrites this file in place. Use this frontmatter at the top:

\`\`\`
---
name: visit ${scope.visitId}
type: rollout_summary
last_used: <today YYYY-MM-DD>
keywords: [auto_dream, visit_${scope.visitId}]
---
\`\`\`

**DO NOT modify memory_summary.md.**
**DO NOT modify allergies.md.**
**DO NOT modify conditions.md.**
**DO NOT touch skills/.**
The rest of the workspace is read-only for this run.
`;
  }
  return `## Phase 3 — Consolidate

For each thing worth remembering:
- Update \`memory_summary.md\` for cross-visit insight (≤ 4 KB).
- Write per-visit summaries to **exactly** \`rollout_summaries/<visit_id>.md\`
  — one file per visit, never any other path or filename. Re-dreaming
  the same visit overwrites this file in place.
- Update \`allergies.md\` and \`conditions.md\` only on explicit, sourced facts.
- Add \`skills/<snake_case_name>.md\` only for genuine task patterns.

If a visit's staged transcript has **no clinical content** (no utterances,
no summary), DO NOT create a stub rollout_summary for it. Skip it entirely
and note the skip in your final message. The runner already filters empty
visits from the input list, so this should be rare — but enforce it
defensively.

Every .md file MUST start with frontmatter:

\`\`\`
---
name: <human-readable name>
type: summary | rollout_summary | facts | skill
last_used: <today YYYY-MM-DD>
keywords: [auto_dream, ...]
---
\`\`\`

Convert relative dates ("yesterday", "last week") to absolute dates.
Do NOT include PHI like full names, contact info, or addresses.
`;
}

const PRUNE_BODY = `## Phase 4 — Prune and index

Rewrite **MEMORY.md** as a thin index:
- Keep it under **80 lines** AND under **~25 KB**.
- Each entry is one line under ~150 characters:
  \`- [Title](file.md) — one-line hook\`
- Drop pointers to deleted/superseded files.
- Demote verbose lines (>200 chars) by moving the detail back into the
  topic file and shortening the index entry.
- Resolve contradictions; if two files disagree, fix the wrong one.

End with a one-paragraph plain-text summary of what changed.
`;
