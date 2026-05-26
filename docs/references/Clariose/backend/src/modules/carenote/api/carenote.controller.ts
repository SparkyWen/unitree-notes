// CareNote HTTP surface — visit-scoped operations.
//
// Routes (mounted under the global `api` prefix from main.ts):
//   POST   /api/visits
//   GET    /api/visits/:visitId
//   GET    /api/visits/:visitId/events                  (SSE; CLARIOSE_V01 §8.2)
//   POST   /api/visits/:visitId/realtime-events
//   POST   /api/visits/:visitId/stage-summary
//   POST   /api/visits/:visitId/final-summary
//   POST   /api/visits/:visitId/draft-tasks/:taskId/confirm
//   POST   /api/visits/:visitId/draft-tasks/:taskId/reject
//   POST   /api/visits/:visitId/memory-candidates/:candidateId/confirm
//   POST   /api/visits/:visitId/memory-candidates/:candidateId/reject
//   DELETE /api/visits/:visitId
//
// Auth: JWT-guarded — all backend surfaces require a signed-in user.
// CareNote operates on the same JWT identity as the rest of the app.

import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  MessageEvent,
  Param,
  Post,
  Query,
  Sse,
  UseGuards,
} from "@nestjs/common";
import { SkipThrottle } from "@nestjs/throttler";
import { AuthGuard } from "@nestjs/passport";
import {
  IsBoolean,
  IsIn,
  IsInt,
  IsObject,
  IsOptional,
  IsString,
  Max,
  Min,
} from "class-validator";
import { Observable, interval, map, merge } from "rxjs";

import { CareNoteService } from "./carenote.service";
import { CarenoteEventBus } from "../swarm/eventBus";
import { TeamRecapService } from "../recap/teamRecap.service";
import { BlackboardService } from "../swarm/blackboard";
import { MailboxFileService } from "../swarm/mailboxFile";
import { tryParseStructured } from "../swarm/mailboxMessages";
import { PrismaService } from "../../../common/prisma/prisma.service";
import { ForbiddenException, NotFoundException, Res } from "@nestjs/common";
import type { Response } from "express";
import { createReadStream, existsSync } from "node:fs";
import { AuthedUser, CurrentUser } from "../../../common/decorators/current-user.decorator";

class CreateVisitDto {
  // CLARIOSE_V01: user_id removed — owner is the JWT subject. Passing
  // user_id from the client was a horizontal-privilege bug (any logged-in
  // user could create visits "as" another user).
  @IsOptional() @IsIn(["zh", "en", "mixed"]) language?: "zh" | "en" | "mixed";
  // CLARIOSE_V02: language the user wants to READ. The agent fan-out and
  // recap render in this language. Defaults to `language` server-side.
  @IsOptional() @IsIn(["zh", "en", "mixed"]) output_language?: "zh" | "en" | "mixed";
  @IsBoolean() consent_recorded!: boolean;
  @IsOptional() @IsBoolean() raw_audio_saved?: boolean;
}

class AskDoctorDto {
  @IsString() source_text!: string;
  @IsOptional() @IsString() source_language?: string;
}

class RealtimeEventDto {
  // The OpenAI Realtime event shape varies; we accept it as opaque and
  // let the assembler validate by `type`. CLARIOSE_V01: explicit @IsObject
  // so the global whitelist pipe doesn't strip it.
  @IsObject() event!: Record<string, unknown>;
}

class StageSummaryDto {
  @IsOptional() @IsInt() @Min(1) @Max(200) last_n_turns?: number;
  @IsOptional() @IsString() mode?: string;
}

@UseGuards(AuthGuard("jwt"))
@Controller()
export class CareNoteVisitsController {
  constructor(
    private readonly carenote: CareNoteService,
    private readonly bus: CarenoteEventBus,
    private readonly recap: TeamRecapService,
    private readonly blackboard: BlackboardService,
    private readonly mailboxFile: MailboxFileService,
    private readonly prisma: PrismaService,
  ) {}

  @Post("visits")
  async createVisit(
    @Body() dto: CreateVisitDto,
    @CurrentUser() user: AuthedUser,
  ) {
    return this.carenote.createVisit({
      ownerUserId: user.id,
      language: dto.language,
      output_language: dto.output_language,
      consent_recorded: dto.consent_recorded,
      raw_audio_saved: dto.raw_audio_saved,
    });
  }

  @Get("visits")
  async listVisits(@CurrentUser() user: AuthedUser) {
    return this.carenote.listVisitsForUser(user.id);
  }

  @Get("visits/:visitId")
  async getVisit(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    const full = await this.carenote.getVisit(visitId, user.id);
    const team_recaps = await this.recap.listAll(visitId);
    // Keep team_recap for back-compat (latest one) — the UI prefers
    // team_recaps so per-round images survive a page refresh.
    const team_recap = team_recaps.length ? team_recaps[team_recaps.length - 1] : null;
    return { ...full, team_recap, team_recaps };
  }

  // CLARIOSE_V03 — multi-agent collaboration timeline. Surfaces the
  // mailbox messages, blackboard writes, and agent runs the swarm has
  // exchanged so the UI can show *how* the team coordinated, not just
  // *what* each agent eventually wrote. Read-only; no side effects.
  @Get("visits/:visitId/team-activity")
  async teamActivity(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);

    const KNOWN_ROLES = [
      "visit_orchestrator",
      "transcript_quality",
      "speaker_role",
      "medical_instruction_extractor",
      "safety_clarification",
      "medication_reminder_draft",
      "follow_up_task_draft",
      "compliance_guardrail",
      "family_summary",
      "memory_update",
      "final_visit_summary",
    ];

    const messages: Array<{
      from: string;
      to: string;
      timestamp: string;
      summary: string | null;
      kind: string;
      text: string;
    }> = [];
    for (const role of KNOWN_ROLES) {
      const inbox = await this.mailboxFile.read(visitId, role);
      for (const m of inbox) {
        const structured = tryParseStructured(m.text);
        messages.push({
          from: m.from,
          to: role,
          timestamp: m.timestamp,
          summary: m.summary ?? null,
          kind: structured?.type ?? "free_text",
          text: m.text,
        });
      }
    }
    messages.sort((a, b) => a.timestamp.localeCompare(b.timestamp));

    const blackboard = await this.blackboard.snapshot(visitId);

    const agent_runs = await this.prisma.carenoteAgentRun.findMany({
      where: { visitId },
      orderBy: { startedAt: "asc" },
      select: {
        id: true,
        role: true,
        kind: true,
        status: true,
        validationStatus: true,
        latencyMs: true,
        startedAt: true,
        endedAt: true,
        errorMessage: true,
        prompt: true,
        parsedJson: true,
        modelName: true,
      },
      take: 200,
    });

    return {
      messages,
      blackboard: blackboard.map((b) => ({
        key: b.key,
        value: b.value,
        writtenBy: b.writtenBy,
        version: b.version,
        updatedAt: b.updatedAt,
      })),
      agent_runs: agent_runs.map((r) => ({
        id: r.id,
        role: r.role,
        kind: r.kind,
        status: r.status,
        validation_status: r.validationStatus,
        latency_ms: r.latencyMs,
        started_at: r.startedAt.toISOString(),
        ended_at: r.endedAt?.toISOString() ?? null,
        error: r.errorMessage,
        // Truncated payloads so the expand-on-click panel can show what the
        // agent actually saw and produced. Hard cap keeps the JSON response
        // small even when the harness logs huge prompts.
        prompt: r.prompt ? r.prompt.slice(0, 8000) : null,
        prompt_truncated: !!r.prompt && r.prompt.length > 8000,
        parsed_json: r.parsedJson ?? null,
        model_name: r.modelName,
      })),
    };
  }

  // POST /api/visits/:visitId/team-recap
  // Trigger when the user pauses or ends recording. Aggregates the latest
  // VisitState into a glanceable digest and renders an infographic via
  // gpt-image-2-2026-04-21. Returns the recap inline so the UI can render
  // immediately. The PNG is also saved to disk and streamed by
  // GET /api/visits/:visitId/recap-image.
  @Post("visits/:visitId/team-recap")
  @HttpCode(200)
  async runTeamRecap(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    const pre = await this.carenote.getVisit(visitId, user.id);
    // CLARIOSE_V02: recap targets the round that was JUST closed, i.e.
    // current_round_index - 1 if we have one. If the user clicks recap
    // before pausing, fall back to the current (still-open) round so the
    // generation isn't blocked.
    const cur = pre.state.current_round_index ?? 0;
    const round_index = cur > 0 ? cur - 1 : 0;
    // Block image generation until every agent for this round has finished.
    // The user reported the image rendering BEFORE the agents wrote their
    // outputs; the standalone Recap path used to skip this step.
    await this.carenote.prepareRoundForRecap(visitId, round_index);
    const full = await this.carenote.getVisit(visitId, user.id);
    const recap = await this.recap.generateForRound(
      visitId,
      full.state,
      round_index,
    );
    await this.carenote.attachRoundRecap(visitId, round_index, recap);
    return recap;
  }

  // CLARIOSE_V02 — close the current round, open a new one.
  // The user's "Pause & recap" flow calls this before runTeamRecap so the
  // recap operates on the just-closed round and the next round starts
  // empty instead of having outputs stack on top of each other.
  @Post("visits/:visitId/round/end")
  @HttpCode(200)
  async endRound(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.carenote.endRound(visitId);
  }

  // CLARIOSE_V02 — reverse translate-TTS. The patient writes a question
  // in their native language; we return the English translation + an
  // mp3 they can play out loud for the doctor.
  @SkipThrottle()
  @Post("visits/:visitId/ask-doctor")
  @HttpCode(200)
  async askDoctor(
    @Param("visitId") visitId: string,
    @Body() dto: AskDoctorDto,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.carenote.askDoctor(visitId, {
      source_text: dto.source_text,
      source_language: dto.source_language,
    });
  }

  // CLARIOSE_V02 — stream the mp3 produced by ask-doctor.
  @SkipThrottle()
  @Get("visits/:visitId/asks/:askId/audio")
  async askAudio(
    @Param("visitId") visitId: string,
    @Param("askId") askId: string,
    @CurrentUser() user: AuthedUser,
    @Res() res: Response,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    const log = await this.carenote.findAskLog(visitId, askId);
    if (!log) throw new NotFoundException("ask not found");
    const path = this.carenote.askDoctorAudioPath(visitId, log.round_index, askId);
    if (!path || !existsSync(path)) {
      throw new NotFoundException("audio not generated");
    }
    res.setHeader("Content-Type", "audio/mpeg");
    res.setHeader("Cache-Control", "private, max-age=3600");
    createReadStream(path).pipe(res);
  }

  // Per-round recap image. The visit page passes ?round=<n> so each pause
  // cycle shows its own consolidated team-output image instead of one
  // global image getting overwritten on every recap.
  @SkipThrottle()
  @Get("visits/:visitId/recap-image")
  async recapImage(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
    @Res() res: Response,
    @Query("round") round?: string,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    const roundIdx = round != null && round !== "" ? Number(round) : undefined;
    const path =
      typeof roundIdx === "number" && Number.isFinite(roundIdx)
        ? this.recap.imagePathFor(visitId, roundIdx)
        : this.recap.imagePathFor(visitId);
    if (!existsSync(path)) {
      // Fall back to the un-suffixed image for legacy visits.
      const legacy = this.recap.imagePathFor(visitId);
      if (existsSync(legacy)) {
        res.setHeader("Content-Type", "image/png");
        res.setHeader("Cache-Control", "private, max-age=60");
        createReadStream(legacy).pipe(res);
        return;
      }
      throw new NotFoundException("recap image not generated yet");
    }
    res.setHeader("Content-Type", "image/png");
    res.setHeader("Cache-Control", "private, max-age=60");
    createReadStream(path).pipe(res);
  }

  // CLARIOSE_V01: implements §8.2 — SSE stream of every event for one visit.
  // Frontend subscribes via EventSource and listens for type-specific events
  // (transcript_turn_completed, agent_run_completed, blackboard_updated, …).
  // Heartbeat every 15s prevents nginx idle-proxy timeout (default 60s).
  // Auth: EventSource cannot send Authorization headers, so the JWT comes via
  // ?token=... — the JWT strategy accepts both extractors. Ownership is
  // checked once on connect; the stream itself is filtered by visitId so it
  // won't leak other visits' events even if the URL is shared.
  @Sse("visits/:visitId/events")
  async streamEvents(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ): Promise<Observable<MessageEvent>> {
    await this.carenote.ensureOwner(visitId, user.id);
    const events = this.bus.streamForVisit(visitId).pipe(
      map(
        (e): MessageEvent => ({
          type: e.type,
          data: e,
        }),
      ),
    );
    const heartbeat = interval(15_000).pipe(
      map(
        (): MessageEvent => ({
          type: "heartbeat",
          data: { ts: Date.now() },
        }),
      ),
    );
    return merge(events, heartbeat);
  }

  // Realtime ingest is fired per Realtime data-channel event (committed,
  // delta×N, completed, …). A single multi-minute visit can easily exceed
  // the global 120 req/min throttler — exactly the symptom the user hit
  // (`429` on /realtime-events while transcripts kept piping in OpenAI's
  // side, so earlier turns silently never reached the server). The handler
  // is JWT-guarded and per-visit ownership-checked, so skipping the
  // throttler is safe; downstream work is bounded by the harness queue.
  @SkipThrottle()
  @Post("visits/:visitId/realtime-events")
  @HttpCode(200)
  async ingest(
    @Param("visitId") visitId: string,
    @Body() dto: RealtimeEventDto,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.carenote.ingestRealtimeEvent(visitId, dto.event);
  }

  @Post("visits/:visitId/stage-summary")
  @HttpCode(202)
  async stageSummary(
    @Param("visitId") visitId: string,
    @Body() dto: StageSummaryDto,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.carenote.runStageSummary(visitId, {
      last_n_turns: dto.last_n_turns ?? 10,
      mode: dto.mode ?? "patient_plain_language",
    });
  }

  @Post("visits/:visitId/final-summary")
  @HttpCode(202)
  async finalSummary(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.carenote.runFinalSummary(visitId);
  }

  @Post("visits/:visitId/draft-tasks/:taskId/confirm")
  async confirmTask(
    @Param("visitId") visitId: string,
    @Param("taskId") taskId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.carenote.confirmDraftTask(visitId, taskId);
  }

  @Post("visits/:visitId/draft-tasks/:taskId/reject")
  async rejectTask(
    @Param("visitId") visitId: string,
    @Param("taskId") taskId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.carenote.rejectDraftTask(visitId, taskId);
  }

  @Post("visits/:visitId/memory-candidates/:candidateId/confirm")
  async confirmMemory(
    @Param("visitId") visitId: string,
    @Param("candidateId") candidateId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.carenote.confirmMemoryCandidate(visitId, candidateId);
  }

  @Post("visits/:visitId/memory-candidates/:candidateId/reject")
  async rejectMemory(
    @Param("visitId") visitId: string,
    @Param("candidateId") candidateId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.carenote.rejectMemoryCandidate(visitId, candidateId);
  }

  @Delete("visits/:visitId")
  @HttpCode(204)
  async deleteVisit(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    await this.carenote.deleteVisit(visitId);
  }
}
