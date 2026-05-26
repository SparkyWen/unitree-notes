我现在根据 OpenAI Codex 官方文档、公开源码和社区讨论重新判断：

> **OpenAI Codex 的 SQLite 主要不是 runtime recall index。**
>  它更像是：
>  **会话 resume / agent job / memory pipeline 的状态数据库。**

也就是说，你这次的判断比“OpenAI 用 SQLite 优化 Claude 的全量搜索”更准确：

```
错误理解：
SQLite = Codex 的主召回索引 / 全文检索库

更准确理解：
SQLite = Codex 的状态控制层
       = resume 元数据
       = memory 生成任务队列
       = Phase 1/Phase 2 的 job/lease/stage-output 存储
       ≠ 主模型每个 turn 直接查询的知识库 （其实这里有一个很有意思的点， 就是不要在一个codex session中进行长上下文的对话， 因为他们的prompt只存第一句话， 可以方便直接搜到的）
```

OpenAI 官方 config reference 明确有一个 `sqlite_home` 配置，说明它是 “SQLite-backed state DB used by agent jobs and other resumable runtime state”，也就是用于 agent jobs 和可恢复 runtime state 的 SQLite 状态库。这个描述本身就更接近“控制平面”，而不是“全文召回索引”。

------

# 1. 先把 OpenAI Codex 的 recall 分成 4 条线

你给的 Claude 图里有三条主线：

```
Memory 系统
主模型 tool call
CLAUDE.md + system context
```

OpenAI Codex 也可以拆成类似结构，但它的 Memory 部分要再拆成“写入”和“读取”。

------

## OpenAI Codex 的整体召回流程图

```
┌──────────────────────────────────────────────────────────────┐
│                    用户输入 / 新 turn                         │
└─────────────────────────────┬────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Memory 读取路径   │  │ 主模型代码库搜索   │  │ 启动/系统上下文    │
│ read_path.md      │  │ shell/tool call   │  │ AGENTS.md/config  │
│                  │  │                  │  │                  │
│ memory_summary.md │  │ rg / rg --files   │  │ system prompt     │
│ MEMORY.md         │  │ sed / cat / nl    │  │ AGENTS.md         │
│ rollout_summaries │  │ git show / ls     │  │ project config    │
│ skills            │  │ tests / build     │  │ sandbox settings  │
│ rollout_path回查  │  │                  │  │                  │
│                  │  │ 模型主动生成查询词 │  │ 启动时加载/注入   │
└──────────────────┘  └──────────────────┘  └──────────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                        主模型上下文


额外后台写入通道：
┌──────────────────────────────────────────────────────────────┐
│                 Memory Generation Pipeline                   │
│                                                              │
│ Root session 启动时触发                                      │
│ 非 ephemeral / memories enabled / 非 sub-agent / state DB 可用 │
│                                                              │
│ Phase 1: rollout JSONL → raw_memory / rollout_summary → DB    │
│ Phase 2: stage-1 outputs → ~/.codex/memories/ 文件            │
│                                                              │
│ SQLite/state DB 负责：claim、lease、retry、stage-output、锁    │
└──────────────────────────────────────────────────────────────┘
```

关键点是：

> **OpenAI 的 SQLite 不在主模型每个 turn 的前台召回路径中心。**
>  前台真正读的是 `memory_summary.md`、`MEMORY.md`、`rollout_summaries/`、`skills/` 和必要时的原始 `rollout_path` JSONL。

Codex 的 `read_path.md` 源码模板明确说：memory folder 用来提供 prior runs 的 guidance，但只能读取，不能更新；并且它列出的 memory layout 是 `memory_summary.md`、`MEMORY.md`、`skills/`、`rollout_summaries/`，再通过 `rollout_path` 回到原始 JSONL。

------

# 2. OpenAI 的 SQLite 到底承担什么，不承担什么？

## 2.1 SQLite 承担的事情

根据 OpenAI 源码 README，memory pipeline 在 root session 启动时触发，并且异步后台跑 Phase 1、Phase 2。触发条件包括：不是 ephemeral session、memory feature enabled、不是 sub-agent session、state DB 可用。

SQLite/state DB 在这个 pipeline 里主要承担：

| 功能                           | 解释                                                         |
| ------------------------------ | ------------------------------------------------------------ |
| **eligible rollout selection** | 从历史 rollout 中选出可以被生成 memory 的候选                |
| **startup claim**              | 每次启动只 claim 有限数量的 rollout                          |
| **lease / ownership**          | 防止多个 worker 同时处理同一个 rollout                       |
| **retry backoff**              | 失败后延迟重试，避免死循环                                   |
| **stage-1 outputs**            | 存储 Phase 1 生成的 `raw_memory`、`rollout_summary`、`rollout_slug` |
| **Phase 2 selection**          | 按 `usage_count`、`last_usage`、`generated_at` 选出要整合的 memory |
| **global phase-2 lock**        | 保证同一时间只有一个 consolidation agent 改 `~/.codex/memories/` |
| **resumable runtime state**    | 保存 agent jobs 和可恢复 runtime 状态                        |

Phase 1 源码说明里直接写：它会从 state DB claim 有界 rollout jobs，过滤 memory-relevant response items，并行发给模型，得到 `raw_memory`、`rollout_summary` 和可选 `rollout_slug`，然后把成功输出写回 state DB。

Phase 2 则会 claim 一个 global lock，从 state DB 读取 bounded stage-1 outputs，然后同步到 `raw_memories.md`、`rollout_summaries/`，最后必要时启动 internal consolidation sub-agent 更新更高层 memory artifacts。

------

## 2.2 SQLite 不承担的事情

根据目前公开源码和官方文档，我没有看到证据说明：

```
SQLite = runtime 每 turn 的主全文检索库
SQLite = 向量数据库
SQLite = semantic codebase index
SQLite = 主模型直接查的 memory index
SQLite = 替代 rg / grep / LSP 的代码召回系统
```

相反，OpenAI 的公开 memory 读取模板说得很清楚：

```
运行时 memory lookup：
1. 看 memory_summary
2. 搜 MEMORY.md
3. 打开 1-2 个 rollout_summaries / skills
4. 需要 exact evidence 时再搜 rollout_path
5. 没有 relevant hits 就停止
```

这个流程里主角是 **Markdown memory artifacts + 原始 JSONL fallback**，不是 SQLite。

所以你的判断可以改成一句更精确的话：

> **OpenAI Codex 的 SQLite 是 memory generation / resumable runtime 的状态数据库，不是前台 recall 的主检索索引。**

------

# 3. OpenAI Codex 的 Memory 写入流程：Phase 1 / Phase 2

这个是 OpenAI 和你图里 Claude “Auto Dream” 最像的部分，但触发机制不同。

Claude 图里你写的是：

```
Auto Dream 24h 触发
forked agent grep JSONL transcripts
把信号整合回 .md
```

OpenAI Codex 更像：

```
Root session 启动触发
后台异步跑
Phase 1 处理历史 rollout JSONL
Phase 2 整合到 ~/.codex/memories/
```

------

## 3.1 Phase 1：从单个 rollout 抽取 memory

Phase 1 官方源码叫：

```
Phase 1: Rollout Extraction (per-thread)
```

它做的事情是：

```
历史 rollout JSONL
   ↓
过滤 memory-relevant response items
   ↓
发给模型抽取
   ↓
得到 raw_memory / rollout_summary / rollout_slug
   ↓
redact secrets
   ↓
写入 state DB
```

OpenAI 源码明确写：Phase 1 会找 recent eligible rollouts，并从每个 rollout 抽取 structured memory；eligible rollouts 是从 state DB 里根据 startup claim rules 选择的，包括来源、年龄窗口、idle 时间、是否已被其他 worker 拥有、是否在 startup scan/claim limit 内。

这说明 Phase 1 不是“当前 turn 的 recall”。它是：

```
后台 memory 生成任务
```

而且它不会全量处理所有历史。官方配置里有：

| 配置                                | 默认/含义                                       |
| ----------------------------------- | ----------------------------------------------- |
| `memories.max_rollout_age_days`     | 默认 30 天，最多考虑多老的线程                  |
| `memories.max_rollouts_per_startup` | 默认每次启动最多处理 16 个候选                  |
| `memories.min_rollout_idle_hours`   | 默认 idle 6 小时后才考虑生成 memory             |
| `memories.generate_memories`        | 是否把新线程作为 memory-generation inputs       |
| `memories.extract_model`            | 可选 per-thread memory extraction 模型 override |

这些配置说明 OpenAI 是受限、后台、分批抽取，不是无限全量扫描。

------

## 3.2 Phase 2：把多个 stage-1 outputs 整合成 memory files

Phase 2 官方源码叫：

```
Phase 2: Global Consolidation
```

它做的是：

```
state DB 里的 stage-1 outputs
   ↓
按 usage_count / last_usage / generated_at 选 top-N
   ↓
同步 raw_memories.md
   ↓
同步 rollout_summaries/
   ↓
写 phase2_workspace_diff.md
   ↓
如果 workspace 有变化，启动 internal consolidation sub-agent
   ↓
更新 MEMORY.md / memory_summary.md / skills 等
```

源码明确写：Phase 2 会 claim 一个 single global phase-2 lock，然后读取 bounded stage-1 outputs，忽略超过 `max_unused_days` 的 memory，并按 `usage_count` 和最近使用/生成时间排序。它会同步 `raw_memories.md` 和 `rollout_summaries/`，并把 memories root 作为 git-baseline directory 管理。

这和 Claude 图里的 “Auto Dream 把信号整合回 .md” 很像，但 OpenAI 更工程化：

```
Claude 图里的离线通道：
JSONL transcripts → forked agent grep → .md

OpenAI Codex：
rollout JSONL → Phase 1 model extraction → state DB
state DB stage-1 outputs → Phase 2 consolidation agent → ~/.codex/memories/*.md
```

注意这里 SQLite 仍然不是最终 recall index，它是：

```
Phase 1/Phase 2 的中间状态仓库
```

最终给未来 session 读的是 `.md` 文件和 rollout summary 文件。

------

# 4. OpenAI Codex 的 Memory 读取流程：read_path.md

前面 Phase 1 / Phase 2 是“写 memory”。
 真正 runtime 读 memory 的地方是：

```
codex-rs/core/templates/memories/read_path.md
```

这个文件等价于 Codex 的 memory recall policy。

源码里写得非常清楚：

```
Memory layout:
- memory_summary.md
- MEMORY.md
- skills/
- rollout_summaries/
- rollout_path JSONL
```

并且 `MEMORY.md` 被称为 searchable registry / primary file to query。

------

## 4.1 runtime 读取路径

OpenAI 的 runtime memory 读取流程可以画成：

```
新 turn
  ↓
判断是否需要 memory
  ↓
如果任务 self-contained，就跳过
  ↓
否则 quick memory pass
  ↓
先看 memory_summary.md
  ↓
提取 task-relevant keywords
  ↓
搜索 MEMORY.md
  ↓
如果 MEMORY.md 指向 rollout_summaries/skills
  ↓
只打开 1-2 个最相关文件
  ↓
如果还需要 exact commands / error text / evidence
  ↓
搜索 rollout_path 原始 JSONL
  ↓
停止 memory lookup，进入主任务
```

源码明确说：memory lookup 要轻量，理想情况下在 4-6 个 search steps 内完成，并避免 broad scans of all rollout summaries。

这就说明：

> **OpenAI runtime recall 不是 SQLite 全库搜索，而是 Markdown registry + summary-first + bounded lookup + JSONL fallback。**

------

# 5. 你猜测的“模型生成 grep/search pattern”是否成立？

## 5.1 对代码库搜索：成立

OpenAI Codex 的公开模型指令里明确写：搜索文本或文件时优先用 `rg` 或 `rg --files`，因为它们比 `grep` 快；如果 `rg` 不可用，就用替代工具。它还鼓励并行化 `cat`、`rg`、`sed`、`ls`、`git show`、`nl`、`wc` 等文件读取工具调用。

这说明 Codex 在代码库理解上，很大程度是：

```
模型根据任务生成搜索词 / 文件路径假设
  ↓
调用 shell 工具，如 rg / rg --files / sed / cat / git show
  ↓
读取局部证据
  ↓
继续迭代搜索
```

所以你说的：

> “利用大模型能力去生成 grep 等 search pattern”

对 **代码库召回** 是成立的。

------

## 5.2 对 memory 召回：部分成立

Memory 召回里也有“模型生成关键词”的成分。`read_path.md` 明确说 quick memory pass 第一步是 skim `MEMORY_SUMMARY`，然后 extract task-relevant keywords，再搜索 `MEMORY.md`。

但这不是直接：

```
模型 grep 所有 transcript
```

而是：

```
模型先从 memory_summary 里抽关键词
  ↓
搜索 MEMORY.md
  ↓
再打开少量 rollout_summaries
  ↓
必要时才搜 rollout_path 原始 JSONL
```

所以 OpenAI 是 **模型辅助关键词选择 + 有界 markdown registry 搜索 + 原始 JSONL fallback**。

------

## 5.3 对 LSP / 语义搜索：目前公开证据不足

你猜测 Codex 可能用 “语义 LSPTool 等进行匹配”。这里需要谨慎。

我查到的公开 Codex GitHub issue 反而说明：**first-class semantic codebase indexing/search 仍然是社区提出的 feature request，而不是公开证明已经是 Codex core 的默认能力**。一个 2025 年 10 月 issue 明确说 Codex 目前在大代码库中主要依赖 grep 或 filename heuristics，缺少 first-class semantic search；该 issue 提议增加 semantic index/search flow。

也就是说，根据公开源码和社区 issue：

```
能确认：
Codex 强依赖 rg / rg --files / shell 工具 / 文件读取

不能确认：
Codex core 已经默认有成熟的 semantic LSP recall index

社区诉求：
希望加入 semantic codebase indexing/search 或 LSP integration
```

所以你的猜测应该分开写：

| 召回对象       | 是否模型生成搜索 pattern                    | 是否公开证明有 SQLite/LSP/semantic index |
| -------------- | ------------------------------------------- | ---------------------------------------- |
| 当前代码库     | 是，主要通过 `rg` / shell / 文件读取        | semantic index 未见已落地证据            |
| memory files   | 是，先从 summary 生成关键词再搜 `MEMORY.md` | 不是 SQLite 主查                         |
| 旧 transcript  | 必要时可按 `rollout_path` 回查              | 不是默认全量扫                           |
| session resume | 依赖 state/session metadata + rollout JSONL | SQLite 主要是恢复/索引状态               |

------

# 6. OpenAI 和 Claude 的核心区别

根据你给的 Claude 图，我会这样评判。

------

## 6.1 Claude：更像 turn-level 被动预取 + `.md only` memory

你总结的 Claude 流程是：

```
每个新 turn
  ↓
scanMemoryFiles
formatManifest
sideQuery Sonnet
readForSurfacing
  ↓
最多 20KB/turn, 60KB/session
  ↓
注入主模型上下文
```

这像是：

```
前台 turn 过程中，有一个 memory surfacing 系统
```

它更偏：

```
每 turn 辅助召回 memory markdown
```

------

## 6.2 OpenAI：更像后台 memory 生成 + 前台轻量读取

OpenAI Codex 是：

```
后台：
rollout JSONL → Phase 1 → state DB → Phase 2 → ~/.codex/memories/*.md

前台：
memory_summary.md → MEMORY.md → rollout_summaries/skills → rollout_path fallback
```

它的重点不是“每 turn 大量预取”，而是：

```
提前把历史 session 蒸馏成 memory artifacts
前台只轻量查 registry 和少数 evidence
```

------

## 6.3 OpenAI 的 SQLite 位置和 Claude 不同

如果把 Claude 的 `.md only memory` 和 OpenAI 对比：

| 模块             | Claude 图中的理解                  | OpenAI Codex 对应                                       |
| ---------------- | ---------------------------------- | ------------------------------------------------------- |
| 启动/系统规则    | `CLAUDE.md`                        | `AGENTS.md` / global + repo + subdir guidance           |
| 当前代码库检索   | Grep / Glob / Read / LSPTool       | `rg` / `rg --files` / shell / file reads / git / tests  |
| Memory 前台召回  | scan `.md` + sideQuery + surfacing | `read_path.md`：summary → MEMORY.md → rollout_summaries |
| 离线整合         | Auto Dream 24h                     | root session startup background pipeline                |
| 原始 transcript  | JSONL transcripts                  | rollout JSONL                                           |
| SQLite           | Claude 图里没有                    | Codex state DB：resume + job/lease + stage outputs      |
| 最终 memory 形态 | `.md`                              | 仍然主要是 `~/.codex/memories/*.md`                     |

所以 OpenAI 不是“把 Claude 的 Memory `.md only` 改成 SQLite 检索”。

更准确是：

> **OpenAI 仍然把最终 memory 做成 `.md` 文件；SQLite 只是把 memory 生成和 session 恢复工程化了。**

------

# 7. OpenAI Codex 的前台 recall 可以这样画

这是我认为最接近公开源码的 OpenAI Codex recall 图：

```
┌──────────────────────────────────────────────────────────────┐
│                      用户输入 / 新 turn                       │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ 判断是否需要 memory│
                    │ read_path.md      │
                    └─────────┬────────┘
                              │
         ┌────────────────────┴────────────────────┐
         │                                         │
         ▼                                         ▼
┌──────────────────┐                      ┌──────────────────┐
│ self-contained    │                      │ 需要 prior context│
│ 跳过 memory       │                      │ quick memory pass │
└──────────────────┘                      └─────────┬────────┘
                                                    │
                                                    ▼
                                      ┌────────────────────────┐
                                      │ memory_summary.md       │
                                      │ 已经注入/提供，不再打开 │
                                      └───────────┬────────────┘
                                                  │
                                                  ▼
                                      ┌────────────────────────┐
                                      │ 提取 task keywords      │
                                      └───────────┬────────────┘
                                                  │
                                                  ▼
                                      ┌────────────────────────┐
                                      │ 搜索 MEMORY.md          │
                                      │ primary searchable file │
                                      └───────────┬────────────┘
                                                  │
                           ┌──────────────────────┴──────────────────────┐
                           ▼                                             ▼
              ┌────────────────────────┐                    ┌──────────────────────┐
              │ 打开 1-2 个相关 summary │                    │ 没有相关命中，停止    │
              │ rollout_summaries/skills│                    │ memory lookup         │
              └───────────┬────────────┘                    └──────────────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ 需要精确证据时           │
              │ 搜 rollout_path JSONL    │
              └───────────┬────────────┘
                          │
                          ▼
                    主模型继续工作
```

这张图的核心和 Claude 图不同：

```
Claude：每 turn memory surfacing 可能更像前台预取

OpenAI：前台 read_path 是 lightweight lookup；
       后台 Phase 1/2 已经提前把历史加工成 memory artifacts
```

------

# 8. OpenAI Codex 的后台 memory pipeline 图

```
┌──────────────────────────────────────────────────────────────┐
│                    root session starts                       │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
            ┌──────────────────────────────────────┐
            │ 检查触发条件                          │
            │ - not ephemeral                       │
            │ - memories enabled                    │
            │ - not sub-agent                       │
            │ - state DB available                  │
            └──────────────────┬───────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Phase 1: Rollout Extraction                                  │
│                                                              │
│ state DB 选择 eligible rollouts                              │
│   - allowed sources                                           │
│   - age window                                                │
│   - idle long enough                                          │
│   - not owned by another worker                               │
│   - startup claim limit                                       │
│                                                              │
│ 读取 rollout JSONL                                            │
│ 过滤 memory-relevant response items                           │
│ 调模型抽取 raw_memory / rollout_summary / rollout_slug         │
│ redacts secrets                                               │
│ 写回 state DB as stage-1 outputs                              │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ Phase 2: Global Consolidation                                │
│                                                              │
│ claim global phase-2 lock                                     │
│ 从 state DB 读取 bounded stage-1 outputs                      │
│ 按 usage_count / last_usage / generated_at 选择                │
│ 同步 raw_memories.md                                          │
│ 同步 rollout_summaries/                                       │
│ 生成 phase2_workspace_diff.md                                 │
│ 若有变化，启动 internal consolidation sub-agent                │
│ 更新 MEMORY.md / memory_summary.md / skills                   │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              ▼
                    ~/.codex/memories/
```

OpenAI 官方 memories 文档也说：Codex 会把 eligible prior threads 的有用上下文转成本地 memory files；它会跳过 active 或 short-lived sessions，redact secrets，并在后台更新 memories，而不是每个 thread 结束立刻更新。

------

# 9. 所以 SQLite 对速度有没有帮助？

有，但不是你最开始想的那种“检索速度”。

## 9.1 SQLite 加速的是后台管理和恢复

SQLite 帮助的是：

```
快速找哪些 rollout eligible
快速 claim N 个 job
避免重复处理
失败 retry
按使用次数/时间排序
保存 stage-1 outputs
session/thread resume
agent jobs resumable state
```

这确实能提高系统整体速度和稳定性。尤其当历史 session 很多时，不能每次都扫整个 `sessions/**/*.jsonl` 来判断哪个 thread 该处理。

------

## 9.2 SQLite 没有公开证据承担主召回索引

没有看到证据说：

```
用户问问题
  ↓
Codex 在 SQLite 里做全文检索/语义检索
  ↓
召回相关 transcript
  ↓
注入主模型
```

相反，官方 `read_path.md` 指向的是：

```
memory_summary.md
MEMORY.md
rollout_summaries/
rollout_path
```

并且建议避免 broad full-content scans。

因此：

> **SQLite 提高的是 memory pipeline 和 resume 的工程效率；不是直接提高前台语义召回质量。**

------

# 10. OpenAI 会不会漏召回？

会。这个架构天然有 trade-off。

## 10.1 可能漏的地方

| 漏召回位置            | 为什么会漏                                             |
| --------------------- | ------------------------------------------------------ |
| Phase 1 抽取          | 模型没有把某个细节写进 `raw_memory`                    |
| Phase 2 整合          | consolidation 把细节压缩掉                             |
| MEMORY.md 搜索        | 用户提问词和 memory 词不一致                           |
| quick-pass budget     | 只允许 4-6 步，不鼓励广泛扫描                          |
| rollout_path fallback | 只有需要精确证据时才回查原始 JSONL                     |
| semantic search       | 公开核心能力里没有看到 first-class semantic code index |

所以 OpenAI 这套 memory 更偏：

```
稳定偏好 / 项目约定 / 已知坑 / 重复流程
```

不擅长：

```
某次历史 session 中一个低频错误字符串
某个临时命令输出
一个从未被总结进 memory 的细节
```

------

## 10.2 但 OpenAI 为什么仍然这么做？

因为全量 transcript 搜索有巨大成本：

```
启动慢
token 噪音高
跨项目污染
上下文预算浪费
历史越多越不可控
容易把旧状态当成新事实
```

OpenAI 的设计倾向是：

```
历史全量信息 → 后台蒸馏
未来使用 → summary-first / registry-first / evidence-on-demand
```

这牺牲了一些 recall completeness，但换来了：

```
速度
低噪音
可控上下文预算
并发安全
可恢复状态
更少主模型负担
```

------

# 11. 最终评判你的观点

你的观点：

> “OpenAI 的 SQLite 其实只做 transcript 的正确 resume，而不承担召回索引功能。”

我会修正成：

> **基本正确，但还要加上一点：SQLite 不只是 transcript resume，也承担 memory generation pipeline 的 job/state/stage-output 管理。只是它不承担前台 runtime recall 的主索引功能。**

更完整：

```
SQLite 在 OpenAI Codex 中主要承担：
1. session/thread/resume 相关状态
2. agent jobs 和 resumable runtime state
3. Phase 1 rollout extraction 的 claim/lease/retry/stage-output
4. Phase 2 global consolidation 的 selection/lock/watermark/usage metadata

SQLite 不主要承担：
1. 每 turn 的 memory 全文召回
2. 代码库语义检索
3. LSP 符号级索引
4. embedding/vector search
5. Claude 式 sideQuery 的直接替代
```

------

# 12. 一句话总结

**OpenAI Codex 的 recall 不是“SQLite 检索替代 Claude 全量搜索”。**

更准确是：

```
OpenAI Codex =
AGENTS.md 确定性规则
+ 模型主动 rg / shell / git / file read 做代码库搜索
+ 后台 Phase 1/Phase 2 把历史 rollout 蒸馏成 ~/.codex/memories/
+ 前台 read_path.md 轻量读取 memory_summary / MEMORY.md / rollout_summaries
+ 必要时回查 rollout_path JSONL 原始证据
+ SQLite 负责状态、resume、job、lease、stage-output，而不是主召回索引
```

---



我会把这里的 **runtime** 拆成两个概念：一是“用户正在和 Codex 对话/执行工具的主运行时”，二是“Codex 进程启动后悄悄跑的后台 memory runtime”。Phase 1 / Phase 2 更准确地说属于后者，不是每次用户提问时同步执行的主循环。

Thought for 23s

# 直接回答你最关键的问题

**Phase 1 和 Phase 2 确实出现在 Codex 的 runtime 过程中，但不是“用户每发一句话就同步跑一次”的主对话 runtime。**

更准确地说：

> **Phase 1 / Phase 2 是 Codex memory subsystem 的“后台生成记忆 runtime”。**
>  它在 **root session 启动时被触发**，然后**异步后台运行**，顺序是 **Phase 1 → Phase 2**。Codex 源码 README 明确写了触发条件：必须是 root session、不是 ephemeral session、memory feature 已启用、不是 sub-agent session、state DB 可用；满足后，它在后台异步跑两个阶段。

所以你可以把 Codex 分成两条运行线：

```
用户主线 runtime:
用户输入 → 模型思考 → 工具调用 → 编辑文件 → 返回结果

后台 memory runtime:
root session 启动 → Phase 1 抽取旧 rollout → Phase 2 全局整合 → 生成/更新 ~/.codex/memories/
```

------

# 1. Phase 1 / Phase 2 到底“在哪里出现”？

它们出现在 OpenAI Codex 开源仓库的 memory 模块里：

```
codex-rs/core/src/memories/
codex-rs/core/templates/memories/
```

源码 README 说 memory prompt templates 位于：

```
codex-rs/core/templates/memories/
```

其中包括：

```
stage_one_system.md
stage_one_input.md
consolidation.md
read_path.md
```

并且这些 undated template files 是 Codex 当前 runtime 使用的 canonical latest versions。

这几个文件分别对应：

| 文件                  | 作用                                                    |
| --------------------- | ------------------------------------------------------- |
| `stage_one_system.md` | Phase 1 单个 rollout 的 memory writing agent 系统提示词 |
| `stage_one_input.md`  | Phase 1 输入模板                                        |
| `consolidation.md`    | Phase 2 全局整合 agent 提示词                           |
| `read_path.md`        | 未来 session 读取 memories 时的召回路径提示词           |

所以：**Phase 1 和 Phase 2 不是我自己推测出来的概念，而是 OpenAI Codex 源码中明确命名的 memory pipeline 阶段。**

------

# 2. 它是不是 runtime 过程中的一部分？

答案要分三层。

## 2.1 是 runtime，因为 Codex 运行时会触发它

Codex README 明确写：memory pipeline 在 root session starts 时触发，并且异步后台执行 Phase 1 和 Phase 2。

也就是说，当你打开 Codex CLI / Desktop / IDE extension，启动一个新的主 session 时，它可能会同时做两件事：

```
前台：
处理你当前这个 session

后台：
扫描过去 eligible sessions，生成 memories
```

这就是为什么有用户在 GitHub issue 里观察到：Codex Desktop 看起来 idle，但 `~/.codex/logs_2.sqlite` 里出现了 memory subsystem 的模型请求，`cwd=~/.codex/memories`，并且关闭 `generate_memories = false` 后这类 idle sampling request 停止了。这个 issue 是社区观察，不是官方正式说明，但和源码“后台异步生成 memory”的设计一致。

------

## 2.2 但它不是“每轮用户消息都跑”的主 agent loop

你可以理解为：

```
不是：
用户问一句 → Phase 1 → Phase 2 → 再回答

而是：
启动 root session → 后台 memory pipeline 可能开始跑
用户提问 → 主 agent 正常回答
未来 session → 读取已经生成好的 memories
```

所以 Phase 1 / Phase 2 是 **memory 写入链路**，不是 **当前问题回答链路**。

------

## 2.3 当前 session 真正使用 memory 的地方是 `read_path.md`

当 Codex 未来要“读 memory”时，走的是另一个路径：`read_path.md`。这个模板告诉模型：它可以访问 memory folder，但只能读取，不能更新；先看 `memory_summary.md`，再搜 `MEMORY.md`，必要时打开 `rollout_summaries/` 或 `skills/`，最后才根据 `rollout_path` 回查原始 JSONL。

所以完整链路是：

```
Phase 1 / Phase 2 = 写 memory
read_path.md       = 读 memory
```

这点非常重要。

------

# 3. Phase 1 到底做什么？

Phase 1 的正式名字是：

```
Phase 1: Rollout Extraction (per-thread)
```

它的任务是：

> **把一个个历史 session 的 rollout JSONL 转成结构化 memory 记录。**

OpenAI 源码 README 写得很直接：Phase 1 会找到 recent eligible rollouts，并从每一个 rollout 中抽取 structured memory。eligible rollouts 从 state DB 中按 startup claim rules 选择。

------

## 3.1 Phase 1 的输入是什么？

输入主要是：

```
历史 session / rollout JSONL
```

也就是你本机看到的类似：

```
~/.codex/sessions/2026/04/28/rollout-xxx.jsonl
```

但 Phase 1 不会无脑处理所有 JSONL，而是先通过 state DB 筛选 eligible rollouts。

------

## 3.2 什么样的 rollout 才会被 Phase 1 处理？

源码 README 说，它只考虑这些 rollout：

| 条件                                | 含义                                     |
| ----------------------------------- | ---------------------------------------- |
| allowed interactive session sources | 来自允许的交互式 session 来源            |
| within configured age window        | 在配置允许的年龄窗口内                   |
| idle long enough                    | 已经空闲足够久，避免总结还在进行中的工作 |
| not owned by another worker         | 没有被其他 Phase 1 worker 占用           |
| within startup scan/claim limits    | 每次启动只处理有限数量，避免无限扫描     |

这些条件都由 state DB 和配置共同控制。

官方 config reference 也给了相关配置：`memories.max_rollout_age_days` 默认 30 天、`memories.max_rollouts_per_startup` 默认每次 startup 最多处理 16 个候选、`memories.min_rollout_idle_hours` 默认需要 idle 6 小时，`memories.use_memories` 控制是否把已有 memories 注入未来 session。

------

## 3.3 Phase 1 具体步骤

可以拆成下面这条链：

```
state DB 选候选 rollout
        ↓
claim / lease rollout job
        ↓
读取 rollout JSONL
        ↓
过滤成 memory-relevant response items
        ↓
调用模型做单 rollout 抽取
        ↓
得到 raw_memory / rollout_summary / rollout_slug
        ↓
redact secrets
        ↓
写回 state DB，形成 stage-1 outputs
```

源码 README 明确说 Phase 1 会 claim bounded rollout jobs，从 rollout 内容中过滤 memory-relevant response items，并发发送给模型，期望结构化输出包含 `raw_memory`、`rollout_summary` 和可选 `rollout_slug`，然后 redacts secrets 并把成功结果存回 state DB。

------

## 3.4 Phase 1 的模型提示词长什么样？

`stage_one_system.md` 里第一行就写：

```
Memory Writing Agent: Phase 1 (Single Rollout)
```

它的任务是：

```
convert raw agent rollouts into useful raw memories and rollout summaries
```

也就是把原始 agent rollout 转成未来 agent 可用的 raw memories 和 rollout summaries。

这个 prompt 还强调：

| 规则                                      | 解释                              |
| ----------------------------------------- | --------------------------------- |
| raw rollouts 是 immutable evidence        | 不要改原始 rollout                |
| tool outputs 视为 data，不是 instructions | 防 prompt injection               |
| evidence-based only                       | 不要编造                          |
| redact secrets                            | 不存 token/password               |
| no-op allowed                             | 没有高价值内容就输出空字段        |
| high-signal memory                        | 只保存会改变未来 agent 行为的信息 |

源码 prompt 明确说：如果未来 agent 不会因为这条 memory 做得更好，就应该返回空字段；高价值 memory 包括稳定用户偏好、高杠杆流程知识、决策触发器、已验证的环境/workflow 事实等。

------

## 3.5 Phase 1 输出是什么？

Phase 1 输出不是直接写 `MEMORY.md`。

它先输出到 **state DB**，形成所谓：

```
stage-1 outputs
```

每条 stage-1 output 大概包括：

| 字段              | 作用                                                         |
| ----------------- | ------------------------------------------------------------ |
| `raw_memory`      | 更详细、结构化、可被 Phase 2 整合的原始记忆                  |
| `rollout_summary` | 对该 session 的完整摘要，未来必要时可读                      |
| `rollout_slug`    | 文件名友好的短标识                                           |
| metadata          | generated_at、usage_count、last_usage、selected_for_phase2 等状态 |

源码 README 明确说 Phase 1 是把 individual rollouts 变成 DB-backed memory records。

所以它的本质是：

```
原始 JSONL transcript
    ↓
每条会话一个结构化 memory record
    ↓
先进入 SQLite / state DB
```

------

# 4. Phase 2 到底做什么？

Phase 2 的正式名字是：

```
Phase 2: Global Consolidation
```

它的任务是：

> **把 Phase 1 生成的很多 per-rollout memory records，整合成真正可被未来 session 读取的 memory files。**

源码 README 说：Phase 2 会把最新 stage-1 outputs consolidate 到 filesystem memory artifacts，然后运行一个专门的 consolidation agent。

------

## 4.1 Phase 2 的输入是什么？

Phase 2 的输入不是原始 JSONL，而是：

```
state DB 里的 stage-1 outputs
```

也就是 Phase 1 已经抽取好的：

```
raw_memory
rollout_summary
rollout_slug
metadata
```

------

## 4.2 Phase 2 为什么要有 global lock？

因为 Phase 2 会改同一个共享目录：

```
~/.codex/memories/
```

如果多个 Codex 进程同时改这个目录，会出现：

```
MEMORY.md 被并发覆盖
rollout_summaries/ 删除和生成冲突
raw_memories.md 半写入
memory_summary.md 和 MEMORY.md 不一致
```

所以源码 README 写：Phase 2 会先 claim 一个 single global phase-2 lock，确保同一时间只有一个 consolidation 修改 memories root。

这就是 Phase 1 和 Phase 2 分开的关键原因：

```
Phase 1 可以并行：
多个 rollout 各自抽取

Phase 2 必须串行：
全局 memory workspace 只能一个 consolidation agent 改
```

源码 README 最后也明确解释：Phase 1 负责跨很多 rollouts 扩展处理，Phase 2 负责串行化全局 consolidation，以安全、一致地更新共享 memory artifacts。

------

## 4.3 Phase 2 如何选择哪些 stage-1 outputs？

它不会把所有历史都整合进去，而是加载 bounded set。

选择规则包括：

| 规则                             | 含义                                     |
| -------------------------------- | ---------------------------------------- |
| `max_unused_days`                | 太久没用的 memory 不再参与 consolidation |
| `generated_at` fallback          | 没有 last_usage 的新 memory 也可以被选中 |
| `usage_count` 排序               | 使用次数越多越优先                       |
| recent `last_usage/generated_at` | 越近越优先                               |
| top-N bounded set                | 只选有限数量                             |

这些规则都在源码 README 的 Phase 2 部分写明。

官方 config reference 也说 `memories.max_raw_memories_for_consolidation` 默认保留最多 256 条 recent raw memories，`memories.max_unused_days` 默认 30 天，超过后不再 eligible for consolidation。

------

## 4.4 Phase 2 会生成/更新哪些文件？

Phase 2 会同步本地 memory artifacts 到 memories root，比如：

```
~/.codex/memories/raw_memories.md
~/.codex/memories/rollout_summaries/
~/.codex/memories/MEMORY.md
~/.codex/memories/memory_summary.md
~/.codex/memories/skills/
```

其中源码 README 明确提到会同步：

```
raw_memories.md
rollout_summaries/
```

并且如果 workspace 有变化，会运行内部 consolidation sub-agent 继续更新更高层的 consolidated outputs。

官方 Memories 文档也说，main memory files 位于 `~/.codex/memories/`，包括 summaries、durable entries、recent inputs、supporting evidence。

------

## 4.5 Phase 2 为什么还要用 git baseline / diff？

这是一个很聪明的设计。

Phase 2 不只是“重新生成一遍 MEMORY.md”，而是维护一个 memory workspace 的变化视图：

```
上一次成功的 memory baseline
        ↓
这次 Phase 1 新选出来的 raw memories / summaries
        ↓
workspace diff
        ↓
consolidation agent 根据 diff 决定怎么改 MEMORY.md / memory_summary.md
```

源码 README 说，memories root 会作为 git-baseline directory 管理，Phase 2 会写 `phase2_workspace_diff.md`，里面包含从上一次成功 Phase 2 baseline 到当前 worktree 的 git-style diff；如果没有变化，就直接标记成功退出。

为什么这么做？

因为这样 consolidation agent 不需要每次重读全部历史，而是只看：

```
新增了什么
删除了什么
修改了什么
哪些 rollout summaries 不再 selected
```

这进一步提高速度，也降低噪音。

------

## 4.6 Phase 2 的 internal consolidation sub-agent 是什么？

如果 memory workspace 有变化，Phase 2 会启动一个内部 agent：

```
internal consolidation sub-agent
```

这个 sub-agent 的特点是：

| 特点                       | 目的                                     |
| -------------------------- | ---------------------------------------- |
| no approvals               | 不打扰用户                               |
| no network                 | 防止把 memory consolidation 变成联网任务 |
| local write access only    | 只写 memory workspace                    |
| disables collab            | 防止递归 delegation                      |
| heartbeat global job lease | 防止长任务被误认为死掉                   |

源码 README 明确写了这些限制。

所以 Phase 2 不是普通用户可见 agent，而是专门负责整理 memory workspace 的内部 agent。

------

# 5. Phase 1 / Phase 2 和 `read_path.md` 的关系

你可以用下面这张表理解：

| 阶段      | 读还是写  | 发生时间                  | 作用                                                         |
| --------- | --------- | ------------------------- | ------------------------------------------------------------ |
| Phase 1   | 写 memory | root session 启动后的后台 | 把历史 rollout 抽成 per-thread raw memory                    |
| Phase 2   | 写 memory | Phase 1 后台完成后        | 把很多 raw memories 整合成 `~/.codex/memories/` 文件         |
| read_path | 读 memory | 未来 session 回答问题时   | 从 `memory_summary.md` / `MEMORY.md` / rollout summaries 中召回上下文 |

`read_path.md` 明确规定了读取顺序：

```
1. 先看 MEMORY_SUMMARY
2. 用关键词搜索 MEMORY.md
3. 如果 MEMORY.md 指向 rollout summaries / skills，就打开 1-2 个最相关文件
4. 如果还需要 exact commands / error text / precise evidence，再查 rollout_path 原始 JSONL
5. 没有相关命中就停止
```

源码还要求 quick-pass 尽量保持在 4-6 个搜索步骤内，避免 broad scans of all rollout summaries。

所以：

```
Phase 1 / Phase 2 是 memory 写入 pipeline
read_path 是 memory 读取 pipeline
```

------

# 6. 用时间线彻底解释一次

假设你今天 10:00 打开 Codex，之前有 100 个历史 sessions。

## 10:00：root session 启动

Codex 检查：

```
是不是 root session？
是不是非 ephemeral？
memories 是否开启？
是不是不是 sub-agent？
state DB 是否可用？
```

如果满足，就触发 memory pipeline。源码 README 明确写了这些触发条件。

------

## 10:00 - 10:01：前台主 agent 继续工作

你可以正常输入：

```
解释这个代码库
修改这个文件
运行测试
```

这时主 agent loop 走自己的工具调用流程。

------

## 同时后台：Phase 1 开始扫描历史 rollout

它不会全量处理 100 个，而是按配置选一部分：

```
最近 30 天
idle 超过 6 小时
每次 startup 最多 16 个
没有被其他 worker claim
```

这些默认参数在官方 config reference 里有说明。

------

## 后台：Phase 1 调模型抽取

每个 rollout 被送入 Phase 1 memory writing agent。

它输出：

```
{
  "rollout_summary": "...",
  "rollout_slug": "...",
  "raw_memory": "..."
}
```

如果没有值得记住的信息，就输出空字段。`stage_one_system.md` 明确说 no-op is allowed and preferred when there is no meaningful reusable learning worth saving。

------

## 后台：Phase 1 写入 state DB

这时还没有真正形成最终 `MEMORY.md`。

你可以理解为：

```
Phase 1 只是在数据库里生成很多候选记忆
```

------

## 后台：Phase 2 开始

Phase 2 拿全局锁，防止多个 consolidation 同时写：

```
~/.codex/memories/
```

然后它从 state DB 选 top-N stage-1 outputs。

------

## 后台：Phase 2 同步文件

它会更新：

```
raw_memories.md
rollout_summaries/
phase2_workspace_diff.md
```

如果 workspace 没有变化，直接结束；如果有变化，启动 internal consolidation sub-agent。

------

## 后台：consolidation sub-agent 更新最终记忆

这个 agent 根据 diff 更新：

```
MEMORY.md
memory_summary.md
skills/
```

这些文件才是未来主 agent 更可能读取的高层 memory artifacts。

------

## 未来 13:00：你新开一个 session

如果 `use_memories = true`，Codex 会把 memory usage instructions 注入未来 session。官方 config reference 说，`memories.use_memories=false` 时 Codex 会跳过向未来 sessions 注入 existing memories。

这时主 agent 不会重新跑 Phase 1 / Phase 2 来回答你当前问题，而是根据 `read_path.md`：

```
先看 memory_summary.md
再搜 MEMORY.md
再打开 rollout_summaries
必要时回查 rollout_path 原始 JSONL
```

------

# 7. 你问的“runtime过程中吗”：最终判断

## 7.1 如果你说的是“Codex 进程运行期间”

**是。**

Phase 1 / Phase 2 在 Codex 运行期间触发，属于 runtime background work。

------

## 7.2 如果你说的是“模型每次回答用户问题的主推理过程”

**不是。**

它们不是每一轮用户消息同步执行的 recall step。

当前回答用户问题时，主要使用的是已经生成好的：

```
memory_summary.md
MEMORY.md
rollout_summaries/
rollout_path fallback
```

而不是现场把所有历史 rollout 做 Phase 1 / Phase 2。

------

## 7.3 如果你说的是“session 刚启动时会不会跑”

**会，满足条件时会。**

源码明确说 pipeline triggered when a root session starts。

------

## 7.4 如果你说的是“关闭 Codex 后还会不会跑”

一般不会。它不是独立系统 daemon 的概念；从现有源码和 issue 观察看，它依赖 Codex app/server/CLI 进程。社区 issue 也显示，用户是在 Codex Desktop 打开但 idle 时观察到后台 memory generation，而关闭 `generate_memories=false` 后停止了相关 sampling request。

------

# 8. 为什么要拆成 Phase 1 和 Phase 2？

这是架构设计里非常关键的一点。

## 8.1 Phase 1 适合并行

每个 rollout 是独立的：

```
rollout A → raw_memory A
rollout B → raw_memory B
rollout C → raw_memory C
```

所以可以并发处理，提高速度。

------

## 8.2 Phase 2 必须串行

最终记忆文件是共享的：

```
MEMORY.md
memory_summary.md
raw_memories.md
rollout_summaries/
skills/
```

如果多个 agent 同时整理，会冲突。所以 Phase 2 必须拿全局锁。

源码 README 直接解释了拆分原因：Phase 1 scales across many rollouts，Phase 2 serializes global consolidation so shared memory artifacts are updated safely and consistently。

------

# 9. 它和 SQLite 的关系是什么？

你可以这样理解：

```
SQLite/state DB = memory pipeline 的控制平面
Markdown memory files = 未来 agent 读取的知识平面
JSONL rollout = 原始证据平面
```

具体来说：

| 层         | 文件/系统                    | 作用                                                         |
| ---------- | ---------------------------- | ------------------------------------------------------------ |
| 原始证据   | rollout JSONL                | 保存真实历史会话                                             |
| 控制平面   | state DB / SQLite            | 选择 eligible rollout、claim job、lease、retry、usage_count、last_usage、stage-1 outputs |
| 中间产物   | raw_memory / rollout_summary | Phase 1 生成的结构化候选记忆                                 |
| 最终产物   | `~/.codex/memories/`         | Phase 2 整合后的可读 memory workspace                        |
| 运行时读取 | `read_path.md`               | 指导未来 agent 如何轻量召回                                  |

所以 SQLite 不是最终给模型“直接全文读”的记忆本体。SQLite 更像：

```
任务队列 + 状态表 + 索引表 + 去重/锁/租约系统
```

------

# 10. 一句话彻底总结

**Phase 1 和 Phase 2 是 Codex memories 的后台写入 pipeline。**

```
Phase 1:
把单个历史 rollout JSONL 抽取成 DB-backed raw_memory / rollout_summary

Phase 2:
把多个 stage-1 outputs 全局整合成 ~/.codex/memories/ 下的 MEMORY.md、memory_summary.md、rollout_summaries 等文件
```

它们**出现在 Codex 运行时**，但属于**root session 启动后异步后台运行的 memory generation runtime**，不是用户每次提问时同步执行的主 agent runtime。

真正回答未来问题时，Codex 主要走的是：

```
read_path.md:
memory_summary.md → MEMORY.md → rollout_summaries/skills → rollout_path 原始 JSONL fallback
```
