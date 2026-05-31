<script setup lang="ts">
import { computed } from "vue";
import { onMarkdownCopyClick, renderMarkdown } from "~/utils/recallMarkdown";
import { useDream } from "~/composables/useDream";

const dream = useDream();

const html = computed(() => {
  const c = dream.selectedContent.value;
  if (!c) return "";
  return renderMarkdown(c);
});

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString();
}
</script>

<template>
  <section class="dream-viewer">
    <header v-if="dream.selectedPath.value" class="dream-viewer-head">
      <h2>{{ dream.selectedPath.value }}</h2>
      <p v-if="dream.selectedMeta.value" class="dream-viewer-meta">
        {{ fmtTime(dream.selectedMeta.value.mtime) }} · {{ fmtBytes(dream.selectedMeta.value.bytes) }}
      </p>
    </header>
    <div v-if="dream.viewerLoading.value" class="dream-viewer-empty">Loading…</div>
    <div v-else-if="dream.viewerError.value" class="dream-viewer-empty is-error">
      {{ dream.viewerError.value }}
    </div>
    <div
      v-else-if="dream.selectedPath.value && html"
      class="dream-viewer-body"
      v-html="html"
      @click="onMarkdownCopyClick"
    />
    <div v-else class="dream-viewer-empty">
      Select a memory file from the left to view.
    </div>
  </section>
</template>

<style scoped>
.dream-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 18px 22px;
  overflow-y: auto;
}
.dream-viewer-head { margin-bottom: 12px; border-bottom: 1px solid rgba(0, 0, 0, 0.08); padding-bottom: 8px; }
.dream-viewer-head h2 { font-size: 1rem; margin: 0; font-family: ui-monospace, monospace; color: rgba(0, 0, 0, 0.7); word-break: break-all; }
.dream-viewer-meta { font-size: 0.74rem; color: rgba(0, 0, 0, 0.45); margin: 4px 0 0 0; }
.dream-viewer-body { line-height: 1.55; font-size: 0.92rem; }
.dream-viewer-body :deep(h1) { font-size: 1.4rem; margin-top: 0; }
.dream-viewer-body :deep(pre) { background: rgba(0, 0, 0, 0.045); padding: 10px 12px; border-radius: 6px; overflow-x: auto; }
.dream-viewer-empty { color: rgba(0, 0, 0, 0.45); font-size: 0.88rem; padding: 40px 0; text-align: center; }
.dream-viewer-empty.is-error { color: #b91c1c; }
</style>
