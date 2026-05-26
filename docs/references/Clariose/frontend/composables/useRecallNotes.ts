// Recall notes composable — talks to /api/recall/notes/*. Mirrors the
// Qagent shape so the page port is mechanical, but uses Clariose's
// useApi() (get/post/patch/delete) instead of Qagent's call().
//
// State is module-singleton: the recall page's middle-pane card grid
// AND the dream sidebar's "Notes" section both consume the same list.
// Without sharing, uploading or deleting in one would not appear in
// the other. Safe because /recall/** is `ssr: false` in nuxt.config.ts
// → this module never executes server-side.

import { ref, type Ref } from "vue";
import { useApi } from "./useApi";

export interface RecallNote {
  slug: string;
  filename: string;
  title: string;
  type: string | null;
  description: string | null;
  tags: string[];
  bytes: number;
  mtime: string;
  pinned: boolean;
  collection: string | null;
  kind: "md" | "txt" | "jsonl";
}

const MAX_BYTES = 2 * 1024 * 1024;

async function readText(file: File): Promise<{ filename: string; content: string }> {
  if (file.size > MAX_BYTES) throw new Error(`${file.name} exceeds the 2 MB limit`);
  const content = await file.text();
  return { filename: file.name, content };
}

interface RecallNotesState {
  notes: Ref<RecallNote[]>;
  loading: Ref<boolean>;
  uploading: Ref<boolean>;
  error: Ref<string | null>;
}

let _state: RecallNotesState | null = null;

function getState(): RecallNotesState {
  if (_state) return _state;
  _state = {
    notes: ref<RecallNote[]>([]),
    loading: ref(false),
    uploading: ref(false),
    error: ref<string | null>(null),
  };
  return _state;
}

export function useRecallNotes() {
  const api = useApi();
  const s = getState();

  async function refresh(): Promise<void> {
    s.loading.value = true;
    s.error.value = null;
    try {
      s.notes.value = await api.get<RecallNote[]>("/recall/notes");
    } catch (e: any) {
      s.error.value = e?.data?.message ?? e?.message ?? "Failed to load notes";
    } finally {
      s.loading.value = false;
    }
  }

  async function upload(files: File[]): Promise<void> {
    if (files.length === 0) return;
    s.uploading.value = true;
    s.error.value = null;
    try {
      const payloads = await Promise.all(files.map(readText));
      s.notes.value = await api.post<RecallNote[]>("/recall/notes", { files: payloads });
    } catch (e: any) {
      s.error.value = e?.data?.message ?? e?.message ?? "Upload failed";
      throw e;
    } finally {
      s.uploading.value = false;
    }
  }

  async function remove(slug: string): Promise<void> {
    await api.delete(`/recall/notes/${encodeURIComponent(slug)}`);
    s.notes.value = s.notes.value.filter((n) => n.slug !== slug);
  }

  async function readContent(slug: string): Promise<{ note: RecallNote; content: string }> {
    return api.get<{ note: RecallNote; content: string }>(
      `/recall/notes/${encodeURIComponent(slug)}/content`,
    );
  }

  async function pin(slug: string, pinned: boolean): Promise<void> {
    const updated = await api.patch<RecallNote>(
      `/recall/notes/${encodeURIComponent(slug)}`,
      { pinned },
    );
    s.notes.value = s.notes.value.map((n) => (n.slug === updated.slug ? updated : n));
    s.notes.value.sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      return b.mtime.localeCompare(a.mtime);
    });
  }

  return {
    notes: s.notes,
    loading: s.loading,
    uploading: s.uploading,
    error: s.error,
    refresh,
    upload,
    remove,
    pin,
    readContent,
  };
}
