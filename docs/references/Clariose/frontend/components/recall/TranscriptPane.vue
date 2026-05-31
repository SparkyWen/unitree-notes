<script setup lang="ts">
// Recall transcript pane.
//
// Two efficiency tricks borrowed from the Qagent runtime transcript:
//
//  1. Tail virtualization. We only mount the most recent VISIBLE_WINDOW
//     blocks. Hidden older blocks are stashed behind a "show earlier"
//     button. For long recall conversations this keeps the DOM under ~80
//     blocks regardless of total length.
//
//  2. @chenglou/pretext height estimator for the still-streaming tail.
//     Codex coordinator turns can stream a long markdown answer; without a
//     reserved height the scroll container snaps around on every delta as
//     the text wraps. We measure the streaming block's natural height once
//     per delta, reserve that much space, and the container stays calm.
//     pretext is dynamically imported (it needs `Intl.Segmenter`, so it's
//     client-only). Failing to load is non-fatal — we just skip the
//     reservation.

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { RecallBlock } from "~/composables/useRecallChat";
import MessageBlock from "./MessageBlock.vue";

const props = defineProps<{ blocks: RecallBlock[] }>();

const VISIBLE_WINDOW = 80;
const showingAll = ref(false);

const visible = computed<RecallBlock[]>(() => {
  if (showingAll.value) return props.blocks;
  return props.blocks.slice(-VISIBLE_WINDOW);
});
const hiddenCount = computed(() => Math.max(0, props.blocks.length - visible.value.length));

const scrollEl = ref<HTMLElement | null>(null);
const stickToBottom = ref(true);
const showNewBadge = ref(false);

function onScroll(): void {
  if (!scrollEl.value) return;
  const el = scrollEl.value;
  const distanceFromBottom = el.scrollHeight - (el.scrollTop + el.clientHeight);
  stickToBottom.value = distanceFromBottom < 80;
  if (stickToBottom.value) showNewBadge.value = false;
}

// ─── pretext height estimator ──────────────────────────────────────────
type Pretext = { prepare: (t: string, font: string) => unknown; layout: (p: unknown, w: number, lh: number) => { height: number } };
let pretext: Pretext | null = null;
async function loadPretext(): Promise<Pretext | null> {
  try {
    const m = await import("@chenglou/pretext");
    return { prepare: m.prepare as Pretext["prepare"], layout: m.layout as Pretext["layout"] };
  } catch {
    return null;
  }
}
async function estimate(text: string, width: number): Promise<number> {
  if (!pretext) pretext = await loadPretext();
  if (!pretext) return 0;
  try {
    const prepared = pretext.prepare(text, "14px ui-sans-serif, system-ui, sans-serif");
    const { height } = pretext.layout(prepared, width, 22);
    return height;
  } catch {
    return 0;
  }
}

const estimatedStreamHeight = ref(0);

// Watch the streaming tail's text length AND its `done` flag. Without
// `done` in the key, settling the block (which doesn't grow text) leaves
// the spacer up forever and the user can scroll into a blank zone past
// the bottom.
watch(
  () => props.blocks.map((b) => {
    if (b.kind === "assistant") return `a:${b.text.length}:${b.done ? 1 : 0}`;
    return `${b.kind[0]}:0`;
  }).join(","),
  async () => {
    await nextTick();
    const tail = props.blocks[props.blocks.length - 1];
    if (tail && tail.kind === "assistant" && !tail.done) {
      const width = scrollEl.value?.clientWidth ? scrollEl.value.clientWidth - 32 : 600;
      estimatedStreamHeight.value = await estimate(tail.text, width);
    } else {
      estimatedStreamHeight.value = 0;
    }
    if (stickToBottom.value && scrollEl.value) {
      scrollEl.value.scrollTop = scrollEl.value.scrollHeight;
    } else if (props.blocks.length > 0) {
      showNewBadge.value = true;
    }
  },
);

function jumpToBottom(): void {
  if (!scrollEl.value) return;
  scrollEl.value.scrollTop = scrollEl.value.scrollHeight;
  showNewBadge.value = false;
  stickToBottom.value = true;
}

function revealAll(): void {
  showingAll.value = true;
}

let resizeObserver: ResizeObserver | null = null;
onMounted(() => {
  if (scrollEl.value && typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(() => {
      const tail = props.blocks[props.blocks.length - 1];
      if (tail && tail.kind === "assistant" && !tail.done) {
        const width = (scrollEl.value?.clientWidth ?? 600) - 32;
        estimate(tail.text, width).then((h) => { estimatedStreamHeight.value = h; });
      }
    });
    resizeObserver.observe(scrollEl.value);
  }
});
onBeforeUnmount(() => { resizeObserver?.disconnect(); });
</script>

<template>
  <div class="transcript-shell">
    <div ref="scrollEl" class="transcript-scroll" @scroll="onScroll">
      <button
        v-if="hiddenCount > 0"
        type="button"
        class="reveal-older"
        @click="revealAll"
      >Show {{ hiddenCount }} earlier message{{ hiddenCount === 1 ? "" : "s" }}</button>

      <div v-if="props.blocks.length === 0" class="empty">
        Tell Recall what you're looking for — it will use <code>rg / sed / cat</code>
        across the memories root and reply with <code>file:line</code> citations.
      </div>

      <MessageBlock v-for="b in visible" :key="b.id" :block="b" />

      <!-- Reserved space so auto-scroll doesn't snap around while a block
           is still streaming. Drops back to 0 the moment the tail settles. -->
      <div v-if="estimatedStreamHeight > 0" :style="{ height: `${Math.max(0, estimatedStreamHeight - 40)}px` }" />
    </div>
    <button
      v-if="showNewBadge"
      type="button"
      class="new-badge"
      @click="jumpToBottom"
    >New messages ↓</button>
  </div>
</template>

<style scoped>
.transcript-shell { position: relative; display: flex; flex-direction: column; }
.transcript-scroll { flex: 1; min-height: 0; overflow-y: auto; }
.empty {
  padding: 2rem 1.25rem; color: #5C544D; font-size: 13.5px; line-height: 1.6;
}
.empty code { font-family: "JetBrains Mono", ui-monospace, monospace; color: #71303F; background: rgba(184,80,101,0.08); padding: 0 0.25em; border-radius: 3px; }
.reveal-older {
  width: calc(100% - 2rem); margin: 0.5rem 1rem 0;
  border: 1px solid rgba(11,9,7,0.08); background: rgba(255,255,255,0.6);
  border-radius: 6px; padding: 0.4rem 0.6rem;
  font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 11px;
  color: #5C544D; cursor: pointer;
}
.reveal-older:hover { background: rgba(255,255,255,0.85); }
.new-badge {
  position: absolute; bottom: 0.75rem; left: 50%; transform: translateX(-50%);
  background: #161310; color: #FFFFFF; border: none;
  border-radius: 9999px; padding: 0.4rem 0.9rem; font-size: 12px; cursor: pointer;
}
</style>
