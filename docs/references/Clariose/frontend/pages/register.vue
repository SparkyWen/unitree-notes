<script setup lang="ts">
useHead({ title: 'Create account — Clariose' });
useReveal();
const auth = useAuth();
const email = ref('');
const password = ref('');
const displayName = ref('');
const role = ref<'PATIENT' | 'CLINICIAN' | 'CARETAKER'>('PATIENT');
const error = ref<string | null>(null);
const loading = ref(false);

async function submit() {
  error.value = null;
  loading.value = true;
  try {
    await auth.register({
      email: email.value, password: password.value,
      displayName: displayName.value, role: role.value,
    });
    await navigateTo('/dashboard');
  } catch (e: any) {
    error.value = e?.data?.message || 'Could not create the account.';
  } finally {
    loading.value = false;
  }
}

const roleCopy: Record<typeof role.value, string> = {
  PATIENT:   'Patient',
  CLINICIAN: 'Clinician',
  CARETAKER: 'Caretaker',
};
</script>

<template>
  <div class="container-page py-10 sm:py-16">
    <div class="card overflow-hidden lg:grid lg:min-h-[680px] lg:grid-cols-[1fr,1.05fr]">
      <!-- Left form -->
      <div class="flex items-center justify-center bg-paper p-8 sm:p-12">
        <div class="w-full max-w-[420px]" data-reveal>
          <div class="mb-8">
            <p class="eyebrow mb-3">Create account</p>
            <h1 class="display text-[40px] leading-[1.02] sm:text-[48px]">
              A quieter clinic<span class="text-rose-500">.</span>
            </h1>
          </div>

          <form @submit.prevent="submit" class="flex flex-col gap-5">
            <div>
              <label class="label">Name</label>
              <input v-model="displayName" required autocomplete="name" class="input" placeholder="Mei Chen" />
            </div>
            <div>
              <label class="label">Email</label>
              <input v-model="email" type="email" required autocomplete="email" class="input" placeholder="you@example.com" />
            </div>
            <div>
              <label class="label">Password</label>
              <input v-model="password" type="password" required minlength="8" autocomplete="new-password" class="input" placeholder="At least 8 characters" />
            </div>

            <div>
              <label class="label">I am</label>
              <div class="grid grid-cols-3 gap-2">
                <button
                  v-for="r in ['PATIENT','CLINICIAN','CARETAKER'] as const"
                  :key="r" type="button"
                  class="rounded-2xl border px-3 py-3 text-[12.5px] uppercase tracking-[0.18em] transition"
                  :class="role === r
                    ? 'border-rose-500 bg-rose-50 text-rose-700'
                    : 'border-line bg-paper text-ink-500 hover:border-line-strong'"
                  @click="role = r">
                  {{ roleCopy[r] }}
                </button>
              </div>
            </div>

            <p v-if="error" class="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-[13px] text-amber-600">{{ error }}</p>

            <button class="btn-primary mt-2 w-full !py-3" :disabled="loading">
              {{ loading ? 'Creating…' : 'Create account' }}
              <svg v-if="!loading" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                <path d="M5 12h14M13 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </form>

          <p class="mt-8 text-[13px] text-ink-500">
            Already have one?
            <NuxtLink to="/login" class="text-ink-900 underline decoration-rose-500 underline-offset-4">Sign in</NuxtLink>.
          </p>
        </div>
      </div>

      <!-- Right poster -->
      <aside class="relative hidden flex-col justify-between p-12 lg:flex"
             style="background: linear-gradient(220deg, #F1F4EE 0%, #C2CFB5 45%, #5F7A4E 100%);">
        <div class="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.24em] text-sage-800">
          <span class="inline-flex h-1.5 w-1.5 rounded-full bg-sage-700" />
          Clariose · the team
        </div>
        <div data-reveal>
          <h2 class="display text-[56px] leading-[0.96] text-ink-900">
            Four small
            <span class="display-italic">listeners</span>
            for one room.
          </h2>
          <ul class="mt-8 grid max-w-xs gap-3 text-[13px] text-ink-700/85">
            <li class="flex items-center gap-3"><span class="h-1.5 w-1.5 rounded-full bg-ink-700" /> Reviewer · grounds every claim</li>
            <li class="flex items-center gap-3"><span class="h-1.5 w-1.5 rounded-full bg-sage-700" /> Medication · drafts a schedule</li>
            <li class="flex items-center gap-3"><span class="h-1.5 w-1.5 rounded-full bg-amber-400" /> Risk · asks the missing question</li>
            <li class="flex items-center gap-3"><span class="h-1.5 w-1.5 rounded-full bg-rose-500" /> Family · writes plain language</li>
          </ul>
        </div>
        <div class="font-mono text-[10.5px] uppercase tracking-[0.24em] text-sage-800/70">
          clarity after care
        </div>
      </aside>
    </div>
  </div>
</template>
