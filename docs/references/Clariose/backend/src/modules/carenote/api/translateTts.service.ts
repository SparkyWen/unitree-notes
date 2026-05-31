// TranslateTtsService — patient → doctor reverse translation + TTS.
//
// Use case (CLARIOSE_V02): the patient or family member doesn't speak good
// English. They type a follow-up question in their native language; we
// translate it to English and synthesize speech with gpt-4o-mini-tts so
// they can play the audio out loud and the doctor hears the question
// in clear English.
//
// We deliberately do NOT auto-play the audio — the visit page hands the
// patient a "Speak to doctor" button so they're in control of when the
// audio fires (e.g., wait until the doctor stops talking).
//
// When OPENAI_API_KEY is missing, this service surfaces a 503 — there is
// no useful fallback for "say this in English" without a model. The rest
// of the visit page keeps working.

import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import {
  Injectable,
  Logger,
  ServiceUnavailableException,
  BadRequestException,
} from "@nestjs/common";
import { ConfigService } from "@nestjs/config";

import { VisitFolderService } from "./visitFolder.service";

// Per the user spec — gpt-4o-mini-tts release tag from 2025-12-15.
const TTS_MODEL = "gpt-4o-mini-tts-2025-12-15";
const DEFAULT_TRANSLATION_MODEL = "gpt-4o-mini";
// Kind, clinical-default voice — neutral pitch, warm but not perky.
const TTS_VOICE = "alloy";

export type AskDoctorResult = {
  ask_id: string;
  source_language: string;
  source_text: string;
  translated_text: string;
  audio_relpath: string;
  audio_url: string;
  duration_ms: number;
  created_at: string;
};

@Injectable()
export class TranslateTtsService {
  private readonly logger = new Logger("TranslateTts");

  constructor(
    private readonly cfg: ConfigService,
    private readonly folder: VisitFolderService,
  ) {}

  /**
   * Translate `source_text` (in `source_language`) → English, then run TTS
   * over the English translation. Audio is written into the round's
   * `asks/` subfolder; caller (CareNoteService) records the metadata into
   * VisitState.ask_doctor_logs and persists.
   */
  async ask(input: {
    visit_id: string;
    round_index: number;
    source_language: string;
    source_text: string;
  }): Promise<AskDoctorResult> {
    const text = input.source_text.trim();
    if (!text) throw new BadRequestException("source_text required");
    if (text.length > 1500) {
      throw new BadRequestException("source_text too long (max 1500 chars)");
    }

    const apiKey = this.cfg.get<string>("OPENAI_API_KEY");
    if (!apiKey) {
      throw new ServiceUnavailableException(
        "OPENAI_API_KEY required for translate-TTS",
      );
    }

    const translated = await this.translateToEnglish(
      apiKey,
      input.source_language,
      text,
    );

    const ask_id = `ask_${Date.now().toString(36)}_${randomUUID().slice(0, 6)}`;
    const audioPath = this.folder.askAudioPath(
      input.visit_id,
      input.round_index,
      ask_id,
    );
    const audio_relpath = this.folder.askAudioRelpath(input.round_index, ask_id);

    const audioStartedAt = Date.now();
    const audioBytes = await this.synthesize(apiKey, translated);
    await writeFile(audioPath, audioBytes);
    const duration_ms = Date.now() - audioStartedAt;

    const audio_url = `/api/visits/${encodeURIComponent(input.visit_id)}/asks/${encodeURIComponent(ask_id)}/audio`;
    return {
      ask_id,
      source_language: input.source_language,
      source_text: text,
      translated_text: translated,
      audio_relpath,
      audio_url,
      duration_ms,
      created_at: new Date().toISOString(),
    };
  }

  // ---------------------------------------------------------------------------
  // Translation — chat-completions with strict "translate only, no commentary"
  // ---------------------------------------------------------------------------

  private async translateToEnglish(
    apiKey: string,
    source_language: string,
    text: string,
  ): Promise<string> {
    const model =
      this.cfg.get<string>("OPENAI_TRANSLATE_MODEL") ??
      this.cfg.get<string>("OPENAI_AGENT_MODEL") ??
      DEFAULT_TRANSLATION_MODEL;

    const sys = [
      "You are a medical interpreter helping a non-English-speaking patient",
      "ask their doctor a question in clear, polite English. The patient just",
      "wrote the question below in their own language. Output ONLY the English",
      "translation — no preamble, no quotes, no notes. Keep medical terms",
      "(drug names, dosages, anatomy) precise. Preserve the patient's tone:",
      "questions stay questions; first-person stays first-person. If the",
      "input is already in English, return it lightly cleaned up.",
    ].join(" ");

    const user = [
      `Source language: ${source_language || "auto-detect"}`,
      "Source text:",
      text,
    ].join("\n");

    const resp = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        temperature: 0.1,
        messages: [
          { role: "system", content: sys },
          { role: "user", content: user },
        ],
      }),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      this.logger.warn(`translate ${resp.status} ${txt}`);
      throw new ServiceUnavailableException("Translation failed");
    }
    const data = (await resp.json()) as {
      choices?: { message?: { content?: string } }[];
    };
    const out = (data.choices?.[0]?.message?.content ?? "").trim();
    if (!out) {
      throw new ServiceUnavailableException("Empty translation");
    }
    return stripQuoteWrap(out);
  }

  // ---------------------------------------------------------------------------
  // TTS — gpt-4o-mini-tts-2025-12-15
  // ---------------------------------------------------------------------------

  private async synthesize(apiKey: string, text: string): Promise<Buffer> {
    const resp = await fetch("https://api.openai.com/v1/audio/speech", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: TTS_MODEL,
        voice: TTS_VOICE,
        input: text,
        format: "mp3",
        // A short per-utterance instruction nudges the model toward the
        // calm, plainly-paced "patient asking a doctor" register.
        instructions:
          "Read aloud in clear, polite, conversational English at a calm pace, "
          + "as a patient politely asking their doctor a question.",
      }),
    });
    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      this.logger.warn(`tts ${resp.status} ${txt}`);
      throw new ServiceUnavailableException("TTS failed");
    }
    const buf = Buffer.from(await resp.arrayBuffer());
    if (buf.byteLength < 64) {
      throw new ServiceUnavailableException("TTS returned empty audio");
    }
    return buf;
  }
}

function stripQuoteWrap(s: string): string {
  // The model occasionally wraps the translation in quotes despite the
  // "no quotes" instruction. Strip a single matching pair.
  const t = s.trim();
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    return t.slice(1, -1).trim();
  }
  return t;
}
