/**
 * useRealtimeVisit — drives the CareNote Realtime pipeline in the browser.
 *
 * Differs from `useRealtime` (the legacy Clariose consult flow):
 *   • Bound to a CareNote `visit_id` (already created via /api/visits).
 *   • Does not assume the AI will speak: `create_response: false`.
 *   • Forwards every interesting Realtime event to the server-side
 *     `/api/visits/:visitId/realtime-events` endpoint, which feeds the
 *     Codex harness queue.
 *   • Maintains a tiny local "partial / completed" buffer for instant
 *     UI feedback before the Codex turn completes.
 *
 * The OpenAI API key never reaches the browser; we mint a short-lived
 * `client_secret` via `/api/realtime/session`.
 */

type ConnState = "idle" | "connecting" | "listening" | "paused" | "ended" | "error";

export type VisitTurn = {
  item_id: string;
  partial: string;
  transcript: string | null;
  status: "partial" | "completed" | "failed";
  startedAt: number;
};

export type RealtimeDiagnostics = {
  dataChannelState: "absent" | "connecting" | "open" | "closing" | "closed";
  lastEventType: string | null;
  committedCount: number;
  deltaCount: number;
  completedCount: number;
  failedCount: number;
  lastCompletedTranscript: string | null;
  lastIngestStatus: "ok" | "error" | null;
  lastIngestError: string | null;
  lastTranscriptionFailedError: string | null;
  lastOpenAiError: string | null;
  lastDuplicate: boolean;
};

export function useRealtimeVisit(visitId: Ref<string | null> | string) {
  const api = useApi();

  const visitIdRef = (typeof visitId === "string"
    ? ref(visitId)
    : visitId) as Ref<string | null>;

  const state = ref<ConnState>("idle");
  const error = ref<string | null>(null);
  const partial = ref<string>("");
  const turns = ref<VisitTurn[]>([]);
  const level = ref(0);
  const diagnostics = ref<RealtimeDiagnostics>({
    dataChannelState: "absent",
    lastEventType: null,
    committedCount: 0,
    deltaCount: 0,
    completedCount: 0,
    failedCount: 0,
    lastCompletedTranscript: null,
    lastIngestStatus: null,
    lastIngestError: null,
    lastTranscriptionFailedError: null,
    lastOpenAiError: null,
    lastDuplicate: false,
  });

  let pc: RTCPeerConnection | null = null;
  let dc: RTCDataChannel | null = null;
  let mediaStream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let levelTimer: number | null = null;
  let startedAt = 0;

  async function start() {
    const visit_id = visitIdRef.value;
    if (!visit_id) {
      error.value = "visit_id is required";
      state.value = "error";
      return;
    }
    if (state.value === "listening" || state.value === "connecting") return;

    state.value = "connecting";
    error.value = null;

    try {
      const session = await api.post<{
        visit_id: string;
        client_secret: string;
        expires_at: number;
        model: string;
        config: { audio: { input: { transcription: { model: string; language: string } } } };
      }>("/realtime/session", { visit_id, mode: "doctor_visit" });

      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      pc = new RTCPeerConnection();
      mediaStream.getAudioTracks().forEach((t) => pc!.addTrack(t, mediaStream!));
      pc.ontrack = () => { /* CareNote never plays AI voice */ };

      dc = pc.createDataChannel("oai-events");
      dc.onmessage = handleEvent;
      dc.onclose = () => { diagnostics.value.dataChannelState = "closed"; };
      dc.onerror = () => { diagnostics.value.dataChannelState = "closed"; };
      diagnostics.value.dataChannelState = "connecting";
      dc.onopen = () => {
        diagnostics.value.dataChannelState = "open";
        // Re-assert the session config (the broker already configured it,
        // but Realtime accepts a `session.update` to make values explicit
        // and visible in the data-channel trace).
        const tx = session.config?.audio?.input?.transcription;
        dc!.send(
          JSON.stringify({
            type: "session.update",
            session: {
              modalities: ["text"],
              input_audio_transcription: tx
                ? { model: tx.model, language: tx.language }
                : { model: "gpt-4o-transcribe" },
              turn_detection: {
                type: "server_vad",
                threshold: 0.5,
                silence_duration_ms: 700,
                create_response: false,
                interrupt_response: false,
              },
            },
          }),
        );
      };

      // mic level for the orb
      audioCtx = new AudioContext();
      const src = audioCtx.createMediaStreamSource(mediaStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      levelTimer = window.setInterval(() => {
        analyser!.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        level.value = Math.sqrt(sum / buf.length);
      }, 80);

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const sdpResp = await fetch(
        `https://api.openai.com/v1/realtime?model=${encodeURIComponent(session.model)}`,
        {
          method: "POST",
          body: offer.sdp,
          headers: {
            Authorization: `Bearer ${session.client_secret}`,
            "Content-Type": "application/sdp",
          },
        },
      );
      if (!sdpResp.ok) {
        const txt = await sdpResp.text().catch(() => "");
        throw new Error(`Realtime SDP exchange failed: ${sdpResp.status} ${txt}`);
      }
      const answer: RTCSessionDescriptionInit = {
        type: "answer",
        sdp: await sdpResp.text(),
      };
      await pc.setRemoteDescription(answer);

      startedAt = Date.now();
      state.value = "listening";
    } catch (err: any) {
      console.error("[carenote-realtime] start failed", err);
      error.value = err?.message ?? "Could not start Realtime session";
      state.value = "error";
      await stop();
    }
  }

  async function stop() {
    if (levelTimer != null) {
      clearInterval(levelTimer);
      levelTimer = null;
    }
    try { dc?.close(); } catch { /* ignore */ }
    try { pc?.close(); } catch { /* ignore */ }
    mediaStream?.getTracks().forEach((t) => t.stop());
    if (audioCtx && audioCtx.state !== "closed") {
      try { await audioCtx.close(); } catch { /* ignore */ }
    }
    pc = null;
    dc = null;
    mediaStream = null;
    audioCtx = null;
    analyser = null;
    level.value = 0;
    if (state.value !== "error") state.value = "ended";
  }

  function pause() {
    if (state.value !== "listening") return;
    mediaStream?.getAudioTracks().forEach((t) => (t.enabled = false));
    state.value = "paused";
  }
  function resume() {
    if (state.value !== "paused") return;
    mediaStream?.getAudioTracks().forEach((t) => (t.enabled = true));
    state.value = "listening";
  }

  function handleEvent(ev: MessageEvent) {
    let payload: any;
    try { payload = JSON.parse(ev.data); } catch { return; }

    const visit_id = visitIdRef.value;
    if (!visit_id) return;

    diagnostics.value.lastEventType = payload?.type ?? null;

    switch (payload.type) {
      case "input_audio_buffer.committed": {
        diagnostics.value.committedCount += 1;
        upsertTurn(payload.item_id, {
          previous_item_id: payload.previous_item_id ?? null,
          status: "partial",
        });
        forwardEvent(visit_id, payload);
        break;
      }
      case "input_audio_buffer.speech_started": {
        partial.value = "";
        forwardEvent(visit_id, payload);
        break;
      }
      case "input_audio_buffer.speech_stopped": {
        forwardEvent(visit_id, payload);
        break;
      }
      case "conversation.item.input_audio_transcription.delta": {
        diagnostics.value.deltaCount += 1;
        partial.value += payload.delta ?? "";
        upsertTurn(payload.item_id, {
          partial: (currentTurn(payload.item_id)?.partial ?? "") + (payload.delta ?? ""),
        });
        forwardEvent(visit_id, payload);
        break;
      }
      case "conversation.item.input_audio_transcription.completed": {
        diagnostics.value.completedCount += 1;
        const text = (payload.transcript || "").trim();
        if (text) {
          upsertTurn(payload.item_id, { transcript: text, status: "completed" });
          partial.value = "";
          diagnostics.value.lastCompletedTranscript = text;
        }
        forwardEvent(visit_id, payload);
        break;
      }
      case "conversation.item.input_audio_transcription.failed": {
        diagnostics.value.failedCount += 1;
        diagnostics.value.lastTranscriptionFailedError =
          payload.error?.message ?? payload.error?.type ?? "transcription failed";
        upsertTurn(payload.item_id, { status: "failed" });
        forwardEvent(visit_id, payload);
        break;
      }
      case "error": {
        const msg = payload.error?.message ?? "Realtime error";
        error.value = msg;
        diagnostics.value.lastOpenAiError = msg;
        state.value = "error";
        // Forward errors to backend so transcript_stats.last_error
        // can light up the diagnostics panel for ops debugging.
        forwardEvent(visit_id, payload);
        break;
      }
    }
  }

  function currentTurn(item_id: string): VisitTurn | undefined {
    return turns.value.find((t) => t.item_id === item_id);
  }

  function upsertTurn(item_id: string, patch: Partial<VisitTurn> & { previous_item_id?: string | null }) {
    const idx = turns.value.findIndex((t) => t.item_id === item_id);
    if (idx === -1) {
      turns.value = [
        ...turns.value,
        {
          item_id,
          partial: patch.partial ?? "",
          transcript: patch.transcript ?? null,
          status: (patch.status ?? "partial") as VisitTurn["status"],
          startedAt: Date.now() - (startedAt || Date.now()),
        },
      ];
      return;
    }
    const next = { ...turns.value[idx], ...patch } as VisitTurn;
    turns.value = [...turns.value.slice(0, idx), next, ...turns.value.slice(idx + 1)];
  }

  function forwardEvent(visit_id: string, event: unknown): void {
    api
      .post<{ accepted: boolean; emitted_transcript_turn: boolean; job_id: string | null; duplicate?: boolean }>(
        `/visits/${visit_id}/realtime-events`,
        { event },
      )
      .then((res) => {
        diagnostics.value.lastIngestStatus = "ok";
        diagnostics.value.lastIngestError = null;
        diagnostics.value.lastDuplicate = res?.duplicate === true;
      })
      .catch((err) => {
        diagnostics.value.lastIngestStatus = "error";
        diagnostics.value.lastIngestError = err?.message ?? String(err);
        console.warn("[carenote-realtime] ingest failed", err);
      });
  }

  onBeforeUnmount(() => { void stop(); });

  return {
    state,
    error,
    partial,
    turns,
    level,
    diagnostics,
    start,
    stop,
    pause,
    resume,
  };
}
