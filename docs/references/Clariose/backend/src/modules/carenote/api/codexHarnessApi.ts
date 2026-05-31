// codexHarnessApi — assembles the harness graph for use by the NestJS
// controllers, the mock-turn CLI, and tests. Stays framework-agnostic so
// it is callable from anywhere.

import { resolve } from "node:path";

import type {
  AgentRunRecorded,
  AnalyzeTurnResult,
} from "../codex-harness/codexRunManager";
import { CodexRunManager } from "../codex-harness/codexRunManager";
import {
  bootstrapCareNoteTeam,
  type BootstrapResult,
} from "../codex-harness/codexTeamBootstrap";
import {
  InMemoryCodexJobQueue,
  type CodexJob,
  type CodexJobQueue,
} from "../codex-harness/codexJobQueue";
import {
  InMemoryMemoryRetrievalService,
  type MemoryRetrievalService,
} from "../medical/memoryRetrieval";
import { InMemoryVisitStateStore } from "../medical/visitStateStore";
import { InMemoryTranscriptEventBus } from "../realtime/transcriptEventBus";
import { TranscriptAssembler } from "../realtime/transcriptAssembler";
import type { MemoryRecallService } from "../recall/memoryRecall";
import type { MailboxService } from "../swarm/mailboxService";
import type { BlackboardService } from "../swarm/blackboard";
import type { SubscriptionRegistry } from "../swarm/subscriptionRegistry";
import type { CodexAgentRole } from "../medical/medicalSchemas";
import type { CarenoteEventBus } from "../swarm/eventBus";
import type { TasksService } from "../runtime/tasks/tasks.service";
import type {
  AgentContextService,
  TeammateContextService,
  WorkloadContextService,
} from "../runtime/als";
import type { RoleWorkspaceService } from "../runtime/roleWorkspace.service";

export type CareNoteHarness = {
  bootstrap: BootstrapResult;
  manager: CodexRunManager;
  queue: CodexJobQueue;
  visits: InMemoryVisitStateStore;
  memory: InMemoryMemoryRetrievalService;
  bus: InMemoryTranscriptEventBus;
  assembler: TranscriptAssembler;
  /** Per-turn agent runs collected by the manager via recordAgentRun. */
  runs: AgentRunRecorded[];
  /** AnalyzeTurn results in fire order. */
  analyzed: AnalyzeTurnResult[];
};

export async function assembleHarness(opts?: {
  repoRoot?: string;
  forceStub?: boolean;
  /** CLARIOSE_V01 §4 — file-based recall pipeline. Optional in tests. */
  recall?: MemoryRecallService;
  /** Owner lookup so recall can pick user-scoped memory. Optional. */
  visitOwnerLookup?: (visit_id: string) => Promise<string | null>;
  /** CLARIOSE_V01 §3 — 4-layer comm services. Optional in tests. */
  mailbox?: MailboxService;
  blackboard?: BlackboardService;
  subscriptions?: SubscriptionRegistry;
  /** CLARIOSE_V01 §8 — emits agent_run_started/completed for SSE. */
  eventBus?: CarenoteEventBus;
  /**
   * Layer-1 multi-agent runtime (CCLearn note 4). When provided, every
   * codex role-run is wrapped in a RuntimeTask + AsyncLocalStorage backpack
   * so downstream layers (mailbox, blackboard, eventBus, recall) attribute
   * via `agentCtx.current()` instead of plumbed arguments.
   */
  tasks?: TasksService;
  agentCtx?: AgentContextService;
  teammateCtx?: TeammateContextService;
  workloadCtx?: WorkloadContextService;
  /** Per-role on-disk workspace (memory/, artifacts/, skills/, inboxes/). */
  roleWorkspace?: RoleWorkspaceService;
  /** Extra hook invoked alongside the in-memory recordAgentRun. The carenote
   *  service uses it to mirror runs into `carenote_agent_runs` so the team
   *  activity panel can show them across requests. */
  onRunRecorded?: (rec: AgentRunRecorded) => Promise<void>;
}): Promise<CareNoteHarness> {
  const repoRoot = opts?.repoRoot ?? resolve(__dirname, "../../../../..");
  // CLARIOSE_DATA_ROOT lets dev/test point writes outside the prod tree.
  const dataOverride = process.env.CLARIOSE_DATA_ROOT?.trim();
  const debugDir = dataOverride
    ? resolve(dataOverride, "carenote/debug/codex-runs")
    : resolve(repoRoot, ".data/carenote/debug/codex-runs");
  const bootstrap = await bootstrapCareNoteTeam({
    repoRoot,
    runtime: opts?.forceStub
      ? { force: "stub", debugDir }
      : { debugDir },
  });

  const visits = new InMemoryVisitStateStore();
  const memory: MemoryRetrievalService = new InMemoryMemoryRetrievalService();
  const queue: CodexJobQueue = new InMemoryCodexJobQueue();
  const bus = new InMemoryTranscriptEventBus();
  const assembler = new TranscriptAssembler();

  const runs: AgentRunRecorded[] = [];
  const analyzed: AnalyzeTurnResult[] = [];

  const manager = new CodexRunManager({
    team: bootstrap.team,
    queue,
    visitStateGet: (id) => visits.get(id),
    visitStateSet: (id, next) => visits.set(id, next),
    memory,
    recall: opts?.recall,
    visitOwnerLookup: opts?.visitOwnerLookup,
    mailbox: opts?.mailbox,
    blackboard: opts?.blackboard,
    subscriptions: opts?.subscriptions,
    eventBus: opts?.eventBus,
    tasks: opts?.tasks,
    agentCtx: opts?.agentCtx,
    teammateCtx: opts?.teammateCtx,
    workloadCtx: opts?.workloadCtx,
    roleWorkspace: opts?.roleWorkspace,
    recordAgentRun: async (rec) => {
      runs.push(rec);
      if (opts?.onRunRecorded) {
        try {
          await opts.onRunRecorded(rec);
        } catch {
          // The DB mirror is best-effort: in-memory state is the source of
          // truth for the run pipeline, so a persistence failure should not
          // break role execution.
        }
      }
    },
    onAnalyzed: async (r: AnalyzeTurnResult) => {
      analyzed.push(r);
    },
  });

  // Register the team's default subscriptions BEFORE starting (start wires
  // the bus and triggers fire from there).
  if (opts?.subscriptions) {
    const roleNames = bootstrap.team
      .manifest()
      .agents.map((a) => a.role as CodexAgentRole);
    opts.subscriptions.registerDefaultsFor(roleNames);
  }
  manager.start();

  // Wire bus → queue. Each completed transcript turn becomes an analyze_turn job.
  bus.on(async (e) => {
    visits.ensure(e.visit_id);
    const job: CodexJob = {
      kind: "analyze_turn",
      visit_id: e.visit_id,
      turn_id: e.turn.item_id,
      transcript: e.turn.transcript,
      previous_item_id: e.turn.previous_item_id ?? null,
    };
    await queue.enqueue(job);
  });

  return {
    bootstrap,
    manager,
    queue,
    visits,
    memory: memory as InMemoryMemoryRetrievalService,
    bus,
    assembler,
    runs,
    analyzed,
  };
}
