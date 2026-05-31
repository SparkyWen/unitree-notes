// CareNoteService — singleton wrapper around the M5/M6 harness graph.
//
// Owns:
//   • the assembled harness (queue, manager, bus, assembler, stores);
//   • per-visit metadata that doesn't live inside VisitState
//     (consent, raw_audio_saved, user_id, status);
//   • all mutating operations the controllers expose.
//
// The harness is lazy-initialized on first use so the Nest app can boot
// without the codex-cli being authenticated (e.g., during `nest start
// --watch` on a developer laptop).

import { randomUUID } from "node:crypto";
import {
  Injectable,
  Logger,
  NotFoundException,
  BadRequestException,
  ServiceUnavailableException,
  ForbiddenException,
  ConflictException,
  OnModuleDestroy,
} from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { Prisma, SessionStatus } from "@prisma/client";

import { assembleHarness, type CareNoteHarness } from "./codexHarnessApi";
import {
  buildRealtimeSessionConfig,
  type RealtimeLanguage,
} from "../realtime/realtimeConfig";
import { REALTIME_SESSION_PROMPT } from "../prompts/realtimeSessionPrompt";
import { TRANSCRIPTION_PROMPT } from "../prompts/transcriptionPrompt";
import type {
  RealtimeIngestEvent,
  DoctorVisitTranscriptTurnCompleted,
} from "../realtime/realtimeEventTypes";
import { applyRealtimeEventToVisitState } from "../realtime/applyRealtimeEvent";
import {
  VisitStateSchema,
  type VisitState,
  type ConfirmationStatusSchema,
} from "../medical/medicalSchemas";
import { dedupVisitState } from "../medical/medicalReducers";
import type { z } from "zod";
import {
  redactPhi,
  isPhiDebugEnabled,
  assertPhiDebugWarningPrinted,
} from "./redactPhi";
import { CarenoteEventBus } from "../swarm/eventBus";
import { PrismaService } from "../../../common/prisma/prisma.service";
import { MemoryRecallService } from "../recall/memoryRecall";
import { MailboxService } from "../swarm/mailboxService";
import { BlackboardService } from "../swarm/blackboard";
import { SubscriptionRegistry } from "../swarm/subscriptionRegistry";
import { TasksService } from "../runtime/tasks/tasks.service";
import {
  AgentContextService,
  TeammateContextService,
  WorkloadContextService,
} from "../runtime/als";
import { RoleWorkspaceService } from "../runtime/roleWorkspace.service";
import { VisitFolderService } from "./visitFolder.service";
import {
  TranslateTtsService,
  type AskDoctorResult,
} from "./translateTts.service";

export type CareNoteVisitMeta = {
  visit_id: string;
  user_id: string;
  patient_id: string | null;
  language: RealtimeLanguage;
  output_language: RealtimeLanguage;
  consent_recorded: true;
  raw_audio_saved: boolean;
  status: "active" | "ended" | "deleted";
  created_at: string;
  ended_at?: string | null;
};

export type RealtimeSessionResult = {
  visit_id: string;
  client_secret: string;
  expires_at: number;
  model: "gpt-realtime-1.5";
  config: ReturnType<typeof buildRealtimeSessionConfig>;
};

export type ConfirmedTask = {
  task_id: string;
  task_type: string;
  title: string;
  description: string;
  due_at?: string | null;
  source_fact_ids: string[];
  source_turn_ids: string[];
  confirmation_status: "confirmed";
  confirmed_at: string;
};

export type ConfirmedMemory = {
  memory_id: string;
  source_candidate_id: string;
  user_id: string;
  memory_type: string;
  content: string;
  source_turn_ids: string[];
  confirmed_at: string;
};

type ConfStatus = z.infer<typeof ConfirmationStatusSchema>;

@Injectable()
export class CareNoteService implements OnModuleDestroy {
  private readonly logger = new Logger("CareNote");
  private harnessPromise: Promise<CareNoteHarness> | null = null;
  private harness: CareNoteHarness | null = null;
  private readonly visits = new Map<string, CareNoteVisitMeta>();
  private readonly confirmedTasks = new Map<string, Map<string, ConfirmedTask>>();
  private readonly confirmedMemories = new Map<string, ConfirmedMemory[]>();

  constructor(
    private readonly cfg: ConfigService,
    private readonly eventBus: CarenoteEventBus,
    private readonly prisma: PrismaService,
    private readonly tasks?: TasksService,
    private readonly agentCtx?: AgentContextService,
    private readonly teammateCtx?: TeammateContextService,
    private readonly workloadCtx?: WorkloadContextService,
    private readonly recall?: MemoryRecallService,
    private readonly mailbox?: MailboxService,
    private readonly blackboard?: BlackboardService,
    private readonly subscriptions?: SubscriptionRegistry,
    private readonly roleWorkspace?: RoleWorkspaceService,
    private readonly folder?: VisitFolderService,
    private readonly translateTts?: TranslateTtsService,
  ) {
    assertPhiDebugWarningPrinted(this.logger);
  }

  // ---------------------------------------------------------------------------
  // CLARIOSE_V01 §7 — Visit DB persistence + ownership
  // ---------------------------------------------------------------------------

  /**
   * Verify the visit exists and is owned by the given user. Throws 404 if
   * the visit does not exist OR the caller does not own it (don't leak
   * existence). All write/read endpoints call this before doing anything.
   */
  async ensureOwner(visit_id: string, user_id: string): Promise<void> {
    const row = await this.prisma.consultSession.findUnique({
      where: { id: visit_id },
      select: { ownerUserId: true },
    });
    if (!row || row.ownerUserId !== user_id) {
      throw new NotFoundException(`visit ${visit_id} not found`);
    }
  }

  /**
   * Hydrate the in-memory visit meta + VisitState from DB if missing. Called
   * by every read/write path so a PM2 reload or fresh process boot can serve
   * a visit created in a previous run.
   */
  private async hydrateVisit(visit_id: string): Promise<CareNoteVisitMeta> {
    const cached = this.visits.get(visit_id);
    if (cached) return cached;

    const row = await this.prisma.consultSession.findUnique({
      where: { id: visit_id },
    });
    if (!row) throw new NotFoundException(`visit ${visit_id} not found`);

    const language = (row.language as RealtimeLanguage) ?? "en";
    const stateBlob = (row.visitState ?? {}) as Record<string, unknown>;
    // CLARIOSE_V02: output_language was added later, so legacy blobs may
    // not have it. Fall back to the spoken language so existing visits
    // keep behaving as before.
    const output_language =
      (typeof stateBlob.output_language === "string"
        ? (stateBlob.output_language as RealtimeLanguage)
        : null) ?? language;
    const meta: CareNoteVisitMeta = {
      visit_id: row.id,
      user_id: row.ownerUserId,
      patient_id: row.patientId,
      language,
      output_language,
      consent_recorded: true,
      raw_audio_saved: row.rawAudioSaved,
      status:
        row.status === "ENDED" ? "ended" :
        row.status === "ARCHIVED" ? "deleted" : "active",
      created_at: row.startedAt.toISOString(),
      ended_at: row.endedAt?.toISOString() ?? null,
    };
    this.visits.set(visit_id, meta);

    // Rehydrate VisitState into the harness's in-memory store. If the JSON
    // blob is empty (visit predates the persistence change) start fresh.
    const harness = await this.getHarness();
    if (stateBlob && stateBlob.visit_id) {
      const parsed = VisitStateSchema.safeParse(stateBlob);
      if (parsed.success) {
        // CLARIOSE_V02: backfill round 0 + output_language for legacy blobs.
        const data = parsed.data;
        const patched = {
          ...data,
          output_language: data.output_language ?? output_language,
          rounds:
            data.rounds && data.rounds.length > 0
              ? data.rounds
              : [
                  {
                    index: 0,
                    started_at: meta.created_at,
                    ended_at: null,
                    turn_item_ids: data.turns.map((t) => t.item_id),
                    recap_headline: null,
                    recap_generated_at: null,
                  },
                ],
          current_round_index: data.current_round_index ?? 0,
          ask_doctor_logs: data.ask_doctor_logs ?? [],
        };
        // Heal blobs that predate the dedup-on-reduce fix: visits persisted
        // before the multi-pass commit-partial flow learned to dedup carry
        // up to 4× copies of the same fact / question / flag.
        await harness.visits.set(visit_id, dedupVisitState(patched));
      } else {
        this.logger.warn(
          `visitState rehydrate parse-failed for ${visit_id}; starting fresh: ${parsed.error.message}`,
        );
        harness.visits.ensure(visit_id, language, output_language);
      }
    } else {
      harness.visits.ensure(visit_id, language, output_language);
    }
    if (!this.confirmedTasks.has(visit_id))
      this.confirmedTasks.set(visit_id, new Map());
    if (!this.confirmedMemories.has(visit_id))
      this.confirmedMemories.set(visit_id, []);
    return meta;
  }

  /**
   * Persist the current VisitState to ConsultSession.visitState. Called
   * after every ingestRealtimeEvent so the latest transcript / agent
   * outputs survive process restart. Fire-and-forget: an error here logs
   * but does not break the request.
   */
  private async persistVisitState(visit_id: string): Promise<void> {
    try {
      const harness = await this.getHarness();
      const state = await harness.visits.get(visit_id);
      await this.prisma.consultSession.update({
        where: { id: visit_id },
        data: {
          visitState: state as unknown as object,
          utteranceCount: state.turns.length,
        },
      });
    } catch (err) {
      // Loud — silent persist failures are why we couldn't tell why
      // visitState stayed `{}` while utteranceCount kept incrementing.
      this.logger.error(
        `persistVisitState ${visit_id} failed: ${(err as Error).message}`,
        (err as Error).stack,
      );
    }
  }

  /** List all carenote visits owned by the given user (newest first). */
  async listVisitsForUser(user_id: string) {
    const rows = await this.prisma.consultSession.findMany({
      where: { ownerUserId: user_id },
      orderBy: { startedAt: "desc" },
      take: 50,
      select: {
        id: true,
        startedAt: true,
        endedAt: true,
        durationSec: true,
        utteranceCount: true,
        status: true,
        language: true,
        summaryMd: true,
      },
    });
    return rows.map((r) => ({
      visit_id: r.id,
      started_at: r.startedAt.toISOString(),
      ended_at: r.endedAt?.toISOString() ?? null,
      duration_sec: r.durationSec,
      turn_count: r.utteranceCount,
      status: r.status,
      language: r.language,
      summary_md: r.summaryMd,
    }));
  }

  async onModuleDestroy(): Promise<void> {
    if (this.harness) {
      await this.harness.queue.stop();
    }
  }

  // ---------------------------------------------------------------------------
  // Harness lifecycle
  // ---------------------------------------------------------------------------

  /** Lazy-load the harness. Tests can override by calling setHarnessForTest. */
  async getHarness(): Promise<CareNoteHarness> {
    if (this.harness) return this.harness;
    if (!this.harnessPromise) {
      this.logger.log("Bootstrapping CareNote codex harness…");
      this.harnessPromise = assembleHarness({
        // CLARIOSE_V01 §4: hand the recall service + owner lookup to the
        // run-manager so each turn can prefetch memory once and inject the
        // result into all 11 roles' prompts.
        recall: this.recall,
        visitOwnerLookup: async (visit_id: string) => {
          try {
            const meta = await this.hydrateVisit(visit_id).catch(() => null);
            return meta?.user_id ?? null;
          } catch {
            return null;
          }
        },
        // CLARIOSE_V01 §3 — 4-layer comm services pumped into the manager so
        // runRole can drain mailbox + slice blackboard, and so the
        // SubscriptionRegistry can fire on-demand single_role jobs in
        // response to bus events.
        mailbox: this.mailbox,
        blackboard: this.blackboard,
        subscriptions: this.subscriptions,
        // CLARIOSE_V01 §8 — bus for agent_run_* SSE emits (frontend End&review).
        eventBus: this.eventBus,
        // Layer-1 (CCLearn note 4): every codex run is wrapped in a
        // RuntimeTask + AsyncLocalStorage backpack so downstream layers can
        // attribute via `agentCtx.current()` instead of plumbed arguments.
        tasks: this.tasks,
        agentCtx: this.agentCtx,
        teammateCtx: this.teammateCtx,
        workloadCtx: this.workloadCtx,
        roleWorkspace: this.roleWorkspace,
        onRunRecorded: async (rec) => {
          // Mirror each codex run into the DB so the team-activity panel
          // can show it. The in-memory list inside the harness gets reset
          // on process restart and is not query-friendly; the DB row is.
          const startedAt = new Date(rec.started_at);
          const endedAt = rec.completed_at ? new Date(rec.completed_at) : null;
          const status =
            rec.validation_status === "failed"
              ? "FAILED"
              : "COMPLETED";
          const rawPreview =
            rec.raw_output_preview ??
            (typeof rec.raw_text === "string"
              ? rec.raw_text.slice(0, 4000)
              : null);
          await this.prisma.carenoteAgentRun
            .create({
              data: {
                visitId: rec.visit_id,
                role: rec.role,
                kind: "turn",
                status,
                rawOutput: rawPreview,
                parsedJson:
                  rec.parsed_json == null
                    ? Prisma.JsonNull
                    : (rec.parsed_json as Prisma.InputJsonValue),
                validationStatus: rec.validation_status,
                errorMessage: rec.errors?.[0] ?? null,
                threadId: rec.thread_id,
                latencyMs:
                  endedAt && startedAt
                    ? endedAt.getTime() - startedAt.getTime()
                    : null,
                startedAt,
                endedAt,
              },
            })
            .catch((err) =>
              this.logger.warn(
                `carenoteAgentRun mirror failed: ${(err as Error).message}`,
              ),
            );
        },
      }).then((h) => {
        this.harness = h;
        this.logger.log(
          `Harness ready (runtime=${h.bootstrap.runtime.runtime.name}, recall=${this.recall ? "on" : "off"})`,
        );
        return h;
      });
    }
    return this.harnessPromise;
  }

  /** Test-only injector. */
  setHarnessForTest(h: CareNoteHarness): void {
    this.harness = h;
    this.harnessPromise = Promise.resolve(h);
  }

  // ---------------------------------------------------------------------------
  // Visit lifecycle
  // ---------------------------------------------------------------------------

  /**
   * CLARIOSE_V01: create a visit owned by the JWT-authenticated user. The
   * visit_id is the cuid Prisma assigns to the ConsultSession row, so URL
   * /carenote/visit/<cuid> maps 1:1 to the DB row.
   *
   * Auto-creates a Patient row if the User doesn't have one yet (mirrors the
   * pattern in sessions.service.ts:11-18).
   */
  async createVisit(input: {
    ownerUserId: string;
    language?: RealtimeLanguage;
    output_language?: RealtimeLanguage;
    consent_recorded: boolean;
    raw_audio_saved?: boolean;
  }): Promise<{ visit_id: string; status: "active" }> {
    if (input.consent_recorded !== true) {
      throw new BadRequestException(
        "consent_recorded must be true to create a visit",
      );
    }
    const language: RealtimeLanguage = input.language ?? "en";
    const output_language: RealtimeLanguage =
      input.output_language ?? language;

    // Ensure the user has a Patient row.
    let patient = await this.prisma.patient.findUnique({
      where: { userId: input.ownerUserId },
    });
    if (!patient) {
      const user = await this.prisma.user.findUnique({
        where: { id: input.ownerUserId },
      });
      if (!user) throw new NotFoundException("user not found");
      patient = await this.prisma.patient.create({
        data: {
          userId: input.ownerUserId,
          fullName: user.displayName || user.email,
        },
      });
    }

    // Persist the visit. visit_id comes from the cuid that Prisma generates.
    const session = await this.prisma.consultSession.create({
      data: {
        ownerUserId: input.ownerUserId,
        patientId: patient.id,
        language,
        consentRecorded: true,
        rawAudioSaved: input.raw_audio_saved === true,
        status: "ACTIVE",
        // visitState seeded as empty {}; first ingestRealtimeEvent populates it.
      },
    });
    const visit_id = session.id;

    const meta: CareNoteVisitMeta = {
      visit_id,
      user_id: input.ownerUserId,
      patient_id: patient.id,
      language,
      output_language,
      consent_recorded: true,
      raw_audio_saved: session.rawAudioSaved,
      status: "active",
      created_at: session.startedAt.toISOString(),
      ended_at: null,
    };
    this.visits.set(visit_id, meta);

    const harness = await this.getHarness();
    harness.visits.ensure(visit_id, language, output_language);
    // CLARIOSE_V02: pre-create the on-disk visit folder + round-000/ so the
    // first transcript event has somewhere to land. Other writers (recap,
    // ask-doctor TTS) reuse these helpers.
    if (this.folder) {
      this.folder.roundDir(visit_id, 0);
    }
    this.confirmedTasks.set(visit_id, new Map());
    this.confirmedMemories.set(visit_id, []);
    this.logger.log(
      `visit.created visit_id=${visit_id} owner=${input.ownerUserId} lang=${language} raw_audio=${meta.raw_audio_saved}`,
    );
    return { visit_id, status: "active" };
  }

  /**
   * Synchronous lookup of in-memory meta. Internal callers that already know
   * the visit was hydrated (via ensureOwner → hydrateVisit chain) can use
   * this. External callers should go through hydrateVisit first.
   */
  getVisitMeta(visit_id: string): CareNoteVisitMeta {
    const m = this.visits.get(visit_id);
    if (!m) throw new NotFoundException(`visit ${visit_id} not found`);
    return m;
  }

  async getVisit(
    visit_id: string,
    user_id?: string,
  ): Promise<{
    meta: CareNoteVisitMeta;
    state: VisitState;
    confirmed_tasks: ConfirmedTask[];
    confirmed_memories: ConfirmedMemory[];
    job_status: { pending: number; in_flight: number };
    transcript_stats: ReturnType<CareNoteHarness["assembler"]["stats"]>;
  }> {
    if (user_id) await this.ensureOwner(visit_id, user_id);
    const meta = await this.hydrateVisit(visit_id);
    // Soft-deleted (ARCHIVED) visits are 404 from the read API, even though
    // the DB row stays for audit. Mirrors typical REST soft-delete semantics.
    if (meta.status === "deleted") {
      throw new NotFoundException(`visit ${visit_id} not found`);
    }
    const harness = await this.getHarness();
    const raw = await harness.visits.get(visit_id);
    // Belt-and-braces: a visit cached in memory before the dedup fix shipped
    // can still hold duplicate accumulators. Cleaning at read time means the
    // user sees the fixed view immediately, without waiting for the next
    // analyze_turn to land.
    const state = dedupVisitState(raw);
    if (state !== raw) {
      await harness.visits.set(visit_id, state);
    }
    return {
      meta,
      state,
      confirmed_tasks: [...(this.confirmedTasks.get(visit_id)?.values() ?? [])],
      confirmed_memories: this.confirmedMemories.get(visit_id) ?? [],
      job_status: {
        pending: harness.queue.pendingCount(),
        in_flight: harness.queue.inFlightCount(),
      },
      transcript_stats: harness.assembler.stats(visit_id),
    };
  }

  async endVisit(visit_id: string): Promise<void> {
    const m = await this.hydrateVisit(visit_id);
    if (m.status === "deleted") {
      throw new ConflictException("visit was deleted");
    }
    const endedAt = new Date();
    m.status = "ended";
    m.ended_at = endedAt.toISOString();
    const startedAt = new Date(m.created_at);
    const durationSec = Math.floor(
      (endedAt.getTime() - startedAt.getTime()) / 1000,
    );
    // CLARIOSE_V02: close any still-open round + flush a final snapshot.
    try {
      const harness = await this.getHarness();
      const state = await harness.visits.get(visit_id);
      const idx = state.current_round_index ?? 0;
      const rounds = state.rounds.map((r) =>
        r.index === idx && r.ended_at == null
          ? { ...r, ended_at: endedAt.toISOString() }
          : r,
      );
      await harness.visits.set(visit_id, { ...state, rounds });
      if (this.folder) {
        const finalState = await harness.visits.get(visit_id);
        for (const r of finalState.rounds) {
          await this.folder.writeRoundSnapshot(finalState, r.index);
        }
        await this.folder.writeVisitSnapshot(finalState);
      }
      await this.persistVisitState(visit_id);
    } catch (err) {
      this.logger.warn(
        `endVisit snapshot failed visit=${visit_id}: ${(err as Error).message}`,
      );
    }
    await this.prisma.consultSession.update({
      where: { id: visit_id },
      data: { status: "ENDED", endedAt, durationSec },
    });
    // CLARIOSE_V01 §4: free the recall manifest cache for this visit.
    // Auto-dream (Week 4) will write fresh files; we don't want stale
    // manifests blocking re-scan if the user views the visit again later.
    if (this.recall) {
      void this.recall.invalidateManifest(visit_id).catch(() => undefined);
    }
    this.eventBus.emit({
      type: "visit_status_changed",
      visitId: visit_id,
      status: "ended",
    });
  }

  async deleteVisit(visit_id: string): Promise<void> {
    const m = this.visits.get(visit_id) ?? (await this.hydrateVisit(visit_id).catch(() => null));
    if (!m) return;
    m.status = "deleted";
    const harness = await this.getHarness();
    harness.visits.delete(visit_id);
    this.confirmedTasks.delete(visit_id);
    this.confirmedMemories.delete(visit_id);
    this.visits.delete(visit_id);
    await this.prisma.consultSession
      .update({ where: { id: visit_id }, data: { status: "ARCHIVED" } })
      .catch(() => undefined);
    if (this.recall) {
      void this.recall.invalidateManifest(visit_id).catch(() => undefined);
    }
    this.eventBus.emit({
      type: "visit_status_changed",
      visitId: visit_id,
      status: "deleted",
    });
    this.logger.log(`visit.deleted visit_id=${visit_id}`);
  }

  // ---------------------------------------------------------------------------
  // Realtime ingest
  // ---------------------------------------------------------------------------

  /**
   * Apply one Realtime event to the assembler. If a transcript turn
   * completes we publish to the bus (which in turn enqueues an
   * analyze_turn job).
   *
   * M7.6 — every event also mutates VisitState directly so:
   *   • GET /api/visits/:id returns the live transcript (no Codex needed);
   *   • duplicate completed events do NOT re-enqueue Codex jobs.
   */
  async ingestRealtimeEvent(
    visit_id: string,
    rawEvent: unknown,
  ): Promise<{
    accepted: boolean;
    emitted_transcript_turn: boolean;
    job_id: string | null;
    duplicate: boolean;
  }> {
    const m = await this.hydrateVisit(visit_id);
    if (m.status !== "active") {
      throw new ConflictException(
        `visit ${visit_id} is ${m.status}, cannot ingest events`,
      );
    }
    const evt = rawEvent as RealtimeIngestEvent;
    const evtType = (evt as { type?: unknown })?.type;
    if (!evt || typeof evtType !== "string") {
      throw new BadRequestException("event.type required");
    }

    const harness = await this.getHarness();

    // 1) Mutate VisitState immediately so the GET endpoint reflects the
    //    transcript even before Codex runs. We catch unknown event types
    //    (`error`, `input_audio_buffer.speech_started`, etc.) and only
    //    record their last_event_type / last_error in transcript_stats.
    const state = await harness.visits.get(visit_id);
    const beforeAlreadyAnalyzed = new Set(state.analyzed_item_ids);
    const updated = applyRealtimeEventToVisitState(state, evt);
    await harness.visits.set(visit_id, updated.next);

    // 2) Apply to the in-memory assembler ONLY for the four canonical
    //    transcript event types it understands. Other events stay
    //    visible via transcript_stats above.
    let emitted: DoctorVisitTranscriptTurnCompleted[] = [];
    if (
      evtType === "input_audio_buffer.committed" ||
      evtType === "conversation.item.input_audio_transcription.delta" ||
      evtType === "conversation.item.input_audio_transcription.completed" ||
      evtType === "conversation.item.input_audio_transcription.failed"
    ) {
      try {
        emitted = harness.assembler.apply(visit_id, evt);
      } catch (err) {
        this.logger.warn(
          `assembler error visit=${visit_id} type=${evtType}: ${(err as Error).message}`,
        );
      }
    }

    if (isPhiDebugEnabled()) {
      this.logger.debug(`ingest visit=${visit_id} ${JSON.stringify(evt)}`);
    } else {
      this.logger.debug(
        `ingest visit=${visit_id} ${JSON.stringify(redactPhi(evt))}`,
      );
    }

    let job_id: string | null = null;
    let duplicate = false;
    if (emitted.length > 0) {
      // CLARIOSE_V03 — DEFERRED AGENT FAN-OUT:
      // Per the user's hard requirement ("必须等我手动pause才能上传所有的
      // transcript给agent团队处理信息"), we do NOT publish completed turns
      // to the codex bus on ingest. Each completed turn is buffered in the
      // VisitState round it belongs to; the agent pipeline only fires when
      // the user calls endRound() (Pause) or runFinalSummary() (End visit).
      //
      // We still emit `transcript_turn_completed` to the SSE bus so the
      // browser sees live transcripts; we just don't trigger the codex
      // queue — that work is owned by flushPendingTurnsForRound().
      const fresh: DoctorVisitTranscriptTurnCompleted[] = [];
      for (const e of emitted) {
        if (beforeAlreadyAnalyzed.has(e.turn.item_id)) {
          duplicate = true;
          continue;
        }
        fresh.push(e);
      }
      for (const e of fresh) {
        this.eventBus.emit({
          type: "transcript_turn_completed",
          visitId: visit_id,
          turnId: e.turn.item_id,
          transcript: e.turn.transcript ?? "",
        });
      }
      if (fresh.length > 0) {
        // Surface a synthetic job_id so callers can tell turns landed,
        // even though the actual codex job hasn't been queued yet.
        job_id = `buffered:${visit_id}:${fresh[fresh.length - 1]!.turn.item_id}`;
      } else if (emitted.length > 0) {
        duplicate = true;
      }
    }
    // CLARIOSE_V01 §7: persist VisitState after every ingest so a process
    // reload doesn't lose the in-memory transcript / agent outputs.
    // Awaited so the next GET /api/visits/:id sees the same state the
    // ingest just wrote — the previous fire-and-forget caused races
    // where frontend polled before persist landed and saw `{}`.
    await this.persistVisitState(visit_id);
    return {
      accepted: true,
      emitted_transcript_turn: job_id !== null,
      job_id,
      duplicate,
    };
  }

  // ---------------------------------------------------------------------------
  // Realtime session minting
  // ---------------------------------------------------------------------------

  buildSessionConfig(language: RealtimeLanguage) {
    return buildRealtimeSessionConfig({
      language,
      sessionInstructions: REALTIME_SESSION_PROMPT,
      transcriptionPrompt: TRANSCRIPTION_PROMPT,
      transcriptionModel: "gpt-4o-transcribe",
    });
  }

  async mintRealtimeSession(visit_id: string, mode: "doctor_visit"): Promise<RealtimeSessionResult> {
    if (mode !== "doctor_visit") {
      throw new BadRequestException("only mode=doctor_visit is supported");
    }
    const m = await this.hydrateVisit(visit_id);
    if (m.status !== "active") {
      throw new ConflictException(`visit ${visit_id} is ${m.status}`);
    }
    if (!m.consent_recorded) {
      throw new BadRequestException("consent_recorded must be true");
    }

    const apiKey = this.cfg.get<string>("OPENAI_API_KEY");
    if (!apiKey) {
      throw new ServiceUnavailableException(
        "OPENAI_API_KEY is not configured on the server",
      );
    }

    const config = this.buildSessionConfig(m.language);

    // OpenAI Realtime: mint a client_secret bound to the desired session.
    // The exact wire format has shifted across previews — we send what the
    // GA endpoint accepts and surface raw failures rather than guessing.
    const resp = await fetch("https://api.openai.com/v1/realtime/sessions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: config.model,
        modalities: config.output_modalities,
        instructions: config.instructions,
        input_audio_transcription: {
          model: config.audio.input.transcription.model,
          language: config.audio.input.transcription.language,
          prompt: config.audio.input.transcription.prompt,
        },
        turn_detection: config.audio.input.turn_detection,
        input_audio_noise_reduction: config.audio.input.noise_reduction,
        include: config.include,
      }),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      this.logger.error(`Realtime session mint failed: ${resp.status} ${errText}`);
      throw new ServiceUnavailableException("Could not mint realtime session");
    }
    const data = (await resp.json()) as {
      client_secret: { value: string; expires_at: number };
    };
    return {
      visit_id,
      client_secret: data.client_secret.value,
      expires_at: data.client_secret.expires_at,
      model: "gpt-realtime-1.5",
      config,
    };
  }

  // ---------------------------------------------------------------------------
  // Stage / final summary
  // ---------------------------------------------------------------------------

  async runStageSummary(visit_id: string, _opts: { last_n_turns: number; mode: string }): Promise<{
    queued: true;
    job_id: string;
  }> {
    await this.hydrateVisit(visit_id);
    const harness = await this.getHarness();
    await harness.queue.enqueue({ kind: "stage_summary", visit_id });
    return { queued: true, job_id: `stage_summary:${visit_id}:${Date.now()}` };
  }

  /**
   * CLARIOSE_V03 — End-visit pipeline. Previously this only enqueued the
   * final_summary job and silently flipped in-memory meta to "ended"; the
   * DB row stayed ACTIVE, the open round was never closed, and any turns
   * buffered after the last Pause never reached the agent fan-out. The
   * user reported exactly that: "end visit之后, 其实并没有把当前轮结束".
   *
   * The new flow:
   *   1. Close the currently-open round (ended_at = now).
   *   2. Flush every pending round's buffered turns through the agent
   *      team. Most rounds are already analyzed (endRound flushes on
   *      pause), but the LAST round usually isn't because End visit is
   *      hit straight from "listening" without a Pause first.
   *   3. Wait for the codex queue to drain so the final_summary agent
   *      sees a fully analyzed VisitState.
   *   4. Persist the DB row as ENDED with endedAt + durationSec.
   *   5. Enqueue the final_summary job.
   *   6. Emit visit_status_changed so the SSE consumer flips the page.
   */
  async runFinalSummary(visit_id: string): Promise<{
    queued: true;
    job_id: string;
    finalized_round_count: number;
    analyzed_turn_count: number;
  }> {
    const m = await this.hydrateVisit(visit_id);
    if (m.status === "deleted") {
      throw new ConflictException("visit was deleted");
    }
    const harness = await this.getHarness();
    const endedAt = new Date();
    const startedAt = new Date(m.created_at);
    const durationSec = Math.floor((endedAt.getTime() - startedAt.getTime()) / 1000);

    // 1) Close the open round.
    const state = await harness.visits.get(visit_id);
    const currentIdx = state.current_round_index ?? 0;
    const rounds = state.rounds.map((r) =>
      r.index === currentIdx && r.ended_at == null
        ? { ...r, ended_at: endedAt.toISOString() }
        : r,
    );
    await harness.visits.set(visit_id, { ...state, rounds });

    // 2) Flush every round's pending turns. Most are already analyzed,
    //    but the last one usually isn't.
    let totalPublished = 0;
    for (const r of rounds) {
      const flushed = await this.flushPendingTurnsForRound(visit_id, r.index);
      totalPublished += flushed.member_count;
    }
    // Always wait — runs from earlier rounds may still be in flight.
    await this.waitForQueueIdle(180_000);

    // 3) Persist + close.
    m.status = "ended";
    m.ended_at = endedAt.toISOString();
    try {
      await this.prisma.consultSession.update({
        where: { id: visit_id },
        data: { status: "ENDED", endedAt, durationSec },
      });
    } catch (err) {
      this.logger.warn(
        `consultSession.update failed visit=${visit_id}: ${(err as Error).message}`,
      );
    }
    if (this.folder) {
      try {
        const finalState = await harness.visits.get(visit_id);
        for (const r of finalState.rounds) {
          await this.folder.writeRoundSnapshot(finalState, r.index);
        }
        await this.folder.writeVisitSnapshot(finalState);
      } catch (err) {
        this.logger.warn(
          `endVisit snapshot failed visit=${visit_id}: ${(err as Error).message}`,
        );
      }
    }
    await this.persistVisitState(visit_id);

    // 4) Enqueue the final_summary agent run. It reads the now-fully-
    //    analyzed VisitState and produces the family-facing summary.
    await harness.queue.enqueue({ kind: "final_summary", visit_id });

    // 5) Tell the SSE stream so the visit page flips into the summary view.
    this.eventBus.emit({
      type: "visit_status_changed",
      visitId: visit_id,
      status: "ended",
    });
    if (this.recall) {
      void this.recall.invalidateManifest(visit_id).catch(() => undefined);
    }

    return {
      queued: true,
      job_id: `final_summary:${visit_id}:${Date.now()}`,
      finalized_round_count: rounds.length,
      analyzed_turn_count: totalPublished,
    };
  }

  // ---------------------------------------------------------------------------
  // Confirm / reject draft tasks
  // ---------------------------------------------------------------------------

  async confirmDraftTask(visit_id: string, task_id: string): Promise<ConfirmedTask> {
    await this.hydrateVisit(visit_id);
    const harness = await this.getHarness();
    const state = await harness.visits.get(visit_id);
    let promoted: ConfirmedTask | null = null;

    const draft_tasks = state.draft_tasks.filter((t) => {
      if (t.task_id !== task_id) return true;
      promoted = {
        task_id: t.task_id,
        task_type: t.task_type,
        title: t.title,
        description: t.description,
        due_at: t.due_at ?? null,
        source_fact_ids: t.source_fact_ids ?? [],
        source_turn_ids: t.source_turn_ids,
        confirmation_status: "confirmed",
        confirmed_at: new Date().toISOString(),
      };
      return false;
    });

    const draft_reminders = state.draft_reminders.filter((r) => {
      if (r.task_id !== task_id) return true;
      promoted = {
        task_id: r.task_id,
        task_type: r.task_type,
        title: r.title,
        description: r.description,
        due_at: r.due_at ?? null,
        source_fact_ids: r.source_fact_ids ?? [],
        source_turn_ids: r.source_turn_ids,
        confirmation_status: "confirmed",
        confirmed_at: new Date().toISOString(),
      };
      return false;
    });

    if (!promoted) {
      throw new NotFoundException(
        `draft task ${task_id} not found in visit ${visit_id}`,
      );
    }

    await harness.visits.set(visit_id, { ...state, draft_tasks, draft_reminders });
    let bag = this.confirmedTasks.get(visit_id);
    if (!bag) {
      bag = new Map();
      this.confirmedTasks.set(visit_id, bag);
    }
    bag.set(task_id, promoted);
    return promoted;
  }

  async rejectDraftTask(visit_id: string, task_id: string): Promise<{ task_id: string; status: "rejected" }> {
    await this.hydrateVisit(visit_id);
    const harness = await this.getHarness();
    const state = await harness.visits.get(visit_id);
    let found = false;
    const draft_tasks = state.draft_tasks.filter((t) => {
      if (t.task_id === task_id) { found = true; return false; }
      return true;
    });
    const draft_reminders = state.draft_reminders.filter((r) => {
      if (r.task_id === task_id) { found = true; return false; }
      return true;
    });
    if (!found) {
      throw new NotFoundException(
        `draft task ${task_id} not found in visit ${visit_id}`,
      );
    }
    await harness.visits.set(visit_id, { ...state, draft_tasks, draft_reminders });
    return { task_id, status: "rejected" };
  }

  // ---------------------------------------------------------------------------
  // Confirm / reject memory candidates
  // ---------------------------------------------------------------------------

  async confirmMemoryCandidate(
    visit_id: string,
    candidate_id: string,
  ): Promise<ConfirmedMemory> {
    const m = await this.hydrateVisit(visit_id);
    const harness = await this.getHarness();
    const state = await harness.visits.get(visit_id);
    const cand = state.memory_candidates.find((c) => c.memory_candidate_id === candidate_id);
    if (!cand) {
      throw new NotFoundException(
        `memory candidate ${candidate_id} not found in visit ${visit_id}`,
      );
    }
    const memory: ConfirmedMemory = {
      memory_id: `mem-${randomUUID()}`,
      source_candidate_id: candidate_id,
      user_id: m.user_id,
      memory_type: cand.memory_type,
      content: cand.content,
      source_turn_ids: cand.source_turn_ids,
      confirmed_at: new Date().toISOString(),
    };

    // Drop the candidate from the visit so it isn't shown twice.
    const memory_candidates = state.memory_candidates.filter(
      (c) => c.memory_candidate_id !== candidate_id,
    );
    await harness.visits.set(visit_id, { ...state, memory_candidates });

    let bag = this.confirmedMemories.get(visit_id);
    if (!bag) {
      bag = [];
      this.confirmedMemories.set(visit_id, bag);
    }
    bag.push(memory);

    // Push into the in-memory retrieval service so subsequent turns can see it.
    harness.memory.add({
      memory_id: memory.memory_id,
      memory_type: cand.memory_type,
      content: cand.content,
      confidence: cand.confidence,
      source_visit_id: visit_id,
      source_turn_ids: cand.source_turn_ids,
      updated_at: memory.confirmed_at,
    });
    return memory;
  }

  async rejectMemoryCandidate(
    visit_id: string,
    candidate_id: string,
  ): Promise<{ candidate_id: string; status: "rejected" }> {
    await this.hydrateVisit(visit_id);
    const harness = await this.getHarness();
    const state = await harness.visits.get(visit_id);
    const before = state.memory_candidates.length;
    const memory_candidates = state.memory_candidates.filter(
      (c) => c.memory_candidate_id !== candidate_id,
    );
    if (memory_candidates.length === before) {
      throw new NotFoundException(
        `memory candidate ${candidate_id} not found in visit ${visit_id}`,
      );
    }
    await harness.visits.set(visit_id, { ...state, memory_candidates });
    return { candidate_id, status: "rejected" };
  }

  // ---------------------------------------------------------------------------
  // CLARIOSE_V02 — Round lifecycle
  // ---------------------------------------------------------------------------

  /**
   * CLARIOSE_V03 — flush all buffered (completed-but-not-yet-analyzed) turns
   * inside one round through the codex agent pipeline as a SINGLE batched
   * analyze_turn job. Called by endRound (on Pause) and runFinalSummary (on
   * End visit).
   *
   * Why one job and not N: gpt-realtime fragments speech on small silences,
   * so a single user thought often arrives as 2–3 transcript items. Treating
   * each item as its own agent fan-out makes agents reason on shards of
   * context and produces redundant outputs. The user's hard requirement is
   * "all transcripts in this pause-cycle should reach the team as ONE turn".
   * We concatenate the buffered transcripts (each tagged with its real
   * item_id so agents can populate source_turn_ids), use the last member's
   * item_id as the canonical turn_id (the assembler chain already points to
   * it), and publish a single event.
   *
   * Idempotent: every member item_id is moved into `analyzed_item_ids`
   * before publishing, so a concurrent flush for the same round is a no-op.
   */
  private async flushPendingTurnsForRound(
    visit_id: string,
    round_index: number,
  ): Promise<{ published: number; member_count: number }> {
    const harness = await this.getHarness();
    const state = await harness.visits.get(visit_id);
    const round = state.rounds.find((r) => r.index === round_index);
    if (!round) return { published: 0, member_count: 0 };

    const ids = round.turn_item_ids;
    if (ids.length === 0) return { published: 0, member_count: 0 };
    const turnsById = new Map(state.turns.map((t) => [t.item_id, t]));
    const alreadyAnalyzed = new Set(state.analyzed_item_ids);

    const members: { item_id: string; transcript: string; previous_item_id: string | null }[] = [];
    for (const id of ids) {
      if (alreadyAnalyzed.has(id)) continue;
      const turn = turnsById.get(id);
      if (!turn) continue;
      // Only flush turns the assembler actually completed. Partial / failed
      // turns are dropped — the agent pipeline expects a full transcript.
      if (turn.status !== "completed" || !turn.transcript) continue;
      members.push({
        item_id: turn.item_id,
        transcript: turn.transcript,
        previous_item_id: turn.previous_item_id ?? null,
      });
    }
    if (members.length === 0) return { published: 0, member_count: 0 };

    // Mark every member as analyzed BEFORE publishing so a concurrent flush
    // for the same round doesn't re-emit the batch.
    const seen = new Set(state.analyzed_item_ids);
    for (const m of members) seen.add(m.item_id);
    await harness.visits.set(visit_id, {
      ...state,
      analyzed_item_ids: [...seen],
    });

    // Concatenate transcripts with item-id labels so agents can reference
    // each fragment in source_turn_ids. The "[turn <id>] ..." prefix mirrors
    // the format the prompt assembler already uses in <recent_transcript>.
    const combinedTranscript = members
      .map((m) => `[turn ${m.item_id}] ${m.transcript}`)
      .join("\n");
    const last = members[members.length - 1]!;

    const transcriptionModel =
      this.cfg.get<string>("OPENAI_REALTIME_TRANSCRIPTION_MODEL") ??
      "gpt-4o-transcribe";
    const evt: DoctorVisitTranscriptTurnCompleted = {
      event_type: "doctor_visit.transcript_turn.completed",
      event_id: `tt_${randomUUID()}`,
      visit_id,
      turn: {
        item_id: last.item_id,
        previous_item_id: last.previous_item_id,
        transcript: combinedTranscript,
        ordering_confidence: "high",
      },
      source: {
        provider: "openai",
        api: "realtime",
        realtime_model: "gpt-realtime-1.5",
        transcription_model: transcriptionModel,
      },
      created_at: new Date().toISOString(),
    };
    harness.bus.publish(evt);
    this.logger.log(
      `flush visit=${visit_id} round=${round_index} batched ${members.length} turn(s) into one analyze_turn`,
    );
    return { published: 1, member_count: members.length };
  }

  /**
   * Close the currently-open round, flush its buffered turns to the agent
   * pipeline, wait for the queue to drain, then open a fresh round so the
   * next batch of speech doesn't pile onto this one.
   *
   * Idempotent: calling this on an already-closed round is a no-op (returns
   * the same state). Trying to close past `End visit` raises 409.
   */
  async endRound(visit_id: string): Promise<{
    closed_round_index: number;
    new_round_index: number;
    analyzed_turn_count: number;
  }> {
    const m = await this.hydrateVisit(visit_id);
    if (m.status !== "active") {
      throw new ConflictException(
        `visit ${visit_id} is ${m.status}; cannot start a new round`,
      );
    }
    const harness = await this.getHarness();
    const state = await harness.visits.get(visit_id);
    const now = new Date().toISOString();
    const currentIdx = state.current_round_index ?? 0;
    const rounds = [...state.rounds];
    const idx = rounds.findIndex((r) => r.index === currentIdx);
    if (idx === -1) {
      // Unexpected — backfill the current round before closing it.
      rounds.push({
        index: currentIdx,
        started_at: now,
        ended_at: now,
        turn_item_ids: [],
        recap_headline: null,
        recap_generated_at: null,
      });
    } else if (rounds[idx]!.ended_at == null) {
      rounds[idx] = { ...rounds[idx]!, ended_at: now };
    }

    const newIdx = currentIdx + 1;
    rounds.push({
      index: newIdx,
      started_at: now,
      ended_at: null,
      turn_item_ids: [],
      recap_headline: null,
      recap_generated_at: null,
    });

    await harness.visits.set(visit_id, {
      ...state,
      rounds,
      current_round_index: newIdx,
    });

    // Publish the batched analyze_turn for this round. Returns IMMEDIATELY
    // so the browser's "Pause" button isn't blocked behind a 30+ second
    // queue drain. The visit page is subscribed to SSE (agent_run_started /
    // agent_run_completed / blackboard_updated) and refreshes per event,
    // so panels populate progressively as each pass finishes — exactly the
    // streaming UX the user asked for.
    //
    // The standalone "Recap current round" path (prepareRoundForRecap)
    // still awaits queue idle before generating the image, so the recap
    // never races ahead of the agents.
    const flushed = await this.flushPendingTurnsForRound(visit_id, currentIdx);
    await this.persistVisitState(visit_id);
    this.eventBus.emit({
      type: "visit_status_changed",
      visitId: visit_id,
      status: m.status,
    });

    // Fire-and-forget: once the agents land, run the pause-time noise
    // filter and then snapshot the closed round. We do NOT await this — the
    // caller has already received the response and the visit page is
    // reading state via SSE. The noise filter runs AFTER queue idle so it
    // sees the cumulative VisitState produced by every per-turn agent for
    // this round; its `applyNoiseFilter` reducer strips quarantined
    // contributions so the recap that follows reads from a cleaned state.
    void this.waitForQueueIdle(180_000)
      .then(async () => {
        try {
          const result = await harness.manager.runPauseNoiseFilter({
            visit_id,
            round_index: currentIdx,
          });
          if (result.applied) {
            this.logger.log(
              `noise_filter visit=${visit_id} round=${currentIdx} ` +
                `quarantined=${result.quarantined_turn_ids.length}/` +
                `${result.noise_tags?.summary.total_turns ?? 0}`,
            );
          }
        } catch (err) {
          this.logger.warn(
            `noise_filter failed visit=${visit_id} round=${currentIdx}: ${(err as Error).message}`,
          );
        }
        if (this.folder) {
          const updated = await harness.visits.get(visit_id);
          try {
            await this.folder.writeRoundSnapshot(updated, currentIdx);
            await this.folder.writeVisitSnapshot(updated);
          } catch (err) {
            this.logger.warn(
              `round snapshot write failed visit=${visit_id} round=${currentIdx}: ${(err as Error).message}`,
            );
          }
        }
        await this.persistVisitState(visit_id);
      })
      .catch((err) => {
        this.logger.warn(
          `endRound background drain failed visit=${visit_id} round=${currentIdx}: ${(err as Error).message}`,
        );
      });

    return {
      closed_round_index: currentIdx,
      new_round_index: newIdx,
      analyzed_turn_count: flushed.member_count,
    };
  }

  /**
   * Flush a target round's pending turns through the agent pipeline and
   * block until the codex queue is idle. Used by the team-recap controller
   * so the image generation always sees a fully-analyzed VisitState — the
   * user reported that the image was being produced before all agents had
   * finished, and the cause was the standalone "Recap current round" path
   * skipping the flush+wait that endRound does.
   *
   * Idempotent: turns already analyzed are skipped, and waitForQueueIdle
   * returns immediately when the queue is already empty.
   */
  async prepareRoundForRecap(
    visit_id: string,
    round_index: number,
  ): Promise<{ analyzed_turn_count: number; quarantined_turn_count: number }> {
    const flushed = await this.flushPendingTurnsForRound(visit_id, round_index);
    await this.waitForQueueIdle(180_000);
    // Pause-time noise filter — strips quarantined-turn contributions from
    // VisitState before the recap reads it. Failures are logged but do not
    // block the recap, so this path is identical in shape to the previous
    // version when the filter is unavailable.
    const harness = await this.getHarness();
    let quarantined_turn_count = 0;
    try {
      const result = await harness.manager.runPauseNoiseFilter({
        visit_id,
        round_index,
      });
      if (result.applied) {
        quarantined_turn_count = result.quarantined_turn_ids.length;
        this.logger.log(
          `noise_filter visit=${visit_id} round=${round_index} ` +
            `quarantined=${quarantined_turn_count}/` +
            `${result.noise_tags?.summary.total_turns ?? 0} (recap path)`,
        );
      }
    } catch (err) {
      this.logger.warn(
        `noise_filter failed visit=${visit_id} round=${round_index}: ${(err as Error).message}`,
      );
    }
    return {
      analyzed_turn_count: flushed.member_count,
      quarantined_turn_count,
    };
  }

  /**
   * Cache a generated recap inline on the closed round so the frontend can
   * render multiple rounds side-by-side without re-fetching, and so the
   * on-disk recap.json sits next to the round folder.
   */
  async attachRoundRecap(
    visit_id: string,
    round_index: number,
    recap: { headline: string; generated_at: string; [k: string]: unknown },
  ): Promise<void> {
    const harness = await this.getHarness();
    const state = await harness.visits.get(visit_id);
    const rounds = state.rounds.map((r) =>
      r.index === round_index
        ? {
            ...r,
            recap_headline: recap.headline,
            recap_generated_at: recap.generated_at,
          }
        : r,
    );
    await harness.visits.set(visit_id, { ...state, rounds });
    if (this.folder) {
      try {
        await this.folder.writeRoundRecap(visit_id, round_index, recap);
      } catch (err) {
        this.logger.warn(
          `round recap write failed visit=${visit_id} round=${round_index}: ${(err as Error).message}`,
        );
      }
    }
    await this.persistVisitState(visit_id);
  }

  // ---------------------------------------------------------------------------
  // CLARIOSE_V02 — Reverse translate-TTS (patient → doctor)
  // ---------------------------------------------------------------------------

  /**
   * Translate the patient's question into English and synthesize speech
   * with gpt-4o-mini-tts so they can play it for the doctor. The audio
   * mp3 lands in the current round's `asks/` subfolder.
   */
  async askDoctor(
    visit_id: string,
    input: { source_language?: string; source_text: string },
  ): Promise<AskDoctorResult> {
    if (!this.translateTts) {
      throw new ServiceUnavailableException("translate-tts not wired");
    }
    const m = await this.hydrateVisit(visit_id);
    if (m.status !== "active") {
      throw new ConflictException(
        `visit ${visit_id} is ${m.status}; cannot ask new questions`,
      );
    }
    const harness = await this.getHarness();
    const state = await harness.visits.get(visit_id);
    const round_index = state.current_round_index ?? 0;
    const result = await this.translateTts.ask({
      visit_id,
      round_index,
      source_language: input.source_language ?? state.output_language ?? state.language,
      source_text: input.source_text,
    });
    const log = {
      ask_id: result.ask_id,
      round_index,
      source_language: result.source_language,
      source_text: result.source_text,
      translated_text: result.translated_text,
      audio_relpath: result.audio_relpath,
      duration_ms: result.duration_ms,
      created_at: result.created_at,
    };
    await harness.visits.set(visit_id, {
      ...state,
      ask_doctor_logs: [...state.ask_doctor_logs, log],
    });
    await this.persistVisitState(visit_id);
    return result;
  }

  /** Resolve the absolute filesystem path for an ask-doctor mp3. */
  askDoctorAudioPath(
    visit_id: string,
    round_index: number,
    ask_id: string,
  ): string | null {
    if (!this.folder) return null;
    return this.folder.askAudioPath(visit_id, round_index, ask_id);
  }

  /** Find an ask log by id (across all rounds) so the audio handler can serve it. */
  async findAskLog(
    visit_id: string,
    ask_id: string,
  ): Promise<{ round_index: number; audio_relpath: string } | null> {
    const harness = await this.getHarness();
    const state = await harness.visits.get(visit_id);
    const log = state.ask_doctor_logs.find((a) => a.ask_id === ask_id);
    if (!log) return null;
    return { round_index: log.round_index, audio_relpath: log.audio_relpath };
  }

  // ---------------------------------------------------------------------------
  // Drain / waiting helpers (used by tests + smoke scripts)
  // ---------------------------------------------------------------------------

  async waitForQueueIdle(timeoutMs = 5_000): Promise<void> {
    const harness = await this.getHarness();
    const start = Date.now();
    // initial small yield so the bus → queue handoff lands.
    await new Promise((r) => setTimeout(r, 25));
    while (harness.queue.pendingCount() > 0 || harness.queue.inFlightCount() > 0) {
      if (Date.now() - start > timeoutMs) return;
      // eslint-disable-next-line no-await-in-loop
      await new Promise((r) => setTimeout(r, 25));
    }
  }
}
