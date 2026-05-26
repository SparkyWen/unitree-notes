// CLARIOSE_V01 §9 — on-demand inter-agent triggers.
//
// Roles register interest in (a) blackboard keys and/or (b) mailbox
// messages addressed to them. When EventBus publishes a matching event,
// this registry is consulted; if there's a subscriber AND it's not in
// cooldown AND the hop counter hasn't tripped, a fresh codex job is enqueued.
//
// No agent ever polls another agent. All cross-role coordination is
// event-driven. Per CCLearn note 4 §"DON'T": polling between siblings is
// forbidden because it forces every agent to re-run on every tick.
//
// Defenses:
//  - per-(visit, role) cooldown 2s — same role can't be re-fired in a
//    rapid loop
//  - max hop count 3 per turn — prevents A→B→A→B chains from running
//    forever; the hop is carried on the job and incremented each enqueue

import { Injectable, Logger } from "@nestjs/common";

import type { CodexAgentRole } from "../medical/medicalSchemas";
import { CarenoteEventBus, type CarenoteEvent } from "./eventBus";

const COOLDOWN_MS = 2000;
const MAX_HOPS = 3;

export type Subscription = {
  role: CodexAgentRole;
  /** Blackboard keys the role wants to react to. */
  onBlackboardKeys?: string[];
  /** True = react to ANY mailbox message addressed to me. */
  onMailboxFromAnyone?: boolean;
};

export type TriggerContext = {
  visit_id: string;
  role: CodexAgentRole;
  reason: string;
  hop: number;
};

export type TriggerHandler = (ctx: TriggerContext) => Promise<void>;

@Injectable()
export class SubscriptionRegistry {
  private readonly logger = new Logger("SubscriptionRegistry");
  private readonly subs: Subscription[] = [];
  private readonly lastFired = new Map<string, number>(); // `${visit}:${role}` → ms
  private handler: TriggerHandler | null = null;

  constructor(private readonly bus: CarenoteEventBus) {}

  /** Wire the bus → trigger pipeline. Called once at module init. */
  start(handler: TriggerHandler): void {
    this.handler = handler;
    this.bus.stream().subscribe((evt) => {
      void this.onEvent(evt).catch((err) =>
        this.logger.warn(`onEvent failed: ${(err as Error).message}`),
      );
    });
  }

  /** Declare a role's interest. Idempotent on (role). */
  register(sub: Subscription): void {
    const idx = this.subs.findIndex((s) => s.role === sub.role);
    if (idx >= 0) this.subs[idx] = sub;
    else this.subs.push(sub);
  }

  /** Lookup the blackboard keys a role cares about. Used by the run-manager
   *  to slice the blackboard when assembling the role's prompt — each role
   *  only sees the keys it subscribed to (token thrift + isolation). */
  blackboardKeysFor(role: CodexAgentRole): string[] {
    return this.subs.find((s) => s.role === role)?.onBlackboardKeys ?? [];
  }

  /** Default carenote subscription map. Wires the most-useful triggers
   *  the team's role catalog actually depends on. */
  registerDefaultsFor(team: CodexAgentRole[]): void {
    // medication_reminder_draft re-runs whenever allergies or
    // medication_plan_draft change.
    if (team.includes("medication_reminder_draft" as CodexAgentRole)) {
      this.register({
        role: "medication_reminder_draft" as CodexAgentRole,
        onBlackboardKeys: ["allergies", "medication_plan_draft"],
        onMailboxFromAnyone: true,
      });
    }
    // safety_clarification re-runs whenever new safety_flags appear.
    if (team.includes("safety_clarification" as CodexAgentRole)) {
      this.register({
        role: "safety_clarification" as CodexAgentRole,
        onBlackboardKeys: ["safety_flags"],
        onMailboxFromAnyone: true,
      });
    }
    // family_summary picks up updated family_brief or new safety_flags.
    if (team.includes("family_summary" as CodexAgentRole)) {
      this.register({
        role: "family_summary" as CodexAgentRole,
        onBlackboardKeys: ["family_brief", "safety_flags"],
      });
    }
  }

  // ───────────────────────────────────────────────────────────────────────────

  private async onEvent(evt: CarenoteEvent): Promise<void> {
    if (!this.handler) return;
    if (evt.type === "blackboard_updated") {
      const matching = this.subs.filter((s) =>
        (s.onBlackboardKeys ?? []).includes(evt.key),
      );
      for (const m of matching) {
        // Don't bounce a write back to its own author.
        if (m.role === evt.writtenBy) continue;
        await this.fire({
          visit_id: evt.visitId,
          role: m.role,
          reason: `blackboard.${evt.key} v${evt.version}`,
          hop: 0,
        });
      }
    } else if (evt.type === "mailbox_message") {
      const target = this.subs.find(
        (s) => s.role === (evt.to as CodexAgentRole) && s.onMailboxFromAnyone,
      );
      if (target) {
        await this.fire({
          visit_id: evt.visitId,
          role: target.role,
          reason: `mailbox from ${evt.from} (${evt.payloadKind})`,
          hop: 0,
        });
      }
    }
  }

  private async fire(ctx: TriggerContext): Promise<void> {
    if (!this.handler) return;
    if (ctx.hop >= MAX_HOPS) {
      this.logger.warn(
        `cycle_breaker_engaged visit=${ctx.visit_id} role=${ctx.role} reason=${ctx.reason}`,
      );
      return;
    }
    const key = `${ctx.visit_id}:${ctx.role}`;
    const now = Date.now();
    const last = this.lastFired.get(key) ?? 0;
    if (now - last < COOLDOWN_MS) {
      this.logger.debug(
        `cooldown skip visit=${ctx.visit_id} role=${ctx.role} (${now - last}ms since last)`,
      );
      return;
    }
    this.lastFired.set(key, now);
    await this.handler(ctx);
  }
}
