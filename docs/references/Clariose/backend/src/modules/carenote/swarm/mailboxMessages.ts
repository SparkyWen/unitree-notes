// CLARIOSE_V01 §3 Layer 1 — typed mailbox protocol.
//
// Ported from Qagent swarm/mailbox-messages.ts. Each structured message is
// JSON-stringified into the TeammateMessage.text field; recipient-side
// detectors parse it back. Free-form text is allowed and treated as opaque
// chat.
//
// We intentionally drop a few Qagent message types that don't apply to
// carenote yet (mode_set_request, team_permission_update, shutdown_*).
// They can be added later without touching this discriminator.

import { randomUUID } from "node:crypto";

import type { CodexAgentRole } from "../medical/medicalSchemas";

export const TEAMMATE_MESSAGE_TAG = "teammate_message";

/** The on-disk shape inside the inbox JSON array. The structured payload is
 *  JSON-encoded inside `text` — this lets us mix free-form chat with typed
 *  protocol messages without versioning the file format. */
export type TeammateMessage = {
  from: string;
  text: string;
  timestamp: string;
  read: boolean;
  /** UI hint (kept verbatim from Qagent). */
  color?: string;
  /** Short summary surfaced in the prompt's `<teammate_message summary>` attr. */
  summary?: string;
};

// ─── Structured payloads ─────────────────────────────────────────────────────

export type IdleNotificationMessage = {
  type: "idle_notification";
  from: string;
  timestamp: string;
  idleReason?: "available" | "interrupted" | "failed";
  summary?: string;
  completedTaskId?: string;
};

export type PermissionRequestMessage = {
  type: "permission_request";
  request_id: string;
  agent_id: string;
  tool_name: string;
  tool_use_id: string;
  description: string;
  input: Record<string, unknown>;
  permission_suggestions?: unknown[];
};

export type PermissionResponseMessage =
  | {
      type: "permission_response";
      request_id: string;
      behavior: "allow";
      updatedInput?: Record<string, unknown>;
    }
  | {
      type: "permission_response";
      request_id: string;
      behavior: "ask" | "deny";
      message?: string;
    };

export type PlanApprovalRequestMessage = {
  type: "plan_approval_request";
  request_id: string;
  from: string;
  plan: string;
  timestamp: string;
};

export type PlanApprovalResponseMessage = {
  type: "plan_approval_response";
  request_id: string;
  approved: boolean;
  comments?: string;
  timestamp: string;
};

export type TaskAssignmentMessage = {
  type: "task_assignment";
  task_id: string;
  from: string;
  to: string;
  title: string;
  body: string;
  timestamp: string;
};

export type TaskNotificationMessage = {
  type: "task_notification";
  task_id: string;
  from: string;
  status: "completed" | "failed" | "stopped";
  summary: string;
  timestamp: string;
};

export type RecallRequestMessage = {
  type: "recall_request";
  correlation_id: string;
  from: string;
  query: string;
  timestamp: string;
};

export type RecallResponseMessage = {
  type: "recall_response";
  correlation_id: string;
  to: string;
  results: Array<{ relPath: string; preview: string }>;
  timestamp: string;
};

export type StructuredMessage =
  | IdleNotificationMessage
  | PermissionRequestMessage
  | PermissionResponseMessage
  | PlanApprovalRequestMessage
  | PlanApprovalResponseMessage
  | TaskAssignmentMessage
  | TaskNotificationMessage
  | RecallRequestMessage
  | RecallResponseMessage;

// ─── Detectors ───────────────────────────────────────────────────────────────

export function tryParseStructured(text: string): StructuredMessage | null {
  if (!text || text[0] !== "{") return null;
  try {
    const obj = JSON.parse(text) as { type?: unknown };
    if (typeof obj.type !== "string") return null;
    return obj as StructuredMessage;
  } catch {
    return null;
  }
}

export function isStructuredProtocolMessage(text: string): boolean {
  return tryParseStructured(text) !== null;
}

export const isPermissionRequest = (text: string): PermissionRequestMessage | null => {
  const m = tryParseStructured(text);
  return m && m.type === "permission_request" ? m : null;
};

export const isPermissionResponse = (text: string): PermissionResponseMessage | null => {
  const m = tryParseStructured(text);
  return m && m.type === "permission_response" ? m : null;
};

export const isTaskAssignment = (text: string): TaskAssignmentMessage | null => {
  const m = tryParseStructured(text);
  return m && m.type === "task_assignment" ? m : null;
};

export const isPlanApprovalResponse = (
  text: string,
): PlanApprovalResponseMessage | null => {
  const m = tryParseStructured(text);
  return m && m.type === "plan_approval_response" ? m : null;
};

// ─── Constructors / utilities ────────────────────────────────────────────────

export function generateRequestId(prefix: string, seed?: string): string {
  return `${prefix}_${seed ? seed.slice(0, 8) + "_" : ""}${randomUUID().slice(0, 12)}`;
}

export function createTaskAssignment(args: {
  from: CodexAgentRole | string;
  to: CodexAgentRole | string;
  title: string;
  body: string;
}): TaskAssignmentMessage {
  return {
    type: "task_assignment",
    task_id: generateRequestId("task"),
    from: args.from,
    to: args.to,
    title: args.title,
    body: args.body,
    timestamp: new Date().toISOString(),
  };
}

export function createPermissionRequest(args: {
  agent_id: string;
  tool_name: string;
  tool_use_id: string;
  description: string;
  input: Record<string, unknown>;
}): PermissionRequestMessage {
  return {
    type: "permission_request",
    request_id: generateRequestId("perm", args.tool_use_id),
    agent_id: args.agent_id,
    tool_name: args.tool_name,
    tool_use_id: args.tool_use_id,
    description: args.description,
    input: args.input,
  };
}

// ─── Prompt-injection helper (verbatim shape from Qagent) ───────────────────

export function formatTeammateMessages(
  messages: Array<Pick<TeammateMessage, "from" | "text" | "color" | "summary">>,
): string {
  return messages
    .map((m) => {
      const attrs: string[] = [`teammate_id="${escapeAttr(m.from)}"`];
      if (m.color) attrs.push(`color="${escapeAttr(m.color)}"`);
      if (m.summary) attrs.push(`summary="${escapeAttr(m.summary)}"`);
      return `<${TEAMMATE_MESSAGE_TAG} ${attrs.join(" ")}>\n${m.text}\n</${TEAMMATE_MESSAGE_TAG}>`;
    })
    .join("\n\n");
}

function escapeAttr(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
