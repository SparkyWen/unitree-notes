<script setup lang="ts">
const props = defineProps<{ app?: boolean }>();
const { user, ready, refresh, logout } = useAuth();

onMounted(() => { if (!ready.value) refresh(); });

const open = ref(false);
const route = useRoute();
watch(() => route.fullPath, () => (open.value = false));

const links = computed(() => props.app
  ? [
      { to: '/dashboard', label: 'Overview' },
      { to: '/carenote',  label: 'Agents' },
      { to: '/reminders', label: 'Reminders' },
      { to: '/summary',   label: 'Family' },
      { to: '/recall',    label: 'Recall' },
    ]
  : [
      { to: '/#how',     label: 'How' },
      { to: '/carenote', label: 'Agents' },
      { to: '/#trust',   label: 'Trust' },
      { to: '/recall',   label: 'Recall' },
    ]);

const isActive = (to: string) => {
  if (to.startsWith('/#')) return false;
  return route.path === to || route.path.startsWith(`${to}/`);
};
</script>

<template>
  <header class="sticky top-0 z-40 border-b border-line bg-canvas/80 backdrop-blur-md">
    <div class="container-page flex h-16 items-center justify-between gap-6 sm:h-[68px]">
      <BrandMark />

      <nav class="hidden items-center gap-1 md:flex">
        <NuxtLink
          v-for="l in links"
          :key="l.to"
          :to="l.to"
          class="rounded-full px-3.5 py-1.5 text-[13px] transition"
          :class="isActive(l.to)
            ? 'bg-ink-900 text-canvas'
            : 'text-ink-500 hover:text-ink-900 hover:bg-paper/70'">
          {{ l.label }}
        </NuxtLink>
      </nav>

      <div class="hidden items-center gap-3 md:flex">
        <template v-if="user">
          <NuxtLink to="/dashboard" class="text-[13px] text-ink-700 transition hover:text-ink-900">
            {{ user.displayName?.split(' ')[0] || 'Account' }}
          </NuxtLink>
          <button class="btn-ghost !py-2 !px-4 text-[12.5px]" @click="logout">Sign out</button>
        </template>
        <template v-else>
          <NuxtLink to="/login" class="text-[13px] text-ink-500 transition hover:text-ink-900">Sign in</NuxtLink>
          <NuxtLink to="/carenote" class="btn-primary !py-2 !px-4 text-[12.5px]">
            Begin
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M5 12h14M13 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </NuxtLink>
        </template>
      </div>

      <button
        class="md:hidden inline-flex h-10 w-10 items-center justify-center rounded-full border border-line text-ink-700"
        :aria-expanded="open"
        aria-label="Toggle navigation"
        @click="open = !open">
        <svg v-if="!open" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75">
          <path d="M4 7h16M4 12h16M4 17h16" stroke-linecap="round" />
        </svg>
        <svg v-else viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75">
          <path d="M6 6l12 12M18 6L6 18" stroke-linecap="round" />
        </svg>
      </button>
    </div>

    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 -translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0">
      <div v-if="open" class="md:hidden border-t border-line bg-canvas/95 backdrop-blur">
        <nav class="container-page flex flex-col gap-1 py-3">
          <NuxtLink
            v-for="l in links"
            :key="l.to"
            :to="l.to"
            class="rounded-2xl px-3 py-3 text-[15px] text-ink-700 hover:bg-paper">
            {{ l.label }}
          </NuxtLink>
          <div class="mt-2 flex gap-2 px-3 pb-2">
            <template v-if="user">
              <button class="btn-ghost flex-1 !py-2.5 text-[13px]" @click="logout">Sign out</button>
            </template>
            <template v-else>
              <NuxtLink to="/login" class="btn-ghost flex-1 !py-2.5 text-[13px]">Sign in</NuxtLink>
              <NuxtLink to="/carenote" class="btn-primary flex-1 !py-2.5 text-[13px]">Begin</NuxtLink>
            </template>
          </div>
        </nav>
      </div>
    </Transition>
  </header>
</template>
