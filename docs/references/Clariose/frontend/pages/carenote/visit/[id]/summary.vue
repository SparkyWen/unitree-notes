<template>
  <div class="mx-auto max-w-3xl px-4 py-8">
    <header class="flex items-center justify-between">
      <h1 class="text-xl font-semibold">Visit summary</h1>
      <div class="flex gap-2">
        <button
          class="rounded-md border border-neutral-300 px-3 py-1.5 text-sm"
          @click="copyFamilySummary"
        >
          Copy family summary
        </button>
        <button
          class="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700"
          @click="onDelete"
        >
          Delete visit data
        </button>
      </div>
    </header>

    <p v-if="!data" class="mt-6 text-sm text-neutral-500">Loading…</p>

    <template v-else>
      <!-- Team line-up + view toggle -->
      <div class="mt-2 flex items-center justify-between gap-3 rounded-2xl border border-line-soft bg-white/70 p-3">
        <div class="flex items-center gap-3">
          <div class="flex items-center -space-x-2">
            <AgentAvatar v-for="r in roleOrder" :key="r" :role="r" :size="40" />
          </div>
          <p class="text-xs text-ink-500">
            Your care team finished going through the visit.
          </p>
        </div>
        <button
          type="button"
          @click="showTeamDetail = !showTeamDetail"
          class="rounded-md border border-neutral-300 px-3 py-1.5 text-xs text-neutral-700 hover:bg-neutral-50"
          :title="showTeamDetail ? 'Collapse the helper drafts and show only the team summary, follow-ups, and the generated image' : 'Show every helper\'s draft and the cartoon avatars'"
        >
          {{ showTeamDetail ? "Hide team detail" : "Show team detail" }}
        </button>
      </div>

      <!-- Recap image + headline. The team's consolidated visual output —
           always visible (the user explicitly called this out). -->
      <section
        v-if="recaps.length"
        class="mt-4 space-y-4"
      >
        <article
          v-for="r in recaps"
          :key="(r.round_index ?? 0) + ':' + r.generated_at"
          class="overflow-hidden rounded-2xl border border-teal-100 bg-teal-50/30"
        >
          <div class="flex items-center justify-between gap-2 px-4 pt-3">
            <p class="text-[15px] font-semibold text-ink-900">{{ r.headline }}</p>
            <span class="text-[11px] text-ink-500">
              round {{ (r.round_index ?? 0) + 1 }}
            </span>
          </div>
          <div v-if="r.image_status === 'ready'" class="mt-3 border-t border-teal-100 bg-white">
            <img
              :src="recapImageSrc(r)"
              :alt="`Round ${(r.round_index ?? 0) + 1} infographic`"
              class="block w-full"
            />
          </div>
          <div v-else-if="r.image_status === 'failed'" class="mx-4 my-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
            Image generation failed: {{ r.image_error ?? "unknown error" }}. Text recap below is still accurate.
          </div>
          <div v-else class="mx-4 my-3 rounded-lg border border-line-soft bg-canvas/50 p-2 text-xs text-ink-500">
            Image step skipped (no OpenAI key).
          </div>
          <div v-if="r.must_ask?.length" class="px-4 pb-3 pt-3">
            <div class="text-[11px] font-semibold uppercase tracking-wide text-teal-700">Ask the doctor</div>
            <ul class="mt-1 space-y-1 text-sm">
              <li v-for="(q, i) in r.must_ask" :key="i" class="flex items-start gap-2">
                <span class="text-teal-700">?</span><span class="text-ink-800">{{ q }}</span>
              </li>
            </ul>
          </div>
        </article>
      </section>

      <!-- Storyteller summary stays visible in BOTH modes — it's the
           "team summary" the user explicitly wants in the minimal view. -->
      <div class="mt-6">
        <AgentPanel role="storyteller" :empty="!plainSummary" :tagline="storytellerTagline">
          <p class="text-[15px] leading-relaxed text-ink-800">{{ plainSummary }}</p>
          <p class="mt-3 text-[11px] text-ink-400">
            This is a memory aid, not medical advice. Please confirm anything important
            with your doctor or pharmacist.
          </p>
        </AgentPanel>
      </div>

      <!-- Inquirer (follow-up questions) also stays visible in minimal
           mode — same reason as above. The other helpers collapse with
           the toggle. -->
      <div v-if="!showTeamDetail" class="mt-4">
        <AgentPanel
          role="inquirer"
          :empty="!data.state.clarifying_questions.length"
          :count="data.state.clarifying_questions.length"
          :tagline="inquirerTagline"
        >
          <ul class="space-y-1.5 text-sm">
            <li v-for="q in data.state.clarifying_questions" :key="q.question_id" class="flex items-start gap-2">
              <span class="text-champagne-400">•</span>
              <span class="text-ink-800">{{ q.question }}</span>
            </li>
          </ul>
        </AgentPanel>
      </div>

      <section v-if="showTeamDetail" class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <AgentPanel
          role="pharmacist"
          :empty="!data.state.draft_reminders.length && !data.confirmed_tasks.length"
          :count="data.state.draft_reminders.length + data.confirmed_tasks.length"
          :tagline="pharmacistTagline"
        >
          <ul class="space-y-3">
            <li
              v-for="r in data.state.draft_reminders"
              :key="r.task_id"
              class="rounded-xl border border-rose-100 bg-rose-50/60 p-3 text-sm"
            >
              <div class="flex items-center gap-1.5 font-medium text-ink-800">
                <span>💊</span>{{ r.title }}
              </div>
              <div class="mt-0.5 text-ink-700">{{ r.description }}</div>
              <div v-if="r.blocking_missing_fields?.length" class="mt-1.5 rounded bg-amber-100/80 px-2 py-1 text-[11px] text-amber-800">
                missing: {{ r.blocking_missing_fields.join(", ") }}
              </div>
              <div class="mt-2 flex gap-2">
                <button class="rounded-full bg-ink-900 px-3 py-1 text-[11px] text-white hover:bg-ink-800" @click="confirmTask(r.task_id)">
                  Confirm reminder
                </button>
                <button class="rounded-full border border-line-strong px-3 py-1 text-[11px] text-ink-600 hover:bg-ink-50" @click="rejectTask(r.task_id)">
                  Reject
                </button>
              </div>
            </li>
            <li v-for="t in data.confirmed_tasks" :key="t.task_id" class="rounded-xl border border-sage-200 bg-sage-50/70 p-3 text-sm">
              <div class="flex items-center gap-1.5 font-medium text-sage-700">
                <span>✓</span>{{ t.title }}
              </div>
              <div class="text-ink-700">{{ t.description }}</div>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel
          role="coordinator"
          :empty="!followUpTasks.length"
          :count="followUpTasks.length"
          :tagline="coordinatorTagline"
        >
          <ul class="space-y-3">
            <li v-for="t in followUpTasks" :key="t.task_id" class="rounded-xl border border-line-soft bg-canvas/60 p-3 text-sm">
              <div class="font-medium text-ink-800">{{ t.title }}</div>
              <div class="text-ink-600">{{ t.description }}</div>
              <div class="mt-2 flex gap-2">
                <button class="rounded-full bg-ink-900 px-3 py-1 text-[11px] text-white hover:bg-ink-800" @click="confirmTask(t.task_id)">
                  Confirm task
                </button>
                <button class="rounded-full border border-line-strong px-3 py-1 text-[11px] text-ink-600 hover:bg-ink-50" @click="rejectTask(t.task_id)">
                  Reject
                </button>
              </div>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel
          role="inquirer"
          :empty="!data.state.clarifying_questions.length"
          :count="data.state.clarifying_questions.length"
          :tagline="inquirerTagline"
        >
          <ul class="space-y-1.5 text-sm">
            <li v-for="q in data.state.clarifying_questions" :key="q.question_id" class="flex items-start gap-2">
              <span class="text-champagne-400">•</span>
              <span class="text-ink-800">{{ q.question }}</span>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel role="messenger" :empty="!familySummary" :tagline="messengerTagline">
          <p class="whitespace-pre-wrap rounded-lg bg-sage-50/60 p-3 text-sm leading-relaxed text-ink-800">
            {{ familySummary }}
          </p>
        </AgentPanel>

        <AgentPanel
          role="memory"
          :empty="!data.state.memory_candidates.length"
          :count="data.state.memory_candidates.length"
          :tagline="memoryTagline"
        >
          <ul class="space-y-3">
            <li v-for="c in data.state.memory_candidates" :key="c.memory_candidate_id" class="rounded-xl border border-line-soft bg-canvas/60 p-3 text-sm">
              <div class="text-[10px] uppercase tracking-wide text-ink-400">{{ c.memory_type }}</div>
              <div class="mt-1 text-ink-800">{{ c.content }}</div>
              <div class="mt-2 flex gap-2">
                <button class="rounded-full bg-ink-900 px-3 py-1 text-[11px] text-white hover:bg-ink-800" @click="confirmMemory(c.memory_candidate_id)">
                  Save to memory
                </button>
                <button class="rounded-full border border-line-strong px-3 py-1 text-[11px] text-ink-600 hover:bg-ink-50" @click="rejectMemory(c.memory_candidate_id)">
                  Discard
                </button>
              </div>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel
          role="guardian"
          :empty="!data.state.safety_flags.length"
          :count="data.state.safety_flags.length"
          :tagline="guardianTagline"
        >
          <ul class="space-y-2 text-sm">
            <li v-for="s in data.state.safety_flags" :key="s.flag_id" class="rounded-xl border border-rose-200 bg-rose-50/70 p-3">
              <div class="flex items-center gap-1.5">
                <span>⚠️</span>
                <span class="text-[11px] font-semibold uppercase tracking-wide text-rose-700">
                  {{ s.flag_type }} · {{ s.severity }}
                </span>
              </div>
              <div class="mt-1 text-ink-800">{{ s.message }}</div>
              <div class="mt-1 text-[11px] text-ink-600">→ {{ s.recommended_user_action }}</div>
            </li>
          </ul>
        </AgentPanel>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { VisitFull, TeamRecap } from "~/composables/useCareNote";
import AgentAvatar, { type AgentRole } from "~/components/carenote/AgentAvatar.vue";
import AgentPanel from "~/components/carenote/AgentPanel.vue";

const roleOrder: AgentRole[] = [
  "storyteller",
  "pharmacist",
  "coordinator",
  "inquirer",
  "messenger",
  "memory",
  "guardian",
];

const route = useRoute();
const router = useRouter();
const visitId = computed(() => route.params.id as string);

const carenote = useCareNote();
const data = ref<VisitFull | null>(null);
const showTeamDetail = ref(true);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const recaps = computed<TeamRecap[]>(() => data.value?.team_recaps ?? []);

function recapImageSrc(r: TeamRecap): string {
  if (r.image_status !== "ready") return "";
  const ts = new Date(r.generated_at).getTime();
  const round = r.round_index;
  const roundQ = typeof round === "number" ? `&round=${round}` : "";
  // The native <img> can't send Authorization headers; the JWT strategy
  // also accepts ?token=, so we pass the cookie-stored token in the URL.
  const token = useCookie<string | null>("clariose_token").value ?? "";
  const tokQ = token ? `&token=${encodeURIComponent(token)}` : "";
  return `/api/visits/${visitId.value}/recap-image?v=${ts}${roundQ}${tokQ}`;
}

async function refresh() {
  try {
    data.value = await carenote.getVisit(visitId.value);
  } catch (err) {
    console.warn("[carenote] refresh failed", err);
  }
}

onMounted(() => {
  refresh();
  pollTimer = setInterval(refresh, 2000);
});

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
});

const plainSummary = computed(() => {
  if (!data.value) return "";
  const final = data.value.state.family_summary_final;
  if (final) return final;
  return data.value.state.family_summary_deltas.map((d) => d.text).join(" ");
});

const familySummary = computed(() => plainSummary.value);

const followUpTasks = computed(() =>
  (data.value?.state.draft_tasks ?? []).filter((t) => t.task_type !== "medication_reminder"),
);

// Per-agent taglines on the summary page — past-tense, since the team is done.
const storytellerTagline = computed(() =>
  plainSummary.value ? "Here's the visit, retold gently and clearly." : undefined,
);
const pharmacistTagline = computed(() => {
  const drafts = data.value?.state.draft_reminders.length ?? 0;
  const confirmed = data.value?.confirmed_tasks.length ?? 0;
  if (!drafts && !confirmed) return undefined;
  if (drafts && confirmed) return `${confirmed} confirmed, ${drafts} still need your nod.`;
  if (drafts) return `${drafts} reminder${drafts === 1 ? "" : "s"} ready for you to confirm.`;
  return `${confirmed} reminder${confirmed === 1 ? "" : "s"} confirmed — nicely done.`;
});
const coordinatorTagline = computed(() => {
  const n = followUpTasks.value.length;
  return n ? `${n} follow-up${n === 1 ? "" : "s"} for you to review.` : undefined;
});
const inquirerTagline = computed(() => {
  const n = data.value?.state.clarifying_questions.length ?? 0;
  return n ? `${n} question${n === 1 ? "" : "s"} for the next visit.` : undefined;
});
const messengerTagline = computed(() =>
  familySummary.value ? "Drafted a warm note for the family — yours to send." : undefined,
);
const memoryTagline = computed(() => {
  const n = data.value?.state.memory_candidates.length ?? 0;
  return n ? `${n} thing${n === 1 ? "" : "s"} worth remembering — your call.` : undefined;
});
const guardianTagline = computed(() => {
  const flags = data.value?.state.safety_flags ?? [];
  if (!flags.length) return undefined;
  const high = flags.filter((f: any) => f.severity === "high").length;
  return high
    ? `${high} high-severity flag${high === 1 ? "" : "s"} — please read.`
    : `${flags.length} thing${flags.length === 1 ? "" : "s"} to keep in mind.`;
});

async function confirmTask(taskId: string) {
  await carenote.confirmTask(visitId.value, taskId);
  await refresh();
}
async function rejectTask(taskId: string) {
  await carenote.rejectTask(visitId.value, taskId);
  await refresh();
}
async function confirmMemory(candidateId: string) {
  await carenote.confirmMemory(visitId.value, candidateId);
  await refresh();
}
async function rejectMemory(candidateId: string) {
  await carenote.rejectMemory(visitId.value, candidateId);
  await refresh();
}
async function copyFamilySummary() {
  if (!plainSummary.value) return;
  await navigator.clipboard.writeText(plainSummary.value);
}
async function onDelete() {
  if (!confirm("Delete this visit and all local data? This cannot be undone.")) return;
  await carenote.deleteVisit(visitId.value);
  await router.push("/carenote");
}
</script>
