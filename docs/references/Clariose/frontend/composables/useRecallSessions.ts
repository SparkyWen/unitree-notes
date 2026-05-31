// Recall sessions composable — talks to /api/recall/sessions/*.

import { ref } from "vue";
import { useApi } from "./useApi";

export interface RecallSessionSummary {
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
}

export function useRecallSessions() {
  const api = useApi();
  const sessions = ref<RecallSessionSummary[]>([]);
  const loading = ref(false);

  async function refresh(): Promise<void> {
    loading.value = true;
    try {
      sessions.value = await api.get<RecallSessionSummary[]>("/recall/sessions");
    } finally {
      loading.value = false;
    }
  }

  async function newChat(): Promise<{ sessionId: string }> {
    const res = await api.post<{ sessionId: string }>("/recall/sessions/new", {});
    await refresh();
    return res;
  }

  async function resume(sessionId: string): Promise<void> {
    await api.post(`/recall/sessions/${encodeURIComponent(sessionId)}/resume`, {});
    await refresh();
  }

  async function readAny(sessionId: string): Promise<{ sessionId: string; messages: any[] }> {
    return api.get<{ sessionId: string; messages: any[] }>(
      `/recall/sessions/${encodeURIComponent(sessionId)}/messages`,
    );
  }

  return { sessions, loading, refresh, newChat, resume, readAny };
}
