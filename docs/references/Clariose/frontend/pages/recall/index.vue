<script setup lang="ts">
// /recall — Codex-driven knowledge console.
//
// Three-column layout (desktop):
//   left rail  → notes filters (pinned / all / collections)
//   center     → notes browser (drag-and-drop upload)
//   right rail → chat with the codex recall coordinator (read-only sandbox)
//
// Adapted from the Qagent recall.vue template; the right-rail chat now
// drives a Codex agent (`templates/readPath.ts` system prompt) instead of
// a Claude Agent SDK session. Drop-targets, viewer modal, and history
// rail behaviour are preserved 1:1 so the UX language stays consistent.

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRecallChat } from "~/composables/useRecallChat";
import { useRecallNotes, type RecallNote } from "~/composables/useRecallNotes";
import { useRecallSessions, type RecallSessionSummary } from "~/composables/useRecallSessions";
import { useDream } from "~/composables/useDream";
import TranscriptPane from "~/components/recall/TranscriptPane.vue";
import DreamSidebar from "~/components/recall/DreamSidebar.vue";
import DreamViewer from "~/components/recall/DreamViewer.vue";
import { onMarkdownCopyClick, renderMarkdown } from "~/utils/recallMarkdown";

// CLARIOSE_V03 §dream — sidebar shows the dream output tree; the
// middle pane prefers the dream viewer when a dream file is selected,
// and falls back to the existing notes browser otherwise.
const dream = useDream();
const showDreamViewer = computed(() => !!dream.selectedPath.value);

definePageMeta({});
useHead({ title: "Recall · Clariose" });

const notesApi = useRecallNotes();
const sessionsApi = useRecallSessions();
const chat = useRecallChat();

type Filter = "pinned" | "all" | "collections";
const filter = ref<Filter>("all");

const dragOver = ref(false);
const uploadInput = ref<HTMLInputElement | null>(null);
const search = ref("");
const selectedNote = ref<RecallNote | null>(null);
const selectedNoteContent = ref<string>("");
const viewerLoading = ref(false);
const viewerError = ref<string | null>(null);

const prompt = ref("");
const composerEl = ref<HTMLTextAreaElement | null>(null);
const sessionFilter = ref("");
const usageExpanded = ref(false);

type MobileSheet = "none" | "chat" | "filters" | "history";
const mobileSheet = ref<MobileSheet>("none");
function openMobileChat()    { mobileSheet.value = "chat"; }
function openMobileFilters() { mobileSheet.value = "filters"; }
function openMobileHistory() { mobileSheet.value = "history"; }
function closeMobileSheet()  { mobileSheet.value = "none"; }
watch(mobileSheet, (v) => {
  if (typeof document === "undefined") return;
  document.body.style.overflow = v === "none" ? "" : "hidden";
});

const filteredSessions = computed(() => {
  const q = sessionFilter.value.trim().toLowerCase();
  if (!q) return sessionsApi.sessions.value;
  return sessionsApi.sessions.value.filter((s) =>
    (s.firstPrompt ?? "").toLowerCase().includes(q) ||
    s.sessionId.toLowerCase().includes(q),
  );
});

const filteredNotes = computed(() => {
  let list = notesApi.notes.value;
  if (filter.value === "pinned") list = list.filter((n) => n.pinned);
  const q = search.value.trim().toLowerCase();
  if (q) {
    list = list.filter((n) =>
      n.title.toLowerCase().includes(q) ||
      (n.description ?? "").toLowerCase().includes(q) ||
      n.slug.toLowerCase().includes(q) ||
      n.tags.some((t) => t.toLowerCase().includes(q)),
    );
  }
  return list;
});

const pinnedCount = computed(() => notesApi.notes.value.filter((n) => n.pinned).length);
const collections = computed(() => {
  const set = new Set<string>();
  for (const n of notesApi.notes.value) {
    if (n.collection) set.add(n.collection);
  }
  return Array.from(set).sort();
});

onMounted(async () => {
  // Dream singleton: this page owns the SSE lifecycle. Sidebar/viewer
  // just consume the shared state set up here.
  dream.connect();
  void dream.refreshTree();
  void dream.refreshRuns();
  void dream.refreshVisits();
  await Promise.all([notesApi.refresh(), sessionsApi.refresh()]);
  const active = sessionsApi.sessions.value.find((s) => s.active);
  if (active) {
    try {
      await chat.loadHistory(active.sessionId);
    } catch { /* tolerate */ }
  }
  chat.connect();
});

onBeforeUnmount(() => {
  chat.disconnect();
  dream.disconnect();
});

async function onDrop(e: DragEvent): Promise<void> {
  e.preventDefault();
  dragOver.value = false;
  const files = Array.from(e.dataTransfer?.files ?? []);
  if (files.length === 0) return;
  await uploadFiles(files);
}

async function onFilePicked(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  if (files.length === 0) return;
  await uploadFiles(files);
  input.value = "";
}

async function uploadFiles(files: File[]): Promise<void> {
  try {
    await notesApi.upload(files);
  } catch { /* surfaced via notesApi.error */ }
}

async function openNote(n: RecallNote): Promise<void> {
  selectedNote.value = n;
  selectedNoteContent.value = "";
  viewerError.value = null;
  viewerLoading.value = true;
  try {
    const data = await notesApi.readContent(n.slug);
    selectedNoteContent.value = data.content;
  } catch (e: any) {
    viewerError.value = e?.data?.message ?? e?.message ?? "Failed to read note";
  } finally {
    viewerLoading.value = false;
  }
}

function onSelectNoteFromSidebar(slug: string): void {
  // Sidebar emits the slug; resolve to the full RecallNote and reuse
  // the existing modal opener so behavior matches clicking a card in
  // the middle pane (delete / pin / etc all work).
  const n = notesApi.notes.value.find((x) => x.slug === slug);
  if (n) void openNote(n);
}

function closeNote(): void {
  selectedNote.value = null;
  selectedNoteContent.value = "";
  viewerError.value = null;
}

async function onNewChat(): Promise<void> {
  const { sessionId } = await sessionsApi.newChat();
  chat.reset();
  // Pin the new session id immediately. Without this, the SSE controller's
  // 5s `attach()` poll is the only thing that synchronises us to the new
  // active session, and any send() that happens in the meantime would still
  // post the (now-cleared) old id ⇒ backend falls back to whatever active
  // session it finds, which races with newChat()'s commit.
  chat.activeSessionId.value = sessionId;
  await sessionsApi.refresh();
}

async function onResume(s: RecallSessionSummary): Promise<void> {
  await sessionsApi.resume(s.sessionId);
  await chat.loadHistory(s.sessionId);
  await sessionsApi.refresh();
}

async function onSend(): Promise<void> {
  const text = prompt.value.trim();
  if (!text) return;
  prompt.value = "";
  await chat.send(text);
  await nextTick();
  composerEl.value?.focus();
}

function onComposerKeydown(e: KeyboardEvent): void {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    void onSend();
  }
}

function noteTypeLabel(n: RecallNote): string {
  if (n.type) return n.type;
  return n.kind.toUpperCase();
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    const today = new Date();
    if (d.toDateString() === today.toDateString()) {
      return `Today ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
    }
    return d.toISOString().slice(0, 10);
  } catch { return "—"; }
}

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function fmtPct(r: number | null | undefined): string {
  if (r === null || r === undefined || Number.isNaN(r)) return "—";
  return `${(r * 100).toFixed(1)}%`;
}

function fmtSec(ms: number | null | undefined): string {
  if (!ms && ms !== 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

// Click delegation for the copy button lives in utils/recallMarkdown.ts so
// the chat transcript and the note viewer share one implementation.
</script>

<template>
  <div class="flex h-[calc(100dvh-64px)] w-full">
    <!-- LEFT RAIL — dream output tree + notes list ────────────────── -->
    <DreamSidebar
      class="hidden w-60 shrink-0 md:flex"
      @select-note="onSelectNoteFromSidebar"
    />

    <!-- CENTER ─────────────────────────────────────────────────────── -->
    <main class="flex min-w-0 flex-1 flex-col">
      <!-- CLARIOSE_V03 §dream — dream-file viewer takes precedence over
           the notes browser whenever a memory file is selected on the left. -->
      <DreamViewer v-if="showDreamViewer" />
      <template v-else>
      <!-- Desktop header -->
      <header class="hidden md:flex items-center gap-3 border-b border-line bg-paper/70 backdrop-blur-md px-6 py-4">
        <h1 class="font-grotesk text-2xl tracking-tight text-ink-900">Notes</h1>
        <div class="ml-auto flex items-center gap-2">
          <input
            v-model="search"
            type="text"
            placeholder="Search notes or ask Recall…"
            class="w-72 rounded-lg border border-line bg-paper px-3 py-1.5 text-sm text-ink-900 placeholder:text-ink-400 focus:border-ink-700 focus:outline-none"
          />
        </div>
      </header>

      <!-- Mobile header -->
      <header class="md:hidden border-b border-line bg-paper/70 backdrop-blur-md px-4 pt-5 pb-3">
        <div class="flex items-end justify-between gap-3">
          <div class="min-w-0">
            <p class="text-[10px] font-mono uppercase tracking-wider text-ink-500">recall</p>
            <h1 class="font-grotesk mt-1 text-[26px] leading-none tracking-tight text-ink-900">
              Notes
              <span class="ml-1.5 font-mono text-[12px] text-ink-400">
                {{ filteredNotes.length }}/{{ notesApi.notes.value.length }}
              </span>
            </h1>
          </div>
          <button
            type="button"
            class="inline-flex h-10 items-center gap-1.5 rounded-full border border-line bg-paper px-3 text-[12px] text-ink-700 active:scale-95"
            aria-label="New / upload note"
            @click="uploadInput?.click()"
          >
            <span class="text-clay-600 text-base leading-none">＋</span>
            <span>New</span>
          </button>
        </div>
        <div class="mt-4 relative">
          <input
            v-model="search"
            type="search"
            placeholder="Search notes…"
            class="w-full rounded-2xl border border-line bg-paper py-3 px-3 text-[15px] text-ink-900 placeholder:text-ink-400 focus:border-ink-700 focus:outline-none"
          />
        </div>
        <div class="-mx-4 mt-3 flex items-center gap-2 overflow-x-auto px-4 pb-1">
          <button
            type="button"
            class="shrink-0 rounded-full border px-3.5 py-1.5 text-[12.5px] font-medium transition active:scale-95"
            :class="filter === 'all' ? 'border-ink-900 bg-ink-900 text-canvas' : 'border-line bg-paper text-ink-700'"
            @click="filter = 'all'"
          >All · {{ notesApi.notes.value.length }}</button>
          <button
            type="button"
            class="shrink-0 rounded-full border px-3.5 py-1.5 text-[12.5px] font-medium transition active:scale-95"
            :class="filter === 'pinned' ? 'border-clay-500 bg-clay-500/10 text-clay-700' : 'border-line bg-paper text-ink-700'"
            @click="filter = 'pinned'"
          >Pinned · {{ pinnedCount }}</button>
          <button
            type="button"
            class="shrink-0 rounded-full border px-3.5 py-1.5 text-[12.5px] font-medium transition active:scale-95"
            :class="filter === 'collections' ? 'border-ink-900 bg-ink-900 text-canvas' : 'border-line bg-paper text-ink-700'"
            @click="filter = 'collections'; openMobileFilters()"
          >Collections · {{ collections.length }}</button>
        </div>
      </header>

      <div
        class="relative flex-1 overflow-y-auto p-4 pb-24 md:p-6 md:pb-6"
        :class="dragOver ? 'bg-clay-500/[0.04]' : ''"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop="onDrop"
      >
        <div
          v-if="notesApi.error.value"
          class="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700"
        >{{ notesApi.error.value }}</div>

        <div
          v-if="!notesApi.loading.value && filteredNotes.length === 0 && notesApi.notes.value.length === 0"
          class="flex h-full flex-col items-center justify-center gap-4 text-center"
        >
          <div class="text-6xl opacity-80">🗂️</div>
          <p class="text-sm text-ink-700">No notes yet. Drop files in to get started.</p>
          <p class="text-xs text-ink-500">Supports <code class="font-mono text-clay-700">.md</code> / <code class="font-mono text-clay-700">.txt</code> / <code class="font-mono text-clay-700">.jsonl</code>.</p>
          <button
            type="button"
            class="rounded-lg border border-line bg-paper px-4 py-2 text-sm font-medium text-ink-800 transition hover:border-ink-300 hover:bg-ink-100/60"
            @click="uploadInput?.click()"
          >
            {{ notesApi.uploading.value ? "Uploading…" : "Choose files to upload" }}
          </button>
        </div>

        <div v-else-if="!notesApi.loading.value && filteredNotes.length === 0" class="py-20 text-center text-sm text-ink-500">
          No matching notes.
        </div>

        <div v-else class="grid gap-2.5 sm:gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <article
            v-for="n in filteredNotes"
            :key="n.slug"
            class="group relative flex cursor-pointer flex-col gap-2 rounded-xl border border-line bg-paper p-4 transition hover:border-ink-300"
            @click="openNote(n)"
          >
            <div class="flex items-start gap-2">
              <span class="text-lg">{{ n.kind === "md" ? "📄" : n.kind === "jsonl" ? "🧾" : "📃" }}</span>
              <div class="min-w-0 flex-1">
                <div class="truncate text-sm font-semibold text-ink-900">{{ n.title }}</div>
                <div class="truncate text-xs text-ink-500 font-mono">{{ n.filename }}</div>
              </div>
              <button
                type="button"
                class="opacity-0 transition group-hover:opacity-100"
                :class="n.pinned ? 'opacity-100 text-clay-500' : 'text-ink-400 hover:text-clay-500'"
                :title="n.pinned ? 'Unpin' : 'Pin'"
                @click.stop="notesApi.pin(n.slug, !n.pinned)"
              >📌</button>
            </div>
            <p v-if="n.description" class="line-clamp-2 text-xs text-ink-600 leading-relaxed">{{ n.description }}</p>
            <div class="mt-auto flex items-center justify-between text-[10px] uppercase tracking-wider text-ink-500 font-mono">
              <span>{{ noteTypeLabel(n) }}</span>
              <span>{{ formatBytes(n.bytes) }} · {{ formatDate(n.mtime) }}</span>
            </div>
          </article>
        </div>

        <div
          v-if="dragOver"
          class="pointer-events-none absolute inset-6 flex items-center justify-center rounded-2xl border-2 border-dashed border-clay-500/60 bg-clay-500/[0.06] text-sm font-medium text-clay-700"
        >Drop to upload</div>
      </div>

      <input
        ref="uploadInput"
        type="file"
        accept=".md,.txt,.jsonl,text/markdown,text/plain,application/jsonl"
        multiple
        class="hidden"
        @change="onFilePicked"
      />
      </template>
    </main>

    <!-- HISTORY RAIL ───────────────────────────────────────────────── -->
    <aside class="hidden xl:flex w-[260px] shrink-0 flex-col border-l border-line bg-paper/55 backdrop-blur-md">
      <header class="flex items-center justify-between border-b border-line px-4 py-3">
        <div class="min-w-0">
          <p class="text-[10px] font-mono uppercase tracking-wider text-ink-500">history</p>
          <p class="mt-0.5 text-[11px] font-mono text-ink-500 truncate">
            {{ sessionsApi.sessions.value.length }} total
          </p>
        </div>
        <button
          type="button"
          class="rounded-full border border-line bg-paper px-2 py-0.5 text-[10.5px] font-medium text-ink-700 transition hover:border-ink-300 hover:bg-ink-100/60"
          @click="sessionsApi.refresh()"
        >Refresh</button>
      </header>
      <div class="px-3 pt-2.5 pb-1.5">
        <input
          v-model="sessionFilter"
          type="search"
          placeholder="Search history…"
          class="w-full rounded-lg border border-line bg-paper py-1.5 px-2.5 text-[12px] text-ink-900 placeholder:text-ink-400 focus:border-ink-700 focus:outline-none"
        />
      </div>
      <ul class="flex-1 min-h-0 overflow-y-auto pb-3">
        <li
          v-for="s in filteredSessions"
          :key="`hist:${s.sessionId}`"
          class="border-t border-line/60 first:border-t-0 transition-colors"
          :class="s.active ? 'bg-clay-500/[0.06]' : 'hover:bg-ink-100/50'"
        >
          <button
            type="button"
            class="block w-full px-4 py-2.5 text-left"
            @click="onResume(s)"
          >
            <div class="flex items-center gap-1.5 min-w-0">
              <span
                v-if="s.active"
                class="shrink-0 rounded-full border border-clay-500/40 bg-clay-50 px-1.5 py-[1px] text-[9px] font-mono text-clay-700"
              >active</span>
              <span class="ml-auto text-[10px] font-mono text-ink-500 shrink-0">
                {{ formatDate(new Date(s.mtimeMs).toISOString()) }}
              </span>
            </div>
            <p class="mt-1 text-[12.5px] leading-snug text-ink-800 line-clamp-2 break-words">
              {{ s.firstPrompt ?? s.sessionId.slice(0, 8) }}
            </p>
            <div class="mt-1 flex items-center gap-1.5 text-[10px] text-ink-500 font-mono">
              <span class="shrink-0">{{ s.messageCount }} msg</span>
            </div>
          </button>
        </li>
        <li v-if="filteredSessions.length === 0" class="px-4 py-6 text-center text-[11.5px] text-ink-500">
          {{ sessionsApi.sessions.value.length === 0 ? "No conversations yet" : "No matching conversations" }}
        </li>
      </ul>
    </aside>

    <!-- RIGHT RAIL CHAT ────────────────────────────────────────────── -->
    <aside class="hidden md:flex w-[420px] shrink-0 flex-col border-l border-line bg-paper/75 backdrop-blur-md">
      <header class="flex items-center justify-between border-b border-line px-4 py-3">
        <div class="flex flex-col">
          <span class="text-sm font-semibold text-ink-900">Recall</span>
          <span class="mt-0.5 text-[10px] uppercase tracking-wider text-ink-500 font-mono">
            <span :class="{
              'text-clay-700': chat.status.value === 'running',
              'text-rose-700': chat.status.value === 'failed',
              'text-ink-500': chat.status.value !== 'running' && chat.status.value !== 'failed',
            }">{{ chat.status.value === "running" ? "running" : chat.status.value === "failed" ? "failed" : "idle" }}</span>
            · {{ chat.connected.value ? "SSE connected" : "disconnected" }}
          </span>
        </div>
        <div class="flex items-center gap-1">
          <button
            v-if="chat.status.value === 'running'"
            type="button"
            class="rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700 transition hover:bg-rose-100"
            @click="chat.abort()"
          >Stop</button>
          <button
            type="button"
            class="rounded-md border border-line bg-paper px-2 py-1 text-xs font-medium text-ink-800 transition hover:border-ink-300 hover:bg-ink-100/60"
            @click="onNewChat"
          >＋ New chat</button>
        </div>
      </header>

      <TranscriptPane :blocks="chat.blocks.value" class="flex-1 min-h-0" />

      <section v-if="chat.usage.value" class="border-t border-line px-3 py-2 text-[11px]">
        <button
          type="button"
          class="flex w-full items-center gap-2 text-ink-600 hover:text-ink-900 transition-colors"
          @click="usageExpanded = !usageExpanded"
        >
          <span class="text-[10px] uppercase tracking-wider font-mono text-ink-500">usage · last turn</span>
          <span class="font-mono text-ink-800 font-medium">{{ fmtNum(chat.usage.value.totalTokens) }} tok</span>
          <span class="text-ink-300">·</span>
          <span class="font-mono text-clay-700 font-medium">{{ fmtPct(chat.usage.value.cacheHitRate) }}</span>
          <span class="text-ink-500">hit</span>
          <span class="flex-1" />
          <span class="text-ink-500 font-mono">{{ fmtSec(chat.usage.value.durationMs) }}</span>
        </button>
      </section>

      <footer class="border-t border-line bg-paper/80 px-3 py-3">
        <div class="flex items-end gap-2 rounded-xl border border-line bg-paper p-2 transition focus-within:border-ink-700">
          <textarea
            ref="composerEl"
            v-model="prompt"
            rows="1"
            placeholder="Ask Recall what to find…"
            class="flex-1 resize-none bg-transparent text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none"
            @keydown="onComposerKeydown"
          />
          <button
            type="button"
            class="shrink-0 rounded-lg bg-ink-900 px-3 py-1.5 text-xs font-medium text-canvas transition disabled:opacity-40 hover:bg-ink-700"
            :disabled="chat.status.value === 'running' || prompt.trim().length === 0"
            @click="onSend"
          >Send</button>
        </div>
        <div class="mt-1 text-[10px] text-ink-500 font-mono">Enter to send · Shift+Enter for newline</div>
      </footer>
    </aside>

    <!-- MOBILE BOTTOM ACTION BAR ───────────────────────────────────── -->
    <div class="md:hidden fixed inset-x-4 bottom-4 z-30">
      <div class="flex items-center gap-2 rounded-2xl border border-line bg-paper/95 px-2 py-2 backdrop-blur-md">
        <button
          type="button"
          class="flex-1 rounded-xl bg-ink-900 px-4 py-3 text-[13.5px] font-medium text-canvas transition active:scale-[0.98]"
          @click="openMobileChat"
        >Ask Recall</button>
        <button
          type="button"
          class="rounded-xl border border-line bg-paper px-3.5 py-3 text-[13px] text-ink-700 transition active:scale-95"
          aria-label="History"
          @click="openMobileHistory"
        >📜</button>
        <button
          type="button"
          class="rounded-xl border border-line bg-paper px-3.5 py-3 text-[13px] text-ink-700 transition active:scale-95"
          aria-label="Upload note"
          @click="uploadInput?.click()"
        >⬆︎</button>
      </div>
    </div>

    <!-- MOBILE HISTORY SHEET ───────────────────────────────────────── -->
    <Teleport to="body">
      <div
        v-if="mobileSheet === 'history'"
        class="md:hidden fixed inset-0 z-40"
        role="dialog"
        aria-modal="true"
      >
        <button
          type="button"
          aria-label="Close"
          class="absolute inset-0 bg-ink-900/40 backdrop-blur-sm"
          @click="closeMobileSheet"
        />
        <section class="absolute inset-x-0 bottom-0 flex h-[88dvh] flex-col rounded-t-3xl border-t border-line bg-canvas overflow-hidden">
          <button
            type="button"
            aria-label="Close"
            class="flex h-7 w-full shrink-0 items-center justify-center"
            @click="closeMobileSheet"
          >
            <span class="block h-1 w-10 rounded-full bg-ink-300" />
          </button>
          <header class="border-b border-line px-5 py-3">
            <p class="text-[10px] font-mono uppercase tracking-wider text-ink-500">history</p>
            <h3 class="font-grotesk mt-0.5 text-lg tracking-tight text-ink-900 truncate">
              History · {{ sessionsApi.sessions.value.length }}
            </h3>
          </header>
          <ul class="flex-1 min-h-0 overflow-y-auto">
            <li
              v-for="s in filteredSessions"
              :key="`m-hist:${s.sessionId}`"
              class="border-t border-line/60 first:border-t-0"
            >
              <button
                type="button"
                class="block w-full px-5 py-3 text-left"
                @click="onResume(s); closeMobileSheet(); openMobileChat()"
              >
                <p class="text-[14px] leading-snug text-ink-900 line-clamp-2 break-words">
                  {{ s.firstPrompt ?? s.sessionId.slice(0, 8) }}
                </p>
                <div class="mt-1 text-[10.5px] text-ink-500 font-mono">{{ s.messageCount }} msg · {{ formatDate(new Date(s.mtimeMs).toISOString()) }}</div>
              </button>
            </li>
            <li v-if="filteredSessions.length === 0" class="px-5 py-10 text-center text-[12.5px] text-ink-500">
              No conversations yet
            </li>
          </ul>
        </section>
      </div>
    </Teleport>

    <!-- MOBILE CHAT SHEET ──────────────────────────────────────────── -->
    <Teleport to="body">
      <div
        v-if="mobileSheet === 'chat'"
        class="md:hidden fixed inset-0 z-40"
        role="dialog"
        aria-modal="true"
      >
        <button
          type="button"
          aria-label="Close"
          class="absolute inset-0 bg-ink-900/40 backdrop-blur-sm"
          @click="closeMobileSheet"
        />
        <section class="absolute inset-x-0 bottom-0 flex h-[92dvh] flex-col rounded-t-3xl border-t border-line bg-canvas overflow-hidden">
          <button
            type="button"
            aria-label="Close"
            class="flex h-7 w-full shrink-0 items-center justify-center"
            @click="closeMobileSheet"
          >
            <span class="block h-1 w-10 rounded-full bg-ink-300" />
          </button>
          <header class="flex items-center justify-between border-b border-line px-5 py-3">
            <div class="flex flex-col min-w-0">
              <span class="text-[15px] font-semibold text-ink-900">Recall</span>
              <span class="mt-0.5 text-[10.5px] uppercase tracking-wider text-ink-500 font-mono truncate">
                {{ chat.status.value === "running" ? "running" : chat.status.value === "failed" ? "failed" : "idle" }}
                · {{ chat.connected.value ? "SSE connected" : "disconnected" }}
              </span>
            </div>
            <div class="flex items-center gap-1.5">
              <button
                v-if="chat.status.value === 'running'"
                type="button"
                class="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-[11.5px] font-medium text-rose-700"
                @click="chat.abort()"
              >Stop</button>
              <button
                type="button"
                class="rounded-full border border-line bg-paper px-2.5 py-1 text-[11.5px] font-medium text-ink-800"
                @click="onNewChat"
              >＋ New chat</button>
            </div>
          </header>
          <TranscriptPane :blocks="chat.blocks.value" class="flex-1 min-h-0" />
          <footer class="border-t border-line bg-paper/85 px-3 py-3">
            <div class="flex items-end gap-2 rounded-2xl border border-line bg-paper p-2 transition focus-within:border-ink-700">
              <textarea
                v-model="prompt"
                rows="1"
                placeholder="Ask Recall what to find…"
                class="flex-1 resize-none bg-transparent text-[15px] text-ink-900 placeholder:text-ink-400 focus:outline-none"
                @keydown="onComposerKeydown"
              />
              <button
                type="button"
                class="shrink-0 rounded-xl bg-ink-900 px-4 py-2 text-[13px] font-medium text-canvas transition disabled:opacity-40 active:scale-95"
                :disabled="chat.status.value === 'running' || prompt.trim().length === 0"
                @click="onSend"
              >Send</button>
            </div>
            <div class="mt-1.5 px-1 text-[10.5px] text-ink-500 font-mono">Enter to send · Shift+Enter for newline</div>
          </footer>
        </section>
      </div>
    </Teleport>

    <!-- MOBILE FILTERS SHEET ───────────────────────────────────────── -->
    <Teleport to="body">
      <div
        v-if="mobileSheet === 'filters'"
        class="md:hidden fixed inset-0 z-40"
        role="dialog"
        aria-modal="true"
      >
        <button
          type="button"
          aria-label="Close"
          class="absolute inset-0 bg-ink-900/40 backdrop-blur-sm"
          @click="closeMobileSheet"
        />
        <section class="absolute inset-x-0 bottom-0 flex max-h-[80dvh] flex-col rounded-t-3xl border-t border-line bg-canvas overflow-hidden">
          <button
            type="button"
            class="flex h-7 w-full shrink-0 items-center justify-center"
            @click="closeMobileSheet"
          >
            <span class="block h-1 w-10 rounded-full bg-ink-300" />
          </button>
          <header class="border-b border-line px-5 py-3">
            <p class="text-[10px] font-mono uppercase tracking-wider text-ink-500">collections</p>
            <h3 class="font-grotesk mt-1 text-lg tracking-tight text-ink-900">Collections</h3>
          </header>
          <ul class="flex-1 overflow-y-auto px-4 py-3 space-y-1.5">
            <li v-if="collections.length === 0" class="px-2 py-6 text-center text-[13px] text-ink-500">
              No collections yet.
            </li>
            <li v-for="c in collections" :key="c">
              <button
                type="button"
                class="w-full rounded-xl bg-paper border border-line px-4 py-3 text-left text-[14px] text-ink-800"
                @click="closeMobileSheet"
              >{{ c }}</button>
            </li>
          </ul>
        </section>
      </div>
    </Teleport>

    <!-- NOTE VIEWER MODAL ──────────────────────────────────────────── -->
    <div
      v-if="selectedNote"
      class="fixed inset-0 z-50 flex items-stretch justify-center bg-ink-900/40 backdrop-blur-sm p-0 sm:items-center sm:p-4"
      @click.self="closeNote"
    >
      <div class="flex h-[100dvh] w-full max-w-4xl flex-col overflow-hidden border-line bg-paper sm:h-[85vh] sm:rounded-2xl sm:border">
        <header class="flex items-start gap-3 border-b border-line bg-canvas/60 px-5 py-3">
          <span class="text-2xl">{{ selectedNote.kind === "md" ? "📄" : selectedNote.kind === "jsonl" ? "🧾" : "📃" }}</span>
          <div class="min-w-0 flex-1">
            <h2 class="truncate text-base font-semibold text-ink-900">{{ selectedNote.title }}</h2>
            <div class="truncate text-xs text-ink-500 font-mono">
              {{ selectedNote.filename }} · {{ formatBytes(selectedNote.bytes) }} · {{ formatDate(selectedNote.mtime) }}
            </div>
          </div>
          <button
            type="button"
            class="shrink-0 rounded-md px-2 py-1 text-xs transition hover:bg-ink-100"
            :class="selectedNote.pinned ? 'text-clay-600' : 'text-ink-500 hover:text-clay-600'"
            :title="selectedNote.pinned ? 'Unpin' : 'Pin'"
            @click="notesApi.pin(selectedNote.slug, !selectedNote.pinned)"
          >📌</button>
          <button
            type="button"
            class="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-rose-700 transition hover:bg-rose-50"
            @click="notesApi.remove(selectedNote.slug).then(closeNote)"
          >Delete</button>
          <button
            type="button"
            class="shrink-0 rounded-md px-2 py-1 text-xs text-ink-500 transition hover:bg-ink-100 hover:text-ink-900"
            @click="closeNote"
          >✕</button>
        </header>
        <div class="flex-1 overflow-y-auto bg-paper px-6 py-4 text-sm text-ink-800 leading-relaxed">
          <div v-if="viewerLoading" class="py-10 text-center text-ink-500">Loading…</div>
          <div v-else-if="viewerError" class="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
            {{ viewerError }}
          </div>
          <div
            v-else-if="selectedNote.kind === 'md'"
            class="max-w-none"
            v-html="renderMarkdown(selectedNoteContent)"
            @click="onMarkdownCopyClick"
          />
          <pre
            v-else
            class="whitespace-pre-wrap break-words rounded-xl bg-canvas/70 p-4 font-mono text-[12.5px] leading-relaxed text-ink-900 border border-line"
          >{{ selectedNoteContent }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
