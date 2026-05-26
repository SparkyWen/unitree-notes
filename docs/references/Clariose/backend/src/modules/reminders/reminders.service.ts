import { ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { ReminderStatus } from '@prisma/client';
import { PrismaService } from '../../common/prisma/prisma.service';

@Injectable()
export class RemindersService {
  constructor(private readonly prisma: PrismaService) {}

  list(userId: string) {
    return this.prisma.reminder.findMany({
      where: { ownerUserId: userId, status: { in: ['SCHEDULED', 'PAUSED', 'DONE'] } },
      orderBy: [{ status: 'asc' }, { startsOn: 'asc' }],
    }).then(rows => rows.map(r => ({
      id: r.id, title: r.title, drug: r.drug, dose: r.dose,
      cadence: r.cadence, channel: r.channel.toLowerCase(),
      status: r.status.toLowerCase(),
      startsOn: r.startsOn.toISOString(),
      endsOn: r.endsOn?.toISOString() ?? null,
      nextFireAt: r.nextFireAt?.toISOString() ?? null,
    })));
  }

  async update(userId: string, id: string, patch: { status?: ReminderStatus }) {
    const r = await this.prisma.reminder.findUnique({ where: { id } });
    if (!r) throw new NotFoundException();
    if (r.ownerUserId !== userId) throw new ForbiddenException();
    return this.prisma.reminder.update({ where: { id }, data: patch });
  }
}
