"""Build the session_start passive-injection context.

Reads memory_summary.md + AGENTS.md, applies token-budget truncation,
returns a single string suitable for appending to the fast brain's
developer instructions.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


# Rough char-per-token ratio for cl100k_base on Latin + CJK mixed text.
# We don't import tiktoken because it's an optional dep; the conservative
# estimate is fine for budgeting purposes (real Realtime model has its own
# tokenizer anyway).
_CHARS_PER_TOKEN_EST = 3.0


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Best-effort truncation to roughly max_tokens.

    Uses a conservative char/token ratio. We aim for ~10% safety margin.
    """
    if not text:
        return ""
    char_budget = int(max_tokens * _CHARS_PER_TOKEN_EST * 0.9)
    if len(text) <= char_budget:
        return text
    cut = text[:char_budget].rstrip()
    return cut + "\n\n…[truncated to fit token budget]"


class ContextBuilder:
    def __init__(
        self,
        *,
        memories_dir: Path,
        passive_summary_max_tokens: int = 2500,
        passive_agents_md_max_tokens: int = 1500,
    ):
        self._memories_dir = memories_dir.expanduser().resolve()
        self._summary_tokens = passive_summary_max_tokens
        self._agents_tokens = passive_agents_md_max_tokens

    def build(self) -> str:
        """Return the developer-instructions addendum, or "" if nothing to add."""
        parts: list[str] = []

        agents_md = self._memories_dir / "AGENTS.md"
        if agents_md.exists():
            try:
                text = agents_md.read_text(encoding="utf-8")
                if text.strip():
                    parts.append(
                        "## Project rules (AGENTS.md)\n"
                        + _truncate_to_tokens(text, self._agents_tokens)
                    )
            except OSError as e:
                log.warning("ContextBuilder: cannot read AGENTS.md: %s", e)

        summary_md = self._memories_dir / "memory_summary.md"
        if summary_md.exists():
            try:
                text = summary_md.read_text(encoding="utf-8")
                if text.strip():
                    parts.append(
                        "## Long-term memory (from prior sessions)\n"
                        + _truncate_to_tokens(text, self._summary_tokens)
                    )
            except OSError as e:
                log.warning("ContextBuilder: cannot read memory_summary.md: %s", e)

        if not parts:
            return ""

        header = (
            "\n\n# Robot long-term context\n"
            "The following is curated memory from prior sessions. Treat as "
            "background knowledge. When you need detail beyond this summary, "
            "call the `recall_grep` / `recall_read` / `recall_glob` tools. "
            "For deliberation that needs multi-step reasoning over memory, "
            "call `ask_slow_brain(query)` — sparingly, it takes 10–60 seconds.\n"
        )
        return header + "\n\n" + "\n\n".join(parts) + "\n"
