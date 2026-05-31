// CLARIOSE_V01 §4.2 Phase 2 — sideQuery: ask a small LLM which manifest
// entries are relevant to the current turn.
//
// Model: gpt-5.4-mini-2026-03-17 (user-specified). Configurable via env so
// we can swap to gpt-4o-mini etc. without code change. Output contract is a
// strict JSON array of relPath strings (we use response_format: json_object
// with a wrapper { selected: string[] } since that's the broadly-supported
// shape).

import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import OpenAI from "openai";

import {
  SIDEQUERY_MAX_OUTPUT_TOKENS,
  SIDEQUERY_MAX_RESULTS,
  SIDEQUERY_MODEL_DEFAULT,
} from "./recall.constants";
import type { ManifestEntry, SideQueryInput } from "./recall.types";

@Injectable()
export class MemorySideQueryService {
  private readonly logger = new Logger("MemorySideQuery");
  private _client: OpenAI | null = null;

  constructor(private readonly cfg: ConfigService) {}

  isEnabled(): boolean {
    if (this.cfg.get<string>("CARENOTE_RECALL_ENABLED") === "false") return false;
    return !!this.cfg.get<string>("OPENAI_API_KEY");
  }

  modelName(): string {
    return (
      this.cfg.get<string>("CARENOTE_SIDEQUERY_MODEL") ?? SIDEQUERY_MODEL_DEFAULT
    );
  }

  private client(): OpenAI {
    if (!this._client) {
      this._client = new OpenAI({
        apiKey: this.cfg.get<string>("OPENAI_API_KEY") ?? "sk-missing",
      });
    }
    return this._client;
  }

  /**
   * Returns the manifest entries the side-LLM judged relevant. On any
   * failure (timeout, parse error, empty manifest) returns []. Never throws.
   */
  async select(input: SideQueryInput): Promise<ManifestEntry[]> {
    if (input.manifest.length === 0) return [];
    if (!this.isEnabled()) return [];

    const topN = input.topN ?? SIDEQUERY_MAX_RESULTS;

    const system = [
      "You are a medical-memory retriever for a doctor-visit assistant.",
      "You receive (a) a short query/topic and (b) a manifest of available memory files about ONE patient.",
      "Return ONLY the most relevant files for the query. Prefer files whose keywords or descriptions clearly relate.",
      "Output MUST be a JSON object of the form: {\"selected\": [\"rel/path/one.md\", \"rel/path/two.md\"]}.",
      `Choose at most ${topN} files. If nothing is clearly relevant, return {\"selected\": []}.`,
    ].join("\n");

    const manifestStr = input.manifest
      .map((e) => {
        const kw = e.keywords.length ? ` keywords=[${e.keywords.join(",")}]` : "";
        return `- relPath="${e.relPath}" scope=${e.scope}${kw} :: ${e.description}`;
      })
      .join("\n");

    const userMsg = [
      `Query: ${input.query.slice(0, 1500)}`,
      "",
      `Recently used: ${(input.recentTools ?? []).join(", ") || "(none)"}`,
      "",
      "Manifest:",
      manifestStr,
    ].join("\n");

    let raw: string;
    try {
      const resp = await this.client().chat.completions.create({
        model: this.modelName(),
        max_tokens: SIDEQUERY_MAX_OUTPUT_TOKENS,
        response_format: { type: "json_object" },
        messages: [
          { role: "system", content: system },
          { role: "user", content: userMsg },
        ],
      });
      raw = resp.choices[0]?.message?.content ?? "";
    } catch (err) {
      this.logger.warn(
        `sideQuery LLM call failed (${this.modelName()}): ${(err as Error).message}`,
      );
      return [];
    }

    let parsed: { selected?: unknown };
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      this.logger.warn(
        `sideQuery JSON parse failed: ${(err as Error).message}; raw=${raw.slice(0, 200)}`,
      );
      return [];
    }
    if (!parsed || !Array.isArray(parsed.selected)) return [];

    const wantSet = new Set(
      (parsed.selected as unknown[])
        .filter((s): s is string => typeof s === "string")
        .map((s) => s.trim()),
    );
    return input.manifest.filter((m) => wantSet.has(m.relPath));
  }
}
