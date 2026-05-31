<script setup lang="ts">
// Single message block in the recall transcript: user prompt, assistant
// reply (with optional citations + tool calls), or a system info/error.
//
// Streaming policy (mirrors the consult/runtime MessageBlock convention):
// while an assistant block is still receiving deltas (`!block.done`) we
// render its raw text with `whitespace-pre-wrap` instead of running the
// markdown parser on every token. We only flip to the `v-html` rendered
// markdown once the block settles. This keeps the DOM stable during the
// stream — every delta only mutates a single text node — and lets
// @chenglou/pretext (in TranscriptPane) measure block height from raw
// text length without fighting a re-rendered HTML tree.

import { computed } from "vue";
import type { RecallBlock } from "~/composables/useRecallChat";
import { onMarkdownCopyClick, renderMarkdown } from "~/utils/recallMarkdown";

const props = defineProps<{ block: RecallBlock }>();

const renderedMarkdown = computed(() => {
  if (props.block.kind !== "assistant") return "";
  if (!props.block.done) return "";
  return renderMarkdown(props.block.text || "");
});

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
  } catch {
    return "";
  }
}

function shortCmd(cmd: string): string {
  return cmd.length > 80 ? `${cmd.slice(0, 77)}…` : cmd;
}
</script>

<template>
  <div class="recall-msg" :data-kind="block.kind">
    <!-- USER -->
    <div v-if="block.kind === 'user'" class="msg-user">
      <span class="msg-eyebrow">You · {{ fmtTime(block.at) }}</span>
      <p class="msg-user-text">{{ block.text }}</p>
    </div>

    <!-- ASSISTANT -->
    <div v-else-if="block.kind === 'assistant'" class="msg-assistant">
      <span class="msg-eyebrow">Recall · {{ fmtTime(block.at) }}<span v-if="!block.done" class="msg-streaming">⋯ streaming</span></span>
      <!-- While streaming, paint the raw text directly. Only render the
           markdown HTML once the block is settled — keeps the DOM cheap
           per delta and lets pretext measure layout from raw text. -->
      <div
        v-if="!block.done"
        class="msg-body msg-body-stream"
      >{{ block.text }}</div>
      <div
        v-else
        class="msg-body prose-md"
        v-html="renderedMarkdown"
        @click="onMarkdownCopyClick"
      />

      <div v-if="block.citations.length" class="msg-citations">
        <span class="cite-eyebrow">citations</span>
        <a
          v-for="c in block.citations"
          :key="`${c.relPath}:${c.startLine ?? 0}-${c.endLine ?? 0}`"
          class="cite-chip"
          :title="c.excerpt ?? ''"
          :href="`#${c.relPath}`"
        >{{ c.relPath }}<span v-if="c.startLine">:{{ c.startLine }}<span v-if="c.endLine">-{{ c.endLine }}</span></span></a>
      </div>

      <details v-if="block.toolCalls.length" class="msg-tools">
        <summary>{{ block.toolCalls.length }} shell call{{ block.toolCalls.length === 1 ? "" : "s" }}</summary>
        <ul>
          <li v-for="(t, i) in block.toolCalls" :key="i">
            <code class="cmd">{{ shortCmd(t.command) }}</code>
            <span v-if="t.exit !== null && t.exit !== undefined" class="exit" :data-ok="t.exit === 0">exit {{ t.exit }}</span>
            <span v-if="t.durationMs" class="dur">{{ t.durationMs }}ms</span>
            <pre v-if="t.snippet" class="snip">{{ t.snippet }}</pre>
          </li>
        </ul>
      </details>
    </div>

    <!-- TOOL (in-flight, before the assistant block consumes it) -->
    <div v-else-if="block.kind === 'tool'" class="msg-tool">
      <span class="msg-eyebrow">shell</span>
      <code class="cmd">{{ shortCmd(block.command) }}</code>
      <span v-if="block.exit !== null && block.exit !== undefined" class="exit" :data-ok="block.exit === 0">exit {{ block.exit }}</span>
    </div>

    <!-- SYSTEM -->
    <div v-else class="msg-system" :data-subtype="block.subtype">
      <span class="msg-eyebrow">{{ block.subtype === "error" ? "error" : "system" }}</span>
      <p>{{ block.text }}</p>
    </div>
  </div>
</template>

<style scoped>
.recall-msg { padding: 0.75rem 1rem; border-bottom: 1px solid rgba(11,9,7,0.06); }
.recall-msg[data-kind="user"]      { background: rgba(239,234,224,0.4); }
.recall-msg[data-kind="assistant"] { background: rgba(255,255,255,0.6); }
.recall-msg[data-kind="system"][data-subtype="error"] { background: rgba(255,229,229,0.4); }
.msg-eyebrow {
  display: block;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  color: #8A8275;
  text-transform: uppercase;
  margin-bottom: 0.25rem;
}
.msg-streaming { color: #B85065; margin-left: 0.5rem; text-transform: none; }
.msg-user-text { font-size: 14px; color: #161310; white-space: pre-wrap; line-height: 1.5; }
.msg-body { font-size: 14px; color: #161310; line-height: 1.6; }
.msg-body-stream { white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; }
.msg-body :deep(.md-h1), .msg-body :deep(.md-h2), .msg-body :deep(.md-h3) { font-weight: 600; margin: 0.6em 0 0.3em; color: #0B0907; }
.msg-body :deep(.md-h2) { font-size: 1.15em; }
.msg-body :deep(.md-h3) { font-size: 1.05em; }
.msg-body :deep(.md-p) { margin: 0.5em 0; }
.msg-body :deep(.md-ul), .msg-body :deep(.md-ol) { margin: 0.5em 0; padding-left: 1.4em; }
.msg-body :deep(.md-li) { margin: 0.2em 0; }
.msg-body :deep(.md-code-inline) {
  background: rgba(184,80,101,0.08); color: #71303F;
  padding: 0 0.25em; border-radius: 3px;
  font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 0.92em;
}
.msg-body :deep(.md-pre) {
  position: relative;
  background: rgba(11,9,7,0.05); padding: 0.6em 0.8em; border-radius: 6px;
  overflow-x: auto; font-size: 12.5px; margin: 0.5em 0;
  user-select: text;
}
.msg-body :deep(.md-pre code) { user-select: text; }
.msg-body :deep(.md-copy) {
  position: absolute; top: 0.4em; right: 0.4em;
  background: rgba(255,255,255,0.7); border: 1px solid rgba(11,9,7,0.1);
  border-radius: 4px; padding: 0 0.4em; font-size: 11px; cursor: pointer;
  /* Hidden until the user hovers the <pre>. Keeps the button out of the
     way of mouse text-selection on short snippets, which used to break the
     drag because the absolute-positioned button intercepted pointerup. */
  opacity: 0; transition: opacity 120ms ease, background 120ms ease;
  user-select: none;
}
.msg-body :deep(.md-pre:hover .md-copy),
.msg-body :deep(.md-pre:focus-within .md-copy),
.msg-body :deep(.md-copy:focus-visible) { opacity: 1; }
.msg-body :deep(.md-copy.is-copied) {
  opacity: 1; background: rgba(184,80,101,0.18); color: #71303F;
}
.msg-body :deep(.md-citation) {
  background: rgba(184,80,101,0.08); color: #71303F; padding: 0 0.2em;
  border-radius: 3px; font-family: "JetBrains Mono", ui-monospace, monospace;
}
.msg-citations { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem; align-items: center; }
.cite-eyebrow {
  font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 10px;
  text-transform: uppercase; color: #8A8275;
}
.cite-chip {
  font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 11px;
  color: #71303F; background: rgba(184,80,101,0.08);
  border: 1px solid rgba(184,80,101,0.18);
  padding: 0.1rem 0.4rem; border-radius: 4px; text-decoration: none;
}
.cite-chip:hover { background: rgba(184,80,101,0.15); }
.msg-tools { margin-top: 0.5rem; font-size: 12px; color: #5C544D; }
.msg-tools summary { cursor: pointer; user-select: none; }
.msg-tools ul { list-style: none; margin: 0.4rem 0 0; padding: 0; }
.msg-tools li { margin: 0.3rem 0; }
.cmd {
  font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 11.5px;
  background: rgba(11,9,7,0.05); padding: 0 0.25em; border-radius: 3px; color: #26221F;
}
.exit { margin-left: 0.4rem; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 10.5px; color: #963F52; }
.exit[data-ok="true"] { color: #2C7A4D; }
.dur { margin-left: 0.4rem; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 10.5px; color: #8A8275; }
.snip {
  margin: 0.3rem 0 0; padding: 0.4rem 0.6rem;
  background: rgba(11,9,7,0.04); border-radius: 4px;
  font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 11px;
  white-space: pre-wrap; max-height: 8rem; overflow-y: auto;
}
.msg-tool { display: flex; align-items: center; gap: 0.4rem; padding: 0.4rem 0; }
.msg-system p { font-size: 13px; color: #5C544D; margin: 0; }
.msg-system[data-subtype="error"] p { color: #963F52; }
</style>
