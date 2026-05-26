<script setup lang="ts">
useHead({ title: 'Family digest — Clariose' });
useReveal();

// Family is a shortcut to the latest visit's shareable digest. The actual
// content lives on the carenote per-visit summary page; this route just
// redirects there so the nav entry stays meaningful after the v1.5 digest
// endpoint was retired.
const api = useApi();
type VisitListItem = { visit_id: string; started_at: string };
const { data: visits, pending } = await useAsyncData<VisitListItem[]>(
  'family-latest-visit',
  () => api.get<VisitListItem[]>('/visits'),
  { default: () => [] },
);

const latestVisitId = computed(() => visits.value?.[0]?.visit_id ?? null);

if (process.client) {
  watchEffect(() => {
    if (!pending.value && latestVisitId.value) {
      navigateTo(`/carenote/visit/${latestVisitId.value}/summary`, { replace: true });
    }
  });
}
</script>

<template>
  <div class="container-narrow py-10 sm:py-14">
    <header class="mb-10 sm:mb-14" data-reveal>
      <p class="eyebrow mb-3">Family digest</p>
      <h1 class="display text-[40px] leading-[1.02] sm:text-[64px]">
        For the people <span class="display-italic">who care</span>.
      </h1>
      <p class="mt-4 max-w-md text-[14.5px] leading-relaxed text-ink-500">
        Plain language. One page. Shareable.
      </p>
    </header>

    <div v-if="pending || latestVisitId" class="card p-12 text-center text-[13px] text-ink-400">
      Opening your latest digest…
    </div>

    <div v-else class="card flex flex-col items-center p-12 text-center" data-reveal>
      <div class="mb-6 grid h-16 w-16 place-items-center rounded-full bg-rose-50 text-rose-500">
        <svg viewBox="0 0 24 24" class="h-7 w-7" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M4 6h16M4 12h10M4 18h16" stroke-linecap="round" />
        </svg>
      </div>
      <p class="display text-[28px] sm:text-[36px]">Nothing yet<span class="text-rose-500">.</span></p>
      <p class="mx-auto mt-3 max-w-sm text-[14px] text-ink-500">
        After your first consult, a digest will be drafted here for review and sharing.
      </p>
      <NuxtLink to="/carenote" class="btn-primary mt-7 !py-3">Begin a session</NuxtLink>
    </div>
  </div>
</template>
