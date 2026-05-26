<script setup lang="ts">
defineProps<{ size?: 'sm' | 'md' | 'lg'; variant?: 'inline' | 'stacked' }>();
</script>

<template>
  <NuxtLink to="/" class="inline-flex items-center gap-2.5 group" aria-label="Clariose home">
    <span
      class="relative grid place-items-center rounded-full bg-ink-900 text-paper transition-colors duration-300 group-hover:bg-rose-500"
      :class="size === 'lg' ? 'h-9 w-9' : size === 'sm' ? 'h-5 w-5' : 'h-7 w-7'">
      <!-- Stylised "C" with a rose petal dot -->
      <svg
        viewBox="0 0 24 24" fill="none"
        :class="size === 'lg' ? 'h-[18px] w-[18px]' : size === 'sm' ? 'h-2.5 w-2.5' : 'h-3.5 w-3.5'">
        <path
          d="M17.5 6.8a7.5 7.5 0 1 0 0 10.4"
          stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="17.5" cy="12" r="2.1" fill="#B85065" />
      </svg>
    </span>
    <span class="flex flex-col leading-none">
      <span class="font-grotesk text-[15px] font-semibold tracking-[-0.01em] text-ink-900">
        Clariose<span class="text-rose-500">.</span>
      </span>
      <span
        v-if="size === 'lg'"
        class="mt-1.5 font-mono text-[10px] uppercase tracking-[0.24em] text-ink-400">
        clarity after care
      </span>
    </span>
  </NuxtLink>
</template>
