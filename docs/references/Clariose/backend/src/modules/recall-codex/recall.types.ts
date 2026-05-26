// recall-codex — public type surface. Most types are re-exported from the
// generated Prisma client; the rest model the SSE event stream and the
// JSON shape the Phase-1/Phase-2 codex agents must return.

import type { NoteKind } from "./recall.constants";

// ─── REST views (mirror Qagent / Zai frontend expectations) ───────────────

export type RecallNoteView = {
  slug: string;
  filename: string;
  title: string;
  type: string | null;
  description: string | null;
  tags: string[];
  bytes: number;
  mtime: string;
  pinned: boolean;
  collection: string | null;
  kind: NoteKind;
};

export type RecallSessionSummary = {
  sessionId: string;
  mtimeMs: number;
  bytes: number;
  messageCount: number;
  firstPrompt: string | null;
  cwd: string | null;
  projectLabel: string | null;
  own: boolean;
  resumable: boolean;
  active: boolean;
};

export type RecallMessageView = {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: RecallToolCall[];
  usage?: RecallUsage;
  createdAt: string;
};

export type RecallToolCall = {
  command: string;
  exit?: number | null;
  snippet?: string;
  durationMs?: number;
};

export type RecallUsage = {
  totalTokens?: number;
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  cacheCreationTokens?: number;
  cacheHitRate?: number | null;
  durationMs?: number;
};

export type RecallCitationView = {
  relPath: string;
  startLine?: number;
  endLine?: number;
  excerpt?: string;
};

// ─── SSE event stream ─────────────────────────────────────────────────────

export type RecallSseEvent =
  | { type: "session_started"; sessionId: string; codexThreadId: string | null; timestamp: string }
  | { type: "message_delta"; sessionId: string; delta: string; timestamp: string }
  | { type: "tool_call"; sessionId: string; command: string; timestamp: string }
  | { type: "tool_result"; sessionId: string; command: string; exit: number | null; snippet: string; timestamp: string }
  | { type: "citation"; sessionId: string; relPath: string; startLine?: number; endLine?: number; excerpt?: string; timestamp: string }
  | { type: "usage"; sessionId: string; totalTokens?: number; cacheHitRate?: number | null; durationMs?: number; timestamp: string }
  | { type: "done"; sessionId: string; messageId: string; timestamp: string }
  | { type: "error"; sessionId: string; code: string; message: string; timestamp: string };

// ─── Phase-1 agent JSON shape ─────────────────────────────────────────────

export type Phase1Output = {
  raw_memory: string | null;
  rollout_summary: string | null;
  rollout_slug: string | null;
};

// ─── Phase-2 inputs / outputs ────────────────────────────────────────────

export type Phase2SelectedJob = {
  jobId: string;
  rolloutSlug: string | null;
  rolloutSummary: string | null;
  rawMemory: string | null;
  generatedAt: string | null;
  usageCount: number;
};

// ─── DTOs (kept thin to avoid pulling class-validator into this file) ────

export type RecallChatStartRequest = {
  sessionId: string | null;
  prompt: string;
};

export type RecallChatAbortRequest = {
  sessionId: string;
};

export type RecallNoteUploadRequest = {
  files: { filename: string; content: string }[];
};

export type RecallNotePatchRequest = {
  pinned?: boolean;
  collection?: string | null;
  type?: string | null;
  tags?: string[];
  description?: string | null;
  title?: string;
};
