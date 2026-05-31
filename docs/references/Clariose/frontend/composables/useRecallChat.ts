// Recall chat composable — drives the right-rail chat against the
// codex coordinator over SSE.
//
// Frontend ↔ backend contract (see backend/src/modules/recall-codex):
//   POST /api/recall/chat            { sessionId?, prompt }   → 202 { sessionId }
//   POST /api/recall/chat/abort      { sessionId }            → { aborted }
//   GET  /api/recall/chat/stream?token=<jwt>  ← EventSource
//
// SSE events: session_started | message_delta | tool_call | tool_result
//             | citation | usage | done | error

import { computed, ref } from "vue";
import { useApi } from "./useApi";

export type RecallChatStatus = "idle" | "running" | "completed" | "failed";

export interface RecallToolCall {
  command: string;
  exit?: number | null;
  snippet?: string;
  durationMs?: number;
}

export interface RecallCitation {
  relPath: string;
  startLine?: number;
  endLine?: number;
  excerpt?: string;
}

export interface RecallUsage {
  totalTokens?: number;
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  cacheCreationTokens?: number;
  cacheHitRate?: number | null;
  durationMs?: number;
}

export type RecallBlock =
  | { kind: "user";  id: string; text: string; at: string }
  | { kind: "assistant"; id: string; text: string; done: boolean; at: string; toolCalls: RecallToolCall[]; citations: RecallCitation[] }
  | { kind: "tool"; id: string; command: string; exit?: number | null; snippet?: string; at: string }
  | { kind: "system"; id: string; subtype: "info" | "error"; text: string; at: string };

export function useRecallChat() {
  const api = useApi();

  const status = ref<RecallChatStatus>("idle");
  const connected = ref(false);
  const blocks = ref<RecallBlock[]>([]);
  const usage = ref<RecallUsage | null>(null);
  const activeSessionId = ref<string | null>(null);

  let eventSource: EventSource | null = null;
  let assistantBlockId: string | null = null;

  function ensureAssistantBlock(): RecallBlock & { kind: "assistant" } {
    if (assistantBlockId) {
      const found = blocks.value.find((b) => b.id === assistantBlockId);
      if (found && found.kind === "assistant") return found;
    }
    const id = `a-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const block: RecallBlock = {
      kind: "assistant",
      id,
      text: "",
      done: false,
      at: new Date().toISOString(),
      toolCalls: [],
      citations: [],
    };
    blocks.value.push(block);
    assistantBlockId = id;
    return block as RecallBlock & { kind: "assistant" };
  }

  function pushSystem(subtype: "info" | "error", text: string): void {
    blocks.value.push({
      kind: "system",
      id: `sys-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      subtype,
      text,
      at: new Date().toISOString(),
    });
  }

  async function send(prompt: string): Promise<void> {
    blocks.value.push({
      kind: "user",
      id: `u-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      text: prompt,
      at: new Date().toISOString(),
    });
    assistantBlockId = null;
    status.value = "running";
    try {
      const res = await api.post<{ ok: boolean; sessionId: string }>(
        "/recall/chat",
        { sessionId: activeSessionId.value, prompt },
      );
      activeSessionId.value = res.sessionId;
    } catch (e: any) {
      status.value = "failed";
      pushSystem("error", e?.data?.message ?? e?.message ?? "send failed");
    }
  }

  async function abort(): Promise<void> {
    if (!activeSessionId.value) return;
    try {
      await api.post("/recall/chat/abort", { sessionId: activeSessionId.value });
    } catch { /* noop */ }
    status.value = "idle";
  }

  function reset(): void {
    blocks.value = [];
    usage.value = null;
    status.value = "idle";
    assistantBlockId = null;
    // Critical: drop the active session id too. Otherwise the next send()
    // posts the OLD sessionId in the body and the backend dutifully routes
    // the message back into the just-archived conversation. Callers that
    // know the new id (e.g. after sessionsApi.newChat()) should reassign
    // chat.activeSessionId.value immediately after reset() to avoid the
    // small race where send() runs before the next SSE attach tick.
    activeSessionId.value = null;
  }

  async function loadHistory(sessionId: string): Promise<void> {
    const data = await api.get<{
      sessionId: string;
      messages: { id: string; role: "user" | "assistant"; content: string; toolCalls?: RecallToolCall[]; usage?: RecallUsage; createdAt: string }[];
      citations: RecallCitation[];
    }>(`/recall/sessions/${encodeURIComponent(sessionId)}/messages`);
    activeSessionId.value = data.sessionId;
    blocks.value = [];
    assistantBlockId = null;
    for (const m of data.messages) {
      if (m.role === "user") {
        blocks.value.push({ kind: "user", id: m.id, text: m.content, at: m.createdAt });
      } else {
        blocks.value.push({
          kind: "assistant",
          id: m.id,
          text: m.content,
          done: true,
          at: m.createdAt,
          toolCalls: m.toolCalls ?? [],
          citations: data.citations ?? [],
        });
      }
    }
  }

  function connect(): void {
    disconnect();
    if (typeof window === "undefined") return;
    const token = api.token.value;
    if (!token) return;
    const cfg = useRuntimeConfig();
    const url = `${cfg.public.apiBase}/recall/chat/stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url, { withCredentials: true });
    eventSource = es;
    es.onopen = () => { connected.value = true; };
    es.onerror = () => { connected.value = false; };
    es.onmessage = (evt) => {
      try {
        const ev = JSON.parse(evt.data) as { type: string } & Record<string, any>;
        apply(ev);
      } catch { /* skip non-json */ }
    };
  }

  function disconnect(): void {
    if (eventSource) {
      try { eventSource.close(); } catch { /* ignore */ }
      eventSource = null;
    }
    connected.value = false;
  }

  function apply(e: { type: string } & Record<string, any>): void {
    switch (e.type) {
      case "ready":
      case "session_started":
        if (e.sessionId) activeSessionId.value = e.sessionId;
        return;
      case "message_delta": {
        const block = ensureAssistantBlock();
        block.text += String(e.delta ?? "");
        return;
      }
      case "tool_call":
        blocks.value.push({
          kind: "tool",
          id: `t-${Date.now()}-${blocks.value.length}`,
          command: String(e.command ?? ""),
          at: e.timestamp ?? new Date().toISOString(),
        });
        return;
      case "tool_result": {
        // Update the most-recent tool block matching this command.
        for (let i = blocks.value.length - 1; i >= 0; i--) {
          const b = blocks.value[i];
          if (b.kind === "tool" && b.command === String(e.command ?? "") && b.exit === undefined) {
            b.exit = (e.exit ?? null) as number | null;
            b.snippet = String(e.snippet ?? "");
            return;
          }
        }
        return;
      }
      case "citation": {
        const block = ensureAssistantBlock();
        block.citations.push({
          relPath: String(e.relPath ?? ""),
          startLine: typeof e.startLine === "number" ? e.startLine : undefined,
          endLine: typeof e.endLine === "number" ? e.endLine : undefined,
          excerpt: typeof e.excerpt === "string" ? e.excerpt : undefined,
        });
        return;
      }
      case "usage":
        usage.value = {
          totalTokens: e.totalTokens,
          cacheHitRate: e.cacheHitRate,
          durationMs: e.durationMs,
        };
        return;
      case "done": {
        const block = ensureAssistantBlock();
        block.done = true;
        status.value = "completed";
        assistantBlockId = null;
        return;
      }
      case "error":
        status.value = "failed";
        pushSystem("error", String(e.message ?? "unknown error"));
        return;
    }
  }

  return {
    status: computed(() => status.value),
    connected: computed(() => connected.value),
    blocks,
    usage,
    activeSessionId,
    send,
    abort,
    reset,
    connect,
    disconnect,
    loadHistory,
  };
}
