// CareNote NestJS module wiring. Hung off AppModule.
//
// Layered structure:
//   - CarenoteRuntimeModule: Layer-1 (AsyncLocalStorage backpack + Tasks).
//     Imported here so codex-side code can inject AgentContext/Teammate/
//     Workload + TasksService without redeclaring providers.
//   - This module: API surface, codex harness, recall pipeline, swarm
//     services (Layer-2 mailbox / Layer-3 blackboard / Layer-4 eventBus),
//     auto-dream cron.

import { Module } from "@nestjs/common";
import { CareNoteService } from "./carenote.service";
import { CareNoteVisitsController } from "./carenote.controller";
import { CareNoteRealtimeController } from "./carenoteRealtime.controller";
import { TasksController } from "./tasks.controller";
import { CarenoteEventBus } from "../swarm/eventBus";
import { PrismaModule } from "../../../common/prisma/prisma.module";

// CLARIOSE_V01 §4 — recall pipeline.
import { RecallCache } from "../recall/recallCache";
import { MemoryScanService } from "../recall/memoryScan";
import { MemorySideQueryService } from "../recall/memorySideQuery";
import { MemorySurfaceService } from "../recall/memorySurface";
import { RecallBudgetService } from "../recall/recallBudget";
import { MemoryRecallService } from "../recall/memoryRecall";

// 4-layer multi-agent communication.
import { MailboxFileService } from "../swarm/mailboxFile";
import { MailboxService } from "../swarm/mailboxService";
import { BlackboardService } from "../swarm/blackboard";
import { DraftTasksService } from "../swarm/tasks";
import { SubscriptionRegistry } from "../swarm/subscriptionRegistry";

// CLARIOSE_V03 §dream — auto + manual memory consolidation.
import { ConsolidationLockService } from "../swarm/consolidationLock";
import { DreamCronService } from "../swarm/dreamCron";
import { DreamGates } from "../swarm/dream/dream.gates";
import { DreamWorkspace } from "../swarm/dream/dream.workspace";
import { DreamSessionRegistry } from "../swarm/dream/dream.session";
import { DreamCodexFork } from "../swarm/dream/dream.codexFork";
import { DreamRunner } from "../swarm/dream/dream.runner";
import { DreamController } from "../swarm/dream/dream.controller";

// Layer-1 runtime (AsyncLocalStorage + Tasks).
import { CarenoteRuntimeModule } from "../runtime/runtime.module";

// Pause-driven team retrospective (text digest + infographic image).
import { TeamRecapService } from "../recap/teamRecap.service";

// CLARIOSE_V02 — round-folder persistence + reverse translate-TTS.
import { VisitFolderService } from "./visitFolder.service";
import { TranslateTtsService } from "./translateTts.service";

@Module({
  imports: [PrismaModule, CarenoteRuntimeModule],
  controllers: [
    CareNoteVisitsController,
    CareNoteRealtimeController,
    TasksController,
    DreamController,
  ],
  providers: [
    CareNoteService,
    CarenoteEventBus,
    // recall
    RecallCache,
    MemoryScanService,
    MemorySideQueryService,
    MemorySurfaceService,
    RecallBudgetService,
    MemoryRecallService,
    // 4-layer comm
    MailboxFileService,
    MailboxService,
    BlackboardService,
    DraftTasksService,
    SubscriptionRegistry,
    // dream (auto + manual)
    ConsolidationLockService,
    DreamGates,
    DreamWorkspace,
    DreamSessionRegistry,
    DreamCodexFork,
    DreamRunner,
    DreamCronService,
    // team recap (pause-driven retrospective + infographic)
    TeamRecapService,
    // CLARIOSE_V02 — round folders + reverse TTS
    VisitFolderService,
    TranslateTtsService,
  ],
  exports: [
    CareNoteService,
    CarenoteEventBus,
    MemoryRecallService,
    MailboxService,
    BlackboardService,
    DraftTasksService,
    DreamRunner,
    TeamRecapService,
    CarenoteRuntimeModule,
  ],
})
export class CareNoteModule {}
