// CLARIOSE_V01 §3 + §9 — 4-layer comm tests.
//   - mailbox file round-trip with structured + free-text payloads
//   - mailbox drain marks unread → read atomically
//   - blackboard write emits blackboard_updated to the bus
//   - SubscriptionRegistry fires single_role on matching blackboard event
//   - cooldown blocks rapid re-fire
//   - hop counter trips MAX_HOPS

import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ConfigService } from "@nestjs/config";

import { CarenoteEventBus } from "../../src/modules/carenote/swarm/eventBus";
import { MailboxFileService } from "../../src/modules/carenote/swarm/mailboxFile";
import { MailboxService } from "../../src/modules/carenote/swarm/mailboxService";
import { BlackboardService } from "../../src/modules/carenote/swarm/blackboard";
import {
  SubscriptionRegistry,
  type TriggerContext,
} from "../../src/modules/carenote/swarm/subscriptionRegistry";
import { createTaskAssignment } from "../../src/modules/carenote/swarm/mailboxMessages";
import { makeFakePrisma } from "./fakePrisma";

async function setup() {
  const tmp = await mkdtemp(join(tmpdir(), "carenote-swarm-"));
  const cfg = new ConfigService({ CARENOTE_TEAMS_ROOT: tmp });
  const bus = new CarenoteEventBus();
  const file = new MailboxFileService(cfg);
  // Build a fake prisma with the carenoteMailbox + carenoteBlackboard ops
  // we use here. fakePrisma already covers consultSession/patient/user; we
  // monkey-extend.
  const prisma = makeFakePrisma() as any;
  const mailboxRows: any[] = [];
  prisma.carenoteMailbox = {
    create: async ({ data }: { data: any }) => {
      mailboxRows.push({ id: `m_${mailboxRows.length}`, ...data });
      return mailboxRows[mailboxRows.length - 1];
    },
    updateMany: async ({ where, data }: { where: any; data: any }) => {
      let n = 0;
      for (const r of mailboxRows) {
        if (r.visitId === where.visitId && r.recipientRole === where.recipientRole) {
          if (where.isRead === false && r.isRead) continue;
          Object.assign(r, data);
          n++;
        }
      }
      return { count: n };
    },
  };
  const blackboardRows = new Map<string, any>();
  prisma.carenoteBlackboard = {
    findUnique: async ({ where }: { where: any }) =>
      blackboardRows.get(`${where.visitId_key.visitId}:${where.visitId_key.key}`) ?? null,
    findMany: async ({ where }: { where: any }) => {
      const all = [...blackboardRows.values()];
      return all.filter(
        (r) =>
          r.visitId === where.visitId &&
          (!where.key?.in || (where.key.in as string[]).includes(r.key)),
      );
    },
    upsert: async ({ where, create, update }: { where: any; create: any; update: any }) => {
      const k = `${where.visitId_key.visitId}:${where.visitId_key.key}`;
      const existing = blackboardRows.get(k);
      if (existing) {
        Object.assign(existing, update, { updatedAt: new Date() });
        return existing;
      }
      const row = { id: `bb_${blackboardRows.size}`, ...create, updatedAt: new Date() };
      blackboardRows.set(k, row);
      return row;
    },
  };
  prisma.$transaction = async (fn: any) => fn(prisma);

  const mailbox = new MailboxService(file, prisma, bus);
  const blackboard = new BlackboardService(prisma, bus);
  const subs = new SubscriptionRegistry(bus);

  return {
    cfg,
    bus,
    mailbox,
    blackboard,
    subs,
    prisma,
    mailboxRows,
    cleanup: () => rm(tmp, { recursive: true, force: true }),
  };
}

describe("CLARIOSE_V01 §3 — Mailbox file + DB", () => {
  test("send + drain round-trip with free-text payload", async () => {
    const { mailbox, cleanup } = await setup();
    try {
      await mailbox.send({
        visit_id: "v1",
        from: "speaker_role",
        to: "medical_instruction_extractor",
        payload: "ping",
      });

      const drained = await mailbox.drainUnread(
        "v1",
        "medical_instruction_extractor",
      );
      expect(drained).toHaveLength(1);
      expect(drained[0]!.text).toBe("ping");
      expect(drained[0]!.structured).toBeNull();

      // Second drain returns nothing (already marked read).
      const again = await mailbox.drainUnread(
        "v1",
        "medical_instruction_extractor",
      );
      expect(again).toHaveLength(0);
    } finally {
      await cleanup();
    }
  });

  test("structured payload is JSON-encoded into text and parses back", async () => {
    const { mailbox, cleanup } = await setup();
    try {
      const ta = createTaskAssignment({
        from: "visit_orchestrator",
        to: "medication_reminder_draft",
        title: "verify dose against allergies",
        body: "patient is allergic to penicillin",
      });
      await mailbox.send({
        visit_id: "v1",
        from: "visit_orchestrator",
        to: "medication_reminder_draft",
        payload: ta,
        color: "blue",
      });
      const drained = await mailbox.drainUnread(
        "v1",
        "medication_reminder_draft",
      );
      expect(drained).toHaveLength(1);
      expect(drained[0]!.structured).not.toBeNull();
      expect(drained[0]!.structured!.type).toBe("task_assignment");
    } finally {
      await cleanup();
    }
  });

  test("DB mirror records each send", async () => {
    const { mailbox, mailboxRows, cleanup } = await setup();
    try {
      await mailbox.send({
        visit_id: "v1",
        from: "a",
        to: "b",
        payload: "x",
      });
      await mailbox.send({
        visit_id: "v1",
        from: "a",
        to: "b",
        payload: "y",
      });
      // Async fire-and-forget — give microtasks a chance.
      await new Promise((r) => setTimeout(r, 50));
      expect(mailboxRows).toHaveLength(2);
      expect(mailboxRows[0]!.recipientRole).toBe("b");
      expect(mailboxRows[0]!.fileIndex).toBe(0);
      expect(mailboxRows[1]!.fileIndex).toBe(1);
    } finally {
      await cleanup();
    }
  });
});

describe("CLARIOSE_V01 §3 — Blackboard", () => {
  test("write emits blackboard_updated and read returns latest", async () => {
    const { blackboard, bus, cleanup } = await setup();
    try {
      const events: any[] = [];
      bus.streamForVisit("v1").subscribe((e) => events.push(e));

      const w1 = await blackboard.write({
        visit_id: "v1",
        key: "allergies",
        value: ["penicillin"],
        writtenBy: "medical_instruction_extractor",
      });
      expect(w1.version).toBe(1);

      const w2 = await blackboard.write({
        visit_id: "v1",
        key: "allergies",
        value: ["penicillin", "sulfa"],
        writtenBy: "medical_instruction_extractor",
      });
      expect(w2.version).toBe(2);

      // Allow microtask for bus delivery.
      await new Promise((r) => setTimeout(r, 10));
      const bbEvents = events.filter((e) => e.type === "blackboard_updated");
      expect(bbEvents).toHaveLength(2);
      expect(bbEvents[1].version).toBe(2);

      const r = await blackboard.read("v1", "allergies");
      expect(r?.value).toEqual(["penicillin", "sulfa"]);
      expect(r?.version).toBe(2);
    } finally {
      await cleanup();
    }
  });

  test("readMany returns subset; missing keys omitted", async () => {
    const { blackboard, cleanup } = await setup();
    try {
      await blackboard.write({
        visit_id: "v1",
        key: "allergies",
        value: ["p"],
        writtenBy: "x",
      });
      await blackboard.write({
        visit_id: "v1",
        key: "medication_plan_draft",
        value: { drug: "amoxicillin" },
        writtenBy: "y",
      });
      const subset = await blackboard.readMany("v1", [
        "allergies",
        "medication_plan_draft",
        "nonexistent",
      ]);
      expect(Object.keys(subset).sort()).toEqual([
        "allergies",
        "medication_plan_draft",
      ]);
    } finally {
      await cleanup();
    }
  });
});

describe("CLARIOSE_V01 §9 — SubscriptionRegistry on-demand triggers", () => {
  test("blackboard write fires subscribed role; respects writtenBy filter", async () => {
    const { blackboard, subs, cleanup } = await setup();
    try {
      const fired: TriggerContext[] = [];
      subs.start(async (ctx) => { fired.push(ctx); });
      subs.register({
        role: "medication_reminder_draft" as any,
        onBlackboardKeys: ["allergies"],
      });

      // Write from another role → should fire.
      await blackboard.write({
        visit_id: "v1",
        key: "allergies",
        value: ["p"],
        writtenBy: "medical_instruction_extractor",
      });
      await new Promise((r) => setTimeout(r, 50));
      expect(fired).toHaveLength(1);
      expect(fired[0]!.role).toBe("medication_reminder_draft");

      // Write FROM the subscribed role itself → should NOT fire (no self-bounce).
      await new Promise((r) => setTimeout(r, 2100)); // clear cooldown
      await blackboard.write({
        visit_id: "v1",
        key: "allergies",
        value: ["p", "s"],
        writtenBy: "medication_reminder_draft",
      });
      await new Promise((r) => setTimeout(r, 50));
      expect(fired).toHaveLength(1); // still 1
    } finally {
      await cleanup();
    }
  });

  test("cooldown blocks rapid re-fire of the same (visit, role)", async () => {
    const { blackboard, subs, cleanup } = await setup();
    try {
      const fired: TriggerContext[] = [];
      subs.start(async (ctx) => { fired.push(ctx); });
      subs.register({
        role: "safety_clarification" as any,
        onBlackboardKeys: ["safety_flags"],
      });

      for (let i = 0; i < 3; i++) {
        await blackboard.write({
          visit_id: "v1",
          key: "safety_flags",
          value: [{ id: i }],
          writtenBy: "compliance_guardrail",
        });
      }
      await new Promise((r) => setTimeout(r, 80));
      // Within the 2s cooldown window, only the first should land.
      expect(fired).toHaveLength(1);
    } finally {
      await cleanup();
    }
  });

  test("blackboardKeysFor returns the registered keys for the run-manager", async () => {
    const { subs, cleanup } = await setup();
    try {
      subs.register({
        role: "medication_reminder_draft" as any,
        onBlackboardKeys: ["allergies", "medication_plan_draft"],
      });
      const keys = subs.blackboardKeysFor("medication_reminder_draft" as any);
      expect(keys).toEqual(["allergies", "medication_plan_draft"]);
      // Unknown role → empty.
      expect(subs.blackboardKeysFor("nonexistent" as any)).toEqual([]);
    } finally {
      await cleanup();
    }
  });
});
