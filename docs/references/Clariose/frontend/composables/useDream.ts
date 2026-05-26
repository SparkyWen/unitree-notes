// Drives the dream sidebar + viewer:
//   - run / runVisit POSTs to /api/carenote/dream/run[/visit/:vid]
//   - subscribes to /api/carenote/dream/events SSE for progress
//   - reloads /tree on dream_completed; opens individual files via /file
//
// State is module-singleton: the recall page mounts three consumers
// (page itself, DreamSidebar, DreamViewer) and they MUST share one set
// of refs — otherwise clicking a file in the sidebar would not surface
// in the viewer, and SSE progress would only land in whichever consumer
// happened to call connect().
//
// Module-scoped state is safe here because /recall/** is `ssr: false`
// in nuxt.config.ts → this module never executes server-side.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §8.2.

import { computed, ref, type Ref, type ComputedRef } from "vue";
import { useApi } from "./useApi";

export type DreamStatus = "idle" | "running" | "success" | "failed";

export interface DreamProgressView {
  dreamId: string;
  phase: "orient" | "gather" | "consolidate" | "prune";
  pct: number;
  visitCount: number;
  note?: string;
}

export interface DreamRunSummary {
  id: string;
  scope: string;
  trigger: "manual_user" | "manual_visit" | "cron";
  status: "running" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  endedAt: string | null;
  visitCount: number;
  filesUpdated: number;
  errorMessage: string | null;
}

export interface DreamTreeNode {
  name: string;
  path: string;
  kind: "dir" | "file";
  children?: DreamTreeNode[];
  mtime?: string;
  bytes?: number;
  visitId?: string;
}

export interface DreamVisitOption {
  visitId: string;
  startedAt: string;
  endedAt: string;
  doctorName: string | null;
  summaryPreview: string | null;
  hasMemoryFile: boolean;
  utteranceCount: number;
  durationSec: number;
}

interface DreamState {
  status: Ref<DreamStatus>;
  current: Ref<DreamProgressView | null>;
  lastFinishedAt: Ref<string | null>;
  lastFilesUpdated: Ref<number>;
  lastError: Ref<string | null>;
  tree: Ref<DreamTreeNode[]>;
  treeRoot: Ref<string>;
  lastDreamedAt: Ref<string | null>;
  selectedPath: Ref<string | null>;
  selectedContent: Ref<string | null>;
  selectedMeta: Ref<{ mtime: string; bytes: number } | null>;
  viewerLoading: Ref<boolean>;
  viewerError: Ref<string | null>;
  runs: Ref<DreamRunSummary[]>;
  visits: Ref<DreamVisitOption[]>;
  eventSource: EventSource | null;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
}

let _state: DreamState | null = null;

function getState(): DreamState {
  if (_state) return _state;
  _state = {
    status: ref<DreamStatus>("idle"),
    current: ref<DreamProgressView | null>(null),
    lastFinishedAt: ref<string | null>(null),
    lastFilesUpdated: ref(0),
    lastError: ref<string | null>(null),
    tree: ref<DreamTreeNode[]>([]),
    treeRoot: ref<string>(""),
    lastDreamedAt: ref<string | null>(null),
    selectedPath: ref<string | null>(null),
    selectedContent: ref<string | null>(null),
    selectedMeta: ref<{ mtime: string; bytes: number } | null>(null),
    viewerLoading: ref(false),
    viewerError: ref<string | null>(null),
    runs: ref<DreamRunSummary[]>([]),
    visits: ref<DreamVisitOption[]>([]),
    eventSource: null,
    reconnectTimer: null,
  };
  return _state;
}

export interface UseDreamReturn {
  status: ComputedRef<DreamStatus>;
  current: ComputedRef<DreamProgressView | null>;
  lastFinishedAt: ComputedRef<string | null>;
  lastFilesUpdated: ComputedRef<number>;
  lastError: ComputedRef<string | null>;
  tree: ComputedRef<DreamTreeNode[]>;
  treeRoot: ComputedRef<string>;
  lastDreamedAt: ComputedRef<string | null>;
  runs: ComputedRef<DreamRunSummary[]>;
  visits: ComputedRef<DreamVisitOption[]>;
  selectedPath: ComputedRef<string | null>;
  selectedContent: ComputedRef<string | null>;
  selectedMeta: ComputedRef<{ mtime: string; bytes: number } | null>;
  viewerLoading: ComputedRef<boolean>;
  viewerError: ComputedRef<string | null>;
  run: () => Promise<void>;
  runVisit: (visitId: string) => Promise<void>;
  refreshTree: () => Promise<void>;
  refreshRuns: () => Promise<void>;
  refreshVisits: () => Promise<void>;
  openFile: (path: string) => Promise<void>;
  connect: () => void;
  disconnect: () => void;
}

export function useDream(): UseDreamReturn {
  const api = useApi();
  const config = useRuntimeConfig();
  const s = getState();

  async function refreshTree(): Promise<void> {
    try {
      const r = await api.get<{
        root: string;
        lastDreamedAt: string | null;
        nodes: DreamTreeNode[];
      }>("/carenote/dream/tree");
      s.tree.value = r.nodes;
      s.treeRoot.value = r.root;
      s.lastDreamedAt.value = r.lastDreamedAt;
    } catch (err) {
      // Silent — sidebar shows empty state on first load.
      s.lastError.value = (err as Error).message;
    }
  }

  async function refreshRuns(): Promise<void> {
    try {
      s.runs.value = await api.get<DreamRunSummary[]>("/carenote/dream/runs");
    } catch (err) {
      s.lastError.value = (err as Error).message;
    }
  }

  async function refreshVisits(): Promise<void> {
    try {
      s.visits.value = await api.get<DreamVisitOption[]>(
        "/carenote/dream/visits",
      );
    } catch (err) {
      // Silent — picker just stays empty if the backend can't list visits.
      s.lastError.value = (err as Error).message;
    }
  }

  async function openFile(path: string): Promise<void> {
    s.selectedPath.value = path;
    s.selectedContent.value = null;
    s.selectedMeta.value = null;
    s.viewerError.value = null;
    s.viewerLoading.value = true;
    try {
      const r = await api.get<{
        content: string;
        mtime: string;
        bytes: number;
      }>(`/carenote/dream/file?path=${encodeURIComponent(path)}`);
      s.selectedContent.value = r.content;
      s.selectedMeta.value = { mtime: r.mtime, bytes: r.bytes };
    } catch (err: any) {
      s.viewerError.value = err?.data?.reason ?? (err as Error).message;
    } finally {
      s.viewerLoading.value = false;
    }
  }

  async function run(): Promise<void> {
    s.lastError.value = null;
    try {
      const r = await api.post<{ dreamId: string }>("/carenote/dream/run");
      s.status.value = "running";
      s.current.value = {
        dreamId: r.dreamId,
        phase: "orient",
        pct: 0,
        visitCount: 0,
      };
    } catch (err: any) {
      s.status.value = "failed";
      s.lastError.value = err?.data?.reason ?? (err as Error).message;
    }
  }

  async function runVisit(visitId: string): Promise<void> {
    s.lastError.value = null;
    try {
      const r = await api.post<{ dreamId: string }>(
        `/carenote/dream/run/visit/${encodeURIComponent(visitId)}`,
      );
      s.status.value = "running";
      s.current.value = {
        dreamId: r.dreamId,
        phase: "orient",
        pct: 0,
        visitCount: 1,
      };
    } catch (err: any) {
      s.status.value = "failed";
      s.lastError.value = err?.data?.reason ?? (err as Error).message;
    }
  }

  function connect(): void {
    if (typeof window === "undefined") return;
    if (s.eventSource) return; // idempotent across all consumers
    const tok = api.token.value;
    if (!tok) return;
    const apiBase = config.public.apiBase ?? "/api";
    const url = `${apiBase}/carenote/dream/events?token=${encodeURIComponent(tok)}`;
    const es = new EventSource(url);
    s.eventSource = es;

    es.addEventListener("dream_started", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      s.status.value = "running";
      s.current.value = {
        dreamId: d.dreamId,
        phase: "orient",
        pct: 0,
        visitCount: d.visitCount,
      };
    });
    es.addEventListener("dream_progress", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      if (s.current.value && s.current.value.dreamId === d.dreamId) {
        s.current.value.phase = d.phase;
        s.current.value.pct = d.pct;
        s.current.value.note = d.note;
      } else {
        s.current.value = {
          dreamId: d.dreamId,
          phase: d.phase,
          pct: d.pct,
          visitCount: 0,
          note: d.note,
        };
        s.status.value = "running";
      }
    });
    es.addEventListener("dream_completed", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      s.status.value = "success";
      s.lastFinishedAt.value = new Date(d.at).toISOString();
      s.lastFilesUpdated.value = d.filesUpdated;
      s.current.value = null;
      void refreshTree();
      void refreshRuns();
      void refreshVisits();
      if (s.selectedPath.value) void openFile(s.selectedPath.value);
    });
    es.addEventListener("dream_failed", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      s.status.value = "failed";
      s.lastError.value = d.reason;
      s.current.value = null;
    });

    es.onerror = () => {
      es.close();
      s.eventSource = null;
      // Auto-reconnect after a short backoff. The page calls disconnect()
      // on unmount, which clears this timer, so we never reconnect after
      // the user leaves /recall.
      s.reconnectTimer = setTimeout(connect, 2_000);
    };
  }

  function disconnect(): void {
    if (s.reconnectTimer) {
      clearTimeout(s.reconnectTimer);
      s.reconnectTimer = null;
    }
    s.eventSource?.close();
    s.eventSource = null;
  }

  return {
    status: computed(() => s.status.value),
    current: computed(() => s.current.value),
    lastFinishedAt: computed(() => s.lastFinishedAt.value),
    lastFilesUpdated: computed(() => s.lastFilesUpdated.value),
    lastError: computed(() => s.lastError.value),
    tree: computed(() => s.tree.value),
    treeRoot: computed(() => s.treeRoot.value),
    lastDreamedAt: computed(() => s.lastDreamedAt.value),
    runs: computed(() => s.runs.value),
    visits: computed(() => s.visits.value),
    selectedPath: computed(() => s.selectedPath.value),
    selectedContent: computed(() => s.selectedContent.value),
    selectedMeta: computed(() => s.selectedMeta.value),
    viewerLoading: computed(() => s.viewerLoading.value),
    viewerError: computed(() => s.viewerError.value),
    run,
    runVisit,
    refreshTree,
    refreshRuns,
    refreshVisits,
    openFile,
    connect,
    disconnect,
  };
}
