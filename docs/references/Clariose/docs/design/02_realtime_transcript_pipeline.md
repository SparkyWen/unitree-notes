# 02 — Realtime Transcript Pipeline

Date: 2026-04-29

## 1. Architectural intent

The Realtime pipeline is the **low-latency, sync** half of CareNote. Its
sole responsibility is to (a) get audio from the patient's device into
the OpenAI Realtime API safely, (b) catch transcript events, (c) order
them, and (d) hand finished turns to the (async) Codex harness.

Hard constraints:

- The patient device must never see `OPENAI_API_KEY`. The browser uses
  ephemeral Realtime credentials minted by our server.
- The pipeline must not block on Codex. Transcript turns are persisted
  and enqueued; Codex consumes asynchronously.
- The Realtime model is `gpt-realtime-1.5`. Audio output is configured
  but *muted by default*: `create_response = false`,
  `interrupt_response = false`.
- The transcription model is `gpt-4o-transcribe`. Language defaults to
  Chinese with English drug names preserved.

## 2. End-to-end flow

```
Browser microphone (WebRTC PeerConnection)
        │
        │   1. POST /api/realtime/session  (server-side broker)
        │   2. Server returns ephemeral Realtime client_secret + ICE config
        │   3. Browser opens RTCPeerConnection directly to api.openai.com
        │   4. Browser opens RTCDataChannel "oai-events"
        ▼
OpenAI Realtime API  ──── audio frames (browser → OpenAI)
        │
        │   transcript events on data channel:
        │     conversation.item.input_audio_transcription.delta
        │     conversation.item.input_audio_transcription.completed
        │     input_audio_buffer.committed
        │
        ▼
Browser data channel handler
        │   POST /api/visits/:visitId/realtime-events  (batched)
        ▼
RealtimeEventIngestor (server)
        │
        ▼
TranscriptAssembler (per-visit)  ──→  TranscriptEventBus
                                                │
                                                ▼
                                       CodexJobQueue (async)
```

Two important properties:

1. The **audio path is browser ↔ OpenAI**. The server never proxies
   audio. This is what `client_secret` is for.
2. The **event path is browser → server**. The browser forwards the
   transcript events to the server; the server is the source of truth
   for ordering and persistence.

## 3. Server-side session broker

`POST /api/realtime/session` returns a fresh ephemeral session.

Request:

```json
{
  "visit_id": "uuid",
  "language": "zh|en|mixed"
}
```

Response:

```json
{
  "session": {
    "id": "sess_...",
    "client_secret": { "value": "ephemeral...", "expires_at": "..." }
  },
  "ice_servers": [...],
  "config": { /* see §5 */ }
}
```

Server-side responsibilities:

1. Authenticate the user (existing Clariose JWT).
2. Verify the visit exists and is owned by the user.
3. Build the Realtime session config (§5).
4. Call OpenAI's `realtime.sessions.create` with the long-lived
   `OPENAI_API_KEY`.
5. Hand back the ephemeral `client_secret` to the browser.

The server never receives audio. If it did, we would have failed.

## 4. Client-side microphone flow

Pseudocode (frontend `useRealtime.ts`):

```ts
const { session, config } = await fetch("/api/realtime/session", ...);
const pc = new RTCPeerConnection({ iceServers });
const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
mic.getAudioTracks().forEach(t => pc.addTrack(t, mic));
const dc = pc.createDataChannel("oai-events");

dc.onmessage = (e) => handleRealtimeEvent(JSON.parse(e.data));

const offer = await pc.createOffer();
await pc.setLocalDescription(offer);

const sdpAnswer = await fetch(
  `https://api.openai.com/v1/realtime?model=${config.model}`,
  {
    method: "POST",
    body: offer.sdp,
    headers: {
      "Authorization": `Bearer ${session.client_secret.value}`,
      "Content-Type": "application/sdp"
    }
  }
).then(r => r.text());

await pc.setRemoteDescription({ type: "answer", sdp: sdpAnswer });
```

The data channel is the only place transcript events arrive on the
client. The client batches them and POSTs to the server every 250 ms (or
on every `completed` event, whichever comes first).

## 5. Realtime session config

```json
{
  "type": "realtime",
  "model": "gpt-realtime-1.5",
  "output_modalities": ["text"],
  "instructions": "<see prompts/realtimeSessionPrompt.ts>",
  "audio": {
    "input": {
      "transcription": {
        "model": "gpt-4o-transcribe",
        "language": "zh",
        "prompt": "<see prompts/transcriptionPrompt.ts>"
      },
      "noise_reduction": { "type": "near_field" },
      "turn_detection": {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 700,
        "create_response": false,
        "interrupt_response": false
      }
    },
    "output": { "voice": "marin" }
  },
  "include": ["item.input_audio_transcription.logprobs"]
}
```

`create_response = false` is the load-bearing default. It is what makes
CareNote silent during a doctor visit.

## 6. Transcript event types

```ts
type RealtimeTranscriptDeltaEvent = {
  type: "conversation.item.input_audio_transcription.delta";
  event_id?: string;
  item_id: string;
  content_index?: number;
  delta: string;
  logprobs?: unknown;
};

type RealtimeTranscriptCompletedEvent = {
  type: "conversation.item.input_audio_transcription.completed";
  event_id?: string;
  item_id: string;
  content_index?: number;
  transcript: string;
  logprobs?: unknown;
};

type RealtimeInputAudioBufferCommittedEvent = {
  type: "input_audio_buffer.committed";
  event_id?: string;
  item_id: string;
  previous_item_id?: string | null;
};
```

(Full set of types lives in
`backend/src/modules/carenote/realtime/realtimeEventTypes.ts`.)

## 7. Delta handling

`...delta` events arrive frequently for a single item.

`TranscriptAssembler.handleDelta(visit_id, event)`:

1. Look up `state[item_id]`. If absent, create
   `{ item_id, partial_transcript: "", status: "partial", created_at }`.
2. Append `event.delta` to `partial_transcript`.
3. Update `created_at` once on creation; do not reset.
4. Emit nothing yet. Deltas are not pushed to the bus; only completed
   turns are.

The frontend is free to read `partial_transcript` to show live text
without waiting for completion, but the **harness only sees completed
turns**.

## 8. Completed handling

`TranscriptAssembler.handleCompleted(visit_id, event)`:

1. Find `state[item_id]`. If absent (we missed the deltas), create one
   directly with `partial_transcript = event.transcript`.
2. Set `transcript = event.transcript`,
   `status = "completed"`, `completed_at = now()`.
3. Persist a `transcript_turns` row.
4. Reconstruct ordering (§9) and emit
   `doctor_visit.transcript_turn.completed` to the bus.

If the same `item_id` is completed twice (rare, but ASR retries happen),
the second event wins. We log a warning.

## 9. Ordering with `item_id` and `previous_item_id`

`previous_item_id` is the link in a chain. To produce an ordered list of
turns:

1. Build a map `next[previous_item_id] = item_id`.
2. Find the **head**: the item whose `previous_item_id` is null or
   absent from the map.
3. Walk the chain: `head → next[head] → next[next[head]] → ...`.
4. If a node has no `previous_item_id` link to anything in the map, it
   is a fragment; we append fragments at the tail in `created_at`
   order.

`ordering_confidence`:

- `"high"` if every completed turn participates in a single chain from
  the head.
- `"medium"` if there are at most two chains.
- `"low"` if the graph is disconnected and we are walking by
  `created_at`.

Confidence is recorded on the bus event so downstream agents (and the
UI) can flag uncertainty.

## 10. Fallback when ordering is incomplete

If `previous_item_id` is missing on every event (an OpenAI-side bug, or
an upstream change), we fall back to `created_at` order and set
`ordering_confidence = "low"`. The harness still functions; the
`transcript_quality` agent receives the low-confidence flag and is
expected to mention it.

## 11. VAD configuration

`server_vad` with the values listed in §5 are the documented defaults
for clinical-style speech with reasonable pauses:

- `threshold: 0.5` — moderate sensitivity.
- `prefix_padding_ms: 300` — capture the first 300ms before VAD trips.
- `silence_duration_ms: 700` — finalise the turn after 700ms of silence.

These are tunable per-language. We expose them in
`realtimeConfig.ts:buildRealtimeSessionConfig()` but do not change them
in MVP.

## 12. Noise reduction

`{ type: "near_field" }` is appropriate for a phone held close to the
patient. We do not switch to `far_field` automatically; the user can
override via the API in a later iteration.

## 13. `create_response = false` default behaviour

- The Realtime model does not auto-respond after the user's turn.
- This means the AI never "talks over" the doctor.
- It also means we can't accidentally bill output audio tokens during a
  silent listening phase.
- The model still produces transcripts of the user's speech (that is the
  whole point of the session).

## 14. User-triggered summaries / explanations

The buttons on the recording UI translate to backend calls, not to
`response.create` events on the Realtime session:

- **"I did not understand"** →
  `POST /api/visits/:id/explain-recent` with `{ "n_turns": 5 }`. The
  backend pulls the last N turns, calls the harness's clarification
  agent (or final-summary in "stage" mode), returns plain-language text.
- **"Generate stage summary"** →
  `POST /api/visits/:id/stage-summary`. Backend runs final-summary
  agent over the current state.
- **"What should I ask?"** →
  `POST /api/visits/:id/clarifying-questions`. Backend re-runs the
  safety_clarification role with the most recent state.
- **"End visit and summarize"** →
  `POST /api/visits/:id/final-summary`.

Importantly, none of these go through the Realtime model; they all go
through the Codex harness. This keeps the realtime audio loop pure.

## 15. Persistence

Per turn we write a `transcript_turns` row with the schema in Doc 03 §9.
Raw audio is **not** persisted unless the user explicitly enabled "Save
raw audio" at start; the realtime session does not produce a recording
on our side anyway, so to enable raw-audio capture we would need a
client-side `MediaRecorder` and a separate upload, which is out of MVP
scope.

## 16. Failure modes & recovery

| Failure | Recovery |
|---|---|
| ICE / WebRTC connection drops | Browser retries; on a fresh session, the visit gets a new chain head — we mark the boundary with `ordering_confidence = "medium"`. |
| Server broker can't reach OpenAI | UI shows error; user retries. No partial state is ingested. |
| Transcript event delivery fails (POST 5xx) | Browser retries with exponential backoff. Events are idempotent on `(visit_id, item_id)`. |
| Two devices try to attach to one visit | Reject the second; one visit, one connection. |
| The user clicks End Visit before all deltas have completed | Wait up to 2 seconds for trailing `completed` events; then close. Any later events for this visit are ignored. |

## 17. Privacy boundary on this side

- Raw transcripts are persisted server-side (necessary for the harness
  to work).
- Server logs **redact transcript text** unless `DEBUG_CARENOTE_PHI=true`
  (default false).
- Raw audio is not persisted by default and not by the server.
- The ephemeral `client_secret` is short-lived and cannot be reused.

This concludes the Realtime pipeline design. Doc 03 picks up where this
ends, at the moment a `doctor_visit.transcript_turn.completed` event
hits the bus.
