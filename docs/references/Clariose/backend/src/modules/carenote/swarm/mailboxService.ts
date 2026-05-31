// CLARIOSE_V01 §3 Layer 1 / §7.3 — file (source of truth) + DB mirror.
//
// Write path:
//   1. Acquire file lock, append to <root>/<visit>/inboxes/<role>.json
//   2. Insert mirror row into CarenoteMailbox (best-effort; non-fatal on fail)
//   3. Emit `mailbox_message` to EventBus for SSE / on-demand triggers
//
// Read path:
//   - drainUnread(visit, role) reads from FILE (always authoritative) and
//     marks them read inside the same lock; the DB is updated to match
//     after the lock is released.

import { Injectable, Logger } from "@nestjs/common";

import { PrismaService } from "../../../common/prisma/prisma.service";
import { CarenoteEventBus } from "./eventBus";
import {
  TEAMMATE_MESSAGE_TAG,
  formatTeammateMessages,
  tryParseStructured,
  type StructuredMessage,
  type TeammateMessage,
} from "./mailboxMessages";
import { MailboxFileService } from "./mailboxFile";

export type AddressedMessage = {
  visit_id: string;
  /** Recipient role (one of the 11 carenote roles, or "visit_orchestrator"). */
  to: string;
  /** Sender role/identifier. */
  from: string;
  /** Either a free-text string, or a StructuredMessage that we'll JSON-encode
   *  into the wire `text` field for backward compat with Qagent's format. */
  payload: string | StructuredMessage;
  /** Optional UI hints. */
  color?: string;
  summary?: string;
};

@Injectable()
export class MailboxService {
  private readonly logger = new Logger("Mailbox");

  constructor(
    private readonly file: MailboxFileService,
    private readonly prisma: PrismaService,
    private readonly bus: CarenoteEventBus,
  ) {}

  /** Send one message. File is source of truth; DB mirror + bus emit are
   *  best-effort follow-ups so the caller never blocks on them. */
  async send(args: AddressedMessage): Promise<{ index: number }> {
    const text =
      typeof args.payload === "string" ? args.payload : JSON.stringify(args.payload);
    const message = {
      from: args.from,
      text,
      timestamp: new Date().toISOString(),
      color: args.color,
      summary: args.summary,
    };

    const index = await this.file.append(args.visit_id, args.to, message);

    // DB mirror — fire and forget.
    void this.prisma.carenoteMailbox
      .create({
        data: {
          visitId: args.visit_id,
          recipientRole: args.to,
          fromRole: args.from,
          payloadJson: text as unknown as object,
          isRead: false,
          fileIndex: index,
        },
      })
      .catch((err) =>
        this.logger.warn(`mailbox DB mirror failed: ${(err as Error).message}`),
      );

    // SSE / on-demand trigger emit.
    const kind =
      typeof args.payload === "string"
        ? "free_text"
        : (args.payload as StructuredMessage).type;
    this.bus.emit({
      type: "mailbox_message",
      visitId: args.visit_id,
      from: args.from,
      to: args.to,
      payloadKind: kind,
    });

    return { index };
  }

  /** Drain unread messages addressed to `role` for this visit. Returns the
   *  TeammateMessage list AND, where parseable, the structured payload. */
  async drainUnread(
    visit_id: string,
    role: string,
  ): Promise<
    Array<{
      from: string;
      text: string;
      timestamp: string;
      color?: string;
      summary?: string;
      structured: StructuredMessage | null;
      fileIndex: number;
    }>
  > {
    const drained = await this.file.drainUnread(visit_id, role);

    // Sync DB mirror — flip isRead = true for the mirrored rows. We use
    // (visitId, recipientRole, isRead=false) + ORDER BY fileIndex; this is
    // imprecise if a writer races, but we accept the slack in the demo.
    if (drained.length > 0) {
      void this.prisma.carenoteMailbox
        .updateMany({
          where: { visitId: visit_id, recipientRole: role, isRead: false },
          data: { isRead: true },
        })
        .catch((err) =>
          this.logger.warn(
            `mailbox DB drain mark-read failed: ${(err as Error).message}`,
          ),
        );
    }

    // Look back at the original file order so the index is stable.
    const all = await this.file.read(visit_id, role);
    const out: ReturnType<MailboxService["drainUnread"]> extends Promise<infer R>
      ? R
      : never = [];
    for (let i = 0; i < all.length; i++) {
      const m = all[i]!;
      if (!drained.some((d) => d.timestamp === m.timestamp && d.from === m.from)) continue;
      out.push({
        from: m.from,
        text: m.text,
        timestamp: m.timestamp,
        color: m.color,
        summary: m.summary,
        structured: tryParseStructured(m.text),
        fileIndex: i,
      });
    }
    return out;
  }

  /** Read-only inspection (no mark-as-read). Used by a future ops UI. */
  async list(visit_id: string, role: string): Promise<TeammateMessage[]> {
    return this.file.read(visit_id, role);
  }

  /** Re-export so callers can build the prompt block without re-importing
   *  mailboxMessages. */
  static formatForPrompt(
    msgs: Array<Pick<TeammateMessage, "from" | "text" | "color" | "summary">>,
  ): string {
    return formatTeammateMessages(msgs);
  }

  static get TAG(): string {
    return TEAMMATE_MESSAGE_TAG;
  }
}
