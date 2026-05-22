# G1 Brain · Codex-style Memory Harness 设计

> Status: design freeze · 2026-05-21
> Scope: 在现有 `g1_brain` 上接入 Codex-style memory recall 子系统 + 最小 Codex daemon 基建,完成"快脑 Realtime + 慢脑 Codex"双层 harness 的第一里程碑

---

## 0. 设计起源与意图

机器人当前以本地小模型(YOLO / MediaPipe)做感知,以 OpenAI Realtime 做对话与工具调度,但**没有跨会话的长期记忆**:用户说过的事、机器人尝试过的动作、命中过的安全规则,session 结束就丢失。本设计把当下 AI harness 生态里最成熟的两套范式(OpenAI Codex 的 memory pipeline、Claude Code 的 .md memory)迁移到 G1 上:

- **慢脑 = Codex CLI 子进程**,作为 deliberative 大脑通过 `ask_slow_brain` tool 被快脑按需调用。
- **memory 子系统**生成、整合并向快脑注入跨会话经验,完全文件 + SQLite 双层(无向量库、无 embedding)。
- **快脑(BrainRealtimeAgent)继续做 voice 主调度**,新增 3 个 recall 原语 tool + 1 个 ask_slow_brain tool。

参考资料:
- `docs/references/CDXLearn/cdx_notes/5. Codex召回.md`
- `docs/references/CCLearn/notes/notes_integrated/5. 记忆召回与处理机制.md`
- `docs/references/CDXLearn/openai-codex-source/codex-main/codex-rs/memories/`
- `docs/references/CCLearn/source/src/memdir/` and `services/autoDream/`

---

## 1. 架构总览

### 1.1 双脑并存形态

```
┌─────────────────────────────────────────────────────────────────────┐
│ g1_brain process (agent_main._run)                                  │
│                                                                     │
│  ┌──────────────────────────┐         ┌──────────────────────────┐  │
│  │ Fast Brain (existing)    │         │ Memory Subsystem (new)   │  │
│  │ ────────────────────     │         │ ────────────────────     │  │
│  │ BrainRealtimeAgent       │         │  ├ Phase1 worker         │  │
│  │  ├ OpenAI Realtime WS    │         │  ├ Phase2 worker         │  │
│  │  ├ ConversationStateM    │         │  ├ Recall (grep/read/    │  │
│  │  ├ SkillServer           │ ──IPC── │  │   glob)               │  │
│  │  ├ SafetySupervisor      │         │  ├ State DB (SQLite)     │  │
│  │  └ ConversationLogger    │         │  └ Codex daemon proxy    │  │
│  │     │                    │         │     │                    │  │
│  │     ▼ JSONL append       │         │     ▼ MCP stdio          │  │
│  │  logs/conversations/     │         │  codex mcp-server         │  │
│  │     *.jsonl ────────────────────────┐    (resident subprocess) │  │
│  └──────────────────────────┘         │ └──────────────────────────┘  │
│                                       │              │              │
│                                       ▼              │              │
│            ┌──────────────────────────────────────────┐              │
│            │ ~/.unitree/g1_brain/ (robot-scoped)      │              │
│            │  ├ memories/                             │              │
│            │  │   ├ AGENTS.md  (人手写 read_path 指引) │              │
│            │  │   ├ MEMORY.md  (≤25KB Phase2 输出)    │              │
│            │  │   ├ memory_summary.md (≤8KB Phase2)   │              │
│            │  │   ├ raw_memories.md (Phase2 入口)     │              │
│            │  │   ├ rollout_summaries/*.md            │              │
│            │  │   └ .git/  (workspace diff baseline)  │              │
│            │  ├ state.sqlite                          │              │
│            │  └ .codex_runtime/  (CODEX_HOME 隔离)    │              │
│            └──────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 分层职责

| 层 | 模块 | 职责 | 触发点 |
|---|---|---|---|
| L0 数据 | `~/.unitree/g1_brain/` | 文件 + SQLite 双层持久化 | 文件级原子写 |
| L1 存储 | `memory/storage.py` | DB schema、文件读写、git baseline | 进程内同步 |
| L1 调度 | `memory/jobs.py` | claim / lease / retry / heartbeat | jobs 表 |
| L2 写路径 | `memory/phase1.py` | rollout JSONL → raw_memory + summary | `plan_done` 后入队 |
| L2 写路径 | `memory/phase2.py` | 全局整合 → MEMORY.md / memory_summary.md | Phase1 完成后 |
| L2 读路径 | `memory/recall.py` | grep / read / glob 三 tool + 沙箱 | LLM tool call |
| L2 读路径 | `memory/context.py` | session_start 注入 passive context | agent_main 启动 |
| L3 IPC | `memory/daemon.py` | Codex MCP daemon + ask_slow_brain | LLM tool call |
| L3 IPC | `memory/codex_client.py` | `codex exec` 一次性进程 wrapper | Phase1/Phase2 调 |
| L4 接入 | `brain/conversation_logger.py` 扩 | 新增 3 种 meta subtype | turn 内事件 |
| L4 接入 | `skills/skill_server.py` | 新 4 tool + execute() 末尾自动写 action_result | LLM tool call |
| L4 接入 | `apps/agent_main.py` | 启动/关闭 memory + passive context 注入 | _run() lifecycle |

### 1.3 三条数据流

**写流(每个 turn 之后)**:
```
ConversationLogger.log_*  →  JSONL append
                         ↓
                plan_done hook  →  jobs.enqueue("phase1", session_id, debounce 30s)
                         ↓
                Phase1 worker (async, mutex) → claim → codex exec --json --ephemeral
                         ↓
                UPSERT stage1_outputs (raw_memory, summary, slug)
                         ↓
                Phase2 evaluator (Phase1 done 后立刻评估)
                         ↓
                claim global lock → sync rollout_summaries/ + raw_memories.md
                                  → git diff
                                  → if dirty: codex exec → MEMORY.md + memory_summary.md
                                  → git commit baseline
```

**读流(每个 session 启动 + 每次 LLM 召回)**:
```
session_start hook
  → memory.context.build_passive_context()
    → read memory_summary.md (≤2500 tok) + AGENTS.md (≤1500 tok)
    → brain_agent.append_developer_instructions(...)
    → injected into Realtime developer instructions (one shot, never refreshed)

LLM 在 turn 内主动召回
  → recall_grep(pattern, scope) → 调用本机 rg 二进制,返回行+行号(≤ 50 行)
  → recall_read(path) → 沙箱化路径读取(≤ 4 KB)
  → recall_glob(pattern) → 列出匹配文件
  → LLM 按 AGENTS.md 教的 4-6 步顺序自主迭代,毫秒级
```

**深思流(LLM 主动求慢脑)**:
```
LLM tool: ask_slow_brain(query, timeout_s=20)
  → SkillServer 转 memory.daemon.ask_slow_brain
  → 向 codex mcp-server 子进程发 MCP tools/call
  → daemon 累积流式响应,直到 final assistant text 或 timeout/cancel
  → barge-in 时 SkillServer.on_response_canceled 触发 cancel_event
    → daemon 发 MCP notifications/cancelled
  → 返回 {status, text, latency_ms, partial}
```

---

## 2. 关键架构决定(已锁定)

| 决定 | 选项 | 锁定理由 |
|---|---|---|
| Codex 在 G1 的定位 | **并存:Codex 在 BrainRealtimeAgent 上方** | 快脑 voice 实时性不可破坏;慢脑负责长期记忆+深度推理 |
| Memory 内容范围 | **体验型**(对话+tool+scene_snapshot+action_result+safety_event) | 仅对话 transcript 无法让机器人"召回看过的、做过的" |
| Codex 节奏 | **常驻 daemon**,与快脑同周期启动 | Phase 任务后台跑,ask_slow_brain 走 MCP 持久连接,不重复冷启动 |
| 本期 spec 范围 | **memory + ask_slow_brain 基本形态(中型)** | planning/MCP/multi-agent 等留给后续 spec |
| LLM 引擎 | **统一走 Codex 订阅**,不调 OpenAI SDK | 订阅额度覆盖,不刷 API 账单;三种用法(`codex exec` x2 + `codex mcp-server` x1) |
| 数据根目录 | **`~/.unitree/g1_brain/`** 机器人独立 | 与个人 `~/.codex/` 完全隔离,清数据/换 robot_id 一行命令 |
| 文件布局 | **照搬 Codex** (memories/{MEMORY,memory_summary,raw_memories}.md + rollout_summaries/) | 复刻成熟设计;以后看 codex-rs 测试可直接对照 |
| JSONL schema 扩展 | **meta subtype**(不引入新 top-level type) | 保持 Claude-harness 兼容,现有 6 type 不动 |
| FTS5 | **不上** | grep markdown 毫秒级足够;FTS5 留作未来 spec |
| Codex IPC 协议 | **MCP over stdio**(`codex mcp-server`)| OpenAI 官方稳定接口,自带 cancel/progress/tool listing |
| Phase2 触发节奏 | **仅 Phase1 done 后评估,无周期 tick** | idle 时不跑,节省订阅 quota |
| `CODEX_HOME` 隔离 | **指向 robot_root/.codex_runtime** | daemon 的 rollout 不污染 ~/.codex/sessions/ |
| 慢脑 sandbox | **read-only** | 慢脑不应写文件;Phase2 整合走 Python atomic_write,不经 daemon |
| ask 并发 | **mutex + queue_max=2,超出立即 queue_full** | 不让 LLM 等几十秒;直接 fallback recall_grep |
| 召回模型化 | **LLM 自己用 rg/Read/Glob 搜**,不在 Python 端预过滤 | Codex / CC 共同范式;两份笔记一致结论 |
| LSP | **不接** | LSP 是给源代码符号用的,memory 是 .md + .jsonl,LSP 无意义 |
| 历史 JSONL 回填 | **不回填,只对启用后的 session 生效** | pre-memory 噪音太多 |
| Memory enable marker | **MEMORY.md 首行 `# Memory enabled at <ISO>`** | 时间锚,以后翻 memory 知道这之前的 session 没记 |
| 三脑模式隔离 | **Phase1/2 用 `codex exec --ephemeral`,daemon 用 `codex mcp-server`** | 无状态批处理 vs 有状态深思,各取所需,不跨污染 |
| `forget(turn)` tool | **本期不做,留 TODO + AGENTS.md 提示** | 渐进;先解决 80% 用例 |
| PII redaction | **全交 Phase1 prompt 兜底** | Codex 原版做法;Python 正则黑名单复杂且误伤 |
| `enabled` 默认 | **true** | 用户明确选择 |
| Mock 边界 | **只 mock codex subprocess** | SQLite/git/rg/文件系统全真跑,CI 速度可接受 |
| 测试覆盖 | **故障矩阵每行一个 test**,不追 100% | 关注关键路径而非覆盖率指标 |

---

## 3. 数据模型

### 3.1 文件树(robot-scoped)

```
~/.unitree/g1_brain/                   <- $UNITREE_G1_HOME (env, defaults here)
├── memories/
│   ├── AGENTS.md                      <- 人手写规则 + read_path 指引(下文 4.2)
│   ├── MEMORY.md                      <- ≤25KB 顶层索引,Phase2 输出
│   ├── memory_summary.md              <- ≤8KB session_start 注入源
│   ├── raw_memories.md                <- 所有 stage1.raw_memory 合并,Phase2 输入
│   ├── rollout_summaries/
│   │   └── {session_id}-{ts}-{slug}.md  <- 每个 session 一份摘要
│   ├── .git/                          <- baseline,Phase2 用 git diff 判定是否需要整合
│   └── .gitignore                     <- 忽略 .tmp_* 等过渡文件
├── state.sqlite                       <- 状态控制面(WAL 模式)
└── .codex_runtime/                    <- CODEX_HOME,daemon 的 rollout/auth/state
```

现有 `g1_brain/logs/conversations/*.jsonl` **不动**——那是源数据,memory 从那里只读。

### 3.2 SQLite schema(`state.sqlite`)

```sql
CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY);
INSERT INTO schema_version(version) VALUES (1);

-- 一个 agent session 一行
CREATE TABLE sessions (
    id             TEXT PRIMARY KEY,             -- ConversationLogger.session_id (32-hex)
    rollout_path   TEXT NOT NULL UNIQUE,         -- absolute path to JSONL
    started_at     INTEGER NOT NULL,             -- epoch ms
    ended_at       INTEGER,                      -- NULL until session close
    robot_id       TEXT NOT NULL DEFAULT 'g1',
    git_sha        TEXT,                         -- g1_brain repo HEAD at session start
    mjcf_path      TEXT,
    config_hash    TEXT                          -- sha256 of effective g1_brain.yaml
);

-- Phase1 输出
CREATE TABLE stage1_outputs (
    session_id        TEXT PRIMARY KEY,
    source_updated_at INTEGER NOT NULL,           -- JSONL last-modified epoch ms
    raw_memory        TEXT NOT NULL,
    rollout_summary   TEXT NOT NULL,
    rollout_slug      TEXT,
    generated_at      INTEGER NOT NULL,
    usage_count       INTEGER NOT NULL DEFAULT 0,
    last_usage        INTEGER,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX idx_stage1_source_updated
    ON stage1_outputs(source_updated_at DESC, session_id DESC);

-- 协同 jobs 队列
CREATE TABLE jobs (
    kind                    TEXT NOT NULL,        -- 'phase1' | 'phase2' | 'phase2_global_lock'
    job_key                 TEXT NOT NULL,        -- session_id | 'global'
    status                  TEXT NOT NULL,        -- 'pending' | 'leased' | 'done' | 'failed'
    worker_id               TEXT,
    ownership_token         TEXT,
    started_at              INTEGER,
    finished_at             INTEGER,
    lease_until             INTEGER,
    retry_at                INTEGER,
    retry_remaining         INTEGER NOT NULL,
    last_error              TEXT,
    input_watermark         INTEGER,
    last_success_watermark  INTEGER,
    PRIMARY KEY (kind, job_key)
);
CREATE INDEX idx_jobs_kind_status_retry_lease
    ON jobs(kind, status, retry_at, lease_until);
```

WAL 模式:`PRAGMA journal_mode=WAL;` 启动时执行。

### 3.3 JSONL event schema 扩展(meta subtype)

现有 6 个 top-level type 不动(user / assistant / tool_use / tool_result / system / meta)。现有 meta subtype(session_start / turn_start / state_transition / plan_done / error / shutdown)不动。

#### (a) `meta.scene_snapshot`(关键帧场景快照)
**触发时机**:turn_start(IDLE→CAPTURING)、pre_motion(每次 motion-tool 执行前)、post_motion(执行后)。本期**不**做 delta trigger。

```json
{
  "ts_ms": 1715000000000,
  "trigger": "turn_start | pre_motion | post_motion",
  "persons_visible": 1,
  "user_pose": "standing | sitting | unknown",
  "user_gesture": "wave | point | null",
  "nearest_person_m": 1.3,
  "nearest_obstacle_m": 0.8,
  "ground_constraint": "flat | ramp | stairs | unsafe",
  "warnings": ["close_obstacle"],
  "detections_summary": {
    "head_cam": {"person": 1, "chair": 2},
    "usb_cam": {"person": 1}
  },
  "frame_ref": null
}
```

`frame_ref` 本期固定 `null`(占位,留给未来多模态 Phase1)。

#### (b) `meta.action_result`(动作执行物理结果)
**触发时机**:`SkillServer.execute()` 返回后(包括 motion + no-motion)。

```json
{
  "ts_ms": 1715000000800,
  "tool_use_id": "call_af9N...",
  "tool_name": "walk",
  "args": {"vx": 0.3, "duration": 2.0},
  "status": "ok | blocked_by_safety | exec_error | canceled",
  "blocked_reason": "scene_check_walk:obstacle_too_close | null",
  "outcome_metrics": {
    "displacement_m": 0.58,        // sim 真值;real 模式本期填 null
    "duration_actual_s": 2.05,
    "end_pose_z": 0.71,
    "end_safety_state": "STANDING"
  },
  "result_payload_brief": "{walked 0.58m forward}"   // ≤ 256 字节
}
```

#### (c) `meta.safety_event`(安全决策与状态变迁)
**触发时机**:SafetySupervisor 拒绝 tool / FSM 状态变迁 / vision_risk_gate 判 RISK / E-stop。

```json
{
  "ts_ms": 1715000000900,
  "kind": "tool_rejected | fsm_transition | vision_gate_risk | estop",
  "rule": "scene_check_walk | pose_check_upright | watchdog_lowstate | null",
  "from_state": "STANDING | null",
  "to_state": "EMERGENCY_STOP | null",
  "details": "gravity-projected z=0.42 below 0.6 threshold",
  "associated_tool_use_id": "call_af9N... | null"
}
```

#### ConversationLogger API 新增(3 个公共方法)

```python
def log_scene_snapshot(self, *, trigger, scene_state, frame_paths=None) -> None
def log_action_result(self, *, tool_use_id, tool_name, args, status,
                      blocked_reason=None, outcome_metrics=None,
                      result_payload_brief="") -> None
def log_safety_event(self, *, kind, rule=None, from_state=None,
                     to_state=None, details="",
                     associated_tool_use_id=None) -> None
```

内部走现有 `_emit_meta(subtype, data)` 通道。

---

## 4. Phase1 / Phase2 写路径

### 4.1 LLM 引擎:统一走 Codex 订阅

| 用途 | 进程模型 | 上下文 | 命令 |
|---|---|---|---|
| Phase1 提取(单 session) | `codex exec --json` 一次性 | 每次全新 | `codex exec --json --ephemeral --output-schema phase1_schema.json --cd <robot>/memories -s read-only --skip-git-repo-check --ignore-user-config` |
| Phase2 整合(全局) | `codex exec --json` 一次性 | 每次全新 | 同上 + `--output-schema phase2_schema.json` |
| ask_slow_brain | `codex mcp-server` 持久 daemon | 长会话 | 见 § 6 |

`CODEX_HOME=<robot>/.codex_runtime` 全局生效。

### 4.2 Phase1:每个 session 独立处理

**触发**:
- `plan_done` 入队,debounce 30 秒
- session 关闭(`ConversationLogger.close()`)前强制入队 `force=True`
- `MemorySubsystem.start()` 时扫描 sessions 表 stage1_outputs 缺失/过期者入队

**JSONL projection**(80 KB 上限,超出丢最早 turn):

```
# Session metadata
session_id: ec8b23fb904645a7b6800788ee42e0b4
started_at: 2026-05-07T13:13:45Z
ended_at:   2026-05-07T13:21:08Z
robot_id:   g1
mode:       sim

# Events (chronological)
[t-0001] user: "嘿 sparky 走两步看看"
[t-0001] tool_use[walk]: vx=0.3 duration=2.0
[t-0001] scene[pre_motion]: persons=1, nearest_obstacle=1.4m, ground=flat
[t-0001] action_result: ok, displacement=0.58m, end_state=STANDING
[t-0001] scene[post_motion]: persons=1, nearest_obstacle=0.8m
[t-0001] tool_result[walk]: {"displacement_m": 0.58}
[t-0001] assistant: "走了大概半米。"
[t-0001] plan_done
...
```

**system prompt 关键段**:

```
You extract durable memory from one G1 robot session.

Output JSON exactly:
{
  "raw_memory": "<3-15 bullets, dense, 1st-person from robot. Include: \
                 what user asked; durable scene facts; actions that \
                 succeeded/failed and why; user corrections; learned \
                 places/objects/people.>",
  "rollout_summary": "<2-4 sentences for human skim>",
  "rollout_slug": "<short kebab-case>"
}

Rules:
- DROP small talk and acknowledgements ("ok", "yes", "thank you").
- KEEP scene facts only if durable ("the red cup is on the kitchen table" \
  yes; "1 person visible at 13:15" no).
- KEEP every safety rejection with rule name.
- KEEP every action_result.status != ok with reason.
- NO speculation: if JSONL doesn't say it, don't write it.

SECRET / PII RULES (robotic context):
- DROP user-spoken passwords, WiFi keys, credit card numbers.
- For names: keep first names only ("Alice"); drop last names.
- For addresses: drop street numbers/postcodes; keep generic place names
  ("kitchen", "Alice's apartment").
- DROP raw image paths and frame_ref entries.
- DROP API keys, tokens, env values.

No-op allowed: if no durable value exists, return empty strings.
```

**重试**:JSON parse 失败 retry 1 次(stricter re-prompt);第二次仍失败 → `raw_memory=""` upsert,job status=failed,Phase2 跳过。

**并发**:单 asyncio worker,SQLite RETURNING claim 原子化,lease=60s,heartbeat 20s。

### 4.3 Phase2:全局整合(仅 Phase1 done 后评估,无周期 tick)

**步骤**:
1. claim `(kind='phase2_global_lock', job_key='global')`,lease 3600s,heartbeat 30s
2. `sync_phase2_inputs(db, mem_root)`:从 stage1_outputs 拉 top-N(LRU 排序,`usage_count` + `last_usage`)
3. 写 `raw_memories.md`(确定性顺序,稳定 git diff)+ `rollout_summaries/{session}-{ts}-{slug}.md`
4. `git status --porcelain` 看 dirty
5. 空 → 结束,release lock
6. 非空 → 调 `codex exec --json --output-schema phase2_schema.json`,prompt 含 raw_memories.md / 当前 MEMORY.md / `phase2_workspace_diff.md`(git diff 文本)
7. 解析 `{memory_md, memory_summary_md}`,atomic_write
8. `git commit -m "phase2 consolidation @ <ts>"`,release lock

**整合 system prompt 强约束**:
- MEMORY.md ≤ 200 行 ≤ 25 KB(超出截断最老内容)
- memory_summary.md ≤ 80 行 ≤ 8 KB(注入用,token 预算硬上限)
- 每条 claim 必须可追溯到 raw_memories 某一条
- 分类章节固定:## People / ## Places / ## Skills learned / ## Safety lessons / ## User preferences
- "DO NOT use any tools; output only the JSON object"

### 4.4 启用时机与历史 session(已锁定)

- `memory.enabled: true` + 第一次 `agent_main` 启动:
  - 建 SQLite,migrations 跑到 v1
  - 初始化 `~/.unitree/g1_brain/memories/` + `git init` + 空 baseline commit
  - 写 marker:`MEMORY.md` 首行 `# Memory enabled at <ISO timestamp>`
  - **不扫描** `logs/conversations/` 历史 JSONL(全部视为 pre-memory 噪音)
- 此后每次启动:新 session 一启动就 INSERT 一行,plan_done 触发 Phase1

### 4.5 资源估算

| 任务 | 默认模型 | 频率 | 单次成本 |
|---|---|---|---|
| Phase1 | Codex 订阅默认(gpt-5) | 每 turn,30s debounce | prompt ≤ 30 KB,output ≤ 2 KB |
| Phase2 | 同上 | Phase1 done 后(仅 dirty 时跑) | prompt ≤ 50 KB,output ≤ 10 KB |
| ask_slow_brain | 同上 | LLM 主动调,稀少 | 流式,默认 20s timeout |

订阅 quota 用尽检测:解析 stderr / MCP error 关键字 → Phase1/Phase2 job retry_at=+1h;daemon 标 quota_exhausted 30 min;ask_slow_brain 返回 `{"status":"quota_exhausted"}`。

---

## 5. 召回双路(LLM 自主驱动)

### 5.1 范式锚点

```
Codex / CC 共同范式:
  LLM 看 memory_summary.md (已注入)
   ↓
  LLM 自己提关键词
   ↓
  LLM 调 grep tool(本机 rg)
   ↓
  LLM 看返回行 + 行号
   ↓
  LLM 调 read tool 开特定文件
   ↓
  LLM 必要时 grep_rollout JSONL
   ↓
  LLM 自己停在 4-6 步内
```

**Python 端不替 LLM 决定相关性**。只铺好文件 + 暴露原始工具 + 在 AGENTS.md 给指引。

### 5.2 路径 A:被动注入(session_start 一次性)

**触发点**:`agent_main._run()` 在 `brain_agent` 实例化后、`await brain_agent.run()` 之前调用。

```python
ctx = memory_subsystem.build_passive_context()
if ctx:
    brain_agent.append_developer_instructions(ctx)
```

**`build_passive_context()` 内部**:
```python
def build_passive_context() -> str:
    parts = []
    if (mem_root / "AGENTS.md").exists():
        parts.append("## Project rules (AGENTS.md)\n"
                     + read_truncated("AGENTS.md", 1500))
    if (mem_root / "memory_summary.md").exists():
        parts.append("## Long-term memory (from prior sessions)\n"
                     + read_truncated("memory_summary.md", 2500))
    if not parts:
        return ""
    return (
        "\n\n# Robot long-term context\n"
        "The following is curated memory from prior sessions. Treat as "
        "background knowledge. When you need detail beyond this summary, "
        "call the recall_grep / recall_read / recall_glob tools.\n\n"
        + "\n\n".join(parts)
    )
```

token 估算用 tiktoken `cl100k_base`,留 10% 安全 margin。失败兜底:返回 ""(never block fast brain)。

### 5.3 路径 B:主动召回(LLM 工具调用)

#### `recall_grep`
```python
{
  "name": "recall_grep",
  "description": "Run ripgrep over memory files. Returns matching lines "
                 "with file path and line number. Use this as primary recall.",
  "parameters": {
    "pattern": "string (regex)",
    "scope": "registry | rollouts | jsonl | all",
    "session_id": "string (required for scope=jsonl)",
    "max_lines": "int default 50 max 100"
  }
}
```

实现:直接调本机 `rg`(已装 14.1.0)。fallback 链:`rg` → `grep -rn` → Python `re`。

#### `recall_read`
```python
{
  "name": "recall_read",
  "description": "Read a memory file. Use after recall_grep finds a hit.",
  "parameters": {
    "path": "string (relative to memories/ or logs/conversations/)",
    "start_line": "int default 1",
    "end_line": "int optional"
  }
}
```

实现:沙箱化路径解析(见 § 8.3),≤ 4 KB 返回。

#### `recall_glob`
```python
{
  "name": "recall_glob",
  "description": "List memory files matching glob pattern.",
  "parameters": {
    "pattern": "string",
    "limit": "int default 50 max 200"
  }
}
```

### 5.4 慢脑的召回(零代码)

`codex mcp-server` 启动时 `--cd ~/.unitree/g1_brain/memories`,cwd 锁定。Codex 内置 Grep/Read/Glob/Bash 全部可用(在 sandbox=read-only 下)。它会读 cwd 下的 AGENTS.md,然后按 read_path 指引召回——**完全是 Codex 原生行为,我们零行代码**。

### 5.5 AGENTS.md(两脑共享的 read_path 指引)

```markdown
# G1 robot memory — read path

## Memory layout
- `memory_summary.md`  ← already injected; treat as background.
- `MEMORY.md`          ← primary searchable registry. Grep this first.
- `rollout_summaries/` ← per-session narratives. Open 1-2 most relevant.
- `raw_memories.md`    ← dense per-session dump. Use as fallback.
- `rollout_path` JSONL ← original transcripts at logs/conversations/*.jsonl.
                         Only grep this if you need exact text/numbers/args.

## Recall sequence (≤6 steps; stop early if no hits)
1. Skim memory_summary.md (already in context).
2. Extract 1-3 task-relevant keywords.
3. recall_grep(pattern, scope="registry") on MEMORY.md + raw_memories.md.
4. If hit, recall_read the file shown.
5. If you need exact evidence, recall_grep(scope="rollouts" or "jsonl").
6. Last resort: scope="jsonl" with session_id from a rollout_summary.

## Stop conditions
- No hits in MEMORY.md AND question isn't about prior context → stop.
- 4-6 search steps and nothing → stop, tell user you don't recall.

## Robot-specific rules
- "上次/last time/do you remember" → recall trigger.
- Scene fields are durable only if they survive multiple sessions
  ("red cup on table" yes; "1 person at 13:15" no).
- action_result.status != ok always surfaces in memory_summary lessons.

## What memory does NOT contain
- Current scene state — use describe_scene / query_scene_state tools.
- Current battery / pose — use query_scene_state.
- Project code — Codex has its own tools for that.

## TODO (not yet implemented)
- `forget(session_id, turn_id)` — say "forget this" verbally, the brain
  will tag turn for redaction at next Phase2.
```

---

## 6. ask_slow_brain IPC(Codex daemon)

### 6.1 协议选型:MCP over stdio

Codex 自带 `codex mcp-server` 子命令:作为 stdio JSON-RPC 2.0 MCP 服务器对外暴露能力。OpenAI 官方稳定接口。

```
g1_brain (Python)                   codex (Rust subprocess)
─────────────────                   ──────────────────────
memory/daemon.py:CodexDaemon  ────► codex mcp-server
  - MCP client (stdio)              - stdio JSON-RPC server
  - asyncio mutex                   - --cd <robot>/memories
  - 30s idle ping                   - --sandbox read-only
  - crash → exponential restart     - --skip-git-repo-check
                                    - --ignore-user-config
                                    - approval_policy=never
                                    - CODEX_HOME=<robot>/.codex_runtime
```

### 6.2 daemon 生命周期

**start**:
1. spawn subprocess with above flags
2. wait `initialize` MCP response(timeout 10s)
3. call `tools/list`,缓存返回的 tool 名(确认 codex 暴露的主 tool)
4. state = READY
5. spawn ping task(每 30s,timeout 2s):失败 → 标 stale + restart
6. spawn stderr-drainer 防 pipe 阻塞

**shutdown**:
1. cancel any in-flight ask via MCP cancellation
2. send `shutdown` notification
3. SIGTERM,grace 3s
4. SIGKILL if still alive
5. drain pipes

**crash 恢复**:
- EOF → state=CRASHED
- 重启退避:1s / 5s / 30s / 60s / 300s 上限
- 连续 5 次失败 → state=DEAD,后续 ask 返回 daemon_dead

### 6.3 ask_slow_brain 接口

```python
async def ask_slow_brain(
    query: str,
    *,
    timeout_s: float = 20.0,
    cancel_event: Optional[asyncio.Event] = None,
) -> AskResult:
    """
    AskResult.status: 'ok' | 'timeout' | 'canceled' | 'daemon_dead'
                    | 'queue_full' | 'quota_exhausted' | 'protocol_error'
    """
```

**并发**:asyncio mutex 保证一次一个 ask;queue_max=2(包括 in-flight),第 3 个立即 queue_full。

**Cancel 链**:
```
快脑 LLM tool_use: ask_slow_brain(...)
  → SkillServer._skill_ask_slow_brain
  → cancel_event = asyncio.Event(); track by call_id
  → memory.daemon.ask_slow_brain(query, cancel_event=cancel_event)
  ↓
[barge-in 用户唤醒]
  → BrainRealtimeAgent.on_response_canceled(response_id) fires
  → SkillServer.on_response_canceled: set all pending cancel_events
  ↓
daemon 检测 cancel_event.is_set()
  → MCP notifications/cancelled with request_id
  → Codex 中断 LLM,停止计费
  → 返回 AskResult("canceled", partial=<accumulated>, ...)
```

### 6.4 ask_slow_brain tool schema

```python
{
  "type": "function",
  "name": "ask_slow_brain",
  "description": (
    "Consult the slow deliberative brain (Codex) for queries that need "
    "multi-step reasoning, planning, or deep historical recall. "
    "SLOW: 5-20 seconds. Use sparingly. Cases: "
    "(1) user asks for multi-step planning; "
    "(2) recall fails and you suspect rare historical fact; "
    "(3) non-obvious safety implication needs deep think. "
    "NEVER use for reflex/motion decisions."
  ),
  "parameters": {
    "query": "string (specific, self-contained)",
    "timeout_s": "number 3-60, default 20"
  }
}
```

---

## 7. 接入面(改 4 个文件 + 4 个单行接线)

### 7.1 改动文件汇总

| 文件 | 改动 | 行数 |
|---|---|---|
| `apps/agent_main.py` | 3 处插入(实例化 / 注入 context / shutdown step) | ~15 |
| `brain/conversation_logger.py` | 加 3 个公共方法 | ~80 |
| `skills/skill_server.py` | 加 memory kwarg / 4 个新 `_skill_*` / execute() 末尾 action_result / on_response_canceled | ~150 |
| `configs/g1_brain.yaml` | 加 `memory:` 节 | ~15 |
| **新增** `g1_brain/memory/` | 整个新包 | ~2000 |
| **新增** `g1_brain/tools/reset_memory.py` | CLI 工具 | ~80 |

### 7.2 单行接线点

| 文件 | 接线 |
|---|---|
| `brain/conversation_state.py` | `IDLE→CAPTURING` 时调 `conv_logger.log_scene_snapshot(trigger="turn_start", scene_state=scene_bus.snapshot())` |
| `safety/state_machine.py` | `RobotFsm.transition_to` 末尾调 `conv_logger.log_safety_event(kind="fsm_transition", ...)` |
| `safety/vision_risk_gate.py` | 判 RISK 后调 `conv_logger.log_safety_event(kind="vision_gate_risk", ...)` |
| `safety/estop_listener.py` | E-stop 触发处调 `conv_logger.log_safety_event(kind="estop", ...)` |

### 7.3 `apps/agent_main.py` 改动伪 diff

```python
# 已有                                            │ 新增
# ────────────                                    │ ────────────
# conv_logger = ConversationLogger(...)           │  (no change)
# conv_logger.log_session_start(...)              │  (no change)
                                                  │
                                                  │  memory_subsystem = None
                                                  │  if cfg.get("memory", {}).get("enabled", True):
                                                  │      from ..memory import MemorySubsystem
                                                  │      memory_subsystem = MemorySubsystem(
                                                  │          robot_root=Path(cfg["memory"]["root_dir"]).expanduser(),
                                                  │          rollout_path=conv_logger.path,
                                                  │          session_id=conv_logger.session_id,
                                                  │          cfg=cfg["memory"],
                                                  │      )
                                                  │      await memory_subsystem.start()
                                                  │
# skill_server = _try_build_skill_server(...)     │  +memory=memory_subsystem)
# brain_agent = _try_build_brain_agent(...)       │  (no change)
                                                  │
                                                  │  if memory_subsystem is not None and brain_agent is not None:
                                                  │      ctx = memory_subsystem.build_passive_context()
                                                  │      if ctx:
                                                  │          brain_agent.append_developer_instructions(ctx)
                                                  │
# sm = _build_state_machine(...)                  │  (no change)
# await brain_agent.run()                         │  (no change)
                                                  │
# ─── shutdown 段 ───                              │
# _shutdown_step("sm.stop", sm.stop, 3.0)         │  (existing)
# _shutdown_step("brain_agent.stop", ..., 3.0)    │  (existing)
                                                  │  + _shutdown_step("memory.stop", memory_subsystem.stop, 5.0)
# _shutdown_step("conv_logger.close", ..., 1.0)   │  (existing)
```

### 7.4 配置(`configs/g1_brain.yaml`)

```yaml
memory:
  enabled: true
  root_dir: "~/.unitree/g1_brain"

  # Phase1/Phase2(走 codex exec)
  phase1_model: ""                           # 空 = 用 Codex 订阅默认
  phase2_model: ""
  phase1_debounce_s: 30
  phase1_max_jsonl_bytes: 80000
  phase2_max_raw_memories: 256
  phase2_max_unused_days: 30

  # ask_slow_brain daemon
  slow_brain_model: ""                       # 空 = 用订阅默认
  ask_default_timeout_s: 20
  ask_queue_max: 2
  daemon_ping_interval_s: 30
  daemon_restart_max_attempts: 5

  # Recall budgets
  passive_summary_max_tokens: 2500
  passive_agents_md_max_tokens: 1500
  recall_grep_default_max_lines: 50
  recall_read_max_bytes: 4096
```

---

## 8. 错误处理与安全

### 8.1 核心不变量

1. Memory 失败 → 快脑必须照常跑(motion path 不受影响)
2. 不能漏写 JSONL(那是源数据)
3. recall_* 路径必须沙箱化
4. Codex daemon crash 不能引起 g1_brain 进程 crash
5. SQLite WAL 允许并发读 + 串行写
6. 安全决策(FSM/E-stop)不能被日志写入阻塞

### 8.2 故障矩阵摘要

| 层 | 故障 | 行为 | 给快脑的可见性 |
|---|---|---|---|
| MemorySubsystem.start | DB/目录失败 | memory_subsystem=None,整体禁用 | tool 返回 `memory_disabled` |
| SQLite 损坏 | DatabaseError | 备份到 .broken,重建 schema | 同上 |
| Phase1 LLM JSON parse fail | retry 1 次 → 失败 | upsert `raw_memory=""` | 透明 |
| Phase2 sub-LLM hang | timeout 600s | SIGTERM,retry_at=+30min | 透明 |
| CodexDaemon 启动失败 | initialize 超时 | 5 次重启退避 | ask 返回 daemon_dead |
| Daemon 中途 crash | EOF | partial 返回 + 重启 | LLM 看到 partial |
| 订阅 quota 用尽 | stderr 关键字 | Phase 暂停 30min;daemon 标 quota_exhausted 30min | ask 返回 quota_exhausted |
| recall_grep 路径越界 | sandbox check | reject | tool_result `path_outside_sandbox` |

### 8.3 路径沙箱

```python
ALLOWED_ROOTS = [
    robot_root / "memories",
    g1_brain_repo / "logs" / "conversations",
]

def _resolve_safe_path(rel: str) -> Path:
    if Path(rel).is_absolute():
        raise PathSandboxError(f"absolute path forbidden: {rel}")
    for root in ALLOWED_ROOTS:
        candidate = (root / rel).resolve(strict=False)
        try:
            candidate.relative_to(root.resolve())
            if candidate.exists():
                return candidate
        except ValueError:
            continue
    raise PathSandboxError(f"not in allowed roots: {rel}")
```

`scope` 参数是枚举,硬映射到 ALLOWED_ROOTS 子集,**LLM 永不能写自定义 base**。

### 8.4 PII redaction

完全交给 Phase1 prompt(见 § 4.2 SECRET/PII RULES)。Python 端无正则黑名单。

### 8.5 资源上限

| 资源 | 默认上限 | 越界 |
|---|---|---|
| JSONL 单文件 | 50 MB(现有 ConversationLogger 限) | 现有轮转 |
| rollout_summaries 数 | 200 | Phase2 LRU 驱逐 |
| MEMORY.md | 25 KB / 200 行 | Phase2 prompt 强约束 |
| memory_summary.md | 8 KB / 80 行 | 同上 |
| state.sqlite | 100 MB 警告 | log warning,不自动清理 |

### 8.6 损坏恢复(`tools/reset_memory.py` CLI)

提供:
- `reset_memory --rebuild-state` 重建 state.sqlite,JSONL 保留
- `reset_memory --rebuild-git` 重建 memories/.git
- `reset_memory --reset-md` 删 MEMORY.md / memory_summary.md / rollout_summaries
- `reset_memory --nuke` 整个 `~/.unitree/g1_brain/` 删除(双 `--confirm`)

---

## 9. 测试策略

### 9.1 金字塔

- **Unit**(60-80 个,per module):storage / jobs / phase1 / phase2 / recall / daemon / codex_client / context / conversation_logger 扩展 / skill_server 扩展 / tool_schemas
- **Integration**(8-12 个):memory_pipeline_e2e / recall_with_pipeline / ask_slow_brain_cancel / failure_modes
- **E2E**(1-2 个,扩 test_vertical_slice):session_start 注入 / motion turn 后多条新 meta

### 9.2 Mock 边界

| 组件 | Mock? | 替代 |
|---|---|---|
| `codex exec --json` | ✓ | MockCodexExecRunner,prompt→预设响应 |
| `codex mcp-server` | ✓ | MockMcpServer,实现 initialize/tools/list/tools/call |
| Realtime API | 已有 mock | 现有 |
| SQLite | 不 mock | tmp_path |
| 文件系统 | 不 mock | tmp_path |
| `rg` binary | 不 mock | 系统 rg 14.1.0 |
| `git` | 不 mock | tmp git repo |

### 9.3 测试数据 fixtures

`tests/fixtures/memory/`:
- `sample_jsonl/`:4 类(turn_start-only / motion-success / motion-blocked / safety_event-heavy)
- `expected_phase1_outputs/`:snapshot 对照
- `expected_memory_md/`:Phase2 整合后预期
- `mock_codex_responses.json`:`{prompt_hash: response}` 字典

snapshot 用 `pytest-snapshot` 库(本期引入)。

### 9.4 CI 矩阵

| job | 跑哪些 |
|---|---|
| `pytest -m "not bench and not manual"` | 默认全部 |
| `pytest -m bench` | 性能回归 PR 才跑 |
| `tests/manual/` | release 前手动,需真 codex |

---

## 10. 实现顺序(spec → plan → code)

1. ✅ Design freeze(本文档)
2. → `docs/superpowers/specs/2026-05-21-g1-memory-harness-design.md`(brainstorming skill 出 spec)
3. → `writing-plans` skill 出实现计划
4. → 实现:
   - storage + jobs(纯 SQLite,无网络)
   - codex_client + daemon(可 mock)
   - phase1 + phase2(依赖前两个)
   - recall + context(独立)
   - ConversationLogger 扩展
   - SkillServer 扩展
   - agent_main 接入 + 4 单行接线 + YAML 配置
   - reset_memory CLI
   - Integration / e2e tests
5. → `pytest -m "not bench and not manual"` 全绿才算结

---

## 附录 A:数据流时序图

### A.1 一个完整 turn 的事件流

```
T0  user 说 "走两步"
     ConversationLogger.begin_turn() → meta.turn_start (uuid_a)
     conv_logger.log_scene_snapshot(trigger=turn_start, ...) (uuid_b, parent=uuid_a)
T1  Realtime ASR finalize → log_user_transcript("走两步") (uuid_c)
T2  Realtime emits tool_use: walk(vx=0.3,dur=2.0) → log_tool_use (uuid_d)
T3  SkillServer.execute("walk", ...)
     SafetySupervisor.gate → ok
     log_scene_snapshot(trigger=pre_motion, ...) (uuid_e)
     combo_proxy.walk → 实际控制
     RobotFsm: STANDING → ACTING → STANDING
       transition_to() → log_safety_event(kind=fsm_transition, ...) (uuid_f, x2)
     log_scene_snapshot(trigger=post_motion, ...) (uuid_g)
     log_action_result(status=ok, displacement=0.58, ...) (uuid_h)
T4  Realtime emits assistant: "好的" → log_assistant_transcript (uuid_i)
T5  Realtime emits tool_result: walk done → log_tool_result (uuid_j)
T6  plan_done → meta.plan_done (uuid_k)
     memory.on_plan_done() → jobs.enqueue("phase1", session_id, debounce_until=T6+30s)
```

### A.2 Phase1/Phase2 后台流

```
T6+30  Phase1 worker tick
        claim_lease("phase1", session_id)
        build_projection from JSONL[0:size]
        codex exec --json (prompt + projection) → {raw_memory, summary, slug}
        UPSERT stage1_outputs
        complete_job
        trigger Phase2 evaluator

T6+45  Phase2 worker tick
        try_claim_global_lock
        sync_phase2_inputs → write raw_memories.md + rollout_summaries/
        git status → dirty? 
          → yes: codex exec (consolidation prompt) → {memory_md, summary_md}
                 atomic_write MEMORY.md + memory_summary.md
                 git commit
          → no: skip
        release_lock

T_next  Next session_start
        memory.build_passive_context()
          → read memory_summary.md (≤ 2500 tok) + AGENTS.md (≤ 1500 tok)
          → brain_agent.append_developer_instructions(...)
```

### A.3 ask_slow_brain + barge-in 时序

```
T0  LLM tool_use: ask_slow_brain(query="规划下今天怎么帮我做家务")
T1  SkillServer._skill_ask_slow_brain
      cancel_event = asyncio.Event()
      register(call_id → cancel_event)
      task = daemon.ask_slow_brain(query, cancel_event=cancel_event, timeout=20)
T2  daemon: acquire mutex (queue check: 0 in flight, ok)
T3  daemon: write MCP tools/call {id: r1, method: tools/call, ...}
T4  codex 开始流式 progress notifications → daemon 累积 partial_text
T5  用户突然说 "等下,先帮我看下窗外"  ← barge-in
T6  BrainRealtimeAgent: on_response_canceled(resp_42) 触发
T7  SkillServer.on_response_canceled: 遍历 cancel_tokens,对应 set()
T8  daemon: cancel_event.is_set() 检测到
      write MCP notifications/cancelled {requestId: r1}
T9  codex 中断 LLM 调用,关闭流
T10 daemon: 返回 AskResult("canceled", partial=<accumulated>, ...)
T11 SkillServer 返回 tool_result {status:"canceled", partial:"..."}
T12 LLM 自己决定:"那我放弃这个规划,先 describe_scene"
```

---

## 附录 B:文件清单

### 新增

```
g1_brain/g1_brain/memory/
├── __init__.py              # MemorySubsystem 门面
├── storage.py               # SQLite + 文件树读写
├── jobs.py                  # claim/lease/retry
├── phase1.py                # Phase1 worker + prompt
├── phase2.py                # Phase2 worker + sync + consolidation
├── recall.py                # grep/read/glob + sandbox
├── context.py               # build_passive_context
├── codex_client.py          # codex exec wrapper
├── daemon.py                # CodexDaemon (MCP client)
├── schemas.py               # 事件 schema + AskResult dataclass
└── prompts/
    ├── phase1_system.md     # Phase1 system prompt 模板
    ├── phase2_system.md     # Phase2 consolidation prompt 模板
    └── default_agents_md.md # AGENTS.md 初始模板(reset 时复制)

g1_brain/g1_brain/tools/
└── reset_memory.py          # reset CLI

g1_brain/tests/
├── test_memory_storage.py
├── test_memory_jobs.py
├── test_memory_codex_client.py
├── test_memory_daemon.py
├── test_memory_phase1.py
├── test_memory_phase2.py
├── test_memory_recall.py
├── test_memory_context.py
├── test_memory_pipeline_e2e.py
├── test_memory_recall_with_pipeline.py
├── test_memory_ask_slow_brain_with_cancel.py
├── test_memory_failure_modes.py
├── fixtures/memory/         # JSONL / expected outputs / mock responses
└── manual/
    └── test_real_codex_smoke.py   # release 前手测
```

### 修改

```
g1_brain/g1_brain/brain/conversation_logger.py     +80 行(3 个新方法)
g1_brain/g1_brain/skills/skill_server.py           +150 行(memory kwarg + 4 tool + auto action_result)
g1_brain/g1_brain/skills/tool_schemas.py           +60 行(4 个新 schema)
g1_brain/g1_brain/apps/agent_main.py               +15 行(3 处插入)
g1_brain/configs/g1_brain.yaml                     +15 行(memory: 节)
g1_brain/g1_brain/brain/conversation_state.py      +3 行(turn_start scene_snapshot)
g1_brain/g1_brain/safety/state_machine.py          +3 行(fsm_transition safety_event)
g1_brain/g1_brain/safety/vision_risk_gate.py       +3 行(vision_gate_risk)
g1_brain/g1_brain/safety/estop_listener.py         +3 行(estop)
g1_brain/tests/test_conversation_logger.py         +60 行(3 个新方法测试)
g1_brain/tests/test_skill_server.py                +120 行(4 个新 tool + action_result)
g1_brain/tests/test_tool_schemas.py                +30 行
g1_brain/tests/test_vertical_slice.py              +40 行(memory 注入验证)
```

---

文档结束。设计 freeze,下一步进入 spec 与实现。
