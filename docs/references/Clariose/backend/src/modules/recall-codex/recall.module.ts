// recall-codex module — NestJS wiring for the knowledge-recall feature.
//
// IMPORTANT: This module is a self-contained add-on. It does NOT depend on
// any of the existing carenote / realtime / sessions modules, and nothing
// in those modules imports anything here. Removing this module from
// AppModule's `imports` array fully disables the feature with zero side
// effects on the existing multi-agent pipeline.

import { Module } from "@nestjs/common";
import { ConfigModule } from "@nestjs/config";

import { FilesystemBootstrapper } from "./filesystemBootstrapper";
import { MemoryRootResolver } from "./memoryRootResolver";
import { RecallChatController } from "./recallChat.controller";
import { RecallCoordinatorService } from "./recallCoordinator.service";
import { RecallNotesController } from "./recallNotes.controller";
import { RecallNotesService } from "./recallNotes.service";
import { RecallSessionStore } from "./recallSession.store";
import { RecallSessionsController } from "./recallSessions.controller";
import { Phase1Worker } from "./phase1.worker";
import { Phase2LockService } from "./phase2.lock.service";
import { Phase2Worker } from "./phase2.worker";
import { RecallCron } from "./recall.cron";

@Module({
  imports: [ConfigModule],
  providers: [
    MemoryRootResolver,
    FilesystemBootstrapper,
    RecallNotesService,
    RecallSessionStore,
    RecallCoordinatorService,
    Phase1Worker,
    Phase2LockService,
    Phase2Worker,
    RecallCron,
  ],
  controllers: [
    RecallNotesController,
    RecallSessionsController,
    RecallChatController,
  ],
  exports: [],
})
export class RecallCodexModule {}
