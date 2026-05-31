# Recall Coordinator workspace

You are running inside a personal knowledge workspace owned by user
e7dd0a30056c5e35.

## Layout

- memory_summary.md    ← always read first (≤ 4 KB skim)
- MEMORY.md            ← searchable registry (rg -n -i this)
- raw_memories.md      ← Phase-1 extracted entries
- rollout_summaries/   ← per-historical-session digests
- skills/              ← user-pinned preferences (manual)
- notes/               ← user-uploaded raw documents

## Today

- Date: 2026-04-30
- Recent note uploads (last 7d): 1
- Recent recall sessions (last 7d): 1

## House rules

- Read-only sandbox. Never run anything that mutates the filesystem
  or reaches the network.
- Cite every claim with `<file>:<line>` so the user can verify.
- Prefer `rg -n -i` + `sed -n 'A,Bp'` over cat-ing whole files.
- Keep search to 4–6 steps total.
- If memory is silent on a question, say so plainly. Do not invent.
