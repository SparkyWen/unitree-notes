// Realtime transcript event types. These mirror the OpenAI Realtime API
// event shapes that we forward from the browser to the server.
//
// We only declare the events the harness consumes. The full Realtime
// event surface (response.* / session.* / etc.) is much larger and is
// handled by the browser-side data-channel listener; the server only
// cares about the input-audio-transcription pipeline.

export type RealtimeTranscriptDeltaEvent = {
  type: "conversation.item.input_audio_transcription.delta";
  event_id?: string;
  item_id: string;
  content_index?: number;
  delta: string;
  logprobs?: unknown;
};

export type RealtimeTranscriptCompletedEvent = {
  type: "conversation.item.input_audio_transcription.completed";
  event_id?: string;
  item_id: string;
  content_index?: number;
  transcript: string;
  logprobs?: unknown;
};

export type RealtimeTranscriptFailedEvent = {
  type: "conversation.item.input_audio_transcription.failed";
  event_id?: string;
  item_id: string;
  error?: { message?: string; type?: string };
};

export type RealtimeInputAudioBufferCommittedEvent = {
  type: "input_audio_buffer.committed";
  event_id?: string;
  item_id: string;
  previous_item_id?: string | null;
};

export type RealtimeIngestEvent =
  | RealtimeTranscriptDeltaEvent
  | RealtimeTranscriptCompletedEvent
  | RealtimeTranscriptFailedEvent
  | RealtimeInputAudioBufferCommittedEvent;

export type OrderingConfidence = "high" | "medium" | "low";

// The single bus event the assembler emits.
export type DoctorVisitTranscriptTurnCompleted = {
  event_type: "doctor_visit.transcript_turn.completed";
  event_id: string;
  visit_id: string;
  turn: {
    item_id: string;
    previous_item_id?: string | null;
    transcript: string;
    speaker_label?: "doctor" | "patient" | "family" | "unknown";
    ordering_confidence?: OrderingConfidence;
  };
  source: {
    provider: "openai";
    api: "realtime";
    realtime_model: "gpt-realtime-1.5";
    transcription_model: string;
  };
  created_at: string;
};
