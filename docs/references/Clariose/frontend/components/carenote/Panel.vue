<template>
  <div class="rounded-md border border-neutral-200 bg-white p-4">
    <h3 class="text-sm font-semibold uppercase tracking-wide text-neutral-500">
      {{ title }}
    </h3>
    <div v-if="empty" class="mt-3 text-sm text-neutral-400">
      {{ emptyText ?? "Nothing here yet." }}
    </div>
    <div v-else class="mt-3">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ title: string; empty?: boolean; emptyText?: string }>();
</script>
