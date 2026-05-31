// Tiny markdown → HTML for the recall transcript / note viewer.
// Matches the editorial light theme. Escapes input first, then re-introduces
// a small whitelist of inline elements; never v-html on raw user text.
//
// Adapted from the Qagent recall page; trimmed to what the recall UI needs.

/** Click handler for the copy button injected into fenced code blocks
 *  (`<button class="md-copy" data-copy-trigger>`). Wire it to whatever
 *  container holds the v-html'd markdown:
 *
 *      <div v-html="renderMarkdown(text)" @click="onMarkdownCopyClick" />
 *
 *  Lives here (not in each consumer) so the chat transcript and the note
 *  viewer modal stay in sync. */
export function onMarkdownCopyClick(e: MouseEvent): void {
  const target = (e.target as HTMLElement | null)?.closest("[data-copy-trigger]") as HTMLButtonElement | null;
  if (!target) return;
  e.preventDefault();
  const pre = target.closest("pre");
  const code = pre?.querySelector("code")?.textContent ?? "";
  if (!code) return;
  const flash = (): void => {
    target.classList.add("is-copied");
    target.setAttribute("aria-label", "Copied");
    window.setTimeout(() => {
      target.classList.remove("is-copied");
      target.setAttribute("aria-label", "Copy code");
    }, 1400);
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(code).then(flash).catch(() => fallbackCopy(code, flash));
  } else {
    fallbackCopy(code, flash);
  }
}

function fallbackCopy(code: string, after: () => void): void {
  try {
    const ta = document.createElement("textarea");
    ta.value = code;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    after();
  } catch { /* ignore */ }
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function inline(s: string): string {
  return s
    .replace(/`([^`]+)`/g, '<code class="md-code-inline">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="md-strong">$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em class="md-em">$2</em>')
    .replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener" class="md-link">$1</a>',
    )
    // Bare file:line refs become highlighted spans (the recall page parses
    // these into clickable chips separately, but standalone they render
    // legibly here).
    .replace(/(\b[A-Za-z0-9_./\-]+\.(?:md|txt|jsonl):\d+(?:-\d+)?)/g,
      '<span class="md-citation">$1</span>');
}

export function renderMarkdown(src: string): string {
  if (!src) return "";
  const escaped = escapeHtml(src);
  const lines = escaped.split(/\n/);
  const out: string[] = [];
  let inCode = false;
  let inUl = false;
  let inOl = false;
  let codeBuf: string[] = [];

  function closeLists() {
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
  }

  for (const raw of lines) {
    if (raw.startsWith("```")) {
      if (inCode) {
        out.push(
          `<pre class="md-pre"><button class="md-copy" data-copy-trigger aria-label="Copy code">⧉</button><code>${codeBuf.join("\n")}</code></pre>`,
        );
        codeBuf = [];
        inCode = false;
      } else {
        closeLists();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeBuf.push(raw);
      continue;
    }
    if (/^#{1,6}\s+/.test(raw)) {
      closeLists();
      const m = /^(#{1,6})\s+(.*)$/.exec(raw)!;
      const level = m[1].length;
      out.push(`<h${level} class="md-h${level}">${inline(m[2])}</h${level}>`);
      continue;
    }
    if (/^\s*[-*+]\s+/.test(raw)) {
      if (!inUl) { closeLists(); out.push('<ul class="md-ul">'); inUl = true; }
      out.push(`<li class="md-li">${inline(raw.replace(/^\s*[-*+]\s+/, ""))}</li>`);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(raw)) {
      if (!inOl) { closeLists(); out.push('<ol class="md-ol">'); inOl = true; }
      out.push(`<li class="md-li">${inline(raw.replace(/^\s*\d+\.\s+/, ""))}</li>`);
      continue;
    }
    if (/^\s*&gt;\s+/.test(raw)) {
      closeLists();
      out.push(`<blockquote class="md-quote">${inline(raw.replace(/^\s*&gt;\s+/, ""))}</blockquote>`);
      continue;
    }
    if (/^\s*---\s*$/.test(raw)) {
      closeLists();
      out.push('<hr class="md-hr" />');
      continue;
    }
    if (raw.trim()) {
      closeLists();
      out.push(`<p class="md-p">${inline(raw)}</p>`);
    }
  }
  closeLists();
  if (inCode) {
    out.push(`<pre class="md-pre"><code>${codeBuf.join("\n")}</code></pre>`);
  }
  return out.join("\n");
}
