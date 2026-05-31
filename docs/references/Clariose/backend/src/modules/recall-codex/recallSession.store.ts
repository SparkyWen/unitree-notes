// RecallSessionStore — Postgres-backed transcript store. Two responsibilities:
//   (1) bookkeeping for the active session pointer (one per user);
//   (2) persisting RecallMessage rows + parsed citations so reload can
//       replay the full transcript.

import { Injectable, NotFoundException } from "@nestjs/common";

import { PrismaService } from "../../common/prisma/prisma.service";
import type {
  RecallCitationView,
  RecallMessageView,
  RecallSessionSummary,
  RecallToolCall,
  RecallUsage,
} from "./recall.types";

@Injectable()
export class RecallSessionStore {
  constructor(private readonly prisma: PrismaService) {}

  async list(userId: string): Promise<RecallSessionSummary[]> {
    const rows = await this.prisma.recallSession.findMany({
      where: { userId },
      orderBy: [{ active: "desc" }, { lastTurnAt: "desc" }, { createdAt: "desc" }],
      take: 50,
    });
    return rows.map((s) => ({
      sessionId: s.id,
      mtimeMs: (s.lastTurnAt ?? s.createdAt).getTime(),
      bytes: 0, // not tracked at row level; UI does not need this
      messageCount: s.messageCount,
      firstPrompt: s.firstPrompt,
      cwd: null,
      projectLabel: "recall",
      own: true,
      resumable: true,
      active: s.active,
    }));
  }

  async getOrCreateActive(userId: string): Promise<{ sessionId: string }> {
    const existing = await this.prisma.recallSession.findFirst({
      where: { userId, active: true },
      orderBy: { lastTurnAt: "desc" },
    });
    if (existing) return { sessionId: existing.id };

    const created = await this.prisma.recallSession.create({
      data: { userId, active: true },
    });
    return { sessionId: created.id };
  }

  /** Transition: mark the current active session ended; create a fresh one. */
  async newChat(userId: string): Promise<{ sessionId: string }> {
    await this.prisma.recallSession.updateMany({
      where: { userId, active: true },
      data: { active: false, endedAt: new Date() },
    });
    const created = await this.prisma.recallSession.create({
      data: { userId, active: true },
    });
    return { sessionId: created.id };
  }

  /** Move the active pointer to an existing session id. */
  async resume(userId: string, sessionId: string): Promise<void> {
    const target = await this.prisma.recallSession.findFirst({
      where: { id: sessionId, userId },
    });
    if (!target) throw new NotFoundException("session not found");
    await this.prisma.$transaction([
      this.prisma.recallSession.updateMany({
        where: { userId, active: true, NOT: { id: sessionId } },
        data: { active: false, endedAt: new Date() },
      }),
      this.prisma.recallSession.update({
        where: { id: sessionId },
        data: { active: true, endedAt: null },
      }),
    ]);
  }

  async getMessages(
    userId: string,
    sessionId: string,
  ): Promise<{ sessionId: string; messages: RecallMessageView[]; citations: RecallCitationView[] }> {
    const session = await this.prisma.recallSession.findFirst({
      where: { id: sessionId, userId },
      include: {
        messages: { orderBy: { createdAt: "asc" } },
        citations: true,
      },
    });
    if (!session) throw new NotFoundException("session not found");
    return {
      sessionId: session.id,
      messages: session.messages.map((m) => ({
        id: m.id,
        role: m.role as "user" | "assistant",
        content: m.content,
        toolCalls: (m.toolCalls as unknown as RecallToolCall[] | null) ?? undefined,
        usage: (m.usage as unknown as RecallUsage | null) ?? undefined,
        createdAt: m.createdAt.toISOString(),
      })),
      citations: session.citations.map((c) => ({
        relPath: c.relPath,
        startLine: c.startLine ?? undefined,
        endLine: c.endLine ?? undefined,
        excerpt: c.excerpt ?? undefined,
      })),
    };
  }

  async appendUserMessage(
    sessionId: string,
    content: string,
  ): Promise<{ messageId: string }> {
    const result = await this.prisma.$transaction(async (tx) => {
      const session = await tx.recallSession.findUnique({
        where: { id: sessionId },
        select: { firstPrompt: true, messageCount: true },
      });
      const msg = await tx.recallMessage.create({
        data: { sessionId, role: "user", content },
      });
      await tx.recallSession.update({
        where: { id: sessionId },
        data: {
          messageCount: { increment: 1 },
          lastTurnAt: new Date(),
          firstPrompt: session?.firstPrompt ?? content.slice(0, 200),
        },
      });
      return { messageId: msg.id };
    });
    return result;
  }

  async appendAssistantMessage(
    sessionId: string,
    content: string,
    opts: {
      toolCalls?: RecallToolCall[];
      usage?: RecallUsage;
      codexThreadId?: string | null;
      citations?: RecallCitationView[];
    } = {},
  ): Promise<{ messageId: string }> {
    return this.prisma.$transaction(async (tx) => {
      const msg = await tx.recallMessage.create({
        data: {
          sessionId,
          role: "assistant",
          content,
          toolCalls: opts.toolCalls ? (opts.toolCalls as any) : undefined,
          usage: opts.usage ? (opts.usage as any) : undefined,
        },
      });
      await tx.recallSession.update({
        where: { id: sessionId },
        data: {
          messageCount: { increment: 1 },
          lastTurnAt: new Date(),
          codexThreadId: opts.codexThreadId ?? undefined,
        },
      });
      if (opts.citations?.length) {
        await tx.recallCitation.createMany({
          data: opts.citations.map((c) => ({
            sessionId,
            messageId: msg.id,
            relPath: c.relPath,
            startLine: c.startLine ?? null,
            endLine: c.endLine ?? null,
            excerpt: c.excerpt ?? null,
          })),
        });
      }
      return { messageId: msg.id };
    });
  }

  async getCodexThreadId(sessionId: string): Promise<string | null> {
    const row = await this.prisma.recallSession.findUnique({
      where: { id: sessionId },
      select: { codexThreadId: true },
    });
    return row?.codexThreadId ?? null;
  }
}
