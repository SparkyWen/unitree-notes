/**
 * useTeam — owns the 8-agent TeamRunner state on the browser.
 *
 *   • Polls /sessions/:id/team every few seconds to refresh agent status.
 *   • Subscribes to the SSE stream so cards light up the moment an agent
 *     starts/finishes.
 *   • Keeps a small ring buffer of recent events so the UI can render a live
 *     activity timeline.
 *   • Exposes the `clarification.requested` event so the consult page can
 *     route a HIGH-severity question into the live gpt-realtime data
 *     channel (so the model asks the doctor in the room).
 */

export type TeamAgentId =
  | 'orchestrator'
  | 'transcript-verification'
  | 'speaker-role'
  | 'medical-instruction-extractor'
  | 'clarification-question'
  | 'medication-schedule-draft'
  | 'caregiver-notification'
  | 'safety-guardrail';

export type AgentStatus = 'idle' | 'thinking' | 'ready' | 'error';
export type StreamState = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

export interface TeamSnapshotAgent {
  id: TeamAgentId;
  displayName: string;
  tone: 'rose' | 'clay' | 'sage' | 'amber' | 'ink';
  stage: number;
  status: AgentStatus;
  reads: string[];
  writes: string[];
  output: any;
  errorMessage?: string;
  latencyMs?: number;
  finishedAt?: string;
}

export interface BlackboardEntry {
  key: string;
  value: unknown;
  writtenBy: string;
  writtenAt: number;
  version: number;
}

export interface TeamSnapshot {
  manifest: { name: string; version: string };
  agents: TeamSnapshotAgent[];
  blackboard: Record<string, BlackboardEntry>;
  lastRunAt?: string;
  liveClarification?: { question: string; severity: 'LOW' | 'MEDIUM' | 'HIGH'; askLive: boolean } | null;
}

export interface TeamRunEvent {
  ts: number;
  kind:
    | 'run.started' | 'stage.started' | 'agent.started' | 'agent.finished'
    | 'agent.failed' | 'blackboard.write' | 'stage.finished' | 'run.finished'
    | 'clarification.requested' | 'heartbeat';
  sessionId?: string;
  stage?: number;
  agentId?: TeamAgentId;
  agentRunId?: string;
  blackboardKey?: string;
  data?: any;
}

/**
 * Static spec — the manifest the backend ships at /team. Embedding it here
 * lets the panel render all 8 agents the moment the consult page mounts,
 * before any sessionId is minted. Keep in sync with `team/team.json`.
 */
export const TEAM_AGENTS: Array<Omit<TeamSnapshotAgent, 'status' | 'output' | 'reads' | 'writes'> & { reads: string[]; writes: string[] }> = [
  { id: 'orchestrator',                  displayName: 'Orchestrator',          tone: 'ink',   stage: 0, reads: ['transcript.raw'],                                                                    writes: ['orchestrator.plan'] },
  { id: 'transcript-verification',       displayName: 'Transcript verifier',   tone: 'rose',  stage: 1, reads: ['transcript.raw', 'orchestrator.plan'],                                               writes: ['transcript.verified', 'transcript.lowConfidence'] },
  { id: 'speaker-role',                  displayName: 'Speaker role',          tone: 'rose',  stage: 1, reads: ['transcript.raw', 'orchestrator.plan'],                                               writes: ['speakers.assignments'] },
  { id: 'medical-instruction-extractor', displayName: 'Instruction extractor', tone: 'clay',  stage: 2, reads: ['transcript.verified', 'speakers.assignments'],                                       writes: ['instructions.medications', 'instructions.procedures', 'instructions.lifestyle'] },
  { id: 'clarification-question',        displayName: 'Clarifications',        tone: 'amber', stage: 3, reads: ['instructions.medications', 'instructions.procedures', 'instructions.lifestyle'],    writes: ['questions.clarifications'] },
  { id: 'medication-schedule-draft',     displayName: 'Schedule drafter',      tone: 'sage',  stage: 3, reads: ['instructions.medications'],                                                          writes: ['schedule.reminders'] },
  { id: 'caregiver-notification',        displayName: 'Caregiver digest',      tone: 'sage',  stage: 3, reads: ['transcript.verified', 'instructions.medications', 'instructions.lifestyle'],        writes: ['caregiver.digest'] },
  { id: 'safety-guardrail',              displayName: 'Safety auditor',        tone: 'amber', stage: 4, reads: ['instructions.medications', 'questions.clarifications', 'schedule.reminders'],       writes: ['audit.issues'] },
];

export const TEAM_STAGES: Array<{ stage: number; label: string }> = [
  { stage: 0, label: 'Plan' },
  { stage: 1, label: 'Verify transcript' },
  { stage: 2, label: 'Extract instructions' },
  { stage: 3, label: 'Author artefacts' },
  { stage: 4, label: 'Safety audit' },
];

/** Build the empty-but-rendered placeholder snapshot used before sessionId. */
export function placeholderSnapshot(): TeamSnapshot {
  return {
    manifest: { name: 'clariose-consult-team', version: '—' },
    agents: TEAM_AGENTS.map(a => ({ ...a, status: 'idle', output: null })),
    blackboard: {},
    liveClarification: null,
  };
}

const MAX_TIMELINE = 40;

export function useTeam(sessionId: Ref<string | null>) {
  const api = useApi();
  const config = useRuntimeConfig();
  const token = useCookie<string | null>('clariose_token');

  const snapshot = ref<TeamSnapshot | null>(placeholderSnapshot());
  const lastEvent = ref<TeamRunEvent | null>(null);
  const onClarification = ref<((q: { question: string; severity: string }) => void) | null>(null);

  /** Live activity timeline — newest first, capped to MAX_TIMELINE. */
  const timeline = ref<TeamRunEvent[]>([]);
  /** SSE connection state — drives the "online/offline" indicator. */
  const streamState = ref<StreamState>('idle');
  /** True between run.started and run.finished. */
  const runActive = ref(false);
  /** Last completed run wall-clock duration (ms). */
  const lastRunDurationMs = ref<number | null>(null);
  /** Last refresh wall-clock — drives the polling indicator. */
  const lastRefreshAt = ref<number | null>(null);
  let runStartedAt = 0;

  let pollTimer: any = null;
  let es: EventSource | null = null;
  let stopWatch: (() => void) | null = null;

  async function refresh() {
    if (!sessionId.value) return;
    try {
      snapshot.value = await api.get<TeamSnapshot>(`/sessions/${sessionId.value}/team`);
      lastRefreshAt.value = Date.now();
    } catch { /* ignore — most likely 404 mid-mint */ }
  }

  async function trigger() {
    if (!sessionId.value) return;
    try {
      await api.post(`/sessions/${sessionId.value}/team/run`, {});
    } catch (err) {
      console.error('[team] trigger failed', err);
    }
  }

  function recordEvent(ev: TeamRunEvent) {
    lastEvent.value = ev;
    if (ev.kind === 'heartbeat') return;
    timeline.value = [ev, ...timeline.value].slice(0, MAX_TIMELINE);
    if (ev.kind === 'run.started')   { runActive.value = true;  runStartedAt = ev.ts; }
    if (ev.kind === 'run.finished')  { runActive.value = false; lastRunDurationMs.value = ev.ts - runStartedAt; }
  }

  function openStream() {
    if (!sessionId.value || !import.meta.client) return;
    closeStream();
    streamState.value = 'connecting';
    // EventSource cannot set headers, so we pass the JWT as a query param to
    // a dedicated SSE path. The backend's JwtStrategy already accepts
    // `?token=...` for SSE — see backend/src/modules/auth/jwt.strategy.ts.
    const base = config.public.apiBase as string;
    const sep = base.includes('?') ? '&' : '?';
    const t = token.value ? `${sep}token=${encodeURIComponent(token.value)}` : '';
    const url = `${base}/sessions/${sessionId.value}/team/stream${t}`;
    try {
      es = new EventSource(url, { withCredentials: true });
      es.onopen = () => { streamState.value = 'open'; };
      es.onmessage = e => {
        try {
          const ev = JSON.parse(e.data) as TeamRunEvent;
          recordEvent(ev);
          if (ev.kind === 'agent.finished' || ev.kind === 'agent.failed' || ev.kind === 'run.finished') {
            void refresh();
          }
          if (ev.kind === 'clarification.requested' && ev.data && onClarification.value) {
            onClarification.value(ev.data);
          }
        } catch { /* ignore malformed event */ }
      };
      es.onerror = () => {
        // EventSource will auto-reconnect; flip state so the UI shows the
        // gap. Polling keeps the cards fresh in the meantime.
        streamState.value = 'error';
      };
    } catch {
      streamState.value = 'error';
    }
  }

  function closeStream() {
    try { es?.close(); } catch {}
    es = null;
    streamState.value = 'closed';
  }

  function start() {
    refresh();
    openStream();
    pollTimer = setInterval(refresh, 4000);
    // If sessionId arrives later (the consult page mounts before the realtime
    // mint completes), kick the stream + a fresh refresh as soon as we have
    // it — otherwise the user waits up to 4s for the next poll tick.
    stopWatch = watch(sessionId, (v, prev) => {
      if (v && v !== prev) { refresh(); openStream(); }
    });
  }

  function stop() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (stopWatch) { stopWatch(); stopWatch = null; }
    closeStream();
    streamState.value = 'idle';
  }

  return {
    snapshot, lastEvent, onClarification, timeline,
    streamState, runActive, lastRunDurationMs, lastRefreshAt,
    refresh, trigger, start, stop,
  };
}
