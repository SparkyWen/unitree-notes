<template>
  <div class="mx-auto max-w-2xl px-4 py-12">
    <h1 class="text-3xl font-semibold">CareNote — Doctor visit recorder</h1>
    <p class="mt-3 text-neutral-600">
      A quiet, consent-gated assistant that listens to your doctor visit, extracts
      medication and follow-up details, and asks before saving anything.
    </p>

    <form class="mt-8 space-y-6" @submit.prevent="onStart">
      <div>
        <label class="block text-sm font-medium text-neutral-800">Language spoken at the visit</label>
        <p class="mt-1 text-xs text-neutral-500">
          What you and the doctor will speak. Used by the live transcription model.
        </p>
        <select v-model="language" class="mt-2 w-full rounded-md border border-neutral-300 bg-white px-3 py-2">
          <option value="en">English</option>
          <option value="zh">中文 / Chinese</option>
          <option value="mixed">Mixed Chinese / English</option>
        </select>
      </div>

      <div>
        <label class="block text-sm font-medium text-neutral-800">Show me results in</label>
        <p class="mt-1 text-xs text-neutral-500">
          The team recap, reminders and questions will be written in this language —
          even if the visit itself is spoken in another.
        </p>
        <select v-model="outputLanguage" class="mt-2 w-full rounded-md border border-neutral-300 bg-white px-3 py-2">
          <option value="en">English</option>
          <option value="zh">中文 / Chinese</option>
          <option value="mixed">Mixed Chinese / English</option>
        </select>
      </div>

      <label class="flex items-start gap-3 rounded-md border border-neutral-200 bg-neutral-50 p-4">
        <input v-model="consent" type="checkbox" class="mt-1 h-4 w-4" />
        <span class="text-sm text-neutral-700">
          I understand my voice will be transcribed in real time by OpenAI for the
          purpose of building a memory aid for this visit. Audio is not stored by
          default. Reminders and saved memories require my explicit confirmation.
        </span>
      </label>

      <label class="flex items-center gap-3 text-sm text-neutral-700">
        <input v-model="rawAudio" type="checkbox" class="h-4 w-4" />
        Save raw audio for this visit (optional, off by default)
      </label>

      <button
        type="submit"
        class="w-full rounded-md bg-neutral-900 px-4 py-3 text-white disabled:opacity-50"
        :disabled="!consent || starting"
      >
        {{ starting ? "Starting…" : "Start visit" }}
      </button>

      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    </form>
  </div>
</template>

<script setup lang="ts">
// CLARIOSE_V01: drop the localStorage guest user_id (was a horizontal-priv
// bug: any browser could pose as anyone). Use the JWT-authenticated user via
// useAuth(); kick to /login if not signed in.
const consent = ref(false);
const rawAudio = ref(false);
// Default to English on both axes — most caregivers in our pilot
// consume the recap in English even when the visit is multilingual.
const language = ref<"zh" | "en" | "mixed">("en");
const outputLanguage = ref<"zh" | "en" | "mixed">("en");
const starting = ref(false);
const error = ref<string | null>(null);

const carenote = useCareNote();
const auth = useAuth();
const router = useRouter();

onMounted(async () => {
  await auth.refresh();
  if (!auth.user.value) {
    await router.replace({ path: "/login", query: { redirect: "/carenote" } });
  }
});

async function onStart() {
  if (!consent.value) {
    error.value = "Consent is required.";
    return;
  }
  if (!auth.user.value) {
    await router.replace({ path: "/login", query: { redirect: "/carenote" } });
    return;
  }
  starting.value = true;
  error.value = null;
  try {
    // user_id is no longer sent — the backend takes it from the JWT subject.
    const { visit_id } = await carenote.createVisit({
      language: language.value,
      output_language: outputLanguage.value,
      consent_recorded: true,
      raw_audio_saved: rawAudio.value,
    });
    await router.push(`/carenote/visit/${visit_id}`);
  } catch (err: any) {
    error.value = err?.data?.message ?? err?.message ?? "Could not start visit.";
  } finally {
    starting.value = false;
  }
}
</script>
