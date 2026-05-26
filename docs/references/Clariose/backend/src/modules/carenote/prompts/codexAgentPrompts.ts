// Constants describing where the agent prompts live on disk. The actual
// prompt bodies live as Markdown files under `prompts/codex-agents/` so
// that they can be reviewed, diffed, and edited without TS rebuilds.

import type { CodexAgentRole } from "../medical/medicalSchemas";

export const CODEX_AGENT_PROMPT_FILES: Record<CodexAgentRole, string> = {
  visit_orchestrator: "prompts/codex-agents/visit_orchestrator.md",
  transcript_noise_filter: "prompts/codex-agents/transcript_noise_filter.md",
  transcript_quality: "prompts/codex-agents/transcript_quality.md",
  speaker_role: "prompts/codex-agents/speaker_role.md",
  medical_instruction_extractor: "prompts/codex-agents/medical_instruction_extractor.md",
  medication_reminder_draft: "prompts/codex-agents/medication_reminder_draft.md",
  follow_up_task_draft: "prompts/codex-agents/follow_up_task_draft.md",
  safety_clarification: "prompts/codex-agents/safety_clarification.md",
  family_summary: "prompts/codex-agents/family_summary.md",
  memory_update: "prompts/codex-agents/memory_update.md",
  compliance_guardrail: "prompts/codex-agents/compliance_guardrail.md",
  final_visit_summary: "prompts/codex-agents/final_visit_summary.md",
};

export const JSON_REPAIR_PROMPT_FILE = "prompts/codex-agents/_json_repair.md";
