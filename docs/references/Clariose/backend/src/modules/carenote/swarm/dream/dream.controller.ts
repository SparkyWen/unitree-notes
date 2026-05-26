// HTTP + SSE surface for the dream runner. All endpoints are JWT-guarded
// and scoped to the current user.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §6.

import {
  Controller,
  Get,
  HttpCode,
  HttpException,
  HttpStatus,
  type MessageEvent,
  Param,
  Post,
  Query,
  Sse,
  UseGuards,
} from "@nestjs/common";
import { AuthGuard } from "@nestjs/passport";
import { Observable, concat, from, interval, map, merge } from "rxjs";

import {
  type AuthedUser,
  CurrentUser,
} from "../../../../common/decorators/current-user.decorator";
import { PrismaService } from "../../../../common/prisma/prisma.service";
import { CarenoteEventBus } from "../eventBus";
import { DreamRunner } from "./dream.runner";
import { DreamSessionRegistry } from "./dream.session";
import { DreamWorkspace } from "./dream.workspace";
import type {
  DreamFileResponse,
  DreamRunSummary,
  DreamTreeResponse,
  DreamVisitOption,
} from "./dream.types";

const VISIT_PICKER_LIMIT = 50;

@UseGuards(AuthGuard("jwt"))
@Controller("carenote/dream")
export class DreamController {
  constructor(
    private readonly runner: DreamRunner,
    private readonly bus: CarenoteEventBus,
    private readonly sessions: DreamSessionRegistry,
    private readonly workspace: DreamWorkspace,
    private readonly prisma: PrismaService,
  ) {}

  @Post("run")
  @HttpCode(202)
  async runAll(@CurrentUser() user: AuthedUser): Promise<{ dreamId: string }> {
    const r = await this.runner.run(user.id, {
      scope: { kind: "all" },
      trigger: "manual_user",
      bypassTimeGate: true,
    });
    if (r.outcome === "started" && r.dreamId) return { dreamId: r.dreamId };
    if (r.outcome === "no_eligible_visits") {
      throw new HttpException({ reason: "no_eligible_visits" }, HttpStatus.LOCKED);
    }
    if (r.outcome === "busy") {
      throw new HttpException({ reason: "busy" }, HttpStatus.CONFLICT);
    }
    if (r.outcome === "disabled") {
      throw new HttpException(
        { reason: "disabled" },
        HttpStatus.SERVICE_UNAVAILABLE,
      );
    }
    throw new HttpException({ reason: r.outcome }, HttpStatus.BAD_REQUEST);
  }

  @Post("run/visit/:visitId")
  @HttpCode(202)
  async runVisit(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ): Promise<{ dreamId: string }> {
    const r = await this.runner.run(user.id, {
      scope: { kind: "visit", visitId },
      trigger: "manual_visit",
      bypassTimeGate: true,
    });
    if (r.outcome === "started" && r.dreamId) return { dreamId: r.dreamId };
    if (r.outcome === "forbidden") {
      throw new HttpException({ reason: "forbidden" }, HttpStatus.FORBIDDEN);
    }
    if (r.outcome === "empty_visit") {
      // 422 Unprocessable Entity — request was well-formed but the
      // visit has nothing to consolidate (no utterances, no summary).
      throw new HttpException(
        { reason: "empty_visit" },
        HttpStatus.UNPROCESSABLE_ENTITY,
      );
    }
    if (r.outcome === "busy") {
      throw new HttpException({ reason: "busy" }, HttpStatus.CONFLICT);
    }
    if (r.outcome === "disabled") {
      throw new HttpException(
        { reason: "disabled" },
        HttpStatus.SERVICE_UNAVAILABLE,
      );
    }
    throw new HttpException({ reason: r.outcome }, HttpStatus.BAD_REQUEST);
  }

  @Get("runs")
  async listRuns(@CurrentUser() user: AuthedUser): Promise<DreamRunSummary[]> {
    const rows = await this.prisma.dreamRun.findMany({
      where: { userId: user.id },
      orderBy: { startedAt: "desc" },
      take: 20,
    });
    return rows.map((r) => ({
      id: r.id,
      scope: r.scope,
      trigger: triggerToKind(r.trigger),
      status: r.status.toLowerCase() as DreamRunSummary["status"],
      startedAt: r.startedAt.toISOString(),
      endedAt: r.endedAt?.toISOString() ?? null,
      visitCount: r.visitCount,
      filesUpdated: r.filesUpdated,
      errorMessage: r.errorMessage ?? null,
    }));
  }

  @Get("visits")
  async visits(
    @CurrentUser() user: AuthedUser,
  ): Promise<DreamVisitOption[]> {
    // No date window — we cap by count instead. Filter to "has content"
    // (at least one persisted utterance OR a non-empty summary): visits
    // that were started but abandoned before any utterance was finalised
    // aren't dreamable, and offering them in the picker just produces
    // stub rollout_summaries saying "no clinical content".
    //
    // Filter on `utterances: { some: {} }` (relational EXISTS) rather
    // than the cached `consult_sessions.utteranceCount` integer — the
    // counter has been observed to drift (incremented during an active
    // session, then the rows got purged on disconnect without
    // decrementing the counter). The agent saw an empty transcript and
    // wrote a "no clinical content" stub. Filtering on the actual
    // relation is the source of truth.
    const rows = await this.prisma.consultSession.findMany({
      where: {
        ownerUserId: user.id,
        status: "ENDED",
        OR: [
          { utterances: { some: {} } },
          { summaryMd: { not: null } },
        ],
      },
      select: {
        id: true,
        startedAt: true,
        endedAt: true,
        doctorName: true,
        summaryMd: true,
        utteranceCount: true,
        durationSec: true,
        _count: { select: { utterances: true } },
      },
      orderBy: { endedAt: "desc" },
      take: VISIT_PICKER_LIMIT,
    });
    const dreamedIds = await this.workspace.dreamedVisitIds(user.id);
    return rows.map((r) => ({
      visitId: r.id,
      startedAt: r.startedAt.toISOString(),
      endedAt: r.endedAt!.toISOString(),
      doctorName: r.doctorName ?? null,
      summaryPreview: previewOf(r.summaryMd),
      hasMemoryFile: dreamedIds.has(r.id),
      // Trust the relational count over the cached counter — see the
      // comment above the query for why.
      utteranceCount: r._count.utterances,
      durationSec: r.durationSec,
    }));
  }

  @Get("tree")
  async tree(@CurrentUser() user: AuthedUser): Promise<DreamTreeResponse> {
    const root = this.workspace.rootForUser(user.id);
    const u = await this.prisma.user.findUnique({
      where: { id: user.id },
      select: { lastDreamedAt: true },
    });
    const nodes = await this.workspace.walkTree(user.id);
    return {
      root,
      lastDreamedAt: u?.lastDreamedAt?.toISOString() ?? null,
      nodes,
    };
  }

  @Get("file")
  async file(
    @CurrentUser() user: AuthedUser,
    @Query("path") path?: string,
  ): Promise<DreamFileResponse> {
    if (!path || typeof path !== "string") {
      throw new HttpException(
        { reason: "missing_path" },
        HttpStatus.BAD_REQUEST,
      );
    }
    try {
      const r = await this.workspace.readFile(user.id, path);
      return {
        path,
        content: r.content,
        mtime: r.mtime,
        bytes: r.bytes,
      };
    } catch (err) {
      throw new HttpException(
        { reason: (err as Error).message },
        HttpStatus.BAD_REQUEST,
      );
    }
  }

  @Sse("events")
  events(@CurrentUser() user: AuthedUser): Observable<MessageEvent> {
    const open = this.sessions.findOpen(user.id);
    const replay = open
      ? from(
          this.sessions.replayBuffer(open.dreamId).map(
            (ev): MessageEvent => ({
              type: "dream_progress",
              data: {
                type: "dream_progress",
                dreamId: open.dreamId,
                userId: user.id,
                phase: ev.phase,
                pct: ev.pct,
                note: ev.note,
                at: ev.at,
              },
            }),
          ),
        )
      : from([] as MessageEvent[]);

    const live = this.bus.streamForUser(user.id).pipe(
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

    return merge(concat(replay, live), heartbeat);
  }
}

function triggerToKind(t: string): DreamRunSummary["trigger"] {
  if (t === "MANUAL_USER") return "manual_user";
  if (t === "MANUAL_VISIT") return "manual_visit";
  return "cron";
}

function previewOf(md: string | null | undefined): string | null {
  if (!md) return null;
  // Strip markdown headers and collapse whitespace; the picker renders
  // this in a single-line cell so we don't need anything fancier.
  const text = md
    .replace(/^#+\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return null;
  return text.length > 120 ? `${text.slice(0, 117)}…` : text;
}
