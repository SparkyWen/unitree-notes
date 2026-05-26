# Read path policy

This file is informational. The recall coordinator's read protocol is
delivered in its system prompt; this is a copy for human reference.

1. Skim memory_summary.md
2. Generate 1–3 keywords from the question
3. `rg -n -i` MEMORY.md
4. Open at most 2–3 referenced files with `sed -n`
5. Fall back to notes/ or raw_memories.md only if needed
6. Stop after 4–6 search steps
