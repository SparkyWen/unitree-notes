<template>
  <div
    class="agent-avatar relative inline-flex items-center justify-center select-none"
    :style="{ width: sizePx + 'px', height: sizePx + 'px' }"
  >
    <!-- Halo ring -->
    <span
      class="absolute inset-0 rounded-full"
      :style="{ background: theme.halo }"
    />
    <!-- Cartoon -->
    <svg
      :width="sizePx"
      :height="sizePx"
      viewBox="0 0 80 80"
      class="relative drop-shadow-sm agent-bob"
      :style="{ animationDelay: bobDelay + 'ms' }"
    >
      <!-- Background blob -->
      <circle cx="40" cy="40" r="34" :fill="theme.bg" />
      <circle
        cx="40" cy="40" r="34"
        fill="none"
        :stroke="theme.stroke"
        stroke-opacity="0.18"
        stroke-width="1"
      />

      <!-- ─────────── SCRIBE ─────────── transcript verification -->
      <g v-if="role === 'scribe'">
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" :fill="theme.body" />
        <circle cx="40" cy="38" r="13" fill="#F8E0D0" />
        <path d="M28 36 Q40 22 52 36 Q49 30 40 28 Q31 30 28 36 Z" fill="#3F3934" />
        <!-- glasses -->
        <circle cx="35" cy="40" r="3.5" fill="none" stroke="#0B0907" stroke-width="1.4" />
        <circle cx="45" cy="40" r="3.5" fill="none" stroke="#0B0907" stroke-width="1.4" />
        <line x1="38.5" y1="40" x2="41.5" y2="40" stroke="#0B0907" stroke-width="1.4" />
        <!-- smile -->
        <path d="M37 45 Q40 47 43 45" fill="none" stroke="#0B0907" stroke-width="1.2" stroke-linecap="round" />
        <!-- pen -->
        <g transform="rotate(35 60 50)">
          <rect x="56" y="46" width="14" height="3" rx="1" fill="#B85065" />
          <polygon points="70,46 74,47.5 70,49" fill="#3F3934" />
        </g>
      </g>

      <!-- ─────────── INQUIRER ─────────── clarifying questions -->
      <g v-else-if="role === 'inquirer'">
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" :fill="theme.body" />
        <circle cx="40" cy="38" r="13" fill="#F8E0D0" />
        <!-- hair tuft -->
        <path d="M30 30 Q35 18 50 28 Q44 24 38 24 Q32 26 30 30 Z" fill="#5C544D" />
        <!-- eyes (curious wide) -->
        <circle cx="35" cy="39" r="1.6" fill="#0B0907" />
        <circle cx="45" cy="39" r="1.6" fill="#0B0907" />
        <!-- mouth (small "o") -->
        <ellipse cx="40" cy="45" rx="1.4" ry="1.8" fill="#0B0907" />
        <!-- magnifier -->
        <circle cx="60" cy="50" r="6" fill="#FFFFFF" stroke="#3F3934" stroke-width="1.6" />
        <line x1="64.5" y1="54.5" x2="70" y2="60" stroke="#3F3934" stroke-width="2.2" stroke-linecap="round" />
        <!-- ? bubble -->
        <circle cx="20" cy="22" r="6" fill="#FFFFFF" stroke="#BB951E" stroke-width="1.2" />
        <text x="20" y="25" font-size="9" font-weight="700" text-anchor="middle" fill="#947214" font-family="Inter, sans-serif">?</text>
      </g>

      <!-- ─────────── SCOUT ─────────── extracted facts -->
      <g v-else-if="role === 'scout'">
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" :fill="theme.body" />
        <circle cx="40" cy="40" r="13" fill="#F8E0D0" />
        <!-- explorer hat -->
        <ellipse cx="40" cy="29" rx="18" ry="3" fill="#48613B" />
        <path d="M28 28 Q40 18 52 28 Z" fill="#48613B" />
        <rect x="32" y="27" width="16" height="2" fill="#5F7A4E" />
        <!-- eyes -->
        <circle cx="35" cy="41" r="1.4" fill="#0B0907" />
        <circle cx="45" cy="41" r="1.4" fill="#0B0907" />
        <!-- smile -->
        <path d="M36 46 Q40 49 44 46" fill="none" stroke="#0B0907" stroke-width="1.2" stroke-linecap="round" />
        <!-- notebook -->
        <rect x="52" y="50" width="14" height="11" rx="1.5" fill="#FFFFFF" stroke="#3F3934" stroke-width="1.2" />
        <line x1="55" y1="54" x2="63" y2="54" stroke="#8A8275" stroke-width="1" />
        <line x1="55" y1="57" x2="63" y2="57" stroke="#8A8275" stroke-width="1" />
      </g>

      <!-- ─────────── PHARMACIST ─────────── medication drafts -->
      <g v-else-if="role === 'pharmacist'">
        <!-- white coat -->
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" fill="#FFFFFF" stroke="#963F52" stroke-width="1.2" />
        <path d="M38 53 L40 60 L42 53" fill="none" stroke="#963F52" stroke-width="1.2" />
        <circle cx="40" cy="38" r="13" fill="#F8E0D0" />
        <!-- hair -->
        <path d="M28 36 Q40 22 52 36 Q49 30 40 28 Q31 30 28 36 Z" fill="#26221F" />
        <!-- eyes -->
        <circle cx="35" cy="39" r="1.4" fill="#0B0907" />
        <circle cx="45" cy="39" r="1.4" fill="#0B0907" />
        <!-- smile -->
        <path d="M36 44 Q40 47 44 44" fill="none" stroke="#0B0907" stroke-width="1.2" stroke-linecap="round" />
        <!-- pill -->
        <g transform="rotate(-20 60 24)">
          <rect x="52" y="20" width="14" height="7" rx="3.5" fill="#B85065" />
          <rect x="59" y="20" width="7" height="7" fill="#F5DCDD" />
          <rect x="52" y="20" width="14" height="7" rx="3.5" fill="none" stroke="#71303F" stroke-width="1" />
        </g>
      </g>

      <!-- ─────────── COORDINATOR ─────────── follow-up tasks -->
      <g v-else-if="role === 'coordinator'">
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" :fill="theme.body" />
        <circle cx="40" cy="38" r="13" fill="#F8E0D0" />
        <!-- bun hair -->
        <circle cx="40" cy="24" r="5" fill="#3F3934" />
        <path d="M28 34 Q40 24 52 34 Q49 30 40 30 Q31 30 28 34 Z" fill="#3F3934" />
        <!-- eyes -->
        <circle cx="35" cy="40" r="1.4" fill="#0B0907" />
        <circle cx="45" cy="40" r="1.4" fill="#0B0907" />
        <!-- smile -->
        <path d="M36 45 Q40 48 44 45" fill="none" stroke="#0B0907" stroke-width="1.2" stroke-linecap="round" />
        <!-- clipboard -->
        <rect x="50" y="48" width="14" height="16" rx="1.5" fill="#FFFFFF" stroke="#3F3934" stroke-width="1.2" />
        <rect x="54" y="46" width="6" height="3" rx="1" fill="#3F3934" />
        <line x1="53" y1="54" x2="61" y2="54" stroke="#8A8275" stroke-width="1" />
        <line x1="53" y1="57" x2="61" y2="57" stroke="#8A8275" stroke-width="1" />
        <line x1="53" y1="60" x2="59" y2="60" stroke="#8A8275" stroke-width="1" />
      </g>

      <!-- ─────────── GUARDIAN ─────────── safety flags -->
      <g v-else-if="role === 'guardian'">
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" fill="#FFFFFF" stroke="#963F52" stroke-width="1.2" />
        <circle cx="40" cy="38" r="13" fill="#F8E0D0" />
        <!-- nurse cap -->
        <path d="M27 30 L53 30 L50 22 L30 22 Z" fill="#FFFFFF" stroke="#963F52" stroke-width="1.2" />
        <rect x="38" y="24" width="4" height="1.6" fill="#B85065" />
        <rect x="39.2" y="22.8" width="1.6" height="4" fill="#B85065" />
        <!-- focused eyes -->
        <path d="M33 40 Q35 38.6 37 40" fill="none" stroke="#0B0907" stroke-width="1.4" stroke-linecap="round" />
        <path d="M43 40 Q45 38.6 47 40" fill="none" stroke="#0B0907" stroke-width="1.4" stroke-linecap="round" />
        <!-- determined mouth -->
        <line x1="37" y1="46" x2="43" y2="46" stroke="#0B0907" stroke-width="1.4" stroke-linecap="round" />
        <!-- shield -->
        <path d="M58 50 L66 50 L66 56 Q62 62 62 62 Q58 60 58 56 Z" fill="#B85065" />
        <path d="M61 54 L62 56 L64 53" fill="none" stroke="#FFFFFF" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
      </g>

      <!-- ─────────── MESSENGER ─────────── caregiver notification -->
      <g v-else-if="role === 'messenger'">
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" :fill="theme.body" />
        <circle cx="40" cy="38" r="13" fill="#F8E0D0" />
        <!-- cap -->
        <path d="M28 32 Q40 20 52 32 L52 30 Q40 22 28 30 Z" fill="#5F7A4E" />
        <rect x="28" y="30" width="24" height="2" fill="#48613B" />
        <!-- eyes & smile -->
        <circle cx="35" cy="40" r="1.4" fill="#0B0907" />
        <circle cx="45" cy="40" r="1.4" fill="#0B0907" />
        <path d="M36 45 Q40 48 44 45" fill="none" stroke="#0B0907" stroke-width="1.2" stroke-linecap="round" />
        <!-- envelope -->
        <rect x="50" y="48" width="16" height="11" rx="1" fill="#FFFFFF" stroke="#3F3934" stroke-width="1.2" />
        <path d="M50 49 L58 55 L66 49" fill="none" stroke="#3F3934" stroke-width="1.2" />
        <!-- heart sparkle -->
        <path d="M16 22 q0 -3 3 -3 q3 0 3 3 q0 -3 3 -3 q3 0 3 3 q0 4 -6 8 q-6 -4 -6 -8 z" fill="#DA8E94" />
      </g>

      <!-- ─────────── STORYTELLER ─────────── plain-language family summary -->
      <g v-else-if="role === 'storyteller'">
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" :fill="theme.body" />
        <circle cx="40" cy="36" r="13" fill="#F8E0D0" />
        <!-- soft hair / scarf -->
        <path d="M27 30 Q40 18 53 30 Q50 26 40 24 Q30 26 27 30 Z" fill="#963F52" />
        <path d="M28 44 Q40 50 52 44 L50 50 Q40 54 30 50 Z" fill="#B85065" />
        <!-- eyes (closed-warm) -->
        <path d="M33 38 Q35 36.6 37 38" fill="none" stroke="#0B0907" stroke-width="1.4" stroke-linecap="round" />
        <path d="M43 38 Q45 36.6 47 38" fill="none" stroke="#0B0907" stroke-width="1.4" stroke-linecap="round" />
        <!-- gentle smile -->
        <path d="M36 42 Q40 45 44 42" fill="none" stroke="#0B0907" stroke-width="1.2" stroke-linecap="round" />
        <!-- open book -->
        <path d="M16 60 Q24 56 32 60 L32 68 Q24 64 16 68 Z" fill="#FFFFFF" stroke="#3F3934" stroke-width="1.2" />
        <path d="M48 60 Q56 56 64 60 L64 68 Q56 64 48 68 Z" fill="#FFFFFF" stroke="#3F3934" stroke-width="1.2" />
      </g>

      <!-- ─────────── MEMORY ─────────── memory candidates -->
      <g v-else-if="role === 'memory'">
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" :fill="theme.body" />
        <circle cx="40" cy="38" r="13" fill="#F8E0D0" />
        <!-- soft beanie -->
        <path d="M27 30 Q40 18 53 30 Q53 26 40 22 Q27 26 27 30 Z" fill="#5F7A4E" />
        <circle cx="40" cy="20" r="2.4" fill="#9DB089" />
        <!-- eyes -->
        <circle cx="35" cy="40" r="1.4" fill="#0B0907" />
        <circle cx="45" cy="40" r="1.4" fill="#0B0907" />
        <!-- smile -->
        <path d="M36 45 Q40 47 44 45" fill="none" stroke="#0B0907" stroke-width="1.2" stroke-linecap="round" />
        <!-- thought cloud with heart -->
        <circle cx="60" cy="22" r="6" fill="#FFFFFF" stroke="#3F3934" stroke-width="1" opacity="0.95" />
        <circle cx="54" cy="28" r="2.2" fill="#FFFFFF" stroke="#3F3934" stroke-width="1" opacity="0.95" />
        <path d="M56 19 q0 -2 2 -2 q2 0 2 2 q0 -2 2 -2 q2 0 2 2 q0 3 -4 5 q-4 -2 -4 -5 z" fill="#B85065" />
      </g>

      <!-- ─────────── ORCHESTRATOR ─────────── overall multi-agent router -->
      <g v-else-if="role === 'orchestrator'">
        <path d="M22 64 L22 54 Q40 47 58 54 L58 64 Z" :fill="theme.body" />
        <circle cx="40" cy="38" r="13" fill="#F8E0D0" />
        <path d="M27 32 Q40 20 53 32 Q50 26 40 24 Q30 26 27 32 Z" fill="#3F3934" />
        <circle cx="35" cy="40" r="1.4" fill="#0B0907" />
        <circle cx="45" cy="40" r="1.4" fill="#0B0907" />
        <path d="M36 45 Q40 48 44 45" fill="none" stroke="#0B0907" stroke-width="1.2" stroke-linecap="round" />
        <!-- baton + sparkles -->
        <line x1="56" y1="22" x2="68" y2="14" stroke="#3F3934" stroke-width="2" stroke-linecap="round" />
        <circle cx="68" cy="14" r="2.4" fill="#D4B776" />
        <circle cx="14" cy="20" r="1.5" fill="#D4B776" />
        <circle cx="18" cy="14" r="1" fill="#D4B776" />
        <circle cx="22" cy="22" r="1" fill="#D4B776" />
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

export type AgentRole =
  | "scribe"
  | "inquirer"
  | "scout"
  | "pharmacist"
  | "coordinator"
  | "guardian"
  | "messenger"
  | "storyteller"
  | "memory"
  | "orchestrator";

const props = withDefaults(
  defineProps<{
    role: AgentRole;
    size?: number;
  }>(),
  { size: 64 },
);

const sizePx = computed(() => props.size);

// Stable per-role bob delay so the row of avatars feels alive but not in lockstep.
const bobDelay = computed(() => {
  const order: AgentRole[] = [
    "scribe",
    "inquirer",
    "scout",
    "pharmacist",
    "coordinator",
    "guardian",
    "messenger",
    "storyteller",
    "memory",
    "orchestrator",
  ];
  return order.indexOf(props.role) * 220;
});

const theme = computed(() => {
  switch (props.role) {
    case "scribe":
      return { bg: "#EFEAE0", body: "#D9D2C4", stroke: "#5C544D", halo: "radial-gradient(closest-side, rgba(212,183,118,0.25), transparent 70%)" };
    case "inquirer":
      return { bg: "#F2E8D2", body: "#E5D2A5", stroke: "#947214", halo: "radial-gradient(closest-side, rgba(219,181,68,0.25), transparent 70%)" };
    case "scout":
      return { bg: "#E0E7D9", body: "#C2CFB5", stroke: "#48613B", halo: "radial-gradient(closest-side, rgba(95,122,78,0.22), transparent 70%)" };
    case "pharmacist":
      return { bg: "#F5DCDD", body: "#EAB7BB", stroke: "#71303F", halo: "radial-gradient(closest-side, rgba(184,80,101,0.22), transparent 70%)" };
    case "coordinator":
      return { bg: "#FBF6EC", body: "#F2E8D2", stroke: "#8E6F2D", halo: "radial-gradient(closest-side, rgba(142,111,45,0.18), transparent 70%)" };
    case "guardian":
      return { bg: "#F5DCDD", body: "#EAB7BB", stroke: "#963F52", halo: "radial-gradient(closest-side, rgba(184,80,101,0.32), transparent 70%)" };
    case "messenger":
      return { bg: "#E0E7D9", body: "#C2CFB5", stroke: "#48613B", halo: "radial-gradient(closest-side, rgba(95,122,78,0.20), transparent 70%)" };
    case "storyteller":
      return { bg: "#FBF1F1", body: "#F5DCDD", stroke: "#963F52", halo: "radial-gradient(closest-side, rgba(184,80,101,0.18), transparent 70%)" };
    case "memory":
      return { bg: "#E0E7D9", body: "#C2CFB5", stroke: "#48613B", halo: "radial-gradient(closest-side, rgba(95,122,78,0.18), transparent 70%)" };
    case "orchestrator":
    default:
      return { bg: "#FBF1F1", body: "#F5DCDD", stroke: "#71303F", halo: "radial-gradient(closest-side, rgba(184,80,101,0.18), transparent 70%)" };
  }
});
</script>

<style scoped>
.agent-bob {
  animation: agentBob 4.6s ease-in-out infinite;
  transform-origin: center;
}
@keyframes agentBob {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  50%      { transform: translateY(-2px) rotate(-1.5deg); }
}
@media (prefers-reduced-motion: reduce) {
  .agent-bob { animation: none; }
}
</style>
