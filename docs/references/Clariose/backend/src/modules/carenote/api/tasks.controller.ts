import {
  Body,
  Controller,
  Get,
  HttpCode,
  Param,
  Post,
  Query,
  UseGuards,
} from "@nestjs/common";
import { AuthGuard } from "@nestjs/passport";
import { IsOptional, IsString, MaxLength } from "class-validator";

import { CareNoteService } from "./carenote.service";
import { TasksService } from "../runtime/tasks/tasks.service";
import {
  AuthedUser,
  CurrentUser,
} from "../../../common/decorators/current-user.decorator";

class QueueMessageDto {
  @IsString() @MaxLength(40) from!: string;
  @IsString() @MaxLength(4000) text!: string;
}

class TailQueryDto {
  @IsOptional() @IsString() offset?: string;
}

/**
 * TasksController — read surface for Layer-1 runtime tasks plus a
 * SendMessage-equivalent for parents/operators to push a message into a
 * running task's mailbox.
 *
 * Routes (mounted under the global `api` prefix from main.ts):
 *   GET    /api/visits/:visitId/runtime-tasks
 *   GET    /api/runtime-tasks/:taskId
 *   GET    /api/runtime-tasks/:taskId/output           (sidechain tail)
 *   POST   /api/runtime-tasks/:taskId/messages         (queue a pending message)
 *   POST   /api/runtime-tasks/:taskId/kill             (cooperative cancel)
 */
@UseGuards(AuthGuard("jwt"))
@Controller()
export class TasksController {
  constructor(
    private readonly tasks: TasksService,
    private readonly carenote: CareNoteService,
  ) {}

  @Get("visits/:visitId/runtime-tasks")
  async listForVisit(
    @Param("visitId") visitId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    await this.carenote.ensureOwner(visitId, user.id);
    return this.tasks.listForVisit(visitId);
  }

  @Get("runtime-tasks/:taskId")
  async get(
    @Param("taskId") taskId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    const task = this.tasks.get(taskId);
    await this.carenote.ensureOwner(task.visitId, user.id);
    return this.tasks.snapshot(taskId);
  }

  @Get("runtime-tasks/:taskId/output")
  async output(
    @Param("taskId") taskId: string,
    @Query() q: TailQueryDto,
    @CurrentUser() user: AuthedUser,
  ) {
    const task = this.tasks.get(taskId);
    await this.carenote.ensureOwner(task.visitId, user.id);
    const offset = q.offset ? Number.parseInt(q.offset, 10) : undefined;
    return this.tasks.tail(taskId, Number.isFinite(offset) ? offset : undefined);
  }

  @Post("runtime-tasks/:taskId/messages")
  @HttpCode(202)
  async queueMessage(
    @Param("taskId") taskId: string,
    @Body() dto: QueueMessageDto,
    @CurrentUser() user: AuthedUser,
  ) {
    const task = this.tasks.get(taskId);
    await this.carenote.ensureOwner(task.visitId, user.id);
    const ok = this.tasks.queueMessage(taskId, dto.from, dto.text);
    return { ok };
  }

  @Post("runtime-tasks/:taskId/kill")
  @HttpCode(202)
  async kill(
    @Param("taskId") taskId: string,
    @CurrentUser() user: AuthedUser,
  ) {
    const task = this.tasks.get(taskId);
    await this.carenote.ensureOwner(task.visitId, user.id);
    return this.tasks.kill(taskId, "killed by user");
  }
}
