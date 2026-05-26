<script setup lang="ts">
import { computed, ref } from "vue";
import { useDream, type DreamVisitOption } from "~/composables/useDream";
import { useRecallNotes, type RecallNote } from "~/composables/useRecallNotes";
import DreamTreeNode from "./DreamTreeNode.vue";

// Singleton: the recall page owns connect()/refresh() in its own
// onMounted. Calling them here too would still be idempotent, but
// leaving them out keeps the lifecycle in one place.
const dream = useDream();
const notes = useRecallNotes();

const emit = defineEmits<{
  "select-note": [slug: string];
}>();

const isBusy = computed(() => dream.status.value === "running");

const lastDreamedLabel = computed(() => {
  const t = dream.lastDreamedAt.value;
  if (!t) return "never";
  const ms = Date.now() - new Date(t).getTime();
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
});

const progressLabel = computed(() => {
  const c = dream.current.value;
  if (!c) return null;
  return `${c.phase} · ${c.pct}%`;
});

const visitsExpanded = ref(true);
const notesExpanded = ref(true);

function visitDate(v: DreamVisitOption): string {
  try {
    const d = new Date(v.startedAt);
    const m = (d.getMonth() + 1).toString().padStart(2, "0");
    const day = d.getDate().toString().padStart(2, "0");
    const hh = d.getHours().toString().padStart(2, "0");
    const mm = d.getMinutes().toString().padStart(2, "0");
    return `${m}/${day} ${hh}:${mm}`;
  } catch {
    return "—";
  }
}

function visitDuration(v: DreamVisitOption): string {
  const sec = v.durationSec || 0;
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s === 0 ? `${m}m` : `${m}m${s.toString().padStart(2, "0")}`;
}

function visitTitle(v: DreamVisitOption): string {
  // Title fallback chain: explicit summary preview → doctor name → null.
  // Date + stats live in the meta line, so the title is allowed to be
  // null (the row stays compact).
  if (v.summaryPreview) return v.summaryPreview;
  if (v.doctorName) return v.doctorName;
  return "";
}

function onOpen(path: string): void {
  void dream.openFile(path);
}
function onRedream(visitId: string): void {
  if (isBusy.value) return;
  void dream.runVisit(visitId);
}
async function onDreamNow(): Promise<void> {
  if (isBusy.value) return;
  await dream.run();
}
function onDreamVisit(visitId: string): void {
  if (isBusy.value) return;
  void dream.runVisit(visitId);
}

function onSelectNote(n: RecallNote): void {
  // The note viewer modal lives on the page (it owns the upload widget,
  // delete action, and `selectedNote` state). Emit upward; the page
  // handler calls `openNote(...)`.
  emit("select-note", n.slug);
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
</script>

<template>
  <aside class="dream-sidebar">
    <div class="dream-sidebar-head">
      <button
        type="button"
        class="dream-now-btn"
        :disabled="isBusy"
        :title="isBusy ? 'Already running' : 'Dream all my recent visits'"
        @click="onDreamNow"
      >
        <span aria-hidden="true">✨</span>
        <span>{{ isBusy ? "Dreaming…" : "Dream now" }}</span>
      </button>
      <p class="dream-sidebar-meta">
        <span>Last: <strong>{{ lastDreamedLabel }}</strong></span>
        <span v-if="progressLabel"> · {{ progressLabel }}</span>
        <span v-else-if="dream.lastFilesUpdated.value > 0"> · {{ dream.lastFilesUpdated.value }} files</span>
      </p>
      <p v-if="dream.lastError.value" class="dream-sidebar-error">
        {{ dream.lastError.value === "empty_visit"
          ? "This visit has no transcript yet."
          : dream.lastError.value }}
      </p>
    </div>

    <!-- VISITS PICKER ───────────────────────────────────────────────── -->
    <section class="dream-section">
      <button
        type="button"
        class="dream-section-head"
        :aria-expanded="visitsExpanded"
        @click="visitsExpanded = !visitsExpanded"
      >
        <span class="dream-section-caret" :class="{ open: visitsExpanded }">▸</span>
        <span class="dream-section-label">Recent visits</span>
        <span class="dream-section-count">{{ dream.visits.value.length }}</span>
      </button>
      <ul v-if="visitsExpanded" class="dream-visit-list">
        <li
          v-for="v in dream.visits.value"
          :key="v.visitId"
          class="dream-visit-row"
        >
          <div class="dream-visit-meta">
            <span class="dream-visit-date">{{ visitDate(v) }}</span>
            <span class="dream-visit-stats">{{ visitDuration(v) }} · {{ v.utteranceCount }} utt</span>
            <span
              v-if="v.hasMemoryFile"
              class="dream-visit-dot"
              title="Already has a memory file"
              aria-label="Already dreamed"
            >●</span>
          </div>
          <p
            v-if="visitTitle(v)"
            class="dream-visit-preview"
            :title="visitTitle(v)"
          >{{ visitTitle(v) }}</p>
          <button
            type="button"
            class="dream-visit-btn"
            :disabled="isBusy"
            :title="isBusy ? 'Another dream is running' : (v.hasMemoryFile ? 'Re-dream this visit' : 'Dream this visit')"
            @click="onDreamVisit(v.visitId)"
          >
            <span aria-hidden="true">✨</span>
            <span>{{ v.hasMemoryFile ? "Re-dream" : "Dream" }}</span>
          </button>
        </li>
        <li v-if="dream.visits.value.length === 0" class="dream-section-empty">
          No visits with transcript content yet.
        </li>
      </ul>
    </section>

    <!-- MEMORY TREE ─────────────────────────────────────────────────── -->
    <section class="dream-section">
      <div class="dream-section-head dream-section-head-static">
        <span class="dream-section-label">Memory tree</span>
        <span
          v-if="dream.tree.value.length > 0"
          class="dream-section-count"
        >{{ dream.tree.value.length }}</span>
      </div>
      <ul class="dream-sidebar-tree">
        <DreamTreeNode
          v-for="n in dream.tree.value"
          :key="n.path"
          :node="n"
          :depth="0"
          :selected-path="dream.selectedPath.value"
          :busy="isBusy"
          @open="onOpen"
          @redream="onRedream"
        />
      </ul>
      <p v-if="dream.tree.value.length === 0" class="dream-section-empty">
        No memory yet. Dream a visit to populate.
      </p>
    </section>

    <!-- NOTES (uploaded files) ─────────────────────────────────────── -->
    <section class="dream-section">
      <button
        type="button"
        class="dream-section-head"
        :aria-expanded="notesExpanded"
        @click="notesExpanded = !notesExpanded"
      >
        <span class="dream-section-caret" :class="{ open: notesExpanded }">▸</span>
        <span class="dream-section-label">Notes</span>
        <span class="dream-section-count">{{ notes.notes.value.length }}</span>
      </button>
      <ul v-if="notesExpanded" class="dream-notes-list">
        <li
          v-for="n in notes.notes.value"
          :key="n.slug"
          class="dream-notes-row"
        >
          <button
            type="button"
            class="dream-notes-btn"
            :title="n.filename"
            @click="onSelectNote(n)"
          >
            <span aria-hidden="true" class="dream-notes-icon">{{ n.kind === "md" ? "📄" : n.kind === "jsonl" ? "🧾" : "📃" }}</span>
            <span class="dream-notes-name">{{ n.title }}</span>
            <span v-if="n.pinned" class="dream-notes-pin" aria-label="Pinned">📌</span>
          </button>
          <span class="dream-notes-bytes">{{ fmtBytes(n.bytes) }}</span>
        </li>
        <li v-if="notes.notes.value.length === 0" class="dream-section-empty">
          No notes uploaded yet.
        </li>
      </ul>
    </section>
  </aside>
</template>

<style scoped>
.dream-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  padding: 14px 12px;
  border-right: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.5);
  overflow-y: auto;
}
.dream-sidebar-head { display: flex; flex-direction: column; gap: 6px; }
.dream-now-btn {
  appearance: none;
  border: 0;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: white;
  padding: 9px 12px;
  border-radius: 8px;
  font-weight: 600;
  display: flex;
  gap: 6px;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.dream-now-btn:disabled { opacity: 0.55; cursor: progress; }
.dream-sidebar-meta { font-size: 0.78rem; color: rgba(0, 0, 0, 0.55); margin: 0; }
.dream-sidebar-error { font-size: 0.78rem; color: #b91c1c; margin: 0; word-break: break-word; }

.dream-section { display: flex; flex-direction: column; gap: 4px; }
.dream-section-head {
  appearance: none;
  background: transparent;
  border: 0;
  display: flex;
  gap: 6px;
  align-items: center;
  text-align: left;
  font-size: 0.7rem;
  font-family: ui-monospace, monospace;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: rgba(0, 0, 0, 0.55);
  padding: 4px 2px;
  cursor: pointer;
  width: 100%;
}
.dream-section-head-static { cursor: default; }
.dream-section-caret {
  display: inline-block;
  transition: transform 120ms ease;
  font-size: 0.6rem;
  color: rgba(0, 0, 0, 0.4);
}
.dream-section-caret.open { transform: rotate(90deg); }
.dream-section-label { flex: 1; }
.dream-section-count { color: rgba(0, 0, 0, 0.4); font-weight: normal; }
.dream-section-empty { font-size: 0.78rem; color: rgba(0, 0, 0, 0.45); margin: 6px 6px; }

.dream-visit-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dream-visit-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 4px 8px;
  align-items: center;
  padding: 6px 8px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.7);
}
.dream-visit-meta {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 0.75rem;
  color: rgba(0, 0, 0, 0.7);
  min-width: 0;
}
.dream-visit-date { font-family: ui-monospace, monospace; color: rgba(0, 0, 0, 0.65); }
.dream-visit-stats { color: rgba(0, 0, 0, 0.45); font-size: 0.7rem; }
.dream-visit-dot { color: #8b5cf6; font-size: 0.6rem; margin-left: auto; }
.dream-visit-preview {
  grid-column: 1 / -1;
  margin: 0;
  font-size: 0.72rem;
  color: rgba(0, 0, 0, 0.55);
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.dream-visit-btn {
  appearance: none;
  border: 1px solid rgba(99, 102, 241, 0.4);
  background: rgba(99, 102, 241, 0.08);
  color: #4338ca;
  padding: 3px 8px;
  border-radius: 5px;
  font-size: 0.72rem;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  white-space: nowrap;
}
.dream-visit-btn:hover:not(:disabled) { background: rgba(99, 102, 241, 0.15); }
.dream-visit-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.dream-sidebar-tree { list-style: none; padding: 0; margin: 0; }

.dream-notes-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.dream-notes-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 4px;
}
.dream-notes-btn {
  appearance: none;
  background: transparent;
  border: 0;
  display: flex;
  gap: 6px;
  align-items: center;
  flex: 1;
  min-width: 0;
  text-align: left;
  font-size: 0.82rem;
  padding: 3px 6px;
  cursor: pointer;
  border-radius: 4px;
  color: inherit;
}
.dream-notes-btn:hover { background: rgba(0, 0, 0, 0.04); }
.dream-notes-icon { flex-shrink: 0; }
.dream-notes-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dream-notes-pin { font-size: 0.7rem; color: #8b5cf6; }
.dream-notes-bytes {
  font-size: 0.7rem;
  font-family: ui-monospace, monospace;
  color: rgba(0, 0, 0, 0.4);
  white-space: nowrap;
}
</style>
