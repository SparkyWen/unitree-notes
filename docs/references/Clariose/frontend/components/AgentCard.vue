<script setup lang="ts">
defineProps<{
  index: string;
  title: string;
  body: string;
  badge?: string;
  tone?: 'clay' | 'sage' | 'amber' | 'ink';
}>();
</script>

<template>
  <div class="card-lift flex flex-col gap-5 p-7" data-reveal>
    <div class="flex items-center justify-between">
      <span class="font-mono text-[10.5px] uppercase tracking-[0.22em] text-ink-400">
        Agent · {{ index }}
      </span>
      <span v-if="badge"
            class="chip"
            :class="{
              'chip-clay':  tone === 'clay',
              'chip-sage':  tone === 'sage',
              'chip-amber': tone === 'amber',
            }">
        {{ badge }}
      </span>
    </div>
    <h3 class="display text-[24px] sm:text-[28px] leading-[1.05]">{{ title }}</h3>
    <p class="text-[14.5px] leading-relaxed text-ink-500">{{ body }}</p>
    <slot />
  </div>
</template>
