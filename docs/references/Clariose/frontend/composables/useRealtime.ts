/**
 * useRealtime — owns the OpenAI Realtime session lifecycle in the browser.
 *
 * Flow:
 *   1.  Caller invokes `start()`.
 *   2.  We POST /api/realtime/sessions to mint an *ephemeral* client_secret
 *       (the server holds the real key; the browser never sees it).
 *   3.  We open a WebRTC peer to https://api.openai.com/v1/realtime, attach
 *       the user's microphone, and listen for `conversation.item.input_audio_transcription.*`
 *       events on the data channel.
 *   4.  Final transcripts are POSTed to our backend for agent fan-out.
 *
 * The composable exposes a tiny reactive surface:
 *   - state          'idle' | 'connecting' | 'listening' | 'paused' | 'error'
 *   - utterances     Final transcripts so far
 *   - partial        Current in-flight partial
 *   - level          Coarse mic level (0–1) for the orb halo
 *   - sessionId      Backend ConsultSession id (once minted)
 */
type Utterance = {
  id: string;
  speaker: 'doctor' | 'patient' | 'unknown';
  text: string;
  startedAt: number;
  isFinal: boolean;
};

export function useRealtime() {
  const api = useApi();

  const state = ref<'idle' | 'connecting' | 'listening' | 'paused' | 'error'>('idle');
  const utterances = ref<Utterance[]>([]);
  const partial = ref<string>('');
  const level = ref<number>(0);
  const sessionId = ref<string | null>(null);
  const errorMessage = ref<string | null>(null);

  let pc: RTCPeerConnection | null = null;
  let dc: RTCDataChannel | null = null;
  let mediaStream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let levelTimer: number | null = null;
  let startedAt = 0;

  async function mintEphemeralKey(): Promise<{ clientSecret: string; sessionId: string; model: string }> {
    return api.post('/realtime/sessions', { kind: 'consult' });
  }

  async function start() {
    if (state.value === 'listening' || state.value === 'connecting') return;
    state.value = 'connecting';
    errorMessage.value = null;

    try {
      const { clientSecret, sessionId: sid, model } = await mintEphemeralKey();
      sessionId.value = sid;

      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      pc = new RTCPeerConnection();

      // Outbound: send mic.
      mediaStream.getAudioTracks().forEach(t => pc!.addTrack(t, mediaStream!));

      // Inbound: ignore the model's voice (we only need transcription) but
      // still attach a sink so the connection is symmetric.
      pc.ontrack = () => { /* no playback */ };

      // Data channel carries text events (transcripts, function calls, etc.)
      dc = pc.createDataChannel('oai-events');
      dc.onmessage = handleEvent;
      dc.onopen = () => {
        // Configure the session: audio in, text out, server-side VAD,
        // input transcription powered by gpt-4o-transcribe (or whisper).
        dc!.send(JSON.stringify({
          type: 'session.update',
          session: {
            modalities: ['text'],
            input_audio_transcription: { model: 'gpt-4o-transcribe' },
            turn_detection: { type: 'server_vad', threshold: 0.5, silence_duration_ms: 600 },
            instructions:
              'You are a silent transcription assistant. Do not speak. Only transcribe what you hear.',
          },
        }));
      };

      // Audio meter
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

      const sdpResp = await fetch(`https://api.openai.com/v1/realtime?model=${encodeURIComponent(model)}`, {
        method: 'POST',
        body: offer.sdp,
        headers: { Authorization: `Bearer ${clientSecret}`, 'Content-Type': 'application/sdp' },
      });
      if (!sdpResp.ok) throw new Error(`Realtime SDP exchange failed: ${sdpResp.status}`);
      const answer = { type: 'answer', sdp: await sdpResp.text() } as RTCSessionDescriptionInit;
      await pc.setRemoteDescription(answer);

      startedAt = Date.now();
      state.value = 'listening';
    } catch (err: any) {
      console.error('[realtime] start failed', err);
      errorMessage.value = err?.message ?? 'Could not start realtime session';
      state.value = 'error';
      await stop();
    }
  }

  async function stop() {
    if (levelTimer != null) { clearInterval(levelTimer); levelTimer = null; }
    try { dc?.close(); } catch {}
    try { pc?.close(); } catch {}
    mediaStream?.getTracks().forEach(t => t.stop());
    if (audioCtx && audioCtx.state !== 'closed') await audioCtx.close();
    pc = null; dc = null; mediaStream = null; audioCtx = null; analyser = null;
    if (state.value !== 'error') state.value = 'idle';
    level.value = 0;
    partial.value = '';
  }

  function pause() {
    if (state.value !== 'listening') return;
    mediaStream?.getAudioTracks().forEach(t => (t.enabled = false));
    state.value = 'paused';
  }
  function resume() {
    if (state.value !== 'paused') return;
    mediaStream?.getAudioTracks().forEach(t => (t.enabled = true));
    state.value = 'listening';
  }

  function toggle() {
    if (state.value === 'idle' || state.value === 'error') return start();
    if (state.value === 'listening') return pause();
    if (state.value === 'paused')    return resume();
  }

  function handleEvent(ev: MessageEvent) {
    let payload: any;
    try { payload = JSON.parse(ev.data); } catch { return; }

    switch (payload.type) {
      // Live partial transcript while the user is still talking.
      case 'conversation.item.input_audio_transcription.delta':
        partial.value += payload.delta ?? '';
        break;

      // Final transcript for one utterance.
      case 'conversation.item.input_audio_transcription.completed': {
        const text = (payload.transcript || '').trim();
        if (!text) { partial.value = ''; break; }
        const u: Utterance = {
          id: payload.item_id || crypto.randomUUID(),
          // Heuristic: alternate speaker every utterance. The backend can
          // refine this later via diarisation.
          speaker: utterances.value.at(-1)?.speaker === 'doctor' ? 'patient' : 'doctor',
          text,
          startedAt: Date.now() - startedAt,
          isFinal: true,
        };
        utterances.value = [...utterances.value, u];
        partial.value = '';
        if (sessionId.value) {
          // The DTO whitelists only realtimeItemId|id|speaker|text|startedAt
          // and `forbidNonWhitelisted: true` — so we strip `isFinal` (and the
          // local-only fields) before POSTing. Surface errors instead of
          // swallowing them: a silent 400 here is exactly why the agent
          // pipeline went quiet for a whole consult last time.
          const body = { id: u.id, speaker: u.speaker, text: u.text, startedAt: u.startedAt };
          api.post(`/sessions/${sessionId.value}/utterances`, body).catch(err => {
            console.error('[realtime] utterance POST failed', err);
            errorMessage.value = `Transcript not saved: ${err?.message ?? err}`;
          });
        }
        break;
      }

      case 'error':
        errorMessage.value = payload.error?.message ?? 'Realtime error';
        state.value = 'error';
        break;
    }
  }

  onBeforeUnmount(() => { stop(); });

  /**
   * Inject a prompt into the active gpt-realtime data channel so the model
   * speaks/types it back into the room. Used by the team's
   * ClarificationQuestion agent: when a HIGH-severity question needs a
   * doctor's answer, we push it through the realtime peer instead of waiting
   * until the consult ends.
   *
   * Returns true if the message was sent. The caller (the consult page) is
   * responsible for showing the user a confirm prompt before calling this —
   * we never auto-inject.
   */
  function pushAssistantPrompt(text: string): boolean {
    if (!dc || dc.readyState !== 'open') return false;
    try {
      dc.send(JSON.stringify({
        type: 'response.create',
        response: {
          modalities: ['text'],
          instructions:
            `Politely ask the doctor in the room the following clarification, ` +
            `then go silent again: ${text}`,
        },
      }));
      return true;
    } catch {
      return false;
    }
  }

  return {
    state, utterances, partial, level, sessionId, errorMessage,
    start, stop, pause, resume, toggle, pushAssistantPrompt,
  };
}
