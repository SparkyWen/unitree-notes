<script setup lang="ts">
const route = useRoute();
const isApp = computed(() => route.path.startsWith('/dashboard') || route.path.startsWith('/carenote') || route.path.startsWith('/reminders') || route.path.startsWith('/summary') || route.path.startsWith('/recall'));
</script>

<template>
  <div class="flex min-h-screen flex-col bg-canvas">
    <SiteHeader :app="isApp" />
    <main class="flex-1">
      <slot />
    </main>
    <SiteFooter v-if="!isApp" />
  </div>
</template>
