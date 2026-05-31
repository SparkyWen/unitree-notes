// REST endpoints for recall chat sessions: list, new, resume, transcript replay.

import {
  Controller,
  Delete,
  Get,
  Param,
  Post,
  UseGuards,
} from "@nestjs/common";
import { AuthGuard } from "@nestjs/passport";

import { CurrentUser, type AuthedUser } from "../../common/decorators/current-user.decorator";
import { RecallSessionStore } from "./recallSession.store";
import { PrismaService } from "../../common/prisma/prisma.service";

@UseGuards(AuthGuard("jwt"))
@Controller("recall/sessions")
export class RecallSessionsController {
  constructor(
    private readonly store: RecallSessionStore,
    private readonly prisma: PrismaService,
  ) {}

  @Get()
  async list(@CurrentUser() user: AuthedUser) {
    return this.store.list(user.id);
  }

  @Post("new")
  async newChat(@CurrentUser() user: AuthedUser) {
    return this.store.newChat(user.id);
  }

  @Post(":id/resume")
  async resume(@CurrentUser() user: AuthedUser, @Param("id") id: string) {
    await this.store.resume(user.id, id);
    return { ok: true, sessionId: id };
  }

  @Get(":id/messages")
  async messages(@CurrentUser() user: AuthedUser, @Param("id") id: string) {
    return this.store.getMessages(user.id, id);
  }

  @Delete(":id")
  async softDelete(@CurrentUser() user: AuthedUser, @Param("id") id: string) {
    // Soft-delete: mark inactive + ended. Phase-1 uses that as the eligibility
    // signal, so a soft-deleted session can still be distilled into memory.
    const target = await this.prisma.recallSession.findFirst({
      where: { id, userId: user.id },
    });
    if (!target) return { ok: false };
    await this.prisma.recallSession.update({
      where: { id },
      data: { active: false, endedAt: new Date() },
    });
    return { ok: true };
  }
}
