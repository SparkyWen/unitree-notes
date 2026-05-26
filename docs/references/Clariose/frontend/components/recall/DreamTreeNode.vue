<script setup lang="ts">
import type { DreamTreeNode } from "~/composables/useDream";

defineProps<{
  node: DreamTreeNode;
  depth: number;
  selectedPath: string | null;
  busy: boolean;
}>();
const emit = defineEmits<{
  open: [path: string];
  redream: [visitId: string];
}>();
</script>

<template>
  <li class="dream-tree-node">
    <template v-if="node.kind === 'dir'">
      <details open class="dream-tree-dir">
        <summary :style="{ paddingLeft: `${depth * 12}px` }">
          <span aria-hidden="true">📁</span>
          <span class="dream-tree-name">{{ node.name }}</span>
          <span v-if="node.children" class="dream-tree-count">({{ node.children.length }})</span>
        </summary>
        <ul class="dream-tree-children">
          <DreamTreeNode
            v-for="c in node.children ?? []"
            :key="c.path"
            :node="c"
            :depth="depth + 1"
            :selected-path="selectedPath"
            :busy="busy"
            @open="(p: string) => emit('open', p)"
            @redream="(v: string) => emit('redream', v)"
          />
        </ul>
      </details>
    </template>
    <template v-else>
      <button
        type="button"
        class="dream-tree-file"
        :class="{ 'is-selected': selectedPath === node.path }"
        :style="{ paddingLeft: `${depth * 12 + 6}px` }"
        @click="emit('open', node.path)"
      >
        <span aria-hidden="true">📄</span>
        <span class="dream-tree-name">{{ node.name }}</span>
        <span
          v-if="node.visitId"
          role="button"
          tabindex="0"
          class="dream-redream-btn"
          :class="{ 'is-disabled': busy }"
          :title="busy ? 'Another dream is running' : `Re-dream ${node.visitId}`"
          @click.stop="busy ? null : emit('redream', node.visitId!)"
          @keydown.enter.stop="busy ? null : emit('redream', node.visitId!)"
        >↻</span>
      </button>
    </template>
  </li>
</template>

<style scoped>
.dream-tree-node { list-style: none; }
.dream-tree-children { list-style: none; padding: 0; margin: 0; }
.dream-tree-dir summary {
  cursor: pointer;
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 0.86rem;
  padding: 2px 4px;
}
.dream-tree-file {
  appearance: none;
  background: transparent;
  border: 0;
  display: flex;
  gap: 6px;
  align-items: center;
  width: 100%;
  text-align: left;
  font-size: 0.86rem;
  padding: 3px 6px;
  cursor: pointer;
  border-radius: 4px;
  color: inherit;
}
.dream-tree-file.is-selected { background: rgba(99, 102, 241, 0.15); }
.dream-tree-file:hover { background: rgba(0, 0, 0, 0.04); }
.dream-tree-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dream-tree-count { color: rgba(0, 0, 0, 0.4); font-size: 0.78rem; }
.dream-redream-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid rgba(0, 0, 0, 0.15);
  border-radius: 4px;
  font-size: 0.7rem;
  padding: 0 5px;
  cursor: pointer;
  color: inherit;
  user-select: none;
}
.dream-redream-btn.is-disabled { opacity: 0.4; cursor: not-allowed; }
</style>
