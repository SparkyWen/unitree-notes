import { Body, Controller, Post, UseGuards } from '@nestjs/common';
import { AuthGuard } from '@nestjs/passport';
import { IsIn, IsOptional, IsString } from 'class-validator';

import { RealtimeService } from './realtime.service';
import { SessionsService } from '../sessions/sessions.service';
import { CurrentUser, AuthedUser } from '../../common/decorators/current-user.decorator';

class MintSessionDto {
  @IsOptional() @IsString() @IsIn(['consult']) kind?: 'consult';
  @IsOptional() @IsString() doctorName?: string;
}

@UseGuards(AuthGuard('jwt'))
@Controller('realtime')
export class RealtimeController {
  constructor(
    private readonly realtime: RealtimeService,
    private readonly sessions: SessionsService,
  ) {}

  /**
   * Mints a Realtime client_secret AND creates a ConsultSession in one round-trip.
   * The frontend uses the returned `sessionId` for transcript/agent endpoints.
   */
  @Post('sessions')
  async create(@Body() dto: MintSessionDto, @CurrentUser() user: AuthedUser) {
    const session = await this.sessions.create(user.id, { doctorName: dto.doctorName });
    const { clientSecret, expiresAt } = await this.realtime.mintEphemeralKey();
    await this.sessions.attachRealtime(session.id, this.realtime.model);
    return {
      sessionId: session.id,
      model: this.realtime.model,
      clientSecret,
      expiresAt,
    };
  }
}
