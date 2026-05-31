// CareNote — Codex-only doctor-visit memory assistant.
//
// Public surface for callers (NestJS controllers, tests, CLIs). The full
// design lives under docs/design/00..08.md and the operator README is at
// docs/CODEx_HARNESS_README.md.

export * from "./medical/medicalSchemas";
export * from "./medical/medicalReducers";
export * from "./medical/memoryRetrieval";
export * from "./medical/visitStateStore";

export * from "./realtime/realtimeEventTypes";
export * from "./realtime/realtimeConfig";
export * from "./realtime/transcriptAssembler";
export * from "./realtime/transcriptEventBus";

export * from "./codex-harness/codexRuntime";
export * from "./codex-harness/codexRuntimeFactory";
export * from "./codex-harness/codexSdkRuntime";
export * from "./codex-harness/codexCliRuntime";
export * from "./codex-harness/codexAppServerRuntime";
export * from "./codex-harness/stubRuntime";
export * from "./codex-harness/codexThreadStore";
export * from "./codex-harness/codexAgentRegistry";
export * from "./codex-harness/codexAgentTeam";
export * from "./codex-harness/codexJobQueue";
export * from "./codex-harness/codexRunManager";
export * from "./codex-harness/codexOutputParser";
export * from "./codex-harness/codexSchemaValidator";
export * from "./codex-harness/codexGuardrailReducer";
export * from "./codex-harness/codexPromptLoader";
export * from "./codex-harness/codexTeamBootstrap";

export * from "./prompts/realtimeSessionPrompt";
export * from "./prompts/transcriptionPrompt";
export * from "./prompts/codexAgentPrompts";

export { assembleHarness } from "./api/codexHarnessApi";
export { CareNoteModule } from "./api/carenote.module";
export { CareNoteService } from "./api/carenote.service";
export { redactPhi, isPhiDebugEnabled } from "./api/redactPhi";
