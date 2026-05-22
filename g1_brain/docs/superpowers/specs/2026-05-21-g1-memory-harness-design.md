# Spec: G1 Memory Harness — Codex-style memory + ask_slow_brain

> Date: 2026-05-21
> Project: g1_brain (Unitree G1 robot brain)
> Master design doc: `~/unitree/unitree-notes/docs/harness-design.md`
> Status: spec freeze, ready for writing-plans

This spec is the brainstorming output for adding a Codex-style memory recall subsystem and a minimal Codex daemon (`ask_slow_brain`) to the existing G1 brain. It complements (and does not duplicate) the full design document at `~/unitree/unitree-notes/docs/harness-design.md`.

---

## Goal

Give the G1 robot **long-term memory across sessions** and **a slow-brain consultation channel**, while keeping the fast voice loop (`BrainRealtimeAgent` + OpenAI Realtime) untouched in its critical path.

The robot must be able to:
1. **Passively recall** prior-session knowledge at session start (memory_summary.md injected into Realtime developer instructions).
2. **Actively recall** historical facts during a turn (LLM calls `recall_grep` / `recall_read` / `recall_glob` over markdown + JSONL).
3. **Consult a deliberative brain** for multi-step reasoning (LLM calls `ask_slow_brain(query)`; backed by a persistent `codex mcp-server` subprocess).

All LLM work routes through the user's existing Codex subscription — no direct OpenAI API billing.

## Non-goals (this spec)

- No `forget(turn_id)` tool (TODO).
- No periodic Phase2 tick (only triggered after Phase1 done).
- No multi-modal Phase1 (frame_ref placeholder only).
- No FTS5 / vector index (grep markdown is fast enough for current scale).
- No planning / coordinator / multi-agent features (future specs).
- No real-codex CI test (manual only before release).
- No historical JSONL backfill (only sessions starting after memory-enable date).

## Locked architectural decisions

| Decision | Choice | Rationale |
|---|---|---|
| Codex's role | **Parallel slow brain above BrainRealtimeAgent** | Voice fast-path stays intact |
| Memory content scope | **Experiential**: conversation + tool + scene_snapshot + action_result + safety_event | Robot must recall what it saw/did, not just what was said |
| Codex cadence | **Resident daemon** lifecycle-bound to g1_brain process | Subprocess restart overhead avoided |
| LLM engine | **Codex subscription only**, three modes: `codex exec --json --ephemeral` x2 (Phase1, Phase2) + `codex mcp-server` x1 (daemon) | No direct OpenAI API charges |
| Storage location | **`~/.unitree/g1_brain/`** robot-scoped (not `~/.codex/`) | Isolation from user's personal Codex |
| File layout | **Mirrors `~/.codex/memories/`** (MEMORY.md, memory_summary.md, raw_memories.md, rollout_summaries/, .git/) | Reuse Codex's mature design |
| JSONL schema | **Extend meta subtype** (no new top-level types) | Preserve Claude-harness compatibility |
| IPC for daemon | **MCP over stdio** (`codex mcp-server`) | OpenAI's official stable interface |
| `CODEX_HOME` | **`<robot_root>/.codex_runtime`** isolated | Daemon rollouts don't leak to personal Codex |
| Slow-brain sandbox | **`read-only`** | Phase2 writes via Python atomic_write, not via daemon |
| ask concurrency | **mutex + queue_max=2**, third caller → `queue_full` | LLM doesn't wait 60s; falls back to recall_grep |
| Recall paradigm | **LLM uses rg/Read/Glob itself**, no Python-side ranking | Codex / CC共同范式 |
| LSP | **Not used** | Memory is .md + .jsonl, LSP is for source code symbols |
| Historical backfill | **None** | Pre-memory JSONL is noise |
| Memory enable marker | **First line of MEMORY.md: `# Memory enabled at <ISO>`** | Time anchor |
| Phase2 trigger | **Only after Phase1 done, no idle tick** | Save subscription quota |
| forget(turn) | **TODO** | Not in this spec |
| PII redaction | **Phase1 prompt only**, no Python regex blacklist | Codex's own approach |
| `memory.enabled` default | **true** | User confirmed |
| Mock boundary | **Only codex subprocess** (SQLite/git/rg/filesystem all real) | CI parity, no fragile mocks |

## What gets built

### New Python package: `g1_brain/g1_brain/memory/`

```
memory/
├── __init__.py          MemorySubsystem facade
├── storage.py           SQLite schema + file-tree read/write + atomic_write
├── jobs.py              claim / lease / retry / heartbeat
├── phase1.py            Phase1 worker + JSONL→prompt builder
├── phase2.py            Phase2 worker + sync + git diff + consolidation
├── recall.py            recall_grep / recall_read / recall_glob + sandbox
├── context.py           build_passive_context() with token truncation
├── codex_client.py      `codex exec --json` wrapper, JSON event stream parser
├── daemon.py            CodexDaemon: MCP client over stdio, mutex+queue, cancel
├── schemas.py           AskResult dataclass, event-type constants
└── prompts/
    ├── phase1_system.md
    ├── phase2_system.md
    └── default_agents_md.md
```

### New CLI: `g1_brain/g1_brain/tools/reset_memory.py`

Flags: `--rebuild-state` / `--rebuild-git` / `--reset-md` / `--nuke`; nuke requires two `--confirm` flags.

### Modifications to existing files (4 files)

| File | Change |
|---|---|
| `apps/agent_main.py` | 3 insertions: MemorySubsystem instantiation, passive context injection, shutdown step |
| `brain/conversation_logger.py` | 3 new public methods: `log_scene_snapshot`, `log_action_result`, `log_safety_event` |
| `skills/skill_server.py` | New `memory` kwarg; 4 new `_skill_*` methods; `execute()` end-of-call action_result write; `on_response_canceled` cancel-token propagation |
| `skills/tool_schemas.py` | 4 new tool schemas: `recall_grep`, `recall_read`, `recall_glob`, `ask_slow_brain` |
| `configs/g1_brain.yaml` | New `memory:` section |

### Single-line wirings (4 files)

| File | Line change |
|---|---|
| `brain/conversation_state.py` | IDLE→CAPTURING → `conv_logger.log_scene_snapshot(trigger="turn_start", ...)` |
| `safety/state_machine.py` | `RobotFsm.transition_to` end → `conv_logger.log_safety_event(kind="fsm_transition", ...)` |
| `safety/vision_risk_gate.py` | RISK verdict → `conv_logger.log_safety_event(kind="vision_gate_risk", ...)` |
| `safety/estop_listener.py` | E-stop fired → `conv_logger.log_safety_event(kind="estop", ...)` |

## Data model

### File tree (robot-scoped)

```
~/.unitree/g1_brain/
├── memories/
│   ├── AGENTS.md
│   ├── MEMORY.md
│   ├── memory_summary.md
│   ├── raw_memories.md
│   ├── rollout_summaries/{session_id}-{ts}-{slug}.md
│   ├── .git/
│   └── .gitignore
├── state.sqlite      (WAL mode)
└── .codex_runtime/   (CODEX_HOME)
```

### SQLite (full schema in master doc § 3.2)

Three tables: `sessions`, `stage1_outputs`, `jobs` + `schema_version`. WAL mode. Indexes on `stage1_outputs(source_updated_at DESC)` and `jobs(kind, status, retry_at, lease_until)`.

### JSONL meta subtypes added

- `meta.scene_snapshot` — trigger ∈ {turn_start, pre_motion, post_motion}; persons_visible, ground_constraint, nearest_*_m, detections_summary, frame_ref (null this milestone)
- `meta.action_result` — tool_use_id, tool_name, args, status ∈ {ok, blocked_by_safety, exec_error, canceled}, outcome_metrics (displacement_m sim-only this milestone), result_payload_brief ≤ 256 bytes
- `meta.safety_event` — kind ∈ {tool_rejected, fsm_transition, vision_gate_risk, estop}, rule/from_state/to_state/details/associated_tool_use_id

## Pipeline timing (the three flows)

### Write flow

```
event → ConversationLogger.log_*() → JSONL append
plan_done → jobs.enqueue("phase1", session_id, debounce 30s)
Phase1 worker → claim → codex exec → UPSERT stage1_outputs
Phase2 evaluator → claim global lock → sync raw_memories/rollout_summaries
                 → git diff → if dirty: codex exec → MEMORY.md + memory_summary.md
                 → git commit baseline
```

### Read flow (passive)

`session_start` → `build_passive_context()` reads memory_summary.md (≤2500 tok) + AGENTS.md (≤1500 tok) → `brain_agent.append_developer_instructions(...)` ONE TIME ONLY. Phase2 mid-session updates don't refresh this session.

### Read flow (active)

LLM calls `recall_grep` (rg over scoped files) / `recall_read` (sandboxed file read) / `recall_glob` (Path.glob). All purely local, milliseconds. LLM iterates following AGENTS.md's 4-6 step recall protocol.

### Deliberation flow

LLM calls `ask_slow_brain(query, timeout_s=20)` → SkillServer → daemon → MCP `tools/call` → codex → stream → final text or partial-on-cancel/timeout. Barge-in propagates as `cancel_event.set()` → MCP `notifications/cancelled`.

## Testing strategy (full detail in master doc § 9)

- **Unit tests** per module, 60-80 total; pytest + tmp_path
- **Integration tests** 8-12: full pipeline E2E (mock codex only), recall after write, ask_slow_brain cancel chain, failure modes
- **E2E**: extend `test_vertical_slice.py` to assert memory injection + new meta events
- **Mock boundary**: only `codex exec` and `codex mcp-server` subprocesses; everything else real
- `tests/manual/` for real-codex smoke (release-time only)
- `pytest-snapshot` library added

## Failure modes (full matrix in master doc § 8.2)

Core invariant: **memory subsystem failure must not affect the fast brain motion path**. Every layer fails gracefully:
- Memory disabled → all 4 tools return `{"status":"memory_disabled"}`
- Daemon dead after 5 restarts → `ask_slow_brain` returns `daemon_dead`
- Codex subscription quota → 30-min cool-down on Phase + daemon, both report `quota_exhausted`
- Sandbox violations → tool returns `path_outside_sandbox`, never an exception to the agent loop

## Security & isolation

- `~/.unitree/g1_brain/` is robot-scoped; never touches `~/.codex/`
- `CODEX_HOME=<robot>/.codex_runtime` overrides Codex's home
- `--ignore-user-config` prevents personal config.toml from affecting daemon
- `--sandbox read-only` prevents daemon from writing
- recall path sandbox: dual check via `.resolve().relative_to(allowed_root)`
- Phase2 sub-LLM prompt: "DO NOT use any tools; output only the JSON object"

## What this spec does NOT specify (deferred to writing-plans)

- Exact prompt template wording for Phase1/Phase2 (drafted in design doc § 4)
- Exact PHASE1_SCHEMA / PHASE2_SCHEMA JSON Schema files
- Exact `MockMcpServer` / `MockCodexExecRunner` interfaces
- Test fixture JSONL contents (4 sample sessions described, content TBD)
- Exact `AGENTS.md` default content (template in design doc § 5.5)

These are implementation details; the design doc has enough to act.

## Acceptance

This work is "done" when:
1. All code in § "What gets built" exists and matches the design.
2. `pytest -m "not bench and not manual"` is green.
3. Fresh-machine smoke: `agent_main` boots with `memory.enabled: true`, completes one turn, exits cleanly, and a subsequent boot picks up the memory_summary.md generated by Phase2.
4. `tests/manual/test_real_codex_smoke.py` (optional, release-only) ran successfully on the user's machine.

---

## Cross-reference

For every implementation detail (full schema, full prompts, sequence diagrams, error matrix, file-by-file diffs), see the master design doc:

`/home/helios/unitree/unitree-notes/docs/harness-design.md`

This spec is intentionally a thin index over that doc to satisfy the brainstorming workflow's "spec → plan → code" pipeline.
