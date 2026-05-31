import { Module } from "@nestjs/common";

import {
  AgentContextService,
  TeammateContextService,
  WorkloadContextService,
} from "./als";
import { SidechainService, TasksService } from "./tasks";
import { RoleWorkspaceService } from "./roleWorkspace.service";

/**
 * CarenoteRuntimeModule — Layer-1 multi-agent runtime.
 *
 * Bundles the AsyncLocalStorage backpack (agent / teammate / workload) and
 * the Layer-1 TasksService. CareNoteModule imports this so any service
 * (CodexRunManager, MailboxService, BlackboardService, RecallService) can
 * inject these primitives without re-declaring providers in every module.
 *
 * Per CCLearn note 4 §"通信隔离": these are the primitives that prevent
 * cross-agent state leakage when many codex runs share one Node event loop.
 */
@Module({
  providers: [
    AgentContextService,
    TeammateContextService,
    WorkloadContextService,
    SidechainService,
    TasksService,
    RoleWorkspaceService,
  ],
  exports: [
    AgentContextService,
    TeammateContextService,
    WorkloadContextService,
    SidechainService,
    TasksService,
    RoleWorkspaceService,
  ],
})
export class CarenoteRuntimeModule {}
