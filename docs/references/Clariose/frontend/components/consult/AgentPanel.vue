<script setup lang="ts">
type AgentStatus = 'idle' | 'thinking' | 'ready' | 'error';
defineProps<{
  title: string;
  badge: string;
  tone: 'rose' | 'clay' | 'sage' | 'amber' | 'ink';
  status: AgentStatus;
  description?: string;
}>();
</script>

<template>
  <div class="card flex h-full flex-col overflow-hidden">
    <div class="flex items-center justify-between border-b border-line px-5 py-3">
      <div class="flex items-center gap-2">
        <span class="inline-block h-1.5 w-1.5 rounded-full"
              :class="{
                'bg-rose-500':  tone === 'rose' || tone === 'clay',
                'bg-sage-500':  tone === 'sage',
                'bg-amber-400': tone === 'amber',
                'bg-ink-700':   tone === 'ink',
              }" />
        <p class="eyebrow">{{ badge }}</p>
      </div>
      <span
        class="font-mono text-[10.5px] uppercase tracking-[0.22em]"
        :class="status === 'ready' ? 'text-sage-600'
               : status === 'thinking' ? 'text-rose-600 animate-pulse'
               : status === 'error' ? 'text-amber-600'
               : 'text-ink-400'">
        · {{ status }}
      </span>
    </div>

    <div class="border-b border-line px-5 py-4">
      <h3 class="display text-[20px] leading-[1.1]">{{ title }}</h3>
      <p v-if="description" class="mt-2 text-[12.5px] leading-relaxed text-ink-500">{{ description }}</p>
    </div>

    <div class="flex-1 overflow-y-auto px-5 py-4">
      <slot>
        <p class="text-[12.5px] italic text-ink-400">Awaiting transcript…</p>
      </slot>
    </div>
  </div>
</template>
