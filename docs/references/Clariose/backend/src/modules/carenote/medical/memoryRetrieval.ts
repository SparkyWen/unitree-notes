// MemoryRetrievalService — confirmed-only memory retrieval.
//
// MVP implementation: in-memory store. The interface mirrors what a real
// Postgres-backed implementation would expose so callers don't change.

export type ConfirmedMemoryHit = {
  memory_id: string;
  memory_type:
    | "allergy"
    | "medication"
    | "condition"
    | "clinician"
    | "preference"
    | "visit_pattern"
    | "other";
  content: string;
  confidence: "high" | "medium" | "low";
  source_visit_id?: string;
  source_turn_ids?: string[];
  updated_at: string;
};

export interface MemoryRetrievalService {
  retrieve(input: {
    user_id: string;
    patient_id?: string;
    visit_id: string;
    query: string;
    max_results?: number;
    allowed_memory_status: "confirmed_only";
  }): Promise<ConfirmedMemoryHit[]>;
}

export class InMemoryMemoryRetrievalService implements MemoryRetrievalService {
  private items: ConfirmedMemoryHit[] = [];

  add(hit: ConfirmedMemoryHit): void {
    this.items.push(hit);
  }

  async retrieve(input: {
    user_id: string;
    patient_id?: string;
    visit_id: string;
    query: string;
    max_results?: number;
    allowed_memory_status: "confirmed_only";
  }): Promise<ConfirmedMemoryHit[]> {
    if (input.allowed_memory_status !== "confirmed_only") return [];
    // MVP: naive substring match plus most-recent-first.
    const q = input.query.toLowerCase();
    const matches = this.items
      .filter((h) => q.length === 0 || h.content.toLowerCase().includes(q))
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    return matches.slice(0, input.max_results ?? 8);
  }
}
