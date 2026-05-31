import { Module } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';
import { ConfigModule } from '@nestjs/config';
import { ScheduleModule } from '@nestjs/schedule';
import { ThrottlerGuard, ThrottlerModule } from '@nestjs/throttler';

import { PrismaModule } from './common/prisma/prisma.module';
import { AuthModule } from './modules/auth/auth.module';
import { RealtimeModule } from './modules/realtime/realtime.module';
import { SessionsModule } from './modules/sessions/sessions.module';
import { RemindersModule } from './modules/reminders/reminders.module';
import { CareNoteModule } from './modules/carenote/api/carenote.module';
import { RecallCodexModule } from './modules/recall-codex/recall.module';
import { HealthController } from './modules/health/health.controller';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    ScheduleModule.forRoot(),
    ThrottlerModule.forRoot([{ ttl: 60_000, limit: 120 }]),
    PrismaModule,
    AuthModule,
    RealtimeModule,
    SessionsModule,
    RemindersModule,
    CareNoteModule,
    RecallCodexModule,
  ],
  controllers: [HealthController],
  providers: [
    // Global rate-limit guard — combined with per-route @Throttle on /auth.
    { provide: APP_GUARD, useClass: ThrottlerGuard },
  ],
})
export class AppModule {}
