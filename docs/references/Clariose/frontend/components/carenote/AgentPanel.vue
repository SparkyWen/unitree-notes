<template>
  <section
    class="agent-panel relative overflow-hidden rounded-2xl border bg-white p-5 shadow-card"
    :style="{ borderColor: persona.border }"
  >
    <!-- soft tinted glow corner -->
    <div
      class="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full opacity-60"
      :style="{ background: persona.glow }"
    />

    <header class="relative flex items-start gap-3">
      <AgentAvatar :role="role" :size="60" />
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <h3 class="display text-[18px] leading-tight tracking-editorial text-ink-800">
            {{ persona.name }}
          </h3>
          <span
            v-if="count !== undefined && count !== null"
            class="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold text-white"
            :style="{ background: persona.dot }"
          >
            {{ count }}
          </span>
        </div>
        <p class="mt-0.5 font-mono text-[10.5px] uppercase tracking-[0.18em] text-ink-400">
          {{ persona.role }}
        </p>
        <!-- speech bubble: tagline / current activity -->
        <div class="relative mt-2 inline-block max-w-full">
          <div
            class="rounded-2xl rounded-bl-sm px-3 py-1.5 text-[12.5px] leading-snug text-ink-700"
            :style="{ background: persona.bubble }"
          >
            {{ tagline ?? persona.tagline }}
          </div>
        </div>
      </div>
    </header>

    <div v-if="empty" class="relative mt-4 rounded-xl border border-dashed border-line-soft bg-ink-50/40 p-4 text-sm text-ink-400">
      <span aria-hidden="true" class="mr-1.5">{{ persona.idleEmoji }}</span>
      {{ emptyText ?? persona.emptyText }}
    </div>
    <div v-else class="relative mt-4">
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import AgentAvatar, { type AgentRole } from "./AgentAvatar.vue";

const props = defineProps<{
  role: AgentRole;
  empty?: boolean;
  emptyText?: string;
  count?: number | null;
  tagline?: string;
}>();

type Persona = {
  name: string;
  role: string;
  tagline: string;
  emptyText: string;
  idleEmoji: string;
  border: string;
  bubble: string;
  glow: string;
  dot: string;
};

const PERSONAS: Record<AgentRole, Persona> = {
  scribe: {
    name: "Scribe Lin",
    role: "Transcript Verifier",
    tagline: "I read every line twice — let's keep the words honest.",
    emptyText: "Nothing to fact-check yet. Start the visit and I'll get reading.",
    idleEmoji: "✒️",
    border: "rgba(217,210,196,0.7)",
    bubble: "#F7F2EC",
    glow: "radial-gradient(closest-side, rgba(212,183,118,0.30), transparent 70%)",
    dot: "#8E6F2D",
  },
  inquirer: {
    name: "Curious Mei",
    role: "Question Helper",
    tagline: "If something's fuzzy, I'll know what to ask the doctor.",
    emptyText: "No questions in mind yet — I'm listening carefully.",
    idleEmoji: "🔎",
    border: "rgba(229,210,165,0.8)",
    bubble: "#FBF6E9",
    glow: "radial-gradient(closest-side, rgba(219,181,68,0.30), transparent 70%)",
    dot: "#947214",
  },
  scout: {
    name: "Scout Ada",
    role: "Fact Finder",
    tagline: "I jot down the real facts — names, doses, dates.",
    emptyText: "No facts gathered yet. Speak naturally, I'll catch them.",
    idleEmoji: "📓",
    border: "rgba(194,207,181,0.8)",
    bubble: "#F1F4EE",
    glow: "radial-gradient(closest-side, rgba(95,122,78,0.26), transparent 70%)",
    dot: "#5F7A4E",
  },
  pharmacist: {
    name: "Dr. Apo",
    role: "Medication Guide",
    tagline: "Dose, timing, and food — I'll lay out the plan clearly.",
    emptyText: "No prescriptions heard yet. I'll draft a schedule when they appear.",
    idleEmoji: "💊",
    border: "rgba(234,183,187,0.8)",
    bubble: "#FBF1F1",
    glow: "radial-gradient(closest-side, rgba(184,80,101,0.28), transparent 70%)",
    dot: "#B85065",
  },
  coordinator: {
    name: "Planner Yuki",
    role: "Follow-up Coordinator",
    tagline: "Tests, referrals, recheck dates — I keep the calendar tidy.",
    emptyText: "No follow-ups yet. I'll line them up when I hear them.",
    idleEmoji: "🗂️",
    border: "rgba(229,210,165,0.7)",
    bubble: "#FBF6EC",
    glow: "radial-gradient(closest-side, rgba(142,111,45,0.22), transparent 70%)",
    dot: "#8E6F2D",
  },
  guardian: {
    name: "Nurse Iris",
    role: "Safety Watch",
    tagline: "I flag the risky bits — better safe than sorry.",
    emptyText: "All clear. No safety concerns picked up so far.",
    idleEmoji: "🛡️",
    border: "rgba(234,183,187,0.9)",
    bubble: "#FBF1F1",
    glow: "radial-gradient(closest-side, rgba(184,80,101,0.34), transparent 70%)",
    dot: "#963F52",
  },
  messenger: {
    name: "Postie Ren",
    role: "Family Messenger",
    tagline: "I draft a kind note for family — you decide before sending.",
    emptyText: "No notes drafted yet. I'll write something gentle when ready.",
    idleEmoji: "✉️",
    border: "rgba(194,207,181,0.8)",
    bubble: "#F1F4EE",
    glow: "radial-gradient(closest-side, rgba(95,122,78,0.24), transparent 70%)",
    dot: "#5F7A4E",
  },
  storyteller: {
    name: "Auntie Rosa",
    role: "Plain-Language Narrator",
    tagline: "I retell the visit warmly, in words anyone can follow.",
    emptyText: "I'll write a clear summary once the visit wraps up.",
    idleEmoji: "📖",
    border: "rgba(245,220,221,0.85)",
    bubble: "#FBF1F1",
    glow: "radial-gradient(closest-side, rgba(184,80,101,0.22), transparent 70%)",
    dot: "#B85065",
  },
  memory: {
    name: "Keeper Sage",
    role: "Memory Keeper",
    tagline: "Worth remembering? I tuck it away for next time — only with your nod.",
    emptyText: "Nothing to remember yet. I'll suggest what's worth keeping.",
    idleEmoji: "🧠",
    border: "rgba(194,207,181,0.7)",
    bubble: "#F1F4EE",
    glow: "radial-gradient(closest-side, rgba(95,122,78,0.22), transparent 70%)",
    dot: "#48613B",
  },
  orchestrator: {
    name: "Maestro Cen",
    role: "Team Conductor",
    tagline: "I cue the team — everyone plays their part on time.",
    emptyText: "Standing by. The team is warming up.",
    idleEmoji: "🎼",
    border: "rgba(245,220,221,0.7)",
    bubble: "#FBF1F1",
    glow: "radial-gradient(closest-side, rgba(184,80,101,0.18), transparent 70%)",
    dot: "#B85065",
  },
};

const persona = computed<Persona>(() => PERSONAS[props.role]);
</script>
