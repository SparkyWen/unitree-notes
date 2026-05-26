<script setup lang="ts">
useHead({ title: 'Reminders — Clariose' });
useReveal();
const api = useApi();

type Reminder = {
  id: string;
  title: string;
  drug: string | null;
  dose: string | null;
  cadence: string;
  startsOn: string;
  endsOn: string | null;
  channel: 'app' | 'sms' | 'email';
  status: 'scheduled' | 'paused' | 'done';
  nextFireAt: string | null;
};
const { data: reminders, pending, refresh } = await useAsyncData<Reminder[]>(
  'reminders',
  () => api.get<Reminder[]>('/reminders'),
  { default: () => [] },
);

async function setStatus(r: Reminder, status: Reminder['status']) {
  await api.patch(`/reminders/${r.id}`, { status });
  await refresh();
}

function fmtDate(s: string | null) {
  return s ? new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
}

const grouped = computed(() => {
  const list = reminders.value ?? [];
  return {
    scheduled: list.filter(r => r.status === 'scheduled'),
    paused:    list.filter(r => r.status === 'paused'),
    done:      list.filter(r => r.status === 'done'),
  };
});

const summary = computed(() => ({
  scheduled: grouped.value.scheduled.length,
  paused:    grouped.value.paused.length,
  done:      grouped.value.done.length,
}));
</script>

<template>
  <div class="container-page py-10 sm:py-14">
    <header class="mb-10 flex flex-col items-start justify-between gap-6 sm:mb-14 sm:flex-row sm:items-end" data-reveal>
      <div>
        <p class="eyebrow mb-3">Schedule</p>
        <h1 class="display text-[40px] leading-[1.02] sm:text-[64px]">
          Quiet <span class="display-italic">reminders</span>.
        </h1>
        <p class="mt-4 max-w-md text-[14.5px] leading-relaxed text-ink-500">
          Each one came from something the doctor said.
        </p>
      </div>

      <!-- Status counters -->
      <dl class="grid grid-cols-3 gap-2 rounded-3xl border border-line bg-paper p-2 text-center">
        <div class="px-5 py-3">
          <dt class="numeral text-[24px] text-rose-500">{{ summary.scheduled }}</dt>
          <dd class="mt-1 text-[10.5px] uppercase tracking-[0.20em] text-ink-500">Active</dd>
        </div>
        <div class="border-x border-line px-5 py-3">
          <dt class="numeral text-[24px] text-ink-400">{{ summary.paused }}</dt>
          <dd class="mt-1 text-[10.5px] uppercase tracking-[0.20em] text-ink-500">Paused</dd>
        </div>
        <div class="px-5 py-3">
          <dt class="numeral text-[24px] text-sage-500">{{ summary.done }}</dt>
          <dd class="mt-1 text-[10.5px] uppercase tracking-[0.20em] text-ink-500">Done</dd>
        </div>
      </dl>
    </header>

    <div v-if="pending" class="card p-12 text-center text-[13px] text-ink-400">Loading reminders…</div>

    <div v-else-if="!reminders?.length" class="card flex flex-col items-center p-12 text-center" data-reveal>
      <div class="mb-6 grid h-16 w-16 place-items-center rounded-full bg-rose-50 text-rose-500">
        <svg viewBox="0 0 24 24" class="h-7 w-7" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 6v6l4 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </div>
      <p class="display text-[28px] sm:text-[36px]">Nothing scheduled<span class="text-rose-500">.</span></p>
      <p class="mx-auto mt-3 max-w-sm text-[14px] text-ink-500">
        After your next consult, accepted reminders will quietly land here.
      </p>
      <NuxtLink to="/carenote" class="btn-primary mt-7 !py-3">Begin a session</NuxtLink>
    </div>

    <ol v-else class="relative ml-3 border-l border-line pl-8" data-reveal>
      <li v-for="r in reminders" :key="r.id" class="relative pb-8 last:pb-0">
        <span class="absolute -left-[34px] top-2 grid h-7 w-7 place-items-center rounded-full border border-line bg-paper">
          <span class="h-2.5 w-2.5 rounded-full"
                :class="r.status === 'scheduled' ? 'bg-rose-500'
                       : r.status === 'done'      ? 'bg-sage-500'
                                                  : 'bg-ink-300'" />
        </span>
        <div class="card transition-shadow duration-300 hover:shadow-card">
          <div class="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-3">
                <h3 class="display text-[22px] leading-[1.08]">{{ r.title }}</h3>
                <span v-if="r.drug" class="chip-sage">{{ r.drug }}{{ r.dose ? ` · ${r.dose}` : '' }}</span>
                <span class="chip-ink">{{ r.channel }}</span>
              </div>
              <p class="mt-2 text-[13px] text-ink-500">
                {{ r.cadence }} · starts {{ fmtDate(r.startsOn) }}
                <span v-if="r.endsOn"> · ends {{ fmtDate(r.endsOn) }}</span>
              </p>
              <p v-if="r.nextFireAt && r.status === 'scheduled'"
                 class="mt-1 font-mono text-[10.5px] uppercase tracking-[0.22em] text-rose-600">
                Next · {{ fmtDate(r.nextFireAt) }}
              </p>
            </div>
            <div class="flex items-center gap-2">
              <button v-if="r.status === 'scheduled'" class="btn-ghost !py-2 !px-4 text-[12px]" @click="setStatus(r, 'paused')">Pause</button>
              <button v-else-if="r.status === 'paused'" class="btn-ghost !py-2 !px-4 text-[12px]" @click="setStatus(r, 'scheduled')">Resume</button>
              <button class="btn-ghost !py-2 !px-4 text-[12px]" @click="setStatus(r, 'done')">Done</button>
            </div>
          </div>
        </div>
      </li>
    </ol>
  </div>
</template>
