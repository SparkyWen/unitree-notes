# Claude Code 2.1.88 记忆系统深度分析报告

> 源码位置：`E:\Au_notes\claude_code\source\src`
> 源码版本：`@anthropic-ai/claude-code@2.1.88`（从 cli.js.map 提取）

本文档系统梳理 Claude Code 记忆系统的全部细节，涵盖：
1. SessionMemory / DurableMemory / TeamMemory 三种记忆类型的区分
2. Relevant Memory Retrieval（记忆召回）完整流程
3. 记忆召回机制（是否使用 embedding/hybrid？）
4. Extract Memories（记忆抽取）实现
5. Auto Dream / Consolidation（记忆整理/巩固）实现
6. TeamMemory 与 multi-agent 交互机制

---

## 一、三种记忆类型的区分

Claude Code 存在三种独立的记忆层，彼此正交、作用域不同。

### 1.1 SessionMemory（会话内存）

- **定义**：`source/src/services/SessionMemory/sessionMemory.ts`
- **配置**：`source/src/services/SessionMemory/sessionMemoryUtils.ts:18-36`
- **路径**：`{projectDir}/{sessionId}/session-memory/summary.md`（权限 0o700）
- **格式**：单一 Markdown 文件 `summary.md`
- **生命周期**：
  - 初始化阈值：context tokens > `minimumMessageTokensToInit`（默认 10000）
  - 更新频率：token 增长 > `minimumTokensBetweenUpdate`（5000）或工具调用 > `toolCallsBetweenUpdates`（3）
  - 会话结束后清理（不跨会话）
- **作用域**：单会话、私有；用于当前会话的上下文摘要，由后台 forked subagent 维护

```typescript
// sessionMemoryUtils.ts:18-36
export type SessionMemoryConfig = {
  minimumMessageTokensToInit: number  // 10000
  minimumTokensBetweenUpdate: number  // 5000
  toolCallsBetweenUpdates: number     // 3
}
```

### 1.2 DurableMemory / Auto-Memory（持久化内存）

- **定义**：`source/src/memdir/memoryTypes.ts:14-31`
- **路径解析**：`source/src/memdir/paths.ts:223-235`

```
{memoryBase}/projects/{sanitized-git-root}/memory/
        ├── MEMORY.md         (入口索引，≤200行，≤25KB)
        ├── user_role.md
        ├── feedback_xxx.md
        └── project_xxx.md
```

其中 `memoryBase` 优先级：
1. 环境变量 `CLAUDE_CODE_REMOTE_MEMORY_DIR`（CCR 专用）
2. `~/.claude`（默认）

- **四种记忆类型**（`memoryTypes.ts:14-19`）：

```typescript
export const MEMORY_TYPES = [
  'user',      // 用户角色、偏好、知识
  'feedback',  // 工作指导、最佳实践（Why/How to apply）
  'project',   // 项目状态、目标、截止日期
  'reference', // 外部系统指针（Linear、Grafana等）
]
```

- **文件格式**（`memoryTypes.ts:261-271`）：Markdown + YAML frontmatter

```markdown
---
name: {{memory name}}
description: {{one-line description}}
type: {{user|feedback|project|reference}}
---

{{memory content}}
```

- **生命周期**：跨会话持久化；单用户私有；按 git repo 隔离
- **抽取机制**：`extractMemories`（详见第四节）

### 1.3 TeamMemory（团队共享内存）

- **路径**：`source/src/memdir/teamMemPaths.ts:84-94`

```typescript
export function getTeamMemPath(): string {
  return (join(getAutoMemPath(), 'team') + sep).normalize('NFC')
}
export function getTeamMemEntrypoint(): string {
  return join(getAutoMemPath(), 'team', 'MEMORY.md')
}
```

实际路径：`{memoryBase}/projects/{sanitized-project-root}/memory/team/`

- **关键点**：TeamMemory **按 repo 划分（repo-scoped），不按 team 名划分**。
  同一个 repo 下，所有 team、所有 agent 访问的都是同一个 `team/` 目录。
- **启用条件**（`teamMemPaths.ts:73-78`）：

```typescript
export function isTeamMemoryEnabled(): boolean {
  if (!isAutoMemoryEnabled()) return false
  return getFeatureValue_CACHED_MAY_BE_STALE('tengu_herring_clock', false)
}
```

- **同步语义**：通过 Anthropic API 在组织成员间同步（详见第六节）

### 1.4 三层对比总表

| 维度 | SessionMemory | DurableMemory (Auto) | TeamMemory |
|------|---------------|---------------------|------------|
| 作用域 | 单会话 | 单用户、单 repo | 组织、单 repo |
| 持久化 | 会话结束删除 | 永久 | 永久 + 云端同步 |
| 存储路径 | `{projectDir}/{sessionId}/session-memory/summary.md` | `~/.claude/projects/{repo}/memory/` | `~/.claude/projects/{repo}/memory/team/` |
| 文件数 | 1 个 summary.md | 多个 `.md` + MEMORY.md 索引 | 多个 `.md` + MEMORY.md 索引 |
| 格式 | 纯 Markdown | frontmatter + Markdown | frontmatter + Markdown |
| 维护方 | 后台 subagent | 后台 subagent (extractMemories) | 用户/subagent + 云端 sync |
| 同步机制 | 无（内存对象 + 磁盘） | 无（仅本地） | HTTP ETag + sha256 delta push |
| 权限模型 | 0o700 私有 | 单用户私有 | 组织成员 OAuth |

---

## 二、Relevant Memory Retrieval 完整流程

### 2.1 关键结论（最重要）

Claude Code 2.1.88 的记忆召回**不使用 embedding、向量化、cosine 相似度、BM25 或 hybrid 搜索**。

它采用的是：**纯 LLM 语义选择 + Manifest 文本索引** 方案。

对整个 `source/src/memdir` 目录执行 `grep -r "embedding|vector|cosine|hybrid|rerank|bm25"` 返回**零匹配**。

### 2.2 核心文件

| 文件 | 功能 |
|------|------|
| `source/src/query.ts:302` | Prefetch 触发点 |
| `source/src/utils/attachments.ts:2361-2424` | `startRelevantMemoryPrefetch` |
| `source/src/utils/attachments.ts:2196-2242` | `getRelevantMemoryAttachments` |
| `source/src/memdir/findRelevantMemories.ts` | 主召回流程 |
| `source/src/memdir/memoryScan.ts` | 文件扫描 + manifest 生成 |
| `source/src/utils/attachments.ts:2279-2323` | `readMemoriesForSurfacing` |
| `source/src/query.ts:1600-1615` | 消费点（注入上下文） |

### 2.3 触发时机

在每个用户 turn 的最开始（`query.ts:302`），作为**异步后台任务**启动，与主模型 streaming + 工具执行并行。

```typescript
// query.ts:302
using pendingMemoryPrefetch = startRelevantMemoryPrefetch(
  state.messages,
  state.toolUseContext,
)
```

### 2.4 触发条件（`attachments.ts:2361-2424`）

```typescript
export function startRelevantMemoryPrefetch(messages, toolUseContext) {
  if (!isAutoMemoryEnabled() || !getFeatureValue_CACHED_MAY_BE_STALE('tengu_moth_copse', false))
    return undefined
  const lastUserMessage = messages.findLast(m => m.type === 'user' && !m.isMeta)
  if (!lastUserMessage) return undefined
  const input = getUserMessageText(lastUserMessage)
  if (!input || !/\s/.test(input.trim())) return undefined   // 需要 ≥2 词
  const surfaced = collectSurfacedMemories(messages)
  if (surfaced.totalBytes >= RELEVANT_MEMORIES_CONFIG.MAX_SESSION_BYTES) return undefined
  // 启动异步 promise...
}
```

条件：
1. Auto memory 启用
2. feature gate `tengu_moth_copse` 开启
3. 存在真实用户消息（非 meta）
4. 输入至少 2 个词（需要足够语义）
5. 会话累计注入 memory 字节 < 60KB

### 2.5 三阶段 Pipeline

#### Stage 1：`scanMemoryFiles`（`memoryScan.ts:35-77`）

1. 递归读取 memory 目录下所有 `.md` 文件（**排除** `MEMORY.md`）
2. 并行读取每个文件**前 30 行**（frontmatter）
3. 解析 frontmatter 获得 `description` / `type`
4. 按 `mtimeMs` 降序排序，最多保留 200 个

输出 `MemoryHeader[]`：

```typescript
type MemoryHeader = {
  filename: string
  filePath: string
  mtimeMs: number
  description: string | null
  type: 'user'|'feedback'|'project'|'reference' | undefined
}
```

#### Stage 2：`selectRelevantMemories`（`findRelevantMemories.ts:77-141`）

**LLM 驱动的语义选择**，核心是 `formatMemoryManifest` 生成文本索引，交给 Sonnet 判断。

```typescript
// manifest 示例
- [user] user_role.md (2026-03-15T10:45:23Z): Senior Go engineer, new to React
- [feedback] testing_policy.md (2026-03-14T09:20:00Z): Don't mock database in tests
- [project] sprint_status.md (2026-03-10T14:32:15Z): Mobile release frozen 2026-03-15
```

**Sonnet sideQuery 调用**：

```typescript
const result = await sideQuery({
  model: getDefaultSonnetModel(),           // claude-3-5-sonnet
  system: SELECT_MEMORIES_SYSTEM_PROMPT,
  messages: [{ role: 'user', content: `Query: ${query}\n\nAvailable memories:\n${manifest}${toolsSection}` }],
  max_tokens: 256,
  output_format: {
    type: 'json_schema',
    schema: { type: 'object', properties: { selected_memories: { type: 'array', items: { type: 'string' } } }, required: ['selected_memories'] },
  },
  querySource: 'memdir_relevance',
})
```

**System Prompt**（`findRelevantMemories.ts:18-24`）：

> You are selecting memories that will be useful to Claude Code as it processes a user's query. You will be given the user's query and a list of available memory files with their filenames and descriptions.
>
> Return a list of filenames for the memories that will clearly be useful to Claude Code as it processes the user's query (up to 5). Only include memories that you are certain will be helpful based on their name and description.
>
> - If you are unsure if a memory will be useful, do not include it. Be selective and discerning.
> - If there are no memories that would clearly be useful, return an empty list.
> - If recently-used tools is provided, do not select memories that are usage reference or API documentation for those tools (Claude Code is already exercising them). DO still select memories containing warnings, gotchas, or known issues about those tools.

#### Stage 3：`readMemoriesForSurfacing`（`attachments.ts:2279-2323`）

读取被选中的文件，应用截断：
- 单文件 ≤ 200 行
- 单文件 ≤ 4KB
- 超过上限时 append `> This memory file was truncated ...`

### 2.6 消费与注入（`query.ts:1600-1615`）

```typescript
if (pendingMemoryPrefetch && pendingMemoryPrefetch.settledAt !== null &&
    pendingMemoryPrefetch.consumedOnIteration === -1) {
  const memoryAttachments = filterDuplicateMemoryAttachments(
    await pendingMemoryPrefetch.promise,
    toolUseContext.readFileState,  // 已读文件跳过
  )
  for (const memAttachment of memoryAttachments) {
    const msg = createAttachmentMessage(memAttachment)
    yield msg
    toolResults.push(msg)
  }
}
```

`messages.ts:3708-3722` 将 attachment 转为带 `<system-reminder>` 包裹的 user message（`isMeta:true`）。

**Memory 头部格式**（`attachments.ts:2327-2332`）：
- 新文件：`Memory (saved 3 days ago): /path/to/file.md:`
- 陈旧文件（> 1 天）：前置陈旧性警告

```
This memory is 5 days old. Memories are point-in-time observations, not live state
— claims about code behavior or file:line citations may be outdated. Verify against
current code before asserting as fact.

Memory: /home/user/.claude/projects/my-repo/memory/sprint_status.md:
```

### 2.7 MEMORY.md 的角色

关键区分：
- **MEMORY.md**：在 System Prompt 中**静态总是加载**，作为"目录索引"（ToC），由 `loadMemoryPrompt()` → `buildMemoryPrompt()` 同步加载
- **findRelevantMemories**：**运行时动态选择**具体内容文件，**排除** MEMORY.md

```typescript
// findRelevantMemories.ts:31
// Excludes MEMORY.md (already loaded in system prompt).
```

限制：`memdir.ts:34-38`：`MAX_ENTRYPOINT_LINES=200`, `MAX_ENTRYPOINT_BYTES=25000`。

### 2.8 多层过滤与去重

| 层 | 位置 | 作用 |
|----|------|------|
| alreadySurfaced | `findRelevantMemories.ts:46-48` | 过滤已注入过的 memory |
| readFileState | `query.ts:1605-1608` | 用户已 Read 过的跳过 |
| recentTools | `attachments.ts:2465-2503` | 最近成功工具的文档不选 |
| MAX_SESSION_BYTES | `attachments.ts:2384-2386` | 会话累计 60KB 上限 |
| 单文件行/字节 | `readMemoriesForSurfacing` | 200 行 / 4KB |

### 2.9 性能特征

| 指标 | 值 |
|------|-----|
| Prefetch 延迟 | ~100–500ms（Sonnet sideQuery） |
| 隐藏率 | ~98%（首次迭代前完成） |
| Per-turn 注入上限 | 20KB（5 files × 4KB） |
| Session 总上限 | 60KB |
| 扫描上限 | 200 files |
| 选择上限 | 最多 5 个 |

### 2.10 完整调用图

```
query.ts:302
└─ startRelevantMemoryPrefetch()                [attachments.ts:2361]
   └─ getRelevantMemoryAttachments()            [attachments.ts:2196]
      └─ findRelevantMemories()                  [findRelevantMemories.ts:39]
         ├─ scanMemoryFiles()                    [memoryScan.ts:35]
         │    └─ readdir + parseFrontmatter + sort(mtime)
         ├─ selectRelevantMemories()             [findRelevantMemories.ts:77]
         │    ├─ formatMemoryManifest()          [memoryScan.ts:84]
         │    ├─ collectRecentSuccessfulTools()  [attachments.ts:2465]
         │    ├─ sideQuery(Sonnet, json_schema)  [sideQuery.ts:107]
         │    └─ jsonParse + validate
         └─ readMemoriesForSurfacing()           [attachments.ts:2279]
              └─ readFileInRange(≤200 lines, ≤4KB)
                 + memoryHeader + freshness warning

query.ts:1600-1615
└─ 消费 prefetch → filterDuplicate → yield attachment message
```

---

## 三、记忆召回机制：是 RAG 还是纯 search pattern？

### 3.1 最终答案

**既不是 RAG（embedding + hybrid），也不是"LLM 生成 search pattern → grep/rg"。**

真实做法是：**LLM 直接阅读 manifest 文本索引做语义分类**。

### 3.2 详细对比

| 做法 | 是否在源码中 | 说明 |
|------|------------|------|
| Embedding + 向量相似度 | ❌ 完全没有 | 全目录搜索 `embedding/vector/cosine/bm25/rerank/hybrid` 零命中 |
| LLM 生成 search pattern → grep/rg 召回 | ❌ 没有 | 没有基于 grep/ripgrep 的 memory 搜索路径 |
| LLM 读 manifest 做分类 | ✅ 是的 | 见 `findRelevantMemories.ts:77-141` |

### 3.3 为什么选择这种架构

1. **零初始化成本**：不需要 embedding 模型、向量数据库
2. **实时灵活**：新加的 memory 文件立刻可选，无需重建索引
3. **成本低**：Sonnet sideQuery 通常只消耗几百 tokens
4. **可解释性好**：Sonnet 可以"理解"上下文语义、tool 活动、陈旧度等多维信号
5. **召回精度可接受**：依赖 LLM 对 `description` 的语义理解，比固定向量相似度更灵活

### 3.4 过程细节（关键一点不漏）

1. `memoryScan.ts` 扫描 `~/.claude/.../memory/*.md`，读前 30 行 frontmatter
2. `formatMemoryManifest` 生成带类型、时间戳、description 的清单文本
3. `collectRecentSuccessfulTools` 收集用户最近一轮成功使用的工具名
4. `sideQuery` 发请求给 Claude Sonnet，使用 `json_schema` 强制结构化输出 `{ selected_memories: string[] }`
5. 结果反解析，过滤非法文件名
6. 被选中的文件用 `readFileInRange(filePath, 0, 200, 4096)` 读取
7. 拼 `memoryHeader`（带 `memoryFreshnessText` 陈旧警告）
8. 注入为 `isMeta:true` 的 user message，外层包 `<system-reminder>`

**从头到尾没有向量化、没有 grep 搜索 memory 内容**。

---

## 四、Extract Memories：从对话抽取记忆写回

### 4.1 核心文件

| 文件 | 功能 |
|------|------|
| `source/src/query/stopHooks.ts:136-152` | 触发点 |
| `source/src/services/extractMemories/extractMemories.ts` | 抽取主逻辑 |
| `source/src/services/extractMemories/prompts.ts` | Prompt 模板 |
| `source/src/memdir/paths.ts:69-77` | `isExtractModeActive` |

### 4.2 触发时机

在每个 query 循环结束时由 `stopHooks` 触发：

```typescript
// query/stopHooks.ts:141-152
if (
  feature('EXTRACT_MEMORIES') &&
  !toolUseContext.agentId &&        // 仅主会话运行，subagent 跳过
  isExtractModeActive()
) {
  void extractMemoriesModule!.executeExtractMemories(
    stopHookContext,
    toolUseContext.appendSystemMessage,
  )
}
```

### 4.3 启用门控

```typescript
// memdir/paths.ts:69-77
export function isExtractModeActive(): boolean {
  if (!getFeatureValue_CACHED_MAY_BE_STALE('tengu_passport_quail', false)) return false
  return (
    !getIsNonInteractiveSession() ||
    getFeatureValue_CACHED_MAY_BE_STALE('tengu_slate_thimble', false)
  )
}
```

| Gate | 作用 | 默认值 |
|------|------|-------|
| `EXTRACT_MEMORIES` | 编译时 feature flag | — |
| `tengu_passport_quail` | 总开关 | false |
| `tengu_slate_thimble` | 非交互式会话是否运行 | false |
| `tengu_bramble_lintel` | 节流：每 N turns 运行一次 | 1（每次） |

### 4.4 执行流程（闭包状态机）

关键闭包状态（`extractMemories.ts:297-325`）：
- `lastMemoryMessageUuid`：游标，上次处理到的消息 UUID
- `inFlightExtractions`：飞行中的 Promise 集合
- `inProgress`：互斥标志
- `pendingContext`：重叠调用时的尾部上下文
- `turnsSinceLastExtraction`：节流计数

主流程（`extractMemories.ts:329-523`）：

1. **计数新消息**：`countModelVisibleMessagesSince(messages, lastMemoryMessageUuid)`
2. **互斥检查**：`hasMemoryWritesSince(messages, lastMemoryMessageUuid)`
   - 如果主代理已在本轮内用 Write/Edit 写了 memory 文件 → 跳过（避免重复写）
   - 游标推进到最新消息
3. **扫描现存 memory**：`scanMemoryFiles` → `formatMemoryManifest` → 注入到 prompt，避免 agent 自行 `ls`
4. **构建 prompt**：
   - `buildExtractAutoOnlyPrompt` 或 `buildExtractCombinedPrompt`（teamMem 启用时）
5. **启动 forked agent**：

```typescript
const result = await runForkedAgent({
  promptMessages: [createUserMessage({ content: userPrompt })],
  cacheSafeParams: createCacheSafeParams(context),
  canUseTool: createAutoMemCanUseTool(memoryRoot),
  querySource: 'extract_memories',
  forkLabel: 'extract_memories',
  skipTranscript: true,     // 不记录到主 transcript
  maxTurns: 5,              // 硬上限
})
```

6. **游标推进**：成功后更新 `lastMemoryMessageUuid`，失败不推进（下次重试）
7. **尾部运行**：运行期间的新请求存入 `pendingContext`，完成后立即重跑一次

### 4.5 工具权限（`extractMemories.ts:154-222`）

`createAutoMemCanUseTool` 严格限制：

允许：
- Read、Grep、Glob（无条件）
- Bash（仅 `isReadOnly` 命令：`ls/find/cat/stat/wc/head/tail/grep` 等）
- Edit / Write（**仅限** `isAutoMemPath()` 内）

禁止：
- 所有可写 Bash（`rm/wget/git push` 等）
- MCP 工具
- Agent 工具
- 所有其他写工具

### 4.6 Prompt 关键摘录（`prompts.ts:29-44`）

> You are now acting as the memory extraction subagent. Analyze the most recent ~${newMessageCount} messages above and use them to update your persistent memory systems.
>
> ## Existing memory files
>
> [type] filename (timestamp): description
> ...
> Check this list before writing — update an existing file rather than creating a duplicate.
>
> Available tools: Read, Grep, Glob, read-only Bash, and Edit/Write for memory paths only.
> You have a limited turn budget. Efficient strategy: Turn 1 — read all files; Turn 2 — write all edits in parallel.
> You MUST only use content from the last ~${newMessageCount} messages. Do not waste turns investigating further.

### 4.7 抽取什么（按 4 类记忆）

| 类型 | 抽取内容 |
|------|---------|
| user | 用户角色、偏好、背景知识、权限 |
| feedback | 纠正（stop doing X）+ 确认（keep doing Y）+ **Why/How to apply** |
| project | 进度、deadline、stakeholder、**Why/How to apply**（相对日期转绝对日期） |
| reference | 外部系统指针（Linear 项目、Grafana dashboard、Slack channel） |

### 4.8 不抽取的内容（`memoryTypes.ts:183-195`）

- 代码模式、架构、文件路径、项目结构
- Git 历史
- 调试配方（commit message 已有）
- CLAUDE.md 中已有的内容
- 临时任务状态

### 4.9 写入步骤

- **标准模式（skipIndex=false）**：
  1. 写主题文件（带 frontmatter）
  2. 在 MEMORY.md 加一行指针：`- [Title](file.md) — one-line hook`
- **简化模式（skipIndex=true）**：
  1. 只写主题文件，索引由其他过程更新

### 4.10 与 /compact 的关系

**完全无关**。
- `source/src/commands/compact/compact.ts` 中不调用 `executeExtractMemories` 或 `executeAutoDream`
- Compact 有自己的 `trySessionMemoryCompaction`（用于 SessionMemory）
- Memory extraction 是独立的持久化维度，compact 只做对话历史压缩

---

## 五、Auto Dream / Consolidation（自动整理）

### 5.1 存在性确认

**存在且完整**。Auto Dream 是一个后台的定期 memory 整理机制，负责去重、合并、更新、修剪、索引维护。

### 5.2 核心文件

| 文件 | 功能 |
|------|------|
| `source/src/services/autoDream/autoDream.ts` | 主入口、门控、task UI |
| `source/src/services/autoDream/consolidationPrompt.ts` | Four-Phase prompt |
| `source/src/services/autoDream/consolidationLock.ts` | Lock 文件 + 时间戳 |
| `source/src/services/autoDream/config.ts` | 门控配置 |

### 5.3 启用门控链（`autoDream.ts:95-107`）

```typescript
function isGateOpen(): boolean {
  if (getKairosActive()) return false       // KAIROS 有独立 /dream
  if (getIsRemoteMode()) return false       // 远程禁用
  if (!isAutoMemoryEnabled()) return false  // 依赖 auto memory
  return isAutoDreamEnabled()               // settings 或 tengu_onyx_plover
}
```

GrowthBook flag `tengu_onyx_plover` 类型：
```typescript
{ enabled?: boolean, minHours?: number, minSessions?: number }
默认: { enabled: false, minHours: 24, minSessions: 5 }
```

### 5.4 三级节流门控（`autoDream.ts:130-171`）

1. **时间门控**：自上次整理以来 ≥ `minHours`（默认 24h）
2. **扫描节流**：`SESSION_SCAN_INTERVAL_MS = 10 分钟`，避免频繁扫会话目录
3. **会话门控**：自上次整理以来新增/修改的会话数 ≥ `minSessions`（默认 5），排除当前会话
4. **Lock 门控**：`tryAcquireConsolidationLock()`，失败（另一进程持锁）则跳过

### 5.5 触发点

与 extractMemories 同一位置（`query/stopHooks.ts:154-156`）：

```typescript
if (!toolUseContext.agentId) {
  void executeAutoDream(stopHookContext, toolUseContext.appendSystemMessage)
}
```

### 5.6 执行流程（`autoDream.ts:125-272`）

1. **注册 Dream 任务**：`registerDreamTask()`，在底部 nav 和 Shift+Down 对话框可见
2. **构建 prompt**：`buildConsolidationPrompt(memoryRoot, transcriptDir, extra)`
3. **启动 forked agent**：

```typescript
const result = await runForkedAgent({
  promptMessages: [createUserMessage({ content: prompt })],
  cacheSafeParams: createCacheSafeParams(context),
  canUseTool: createAutoMemCanUseTool(memoryRoot),  // 同 extractMemories 权限
  querySource: 'auto_dream',
  forkLabel: 'auto_dream',
  skipTranscript: true,
  overrides: { abortController },
  onMessage: makeDreamProgressWatcher(taskId, setAppState),
})
```

4. **实时进度监视**（`autoDream.ts:281-313`）：
   - 从 assistant messages 提取文本块和工具使用
   - 收集 Edit/Write 的文件路径
   - 实时更新 UI task
5. **完成/失败处理**：
   - 成功：`completeDreamTask()` + "Improved N memories" 内联消息
   - 失败：`failDreamTask()` + `rollbackConsolidationLock(priorMtime)` 回滚 lock mtime

### 5.7 Four-Phase Prompt（`consolidationPrompt.ts:10-65`）

> # Dream: Memory Consolidation
>
> ## Phase 1 — Orient
> - ls the memory directory to see what already exists
> - Read MEMORY.md to understand the current index
> - Skim existing topic files
>
> ## Phase 2 — Gather recent signal
> 1. Daily logs (logs/YYYY/MM/YYYY-MM-DD.md) if present
> 2. Existing memories that drifted
> 3. Transcript search (grep narrowly — `grep -rn "<term>" ${transcriptDir}/ | tail -50`)
>
> ## Phase 3 — Consolidate
> - Merge new signal into existing topic files, not near-duplicates
> - Convert relative dates to absolute (e.g., "yesterday" → "2026-03-15")
> - Delete contradicted facts
>
> ## Phase 4 — Prune and index
> - Update MEMORY.md: stay under 200 lines and 25KB
> - Each entry: one line under ~150 chars: `- [Title](file.md) — one-line hook`
> - Remove stale pointers
> - Resolve contradictions
>
> **Tool constraints:** Bash is restricted to read-only commands (ls, find, grep, cat, stat, wc, head, tail, and similar).

### 5.8 Lock 机制（`consolidationLock.ts`）

Lock 文件 `.consolidate-lock` 的 `mtime` **就是** `lastConsolidatedAt`（一文件两用途）：

```typescript
export async function readLastConsolidatedAt(): Promise<number> {
  try { const s = await stat(lockPath()); return s.mtimeMs }
  catch { return 0 }
}

export async function tryAcquireConsolidationLock(): Promise<number | null> {
  // HOLDER_STALE_MS = 1 小时；PID 检查活跃性
  // 并发竞争：读 mtime → 写 PID → 再读验证 → 赢者继续
}

export async function rollbackConsolidationLock(priorMtime: number) {
  // dream 失败时倒回 mtime，使时间门控下次再次通过
  // priorMtime=0 → unlink
}
```

---

## 六、TeamMemory 与 Multi-Agent 交互

### 6.1 TeamMemory 路径规则

| 规则 | 细节 |
|------|------|
| 按 repo 划分 | `~/.claude/projects/{sanitized-project-root}/memory/team/` |
| **不按 team 名划分** | 多个 team 在同一 repo 下共享同一目录 |
| 入口 | `team/MEMORY.md` |
| 启用 | `isAutoMemoryEnabled() && tengu_herring_clock` |

### 6.2 多层安全防护（`teamMemPaths.ts:183-256`）

```typescript
export async function validateTeamMemWritePath(filePath: string): Promise<string> {
  const resolvedPath = resolve(filePath)
  const teamDir = getTeamMemPath()
  if (!resolvedPath.startsWith(teamDir)) throw new PathTraversalError(...)

  const realPath = await realpathDeepestExisting(resolvedPath)
  if (!(await isRealPathWithinTeamDir(realPath))) throw new PathTraversalError(...)

  return resolvedPath
}
```

防护项：
1. 路径归一化消除 `..`
2. `realpath()` 对最深现存祖先解析，防 symlink 逃逸
3. null byte、URL 编码、Unicode 归一化检查
4. `validateTeamMemKey` 检查相对 key 合法性

### 6.3 Subagent 上下文隔离（`utils/agentContext.ts:32-85`）

通过 `AsyncLocalStorage` 在同进程内隔离：

```typescript
export type SubagentContext = {
  agentId: string
  parentSessionId?: string
  agentType: 'subagent'
  subagentName?: string
  isBuiltIn?: boolean
  invokingRequestId?: string
  invocationKind?: 'spawn' | 'resume'
  invocationEmitted?: boolean
}

export type TeammateAgentContext = {
  agentId: string              // e.g. "researcher@my-team"
  agentName: string
  teamName: string             // 关键
  planModeRequired: boolean
  parentSessionId: string
  isTeamLead: boolean
  agentType: 'teammate'
}
```

关键点：**TeamMemory 不通过 context 显式传递**，因其路径是 repo-scoped 函数 `getTeamMemPath()`，所有 agent 算出同一路径，天然共享。

### 6.4 系统提示中注入 TeamMemory 指引（`teamMemPrompts.ts:22-100`）

`buildCombinedMemoryPrompt` 在 auto + team 都启用时生成两个目录并列的 prompt：

```
- private: 私有内存位于 <autoDir>
- team:    共享团队内存位于 <teamDir>

Subagent/Teammate 可读写两个目录
```

### 6.5 Agent Memory vs TeamMemory（正交）

`source/src/tools/AgentTool/agentMemory.ts`：

```typescript
export type AgentMemoryScope = 'user' | 'project' | 'local'
// ~/.claude/agent-memory/<agentType>/      (user)
// .claude/agent-memory/<agentType>/         (project)
// .claude/agent-memory-local/<agentType>/   (local)
```

差异：
- Agent Memory：按 **agent 类型**（Explore/Researcher 等）分离，提示/工作记忆
- TeamMemory：按 **repo** 共享，所有 agent 通用

### 6.6 权限拦截（`utils/teamMemoryOps.ts`）

```typescript
export function isTeamMemoryWriteOrEdit(toolName, toolInput): boolean {
  if (toolName !== FILE_WRITE_TOOL_NAME && toolName !== FILE_EDIT_TOOL_NAME) return false
  const filePath = (toolInput as any)?.file_path ?? (toolInput as any)?.path
  return filePath !== undefined && isTeamMemFile(filePath)
}
```

Subagent 可读可写；写入时触发 `notifyTeamMemoryWrite()` → watcher 检测 → 2s debounce → push。

### 6.7 TeamCreate / TeamDelete 工具

#### TeamCreate（`tools/TeamCreateTool/TeamCreateTool.ts:128-237`）

流程：
1. 检查 lead 是否已在另一 team 中
2. 生成唯一 team 名
3. 写 TeamFile 到 `~/.claude/teams/<name>/config.json`
4. 初始化 task list 目录 `~/.claude/tasks/<taskListId>/`
5. 更新 `AppState.teamContext`

**注意**：**不创建 TeamMemory 目录**，因 TeamMemory 是 repo-scoped，已自动存在。

#### TeamDelete（`tools/TeamDeleteTool/TeamDeleteTool.ts:71-135`）

流程：
1. 检查是否有活跃成员，活跃则拒绝
2. 清理 `~/.claude/teams/<name>/` 和 tasks 目录
3. 清除 AppState.teamContext 和 inbox

**注意**：**不删除 TeamMemory**（TeamMemory 可能被其他 team 使用或需同步到服务端）。

### 6.8 TeamMemory Sync 机制（核心）

#### API 合约（`services/teamMemorySync/index.ts`）

```
GET  /api/claude_code/team_memory?repo={owner/repo}              → TeamMemoryData（全量）
GET  /api/claude_code/team_memory?repo={owner/repo}&view=hashes  → metadata only（轻量）
PUT  /api/claude_code/team_memory?repo={owner/repo}              → upload delta
```

#### SyncState（`types.ts`）

```typescript
export type SyncState = {
  lastKnownChecksum: string | null         // ETag
  serverChecksums: Map<string, string>     // 每 key 的 sha256:<hex>
  serverMaxEntries: number | null          // 从 413 学习的上限
}
```

#### 语义

- **Pull**：服务器赢，本地被覆盖
- **Push**：Delta（只上传 hash 不同的 key）
- **限制**：单文件 ≤ 250KB；单次 PUT ≤ 200KB（分批）
- **删除**：**文件删除不同步**（下次 pull 会恢复）

#### Watcher（`services/teamMemorySync/watcher.ts`）

- `fs.watch` 监听 `team/` 目录
- Debounce：2000ms（`DEBOUNCE_MS`）
- 推送期间的编辑记为 `hasPendingChanges`，完成后重排
- 永久失败处理：`no_oauth` / `no_repo` / 4xx（除 409/429）停止重试，记录 reason

#### 冲突解决

- 412 Precondition Failed：用 `?view=hashes` 轻量刷新 `serverChecksums`，重新计算 delta（自动排除已与服务端一致的 key），重试
- 413：从响应中学习 `serverMaxEntries`
- 重试策略：`MAX_RETRIES=3`，`MAX_CONFLICT_RETRIES=2`

#### Secret 扫描（`services/teamMemorySync/secretScanner.ts`）

- 规则：Gitleaks rule IDs
- 时机：Push 前扫描，含 secret 的文件跳过
- 日志：只记录相对路径 + ruleId，**从不记录 secret 值**

### 6.9 TeamMemory 如何实现多 agent 通信

在 repo-scoped 共享目录下，agent 通过写入特定文件实现异步通信：
- Agent A 写入 `team/plan.md`
- Watcher 2s 后 push 到服务端
- 同组织其他机器启动时 pull，或实时 polling，获得 A 的内容
- Agent B 读取 `team/plan.md` → 获得信息

**关键特征**：
- 无显式 mutex/semaphore
- 依赖 HTTP ETag + sha256 乐观锁
- 并发推送 → 412 → 刷新 hashes → delta 中自动排除一致 key → 重推
- 文件级覆盖（无字段级 merge）

### 6.10 Lead → Subagent → Teammate 交互全链路

```
┌─ Lead Agent (Session A) ────────────────────────────┐
│ 1. TeamCreate("my-team") → TeamFile + TaskList     │
│ 2. AppState.teamContext 设置                        │
│ 3. 启动 TeamMemory watcher                          │
│    - 初始 pull 拉取服务端                           │
│    - fs.watch 监听本地                              │
│    - 2s debounce → push delta                       │
└──────────────┬──────────────────────────────────────┘
               │ AgentTool.call({subagent_type, prompt})
               ▼
┌─ Subagent (in-process, AsyncLocalStorage) ─────────┐
│ 1. 继承 parentSessionId                              │
│ 2. 系统提示含 buildCombinedMemoryPrompt()            │
│ 3. 对 team/ 的读/写：                                │
│    - Read/Grep/Glob：直接读                          │
│    - Edit/Write：触发 notifyTeamMemoryWrite         │
│      → watcher 检测 → 2s 后 push                    │
└──────────────┬──────────────────────────────────────┘
               │ 可选：SpawnTeammate({name, prompt, team_name})
               ▼
┌─ Teammate (in-process, AsyncLocalStorage) ─────────┐
│ 1. TeammateAgentContext: {agentId, teamName, ...}  │
│ 2. initializeTeammateHooks 注册 Stop hook           │
│ 3. 系统提示同上（team/ 完全可用）                   │
│ 4. 通过 SendMessageTool 与 lead/其他 teammate 通信  │
└──────────────┬──────────────────────────────────────┘
               │ 所有 agent 的编辑流向同一 watcher
               ▼
┌─ TeamMemory Watcher (per session 单例) ─────────────┐
│ executePush():                                       │
│  (a) 读 team/ 所有文件                               │
│  (b) 计算 sha256 hash                                │
│  (c) 与 serverChecksums 比 → delta                  │
│  (d) 分批 PUT（200KB/批）                            │
│  (e) 412 冲突：GET ?view=hashes → 重算 delta → 重试 │
└──────────────┬──────────────────────────────────────┘
               ▼
┌─ Anthropic API (Team Memory Service) ───────────────┐
│ 响应：200 / 304 / 404 / 412 / 413                   │
└──────────────────────────────────────────────────────┘
```

### 6.11 并发安全的设计决策

| 设计 | 原因 |
|------|-----|
| 无显式锁 | repo-scoped，并发几乎不同文件 |
| ETag 乐观锁 | HTTP 级冲突检测 |
| Delta + sha256 | 同内容并发 push 自动对齐 |
| Debounce 2s | 合并短时间内多次写入 |
| 无字段级 merge | 简单可预测；"local wins with delta" |

---

## 七、关键 Feature Gates 汇总

| Gate | 位置 | 作用 | 默认 |
|------|------|------|------|
| `EXTRACT_MEMORIES` | 编译时 | 启用 extractMemories 模块 | — |
| `tengu_passport_quail` | GrowthBook | 主提取总开关 | false |
| `tengu_slate_thimble` | GrowthBook | 非交互会话启用提取 | false |
| `tengu_bramble_lintel` | GrowthBook | 提取节流：每 N turns 1 次 | 1 |
| `tengu_moth_copse` | GrowthBook | Relevant memory prefetch | false |
| `tengu_onyx_plover` | GrowthBook | auto dream 启用 + 阈值 | `{enabled:false, minHours:24, minSessions:5}` |
| `tengu_herring_clock` | GrowthBook | TeamMemory 启用 | false |
| `KAIROS` | 编译时 | assistant 模式（独立 /dream） | — |
| `TEAMMEM` | 编译时 | teamMemory 模块 | — |
| `isAutoMemoryEnabled` | settings | auto memory 总开关 | true |
| `autoDreamEnabled` | settings | override tengu_onyx_plover.enabled | undefined |
| `MEMORY_SHAPE_TELEMETRY` | 编译时 | 记录召回 shape telemetry | — |

---

## 八、核心文件索引（快速查阅表）

### Memory 基础
| 文件 | 作用 |
|------|------|
| `memdir/memoryTypes.ts` | 4 类记忆定义 + frontmatter 格式 |
| `memdir/paths.ts` | Auto-Memory 路径解析 + 门控 |
| `memdir/teamMemPaths.ts` | TeamMemory 路径 + 安全验证 |
| `memdir/memdir.ts` | MEMORY.md 入口加载 |
| `memdir/memoryScan.ts` | 扫描 + manifest |
| `memdir/memoryAge.ts` | 陈旧警告 |
| `memdir/findRelevantMemories.ts` | 召回主流程 |

### Session Memory
| 文件 | 作用 |
|------|------|
| `services/SessionMemory/sessionMemory.ts` | 核心 |
| `services/SessionMemory/sessionMemoryUtils.ts` | 配置 |
| `utils/permissions/filesystem.ts` | 路径定义 |

### Extract + Dream
| 文件 | 作用 |
|------|------|
| `services/extractMemories/extractMemories.ts` | 抽取主逻辑 |
| `services/extractMemories/prompts.ts` | 抽取 prompt |
| `services/autoDream/autoDream.ts` | 整理主逻辑 |
| `services/autoDream/consolidationPrompt.ts` | 4-Phase prompt |
| `services/autoDream/consolidationLock.ts` | Lock + mtime |
| `services/autoDream/config.ts` | 门控配置 |
| `query/stopHooks.ts` | 触发点 |

### Team Memory Sync
| 文件 | 作用 |
|------|------|
| `services/teamMemorySync/index.ts` | Sync API |
| `services/teamMemorySync/types.ts` | 数据结构 |
| `services/teamMemorySync/watcher.ts` | 文件监听 |
| `services/teamMemorySync/secretScanner.ts` | Secret 扫描 |
| `memdir/teamMemPrompts.ts` | 组合 prompt |

### Multi-Agent / Team
| 文件 | 作用 |
|------|------|
| `utils/agentContext.ts` | SubagentContext / TeammateAgentContext |
| `utils/swarm/spawnInProcess.ts` | In-process spawn |
| `utils/swarm/teamHelpers.ts` | TeamFile 结构 |
| `utils/swarm/spawnUtils.ts` | 环境变量转发 |
| `tools/TeamCreateTool/TeamCreateTool.ts` | TeamCreate |
| `tools/TeamDeleteTool/TeamDeleteTool.ts` | TeamDelete |
| `tools/AgentTool/agentMemory.ts` | Agent 专属 memory scope |
| `utils/teamMemoryOps.ts` | 写/编辑拦截 |

### Retrieval 消费
| 文件 | 作用 |
|------|------|
| `query.ts:302` | Prefetch 启动 |
| `query.ts:1600-1615` | 消费注入 |
| `utils/attachments.ts:2196-2503` | 召回封装函数 |
| `utils/messages.ts:3708-3722` | attachment→message 转换 |
| `utils/sideQuery.ts` | Sonnet sideQuery |

---

## 九、最终总结

### 9.1 三种记忆的定位

- **SessionMemory**：当前会话的"工作记忆摘要"，单文件，会话结束即销毁
- **DurableMemory / Auto-Memory**：用户私有的长期知识库，跨会话，按 repo 隔离，由后台 agent 自动维护
- **TeamMemory**：组织共享的长期知识库，repo-scoped，通过 HTTP API + ETag 乐观锁同步

### 9.2 召回机制本质

**LLM-native，非 RAG**。
- Sonnet sideQuery 阅读 manifest（文件名 + 类型 + 时间 + description）→ 返回 JSON `selected_memories`
- 读文件 → 带陈旧性警告注入 → 作为 `isMeta:true` user message + `<system-reminder>`
- **完全没有** embedding / 向量 / cosine / BM25 / hybrid / rerank / grep-based search

### 9.3 写入机制（Extract + Dream）

- **Extract**：每 turn 结束可能运行 forked agent，基于最近消息写入新 memory，互斥防止主 agent 重复写
- **Dream**：每 24 小时 + 5 个新会话阈值触发，4-Phase（Orient / Gather / Consolidate / Prune & Index），维护 MEMORY.md 索引
- 两者共享：权限模型（`createAutoMemCanUseTool`）、`runForkedAgent` + `skipTranscript`、不污染主 transcript

### 9.4 TeamMemory + Multi-Agent

- **路径 repo-scoped**：所有 subagent / teammate 访问同一 `team/` 目录
- **权限共享**：Sub/Teammate 可读可写 TeamMemory，触发 `notifyTeamMemoryWrite` → watcher push
- **同步机制**：ETag + sha256 delta + 2s debounce + 412 自愈
- **通信方式**：通过写入共享文件异步通信（加上 `SendMessageTool` 做实时协调）
- **无锁设计**：依赖乐观锁 + delta 合并

### 9.5 设计哲学

1. **LLM 优先于算法**：用 LLM 语义理解代替向量相似度，避免基础设施复杂度
2. **后台 fork + skipTranscript**：所有记忆维护不污染主对话
3. **Fail-open with rollback**：Lock mtime 机制失败可回滚，让下次重试
4. **分层 feature gate**：编译时 flag + GrowthBook + user settings 多重保险
5. **安全优先**：TeamMemory 的 symlink realpath / secret scanner / 组织 OAuth 多层防护
