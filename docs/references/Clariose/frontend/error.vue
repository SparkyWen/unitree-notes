<script setup lang="ts">
const props = defineProps<{ error: { statusCode: number; message: string } }>();
const handle = () => clearError({ redirect: '/' });
</script>

<template>
  <div class="flex min-h-screen flex-col bg-canvas">
    <SiteHeader />
    <main class="container-page flex flex-1 items-center justify-center py-32 text-center">
      <div data-reveal>
        <p class="font-mono text-[10.5px] uppercase tracking-[0.24em] text-ink-400 mb-5">Error · {{ error.statusCode }}</p>
        <h1 class="display text-[48px] leading-[1.02] sm:text-[80px]">
          A quiet <span class="display-italic text-rose-500">pause</span>.
        </h1>
        <p class="mx-auto mt-5 max-w-md text-[14.5px] text-ink-500">
          {{ error.message || 'The page you were looking for could not be found.' }}
        </p>
        <button class="btn-primary mt-10" @click="handle">Back to safety</button>
      </div>
    </main>
    <SiteFooter />
  </div>
</template>
