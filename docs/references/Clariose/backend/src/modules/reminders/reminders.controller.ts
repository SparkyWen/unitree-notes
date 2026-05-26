import { Body, Controller, Get, Param, Patch, UseGuards } from '@nestjs/common';
import { AuthGuard } from '@nestjs/passport';
import { IsIn, IsOptional, IsString } from 'class-validator';
import { ReminderStatus } from '@prisma/client';

import { RemindersService } from './reminders.service';
import { CurrentUser, AuthedUser } from '../../common/decorators/current-user.decorator';

class PatchDto {
  @IsOptional() @IsString() @IsIn(['scheduled', 'paused', 'done', 'cancelled'])
  status?: 'scheduled' | 'paused' | 'done' | 'cancelled';
}

@UseGuards(AuthGuard('jwt'))
@Controller('reminders')
export class RemindersController {
  constructor(private readonly reminders: RemindersService) {}

  @Get()
  list(@CurrentUser() u: AuthedUser) {
    return this.reminders.list(u.id);
  }

  @Patch(':id')
  update(@Param('id') id: string, @Body() dto: PatchDto, @CurrentUser() u: AuthedUser) {
    return this.reminders.update(u.id, id, {
      status: dto.status?.toUpperCase() as ReminderStatus | undefined,
    });
  }
}
