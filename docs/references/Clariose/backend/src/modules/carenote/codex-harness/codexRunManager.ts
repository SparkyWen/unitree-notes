// CodexRunManager — the orchestrator. Pulls jobs from the queue, runs the
// 11-role pipeline, validates each output, applies the guardrail, and
// reduces into VisitState.

import { randomUUID } from "node:crypto";

import { zodToJsonSchema } from "./zodToJsonSchemaShim";

import {
  ComplianceGuardrailOutputSchema,
  RoleOutputSchemas,
  type CodexAgentRole,
  type ComplianceGuardrailOutput,
  type FamilySummaryOutput,
  type FollowUpTaskDraftOutput,
  type MedicationReminderDraftOutput,
  type MedicalInstructionExtractorOutput,
  type MemoryUpdateOutput,
  type NoiseFilterOutput,
  type NoiseTagsRecord,
  type SafetyClarificationOutput,
  type SpeakerRoleOutput,
  type TranscriptQualityOutput,
  type VisitState,
} from "../medical/medicalSchemas";
import {
  applyGuardrail,
  type TurnEnvelope,
} from "./codexGuardrailReducer";
import { applyNoiseFilter, reduceTurn, removeTurnContributions } from "../medical/medicalReducers";
import { parseCodexJson } from "./codexOutputParser";
import { validateRoleOutput } from "./codexSchemaValidator";
import type { CodexAgentRunOutput } from "./codexRuntime";
import type { CodexAgentTeam } from "./codexAgentTeam";
import type { CodexJob, CodexJobQueue } from "./codexJobQueue";
import type { MemoryRetrievalService } from "../medical/memoryRetrieval";
import type { MemoryRecallService } from "../recall/memoryRecall";
import type { RecallResult } from "../recall/recall.types";
import { assembleCodexPrompt } from "./codexPromptAssembler";
import type { MailboxService } from "../swarm/mailboxService";
import type { BlackboardService } from "../swarm/blackboard";
import type { SubscriptionRegistry } from "../swarm/subscriptionRegistry";
import type { CarenoteEventBus } from "../swarm/eventBus";
import type { TasksService } from "../runtime/tasks/tasks.service";
import type {
  AgentContextService,
  TeammateContextService,
  WorkloadContextService,
} from "../runtime/als";
import type { RoleWorkspaceService } from "../runtime/roleWorkspace.service";
import type { AgentContext, WorkloadKind } from "../runtime/als/types";
import type { RuntimeTask } from "../runtime/tasks/tasks.types";

export type AgentRunRecorded = CodexAgentRunOutput & {
  validation_errors?: string[];
  /** Human-readable preview of raw_text, length-capped. */
  raw_output_preview?: string;
  /** True when the run survived only via the repair pass. */
  repair_attempted?: boolean;
  /** Schema name used to validate, for error reports. */
  schema_name?: string;
};

export type AnalyzeTurnResult = {
  visit_state: VisitState;
  envelope: TurnEnvelope;
  blocked: ComplianceGuardrailOutput["blocked_items"];
  runs: AgentRunRecorded[];
};

export type CodexRunManagerOptions = {
  team: CodexAgentTeam;
  queue: CodexJobQueue;
  visitStateGet: (visit_id: string) => Promise<VisitState>;
  visitStateSet: (visit_id: string, next: VisitState) => Promise<void>;
  memory: MemoryRetrievalService;
  /** CLARIOSE_V01 §4: file-based recall pipeline. Called once per analyze_turn
   *  job (NOT per role) so all 11 roles in one turn share the same recall
   *  result. May be undefined in tests. */
  recall?: MemoryRecallService;
  /** Caller hint: the user this visit belongs to. Plumbed only to recall. */
  visitOwnerLookup?: (visit_id: string) => Promise<string | null>;
  /** CLARIOSE_V01 §3 Layer 1 — file+DB mailbox. Optional in tests. */
  mailbox?: MailboxService;
  /** CLARIOSE_V01 §3 cross-cutting — versioned KV per visit. */
  blackboard?: BlackboardService;
  /** CLARIOSE_V01 §9 — registry of on-demand triggers. Wired into bus at
   *  module init; here we only need it for the single_role hop accounting. */
  subscriptions?: SubscriptionRegistry;
  /** Carenote bus — per-role agent_run_started / agent_run_completed
   *  emits land here so the SSE controller can fan them out to the UI
   *  (the Week-4 End&review wait subscribes to these). */
  eventBus?: CarenoteEventBus;
  /**
   * Layer-1 multi-agent runtime. When wired, every role-run is wrapped in a
   * RuntimeTask + AsyncLocalStorage backpack so downstream layers (mailbox,
   * blackboard, eventBus, recall) see attribution metadata via
   * `agentCtx.current()` instead of having it threaded through arguments.
   * See CCLearn note 4 §"通信隔离".
   */
  tasks?: TasksService;
  agentCtx?: AgentContextService;
  teammateCtx?: TeammateContextService;
  workloadCtx?: WorkloadContextService;
  /**
   * Per-role on-disk workspace (memory/, artifacts/, skills/, inboxes/).
   * Mirrors Qzone's per-agent workspace pattern. When wired, each role's
   * MEMORY.md is loaded once per run and concatenated onto the prompt's
   * extra_instructions so the role sees its private memory alongside the
   * per-turn recall block.
   */
  roleWorkspace?: RoleWorkspaceService;
  recordAgentRun?: (rec: AgentRunRecorded) => Promise<void>;
  onAnalyzed?: (result: AnalyzeTurnResult) => Promise<void>;
};

export class CodexRunManager {
  constructor(private readonly opts: CodexRunManagerOptions) {}

  start(): void {
    this.opts.queue.start((job) => this.process(job));
    // CLARIOSE_V01 §9 — wire the on-demand trigger pipeline. The
    // SubscriptionRegistry watches the bus and invokes our handler when a
    // matching event lands. Handler enqueues a single_role job which the
    // queue serializes per-visit (no two roles for the same visit run
    // concurrently — keeps thread state coherent).
    if (this.opts.subscriptions) {
      this.opts.subscriptions.start(async (ctx) => {
        await this.opts.queue.enqueue({
          kind: "single_role",
          visit_id: ctx.visit_id,
          role: ctx.role,
          reason: ctx.reason,
          hop: ctx.hop + 1,
        });
      });
    }
  }

  /** What blackboard keys to slice for this role's prompt. Defers to the
   *  subscription registry; returns [] when the registry isn't wired. */
  private subscribedKeysFor(role: CodexAgentRole): string[] {
    return this.opts.subscriptions?.blackboardKeysFor(role) ?? [];
  }

  async process(job: CodexJob): Promise<void> {
    // Layer-1 backpack: tag every job kind with a workload classification so
    // downstream telemetry / quota / rate-limit can read it via
    // `workloadCtx.current()` without threading another argument through.
    const workload: WorkloadKind = jobToWorkload(job);
    const run = (): Promise<void> => {
      switch (job.kind) {
        case "analyze_turn":
          return this.analyzeTurn(job).then(() => undefined);
        case "stage_summary":
        case "final_summary":
          return this.summarise(job);
        case "single_role":
          return this.runOneRoleOnDemand(job);
      }
    };
    if (this.opts.workloadCtx) {
      await this.opts.workloadCtx.run(workload, run);
    } else {
      await run();
    }
  }

  /**
   * CLARIOSE_V01 §9 — on-demand single-role re-run, triggered by the
   * SubscriptionRegistry when a blackboard write or mailbox message names
   * this role as interested. Does NOT re-fire the full 11-role pipeline.
   * The role sees the latest VisitState + blackboard + drained mailbox; its
   * output is reduced into VisitState the same way analyze_turn would.
   */
  async runOneRoleOnDemand(
    job: Extract<CodexJob, { kind: "single_role" }>,
  ): Promise<void> {
    const visit = await this.opts.visitStateGet(job.visit_id);
    const role = job.role as CodexAgentRole;
    if (!(role in RoleOutputSchemas)) {
      // Unknown role; silently drop.
      return;
    }
    const triggerEvent = {
      event_kind: "single_role_trigger",
      visit_id: job.visit_id,
      reason: job.reason,
      hop: job.hop,
    };

    // Layer-1 wrap: register a top-level task for the on-demand run so the UI
    // and SSE clients can see why a role is running outside of analyze_turn.
    await this.withParentTask(
      {
        kind: "on_demand_role",
        visitId: job.visit_id,
        role,
        label: `on-demand: ${role} (${job.reason})`,
        description: `Triggered by ${job.reason} at hop ${job.hop}`,
        createdBy: "subscription_registry",
        workload: "on_demand",
      },
      () => this.runRole(role, job.visit_id, triggerEvent, visit, [], null),
    );
    // We deliberately do NOT call reduceTurn here — single_role drafts get
    // recorded into CarenoteAgentRun by recordAgentRun and propagated via
    // EventBus events. Reducer integration for partial pipeline is Week 4.
  }

  async analyzeTurn(job: Extract<CodexJob, { kind: "analyze_turn" }>): Promise<AnalyzeTurnResult> {
    // Layer-1 wrap: the whole pass-1/1.5/2/guardrail fan-out runs under a
    // single parent task. Children (one per role) inherit parentTaskId via
    // AgentContext so task trees render correctly in the UI.
    return this.withParentTask(
      {
        kind: "analyze_turn",
        visitId: job.visit_id,
        label: `analyze_turn ${job.turn_id}`,
        description: `transcript turn ${job.turn_id}`,
        createdBy: "system",
        workload: "turn",
      },
      () => this.analyzeTurnInner(job),
    );
  }

  private async analyzeTurnInner(
    job: Extract<CodexJob, { kind: "analyze_turn" }>,
  ): Promise<AnalyzeTurnResult> {
    const visit = await this.opts.visitStateGet(job.visit_id);
    const memoryHits = await this.opts.memory.retrieve({
      user_id: "user-mvp",
      visit_id: job.visit_id,
      query: job.transcript,
      max_results: 8,
      allowed_memory_status: "confirmed_only",
    });

    // CLARIOSE_V01 §4 — recall once per turn (NOT per role). Pass-1 roles
    // and pass-2 roles share the same RecallResult; sub-agent passes are
    // marked isSubagentFork so they don't re-query (per CCLearn §4 "DO #6").
    let recall: RecallResult | null = null;
    if (this.opts.recall) {
      const ownerUserId = this.opts.visitOwnerLookup
        ? await this.opts.visitOwnerLookup(job.visit_id).catch(() => null)
        : null;
      recall = await this.opts.recall.prefetch({
        visit_id: job.visit_id,
        user_id: ownerUserId,
        query: job.transcript,
      });
      // Lightweight telemetry — visible in pm2 logs, useful for tuning
      // sideQuery latency and seeing what made it into context.
      const summary = recall.skipped
        ? `skipped=${recall.skipped}`
        : `files=${recall.files.length} bytes=${recall.bytesInjected} manifestSize=${recall.manifestSize} selected=${recall.selectedCount}`;
      // eslint-disable-next-line no-console
      console.log(
        `[recall] visit=${job.visit_id} turn=${job.turn_id} latency=${recall.latencyMs}ms ${summary}`,
      );
    }

    const turnEvent = {
      event_kind: "analyze_turn",
      visit_id: job.visit_id,
      turn: { item_id: job.turn_id, transcript: job.transcript },
    };

    // -------------------------------------------------------------------
    // M7.6 pipeline:
    //   1. transcript_verification (transcript_quality)
    //      + speaker_role
    //      + medical_instruction_extractor
    //      run in parallel (pass 1)
    //   2. clarification_question (safety_clarification) sees pass-1
    //      ambiguities + missing_fields
    //   3. medication_schedule_draft (medication_reminder_draft)
    //      + follow_up_task_draft
    //      + caregiver_notification (family_summary)
    //      + memory_candidate (memory_update)
    //      run in parallel using pass-1 + clarification context
    //   4. safety_guardrail (compliance_guardrail) inspects merged envelope
    //      before reducer mutation.
    // -------------------------------------------------------------------

    // Each pass commits its partial envelope to VisitState so the visit
    // page panels populate progressively as agents finish, instead of
    // popping all-at-once at the end of the pipeline. The next pass calls
    // `commitPartial` again with a richer envelope, which strips this
    // turn's prior contributions before re-reducing — so partials never
    // duplicate. The final guardrail step replaces the partial with the
    // safe (filtered) envelope.
    const commitPartial = async (
      env: TurnEnvelope,
      pass: "pass1" | "pass1_5" | "pass2" | "final",
    ): Promise<void> => {
      const latest = await this.opts.visitStateGet(job.visit_id);
      const cleaned = removeTurnContributions(latest, job.turn_id);
      const reduced = reduceTurn(cleaned, env);
      await this.opts.visitStateSet(job.visit_id, reduced.next);
      this.opts.eventBus?.emit({
        type: "turn_partial_committed",
        visitId: job.visit_id,
        turnId: job.turn_id,
        pass,
      });
    };
    const emptyPass1 = {
      transcript_quality: null,
      speaker_role: null,
      medical_instruction_extractor: null,
      safety_clarification: null,
    };
    const emptyPass2 = {
      medication_reminder_draft: null,
      follow_up_task_draft: null,
      family_summary: null,
      memory_update: null,
    };

    // Pass 1: parallel transcript verification, speaker, instruction extractor.
    const [tq, sr, ie] = await Promise.all([
      this.runRole<TranscriptQualityOutput>("transcript_quality", job.visit_id, turnEvent, visit, memoryHits, recall),
      this.runRole<SpeakerRoleOutput>("speaker_role", job.visit_id, turnEvent, visit, memoryHits, recall),
      this.runRole<MedicalInstructionExtractorOutput>("medical_instruction_extractor", job.visit_id, turnEvent, visit, memoryHits, recall),
    ]);

    const pass1 = {
      transcript_quality: tq.parsed,
      speaker_role: sr.parsed,
      medical_instruction_extractor: ie.parsed,
    };

    await commitPartial(
      buildEnvelope(job.visit_id, job.turn_id, {
        pass1: { ...emptyPass1, ...pass1 },
        pass2: emptyPass2,
      }),
      "pass1",
    );

    // Pass 1.5: Clarification Question Agent. Receives ambiguities + missing fields.
    const clarificationEvent = {
      ...turnEvent,
      pass1,
      transcript_ambiguities: tq.parsed?.ambiguities ?? [],
      missing_critical_fields: tq.parsed?.missing_critical_fields ?? [],
      extractor_missing_fields: (ie.parsed?.facts ?? [])
        .flatMap((f: MedicalInstructionExtractorOutput["facts"][number]) => f.missing_fields ?? []),
    };
    const sc = await this.runRole<SafetyClarificationOutput>(
      "safety_clarification",
      job.visit_id,
      clarificationEvent,
      visit,
      memoryHits,
      recall,
    );

    await commitPartial(
      buildEnvelope(job.visit_id, job.turn_id, {
        pass1: { ...pass1, safety_clarification: sc.parsed },
        pass2: emptyPass2,
      }),
      "pass1_5",
    );

    // Pass 2 sees pass1 + clarification.
    const pass2Event = {
      ...turnEvent,
      pass1: { ...pass1, safety_clarification: sc.parsed },
    };
    const [mr, ft, fs, mu] = await Promise.all([
      this.runRole<MedicationReminderDraftOutput>("medication_reminder_draft", job.visit_id, pass2Event, visit, memoryHits, recall),
      this.runRole<FollowUpTaskDraftOutput>("follow_up_task_draft", job.visit_id, pass2Event, visit, memoryHits, recall),
      this.runRole<FamilySummaryOutput>("family_summary", job.visit_id, pass2Event, visit, memoryHits, recall),
      this.runRole<MemoryUpdateOutput>("memory_update", job.visit_id, pass2Event, visit, memoryHits, recall),
    ]);

    // Build envelope.
    const envelope: TurnEnvelope = buildEnvelope(job.visit_id, job.turn_id, {
      pass1: { transcript_quality: tq.parsed, speaker_role: sr.parsed, medical_instruction_extractor: ie.parsed, safety_clarification: sc.parsed },
      pass2: { medication_reminder_draft: mr.parsed, follow_up_task_draft: ft.parsed, family_summary: fs.parsed, memory_update: mu.parsed },
    });

    await commitPartial(envelope, "pass2");

    // Compliance guardrail.
    const cg = await this.runRole<ComplianceGuardrailOutput>(
      "compliance_guardrail",
      job.visit_id,
      { ...turnEvent, envelope: envelope as unknown as Record<string, unknown> },
      visit,
      memoryHits,
      recall,
    );
    const guardrail = cg.parsed ?? ComplianceGuardrailOutputSchema.parse({
      is_safe: false,
      blocked_items: [],
      required_user_confirmations: [],
      safe_output_patch: {},
    });

    const { envelope: safe, blocked } = applyGuardrail(envelope, guardrail);

    // Final commit: replace this turn's partials with the guardrail-filtered
    // safe envelope so blocked content can't survive past pre-guardrail.
    await commitPartial(safe, "final");

    // CLARIOSE_V01 §3 + §9 — bridge agent outputs into the blackboard so
    // downstream subscribers wake up. Each canonical key maps to a slice of
    // the safe envelope; we only write keys that actually changed (cheap
    // deep-equal on JSON), so cooldown-skipped triggers don't fire spuriously.
    if (this.opts.blackboard) {
      void this.publishToBlackboard(job.visit_id, safe).catch((err) =>
        // eslint-disable-next-line no-console
        console.warn(
          `[blackboard] publish failed visit=${job.visit_id} turn=${job.turn_id}: ${(err as Error).message}`,
        ),
      );
    }

    const runs = [tq, sr, ie, sc, mr, ft, fs, mu, cg].map((r) => r.run);
    const finalState = await this.opts.visitStateGet(job.visit_id);
    const result: AnalyzeTurnResult = {
      visit_state: finalState,
      envelope: safe,
      blocked,
      runs,
    };
    if (this.opts.onAnalyzed) await this.opts.onAnalyzed(result);
    return result;
  }

  /**
   * CLARIOSE_V01 §3 — write canonical blackboard keys derived from a turn's
   * safe envelope. Each key is a "fact" downstream agents subscribe to:
   *
   *   allergies                 ← extractor.facts where fact_type='allergy'
   *   medication_plan_draft     ← envelope.draft_reminders
   *   follow_up_tasks           ← envelope.draft_tasks
   *   safety_flags              ← envelope.safety_flags
   *   family_brief              ← envelope.caregiver_notification
   *
   * Per-(visit, key) write is skipped when the value JSON-equals what we
   * already wrote, so cooldown-cleared subscribers don't get woken for
   * unchanged data. Bus emit only happens on real version bumps.
   */
  private async publishToBlackboard(
    visit_id: string,
    envelope: TurnEnvelope,
  ): Promise<void> {
    if (!this.opts.blackboard) return;
    const writeIfChanged = async (
      key: string,
      value: unknown,
      writtenBy: string,
    ) => {
      if (value === undefined || value === null) return;
      const cur = await this.opts.blackboard!.read(visit_id, key);
      if (cur && JSON.stringify(cur.value) === JSON.stringify(value)) return;
      await this.opts.blackboard!.write({ visit_id, key, value, writtenBy });
    };

    // allergies — derived from facts on the envelope
    const allergies = (envelope.facts ?? [])
      .filter((f: { fact_type?: string }) => f?.fact_type === "allergy")
      .map((f: { original_text?: string }) => f.original_text)
      .filter((s): s is string => typeof s === "string" && s.length > 0);
    if (allergies.length > 0) {
      await writeIfChanged(
        "allergies",
        allergies,
        "medical_instruction_extractor",
      );
    }

    if (envelope.draft_reminders.length > 0) {
      await writeIfChanged(
        "medication_plan_draft",
        envelope.draft_reminders,
        "medication_reminder_draft",
      );
    }

    if (envelope.draft_tasks.length > 0) {
      await writeIfChanged(
        "follow_up_tasks",
        envelope.draft_tasks,
        "follow_up_task_draft",
      );
    }

    if (envelope.safety_flags.length > 0) {
      await writeIfChanged(
        "safety_flags",
        envelope.safety_flags,
        "compliance_guardrail",
      );
    }

    if (envelope.caregiver_notification) {
      await writeIfChanged(
        "family_brief",
        envelope.caregiver_notification,
        "family_summary",
      );
    }
  }

  /**
   * Pause-time entry point. Runs ONCE when the user clicks Pause/End.
   *
   * Steps:
   *   1. Reads the full ordered transcript for `round_index` (or every
   *      completed turn when round_index is null) from VisitState.
   *   2. Calls the `transcript_noise_filter` agent with the whole
   *      transcript. Falls back to a permissive no-op (every turn `clean`)
   *      on validation failure so the recap path never breaks.
   *   3. Applies the result via `applyNoiseFilter` — strips contributions
   *      of every `noise_high_conf` turn from VisitState, persists
   *      `noise_tags`.
   *   4. Persists the cleaned VisitState. The recap / final summary that
   *      runs next reads from this cleaned state.
   *
   * Idempotent: re-running on the same transcript replaces noise_tags and
   * removes any newly-quarantined contributions; previously-stripped data
   * does not return.
   */
  async runPauseNoiseFilter(args: {
    visit_id: string;
    round_index?: number | null;
  }): Promise<{
    applied: boolean;
    noise_tags: NoiseTagsRecord | null;
    quarantined_turn_ids: string[];
  }> {
    const visit = await this.opts.visitStateGet(args.visit_id);
    const round =
      args.round_index != null
        ? visit.rounds.find((r) => r.index === args.round_index) ?? null
        : null;
    const allTurnIds =
      round != null
        ? new Set(round.turn_item_ids)
        : null;
    const turns = visit.turns
      .filter((t) => t.status === "completed" && (t.transcript ?? "").length > 0)
      .filter((t) => (allTurnIds ? allTurnIds.has(t.item_id) : true))
      .map((t) => ({
        item_id: t.item_id,
        transcript: t.transcript ?? "",
      }));

    if (turns.length === 0) {
      return { applied: false, noise_tags: null, quarantined_turn_ids: [] };
    }

    const event = {
      event_kind: "pause_noise_filter",
      visit_id: args.visit_id,
      round_index: args.round_index ?? null,
      full_transcript: turns,
    };

    const { parsed } = await this.runRole<NoiseFilterOutput>(
      "transcript_noise_filter",
      args.visit_id,
      event,
      visit,
      [],
      null,
    );

    // Default-clean fallback when the filter fails or returns nothing —
    // guarantees the recap path is not blocked by a parse error.
    const filter: NoiseFilterOutput =
      parsed && Array.isArray(parsed.turn_tags) && parsed.turn_tags.length > 0
        ? parsed
        : {
            turn_tags: turns.map((t) => ({
              turn_id: t.item_id,
              tag: "clean" as const,
              category: "clean" as const,
              confidence: "low" as const,
              reason: "filter unavailable; defaulted to clean",
              phonetic_neighbor: null,
            })),
            summary: {
              total_turns: turns.length,
              clean: turns.length,
              partial: 0,
              duplicate: 0,
              noise_low_conf: 0,
              noise_high_conf: 0,
            },
          };

    const after = applyNoiseFilter(visit, filter, {
      round_index: args.round_index ?? null,
    });
    await this.opts.visitStateSet(args.visit_id, after);

    const quarantined = filter.turn_tags
      .filter((t) => t.tag === "noise_high_conf")
      .map((t) => t.turn_id);

    this.opts.eventBus?.emit({
      type: "blackboard_updated",
      visitId: args.visit_id,
      key: "noise_tags",
      writtenBy: "transcript_noise_filter",
      version: Date.now(),
    });

    return {
      applied: true,
      noise_tags: after.noise_tags,
      quarantined_turn_ids: quarantined,
    };
  }

  async summarise(job: Extract<CodexJob, { kind: "stage_summary" | "final_summary" }>): Promise<void> {
    const visit = await this.opts.visitStateGet(job.visit_id);
    await this.withParentTask(
      {
        kind: job.kind === "final_summary" ? "final_summary" : "stage_summary",
        visitId: job.visit_id,
        role: "final_visit_summary",
        label: job.kind,
        description: `${job.kind} for visit ${job.visit_id}`,
        createdBy: "system",
        workload: job.kind === "final_summary" ? "final_summary" : "stage_summary",
      },
      () =>
        this.runRole(
          "final_visit_summary",
          job.visit_id,
          {
            event_kind: job.kind,
            visit_id: job.visit_id,
          },
          visit,
          [],
        ),
    );
  }

  /**
   * Run one role; parse + validate; one repair pass on schema failure; record.
   *
   * `recall` is the per-turn RecallResult from MemoryRecallService.prefetch
   * (built once in analyzeTurn and reused by every role on the same turn).
   * Its `append` block becomes extra_instructions, which CodexAgentTeam.run
   * concatenates onto the registry-loaded role prompt. CLARIOSE_V01 §4 + §6.
   */
  private async runRole<T>(
    role: CodexAgentRole,
    visit_id: string,
    event: unknown,
    visit_state_snapshot: VisitState,
    memory_context: unknown[],
    recall: RecallResult | null = null,
  ): Promise<{ run: AgentRunRecorded; parsed: T | null }> {
    return this.withChildTask(role, visit_id, () =>
      this.runRoleInner<T>(role, visit_id, event, visit_state_snapshot, memory_context, recall),
    );
  }

  private async runRoleInner<T>(
    role: CodexAgentRole,
    visit_id: string,
    event: unknown,
    visit_state_snapshot: VisitState,
    memory_context: unknown[],
    recall: RecallResult | null = null,
  ): Promise<{ run: AgentRunRecorded; parsed: T | null }> {
    const schema = RoleOutputSchemas[role];
    const jsonSchema = zodToJsonSchema(schema);

    // CLARIOSE_V01 §3 Layer 1 — drain this role's mailbox under file lock.
    // Includes any task_assignment / permission_response / recall_response
    // messages siblings sent us since our last run. Read happens BEFORE the
    // codex call so we don't miss messages that race the run.
    const inboxRaw = this.opts.mailbox
      ? await this.opts.mailbox
          .drainUnread(visit_id, role)
          .catch(() => [])
      : [];
    const inbox = inboxRaw.map((m) => ({
      from: m.from,
      payloadKind: m.structured?.type ?? "free_text",
      payload: m.structured ?? m.text,
    }));

    // CLARIOSE_V01 §3 cross-cutting — read the blackboard subset this role
    // declared interest in. The subscription registry is the authoritative
    // source of "which keys does R care about"; we mirror it here so the
    // role only sees keys relevant to its job (token thrift + isolation).
    const subscribedKeys = this.subscribedKeysFor(role);
    const blackboard = this.opts.blackboard && subscribedKeys.length > 0
      ? await this.opts.blackboard
          .readMany(visit_id, subscribedKeys)
          .catch(() => ({} as Record<string, unknown>))
      : {};

    // CLARIOSE_V01 §6 — build the per-turn user message via the dynamic
    // template assembler. Memory recall flows in two complementary places:
    //   • recall.append → extra_instructions → appended to the role's
    //     registry prompt (system-prompt side, stable across roles)
    //   • the assembled userMessage → sent as the codex turn input,
    //     with structured visit_context / recent_transcript / inbox /
    //     blackboard / event / expected_output_schema_name blocks.
    const assembled = assembleCodexPrompt({
      role,
      rolePrompt: "", // ignored on this side; the registry prompt is composed
                     // inside CodexAgentTeam.run. We keep the assembler API
                     // self-contained but only use its userMessage here.
      expectedOutputSchemaName: role,
      visitState: visit_state_snapshot,
      event,
      recall:
        recall ?? {
          append: null,
          files: [],
          bytesInjected: 0,
          manifestSize: 0,
          selectedCount: 0,
          latencyMs: 0,
          skipped: "empty" as const,
        },
      inbox,
      blackboard,
    });

    // CLARIOSE_V01 §8 — emit lifecycle events for SSE fanout (Week 4 frontend
    // End&review subscribes to agent_run_completed for final_visit_summary).
    const startedRunId = `${role}_${Date.now()}`;
    this.opts.eventBus?.emit({
      type: "agent_run_started",
      visitId: visit_id,
      role,
      runId: startedRunId,
    });

    // Per-role workspace memory injection (Qzone-style isolation).
    // Each role has its own MEMORY.md under
    // <CARENOTE_TEAMS_ROOT>/<role>/memory/MEMORY.md. We append it to the
    // turn-level recall block so the role sees both shared turn recall
    // AND its private cross-visit notes. Empty memory → no-op.
    let extraInstructions = recall?.append ?? null;
    if (this.opts.roleWorkspace) {
      const roleMem = await this.opts.roleWorkspace
        .loadMemoryForPrompt(role)
        .catch(() => null);
      if (roleMem) {
        extraInstructions = extraInstructions
          ? `${extraInstructions}\n\n${roleMem}`
          : roleMem;
      }
    }

    const out = await this.opts.team.run(role, {
      team_id: this.opts.team.teamId,
      visit_id,
      role,
      prompt_version: "1.0.0",
      schema_version: "1.0.0",
      event,
      visit_state_snapshot,
      memory_context,
      instructions: "", // injected by team.run from registry
      extra_instructions: extraInstructions,
      pre_built_user_message: assembled.userMessage,
      expected_output_schema_name: role,
      expected_output_schema: jsonSchema,
    });

    const result = await this.validateAndMaybeRepair<T>(role, out);

    const status: "valid" | "repaired" | "failed" =
      result.parsed === null
        ? "failed"
        : (result.run.validation_status === "repaired" ? "repaired" : "valid");
    this.opts.eventBus?.emit({
      type: "agent_run_completed",
      visitId: visit_id,
      role,
      runId: startedRunId,
      status,
    });

    return result;
  }

  private async validateAndMaybeRepair<T>(
    role: CodexAgentRole,
    out: CodexAgentRunOutput,
  ): Promise<{ run: AgentRunRecorded; parsed: T | null }> {
    const previewOf = (s: string): string =>
      s.length > 400 ? s.slice(0, 400) + `…[+${s.length - 400} chars]` : s;

    // Runtime-level failure → never call validator; report cleanly.
    if (out.validation_status === "failed" && !out.raw_text) {
      const run: AgentRunRecorded = {
        ...out,
        schema_name: role,
        raw_output_preview: previewOf(out.raw_text),
      };
      if (this.opts.recordAgentRun) await this.opts.recordAgentRun(run);
      return { run, parsed: null };
    }

    const parsed1 = parseCodexJson(out.raw_text);
    if (parsed1.ok) {
      const v = validateRoleOutput<T>(role, parsed1.value);
      if (v.ok) {
        const run: AgentRunRecorded = {
          ...out,
          validation_status: "valid",
          parsed_json: v.value,
          schema_name: role,
          raw_output_preview: previewOf(out.raw_text),
        };
        if (this.opts.recordAgentRun) await this.opts.recordAgentRun(run);
        return { run, parsed: v.value };
      }
      // Fallthrough — try repair.
      const repaired = await this.opts.team.run(role, {
        team_id: this.opts.team.teamId,
        visit_id: out.visit_id,
        role,
        prompt_version: "1.0.0",
        schema_version: "1.0.0",
        event: {
          event_kind: "json_repair",
          previous_raw: out.raw_text,
          errors: v.errors,
          target_schema_name: role,
        },
        visit_state_snapshot: {} as never,
        memory_context: [],
        instructions: "",
        expected_output_schema_name: role,
        expected_output_schema: zodToJsonSchema(RoleOutputSchemas[role]),
      });
      const parsed2 = parseCodexJson(repaired.raw_text);
      if (parsed2.ok) {
        const v2 = validateRoleOutput<T>(role, parsed2.value);
        if (v2.ok) {
          const run: AgentRunRecorded = {
            ...repaired,
            validation_status: "repaired",
            parsed_json: v2.value,
            repair_attempted: true,
            schema_name: role,
            raw_output_preview: previewOf(repaired.raw_text),
          };
          if (this.opts.recordAgentRun) await this.opts.recordAgentRun(run);
          return { run, parsed: v2.value };
        }
        const run: AgentRunRecorded = {
          ...repaired,
          validation_status: "invalid",
          validation_errors: v2.errors,
          repair_attempted: true,
          schema_name: role,
          raw_output_preview: previewOf(repaired.raw_text),
        };
        if (this.opts.recordAgentRun) await this.opts.recordAgentRun(run);
        return { run, parsed: null };
      }
      const run: AgentRunRecorded = {
        ...repaired,
        validation_status: "failed",
        errors: [...(repaired.errors ?? []), parsed2.error],
        repair_attempted: true,
        schema_name: role,
        raw_output_preview: previewOf(repaired.raw_text),
      };
      if (this.opts.recordAgentRun) await this.opts.recordAgentRun(run);
      return { run, parsed: null };
    }
    // First-pass parse failure — surface explicit reason.
    const run: AgentRunRecorded = {
      ...out,
      validation_status: "failed",
      errors: [...(out.errors ?? []), parsed1.error],
      schema_name: role,
      raw_output_preview: previewOf(out.raw_text),
    };
    if (this.opts.recordAgentRun) await this.opts.recordAgentRun(run);
    return { run, parsed: null };
  }

  // ─── Layer-1 helpers ──────────────────────────────────────────────────

  /**
   * Wraps a top-level run (analyze_turn / on_demand_role / stage_summary /
   * final_summary) in a parent RuntimeTask + AgentContext + TeammateContext.
   * Children created inside `fn` (via `withChildTask`) inherit the parent
   * via `agentCtx.current()`. Errors mark the parent failed; on success it's
   * marked complete with the resolved value attached.
   */
  private async withParentTask<T>(
    args: {
      kind: RuntimeTask["kind"];
      visitId: string;
      role?: CodexAgentRole;
      label: string;
      description: string;
      createdBy: string;
      workload: WorkloadKind;
    },
    fn: () => Promise<T>,
  ): Promise<T> {
    const tasks = this.opts.tasks;
    const agentCtx = this.opts.agentCtx;
    const teammateCtx = this.opts.teammateCtx;
    if (!tasks || !agentCtx || !teammateCtx) {
      // ALS plumbing not wired (test harness, CLI). Fall through silently.
      return fn();
    }
    const task = tasks.register({
      kind: args.kind,
      visitId: args.visitId,
      role: args.role,
      workload: args.workload,
      label: args.label,
      description: args.description,
      createdBy: args.createdBy,
    });
    const ctx: AgentContext = {
      agentType: "main",
      agentRunId: task.id,
      taskId: task.id,
      visitId: args.visitId,
      role: args.role,
      label: args.label,
    };
    try {
      const result = await agentCtx.run(ctx, () =>
        teammateCtx.run(
          {
            taskId: task.id,
            abortController: task.abortController,
            turnIndex: 0,
            hopCount: 0,
          },
          () => fn(),
        ),
      );
      tasks.complete(task.id, { kind: "parent_complete" });
      return result;
    } catch (err) {
      tasks.fail(task.id, (err as Error).message ?? String(err));
      throw err;
    }
  }

  /**
   * Wraps a single role-run in a child RuntimeTask under whatever parent is
   * currently bound in AgentContext. The child gets its own per-turn
   * abortController (so a runaway role can be killed without taking out the
   * whole turn). On success the task is marked complete with the validated
   * output preview; on throw it's marked failed.
   */
  private async withChildTask<T>(
    role: CodexAgentRole,
    visit_id: string,
    fn: () => Promise<T>,
  ): Promise<T> {
    const tasks = this.opts.tasks;
    const agentCtx = this.opts.agentCtx;
    const teammateCtx = this.opts.teammateCtx;
    if (!tasks || !agentCtx || !teammateCtx) {
      return fn();
    }
    const parent = agentCtx.current();
    const task = tasks.register({
      kind: "role_run",
      visitId: visit_id,
      role,
      workload: parent?.role ? "turn" : (this.opts.workloadCtx?.current() ?? "turn"),
      label: role,
      description: `codex ${role}`,
      createdBy: parent?.role ?? parent?.label ?? "system",
      parentTaskId: parent?.taskId,
    });
    const childCtx: AgentContext = {
      agentType: parent ? "subagent" : "main",
      agentRunId: task.id,
      taskId: task.id,
      parentTaskId: parent?.taskId,
      visitId: visit_id,
      ownerUserId: parent?.ownerUserId,
      role,
      label: role,
      traceId: parent?.traceId,
    };
    try {
      const out = await agentCtx.run(childCtx, () =>
        teammateCtx.run(
          {
            taskId: task.id,
            abortController: task.abortController,
            turnIndex: 0,
            hopCount: 0,
          },
          () => fn(),
        ),
      );
      // Surface a small slice of the output on the task for UI inspection.
      let summary: Record<string, unknown> | undefined;
      if (out && typeof out === "object" && "run" in (out as object)) {
        const run = (out as unknown as { run: AgentRunRecorded }).run;
        summary = {
          validation_status: run.validation_status,
          run_id: run.run_id,
        };
      }
      tasks.complete(task.id, summary);
      return out;
    } catch (err) {
      tasks.fail(task.id, (err as Error).message ?? String(err));
      throw err;
    }
  }
}

function jobToWorkload(job: CodexJob): WorkloadKind {
  switch (job.kind) {
    case "analyze_turn":
      return "turn";
    case "stage_summary":
      return "stage_summary";
    case "final_summary":
      return "final_summary";
    case "single_role":
      return "on_demand";
  }
}

// ---------------------------------------------------------------------------
// Envelope builder
// ---------------------------------------------------------------------------

type Pass1 = {
  transcript_quality: TranscriptQualityOutput | null;
  speaker_role: SpeakerRoleOutput | null;
  medical_instruction_extractor: MedicalInstructionExtractorOutput | null;
  safety_clarification: SafetyClarificationOutput | null;
};
type Pass2 = {
  medication_reminder_draft: MedicationReminderDraftOutput | null;
  follow_up_task_draft: FollowUpTaskDraftOutput | null;
  family_summary: FamilySummaryOutput | null;
  memory_update: MemoryUpdateOutput | null;
};

function buildEnvelope(
  visit_id: string,
  turn_id: string,
  passes: { pass1: Pass1; pass2: Pass2 },
): TurnEnvelope {
  const facts =
    passes.pass1.medical_instruction_extractor?.facts.map(
      (f: MedicalInstructionExtractorOutput["facts"][number], i: number) => ({
        ...f,
        fact_id: `f-${turn_id}-${i + 1}`,
        created_by_agent: "medical_instruction_extractor" as const,
        created_at: new Date().toISOString(),
      }),
    ) ?? [];

  const draft_reminders =
    passes.pass2.medication_reminder_draft?.draft_reminders.map(
      (
        r: MedicationReminderDraftOutput["draft_reminders"][number],
        i: number,
      ) => ({
        ...r,
        task_id: `t-${turn_id}-mr${i + 1}`,
        created_at: new Date().toISOString(),
        requires_user_confirmation: true as const,
        confirmation_status: "pending" as const,
      }),
    ) ?? [];

  const draft_tasks_med =
    passes.pass2.medication_reminder_draft?.confirmation_tasks.map(
      (
        t: MedicationReminderDraftOutput["confirmation_tasks"][number],
        i: number,
      ) => ({
        ...t,
        task_id: `t-${turn_id}-cq${i + 1}`,
        created_at: new Date().toISOString(),
        requires_user_confirmation: true as const,
        confirmation_status: "pending" as const,
        source_fact_ids: t.source_fact_ids ?? [],
      }),
    ) ?? [];

  const draft_tasks_fu =
    passes.pass2.follow_up_task_draft?.draft_tasks.map(
      (t: FollowUpTaskDraftOutput["draft_tasks"][number], i: number) => ({
        ...t,
        task_id: `t-${turn_id}-fu${i + 1}`,
        created_at: new Date().toISOString(),
        requires_user_confirmation: true as const,
        confirmation_status: "pending" as const,
        source_fact_ids: [] as string[],
      }),
    ) ?? [];

  const clarifying_questions =
    passes.pass1.safety_clarification?.clarifying_questions.map(
      (q: SafetyClarificationOutput["clarifying_questions"][number], i: number) => ({
        ...q,
        question_id: `q-${turn_id}-${i + 1}`,
      }),
    ) ?? [];

  const memory_candidates =
    passes.pass2.memory_update?.memory_candidates.map(
      (m: MemoryUpdateOutput["memory_candidates"][number], i: number) => ({
        ...m,
        memory_candidate_id: `mc-${turn_id}-${i + 1}`,
        requires_user_confirmation: true as const,
        confirmation_status: "pending" as const,
      }),
    ) ?? [];

  const safety_flags =
    passes.pass1.safety_clarification?.safety_flags.map(
      (s: SafetyClarificationOutput["safety_flags"][number], i: number) => ({
        ...s,
        flag_id: `sf-${turn_id}-${i + 1}`,
        source_turn_ids: s.source_turn_ids?.length ? s.source_turn_ids : [turn_id],
      }),
    ) ?? [];

  const family_summary_delta =
    passes.pass2.family_summary?.family_summary
      ? {
          turn_id,
          text: passes.pass2.family_summary.family_summary,
          source_turn_ids:
            passes.pass2.family_summary.source_turn_ids?.length
              ? passes.pass2.family_summary.source_turn_ids
              : [turn_id],
        }
      : undefined;

  const tv = passes.pass1.transcript_quality;
  const transcript_verification = tv
    ? {
        verification_id: `tv-${turn_id}`,
        turn_id,
        quality: tv.quality,
        safe_to_extract: tv.safe_to_extract ?? true,
        ambiguities: (tv.ambiguities ?? []).map((a, i) => ({
          ...a,
          ambiguity_id: `tv-${turn_id}-${i + 1}`,
          source_turn_ids: a.source_turn_ids?.length ? a.source_turn_ids : [turn_id],
          created_at: new Date().toISOString(),
        })),
        source_turn_ids: tv.source_turn_ids?.length ? tv.source_turn_ids : [turn_id],
        created_at: new Date().toISOString(),
      }
    : undefined;

  const cnRaw = passes.pass2.family_summary?.caregiver_notification;
  const caregiver_notification = cnRaw
    ? {
        notification_id: `cn-${turn_id}`,
        turn_id,
        title: cnRaw.title,
        message: cnRaw.message,
        needs_confirmation: cnRaw.needs_confirmation ?? [],
        next_actions: cnRaw.next_actions ?? [],
        requires_user_confirmation: true as const,
        confirmation_status: "pending" as const,
        source_turn_ids: cnRaw.source_turn_ids?.length ? cnRaw.source_turn_ids : [turn_id],
        created_at: new Date().toISOString(),
      }
    : undefined;

  return {
    visit_id,
    turn_id,
    facts: facts as unknown as TurnEnvelope["facts"],
    draft_reminders: draft_reminders as unknown as TurnEnvelope["draft_reminders"],
    draft_tasks: [...draft_tasks_med, ...draft_tasks_fu] as unknown as TurnEnvelope["draft_tasks"],
    clarifying_questions: clarifying_questions as unknown as TurnEnvelope["clarifying_questions"],
    family_summary_delta,
    memory_candidates: memory_candidates as unknown as TurnEnvelope["memory_candidates"],
    safety_flags: safety_flags as unknown as TurnEnvelope["safety_flags"],
    transcript_verification: transcript_verification as TurnEnvelope["transcript_verification"],
    caregiver_notification: caregiver_notification as TurnEnvelope["caregiver_notification"],
  };
}
