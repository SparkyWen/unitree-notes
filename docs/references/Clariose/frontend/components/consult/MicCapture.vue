<script setup lang="ts">
/**
 * MicCapture — the live capture orb. Tap to talk, tap to pause.
 */
const props = defineProps<{
  state: 'idle' | 'connecting' | 'listening' | 'paused' | 'error';
  level?: number;
}>();
const emit = defineEmits<{ (e: 'toggle'): void }>();

const label = computed(() => ({
  idle:       'Tap to begin',
  connecting: 'Connecting…',
  listening:  'Listening · tap to pause',
  paused:     'Paused · tap to resume',
  error:      'Mic error · tap to retry',
}[props.state]));

const ringScale = computed(() => 1 + Math.min(0.18, (props.level ?? 0) * 0.4));
</script>

<template>
  <div class="flex flex-col items-center gap-5">
    <button
      type="button"
      class="relative grid h-44 w-44 place-items-center rounded-full text-paper shadow-lifted transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-rose-500/30"
      :class="state === 'listening' ? 'bg-rose-500'
             : state === 'error' ? 'bg-amber-500'
             : 'bg-ink-900 hover:bg-ink-700'"
      :aria-pressed="state === 'listening'"
      :aria-label="label"
      @click="emit('toggle')">

      <span
        v-if="state === 'listening'"
        class="pointer-events-none absolute inset-0 rounded-full"
        style="box-shadow: 0 0 0 0 rgba(184, 80, 101, 0.45); animation: ringPulse 2.4s ease-out infinite;" />

      <span
        v-if="state === 'listening'"
        class="pointer-events-none absolute inset-0 rounded-full bg-rose-500/30 transition-transform duration-100"
        :style="{ transform: `scale(${ringScale})` }" />

      <svg v-if="state !== 'listening'" viewBox="0 0 24 24" class="h-9 w-9" fill="none" stroke="currentColor" stroke-width="1.6">
        <rect x="9" y="3" width="6" height="12" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke-linecap="round" />
      </svg>
      <svg v-else viewBox="0 0 24 24" class="h-9 w-9" fill="currentColor">
        <rect x="6"  y="5" width="4" height="14" rx="1" />
        <rect x="14" y="5" width="4" height="14" rx="1" />
      </svg>
    </button>

    <p class="font-mono text-[10.5px] uppercase tracking-[0.24em] text-ink-500">{{ label }}</p>
  </div>
</template>
