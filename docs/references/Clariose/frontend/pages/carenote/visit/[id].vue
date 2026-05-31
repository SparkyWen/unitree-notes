<template>
  <div class="mx-auto max-w-3xl px-4 py-8">
    <header class="flex items-center justify-between">
      <h1 class="text-xl font-semibold">Recording visit</h1>
      <span class="text-xs text-neutral-500">visit: {{ visitId }}</span>
    </header>

    <!-- Connection state strip -->
    <div class="mt-4 grid grid-cols-3 gap-3 text-sm">
      <div class="rounded-md bg-neutral-50 p-3">
        <div class="text-xs uppercase text-neutral-500">connection</div>
        <div class="mt-1 font-medium">{{ realtime.state.value }}</div>
      </div>
      <div class="rounded-md bg-neutral-50 p-3">
        <div class="text-xs uppercase text-neutral-500">codex queue</div>
        <div class="mt-1 font-medium">
          {{ jobs.pending }} pending · {{ jobs.in_flight }} running
        </div>
      </div>
      <div class="rounded-md bg-neutral-50 p-3">
        <div class="text-xs uppercase text-neutral-500">elapsed</div>
        <div class="mt-1 font-medium">{{ elapsed }}s</div>
      </div>
    </div>

    <!-- Realtime Transcript Debug -->
    <section class="mt-6 rounded-md border border-neutral-200 bg-neutral-50/60 p-3 text-xs font-mono">
      <div class="mb-1 text-[10px] uppercase tracking-wide text-neutral-500">
        Realtime Transcript Debug
      </div>
      <div class="grid grid-cols-2 gap-x-4 gap-y-1 md:grid-cols-3">
        <div>data channel: <span class="text-neutral-700">{{ realtime.diagnostics.value.dataChannelState }}</span></div>
        <div>last event: <span class="text-neutral-700">{{ realtime.diagnostics.value.lastEventType ?? "—" }}</span></div>
        <div>committed: <span class="text-neutral-700">{{ realtime.diagnostics.value.committedCount }}</span></div>
        <div>delta: <span class="text-neutral-700">{{ realtime.diagnostics.value.deltaCount }}</span></div>
        <div>completed: <span class="text-neutral-700">{{ realtime.diagnostics.value.completedCount }}</span></div>
        <div>failed: <span class="text-neutral-700">{{ realtime.diagnostics.value.failedCount }}</span></div>
        <div>ingest: <span :class="realtime.diagnostics.value.lastIngestStatus === 'error' ? 'text-red-600' : 'text-neutral-700'">{{ realtime.diagnostics.value.lastIngestStatus ?? "—" }}</span></div>
        <div>duplicate: <span class="text-neutral-700">{{ realtime.diagnostics.value.lastDuplicate ? "yes" : "no" }}</span></div>
        <div>server completed: <span class="text-neutral-700">{{ state?.transcript_stats?.completed_count ?? 0 }}</span></div>
      </div>
      <div class="mt-2 break-words">
        <div>last transcript: <span class="text-neutral-800">{{ realtime.diagnostics.value.lastCompletedTranscript ?? state?.transcript_stats?.last_completed_transcript ?? "—" }}</span></div>
        <div v-if="realtime.diagnostics.value.lastIngestError" class="text-red-600">ingest error: {{ realtime.diagnostics.value.lastIngestError }}</div>
        <div v-if="realtime.diagnostics.value.lastTranscriptionFailedError" class="text-amber-700">transcription failed: {{ realtime.diagnostics.value.lastTranscriptionFailedError }}</div>
        <div v-if="realtime.diagnostics.value.lastOpenAiError" class="text-red-600">openai error: {{ realtime.diagnostics.value.lastOpenAiError }}</div>
        <div v-if="state?.transcript_stats?.last_error" class="text-red-600">server last_error: {{ state.transcript_stats.last_error }}</div>
      </div>
    </section>

    <!-- Controls -->
    <div class="mt-4 flex flex-wrap items-center gap-2">
      <button
        v-if="realtime.state.value === 'idle'"
        @click="realtime.start()"
        class="rounded-md bg-neutral-900 px-3 py-2 text-sm text-white"
      >
        Start recording
      </button>
      <button
        v-if="realtime.state.value === 'listening'"
        @click="onPause"
        class="rounded-md border border-neutral-300 px-3 py-2 text-sm"
      >
        Pause &amp; recap (round {{ currentRoundIndex + 1 }})
      </button>
      <button
        v-if="realtime.state.value === 'paused'"
        @click="onResume"
        class="rounded-md border border-neutral-300 px-3 py-2 text-sm"
      >
        Start round {{ currentRoundIndex + 1 }}
      </button>
      <button
        @click="onTeamRecap"
        :disabled="recapBusy"
        class="rounded-md border border-teal-600 px-3 py-2 text-sm text-teal-700 hover:bg-teal-50 disabled:opacity-50"
      >
        {{ recapBusy ? "Generating recap…" : "Recap current round" }}
      </button>
      <button
        @click="onEnd"
        class="rounded-md bg-red-600 px-3 py-2 text-sm text-white"
      >
        End visit
      </button>
      <button
        type="button"
        @click="showTeamDetail = !showTeamDetail"
        class="rounded-md border border-neutral-300 px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-50"
        :title="showTeamDetail ? 'Collapse the team detail and show only follow-ups, recap, and the generated image' : 'Show the cartoon helpers, their drafts, and the team conversation'"
      >
        {{ showTeamDetail ? "Hide team detail" : "Show team detail" }}
      </button>
      <span class="ml-auto text-xs text-neutral-500">
        round {{ currentRoundIndex + 1 }} of {{ rounds.length }} · output: {{ outputLanguageLabel }}
      </span>
    </div>

    <!-- CLARIOSE_V02 — Ask the doctor in your language. Patient types a
         follow-up in their own language; we translate to English and play
         the audio out loud. The doctor doesn't need to read anything. -->
    <section class="mt-6 rounded-2xl border border-amber-200 bg-amber-50/60 p-5">
      <div class="flex items-center justify-between">
        <h2 class="display text-lg leading-tight tracking-editorial">Ask the doctor (in your language)</h2>
        <span class="text-[11px] text-ink-500">round {{ currentRoundIndex + 1 }} · plays as English audio</span>
      </div>
      <p class="mt-1 text-xs text-ink-600">
        Type your question in any language. We'll translate it to English and play it
        for the doctor — no need to speak English yourself.
      </p>
      <div class="mt-3 flex flex-col gap-2 md:flex-row">
        <textarea
          v-model="askText"
          rows="2"
          class="flex-1 resize-none rounded-md border border-amber-300 bg-white px-3 py-2 text-sm placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-amber-300"
          :placeholder="askPlaceholder"
        />
        <div class="flex flex-col gap-2 md:w-40">
          <select
            v-model="askLanguage"
            class="rounded-md border border-amber-300 bg-white px-2 py-1 text-sm"
          >
            <option value="auto">Auto-detect</option>
            <option value="zh">中文</option>
            <option value="en">English</option>
            <option value="ja">日本語</option>
            <option value="ko">한국어</option>
            <option value="es">Español</option>
            <option value="fr">Français</option>
          </select>
          <button
            @click="onAsk"
            :disabled="askBusy || !askText.trim()"
            class="rounded-md bg-amber-600 px-3 py-2 text-sm text-white disabled:opacity-50"
          >
            {{ askBusy ? "Translating…" : "Translate &amp; speak" }}
          </button>
        </div>
      </div>
      <p v-if="askError" class="mt-2 text-xs text-red-600">{{ askError }}</p>

      <ul v-if="asksThisRound.length" class="mt-4 space-y-2">
        <li v-for="a in asksThisRound" :key="a.ask_id" class="rounded-xl border border-amber-200 bg-white p-3 text-sm">
          <div class="text-[11px] uppercase tracking-wide text-amber-700">
            you wrote · {{ a.source_language }}
          </div>
          <div class="text-ink-800">{{ a.source_text }}</div>
          <div class="mt-2 text-[11px] uppercase tracking-wide text-teal-700">English for the doctor</div>
          <div class="text-ink-800">{{ a.translated_text }}</div>
          <audio
            controls
            class="mt-2 w-full"
            :src="audioUrl(a.ask_id)"
          />
        </li>
      </ul>
    </section>

    <!-- Top-line "what should I do" card. Always visible when the team has anything to say. -->
    <section v-if="hasHighlights" class="mt-8 rounded-2xl border border-line-soft bg-white/80 p-5 shadow-sm">
      <div class="flex items-center justify-between">
        <h2 class="display text-lg leading-tight tracking-editorial">What you should do next</h2>
        <span class="text-[11px] text-ink-400">live · top items only</span>
      </div>

      <div v-if="topQuestions.length" class="mt-3">
        <div class="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Ask the doctor</div>
        <ul class="mt-1.5 space-y-1.5">
          <li v-for="q in topQuestions" :key="q.question_id" class="flex items-start gap-2 text-sm">
            <span class="mt-0.5 inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-teal-100 px-1.5 text-[10px] font-semibold text-teal-700">?</span>
            <span class="text-ink-800">{{ q.question }}</span>
          </li>
        </ul>
      </div>

      <div v-if="topFlags.length" class="mt-4">
        <div class="text-[11px] font-semibold uppercase tracking-wide text-rose-700">Watch out</div>
        <ul class="mt-1.5 space-y-1.5">
          <li v-for="s in topFlags" :key="s.flag_id" class="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50/70 p-2 text-sm">
            <span class="mt-0.5">⚠️</span>
            <div>
              <div class="text-ink-800">{{ s.message }}</div>
              <div class="text-[11px] text-ink-600">→ {{ s.recommended_user_action }}</div>
            </div>
          </li>
        </ul>
      </div>

      <div v-if="topReminders.length" class="mt-4">
        <div class="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Reminders to confirm</div>
        <ul class="mt-1.5 space-y-1.5">
          <li v-for="r in topReminders" :key="r.task_id" class="flex items-start gap-2 text-sm">
            <span class="mt-0.5">💊</span>
            <div>
              <div class="text-ink-800">{{ r.title }}</div>
              <div v-if="r.blocking_missing_fields?.length" class="text-[11px] text-amber-700">
                missing: {{ r.blocking_missing_fields.join(", ") }}
              </div>
            </div>
          </li>
        </ul>
      </div>
    </section>

    <!-- Team recap (image + key callouts). Shown after the user clicks Pause & recap or Team recap. -->
    <section v-if="recap" class="mt-6 rounded-2xl border border-teal-100 bg-teal-50/40 p-5">
      <div class="flex items-center justify-between">
        <h2 class="display text-lg leading-tight tracking-editorial">Team recap</h2>
        <span class="text-[11px] text-ink-500">{{ recapAge }}</span>
      </div>

      <p class="mt-2 text-[15px] font-semibold text-ink-900">{{ recap.headline }}</p>

      <div v-if="recap.image_status === 'ready'" class="mt-3 overflow-hidden rounded-xl border border-line-soft bg-white">
        <img :src="recapImageSrc" alt="Team recap infographic" class="w-full" />
      </div>
      <div v-else-if="recap.image_status === 'failed'" class="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
        Image generation failed: {{ recap.image_error ?? "unknown error" }}. The text recap below is still accurate.
      </div>
      <div v-else class="mt-3 rounded-xl border border-line-soft bg-white p-3 text-xs text-ink-500">
        Image step skipped (OpenAI key not configured). Text recap below.
      </div>

      <div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div v-if="recap.highlight_facts.length">
          <div class="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Key facts</div>
          <ul class="mt-1.5 space-y-1 text-sm">
            <li v-for="(b, i) in recap.highlight_facts" :key="i" class="flex items-start gap-2">
              <span :class="b.emphasis === 'warning' ? 'text-amber-700' : 'text-teal-700'">•</span>
              <span :class="b.emphasis === 'warning' ? 'text-amber-900' : 'text-ink-800'">{{ b.text }}</span>
            </li>
          </ul>
        </div>
        <div v-if="recap.watch_outs.length">
          <div class="text-[11px] font-semibold uppercase tracking-wide text-rose-700">Watch-outs</div>
          <ul class="mt-1.5 space-y-1 text-sm">
            <li v-for="(b, i) in recap.watch_outs" :key="i" class="flex items-start gap-2 text-rose-900">
              <span>⚠️</span><span>{{ b.text }}</span>
            </li>
          </ul>
        </div>
        <div v-if="recap.must_ask.length">
          <div class="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Ask the doctor</div>
          <ul class="mt-1.5 space-y-1 text-sm">
            <li v-for="(q, i) in recap.must_ask" :key="i" class="flex items-start gap-2">
              <span class="text-teal-700">?</span><span class="text-ink-800">{{ q }}</span>
            </li>
          </ul>
        </div>
        <div v-if="recap.next_steps.length">
          <div class="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Next steps</div>
          <ol class="mt-1.5 list-decimal space-y-1 pl-5 text-sm text-ink-800">
            <li v-for="(s, i) in recap.next_steps" :key="i">{{ s }}</li>
          </ol>
        </div>
      </div>
    </section>

    <!-- CLARIOSE_V02 — transcript grouped by round. Closed rounds are
         collapsed by default so the user's eye lands on the live round. -->
    <section class="mt-8">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-neutral-500">
        Transcript by round
        <span class="ml-1 text-xs normal-case text-neutral-400">
          ({{ rounds.length }} round{{ rounds.length === 1 ? "" : "s" }} · {{ serverTurns.length }} total turns)
        </span>
      </h2>
      <div class="mt-2 space-y-3">
        <div v-if="rounds.length === 0 && realtime.turns.value.length === 0" class="rounded-md border border-dashed border-neutral-300 p-3 text-sm text-neutral-500">
          Waiting for transcribed speech…
        </div>

        <details
          v-for="r in rounds"
          :key="r.index"
          :open="r.index === currentRoundIndex || r.ended_at == null"
          class="rounded-xl border bg-white"
          :class="r.index === currentRoundIndex ? 'border-teal-300 ring-1 ring-teal-200' : 'border-neutral-200'"
        >
          <summary class="cursor-pointer list-none px-4 py-3">
            <div class="flex items-center justify-between">
              <div class="text-sm font-medium text-ink-800">
                Round {{ r.index + 1 }}
                <span v-if="r.index === currentRoundIndex && !r.ended_at" class="ml-2 rounded-full bg-teal-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-teal-700">
                  live
                </span>
                <span v-else-if="r.ended_at" class="ml-2 text-[10px] uppercase tracking-wide text-neutral-400">
                  closed
                </span>
              </div>
              <div class="text-[11px] text-neutral-500">
                {{ r.turn_item_ids.length }} turn{{ r.turn_item_ids.length === 1 ? "" : "s" }}
                <span v-if="r.recap_headline" class="ml-2 italic text-teal-700">· “{{ r.recap_headline }}”</span>
              </div>
            </div>
          </summary>

          <div class="space-y-3 px-4 pb-4">
            <!-- Per-round team-recap card: image + must-ask. Surfaces the
                 multi-agent collaborative output for THIS round only. -->
            <div
              v-if="recapsByRound[r.index]"
              class="rounded-xl border border-teal-200 bg-teal-50/50 p-3"
            >
              <div class="flex items-center justify-between">
                <p class="text-[15px] font-semibold text-ink-900">
                  {{ recapsByRound[r.index].headline }}
                </p>
                <span class="text-[11px] text-ink-500">team output · round {{ r.index + 1 }}</span>
              </div>
              <div
                v-if="recapsByRound[r.index].image_status === 'ready'"
                class="mt-2 overflow-hidden rounded-xl border border-line-soft bg-white"
              >
                <img
                  :src="recapImageSrcFor(r.index)"
                  :alt="`Round ${r.index + 1} team recap infographic`"
                  class="w-full"
                />
              </div>
              <div
                v-else-if="recapsByRound[r.index].image_status === 'failed'"
                class="mt-2 rounded-xl border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800"
              >
                Image generation failed: {{ recapsByRound[r.index].image_error ?? "unknown error" }}
              </div>
              <div v-if="recapsByRound[r.index].must_ask?.length" class="mt-3">
                <div class="text-[11px] font-semibold uppercase tracking-wide text-teal-700">
                  Ask the doctor
                </div>
                <ul class="mt-1 space-y-1 text-sm">
                  <li v-for="(q, i) in recapsByRound[r.index].must_ask" :key="i" class="flex items-start gap-2">
                    <span class="text-teal-700">?</span>
                    <span class="text-ink-800">{{ q }}</span>
                  </li>
                </ul>
              </div>
            </div>

            <details class="rounded-md border border-neutral-200 bg-neutral-50/60">
              <summary class="cursor-pointer list-none px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-500">
                Transcript ({{ visibleTurnsForRound(r).length }} turn{{ visibleTurnsForRound(r).length === 1 ? "" : "s" }}<span v-if="hiddenNoiseCountForRound(r) > 0 && !showHiddenNoise"> · {{ hiddenNoiseCountForRound(r) }} hidden</span>)
              </summary>
              <div class="space-y-2 px-3 pb-3">
                <div
                  v-if="hiddenNoiseCountForRound(r) > 0"
                  class="flex items-center justify-between rounded-md border border-dashed border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-800"
                >
                  <span>
                    {{ hiddenNoiseCountForRound(r) }} segment{{ hiddenNoiseCountForRound(r) === 1 ? "" : "s" }} hidden by transcript noise filter.
                  </span>
                  <button
                    type="button"
                    class="rounded border border-amber-300 bg-white px-2 py-0.5 font-medium text-amber-900 hover:bg-amber-100"
                    @click="showHiddenNoise = !showHiddenNoise"
                  >
                    {{ showHiddenNoise ? "Hide noise" : "Show hidden" }}
                  </button>
                </div>
                <div v-if="visibleTurnsForRound(r).length === 0" class="rounded-md border border-dashed border-neutral-200 p-2 text-xs text-neutral-400">
                  No transcripts in this round yet.
                </div>
                <div
                  v-for="t in visibleTurnsForRound(r)"
                  :key="t.item_id"
                  class="rounded-md border p-3"
                  :class="[
                    t.status === 'failed' ? 'border-red-300' : 'border-neutral-200',
                    noiseTagMap[t.item_id]?.tag === 'noise_high_conf'
                      ? 'bg-amber-50 opacity-60'
                      : noiseTagMap[t.item_id]?.tag === 'noise_low_conf'
                      ? 'bg-neutral-50 opacity-75'
                      : 'bg-white',
                  ]"
                >
                  <div class="flex items-center justify-between text-xs text-neutral-500">
                    <span>{{ t.item_id }} · {{ t.status }} · ord:{{ t.ordering_confidence ?? "high" }}</span>
                    <span class="flex items-center gap-1.5">
                      <span
                        v-if="noiseTagMap[t.item_id] && noiseTagMap[t.item_id].tag !== 'clean'"
                        class="rounded px-1.5 py-0.5 text-[10px] font-medium"
                        :class="
                          noiseTagMap[t.item_id].tag === 'noise_high_conf'
                            ? 'bg-amber-100 text-amber-900'
                            : noiseTagMap[t.item_id].tag === 'noise_low_conf'
                            ? 'bg-neutral-200 text-neutral-700'
                            : 'bg-sky-100 text-sky-800'
                        "
                        :title="noiseTagMap[t.item_id].reason"
                      >
                        {{ noiseTagMap[t.item_id].tag.replace(/_/g, " ") }}
                      </span>
                      <span v-if="t.speaker_label" class="rounded bg-neutral-100 px-1.5 py-0.5">{{ t.speaker_label }}</span>
                    </span>
                  </div>
                  <div class="mt-1 text-sm">
                    {{ t.transcript ?? t.partial_transcript ?? "(no text)" }}
                  </div>
                  <div v-if="t.error" class="mt-1 text-xs text-red-600">error: {{ t.error }}</div>
                </div>
                <div
                  v-if="r.index === currentRoundIndex && realtime.partial.value"
                  class="rounded-md border border-dashed border-neutral-300 p-3 text-sm text-neutral-500"
                >
                  {{ realtime.partial.value }} <span class="opacity-50">…</span>
                </div>
              </div>
            </details>
          </div>
        </details>
      </div>
    </section>

    <!-- CLARIOSE_V03 — multi-agent collaboration timeline. The whole point
         of the swarm is the inter-agent traffic; this section makes it
         visible. Each row is a mailbox message from one persona to another
         (Scribe Lin → Dr. Apo, etc.) so the user can SEE the team
         coordinate, not just read the final outputs. -->
    <section
      v-if="showTeamDetail"
      class="mt-10 rounded-2xl border border-line-soft bg-white/70 p-5"
    >
      <div class="flex items-center justify-between">
        <div>
          <h2 class="display text-[22px] leading-tight tracking-editorial">Team conversation</h2>
          <p class="mt-1 text-xs text-ink-500">
            How the helpers coordinated — mailbox messages, shared notes, and per-agent runs.
          </p>
        </div>
        <div class="hidden items-center gap-1 sm:flex">
          <AgentAvatar v-for="r in roleOrder" :key="r" :role="r" :size="28" />
        </div>
      </div>

      <div
        v-if="teamActivity"
        class="mt-4 grid grid-cols-1 gap-5"
        :class="teamActivity.messages.length ? 'lg:grid-cols-3' : ''"
      >
        <!-- 1. Mailbox traffic — only render when there's actual traffic.
             An empty "Messages between helpers (0)" panel was just noise
             since the helpers usually coordinate via the blackboard. -->
        <div v-if="teamActivity.messages.length" class="lg:col-span-2">
          <div class="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
            Messages between helpers ({{ teamActivity.messages.length }})
          </div>
          <ol class="mt-2 space-y-2">
            <li
              v-for="(m, i) in teamActivity.messages.slice().reverse()"
              :key="i"
              class="flex gap-3 rounded-xl border border-line-soft bg-white p-3"
            >
              <div class="flex shrink-0 -space-x-2">
                <AgentAvatar :role="roleInfo(m.from).avatar" :size="32" />
                <AgentAvatar :role="roleInfo(m.to).avatar" :size="32" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-2 text-[11px] text-ink-500">
                  <span>
                    <span class="font-semibold text-ink-700">{{ roleInfo(m.from).label }}</span>
                    <span class="mx-1 text-ink-400">→</span>
                    <span class="font-semibold text-ink-700">{{ roleInfo(m.to).label }}</span>
                    <span class="ml-2 rounded-full bg-ink-50 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-500">
                      {{ m.kind.replace(/_/g, " ") }}
                    </span>
                  </span>
                  <span class="text-[10px] text-ink-400">{{ fmtTime(m.timestamp) }}</span>
                </div>
                <div class="mt-1 text-sm text-ink-800">
                  {{ shortenMessageText(m.text) }}
                </div>
                <div v-if="m.summary" class="mt-1 text-[11px] italic text-ink-500">
                  {{ m.summary }}
                </div>
              </div>
            </li>
          </ol>
        </div>

        <!-- 2. Blackboard + agent runs.
             Two side-by-side cards when mailbox is hidden, single column on
             the right when mailbox is showing. -->
        <div
          class="grid grid-cols-1 gap-5"
          :class="teamActivity.messages.length ? '' : 'md:grid-cols-2'"
        >
          <div>
            <div class="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
              Shared notes (blackboard)
            </div>
            <ul v-if="teamActivity.blackboard.length" class="mt-2 space-y-1.5 text-xs">
              <li
                v-for="b in teamActivity.blackboard"
                :key="b.key"
                class="rounded-lg border border-line-soft bg-canvas/60"
              >
                <button
                  type="button"
                  class="flex w-full items-center gap-2 p-2 text-left hover:bg-canvas/80"
                  :aria-expanded="expandedBlackboardKeys.has(b.key)"
                  @click="toggleBlackboard(b.key)"
                >
                  <AgentAvatar :role="roleInfo(b.writtenBy).avatar" :size="22" />
                  <div class="min-w-0 flex-1">
                    <div class="truncate font-mono text-[11px] text-ink-700">{{ b.key }}</div>
                    <div class="text-[10px] text-ink-500">
                      {{ roleInfo(b.writtenBy).label }} · v{{ b.version }} · {{ fmtTime(b.updatedAt) }}
                    </div>
                  </div>
                  <svg
                    class="h-3 w-3 shrink-0 text-ink-400 transition-transform"
                    :class="expandedBlackboardKeys.has(b.key) ? 'rotate-90' : ''"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                  >
                    <path d="M9 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </button>
                <pre
                  v-if="expandedBlackboardKeys.has(b.key)"
                  class="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-line-soft bg-white px-3 py-2 font-mono text-[11px] leading-relaxed text-ink-700"
                >{{ formatBlackboardValue(b.value) }}</pre>
              </li>
            </ul>
            <div v-else class="mt-2 rounded-lg border border-dashed border-line-soft p-2 text-[11px] text-ink-400">
              Nothing shared on the team blackboard yet.
            </div>
          </div>

          <div>
            <div class="flex items-center justify-between">
              <div class="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                Recent agent runs
                <span v-if="teamActivity.agent_runs.length" class="ml-1 text-ink-400">
                  ({{ teamActivity.agent_runs.length }})
                </span>
              </div>
              <button
                v-if="teamActivity.agent_runs.length"
                type="button"
                class="text-[10px] text-ink-500 hover:text-ink-700"
                @click="toggleAllAgentRuns"
              >
                {{ allAgentRunsExpanded ? "collapse all" : "expand all" }}
              </button>
            </div>
            <ul v-if="teamActivity.agent_runs.length" class="mt-2 space-y-1.5 text-xs">
              <li
                v-for="r in teamActivity.agent_runs.slice().reverse().slice(0, 12)"
                :key="r.id"
                class="overflow-hidden rounded-lg border border-line-soft bg-white"
              >
                <button
                  type="button"
                  class="flex w-full items-center gap-2 p-2 text-left hover:bg-canvas/40"
                  :aria-expanded="expandedAgentRunIds.has(r.id)"
                  @click="toggleAgentRun(r.id)"
                >
                  <AgentAvatar :role="roleInfo(r.role).avatar" :size="22" />
                  <div class="min-w-0 flex-1">
                    <div class="truncate text-[11px] text-ink-700">
                      {{ roleInfo(r.role).label }} · {{ r.kind }}
                    </div>
                    <div class="text-[10px] text-ink-500">
                      {{ r.status }}<span v-if="r.validation_status"> · {{ r.validation_status }}</span>
                      <span v-if="r.latency_ms != null"> · {{ r.latency_ms }}ms</span>
                    </div>
                  </div>
                  <span
                    class="h-2 w-2 shrink-0 rounded-full"
                    :class="r.status === 'COMPLETED' ? 'bg-sage-500' : r.status === 'FAILED' ? 'bg-rose-500' : 'bg-ink-300'"
                  />
                  <svg
                    class="h-3 w-3 shrink-0 text-ink-400 transition-transform"
                    :class="expandedAgentRunIds.has(r.id) ? 'rotate-90' : ''"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                  >
                    <path d="M9 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </button>
                <div
                  v-if="expandedAgentRunIds.has(r.id)"
                  class="border-t border-line-soft bg-canvas/40 px-2.5 py-2 text-[11px] text-ink-700"
                >
                  <div class="grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-[10.5px]">
                    <div><span class="text-ink-400">started</span> · {{ fmtTime(r.started_at) }}</div>
                    <div v-if="r.ended_at"><span class="text-ink-400">ended</span> · {{ fmtTime(r.ended_at) }}</div>
                    <div v-if="r.model_name"><span class="text-ink-400">model</span> · {{ r.model_name }}</div>
                    <div v-if="r.latency_ms != null"><span class="text-ink-400">latency</span> · {{ r.latency_ms }}ms</div>
                  </div>
                  <div v-if="r.error" class="mt-2 rounded bg-rose-50 px-2 py-1 text-[11px] text-rose-700">
                    error: {{ r.error }}
                  </div>
                  <div v-if="r.parsed_json !== null && r.parsed_json !== undefined" class="mt-2">
                    <div class="text-[10px] uppercase tracking-wide text-ink-400">output</div>
                    <pre class="mt-0.5 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-white px-2 py-1.5 font-mono text-[10.5px] leading-relaxed text-ink-700">{{ formatBlackboardValue(r.parsed_json) }}</pre>
                  </div>
                  <div v-if="r.prompt" class="mt-2">
                    <button
                      type="button"
                      class="text-[10px] uppercase tracking-wide text-ink-400 hover:text-ink-600"
                      @click="togglePromptForRun(r.id)"
                    >
                      {{ expandedRunPrompts.has(r.id) ? "hide prompt" : "show prompt" }}
                    </button>
                    <pre
                      v-if="expandedRunPrompts.has(r.id)"
                      class="mt-1 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-white px-2 py-1.5 font-mono text-[10.5px] leading-relaxed text-ink-600"
                    >{{ r.prompt }}<span v-if="r.prompt_truncated" class="text-ink-400">

…(truncated)</span></pre>
                  </div>
                </div>
              </li>
            </ul>
            <div v-else class="mt-2 rounded-lg border border-dashed border-line-soft p-2 text-[11px] text-ink-400">
              No agent runs recorded yet.
            </div>
          </div>
        </div>
      </div>
      <div v-else class="mt-3 text-xs text-ink-400">Loading team activity…</div>
    </section>

    <!-- Per-helper drafts (transcript verifier, question helper, fact finder, …).
         Visible by default — the user explicitly asked to SEE the cartoon
         agents and their outputs. The "Hide team detail" toggle at the top
         collapses everything down to the essentials. -->
    <section v-if="showTeamDetail" class="mt-8 rounded-2xl border border-line-soft bg-white/40 px-5 py-4">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="display text-[22px] leading-tight tracking-editorial">Team thinking</h2>
          <p class="mt-1 text-xs text-ink-500">
            Per-helper drafts as the visit unfolds.
            <span v-if="selectedTurnId !== 'all'" class="ml-1 rounded-full bg-teal-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-teal-700">
              filtered to one turn
            </span>
          </p>
        </div>
        <div class="hidden items-center gap-1 sm:flex">
          <AgentAvatar v-for="r in roleOrder" :key="r" :role="r" :size="28" />
        </div>
      </div>

      <!-- Turn switcher: pick a turn to see ONLY what each agent did for it.
           "All" returns to the cumulative view. The user explicitly asked to
           "switch different turns so each agent shows different content". -->
      <div class="mt-3 flex flex-wrap items-center gap-1.5">
        <span class="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Turn</span>
        <button
          type="button"
          @click="selectedTurnId = 'all'"
          :class="[
            'rounded-full border px-2.5 py-0.5 text-[11px] transition',
            selectedTurnId === 'all'
              ? 'border-teal-600 bg-teal-600 text-white'
              : 'border-line-soft bg-white text-ink-700 hover:bg-canvas/60',
          ]"
        >
          All
        </button>
        <button
          v-for="t in turnPickerEntries"
          :key="t.item_id"
          type="button"
          @click="selectedTurnId = t.item_id"
          :title="t.snippet"
          :class="[
            'rounded-full border px-2.5 py-0.5 text-[11px] transition',
            selectedTurnId === t.item_id
              ? 'border-teal-600 bg-teal-600 text-white'
              : 'border-line-soft bg-white text-ink-700 hover:bg-canvas/60',
          ]"
        >
          {{ t.label }}<span class="ml-1 text-[10px] opacity-70">· {{ t.snippet || "—" }}</span>
        </button>
        <span v-if="!turnPickerEntries.length" class="text-[11px] text-ink-400">
          No completed turns yet.
        </span>
      </div>
    <section class="px-0 pb-1 pt-4">
      <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
        <AgentPanel
          role="scribe"
          :empty="scribeVerifications.length === 0"
          :count="scribeVerifications.length"
          :tagline="scribeTagline"
        >
          <ul class="space-y-2">
            <li v-for="v in scribeVerifications" :key="v.verification_id" class="text-sm">
              <div class="flex items-center justify-between">
                <span class="rounded-full bg-ink-50 px-2 py-0.5 text-[11px] uppercase tracking-wide text-ink-600">
                  quality: {{ v.quality }}
                </span>
                <span class="text-[11px] text-ink-400">turn {{ v.turn_id }}</span>
              </div>
              <ul v-if="v.ambiguities.length" class="mt-1.5 space-y-1.5 pl-1">
                <li v-for="a in v.ambiguities" :key="a.ambiguity_id" class="rounded-lg border border-amber-200 bg-amber-50/70 p-2 text-xs">
                  <div><span class="font-medium">{{ a.ambiguity_type }}</span> · sev: {{ a.severity }}</div>
                  <div class="text-ink-700">"{{ a.text }}" — {{ a.reason }}</div>
                  <div class="mt-1 italic text-ink-600">→ {{ a.suggested_confirmation_question }}</div>
                </li>
              </ul>
              <div v-else class="pl-1 text-[11px] text-ink-400">no ambiguities — clean read</div>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel
          role="inquirer"
          :empty="inquirerQuestions.length === 0"
          :count="inquirerQuestions.length"
          :tagline="inquirerTagline"
        >
          <ul class="space-y-2 text-sm">
            <li v-for="q in inquirerQuestions" :key="q.question_id" class="rounded-lg border border-line-soft bg-canvas/60 p-2.5">
              <div class="text-[11px] text-ink-400">
                priority: <span class="font-medium text-ink-600">{{ q.priority }}</span>
                · turns: {{ q.source_turn_ids.join(", ") }}
              </div>
              <div class="mt-1 text-ink-800">{{ q.question }}</div>
              <div v-if="q.reason" class="mt-1 text-[11px] text-ink-500">{{ q.reason }}</div>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel
          role="scout"
          :empty="scoutFacts.length === 0"
          :count="scoutFacts.length"
          :tagline="scoutTagline"
        >
          <ul class="space-y-1.5">
            <li v-for="f in scoutFacts" :key="f.fact_id" class="flex items-start gap-2 text-sm">
              <span class="mt-0.5 inline-flex shrink-0 rounded-full bg-sage-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-sage-700">
                {{ f.fact_type }}
              </span>
              <span class="text-ink-800">{{ f.original_text }}</span>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel
          role="pharmacist"
          :empty="pharmacistReminders.length === 0"
          :count="pharmacistReminders.length"
          :tagline="pharmacistTagline"
        >
          <ul class="space-y-3">
            <li v-for="r in pharmacistReminders" :key="r.task_id" class="rounded-xl border border-rose-100 bg-rose-50/60 p-3 text-sm">
              <div class="flex items-center gap-2">
                <span class="text-base">💊</span>
                <div class="font-medium text-ink-800">{{ r.title }}</div>
              </div>
              <div class="mt-0.5 text-ink-600">{{ r.description }}</div>
              <div class="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-ink-700">
                <div><span class="text-ink-400">name</span> · {{ r.medication_name ?? "—" }}</div>
                <div><span class="text-ink-400">dose</span> · {{ r.dose ?? "—" }}</div>
                <div><span class="text-ink-400">frequency</span> · {{ r.frequency ?? "—" }}</div>
                <div><span class="text-ink-400">timing</span> · {{ r.timing ?? "—" }}</div>
                <div><span class="text-ink-400">duration</span> · {{ r.duration ?? "—" }}</div>
                <div><span class="text-ink-400">status</span> · {{ r.status }}</div>
              </div>
              <div v-if="r.blocking_missing_fields?.length" class="mt-2 rounded bg-amber-100/80 px-2 py-1 text-[11px] text-amber-800">
                ✋ missing: {{ r.blocking_missing_fields.join(", ") }} — Dr. Apo wants to confirm these
              </div>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel
          role="coordinator"
          :empty="followUpDrafts.length === 0"
          :count="followUpDrafts.length"
          :tagline="coordinatorTagline"
        >
          <ul class="space-y-1.5">
            <li v-for="t in followUpDrafts" :key="t.task_id" class="flex items-start gap-2 rounded-lg border border-line-soft bg-canvas/60 p-2.5 text-sm">
              <span class="mt-0.5 inline-flex shrink-0 rounded-full bg-champagne-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-champagne-500">
                {{ t.task_type }}
              </span>
              <span class="text-ink-800">{{ t.title }}</span>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel
          role="guardian"
          :empty="guardianFlags.length === 0"
          :count="guardianFlags.length"
          :tagline="guardianTagline"
        >
          <ul class="space-y-2 text-sm">
            <li v-for="s in guardianFlags" :key="s.flag_id" class="rounded-xl border border-rose-200 bg-rose-50/70 p-3">
              <div class="flex items-center gap-1.5">
                <span class="text-base">⚠️</span>
                <span class="text-[11px] font-semibold uppercase tracking-wide text-rose-700">
                  {{ s.flag_type }} · {{ s.severity }}
                </span>
              </div>
              <div class="mt-1 text-ink-800">{{ s.message }}</div>
              <div class="mt-1 text-[11px] text-ink-600">→ {{ s.recommended_user_action }}</div>
            </li>
          </ul>
        </AgentPanel>

        <div class="md:col-span-2">
          <AgentPanel
            role="messenger"
            :empty="messengerNotifications.length === 0"
            :count="messengerNotifications.length"
            :tagline="messengerTagline"
          >
            <ul class="space-y-3">
              <li v-for="n in messengerNotifications" :key="n.notification_id" class="rounded-xl border border-sage-200 bg-sage-50/60 p-3 text-sm">
                <div class="flex items-center justify-between gap-2">
                  <div class="flex items-center gap-1.5 font-medium text-ink-800">
                    <span class="text-base">✉️</span>{{ n.title }}
                  </div>
                  <button
                    @click="copyText(n.message)"
                    class="rounded-full border border-sage-300 px-2.5 py-0.5 text-[11px] text-sage-700 hover:bg-sage-100"
                  >
                    copy
                  </button>
                </div>
                <p class="mt-1.5 whitespace-pre-wrap rounded-lg bg-white/70 p-2.5 text-ink-700">{{ n.message }}</p>
                <div v-if="n.needs_confirmation.length" class="mt-2 text-xs">
                  <div class="font-medium text-amber-800">Postie Ren needs you to confirm:</div>
                  <ul class="ml-4 list-disc text-ink-700">
                    <li v-for="(c, i) in n.needs_confirmation" :key="i">{{ c }}</li>
                  </ul>
                </div>
                <div v-if="n.next_actions.length" class="mt-2 text-xs">
                  <div class="font-medium text-ink-700">Next actions:</div>
                  <ul class="ml-4 list-disc text-ink-700">
                    <li v-for="(a, i) in n.next_actions" :key="i">{{ a }}</li>
                  </ul>
                </div>
                <div class="mt-2 text-[10px] uppercase tracking-wide text-ink-400">
                  draft · {{ n.confirmation_status }} · never auto-sent
                </div>
              </li>
            </ul>
          </AgentPanel>
        </div>

        <AgentPanel
          role="storyteller"
          :empty="!familySummaryFinal && familySummaryDeltas.length === 0"
          :count="familySummaryFinal ? 1 : familySummaryDeltas.length"
          :tagline="storytellerTagline"
        >
          <div v-if="familySummaryFinal" class="rounded-xl border border-rose-100 bg-rose-50/40 p-3 text-sm">
            <div class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-rose-700">
              Final retelling
            </div>
            <p class="whitespace-pre-wrap text-ink-800">{{ familySummaryFinal }}</p>
          </div>
          <ul v-if="familySummaryDeltas.length" class="mt-2 space-y-1.5">
            <li
              v-for="(d, i) in familySummaryDeltas"
              :key="`${d.turn_id}-${i}`"
              class="rounded-lg border border-line-soft bg-canvas/60 p-2.5 text-sm"
            >
              <div class="text-[10px] uppercase tracking-wide text-ink-400">turn {{ d.turn_id }}</div>
              <p class="mt-0.5 whitespace-pre-wrap text-ink-700">{{ d.text }}</p>
            </li>
          </ul>
        </AgentPanel>

        <AgentPanel
          role="memory"
          :empty="memoryCandidates.length === 0"
          :count="memoryCandidates.length"
          :tagline="memoryTagline"
        >
          <ul class="space-y-2 text-sm">
            <li
              v-for="m in memoryCandidates"
              :key="m.memory_candidate_id"
              class="rounded-lg border border-sage-200 bg-sage-50/50 p-2.5"
            >
              <div class="flex items-center justify-between gap-2 text-[11px] text-ink-500">
                <span class="rounded-full bg-sage-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-sage-700">
                  {{ m.memory_type }}
                </span>
                <span class="text-[10px] text-ink-400">
                  confidence: {{ m.confidence }} · {{ m.confirmation_status }}
                </span>
              </div>
              <p class="mt-1 text-ink-800">{{ m.content }}</p>
            </li>
          </ul>
        </AgentPanel>
      </div>
    </section>
    </section>

    <p v-if="realtime.error.value" class="mt-6 text-sm text-red-600">
      {{ realtime.error.value }}
    </p>
  </div>
</template>

<script setup lang="ts">
import type {
  VisitFull,
  VisitTurnPersisted,
  TeamRecap,
  VisitRound,
  AskDoctorLog,
  TeamActivity,
} from "~/composables/useCareNote";
import AgentAvatar, { type AgentRole } from "~/components/carenote/AgentAvatar.vue";
import AgentPanel from "~/components/carenote/AgentPanel.vue";

const roleOrder: AgentRole[] = [
  "scribe",
  "inquirer",
  "scout",
  "pharmacist",
  "coordinator",
  "guardian",
  "messenger",
  "storyteller",
  "memory",
];

const route = useRoute();
const router = useRouter();
const visitId = computed(() => route.params.id as string);

const realtime = useRealtimeVisit(visitId);
const carenote = useCareNote();

const state = ref<VisitFull["state"] | null>(null);
const recap = ref<TeamRecap | null>(null);
const recapBusy = ref(false);
const recapImageNonce = ref(0);
// CLARIOSE_V03 — per-round recap cache. Key = round_index. Each pause-cycle
// runs the team and stores its consolidated image+digest here so the visit
// page can render every round's outcome side-by-side instead of overwriting
// one with the next.
const recapsByRound = ref<Record<number, TeamRecap>>({});
const jobs = ref<{ pending: number; in_flight: number }>({ pending: 0, in_flight: 0 });
const startedAt = Date.now();
const elapsed = ref(0);
let pollTimer: ReturnType<typeof setInterval> | null = null;
let elapsedTimer: ReturnType<typeof setInterval> | null = null;

const serverTurns = computed<VisitTurnPersisted[]>(() => state.value?.turns ?? []);

// CLARIOSE_V02 — round model.
const rounds = computed<VisitRound[]>(() => {
  const r = state.value?.rounds;
  if (r && r.length) return r;
  // Until the first ingest lands we don't have any server-side rounds —
  // synthesize a "round 1" so the UI doesn't flicker empty.
  return [
    {
      index: 0,
      started_at: new Date().toISOString(),
      ended_at: null,
      turn_item_ids: [],
      recap_headline: null,
      recap_generated_at: null,
    },
  ];
});
const currentRoundIndex = computed(() => state.value?.current_round_index ?? 0);

// Noise filter — pause-time per-turn classification. Map item_id → tag so
// we can hide noise_high_conf turns by default, grey out noise_low_conf,
// and tag partial / duplicate turns with an icon. Empty when no filter
// has run yet (live mode); turns just render normally.
type NoiseTagInfo = {
  tag: "clean" | "partial" | "duplicate" | "noise_low_conf" | "noise_high_conf";
  category: string;
  reason: string;
};
const noiseTagMap = computed<Record<string, NoiseTagInfo>>(() => {
  const tags = state.value?.noise_tags?.turn_tags ?? [];
  const map: Record<string, NoiseTagInfo> = {};
  for (const t of tags) {
    map[t.turn_id] = { tag: t.tag, category: t.category, reason: t.reason };
  }
  return map;
});

// User-visible toggle: hide noise_high_conf turns by default. The user can
// flip this to inspect what was filtered.
const showHiddenNoise = ref(false);

function turnsForRound(r: VisitRound): VisitTurnPersisted[] {
  const ids = new Set(r.turn_item_ids);
  return serverTurns.value.filter((t) => ids.has(t.item_id));
}

// Visible vs hidden split for a round. noise_high_conf turns are hidden
// by default (recoverable via toggle); everything else stays visible.
function visibleTurnsForRound(r: VisitRound): VisitTurnPersisted[] {
  const all = turnsForRound(r);
  if (showHiddenNoise.value) return all;
  return all.filter((t) => noiseTagMap.value[t.item_id]?.tag !== "noise_high_conf");
}
function hiddenNoiseCountForRound(r: VisitRound): number {
  return turnsForRound(r).filter(
    (t) => noiseTagMap.value[t.item_id]?.tag === "noise_high_conf",
  ).length;
}

const outputLanguageLabel = computed(() => {
  switch (state.value?.output_language ?? state.value?.language) {
    case "zh": return "中文";
    case "mixed": return "Mixed";
    case "en":
    default: return "English";
  }
});

// Ask-doctor (reverse translate-TTS) panel state.
const askText = ref("");
const askLanguage = ref<string>("auto");
const askBusy = ref(false);
const askError = ref<string | null>(null);

const askPlaceholder = computed(() =>
  state.value?.output_language === "zh"
    ? "请用中文输入您想问医生的问题…"
    : state.value?.output_language === "mixed"
    ? "Type your follow-up question in any language…"
    : "Type your follow-up question in any language…",
);

const asksAll = computed<AskDoctorLog[]>(() => state.value?.ask_doctor_logs ?? []);
const asksThisRound = computed(() =>
  asksAll.value.filter((a) => a.round_index === currentRoundIndex.value).slice().reverse(),
);

function audioUrl(askId: string): string {
  const id = visitId.value;
  // The native <audio> element can't send Authorization headers; the JWT
  // strategy also accepts ?token=, so we pass the cookie-stored token in
  // the URL. Without this the audio tag silently 401s and the controls
  // sit dead on the page (which is exactly what the user reported).
  const token = useCookie<string | null>("clariose_token").value ?? "";
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `/api/visits/${encodeURIComponent(id)}/asks/${encodeURIComponent(askId)}/audio${q}`;
}

async function onAsk() {
  const text = askText.value.trim();
  if (!text || askBusy.value) return;
  askBusy.value = true;
  askError.value = null;
  try {
    const lang = askLanguage.value === "auto" ? undefined : askLanguage.value;
    await carenote.askDoctor(visitId.value, { source_text: text, source_language: lang });
    askText.value = "";
    await refresh();
  } catch (err: any) {
    askError.value = err?.data?.message ?? err?.message ?? "Could not generate audio.";
  } finally {
    askBusy.value = false;
  }
}

// CLARIOSE_V03 — per-turn filter so each agent panel can show ONLY what
// it produced for the selected turn. Without this every panel kept
// growing as the visit went on, and the user couldn't tell which agent
// did what at which moment. Default "all" preserves the cumulative view.
const selectedTurnId = ref<string | "all">("all");

// Reset the filter when the user changes round so they don't end up with
// a stale turn id from a closed round.
watch(currentRoundIndex, () => {
  selectedTurnId.value = "all";
});

function matchesTurn(sourceIds: string[] | undefined | null): boolean {
  if (selectedTurnId.value === "all") return true;
  if (!Array.isArray(sourceIds)) return false;
  return sourceIds.includes(selectedTurnId.value);
}

// Turns visible in the picker: every completed turn in the visit, in the
// order they were spoken. Each chip shows "T<n>" + a short snippet so the
// user knows which moment they're inspecting.
const turnPickerEntries = computed(() => {
  const turns = serverTurns.value;
  return turns.map((t, i) => ({
    item_id: t.item_id,
    label: `T${i + 1}`,
    snippet: ((t.transcript ?? t.partial_transcript ?? "") || "(no text)")
      .toString()
      .trim()
      .slice(0, 36),
  }));
});

// Filtered slices — each agent panel reads from these so switching turns
// changes ONLY what the panel shows, without losing data on the server.
const scribeVerifications = computed(() => {
  const all = state.value?.transcript_verifications ?? [];
  if (selectedTurnId.value === "all") return all;
  return all.filter((v: any) => v.turn_id === selectedTurnId.value);
});
const inquirerQuestions = computed(() =>
  (state.value?.clarifying_questions ?? []).filter((q: any) => matchesTurn(q.source_turn_ids)),
);
const scoutFacts = computed(() =>
  (state.value?.facts ?? []).filter((f: any) => matchesTurn(f.source_turn_ids)),
);
const pharmacistReminders = computed(() =>
  (state.value?.draft_reminders ?? []).filter((r: any) => matchesTurn(r.source_turn_ids)),
);
const guardianFlags = computed(() =>
  (state.value?.safety_flags ?? []).filter((s: any) => matchesTurn(s.source_turn_ids)),
);
const messengerNotifications = computed(() => {
  const all = state.value?.caregiver_notifications ?? [];
  return all.filter((n: any) =>
    selectedTurnId.value === "all"
      ? true
      : (n.turn_id === selectedTurnId.value)
        || matchesTurn(n.source_turn_ids),
  );
});

const followUpDrafts = computed(() =>
  (state.value?.draft_tasks ?? [])
    .filter((t: any) => t.task_type !== "medication_reminder")
    .filter((t: any) => matchesTurn(t.source_turn_ids)),
);
const memoryCandidates = computed(() =>
  (state.value?.memory_candidates ?? []).filter((m: any) => matchesTurn(m.source_turn_ids)),
);
const familySummaryDeltas = computed(() => {
  const deltas = state.value?.family_summary_deltas ?? [];
  if (selectedTurnId.value === "all") return deltas;
  return deltas.filter((d) => d.turn_id === selectedTurnId.value);
});
const familySummaryFinal = computed(() => state.value?.family_summary_final ?? "");

// ── Per-agent dynamic taglines ──────────────────────────────────────────
// Each persona "speaks" a one-liner that reflects what they're currently
// doing or have found. When silent, the AgentPanel falls back to the
// persona's idle tagline.
function turnSuffix(): string {
  return selectedTurnId.value === "all" ? "" : ` for this turn`;
}
const scribeTagline = computed(() => {
  const v = scribeVerifications.value;
  if (!v.length) return undefined;
  const ambig = v.reduce((sum, x) => sum + (x.ambiguities?.length ?? 0), 0);
  if (ambig === 0) return `${v.length} clean read${v.length === 1 ? "" : "s"}${turnSuffix()} — looking sharp.`;
  return `Spotted ${ambig} fuzzy bit${ambig === 1 ? "" : "s"} worth double-checking${turnSuffix()}.`;
});
const inquirerTagline = computed(() => {
  const n = inquirerQuestions.value.length;
  if (!n) return undefined;
  return `${n} question${n === 1 ? "" : "s"} ready for the doctor${turnSuffix()}.`;
});
const scoutTagline = computed(() => {
  const n = scoutFacts.value.length;
  if (!n) return undefined;
  return `Logged ${n} fact${n === 1 ? "" : "s"}${turnSuffix()}.`;
});
const pharmacistTagline = computed(() => {
  const r = pharmacistReminders.value;
  if (!r.length) return undefined;
  const missing = r.some((x: any) => x.blocking_missing_fields?.length);
  return missing
    ? `Drafted ${r.length} reminder${r.length === 1 ? "" : "s"}${turnSuffix()} — a few details still need you.`
    : `Drafted ${r.length} reminder${r.length === 1 ? "" : "s"}${turnSuffix()} — ready to confirm.`;
});
const coordinatorTagline = computed(() => {
  const n = followUpDrafts.value.length;
  if (!n) return undefined;
  return `Lined up ${n} follow-up${n === 1 ? "" : "s"}${turnSuffix()}.`;
});
const guardianTagline = computed(() => {
  const flags = guardianFlags.value;
  if (!flags.length) return undefined;
  const high = flags.filter((f: any) => f.severity === "high").length;
  return high
    ? `${high} high-severity flag${high === 1 ? "" : "s"}${turnSuffix()} — please take a look.`
    : `Watching ${flags.length} item${flags.length === 1 ? "" : "s"}${turnSuffix()} — nothing urgent.`;
});
const messengerTagline = computed(() => {
  const n = messengerNotifications.value.length;
  if (!n) return undefined;
  return `${n} family note${n === 1 ? "" : "s"} ready${turnSuffix()}.`;
});
const memoryTagline = computed(() => {
  const n = memoryCandidates.value.length;
  if (!n) return undefined;
  return `${n} thing${n === 1 ? "" : "s"} worth remembering${turnSuffix()} — your call.`;
});
const storytellerTagline = computed(() => {
  if (familySummaryFinal.value) return "Final retelling is ready — plain language, family-safe.";
  const n = familySummaryDeltas.value.length;
  if (!n) return undefined;
  return `Drafted ${n} retelling${n === 1 ? "" : "s"}${turnSuffix()}.`;
});

// Prefer server turns when available — they reflect what the harness
// has actually persisted. Fall back to the local optimistic mirror in
// realtime.turns if the server has not yet caught up.
const displayTurns = computed(() => {
  if (serverTurns.value.length > 0) return serverTurns.value;
  return realtime.turns.value.map((t) => ({
    item_id: t.item_id,
    status: t.status,
    transcript: t.transcript,
    partial_transcript: t.partial,
    speaker_label: null,
    ordering_confidence: "high" as const,
    error: null,
  })) as unknown as VisitTurnPersisted[];
});

async function refresh() {
  try {
    const v = await carenote.getVisit(visitId.value);
    state.value = v.state;
    jobs.value = v.job_status;
    // Hydrate every per-round recap up front so generated images survive a
    // page refresh — the previous code only kept the recap returned from
    // the inline POST response, so the image vanished as soon as you
    // refreshed.
    if (v.team_recaps && v.team_recaps.length) {
      const byRound: Record<number, TeamRecap> = {};
      let latest: TeamRecap | null = null;
      for (const r of v.team_recaps) {
        if (typeof r.round_index === "number") byRound[r.round_index] = r;
        latest = r;
      }
      recapsByRound.value = byRound;
      if (latest) {
        recap.value = latest;
        recapImageNonce.value = new Date(latest.generated_at).getTime();
      }
    } else if (v.team_recap) {
      recap.value = v.team_recap;
      if (typeof v.team_recap.round_index === "number") {
        recapsByRound.value = {
          ...recapsByRound.value,
          [v.team_recap.round_index]: v.team_recap,
        };
      }
    }
  } catch {
    // visit may have been deleted from another tab; ignore
  }
}

// CLARIOSE_V03 — multi-agent collaboration timeline. Pulled separately so a
// slow blackboard query doesn't delay the main visit poll.
const teamActivity = ref<TeamActivity | null>(null);
async function refreshActivity() {
  try {
    teamActivity.value = await carenote.teamActivity(visitId.value);
  } catch {
    // owner check fails the moment the visit is deleted — ignore
  }
}

const expandedBlackboardKeys = reactive(new Set<string>());
function toggleBlackboard(key: string) {
  if (expandedBlackboardKeys.has(key)) expandedBlackboardKeys.delete(key);
  else expandedBlackboardKeys.add(key);
}

// Per-run expand state for the "Recent agent runs" list. Each row stays
// collapsed by default so the panel doesn't blow up the page; clicking
// reveals timing, output JSON, and the raw prompt on a second click.
const expandedAgentRunIds = reactive(new Set<string>());
const expandedRunPrompts = reactive(new Set<string>());
function toggleAgentRun(id: string) {
  if (expandedAgentRunIds.has(id)) {
    expandedAgentRunIds.delete(id);
    expandedRunPrompts.delete(id);
  } else {
    expandedAgentRunIds.add(id);
  }
}
function togglePromptForRun(id: string) {
  if (expandedRunPrompts.has(id)) expandedRunPrompts.delete(id);
  else expandedRunPrompts.add(id);
}
const allAgentRunsExpanded = computed(() => {
  const visible = (teamActivity.value?.agent_runs ?? []).slice(-12);
  return visible.length > 0 && visible.every((r) => expandedAgentRunIds.has(r.id));
});
function toggleAllAgentRuns() {
  const visible = (teamActivity.value?.agent_runs ?? []).slice(-12);
  if (allAgentRunsExpanded.value) {
    for (const r of visible) {
      expandedAgentRunIds.delete(r.id);
      expandedRunPrompts.delete(r.id);
    }
  } else {
    for (const r of visible) expandedAgentRunIds.add(r.id);
  }
}
function formatBlackboardValue(value: unknown): string {
  if (value == null) return "(empty)";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// Persona descriptors for the multi-agent timeline. Maps the BACKEND role
// names (medical_instruction_extractor, …) to the FRIENDLY persona we render
// in the avatar layer (scout, pharmacist, …).
type RoleInfo = { avatar: AgentRole; label: string };
const ROLE_INFO: Record<string, RoleInfo> = {
  visit_orchestrator:           { avatar: "orchestrator", label: "Maestro Cen" },
  transcript_quality:           { avatar: "scribe",       label: "Scribe Lin" },
  speaker_role:                 { avatar: "scribe",       label: "Scribe Lin" },
  medical_instruction_extractor:{ avatar: "scout",        label: "Scout Ada" },
  safety_clarification:         { avatar: "inquirer",     label: "Curious Mei" },
  medication_reminder_draft:    { avatar: "pharmacist",   label: "Dr. Apo" },
  follow_up_task_draft:         { avatar: "coordinator",  label: "Planner Yuki" },
  compliance_guardrail:         { avatar: "guardian",     label: "Nurse Iris" },
  family_summary:               { avatar: "messenger",    label: "Postie Ren" },
  memory_update:                { avatar: "memory",       label: "Keeper Sage" },
  final_visit_summary:          { avatar: "storyteller",  label: "Auntie Rosa" },
};
function roleInfo(name: string): RoleInfo {
  return ROLE_INFO[name] ?? { avatar: "orchestrator", label: name };
}
function shortenMessageText(text: string, max = 220): string {
  // mailbox messages may be JSON envelopes — show the summary if the JSON
  // exposes one, otherwise the first chunk of free text.
  let body = text ?? "";
  if (body.startsWith("{")) {
    try {
      const j = JSON.parse(body);
      body = j.summary ?? j.title ?? j.body ?? j.description ?? body;
    } catch { /* keep raw */ }
  }
  body = String(body).trim();
  return body.length > max ? body.slice(0, max - 1) + "…" : body;
}
function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

// Toggle: show full team detail (default) vs. minimal mode (only the
// must-ask questions, recap, and the generated image).
const showTeamDetail = ref(true);

// Highlights — surface only the top-priority items so the visit page reads
// in <5 seconds. Everything else is hidden behind the "Team thinking" toggle.
const topQuestions = computed(() => {
  const all = state.value?.clarifying_questions ?? [];
  const seen = new Set<string>();
  const dedup = all.filter((q: any) => {
    const key = q.question.trim().toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const high = dedup.filter((q: any) => q.priority === "high").slice(0, 4);
  if (high.length >= 4) return high;
  const rest = dedup.filter((q: any) => q.priority !== "high").slice(0, 4 - high.length);
  return [...high, ...rest];
});
const topFlags = computed(() => {
  const all = state.value?.safety_flags ?? [];
  return [
    ...all.filter((f: any) => f.severity === "high"),
    ...all.filter((f: any) => f.severity === "medium"),
  ].slice(0, 3);
});
const topReminders = computed(() =>
  (state.value?.draft_reminders ?? []).slice(0, 3),
);
const hasHighlights = computed(
  () => topQuestions.value.length || topFlags.value.length || topReminders.value.length,
);

// Recap image: cache-bust every regeneration so the browser swaps in the
// freshly written PNG instead of rendering stale bytes. The per-round
// helper below carries a round-index query param so each round's image
// is fetched separately.
// <img> can't send Authorization headers; JWT strategy accepts ?token=, so
// we pass the cookie-stored token in the URL. Without this the recap PNG
// silently 401s and renders broken — exactly what the user reported.
function recapImgToken(): string {
  const token = useCookie<string | null>("clariose_token").value ?? "";
  return token ? `&token=${encodeURIComponent(token)}` : "";
}
const recapImageSrc = computed(() => {
  const r = recap.value;
  if (!r || r.image_status !== "ready") return "";
  const round = r.round_index;
  const roundQ = typeof round === "number" ? `&round=${round}` : "";
  return `/api/visits/${visitId.value}/recap-image?v=${recapImageNonce.value}${roundQ}${recapImgToken()}`;
});
function recapImageSrcFor(roundIndex: number): string {
  const r = recapsByRound.value[roundIndex];
  if (!r || r.image_status !== "ready") return "";
  const ts = new Date(r.generated_at).getTime();
  return `/api/visits/${visitId.value}/recap-image?round=${roundIndex}&v=${ts}${recapImgToken()}`;
}
const recapAge = computed(() => {
  if (!recap.value) return "";
  const ts = new Date(recap.value.generated_at).getTime();
  const sec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
});

async function runRecap(): Promise<void> {
  if (recapBusy.value) return;
  recapBusy.value = true;
  try {
    const r = await carenote.runTeamRecap(visitId.value);
    recap.value = r;
    recapImageNonce.value = Date.now();
    if (typeof r.round_index === "number") {
      recapsByRound.value = { ...recapsByRound.value, [r.round_index]: r };
    }
  } catch (err) {
    console.warn("[carenote] team recap failed", err);
  } finally {
    recapBusy.value = false;
  }
}

async function copyText(s: string) {
  try { await navigator.clipboard.writeText(s); } catch { /* ignore */ }
}

// CLARIOSE_V01 §8.3 — subscribe to /api/visits/:id/events via SSE so the UI
// reacts immediately to backend changes (transcript turns, agent runs,
// blackboard writes) instead of polling every 1.5s. Polling is kept as a
// 30s fallback in case the EventSource silently dies (mobile sleep, proxy).
let eventSource: EventSource | null = null;

function openEventStream() {
  // CLARIOSE_V01: EventSource cannot send Authorization: Bearer headers, so
  // the JWT goes via ?token=… (jwt.strategy.ts accepts both extractors).
  const token = useCookie<string | null>("clariose_token").value;
  if (!token) {
    // Caller will route to /login; SSE won't open in this case.
    return;
  }
  const url = `/api/visits/${visitId.value}/events?token=${encodeURIComponent(token)}`;
  eventSource = new EventSource(url);
  const refreshOn = (type: string) => {
    eventSource?.addEventListener(type, () => { void refresh(); });
  };
  refreshOn("transcript_turn_completed");
  refreshOn("agent_run_completed");
  refreshOn("blackboard_updated");
  refreshOn("visit_status_changed");
  // Fired after each pass of analyze_turn writes a partial slice of the
  // safe envelope — drives the streaming-panel UX. Without this the visit
  // page would only repaint when the LAST agent in the pipeline completes.
  refreshOn("turn_partial_committed");
  // collaboration timeline is fed by mailbox + blackboard + agent runs;
  // refresh whenever any of those change so the avatars feel live.
  const refreshActivityOn = (type: string) => {
    eventSource?.addEventListener(type, () => { void refreshActivity(); });
  };
  refreshActivityOn("mailbox_message");
  refreshActivityOn("blackboard_updated");
  refreshActivityOn("agent_run_started");
  refreshActivityOn("agent_run_completed");
  eventSource.onerror = () => {
    // Silent — fallback poll covers it.
  };
}

onMounted(() => {
  refresh();
  refreshActivity();
  openEventStream();
  pollTimer = setInterval(() => {
    refresh();
    refreshActivity();
  }, 30_000); // fallback only
  elapsedTimer = setInterval(() => {
    elapsed.value = Math.floor((Date.now() - startedAt) / 1000);
  }, 1000);
});

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
  if (elapsedTimer) clearInterval(elapsedTimer);
  eventSource?.close();
});

// CLARIOSE_V02 — pause now closes the current round on the server FIRST so
// the recap that follows operates on the just-closed slice (and so the next
// resume() lands fresh transcripts in the next round). The user explicitly
// asked for "不要互相覆盖或者全部堆在一起" — closing on the server is the
// piece that prevents that.
async function onPause() {
  realtime.pause();
  try {
    await carenote.endRound(visitId.value);
  } catch (err) {
    console.warn("[carenote] endRound failed", err);
  }
  await refresh();
  void runRecap();
}

// On resume the server round is already advanced (endRound did it); we just
// re-enable the mic so new turns land in the new round.
function onResume() {
  realtime.resume();
}

async function onTeamRecap() {
  await refresh();
  await runRecap();
}

// CLARIOSE_V01 §11 Week 4 — End & review now waits for the final-summary
// agent to actually finish before navigating, so the summary page lands on
// real content instead of the "summary will appear here" placeholder. We
// listen to the same SSE stream that's already open: when the
// final_visit_summary role completes (or after an 8-second safety timeout)
// we navigate.
const ending = ref(false);
async function onEnd() {
  if (ending.value) return;
  ending.value = true;
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
  try { await realtime.stop(); } catch { /* ignore */ }
  carenote.finalSummary(visitId.value).catch(() => { /* fire-and-forget; summary keeps generating server-side */ });
  await router.push("/carenote");
}
</script>
