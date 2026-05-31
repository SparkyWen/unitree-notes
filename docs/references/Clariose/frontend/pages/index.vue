<script setup lang="ts">
useReveal();
useHead({ title: 'Clariose — Clarity after care.' });
</script>

<template>
  <div class="relative">
    <!-- ───────── Hero ─────────────────────────────────────────────── -->
    <section class="relative overflow-hidden">
      <div class="paper-grain" />
      <div aria-hidden="true" class="pointer-events-none absolute inset-0 -z-10">
        <div class="absolute -top-40 left-1/2 h-[640px] w-[1100px] -translate-x-1/2 bg-rose-bloom" />
        <div class="absolute bottom-0 left-1/2 h-[420px] w-[680px] -translate-x-1/2 bg-sage-bloom" />
      </div>

      <div class="container-narrow flex min-h-[78vh] flex-col items-center justify-center pb-20 pt-20 text-center sm:pb-28 sm:pt-28">
        <div data-reveal class="flex flex-col items-center">
          <span class="mb-10 inline-flex items-center gap-2 rounded-full border border-line bg-paper/60 px-3 py-1 text-[10.5px] uppercase tracking-[0.24em] text-ink-500">
            <span class="relative flex h-1.5 w-1.5">
              <span class="absolute inline-flex h-full w-full animate-ring-pulse rounded-full bg-rose-500 opacity-70" />
              <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-rose-500" />
            </span>
            Clariose · clinical preview
          </span>

          <h1 class="display text-[56px] leading-[1.0] sm:text-[96px] lg:text-[120px]">
            Clarity<span class="text-rose-500">,</span>
            <span class="block">
              <em class="display-italic">after</em> care.
            </span>
          </h1>

          <p class="mt-8 max-w-[520px] text-[16px] leading-relaxed text-ink-500 sm:mt-10 sm:text-[17px]">
            An AI companion that listens with you, then quietly turns the visit into
            a record, a schedule, and a summary your family can actually read.
          </p>

          <div class="mt-10 flex flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-center">
            <NuxtLink to="/carenote" class="btn-primary !py-3.5 sm:!py-3">
              Begin a session
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                <path d="M5 12h14M13 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </NuxtLink>
            <NuxtLink to="/carenote" class="btn-ghost !py-3.5 sm:!py-3">
              See how it works
            </NuxtLink>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
