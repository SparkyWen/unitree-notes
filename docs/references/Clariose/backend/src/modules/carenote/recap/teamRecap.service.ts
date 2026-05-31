// TeamRecapService — pause-driven retrospective for the visit's care team.
//
// What it does:
//   1. Aggregates the latest VisitState (already populated by the per-turn
//      Codex agent fan-out) into a tight, glanceable digest:
//        • headline:  one-sentence "what happened in this visit"
//        • highlight_facts:  3–5 bullets the doctor & patient must agree on
//        • watch_outs:  high-severity safety_flags + transcription_uncertain
//        • must_ask:   top clarifying questions (priority=high first)
//        • next_steps: confirmed reminders/tasks + scheduled follow-ups
//   2. Produces an at-a-glance INFOGRAPHIC PNG by calling the OpenAI image
//      model (`gpt-image-2-2026-04-21` per product spec). The prompt is
//      tuned for medical-recap cards that read in <5 seconds.
//   3. Stores the digest + the on-disk image path in an in-memory map and
//      writes a JSON sidecar so survives PM2 reloads.
//
// Idempotent: a second call replaces both files atomically. Returns the
// same shape whether OpenAI succeeds or fails (the image_url field becomes
// null when the image step failed; the digest text is always present).

import { existsSync, mkdirSync } from "node:fs";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import {
  Injectable,
  Logger,
  NotFoundException,
  ServiceUnavailableException,
} from "@nestjs/common";
import { ConfigService } from "@nestjs/config";

import type { VisitState } from "../medical/medicalSchemas";

// The summary model used for the textual digest. `OPENAI_AGENT_MODEL` env
// override is honored to match the rest of the agent fleet.
const DEFAULT_SUMMARY_MODEL = "gpt-4o-mini";

// Image model. The newer `gpt-image-1` API ALWAYS returns b64_json and
// rejects `response_format` (Unknown parameter), unlike the older
// dall-e-3 endpoint. Override via OPENAI_IMAGE_MODEL when needed.
const RECAP_IMAGE_MODEL = "gpt-image-1";

export type RecapBullet = { text: string; emphasis: "normal" | "warning" };

export type TeamRecap = {
  visit_id: string;
  /** Which pause-cycle this recap describes. Set by generateForRound. */
  round_index: number | null;
  generated_at: string;
  headline: string;
  highlight_facts: RecapBullet[];
  watch_outs: RecapBullet[];
  must_ask: string[];
  next_steps: string[];
  image_path: string | null;
  image_status: "ready" | "skipped" | "failed";
  image_error: string | null;
};

type DigestJson = {
  headline: string;
  highlight_facts: RecapBullet[];
  watch_outs: RecapBullet[];
  must_ask: string[];
  next_steps: string[];
};

@Injectable()
export class TeamRecapService {
  private readonly logger = new Logger("TeamRecap");
  private readonly cache = new Map<string, TeamRecap>();
  private readonly recapDir: string;

  constructor(private readonly cfg: ConfigService) {
    // CLARIOSE_DATA_ROOT lets dev/test point writes outside the prod tree.
    const override = process.env.CLARIOSE_DATA_ROOT?.trim();
    this.recapDir = override
      ? resolve(override, "carenote/recaps")
      : resolve(__dirname, "../../../../..", ".data/carenote/recaps");
    if (!existsSync(this.recapDir)) {
      mkdirSync(this.recapDir, { recursive: true });
    }
  }

  imagePathFor(visit_id: string, round_index?: number): string {
    if (typeof round_index === "number") {
      return resolve(
        this.recapDir,
        `${sanitize(visit_id)}_r${String(round_index).padStart(3, "0")}.png`,
      );
    }
    return resolve(this.recapDir, `${sanitize(visit_id)}.png`);
  }

  jsonPathFor(visit_id: string, round_index?: number): string {
    if (typeof round_index === "number") {
      return resolve(
        this.recapDir,
        `${sanitize(visit_id)}_r${String(round_index).padStart(3, "0")}.json`,
      );
    }
    return resolve(this.recapDir, `${sanitize(visit_id)}.json`);
  }

  /** Return a previously generated recap, or null. Lazy-loads from disk.
   *  Looks at: (1) in-memory cache (most-recent round wins), (2) all per-round
   *  json sidecars on disk, (3) the legacy unsuffixed file. The frontend's
   *  per-visit "team_recap" slot uses this for backward-compat. */
  async get(visit_id: string): Promise<TeamRecap | null> {
    const all = await this.listAll(visit_id);
    if (all.length) return all[all.length - 1]!;
    return null;
  }

  /** Enumerate every recap on disk for this visit, ordered by round_index
   *  ascending (legacy unsuffixed file gets round_index = -1 so it sorts
   *  first). Lets the UI render every pause-cycle's image and digest in
   *  order, instead of only seeing the most recent one. */
  async listAll(visit_id: string): Promise<TeamRecap[]> {
    const safe = sanitize(visit_id);
    let entries: string[] = [];
    try {
      entries = await readdir(this.recapDir);
    } catch {
      return [];
    }
    const matching = entries
      .filter(
        (n) => n === `${safe}.json` || n.startsWith(`${safe}_r`) && n.endsWith(".json"),
      )
      .sort();

    const out: TeamRecap[] = [];
    for (const name of matching) {
      try {
        const raw = await readFile(resolve(this.recapDir, name), "utf8");
        const parsed = JSON.parse(raw) as TeamRecap;
        const cacheKey =
          typeof parsed.round_index === "number"
            ? `${visit_id}#${parsed.round_index}`
            : visit_id;
        this.cache.set(cacheKey, parsed);
        out.push(parsed);
      } catch {
        // skip unreadable / partially-written sidecars
      }
    }
    return out;
  }

  /**
   * Produce a fresh recap from the current VisitState. Always returns a
   * digest. Image generation is best-effort: when OPENAI_API_KEY is not
   * configured (or the image model is unavailable) image_status === "failed".
   */
  /**
   * CLARIOSE_V02 — recap for one round only. Filters facts/questions/etc.
   * by source_turn_ids ⊂ rounds[N].turn_item_ids so each pause-cycle
   * gets its own digest instead of restating the full visit each time.
   */
  async generateForRound(
    visit_id: string,
    state: VisitState,
    round_index: number,
  ): Promise<TeamRecap> {
    const sliced = sliceStateForRound(state, round_index);
    const recap = await this.generateInternal(visit_id, sliced, round_index);
    return recap;
  }

  async generate(visit_id: string, state: VisitState): Promise<TeamRecap> {
    return this.generateInternal(visit_id, state);
  }

  private async generateInternal(
    visit_id: string,
    state: VisitState,
    round_index?: number,
  ): Promise<TeamRecap> {
    if (!state || !state.visit_id) {
      throw new NotFoundException(`visit state missing for ${visit_id}`);
    }
    const digest = await this.buildDigest(state);
    let imageStatus: TeamRecap["image_status"] = "skipped";
    let imageError: string | null = null;
    let imagePath: string | null = null;

    const apiKey = this.cfg.get<string>("OPENAI_API_KEY");
    if (apiKey) {
      try {
        const png = await this.renderInfographic(apiKey, state, digest);
        imagePath = this.imagePathFor(visit_id, round_index);
        await writeFile(imagePath, png);
        imageStatus = "ready";
      } catch (err) {
        imageStatus = "failed";
        imageError = (err as Error).message;
        this.logger.warn(
          `recap image render failed visit=${visit_id}: ${imageError}`,
        );
      }
    }

    const recap: TeamRecap = {
      visit_id,
      round_index: typeof round_index === "number" ? round_index : null,
      generated_at: new Date().toISOString(),
      headline: digest.headline,
      highlight_facts: digest.highlight_facts,
      watch_outs: digest.watch_outs,
      must_ask: digest.must_ask,
      next_steps: digest.next_steps,
      image_path: imagePath,
      image_status: imageStatus,
      image_error: imageError,
    };
    const cacheKey =
      typeof round_index === "number" ? `${visit_id}#${round_index}` : visit_id;
    this.cache.set(cacheKey, recap);
    await writeFile(
      this.jsonPathFor(visit_id, round_index),
      JSON.stringify(recap, null, 2),
    );
    return recap;
  }

  // ---------------------------------------------------------------------------
  // Digest synthesis
  // ---------------------------------------------------------------------------

  /**
   * Best-effort LLM digest with a deterministic fallback. The fallback ranks
   * existing agent outputs without any model call — useful both for offline
   * dev and for not blocking the user when OpenAI is slow.
   */
  private async buildDigest(state: VisitState): Promise<DigestJson> {
    const baseline = this.deterministicDigest(state);
    const apiKey = this.cfg.get<string>("OPENAI_API_KEY");
    if (!apiKey) return baseline;

    const model =
      this.cfg.get<string>("OPENAI_RECAP_MODEL") ??
      this.cfg.get<string>("OPENAI_AGENT_MODEL") ??
      DEFAULT_SUMMARY_MODEL;

    const facts = (state.facts ?? []).map((f) => ({
      type: f.fact_type,
      text: f.original_text,
    }));
    const reminders = (state.draft_reminders ?? []).map((r) => ({
      title: r.title,
      medication: r.medication_name,
      dose: r.dose,
      frequency: r.frequency,
      duration: r.duration,
      missing: r.blocking_missing_fields ?? [],
    }));
    const safety = (state.safety_flags ?? []).map((s) => ({
      severity: s.severity,
      type: s.flag_type,
      message: s.message,
      action: s.recommended_user_action,
    }));
    const questions = (state.clarifying_questions ?? []).map((q) => ({
      priority: q.priority,
      question: q.question,
    }));
    const tasks = (state.draft_tasks ?? []).map((t) => ({
      type: t.task_type,
      title: t.title,
    }));

    // CLARIOSE_V02: render in the language the user wants to READ. Falls
    // back to the spoken language so legacy visits still work. The prompt
    // also instructs the model to keep medical jargon (drug names, dosages)
    // in their canonical form rather than transliterating them.
    const outLang = state.output_language ?? state.language ?? "en";
    const langDirective =
      outLang === "zh"
        ? "Write all output in Simplified Chinese. Keep drug names, dosages,"
          + " and brand names in their canonical Latin form."
        : outLang === "mixed"
        ? "Write in plain English with key medical terms preserved. Use"
          + " parenthetical Chinese only if the patient explicitly mentioned"
          + " a Chinese term."
        : "Write all output in plain English.";

    const prompt = [
      "You are the team-lead nurse writing a one-screen recap of a doctor",
      "visit for the patient and their family. Use plain language and",
      "concrete medical detail. No flowery language. No emojis.",
      "Every bullet is independently understandable in <5 seconds.",
      langDirective,
      "",
      "Output STRICT JSON with exactly these keys:",
      "  headline:        string ≤ 16 words.",
      "  highlight_facts: array of {text, emphasis} (3-5 items).",
      "                   emphasis is 'warning' for allergies/contraindications,",
      "                   else 'normal'.",
      "  watch_outs:      array of {text, emphasis} (≤4 items, 'warning' only).",
      "  must_ask:        array of strings, the top 3-5 questions to ask the",
      "                   doctor or pharmacist now (no duplicates).",
      "  next_steps:      array of strings, concrete actions in chronological",
      "                   order (≤5 items).",
      "",
      "Source data (already produced by per-turn agents):",
      JSON.stringify({ facts, reminders, safety, questions, tasks }, null, 2),
    ].join("\n");

    try {
      const resp = await fetch("https://api.openai.com/v1/chat/completions", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model,
          temperature: 0.2,
          response_format: { type: "json_object" },
          messages: [
            { role: "system", content: "You write tight, glanceable medical recaps." },
            { role: "user", content: prompt },
          ],
        }),
      });
      if (!resp.ok) {
        const txt = await resp.text().catch(() => "");
        throw new Error(`recap-digest ${resp.status} ${txt}`);
      }
      const data = (await resp.json()) as {
        choices: { message: { content: string } }[];
      };
      const json = JSON.parse(data.choices?.[0]?.message?.content ?? "{}");
      return mergeDigest(baseline, json);
    } catch (err) {
      this.logger.warn(`digest LLM failed, using fallback: ${(err as Error).message}`);
      return baseline;
    }
  }

  private deterministicDigest(state: VisitState): DigestJson {
    const meds = state.draft_reminders ?? [];
    const facts = state.facts ?? [];
    const flags = state.safety_flags ?? [];
    const questions = state.clarifying_questions ?? [];
    const tasks = state.draft_tasks ?? [];

    const allergies = facts.filter((f) => f.fact_type === "allergy");
    const symptoms = facts.filter((f) => f.fact_type === "symptom");

    const headlineParts: string[] = [];
    if (symptoms.length) headlineParts.push(symptoms[0]!.original_text);
    if (meds.length && meds[0]!.medication_name) {
      headlineParts.push(`prescribed ${meds[0]!.medication_name}`);
    }
    const headline = headlineParts.join(" — ") || "Visit recorded — review the highlights.";

    const highlight_facts: RecapBullet[] = [];
    for (const m of meds.slice(0, 2)) {
      const dose = [m.medication_name, m.dose, m.frequency, m.timing, m.duration]
        .filter(Boolean)
        .join(" · ");
      highlight_facts.push({
        text: dose || m.title,
        emphasis: m.blocking_missing_fields?.length ? "warning" : "normal",
      });
    }
    for (const a of allergies.slice(0, 2)) {
      highlight_facts.push({ text: `Allergy: ${a.original_text}`, emphasis: "warning" });
    }
    for (const s of symptoms.slice(0, 2)) {
      if (highlight_facts.length >= 5) break;
      highlight_facts.push({ text: s.original_text, emphasis: "normal" });
    }

    const watch_outs: RecapBullet[] = flags
      .slice(0, 4)
      .map((f) => ({ text: `${f.message} → ${f.recommended_user_action}`, emphasis: "warning" }));

    const must_ask = questions
      .filter((q) => q.priority === "high")
      .slice(0, 5)
      .map((q) => q.question);
    if (must_ask.length < 3) {
      for (const q of questions) {
        if (must_ask.length >= 5) break;
        if (!must_ask.includes(q.question)) must_ask.push(q.question);
      }
    }

    const next_steps: string[] = [];
    for (const t of tasks) {
      if (next_steps.length >= 5) break;
      next_steps.push(t.title);
    }

    return { headline, highlight_facts, watch_outs, must_ask, next_steps };
  }

  // ---------------------------------------------------------------------------
  // Image generation — gpt-image-2-2026-04-21
  // ---------------------------------------------------------------------------

  /**
   * Build the image prompt and call the OpenAI Images API. The prompt is
   * fully self-contained: it carries the recap data inline so the model
   * can render real text rather than placeholders. The visual brief is
   * tuned for "doctor + patient see this and instantly know what to do".
   */
  private async renderInfographic(
    apiKey: string,
    state: VisitState,
    digest: DigestJson,
  ): Promise<Buffer> {
    const prompt = buildImagePrompt(state, digest);
    const model =
      this.cfg.get<string>("OPENAI_IMAGE_MODEL") ?? RECAP_IMAGE_MODEL;
    // gpt-image-1 returns b64_json by default and rejects `response_format`.
    // Older dall-e endpoints accept it but also default to b64; we rely on
    // the default in both cases for forward-compat.
    const resp = await fetch("https://api.openai.com/v1/images/generations", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        prompt,
        size: "1024x1024",
        n: 1,
      }),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      throw new ServiceUnavailableException(
        `images.generate ${resp.status} ${txt.slice(0, 400)}`,
      );
    }
    const data = (await resp.json()) as {
      data: { b64_json?: string; url?: string }[];
    };
    const b64 = data.data?.[0]?.b64_json;
    if (b64) return Buffer.from(b64, "base64");
    const url = data.data?.[0]?.url;
    if (url) {
      const fetched = await fetch(url);
      if (!fetched.ok) throw new Error(`image url fetch ${fetched.status}`);
      return Buffer.from(await fetched.arrayBuffer());
    }
    throw new Error("images.generate returned no payload");
  }
}

// -----------------------------------------------------------------------------
// helpers
// -----------------------------------------------------------------------------

function sanitize(id: string): string {
  return id.replace(/[^a-zA-Z0-9_-]/g, "_");
}

/**
 * CLARIOSE_V02 — return a VisitState whose facts/questions/reminders/etc.
 * only include rows whose source_turn_ids fall inside `round_index`. Lets
 * the digest LLM see exactly what was discussed in this pause-cycle, so
 * a 3-round visit produces 3 distinct recaps instead of 3 cumulative
 * over-summaries that drift toward sameness.
 */
function sliceStateForRound(state: VisitState, round_index: number): VisitState {
  const round = state.rounds.find((r) => r.index === round_index);
  if (!round) return state;
  const turnIds = new Set(round.turn_item_ids);
  const inRound = (sourceIds: string[] | undefined): boolean =>
    Array.isArray(sourceIds) && sourceIds.some((id) => turnIds.has(id));
  return {
    ...state,
    turns: state.turns.filter((t) => turnIds.has(t.item_id)),
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
}

function mergeDigest(baseline: DigestJson, llm: Partial<DigestJson>): DigestJson {
  return {
    headline: typeof llm.headline === "string" && llm.headline.trim()
      ? llm.headline.trim()
      : baseline.headline,
    highlight_facts: arrayOrFallback(llm.highlight_facts, baseline.highlight_facts).map(
      (b: any): RecapBullet => ({
        text: String(b?.text ?? "").trim(),
        emphasis: b?.emphasis === "warning" ? "warning" : "normal",
      }),
    ).filter((b: RecapBullet) => b.text.length > 0).slice(0, 5),
    watch_outs: arrayOrFallback(llm.watch_outs, baseline.watch_outs).map(
      (b: any) => ({
        text: String(b?.text ?? "").trim(),
        emphasis: "warning" as const,
      }),
    ).filter((b: RecapBullet) => b.text.length > 0).slice(0, 4),
    must_ask: arrayOrFallback(llm.must_ask, baseline.must_ask)
      .map((s: any) => String(s ?? "").trim())
      .filter((s: string) => s.length > 0)
      .slice(0, 5),
    next_steps: arrayOrFallback(llm.next_steps, baseline.next_steps)
      .map((s: any) => String(s ?? "").trim())
      .filter((s: string) => s.length > 0)
      .slice(0, 5),
  };
}

function arrayOrFallback<T>(maybe: unknown, fallback: T[]): T[] {
  return Array.isArray(maybe) && maybe.length > 0 ? (maybe as T[]) : fallback;
}

/**
 * Build the gpt-image-2 prompt. We supply the literal text the image must
 * render so the model isn't free-styling content. The visual brief enforces:
 *
 *   - poster-style "visit recap card" layout with named regions, so the
 *     reader's eye lands on the headline, then the medication strip, then
 *     watch-outs, then questions — the doctor-patient priority order.
 *   - high contrast, calm clinical palette, no decorative photography.
 *   - no logos, no real-looking patient names, no emoji icons (model
 *     usually renders these poorly), only flat geometric icons.
 *   - explicit "render every word verbatim" instruction so the model uses
 *     real characters instead of glyph-soup.
 */
function buildImagePrompt(state: VisitState, digest: DigestJson): string {
  const language = state.language === "zh" ? "Simplified Chinese" : "English";
  const lines: string[] = [
    "Design a single-page medical visit RECAP CARD for a patient and their family,",
    "rendered as a clean editorial infographic poster. Square 1024x1024.",
    "",
    "Audience: patient + family caregiver. Read time target: under 5 seconds.",
    "Tone: calm, trustworthy, clinical-professional — like a hospital discharge sheet.",
    `Language: ${language}. Render every word VERBATIM — do not invent or rephrase.`,
    "",
    "LAYOUT (top to bottom):",
    "  1. Header strip (12% height): a small medical-cross icon on the left,",
    "     the title 'VISIT RECAP' in bold tracked caps on the right.",
    "  2. Headline band (15% height): one large sentence, weight 700, line-height 1.1.",
    "  3. KEY FACTS panel (28% height): up to 5 bullets in two columns.",
    "     Bullets marked 'warning' get a soft amber pill behind them and a small triangle icon;",
    "     'normal' bullets get a plain dot.",
    "  4. WATCH-OUTS panel (18% height): up to 4 bullets on a soft rose background,",
    "     each prefixed with a small alert-triangle glyph.",
    "  5. ASK THE DOCTOR panel (15% height): up to 5 short questions, each preceded",
    "     by a small question-mark glyph.",
    "  6. NEXT STEPS panel (12% height): up to 5 short imperatives, each",
    "     preceded by a small numbered chip 1,2,3…",
    "",
    "VISUAL RULES:",
    "  - Background: warm off-white (#F7F4EE).",
    "  - Primary ink: near-black (#1B1B1A). Accent: muted teal (#1F6F6B).",
    "  - Warning accent: muted amber (#B5651D); danger pill: rose-50.",
    "  - Generous white-space between panels (≥24 px).",
    "  - Use one humanist sans-serif throughout (Inter / Söhne style).",
    "  - No photographs, no stock illustrations, no decorative icons inside the body text,",
    "    no logos, no watermarks, no fake QR codes, no patient name, no doctor name.",
    "  - Geometric flat glyphs only (cross, triangle, question mark, dot, numbered chip).",
    "  - Crisp typography, sharp edges, slight grid alignment.",
    "  - The poster MUST be readable at 50% zoom on a phone.",
    "",
    "EXACT TEXT TO RENDER (do not paraphrase):",
    `  Title: VISIT RECAP`,
    `  Headline: ${digest.headline}`,
    "  Key facts:",
    ...digest.highlight_facts.map(
      (b, i) => `    ${i + 1}. (${b.emphasis}) ${b.text}`,
    ),
    "  Watch-outs:",
    ...(digest.watch_outs.length
      ? digest.watch_outs.map((b, i) => `    ${i + 1}. ${b.text}`)
      : ["    (none — write 'No safety alerts flagged.')"]),
    "  Ask the doctor:",
    ...(digest.must_ask.length
      ? digest.must_ask.map((q, i) => `    ${i + 1}. ${q}`)
      : ["    (none — write 'No open questions.')"]),
    "  Next steps:",
    ...(digest.next_steps.length
      ? digest.next_steps.map((s, i) => `    ${i + 1}. ${s}`)
      : ["    (none — write 'Awaiting confirmation.')"]),
    "",
    "OUTPUT: a single rendered poster. No frame, no caption, no extra text outside the panels.",
    "Critical: every word above must appear in the rendered image, exactly once, in the correct panel.",
  ];
  return lines.join("\n");
}
