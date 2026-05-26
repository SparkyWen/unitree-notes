// SSE chat controller for the recall coordinator.
//
// Two endpoints:
//   GET  /api/recall/chat/stream?token=<jwt>      ← EventSource subscription
//   POST /api/recall/chat                         ← submit a user prompt
//   POST /api/recall/chat/abort                   ← cancel the running turn
//
// The stream is per-active-session: when the user hits POST /chat we look
// up the active session, append the user message, spawn the codex
// coordinator, and the SSE handler emits whatever events the coordinator
// publishes. Open the stream BEFORE posting the prompt to avoid missing
// the early `session_started` event.

import {
  Body,
  Controller,
  HttpCode,
  Post,
  Sse,
  UseGuards,
} from "@nestjs/common";
import { AuthGuard } from "@nestjs/passport";
import { IsOptional, IsString, MaxLength, MinLength } from "class-validator";
import { Observable } from "rxjs";

import { CurrentUser, type AuthedUser } from "../../common/decorators/current-user.decorator";
import { RecallCoordinatorService } from "./recallCoordinator.service";
import { RecallSessionStore } from "./recallSession.store";
import type { RecallSseEvent } from "./recall.types";

class ChatStartDto {
  @IsOptional() @IsString() sessionId?: string | null;
  @IsString() @MinLength(1) @MaxLength(8000) prompt!: string;
}

class ChatAbortDto {
  @IsString() sessionId!: string;
}

@UseGuards(AuthGuard("jwt"))
@Controller("recall/chat")
export class RecallChatController {
  constructor(
    private readonly coordinator: RecallCoordinatorService,
    private readonly store: RecallSessionStore,
  ) {}

  @Post()
  @HttpCode(202)
  async start(
    @CurrentUser() user: AuthedUser,
    @Body() dto: ChatStartDto,
  ) {
    const sessionId = dto.sessionId
      ?? (await this.store.getOrCreateActive(user.id)).sessionId;
    // Fire-and-forget; the coordinator streams via the per-session emitter.
    void this.coordinator
      .runTurn({ userId: user.id, sessionId, prompt: dto.prompt })
      .catch(() => {
        /* errors land on the SSE channel as type:'error' */
      });
    return { ok: true, sessionId };
  }

  @Post("abort")
  async abort(
    @CurrentUser() user: AuthedUser,
    @Body() dto: ChatAbortDto,
  ) {
    void user;
    const aborted = this.coordinator.abort(dto.sessionId);
    return { ok: true, aborted };
  }

  /** Subscribe to the active session's events via SSE.
   *  EventSource cannot send Authorization headers; jwt.strategy.ts
   *  accepts ?token=... query for that reason. */
  @Sse("stream")
  stream(@CurrentUser() user: AuthedUser): Observable<MessageEvent> {
    return new Observable<MessageEvent>((subscriber) => {
      let unsubscribe: (() => void) | null = null;
      let cancelled = false;
      let currentSessionId: string | null = null;

      // Subscribe to whatever the user's active session is. If the active
      // session changes mid-stream (newChat / resume), we attach to the
      // new one on the next ping. The frontend reconnects on `session_started`
      // for fresh sessions anyway, so this is just a cold-start fallback.
      const attach = async () => {
        const { sessionId } = await this.store.getOrCreateActive(user.id);
        if (cancelled) return;
        if (currentSessionId === sessionId) return;
        currentSessionId = sessionId;
        if (unsubscribe) unsubscribe();
        unsubscribe = this.coordinator.subscribe(sessionId, (e: RecallSseEvent) => {
          subscriber.next({ data: e } as MessageEvent);
        });
      };

      void attach();
      const reattachTimer = setInterval(() => { void attach(); }, 5_000);
      // Immediate keep-alive so EventSource flips to OPEN.
      subscriber.next({ data: { type: "ready" } } as unknown as MessageEvent);

      return () => {
        cancelled = true;
        clearInterval(reattachTimer);
        if (unsubscribe) unsubscribe();
      };
    });
  }
}
