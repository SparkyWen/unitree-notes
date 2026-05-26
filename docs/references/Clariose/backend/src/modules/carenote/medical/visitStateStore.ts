// In-memory VisitState store. MVP only. The CodexRunManager talks to
// this via two callback functions, so swapping to Postgres is one file
// change.

import { VisitStateSchema, type VisitState } from "./medicalSchemas";

export class InMemoryVisitStateStore {
  private byVisit = new Map<string, VisitState>();

  ensure(
    visit_id: string,
    language: VisitState["language"] = "en",
    output_language: VisitState["language"] = language,
  ): VisitState {
    let v = this.byVisit.get(visit_id);
    if (!v) {
      const now = new Date().toISOString();
      v = VisitStateSchema.parse({
        visit_id,
        language,
        output_language,
        status: "new",
        // Round 0 is opened immediately so the first transcript event has
        // a bucket to land in. Subsequent rounds are opened by endRound().
        current_round_index: 0,
        rounds: [
          {
            index: 0,
            started_at: now,
            ended_at: null,
            turn_item_ids: [],
            recap_headline: null,
            recap_generated_at: null,
          },
        ],
        ask_doctor_logs: [],
        turns: [],
        facts: [],
        draft_tasks: [],
        draft_reminders: [],
        clarifying_questions: [],
        family_summary_deltas: [],
        memory_candidates: [],
        safety_flags: [],
        guardrail_blocked: [],
      });
      this.byVisit.set(visit_id, v);
    }
    return v;
  }

  async get(visit_id: string): Promise<VisitState> {
    return this.ensure(visit_id);
  }

  async set(visit_id: string, next: VisitState): Promise<void> {
    this.byVisit.set(visit_id, next);
  }

  delete(visit_id: string): void {
    this.byVisit.delete(visit_id);
  }
}
