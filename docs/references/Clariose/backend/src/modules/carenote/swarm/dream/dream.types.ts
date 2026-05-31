// Shared types for the dream runner + controller + frontend contract.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §6.

export type DreamPhase = "orient" | "gather" | "consolidate" | "prune";

export type DreamScope = { kind: "all" } | { kind: "visit"; visitId: string };

export type DreamTriggerKind = "manual_user" | "manual_visit" | "cron";

export interface DreamProgressEvent {
  at: number; // ms epoch
  phase: DreamPhase;
  pct: number; // 0..100
  note?: string;
}

export interface TreeNode {
  name: string;
  path: string; // workspace-relative
  kind: "dir" | "file";
  children?: TreeNode[];
  mtime?: string; // ISO; file only
  bytes?: number; // file only
  visitId?: string; // file only — present for files under rollout_summaries/
}

export interface DreamTreeResponse {
  root: string; // absolute (server-side debug only); UI renders "memory/users/<u>/"
  lastDreamedAt: string | null;
  nodes: TreeNode[];
}

export interface DreamFileResponse {
  path: string;
  content: string;
  mtime: string;
  bytes: number;
}

export interface DreamRunSummary {
  id: string;
  scope: string;
  trigger: DreamTriggerKind;
  status: "running" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  endedAt: string | null;
  visitCount: number;
  filesUpdated: number;
  errorMessage: string | null;
}

/** One row for the "Recent visits" picker in DreamSidebar.  Lets the user
 *  trigger a per-visit dream without depending on whether the visit
 *  already has a `rollout_summaries/<id>.md` file in the tree. */
export interface DreamVisitOption {
  visitId: string;
  endedAt: string;
  startedAt: string;
  doctorName: string | null;
  /** First ~120 chars of `summaryMd` if one was generated during the
   *  visit; null otherwise.  Pure preview, not the full summary. */
  summaryPreview: string | null;
  /** True if `rollout_summaries/<visitId>.md` already exists — UI shows
   *  a "●" dot so the user can tell which visits already have memory. */
  hasMemoryFile: boolean;
  /** Length of the captured transcript (utterance count). 0 means the
   *  visit was abandoned mid-start; the picker hides those, but we still
   *  return the field for the UI to render "6m · 124 utt" stats. */
  utteranceCount: number;
  durationSec: number;
}
