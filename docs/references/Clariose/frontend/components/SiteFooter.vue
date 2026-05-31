<script setup lang="ts">
// Fix the year on the server and propagate via useState payload so the
// client doesn't recompute `new Date().getFullYear()` after hydration.
// Without useState, a server in UTC and a client a few minutes either
// side of New Year would render different years and trigger Vue's
// "Hydration completed but contains mismatches" warning.
const year = useState<number>('clariose.footer.year', () => new Date().getFullYear());
</script>

<template>
  <footer class="border-t border-line bg-canvas">
    <div class="container-page py-14 sm:py-20">
      <!-- Slogan plate -->
      <div class="mb-12 flex flex-col items-start justify-between gap-6 border-b border-line pb-12 sm:flex-row sm:items-end sm:gap-10">
        <h3 class="display max-w-2xl text-[34px] leading-[1.04] sm:text-[52px]">
          Clarity
          <span class="display-italic text-rose-500">after</span>
          care.
        </h3>
        <div class="flex items-center gap-3">
          <NuxtLink to="/carenote" class="btn-rose !py-3">Begin a session</NuxtLink>
          <NuxtLink to="/register" class="btn-ghost !py-3">Create account</NuxtLink>
        </div>
      </div>

      <div class="grid gap-10 sm:grid-cols-2 lg:grid-cols-[1.6fr,1fr,1fr,1fr]">
        <div>
          <BrandMark size="lg" />
          <p class="mt-5 max-w-xs text-[13.5px] leading-relaxed text-ink-500">
            A quiet AI companion that turns every consultation into a clear record,
            gentle reminders, and a digest your family can actually read.
          </p>
        </div>

        <div>
          <p class="eyebrow mb-4">Product</p>
          <ul class="flex flex-col gap-2.5 text-[13.5px] text-ink-700">
            <li><NuxtLink to="/carenote"  class="hover:text-rose-500">Agents</NuxtLink></li>
            <li><NuxtLink to="/reminders" class="hover:text-rose-500">Reminders</NuxtLink></li>
            <li><NuxtLink to="/summary"   class="hover:text-rose-500">Family digest</NuxtLink></li>
            <li><NuxtLink to="/recall"    class="hover:text-rose-500">Recall</NuxtLink></li>
            <li><NuxtLink to="/dashboard" class="hover:text-rose-500">Dashboard</NuxtLink></li>
          </ul>
        </div>
        <div>
          <p class="eyebrow mb-4">Trust</p>
          <ul class="flex flex-col gap-2.5 text-[13.5px] text-ink-700">
            <li><a href="#" class="hover:text-rose-500">How agents work</a></li>
            <li><a href="#" class="hover:text-rose-500">Data &amp; privacy</a></li>
            <li><a href="#" class="hover:text-rose-500">Clinical disclaimer</a></li>
            <li><a href="#" class="hover:text-rose-500">Audit log</a></li>
          </ul>
        </div>
        <div>
          <p class="eyebrow mb-4">Company</p>
          <ul class="flex flex-col gap-2.5 text-[13.5px] text-ink-700">
            <li><a href="#" class="hover:text-rose-500">About</a></li>
            <li><a href="#" class="hover:text-rose-500">Contact</a></li>
            <li><a href="#" class="hover:text-rose-500">Status</a></li>
          </ul>
        </div>
      </div>

      <div class="mt-12 flex flex-col items-start justify-between gap-3 border-t border-line pt-6 text-[12px] text-ink-400 sm:flex-row sm:items-center">
        <p>© {{ year }} Clariose · An assistive layer, not a substitute for medical care.</p>
        <p class="font-mono uppercase tracking-[0.22em]">zai.gold</p>
      </div>
    </div>
  </footer>
</template>
