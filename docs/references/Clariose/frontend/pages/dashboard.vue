<script setup lang="ts">
useHead({ title: 'Overview — Clariose' });
useReveal();
const api = useApi();
const { user, ready, refresh } = useAuth();
onMounted(async () => { if (!ready.value) await refresh(); });

type SessionRow = {
  id: string;
  startedAt: string;
  durationSec: number;
  utteranceCount: number;
  reminderCount: number;
  doctorName: string | null;
  summary: string | null;
};
const { data: sessions, pending } = await useAsyncData<SessionRow[]>(
  'sessions',
  () => api.get<SessionRow[]>('/sessions'),
  { default: () => [] },
);

function fmtDur(sec: number) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s.toString().padStart(2, '0')}s`;
}
function fmtDate(s: string) {
  return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
function fmtTime(s: string) {
  return new Date(s).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

const totals = computed(() => {
  const list = sessions.value ?? [];
  const utt = list.reduce((a, x) => a + x.utteranceCount, 0);
  const rem = list.reduce((a, x) => a + x.reminderCount, 0);
  const avg = list.length ? Math.round(list.reduce((a, x) => a + x.durationSec, 0) / list.length) : 0;
  return {
    sessions: list.length,
    utterances: utt,
    reminders: rem,
    avgDur: list.length ? fmtDur(avg) : '—',
  };
});
</script>

<template>
  <div class="container-page py-10 sm:py-14">
    <!-- ───────── Header ───────────────────────────────────────────── -->
    <header class="mb-10 flex flex-col items-start justify-between gap-6 sm:mb-14 sm:flex-row sm:items-end" data-reveal>
      <div>
        <p class="eyebrow mb-3">Overview</p>
        <h1 class="display text-[40px] leading-[1.02] sm:text-[64px]">
          Hello<span v-if="user?.displayName">, {{ user.displayName.split(' ')[0] }}</span><span class="text-rose-500">.</span>
        </h1>
        <p class="mt-3 max-w-md text-[14px] text-ink-500">
          Your sessions, schedules, and digests — all in one quiet place.
        </p>
      </div>
      <NuxtLink to="/carenote" class="btn-primary !py-3">
        New consult
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
          <path d="M12 5v14M5 12h14" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </NuxtLink>
    </header>

    <!-- ───────── Stat strip — big numerals ────────────────────────── -->
    <dl class="mb-12 grid grid-cols-2 overflow-hidden rounded-3xl border border-line bg-paper sm:mb-14 sm:grid-cols-4">
      <div v-for="(s, i) in [
        { k: totals.sessions,   v: 'Sessions',   tone: 'rose'  },
        { k: totals.utterances, v: 'Utterances', tone: 'sage'  },
        { k: totals.reminders,  v: 'Reminders',  tone: 'amber' },
        { k: totals.avgDur,     v: 'Avg. visit', tone: 'ink'   },
      ]" :key="s.v"
        class="relative flex flex-col gap-3 p-6 sm:p-7"
        :class="i !== 0 ? 'border-l border-line sm:border-l' : ''">
        <span class="inline-flex h-1.5 w-1.5 rounded-full"
              :class="{
                'bg-rose-500':  s.tone === 'rose',
                'bg-sage-500':  s.tone === 'sage',
                'bg-amber-400': s.tone === 'amber',
                'bg-ink-700':   s.tone === 'ink',
              }" />
        <dt class="numeral text-[44px] sm:text-[56px]">{{ s.k }}</dt>
        <dd class="text-[11.5px] uppercase tracking-[0.20em] text-ink-500">{{ s.v }}</dd>
      </div>
    </dl>

    <!-- ───────── Sessions list ────────────────────────────────────── -->
    <section class="card overflow-hidden">
      <div class="flex items-center justify-between border-b border-line px-6 py-4 sm:px-8">
        <div class="flex items-center gap-3">
          <p class="eyebrow">Recent consultations</p>
          <span v-if="pending" class="font-mono text-[10.5px] uppercase tracking-[0.22em] text-ink-400">loading…</span>
        </div>
        <NuxtLink to="/carenote" class="text-[13px] text-ink-500 hover:text-rose-500">Add new →</NuxtLink>
      </div>

      <div v-if="!pending && sessions?.length" class="divide-y divide-line">
        <NuxtLink
          v-for="s in sessions" :key="s.id"
          :to="`/carenote/visit/${s.id}/summary`"
          class="group grid grid-cols-1 gap-4 px-6 py-5 transition hover:bg-canvas/60 sm:grid-cols-[120px,1fr,160px,140px,40px] sm:items-center sm:gap-6 sm:px-8">
          <div class="font-grotesk">
            <p class="text-[20px] font-medium text-ink-900">{{ fmtDate(s.startedAt) }}</p>
            <p class="text-[12px] text-ink-400">{{ fmtTime(s.startedAt) }}</p>
          </div>
          <div>
            <p class="text-[14.5px] font-medium text-ink-900">{{ s.doctorName || 'Unspecified clinician' }}</p>
            <p class="mt-1 text-[13px] text-ink-500 line-clamp-1">{{ s.summary || 'Open the session to review the digest.' }}</p>
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="chip-sage">{{ s.utteranceCount }} utt</span>
            <span class="chip-rose" v-if="s.reminderCount">{{ s.reminderCount }} rem</span>
          </div>
          <p class="font-mono text-[12px] uppercase tracking-[0.18em] text-ink-500">
            {{ fmtDur(s.durationSec) }}
          </p>
          <span class="hidden h-9 w-9 items-center justify-center rounded-full border border-line text-ink-500 transition group-hover:border-rose-300 group-hover:bg-rose-50 group-hover:text-rose-700 sm:inline-flex">
            <svg class="h-3.5 w-3.5 transition-transform duration-300 group-hover:translate-x-0.5"
                 viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M5 12h14M13 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
        </NuxtLink>
      </div>

      <div v-else-if="!pending" class="flex flex-col items-center px-6 py-20 text-center sm:px-8">
        <div class="mb-6 grid h-16 w-16 place-items-center rounded-full bg-rose-50 text-rose-500">
          <svg viewBox="0 0 24 24" class="h-7 w-7" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 5v14M5 12h14" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <p class="display text-[28px] sm:text-[40px]">A quiet start<span class="text-rose-500">.</span></p>
        <p class="mx-auto mt-3 max-w-sm text-[14px] text-ink-500">
          Your first consult will appear here with a transcript, drafts, and a digest.
        </p>
        <NuxtLink to="/carenote" class="btn-primary mt-7 !py-3">Begin a session</NuxtLink>
      </div>
    </section>
  </div>
</template>
