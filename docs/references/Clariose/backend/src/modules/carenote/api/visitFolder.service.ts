// VisitFolderService — on-disk layout for a CareNote visit.
//
//   data/carenote/visits/<visit_id>/
//     visit.json                    snapshot of meta + state at last write
//     round-001/
//       transcripts.json            all transcript turns whose item_id is in
//                                   rounds[N].turn_item_ids, in order
//       agent-state.json            facts/questions/reminders/flags for this
//                                   round (filtered by source_turn_ids)
//       recap.json                  TeamRecap text payload for this round
//       recap.png                   infographic for this round (if rendered)
//       asks/                       ask-doctor TTS audio + transcripts
//         <ask_id>.mp3
//         <ask_id>.json
//
// CLARIOSE_V02 §turn-folders — the user explicitly asked for "整轮对话保存
// 为一个文件夹, 每一次pause生成的每一次turn的所有的transcript都可以放在
// 该turn的子文件夹中". This service is the only writer.

import { Injectable, Logger } from "@nestjs/common";
import { existsSync, mkdirSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { VisitState, VisitRound } from "../medical/medicalSchemas";

const VISITS_ROOT_REL = ".data/carenote/visits";

@Injectable()
export class VisitFolderService {
  private readonly logger = new Logger("VisitFolder");
  private readonly root: string;

  constructor() {
    // CLARIOSE_DATA_ROOT lets dev/test point writes outside the prod tree.
    const override = process.env.CLARIOSE_DATA_ROOT?.trim();
    this.root = override
      ? resolve(override, "carenote/visits")
      : resolve(__dirname, "../../../../..", VISITS_ROOT_REL);
    if (!existsSync(this.root)) mkdirSync(this.root, { recursive: true });
  }

  visitDir(visit_id: string): string {
    const dir = resolve(this.root, sanitize(visit_id));
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    return dir;
  }

  roundDir(visit_id: string, round_index: number): string {
    const dir = resolve(this.visitDir(visit_id), formatRound(round_index));
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    return dir;
  }

  asksDir(visit_id: string, round_index: number): string {
    const dir = resolve(this.roundDir(visit_id, round_index), "asks");
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    return dir;
  }

  /** Filesystem path for a TTS audio blob. Caller writes the bytes. */
  askAudioPath(visit_id: string, round_index: number, ask_id: string): string {
    return resolve(this.asksDir(visit_id, round_index), `${sanitize(ask_id)}.mp3`);
  }

  /** Path relative to visitDir, suitable for storing in VisitState. */
  askAudioRelpath(round_index: number, ask_id: string): string {
    return `${formatRound(round_index)}/asks/${sanitize(ask_id)}.mp3`;
  }

  /**
   * Write a snapshot of one round's slice of VisitState. Called when a
   * round closes (endRound) and again when the visit ends. Idempotent —
   * later writes overwrite earlier ones for the same round.
   */
  async writeRoundSnapshot(state: VisitState, round_index: number): Promise<void> {
    const round = state.rounds.find((r) => r.index === round_index);
    if (!round) return;
    const dir = this.roundDir(state.visit_id, round_index);

    const turnIds = new Set(round.turn_item_ids);
    const turns = state.turns.filter((t) => turnIds.has(t.item_id));
    const inRound = (sourceIds: string[] | undefined): boolean =>
      Array.isArray(sourceIds) && sourceIds.some((id) => turnIds.has(id));

    const agent_state = {
      round_index,
      facts: state.facts.filter((f: any) => inRound(f.source_turn_ids)),
      clarifying_questions: state.clarifying_questions.filter((q: any) =>
        inRound(q.source_turn_ids),
      ),
      draft_tasks: state.draft_tasks.filter((t: any) => inRound(t.source_turn_ids)),
      draft_reminders: state.draft_reminders.filter((r: any) =>
        inRound(r.source_turn_ids),
      ),
      safety_flags: state.safety_flags.filter((s: any) =>
        inRound(s.source_turn_ids),
      ),
      transcript_verifications: state.transcript_verifications.filter(
        (v: any) => turnIds.has(v.turn_id) || inRound(v.source_turn_ids),
      ),
      caregiver_notifications: state.caregiver_notifications.filter((n: any) =>
        n.turn_id ? turnIds.has(n.turn_id) : inRound(n.source_turn_ids),
      ),
    };

    const ask_logs = state.ask_doctor_logs.filter((a) => a.round_index === round_index);

    await writeFile(
      resolve(dir, "transcripts.json"),
      JSON.stringify(
        {
          visit_id: state.visit_id,
          round_index,
          started_at: round.started_at,
          ended_at: round.ended_at,
          turn_count: turns.length,
          turns,
        },
        null,
        2,
      ),
    );
    await writeFile(
      resolve(dir, "agent-state.json"),
      JSON.stringify(agent_state, null, 2),
    );
    await writeFile(resolve(dir, "asks.json"), JSON.stringify(ask_logs, null, 2));
  }

  /** Write the visit-level snapshot (whole VisitState). Cheap; ~10 KB. */
  async writeVisitSnapshot(state: VisitState): Promise<void> {
    await writeFile(
      resolve(this.visitDir(state.visit_id), "visit.json"),
      JSON.stringify(state, null, 2),
    );
  }

  /**
   * Drop a per-round recap.json + recap.png next to that round's folder.
   * Recap may contain an `image_path` pointing into the global recap dir;
   * we copy it locally so each round has a self-contained folder.
   */
  async writeRoundRecap(
    visit_id: string,
    round_index: number,
    recap_json: unknown,
  ): Promise<string> {
    const dir = this.roundDir(visit_id, round_index);
    const path = resolve(dir, "recap.json");
    await writeFile(path, JSON.stringify(recap_json, null, 2));
    return path;
  }

  recapJsonPath(visit_id: string, round_index: number): string {
    return resolve(this.roundDir(visit_id, round_index), "recap.json");
  }

  recapImagePath(visit_id: string, round_index: number): string {
    return resolve(this.roundDir(visit_id, round_index), "recap.png");
  }
}

function sanitize(id: string): string {
  return id.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function formatRound(idx: number): string {
  return `round-${String(idx).padStart(3, "0")}`;
}
