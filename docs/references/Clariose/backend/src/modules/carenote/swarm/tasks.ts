// User-facing draft tasks (medical follow-up appointments, lifestyle items, …)
// surfaced from the codex pipeline and surviving in the DB until the user
// confirms or rejects them. NOT to be confused with the multi-agent
// communication Layer-1 — that lives in runtime/tasks/tasks.service.ts and
// tracks codex *role-runs*, not user-facing items.

import { Injectable, Logger, NotFoundException } from "@nestjs/common";

import { PrismaService } from "../../../common/prisma/prisma.service";

export type TaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type CarenoteTaskRow = {
  id: string;
  visitId: string;
  parentTaskId: string | null;
  createdByRole: string;
  taskType: string;
  description: string;
  status: TaskStatus;
  inputJson: unknown;
  outputJson: unknown | null;
  blackboardKeys: string[];
  createdAt: string;
  updatedAt: string;
};

@Injectable()
export class DraftTasksService {
  private readonly logger = new Logger("DraftTasks");

  constructor(private readonly prisma: PrismaService) {}

  async create(args: {
    visit_id: string;
    parent_task_id?: string | null;
    created_by_role: string;
    task_type: string;
    description: string;
    input?: unknown;
    blackboard_keys?: string[];
  }): Promise<CarenoteTaskRow> {
    const row = await this.prisma.carenoteTask.create({
      data: {
        visitId: args.visit_id,
        parentTaskId: args.parent_task_id ?? null,
        createdByRole: args.created_by_role,
        taskType: args.task_type,
        description: args.description,
        status: "pending",
        inputJson: (args.input ?? {}) as object,
        blackboardKeys: args.blackboard_keys ?? [],
      },
    });
    return rowToDto(row);
  }

  async update(args: {
    task_id: string;
    status?: TaskStatus;
    output?: unknown;
    blackboard_keys?: string[];
  }): Promise<CarenoteTaskRow> {
    const row = await this.prisma.carenoteTask.update({
      where: { id: args.task_id },
      data: {
        ...(args.status ? { status: args.status } : {}),
        ...(args.output !== undefined ? { outputJson: args.output as object } : {}),
        ...(args.blackboard_keys ? { blackboardKeys: args.blackboard_keys } : {}),
      },
    });
    return rowToDto(row);
  }

  async get(task_id: string): Promise<CarenoteTaskRow> {
    const row = await this.prisma.carenoteTask.findUnique({
      where: { id: task_id },
    });
    if (!row) throw new NotFoundException(`task ${task_id} not found`);
    return rowToDto(row);
  }

  async listForVisit(
    visit_id: string,
    opts: { status?: TaskStatus } = {},
  ): Promise<CarenoteTaskRow[]> {
    const rows = await this.prisma.carenoteTask.findMany({
      where: {
        visitId: visit_id,
        ...(opts.status ? { status: opts.status } : {}),
      },
      orderBy: { createdAt: "asc" },
    });
    return rows.map(rowToDto);
  }
}

function rowToDto(r: {
  id: string;
  visitId: string;
  parentTaskId: string | null;
  createdByRole: string;
  taskType: string;
  description: string;
  status: string;
  inputJson: unknown;
  outputJson: unknown;
  blackboardKeys: string[];
  createdAt: Date;
  updatedAt: Date;
}): CarenoteTaskRow {
  return {
    id: r.id,
    visitId: r.visitId,
    parentTaskId: r.parentTaskId,
    createdByRole: r.createdByRole,
    taskType: r.taskType,
    description: r.description,
    status: r.status as TaskStatus,
    inputJson: r.inputJson,
    outputJson: r.outputJson,
    blackboardKeys: r.blackboardKeys,
    createdAt: r.createdAt.toISOString(),
    updatedAt: r.updatedAt.toISOString(),
  };
}
