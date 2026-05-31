# 01 — CareNote Product Requirements

Date: 2026-04-29

## 1. Product positioning

CareNote is a **doctor-visit memory assistant**. It is not an AI doctor.

The product solves one problem: a patient (or their family) leaves a
clinic with an incomplete or unclear understanding of what was said. They
forget medication names, miss the dose, miss the next appointment, miss
the warning signs. CareNote sits in the patient's pocket and remembers.

The product is **not** any of:

- a diagnosis engine;
- a clinical decision support system;
- a prescription system;
- a treatment recommender;
- a triage system;
- a replacement for doctors, pharmacists, or emergency services.

Every output is either a **transcript record** of what was said, or a
**draft** of an action that the user must explicitly confirm.

## 2. Target user

- **Primary**: a patient or close family member who has a smartphone or
  laptop with a microphone, basic literacy in Chinese or English, and a
  recurring need to attend medical visits (chronic illness, elderly
  parent care, paediatric care).
- **Secondary**: family members at home who did not attend the visit and
  want a clear summary.

We do not target clinicians as a primary user. CareNote does not produce
clinical-grade documentation.

## 3. User flows (MVP)

### 3.1 Pre-visit

1. User opens CareNote.
2. User sees a consent screen explaining what is recorded, what is
   transcribed, and what is stored.
3. User toggles **"Save raw audio"**. Default is OFF.
4. User picks the visit language (Chinese / English / mixed).
5. User taps **Start Visit**.

### 3.2 During the visit

1. The browser/mobile client opens a server-mediated WebRTC session to
   the OpenAI Realtime API (model `gpt-realtime-1.5`).
2. Audio flows directly from the device to OpenAI; the server only mints
   ephemeral credentials. The long-lived `OPENAI_API_KEY` never reaches
   the client.
3. The Realtime API emits transcription events
   (`...input_audio_transcription.delta` and `.completed`).
4. The client streams partial transcripts to the user's screen.
5. Each completed transcript turn is posted to the backend's transcript
   ingest endpoint and pushed onto the Transcript Event Bus.
6. The Codex-only harness consumes turns asynchronously and produces:
   - extracted facts (medication, follow-up, test, allergy, …);
   - clarifying questions to ask;
   - safety flags;
   - draft tasks.
7. The UI updates incrementally as the harness produces results.
8. The user can tap context buttons:
   - **"I did not understand"** — request a plain-language explanation
     of the last few turns.
   - **"Mark important"** — pin the current turn.
   - **"Generate stage summary"** — synthesise a summary now.
   - **"What should I ask?"** — ask the harness for a question list.

The AI is silent unless one of these buttons is pressed. The Realtime
session is created with `create_response = false` and
`interrupt_response = false`.

### 3.3 End of visit

1. User taps **End Visit**.
2. The Realtime peer connection is closed.
3. The harness runs `final_visit_summary` over the ordered turns and
   accumulated state.
4. The UI shows:
   - plain-language summary;
   - medications (with `status = needs_confirmation` if any field
     missing);
   - follow-up tasks;
   - tests / referrals;
   - questions to ask the doctor or pharmacist;
   - family summary;
   - safety flags;
   - memory candidates.
5. For each draft, the user can confirm, edit, or reject.
6. **No reminder, calendar event, or long-term memory write happens
   without explicit user confirmation.**
7. The user can delete the entire visit (including transcript) with a
   single button.

### 3.4 Post-visit

1. Confirmed reminders move to the user's reminder list.
2. Confirmed memory candidates move to the patient's confirmed-memory
   store and become available as `memory_context` for future visits.
3. The family summary can be exported / shared from the user's device.
   CareNote does not auto-send messages to family.

## 4. What CareNote does

- Captures audio and converts it to a structured transcript with
  speaker-role hints.
- Extracts only what is explicitly said.
- Produces drafts for medication reminders, follow-up tasks, family
  summary, and long-term memory candidates.
- Suggests clarifying questions for the doctor or pharmacist.
- Flags missing or uncertain fields.
- Provides plain-language explanations on demand.
- Stores everything locally to the host (Postgres + filesystem) by
  default.

## 5. What CareNote must never do

- Produce a diagnosis.
- Produce a prescription.
- Recommend starting, stopping, or changing medication.
- Judge whether the doctor is correct.
- Triage emergencies. Anything sounding like an emergency must be
  redirected to a doctor / urgent care / local emergency number with no
  triage opinion attached.
- Auto-create reminders, calendar events, or memory entries before the
  user has confirmed them.
- Write raw audio to disk unless the user explicitly enabled it.
- Log raw transcript content in infrastructure logs unless
  `DEBUG_CARENOTE_PHI=true` (default false).
- Share visit data with family without an explicit user-side share
  action.

## 6. MVP scope

In MVP we ship:

- One patient, one device, one visit at a time.
- Realtime transcript pipeline (browser WebRTC + server broker).
- TranscriptEventBus + TranscriptAssembler.
- Codex-only harness with the 11 agent roles defined in Doc 03.
- Persistent agent team manifest + thread store.
- Schema-validated, guardrail-checked draft outputs.
- A minimal UI to start / record / end / confirm.
- Confirmed-memory retrieval (read-only).
- Local Postgres persistence of visits, turns, runs, drafts, memory.

We do **not** ship in MVP:

- Multi-tenant cloud deployment.
- Push notifications / SMS / email reminders (the user's existing
  reminder list is enough).
- Family-side accounts.
- Clinician-side dashboards.
- Insurance / billing integration.
- Voice synthesis (the AI is silent in MVP).
- Mobile app (web only is fine).
- E2EE.

## 7. Success criteria

The MVP succeeds if all of the following hold:

1. A user can complete a 10-minute simulated doctor visit with no
   interruption.
2. The transcript appears on screen with <2s latency on completed
   turns.
3. After end-of-visit, the harness produces:
   - at least the medications mentioned in the script;
   - at least one follow-up draft if the script contains a follow-up;
   - clarifying questions for any medication missing dose, frequency,
     or duration;
   - a family summary;
   - safety flags for any uncertain ASR token of a drug name.
4. No fact appears in the output without `source_turn_ids`.
5. No medication reminder appears with `requires_user_confirmation`
   anywhere except `true`.
6. No memory candidate is committed to long-term memory without an
   explicit confirm action.
7. The harness's behaviour is reproducible by running the mock
   transcript fixtures (Doc 08) — same input, equivalent output (allowing
   for LLM noise on prose fields, but the structural schema is stable).
8. Tearing down a visit removes all visit-scoped data on demand.

## 8. Non-goals (explicit)

- We do not aim to be HIPAA-compliant in this iteration. We document
  the privacy boundary and the gaps; production hardening is a later
  workstream.
- We do not aim to support every Realtime audio model. We pick
  `gpt-realtime-1.5` and `gpt-4o-transcribe` and freeze them.
- We do not aim to support providers other than OpenAI for the audio
  pipeline or Codex for the harness.

## 9. Out-of-band assumptions

- The deployment host has a working Codex CLI on `PATH` and either:
  - `~/.codex/auth.json` from `codex login --device-auth`; or
  - `OPENAI_API_KEY` in env (a documented, less-preferred fallback).
- The deployment host has a working `OPENAI_API_KEY` for the Realtime
  session broker; this key is server-only and never reaches the client.
- The deployment host has Postgres + Redis (already required by the
  Clariose stack).
