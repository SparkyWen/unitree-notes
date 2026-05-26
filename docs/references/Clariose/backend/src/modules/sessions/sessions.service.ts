import { ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { Speaker } from '@prisma/client';
import { PrismaService } from '../../common/prisma/prisma.service';

@Injectable()
export class SessionsService {
  constructor(private readonly prisma: PrismaService) {}

  async create(userId: string, opts: { doctorName?: string }) {
    // Find or create the patient profile for this user.
    let patient = await this.prisma.patient.findUnique({ where: { userId } });
    if (!patient) {
      const user = await this.prisma.user.findUnique({ where: { id: userId } });
      if (!user) throw new NotFoundException('User not found');
      patient = await this.prisma.patient.create({
        data: { userId, fullName: user.displayName || user.email },
      });
    }
    return this.prisma.consultSession.create({
      data: {
        ownerUserId: userId,
        patientId: patient.id,
        doctorName: opts.doctorName,
      },
    });
  }

  attachRealtime(sessionId: string, model: string) {
    return this.prisma.consultSession.update({
      where: { id: sessionId },
      data: { realtimeModel: model },
    });
  }

  async listForUser(userId: string) {
    const rows = await this.prisma.consultSession.findMany({
      where: { ownerUserId: userId },
      orderBy: { startedAt: 'desc' },
      take: 50,
      select: {
        id: true, startedAt: true, durationSec: true,
        utteranceCount: true, reminderCount: true,
        doctorName: true, summaryMd: true,
      },
    });
    return rows.map(r => ({ ...r, summary: r.summaryMd }));
  }

  async ensureOwner(sessionId: string, userId: string) {
    const s = await this.prisma.consultSession.findUnique({ where: { id: sessionId } });
    if (!s) throw new NotFoundException('Session not found');
    if (s.ownerUserId !== userId) throw new ForbiddenException();
    return s;
  }

  async addUtterance(sessionId: string, payload: {
    realtimeItemId?: string;
    speaker: 'doctor' | 'patient' | 'unknown';
    text: string;
    startedAt: number;
  }) {
    const speaker: Speaker = payload.speaker === 'doctor' ? 'DOCTOR'
      : payload.speaker === 'patient' ? 'PATIENT' : 'UNKNOWN';

    // Idempotent on (sessionId, realtimeItemId) so client retries are safe.
    const existing = payload.realtimeItemId
      ? await this.prisma.transcriptUtterance.findUnique({
          where: { sessionId_realtimeItemId: { sessionId, realtimeItemId: payload.realtimeItemId } },
        })
      : null;
    if (existing) return existing;

    const u = await this.prisma.transcriptUtterance.create({
      data: {
        sessionId,
        speaker,
        text: payload.text,
        startedAtMs: payload.startedAt,
        realtimeItemId: payload.realtimeItemId,
      },
    });
    await this.prisma.consultSession.update({
      where: { id: sessionId },
      data: { utteranceCount: { increment: 1 } },
    });
    return u;
  }

  async end(sessionId: string) {
    const session = await this.prisma.consultSession.findUnique({ where: { id: sessionId } });
    if (!session) throw new NotFoundException();
    const durationSec = Math.floor((Date.now() - session.startedAt.getTime()) / 1000);
    return this.prisma.consultSession.update({
      where: { id: sessionId },
      data: { endedAt: new Date(), status: 'ENDED', durationSec },
    });
  }

  fullTranscriptText(sessionId: string) {
    return this.prisma.transcriptUtterance.findMany({
      where: { sessionId },
      orderBy: { startedAtMs: 'asc' },
    });
  }
}
