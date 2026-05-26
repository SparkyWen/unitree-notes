<script setup lang="ts">
useHead({ title: 'Sign in — Clariose' });
useReveal();
const route = useRoute();
const auth = useAuth();
const email = ref('');
const password = ref('');
const error = ref<string | null>(null);
const loading = ref(false);

const notice = computed(() => (route.query.expired === '1'
  ? 'Your session has ended. Please sign in again.'
  : null));

async function submit() {
  error.value = null;
  loading.value = true;
  try {
    await auth.login(email.value, password.value);
    const target = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')
      ? route.query.redirect
      : '/dashboard';
    await navigateTo(target);
  } catch (e: any) {
    error.value = e?.data?.message || 'Could not sign in.';
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="container-page py-10 sm:py-16">
    <div class="card overflow-hidden lg:grid lg:min-h-[640px] lg:grid-cols-[1.05fr,1fr]">
      <!-- Left poster -->
      <aside class="relative hidden flex-col justify-between p-12 lg:flex"
             style="background: linear-gradient(160deg, #FBF1F1 0%, #F2DCDC 40%, #DA8E94 100%);">
        <div class="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.24em] text-rose-800">
          <span class="inline-flex h-1.5 w-1.5 rounded-full bg-rose-700" />
          Clariose · welcome back
        </div>
        <div data-reveal>
          <h2 class="display text-[56px] leading-[0.96] text-ink-900">
            The room
            <span class="display-italic">remembers</span>
            with you.
          </h2>
          <p class="mt-6 max-w-sm text-[14.5px] leading-relaxed text-ink-700/80">
            Your sessions, schedules, and family digests — exactly as you left them.
          </p>
        </div>
        <div class="font-mono text-[10.5px] uppercase tracking-[0.24em] text-rose-800/70">
          clarity after care
        </div>
      </aside>

      <!-- Right form -->
      <div class="flex items-center justify-center bg-paper p-8 sm:p-12">
        <div class="w-full max-w-[380px]" data-reveal>
          <div class="mb-9">
            <p class="eyebrow mb-3">Sign in</p>
            <h1 class="display text-[40px] leading-[1.02] sm:text-[48px]">
              Welcome back<span class="text-rose-500">.</span>
            </h1>
          </div>

          <form @submit.prevent="submit" class="flex flex-col gap-5">
            <div>
              <label class="label">Email</label>
              <input v-model="email" type="email" required autocomplete="email" class="input" placeholder="you@example.com" />
            </div>
            <div>
              <div class="flex items-end justify-between">
                <label class="label">Password</label>
                <a href="#" class="text-[11px] text-ink-400 hover:text-ink-700">Forgot?</a>
              </div>
              <input v-model="password" type="password" required autocomplete="current-password" class="input" placeholder="••••••••" />
            </div>

            <p v-if="notice" class="rounded-2xl border border-rose-200 bg-rose-50 p-3 text-[13px] text-rose-700">{{ notice }}</p>
            <p v-if="error" class="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-[13px] text-amber-600">{{ error }}</p>

            <button class="btn-primary mt-2 w-full !py-3" :disabled="loading">
              {{ loading ? 'Signing in…' : 'Sign in' }}
              <svg v-if="!loading" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                <path d="M5 12h14M13 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </form>

          <p class="mt-8 text-[13px] text-ink-500">
            New here?
            <NuxtLink to="/register" class="text-ink-900 underline decoration-rose-500 underline-offset-4">Create an account</NuxtLink>.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
