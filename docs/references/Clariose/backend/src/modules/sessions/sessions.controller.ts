import {
  Body, Controller, Get, Param, Post, UseGuards,
} from '@nestjs/common';
import { AuthGuard } from '@nestjs/passport';
import { IsBoolean, IsIn, IsInt, IsOptional, IsString } from 'class-validator';

import { SessionsService } from './sessions.service';
import { CurrentUser, AuthedUser } from '../../common/decorators/current-user.decorator';

class UtteranceDto {
  @IsOptional() @IsString() realtimeItemId?: string;
  @IsOptional() @IsString() id?: string;
  @IsString() text!: string;
  @IsString() @IsIn(['doctor', 'patient', 'unknown']) speaker!: 'doctor' | 'patient' | 'unknown';
  @IsInt() startedAt!: number;
  // Accepted (and ignored) for forward-compat with the realtime client which
  // tags finals so they can be distinguished from in-flight partials.
  @IsOptional() @IsBoolean() isFinal?: boolean;
}

/**
 * SessionsController — thin ConsultSession surface that survives the v1/v1.5
 * removal. The agent-fanout endpoints (`/agents/run`, `/agents`, `/digest`,
 * `/reminders/accept`) are gone; `carenote` (`/api/visits/*`) is the sole
 * agent execution path. This controller keeps just session listing and the
 * legacy transcript-utterance ingest used by the realtime layer.
 */
@UseGuards(AuthGuard('jwt'))
@Controller()
export class SessionsController {
  constructor(private readonly sessions: SessionsService) {}

  @Get('sessions')
  list(@CurrentUser() u: AuthedUser) {
    return this.sessions.listForUser(u.id);
  }

  @Post('sessions/:id/utterances')
  async addUtterance(
    @Param('id') sessionId: string,
    @Body() dto: UtteranceDto,
    @CurrentUser() u: AuthedUser,
  ) {
    await this.sessions.ensureOwner(sessionId, u.id);
    return this.sessions.addUtterance(sessionId, {
      realtimeItemId: dto.realtimeItemId ?? dto.id,
      speaker: dto.speaker,
      text: dto.text,
      startedAt: dto.startedAt,
    });
  }

  @Post('sessions/:id/end')
  async end(@Param('id') sessionId: string, @CurrentUser() u: AuthedUser) {
    await this.sessions.ensureOwner(sessionId, u.id);
    return this.sessions.end(sessionId);
  }
}
