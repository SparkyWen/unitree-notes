# G1 robot memory — read path

## Memory layout

- `memory_summary.md` — already injected into your context; treat as
  background knowledge. Do NOT re-open it.
- `MEMORY.md` — primary searchable registry. Grep this first.
- `rollout_summaries/` — per-session narratives. Open 1–2 most relevant.
- `raw_memories.md` — dense per-session dump. Use as fallback.
- `rollout_path` JSONL — original transcripts at
  `logs/conversations/*.jsonl`. Only grep this if you need exact
  text / numbers / tool-call args that the summaries dropped.

## Recall sequence (do in ≤ 6 steps; stop early if no hits)

1. Skim the memory summary already in your context.
2. Extract 1–3 task-relevant keywords from the user's request.
3. `recall_grep(pattern, scope="registry")` — searches MEMORY.md and
   raw_memories.md.
4. If a hit names a `rollout_summaries/<file>.md`, call
   `recall_read(path)` to read it.
5. If you need exact evidence (commands, error strings, tool args), call
   `recall_grep(pattern, scope="rollouts")` to search rollout_summaries.
6. Last resort: `recall_grep(pattern, scope="jsonl", session_id=...)`
   to hit the raw JSONL transcript of one specific past session.

## Stop conditions

- No hits in MEMORY.md AND user's question isn't about prior context →
  stop, answer from current scene / live state.
- 4–6 search steps and still nothing useful → stop, tell user you don't
  recall this.

## Robot-specific rules

- Treat "上次 / last time / do you remember / 还记得" as a recall trigger.
- Scene-snapshot fields are durable only if they survive multiple
  sessions ("the red cup on the kitchen table" yes; "1 person visible
  at 13:15" no — that's a fact about one moment).
- `action_result.status != "ok"` is a safety/skill lesson; surface it.
- For deep planning, multi-step reasoning, or rare historical fact
  lookup, call `ask_slow_brain(query)` — but only when `recall_*` tools
  can't find it. ask_slow_brain takes 5–20 seconds.

## What memory does NOT contain

- Current scene state — use `describe_scene` / `query_scene_state` tools.
- Current battery / pose — use `query_scene_state`.
- Project code — Codex daemon has its own tools for that.

## TODO (not yet implemented in this milestone)

- `forget(session_id, turn_id)` — when the user says "forget this" or
  "don't remember this", the brain will tag the turn so Phase 2 redacts
  it. For now, this is a manual operation.
