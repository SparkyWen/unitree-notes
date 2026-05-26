<script setup lang="ts">
import type { TeamSnapshot, TeamSnapshotAgent, TeamRunEvent, StreamState } from '~/composables/useTeam';
import { TEAM_STAGES } from '~/composables/useTeam';

const props = defineProps<{
  snapshot: TeamSnapshot | null;
  pulseAgentId?: string | null;
  /** Live SSE state — drives the online/offline pill. */
  streamState?: StreamState;
  /** True while the runner is mid-DAG. */
  runActive?: boolean;
  /** Capped, newest-first activity log. */
  timeline?: TeamRunEvent[];
  /** Last completed run duration (ms) — shown in the header. */
  lastRunDurationMs?: number | null;
  /** Wall-clock of the most recent /team poll — used to render "live" age. */
  lastRefreshAt?: number | null;
}>();

const stages = computed(() => {
  const agents = props.snapshot?.agents ?? [];
  const byStage = new Map<number, TeamSnapshotAgent[]>();
  for (const a of agents) {
    const list = byStage.get(a.stage) ?? [];
    list.push(a);
    byStage.set(a.stage, list);
  }
  // Always emit a row for every known stage so the panel doesn't "shrink"
  // before the first agent has fired.
  return TEAM_STAGES.map(s => ({
    stage: s.stage,
    label: s.label,
    agents: byStage.get(s.stage) ?? [],
  }));
});

/** The stage we should highlight as "currently running". */
const currentStage = computed<number | null>(() => {
  if (!props.runActive) return null;
  // First stage that still has any thinking agent.
  for (const r of stages.value) {
    if (r.agents.some(a => a.status === 'thinking')) return r.stage;
  }
  return null;
});

/** Aggregate the team's online/offline status as a single label. */
const teamPresence = computed<{ label: string; tone: 'live' | 'idle' | 'warn' | 'off' }>(() => {
  if (props.streamState === 'open' && props.runActive) return { label: 'live · running', tone: 'live' };
  if (props.streamState === 'open')                    return { label: 'live · standby', tone: 'live' };
  if (props.streamState === 'connecting')              return { label: 'connecting',     tone: 'warn' };
  if (props.streamState === 'error')                   return { label: 'reconnecting',   tone: 'warn' };
  if (props.streamState === 'closed')                  return { label: 'offline',        tone: 'off'  };
  return { label: 'idle', tone: 'idle' };
});

const presenceClass = computed(() => ({
  live: 'bg-sage-500',
  warn: 'bg-amber-400',
  off:  'bg-ink-300',
  idle: 'bg-ink-300',
}[teamPresence.value.tone]));

const counts = computed(() => {
  const a = props.snapshot?.agents ?? [];
  return {
    total:    a.length,
    ready:    a.filter(x => x.status === 'ready').length,
    thinking: a.filter(x => x.status === 'thinking').length,
    error:    a.filter(x => x.status === 'error').length,
    idle:     a.filter(x => x.status === 'idle').length,
  };
});

function statusColor(s: TeamSnapshotAgent['status']) {
  if (s === 'ready')    return 'text-sage-600';
  if (s === 'thinking') return 'text-rose-600 animate-pulse';
  if (s === 'error')    return 'text-amber-600';
  return 'text-ink-400';
}

function statusDotClass(s: TeamSnapshotAgent['status']) {
  if (s === 'ready')    return 'bg-sage-500';
  if (s === 'thinking') return 'bg-rose-500 animate-pulse';
  if (s === 'error')    return 'bg-amber-500';
  return 'bg-ink-300';
}

function toneRing(t: TeamSnapshotAgent['tone']) {
  return ({
    rose:  'bg-rose-500',
    clay:  'bg-rose-700',
    sage:  'bg-sage-500',
    amber: 'bg-amber-400',
    ink:   'bg-ink-700',
  } as const)[t];
}

function preview(a: TeamSnapshotAgent): string {
  const o: any = a.output;
  if (!o) return '';
  if (a.id === 'orchestrator')                  return o.summary || `readiness: ${o.readiness}`;
  if (a.id === 'transcript-verification')       return o.verifiedSummary || `${(o.lowConfidence||[]).length} flagged`;
  if (a.id === 'speaker-role')                  return `${(o.assignments||[]).length} assignments`;
  if (a.id === 'medical-instruction-extractor') return `${(o.medications||[]).length} med · ${(o.procedures||[]).length} proc · ${(o.lifestyle||[]).length} life`;
  if (a.id === 'clarification-question')        return (o.items?.[0]?.question) ?? `${(o.items||[]).length} questions`;
  if (a.id === 'medication-schedule-draft')     return `${(o.items||[]).length} reminders drafted`;
  if (a.id === 'caregiver-notification')        return o.summaryMd?.split('\n').filter(Boolean)[1]?.slice(0, 120) || 'digest ready';
  if (a.id === 'safety-guardrail')              return `${o.verdict || 'PASS'} · ${(o.issues||[]).length} issues`;
  return '';
}

function eventLabel(ev: TeamRunEvent): string {
  switch (ev.kind) {
    case 'run.started':            return 'run started';
    case 'run.finished':           return ev.data?.error ? `run failed · ${ev.data.error}`
                                          : ev.data?.reason ? `run skipped · ${ev.data.reason}`
                                          : 'run finished';
    case 'stage.started':          return `stage ${ev.stage} started`;
    case 'stage.finished':         return `stage ${ev.stage} done`;
    case 'agent.started':          return `${ev.agentId} thinking`;
    case 'agent.finished':         return `${ev.agentId} ready · ${ev.data?.latencyMs ?? '?'}ms`;
    case 'agent.failed':           return `${ev.agentId} failed · ${ev.data?.error ?? 'unknown'}`;
    case 'blackboard.write':       return `wrote ${ev.blackboardKey}`;
    case 'clarification.requested':return `clarification queued (${ev.data?.severity})`;
    default:                       return ev.kind;
  }
}

function eventDot(ev: TeamRunEvent): string {
  if (ev.kind === 'agent.finished' || ev.kind === 'run.finished' || ev.kind === 'stage.finished') return 'bg-sage-500';
  if (ev.kind === 'agent.started'  || ev.kind === 'run.started'  || ev.kind === 'stage.started')  return 'bg-rose-500';
  if (ev.kind === 'agent.failed')          return 'bg-amber-500';
  if (ev.kind === 'blackboard.write')      return 'bg-ink-500';
  if (ev.kind === 'clarification.requested') return 'bg-amber-400';
  return 'bg-ink-300';
}

function relativeTime(ts: number): string {
  const d = Math.max(0, Date.now() - ts);
  if (d < 1000) return 'just now';
  if (d < 60_000) return `${Math.floor(d / 1000)}s ago`;
  if (d < 3_600_000) return `${Math.floor(d / 60_000)}m ago`;
  return new Date(ts).toLocaleTimeString();
}

// Re-tick the "x ago" labels so the activity log stays fresh without waiting
// for the next event.
const tick = ref(0);
let ticker: any = null;
onMounted(() => { ticker = setInterval(() => tick.value++, 1000); });
onBeforeUnmount(() => { if (ticker) clearInterval(ticker); });
</script>

<template>
  <div class="card overflow-hidden">
    <!-- ─── Header: presence + counts + last-run duration ────────────────── -->
    <div class="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
      <div class="flex items-center gap-2">
        <span class="relative flex h-2 w-2">
          <span class="absolute inline-flex h-full w-full rounded-full opacity-60"
                :class="[presenceClass, teamPresence.tone === 'live' ? 'animate-ping' : '']" />
          <span class="relative inline-flex h-2 w-2 rounded-full" :class="presenceClass" />
        </span>
        <p class="eyebrow">8-agent team</p>
        <span class="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-500">
          · {{ teamPresence.label }}
        </span>
      </div>

      <div class="ml-auto flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.18em]">
        <span v-if="counts.thinking" class="rounded-full bg-rose-50 px-2 py-0.5 text-rose-700">
          ▷ {{ counts.thinking }} running
        </span>
        <span class="rounded-full bg-sage-50 px-2 py-0.5 text-sage-700">
          ✓ {{ counts.ready }} / {{ counts.total }}
        </span>
        <span v-if="counts.error" class="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700">
          ! {{ counts.error }} err
        </span>
        <span v-if="lastRunDurationMs" class="rounded-full border border-line px-2 py-0.5 text-ink-500">
          {{ (lastRunDurationMs/1000).toFixed(1) }}s last
        </span>
        <span class="text-ink-400">{{ snapshot?.manifest?.version || '—' }}</span>
      </div>
    </div>

    <!-- ─── Stage rows ───────────────────────────────────────────────────── -->
    <div class="flex flex-col">
      <div v-for="row in stages" :key="row.stage"
           class="border-b border-line/70 px-5 py-4 last:border-b-0 transition-colors"
           :class="currentStage === row.stage ? 'bg-rose-50/40' : ''">
        <div class="mb-3 flex items-center gap-3">
          <span class="font-mono text-[10.5px] uppercase tracking-[0.22em] text-ink-500">
            stage {{ row.stage }}
          </span>
          <span class="text-[12.5px] text-ink-700">{{ row.label }}</span>
          <span v-if="currentStage === row.stage"
                class="font-mono text-[10px] uppercase tracking-[0.18em] text-rose-600 animate-pulse">
            ● live
          </span>
          <span v-if="row.agents.length > 1"
                class="ml-auto font-mono text-[10px] uppercase tracking-[0.18em] text-rose-600">
            ∥ parallel · {{ row.agents.length }}
          </span>
        </div>

        <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="a in row.agents" :key="a.id"
               class="group relative flex flex-col gap-1.5 rounded-2xl border bg-paper p-3 transition"
               :class="[
                 a.status === 'ready' ? 'border-sage-200' :
                 a.status === 'thinking' ? 'border-rose-200 shadow-[0_0_0_3px_rgba(244,63,94,0.08)]' :
                 a.status === 'error' ? 'border-amber-300' : 'border-line opacity-90',
                 pulseAgentId === a.id ? 'ring-2 ring-rose-300' : '',
               ]">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span class="inline-block h-1.5 w-1.5 rounded-full" :class="toneRing(a.tone)" />
                <p class="text-[12.5px] font-medium text-ink-900">{{ a.displayName }}</p>
              </div>
              <span class="flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.18em]"
                    :class="statusColor(a.status)">
                <span class="inline-block h-1.5 w-1.5 rounded-full" :class="statusDotClass(a.status)" />
                {{ a.status }}
              </span>
            </div>

            <p v-if="preview(a)" class="text-[12px] leading-snug text-ink-600 line-clamp-2">
              {{ preview(a) }}
            </p>
            <p v-else-if="a.status === 'thinking'" class="text-[12px] italic text-rose-500">working…</p>
            <p v-else-if="a.status === 'error'" class="text-[12px] italic text-amber-600 line-clamp-2">
              {{ a.errorMessage || 'failed' }}
            </p>
            <p v-else class="text-[12px] italic text-ink-400">awaiting input</p>

            <div class="mt-1 flex flex-wrap items-center gap-1 text-[10px] text-ink-400">
              <span v-if="a.latencyMs" class="rounded-full border border-line px-1.5 py-0.5 font-mono">
                {{ a.latencyMs }}ms
              </span>
              <span v-for="r in a.reads" :key="'r-'+r"
                    class="rounded-full border border-line px-1.5 py-0.5 font-mono">↓ {{ r }}</span>
              <span v-for="w in a.writes" :key="'w-'+w"
                    class="rounded-full border border-sage-200 bg-sage-50 px-1.5 py-0.5 font-mono text-sage-700">↑ {{ w }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ─── Live activity timeline ───────────────────────────────────────── -->
    <details v-if="timeline?.length" class="group border-t border-line bg-paper-soft/50" open>
      <summary class="flex cursor-pointer items-center gap-2 px-5 py-2.5 text-[11px] font-mono uppercase tracking-[0.22em] text-ink-500">
        <span>activity</span>
        <span class="rounded-full bg-ink-50 px-1.5 py-0.5 text-[10px] text-ink-600">{{ timeline.length }}</span>
        <span class="ml-auto text-ink-400 group-open:rotate-90 transition-transform">›</span>
      </summary>
      <ul class="max-h-44 overflow-y-auto px-5 pb-3 pt-1">
        <li v-for="(ev, i) in timeline" :key="i+'-'+ev.ts"
            class="flex items-center gap-2 py-1 text-[11.5px] text-ink-600">
          <!-- key on tick so the relative time re-renders -->
          <span class="inline-block h-1.5 w-1.5 rounded-full" :class="eventDot(ev)" />
          <span class="flex-1 truncate">{{ eventLabel(ev) }}</span>
          <span :key="tick" class="font-mono text-[10px] text-ink-400">{{ relativeTime(ev.ts) }}</span>
        </li>
      </ul>
    </details>

    <div v-if="snapshot?.liveClarification" class="border-t border-amber-200 bg-amber-50 px-5 py-3 text-[12.5px] text-amber-700">
      <p class="font-mono uppercase tracking-[0.22em] text-[10px]">live clarification queued</p>
      <p class="mt-1">{{ snapshot.liveClarification.question }}</p>
    </div>
  </div>
</template>
