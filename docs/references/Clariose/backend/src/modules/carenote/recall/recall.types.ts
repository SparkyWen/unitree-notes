// CLARIOSE_V01 §4 — recall pipeline types.

export type MemoryScope = "visit" | "user";

export type ManifestEntry = {
  /** Frontmatter `name` or filename without extension. */
  name: string;
  /** Stable dedup key relative to memory root, e.g. "users/u-x/allergies.md". */
  relPath: string;
  scope: MemoryScope;
  /** Frontmatter `keywords`, lowercased. */
  keywords: string[];
  /** Frontmatter `description` or first sentence of body. */
  description: string;
  mtimeMs: number;
  bytes: number;
  /** Frontmatter `type` (clinical_fact, history, summary, etc.) — opaque tag. */
  type?: string;
};

export type ScanResult = {
  manifest: ManifestEntry[];
  generatedAt: number;
};

export type SurfacedFile = {
  name: string;
  relPath: string;
  scope: MemoryScope;
  absPath: string;
  content: string;
  truncated: boolean;
  freshDays: number;
  bytes: number;
};

export type SideQueryInput = {
  /** Current turn or topic the agent is reasoning about. */
  query: string;
  manifest: ManifestEntry[];
  /** Recently used tool / role names; sideQuery can deprioritize their docs. */
  recentTools?: string[];
  /** Soft cap on selected files. */
  topN?: number;
};

export type RecallSkipReason =
  | "subagent"
  | "disabled"
  | "no_visit"
  | "empty"
  | "visit_budget"
  | "sidequery_failed"
  | "sidequery_timeout";

export type RecallResult = {
  /** Markdown-formatted block to append to the role's instructions. Null if
   *  nothing was surfaced. */
  append: string | null;
  /** relPath list of files that landed in the append block. */
  files: string[];
  bytesInjected: number;
  manifestSize: number;
  selectedCount: number;
  latencyMs: number;
  skipped?: RecallSkipReason;
};
