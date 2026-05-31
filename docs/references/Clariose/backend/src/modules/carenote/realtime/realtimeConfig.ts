// Realtime session config builder. Exposed so the broker controller can
// pass these defaults to OpenAI's `realtime.sessions.create` and the
// frontend can read them back.
//
// Important defaults:
//  - `create_response: false` — the AI never auto-responds. CareNote is
//    silent during a visit unless the user explicitly asks for a summary.
//  - `interrupt_response: false` — the AI never interrupts the doctor.
//  - `output_modalities: ["text"]` — voice output is configured but not
//    triggered.

export type RealtimeLanguage = "zh" | "en" | "mixed";

export type CareNoteRealtimeConfig = {
  type: "realtime";
  model: "gpt-realtime-1.5";
  output_modalities: ["text"];
  instructions: string;
  audio: {
    input: {
      transcription: {
        model: string;
        language: string;
        prompt: string;
      };
      noise_reduction: { type: "near_field" };
      turn_detection: {
        type: "server_vad";
        threshold: number;
        prefix_padding_ms: number;
        silence_duration_ms: number;
        create_response: boolean;
        interrupt_response: boolean;
      };
    };
    output: { voice: string };
  };
  include: string[];
};

export function buildRealtimeSessionConfig(input: {
  language: RealtimeLanguage;
  sessionInstructions: string;
  transcriptionPrompt: string;
  transcriptionModel?: string;
  voice?: string;
}): CareNoteRealtimeConfig {
  const lang =
    input.language === "en" ? "en" : input.language === "mixed" ? "zh" : "zh";
  return {
    type: "realtime",
    model: "gpt-realtime-1.5",
    output_modalities: ["text"],
    instructions: input.sessionInstructions,
    audio: {
      input: {
        transcription: {
          model: input.transcriptionModel ?? "gpt-4o-transcribe",
          language: lang,
          prompt: input.transcriptionPrompt,
        },
        noise_reduction: { type: "near_field" },
        turn_detection: {
          type: "server_vad",
          threshold: 0.5,
          prefix_padding_ms: 300,
          silence_duration_ms: 700,
          create_response: false,
          interrupt_response: false,
        },
      },
      output: { voice: input.voice ?? "marin" },
    },
    include: ["item.input_audio_transcription.logprobs"],
  };
}
