<script setup lang="ts">
/**
 * TranscriptStream — canvas-rendered streaming transcript.
 *
 * Replaces the previous DOM-based bubble list. All text layout (line breaking,
 * width measurement, height) is computed by `@chenglou/pretext`, then painted
 * on a single <canvas>. This keeps streaming partials cheap: each delta only
 * re-prepares the partial buffer (small string) and repaints — no Vue v-for
 * diff over hundreds of utterances, no DOM reflow per token.
 *
 * Layout per block:
 *   ┌── 1.5px dot
 *   │ HEADER (mono, 10px)              · time (mono)
 *   │
 *   │ Body text wrapped to inner width via pretext layoutWithLines.
 *   └──
 *
 * Doctor blocks are left-aligned with a rose accent. Patient blocks are right-
 * aligned with a sage accent. The current partial draws muted, with a pulsing
 * dot and a `LISTENING…` label.
 *
 * Note: this file is `.client.vue` because pretext requires `Intl.Segmenter`
 * and a Canvas2D context — both unavailable during Nuxt SSR.
 */
import {
  prepareWithSegments,
  layoutWithLines,
  type LayoutLine,
  type PreparedTextWithSegments,
} from '@chenglou/pretext';

type Utterance = {
  id: string;
  speaker: 'doctor' | 'patient' | 'unknown';
  text: string;
  startedAt: number;
  isFinal: boolean;
};

const props = defineProps<{ utterances: Utterance[]; partial?: string }>();

// ── Visual constants ─────────────────────────────────────────────────────
const HORIZONTAL_PAD = 20;          // canvas inner padding (matches px-5)
const VERTICAL_PAD   = 20;          // top/bottom pad
const HEADER_HEIGHT  = 12;          // header (speaker · time) row height
const HEADER_GAP     = 8;           // gap between header and body
const BLOCK_GAP      = 22;          // gap between two utterance blocks
const BODY_LINE_HEIGHT = 22;        // body line height (matches leading-relaxed at 14.5px)
const DOT_RADIUS     = 3;
const DOT_TEXT_GAP   = 10;
const RIGHT_BLOCK_PAD = 28;         // patient block: leave room for the dot on the right

const HEADER_FONT  = '600 10px ui-monospace, "JetBrains Mono", Menlo, monospace';
const BODY_FONT    = '400 14.5px Inter, system-ui, -apple-system, sans-serif';
const PARTIAL_FONT = '400 14.5px Inter, system-ui, -apple-system, sans-serif';

const COLOR = {
  doctor:  { dot: '#e11d48', label: '#be123c', text: '#1f2937' },
  patient: { dot: '#10b981', label: '#047857', text: '#1f2937' },
  unknown: { dot: '#9ca3af', label: '#6b7280', text: '#374151' },
  partial: { dot: '#9ca3af', label: '#9ca3af', text: '#6b7280' },
} as const;
const TIME_COLOR = '#9ca3af';

// ── Refs ─────────────────────────────────────────────────────────────────
const wrap   = ref<HTMLDivElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const cssWidth = ref(0);
const dpr      = ref(1);
const fontsReady = ref(false);
const pulsePhase = ref(0);

let resizeObserver: ResizeObserver | null = null;
let pulseRaf: number | null = null;

// ── Layout cache ─────────────────────────────────────────────────────────
// Keyed by `${font}\x00${width}\x00${text}`. For finalized utterances the key
// is stable across re-renders, so we only re-prepare what's new.
type LaidOut = { lines: LayoutLine[]; height: number };
const layoutCache = new Map<string, LaidOut>();
const MAX_CACHE = 512;

function layText(text: string, font: string, width: number): LaidOut {
  if (!text) return { lines: [], height: 0 };
  const key = `${font}\x00${width}\x00${text}`;
  const hit = layoutCache.get(key);
  if (hit) return hit;
  let prepared: PreparedTextWithSegments;
  try {
    prepared = prepareWithSegments(text, font);
  } catch {
    return { lines: [{ text, width: 0 } as unknown as LayoutLine], height: BODY_LINE_HEIGHT };
  }
  const r = layoutWithLines(prepared, Math.max(40, width), BODY_LINE_HEIGHT);
  const out: LaidOut = { lines: r.lines, height: r.height };
  layoutCache.set(key, out);
  if (layoutCache.size > MAX_CACHE) {
    // Drop the oldest entry (Map preserves insertion order).
    const firstKey = layoutCache.keys().next().value as string | undefined;
    if (firstKey) layoutCache.delete(firstKey);
  }
  return out;
}

// ── Block model (data-only, no DOM) ──────────────────────────────────────
type Block = {
  speaker: Utterance['speaker'] | 'partial';
  time: string;
  align: 'left' | 'right';
  lines: LayoutLine[];
  bodyHeight: number;
  totalHeight: number;
};

function fmtTime(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

const blocks = computed<Block[]>(() => {
  if (!cssWidth.value) return [];
  if (!fontsReady.value) return []; // Defer until Inter has loaded so widths match the visual font.
  const innerWidth = Math.max(80, cssWidth.value - HORIZONTAL_PAD * 2 - RIGHT_BLOCK_PAD);
  const out: Block[] = [];
  for (const u of props.utterances) {
    const align: Block['align'] = u.speaker === 'patient' ? 'right' : 'left';
    const r = layText(u.text, BODY_FONT, innerWidth);
    out.push({
      speaker: u.speaker,
      time: fmtTime(u.startedAt),
      align,
      lines: r.lines,
      bodyHeight: r.height,
      totalHeight: HEADER_HEIGHT + HEADER_GAP + r.height,
    });
  }
  if (props.partial) {
    const r = layText(props.partial, PARTIAL_FONT, innerWidth);
    out.push({
      speaker: 'partial',
      time: '',
      align: 'left',
      lines: r.lines,
      bodyHeight: r.height,
      totalHeight: HEADER_HEIGHT + HEADER_GAP + r.height,
    });
  }
  return out;
});

const totalContentHeight = computed(() => {
  if (!blocks.value.length) return 1;
  let h = VERTICAL_PAD;
  for (let i = 0; i < blocks.value.length; i++) {
    h += blocks.value[i].totalHeight;
    if (i < blocks.value.length - 1) h += BLOCK_GAP;
  }
  h += VERTICAL_PAD;
  return h;
});

// ── Painting ─────────────────────────────────────────────────────────────
function draw() {
  const c = canvas.value;
  if (!c || !cssWidth.value) return;
  const w = cssWidth.value;
  const h = totalContentHeight.value;

  // Resize backing store. Avoid resetting if dimensions unchanged — that would
  // clear the canvas unnecessarily on a no-op repaint.
  const targetW = Math.round(w * dpr.value);
  const targetH = Math.max(1, Math.round(h * dpr.value));
  if (c.width !== targetW)  c.width  = targetW;
  if (c.height !== targetH) c.height = targetH;
  c.style.width  = w + 'px';
  c.style.height = h + 'px';

  const ctx = c.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(dpr.value, 0, 0, dpr.value, 0, 0);
  ctx.clearRect(0, 0, w, h);

  let y = VERTICAL_PAD;
  for (let i = 0; i < blocks.value.length; i++) {
    const b = blocks.value[i];
    drawBlock(ctx, b, w, y);
    y += b.totalHeight;
    if (i < blocks.value.length - 1) y += BLOCK_GAP;
  }
}

function drawBlock(ctx: CanvasRenderingContext2D, b: Block, w: number, y: number) {
  const isPartial = b.speaker === 'partial';
  const palette = isPartial ? COLOR.partial :
    b.speaker === 'doctor'  ? COLOR.doctor :
    b.speaker === 'patient' ? COLOR.patient : COLOR.unknown;

  const labelText = isPartial ? 'LISTENING…' :
    b.speaker === 'doctor'  ? 'DOCTOR' :
    b.speaker === 'patient' ? 'PATIENT' : 'VOICE';

  // Dot
  const dotY = y + HEADER_HEIGHT / 2;
  let dotX: number;
  if (b.align === 'left') {
    dotX = HORIZONTAL_PAD + DOT_RADIUS;
  } else {
    dotX = w - HORIZONTAL_PAD - DOT_RADIUS;
  }
  ctx.save();
  ctx.fillStyle = palette.dot;
  if (isPartial) {
    // pulsing alpha based on RAF phase
    const a = 0.45 + 0.35 * (0.5 + 0.5 * Math.sin(pulsePhase.value));
    ctx.globalAlpha = a;
  }
  ctx.beginPath();
  ctx.arc(dotX, dotY, DOT_RADIUS, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // Header (label · time)
  ctx.font = HEADER_FONT;
  ctx.textBaseline = 'middle';
  if (b.align === 'left') {
    ctx.textAlign = 'left';
    const labelX = HORIZONTAL_PAD + DOT_RADIUS * 2 + DOT_TEXT_GAP;
    ctx.fillStyle = palette.label;
    ctx.fillText(labelText, labelX, dotY);
    if (b.time) {
      const labelW = ctx.measureText(labelText).width;
      ctx.fillStyle = TIME_COLOR;
      ctx.fillText('  ·  ' + b.time, labelX + labelW, dotY);
    }
  } else {
    ctx.textAlign = 'right';
    const labelX = w - HORIZONTAL_PAD - DOT_RADIUS * 2 - DOT_TEXT_GAP;
    ctx.fillStyle = palette.label;
    if (b.time) {
      const timeText = b.time + '  ·  ';
      ctx.fillStyle = TIME_COLOR;
      ctx.fillText(timeText, labelX - ctx.measureText(labelText).width, dotY);
      ctx.fillStyle = palette.label;
    }
    ctx.fillText(labelText, labelX, dotY);
  }

  // Body lines (paint via pretext-computed line strings)
  ctx.font = isPartial ? PARTIAL_FONT : BODY_FONT;
  ctx.fillStyle = palette.text;
  ctx.textBaseline = 'top';
  if (isPartial) ctx.globalAlpha = 0.78;
  let lineY = y + HEADER_HEIGHT + HEADER_GAP;
  for (const line of b.lines) {
    if (b.align === 'right') {
      ctx.textAlign = 'right';
      ctx.fillText(line.text, w - HORIZONTAL_PAD - DOT_RADIUS * 2 - DOT_TEXT_GAP, lineY + 2);
    } else {
      ctx.textAlign = 'left';
      ctx.fillText(line.text, HORIZONTAL_PAD + DOT_RADIUS * 2 + DOT_TEXT_GAP, lineY + 2);
    }
    lineY += BODY_LINE_HEIGHT;
  }
  ctx.globalAlpha = 1;
}

// ── Reactivity wiring ────────────────────────────────────────────────────
function measure() {
  if (!wrap.value) return;
  const rect = wrap.value.getBoundingClientRect();
  if (rect.width !== cssWidth.value) cssWidth.value = rect.width;
  const newDpr = Math.max(1, window.devicePixelRatio || 1);
  if (newDpr !== dpr.value) dpr.value = newDpr;
}

function autoScroll() {
  const w = wrap.value;
  if (!w) return;
  // Only stick to bottom if the user was already near the bottom — lets them
  // scroll up to read earlier turns without being yanked back.
  const distFromBottom = w.scrollHeight - (w.scrollTop + w.clientHeight);
  if (distFromBottom < 80) {
    w.scrollTop = w.scrollHeight;
  }
}

// Re-paint whenever the data, width, dpr, or font readiness changes.
watch([blocks, cssWidth, dpr], () => {
  draw();
  void nextTick(autoScroll);
});

// Pulsing partial dot — only animate while there's a partial.
function startPulse() {
  if (pulseRaf != null) return;
  const t0 = performance.now();
  const tick = (now: number) => {
    pulsePhase.value = (now - t0) / 220;
    // Just repaint the canvas — the rest of the layout is unchanged.
    draw();
    pulseRaf = requestAnimationFrame(tick);
  };
  pulseRaf = requestAnimationFrame(tick);
}
function stopPulse() {
  if (pulseRaf != null) { cancelAnimationFrame(pulseRaf); pulseRaf = null; }
}
watch(() => !!props.partial, has => { has ? startPulse() : (stopPulse(), draw()); });

onMounted(async () => {
  measure();
  // Wait for fonts before the first prepare — pretext measures via canvas, so
  // unloaded fonts give wrong widths and we'd cache them.
  try {
    if ((document as any).fonts?.ready) await (document as any).fonts.ready;
  } catch { /* older browsers — proceed anyway */ }
  fontsReady.value = true;

  if (typeof ResizeObserver !== 'undefined' && wrap.value) {
    resizeObserver = new ResizeObserver(() => { measure(); draw(); });
    resizeObserver.observe(wrap.value);
  }
  draw();
  void nextTick(autoScroll);
  if (props.partial) startPulse();
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  stopPulse();
  layoutCache.clear();
});

// ── Copy fallback ────────────────────────────────────────────────────────
// Canvas text isn't selectable. Provide an explicit copy action so users can
// still extract the transcript.
async function copyAll() {
  const text = props.utterances
    .map(u => `${u.speaker === 'doctor' ? 'Doctor' : u.speaker === 'patient' ? 'Patient' : 'Voice'} (${fmtTime(u.startedAt)}): ${u.text}`)
    .join('\n');
  if (!text) return;
  try { await navigator.clipboard.writeText(text); } catch { /* ignore */ }
}
</script>

<template>
  <div class="card flex h-full flex-col overflow-hidden">
    <div class="flex items-center justify-between border-b border-line px-5 py-3">
      <p class="eyebrow">Transcript</p>
      <div class="flex items-center gap-3">
        <button
          v-if="utterances.length"
          class="font-mono text-[10px] uppercase tracking-[0.2em] text-ink-400 transition hover:text-ink-700"
          @click="copyAll"
        >
          copy
        </button>
        <span class="font-mono text-[10.5px] uppercase tracking-[0.22em] text-ink-400">
          {{ utterances.length }} utt · pretext
        </span>
      </div>
    </div>

    <div ref="wrap" class="relative flex-1 overflow-y-auto"
         role="log"
         aria-live="polite"
         aria-label="Live consultation transcript">
      <canvas ref="canvas" class="block w-full" aria-hidden="true" />
      <div v-if="!utterances.length && !partial"
           class="pointer-events-none absolute inset-0 flex items-center justify-center px-6 text-center text-[13px] italic text-ink-400">
        Tap the orb to begin. Words appear here, in time.
      </div>
      <!-- SR-only mirror so screen readers can still read live updates. -->
      <ol class="sr-only">
        <li v-for="u in utterances" :key="u.id">
          {{ u.speaker === 'doctor' ? 'Doctor' : u.speaker === 'patient' ? 'Patient' : 'Voice' }}: {{ u.text }}
        </li>
        <li v-if="partial">Listening: {{ partial }}</li>
      </ol>
    </div>
  </div>
</template>
