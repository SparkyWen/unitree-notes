// CLARIOSE_V01 §5.1 — daily auto-dream cron.
//
// Cron tick fires DreamRunner.runDailyConsolidation(). The cron expression
// is hard-coded; CARENOTE_DREAM_HOUR is a deprecated env that we still
// log a warning for if set, to avoid silent drift.

import { Injectable, Logger, OnModuleInit } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { Cron } from "@nestjs/schedule";

import { DreamRunner } from "./dream/dream.runner";

const DAILY_AT_0300 = "0 3 * * *";

@Injectable()
export class DreamCronService implements OnModuleInit {
  private readonly logger = new Logger("DreamCron");

  constructor(
    private readonly cfg: ConfigService,
    private readonly runner: DreamRunner,
  ) {}

  onModuleInit(): void {
    const hour = this.cfg.get<string>("CARENOTE_DREAM_HOUR") ?? "3";
    if (hour !== "3") {
      this.logger.warn(
        `CARENOTE_DREAM_HOUR=${hour} but cron is hard-coded to 03:00. Ignoring.`,
      );
    }
    if (this.cfg.get<string>("CARENOTE_DREAM_ENABLED") === "false") {
      this.logger.log("auto-dream disabled — cron will tick but no-op");
    } else {
      this.logger.log(`scheduled daily auto-dream at ${DAILY_AT_0300}`);
    }
  }

  @Cron(DAILY_AT_0300, { name: "carenote.autoDream.daily" })
  async tick(): Promise<void> {
    try {
      const r = await this.runner.runDailyConsolidation();
      this.logger.log(
        `cron tick complete: users=${r.users} ok=${r.ok} failed=${r.failed}`,
      );
    } catch (err) {
      this.logger.error(`cron tick threw: ${(err as Error).message}`);
    }
  }
}
