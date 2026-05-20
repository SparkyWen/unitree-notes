# Claude Code 2.1.88 记忆系统深度补充分析

> 本文档是 `Memory_details_cc.md` 的补充，专门深度解答三个关键机制问题：
> 1. Manifest 本质与纯 LLM 语义选择
> 2. Frontmatter 由谁、在何时写入，缺失或非 .md 格式如何处理
> 3. Auto Dream 的触发时机与 Four-Phase 实际执行模型

---

## 一、Manifest 到底是什么？纯 LLM 语义选择究竟怎么做？

### 1.1 Manifest 的本质定义

**Manifest 不是文件内容，而是"元数据清单文本"**，由 `formatMemoryManifest()` 动态生成，用于让 Sonnet 做相关性判断。

**核心实现**（`source/src/memdir/memoryScan.ts:84-94`）：

```typescript
export function formatMemoryManifest(memories: MemoryHeader[]): string {
  return memories
    .map(m => {
      const tag = m.type ? `[${m.type}] ` : ''
      const ts = new Date(m.mtimeMs).toISOString()
      return m.description
        ? `- ${tag}${m.filename} (${ts}): ${m.description}`
        : `- ${tag}${m.filename} (${ts})`
    })
    .join('\n')
}
```

**输入**：`MemoryHeader[]`（`memoryScan.ts:13-19`）

```typescript
type MemoryHeader = {
  filename: string          // 相对路径
  filePath: string          // 绝对路径
  mtimeMs: number           // 修改时间
  description: string | null // 来自 frontmatter
  type: MemoryType | undefined
}
```

**输出**：纯文本清单

```
- [user] user_role.md (2026-04-15T10:30:00.000Z): Senior Go engineer, new to React
- [feedback] testing_policy.md (2026-04-14T09:20:00.000Z): Don't mock database
- [project] sprint_status.md (2026-04-10T14:32:15.000Z): Mobile release frozen 2026-03-15
```

### 1.2 Manifest vs Frontmatter：关键区别

| 维度 | Frontmatter | Manifest |
|------|-------------|----------|
| 存在位置 | 每个 memory 文件顶部 | 运行时动态生成，不落盘 |
| 格式 | YAML（`---`包围块） | 纯文本行列表（每行一个文件） |
| 包含内容 | name, description, type | [type] filename (mtime): description |
| 生成时机 | 写文件时由 agent 写入 | 每次 retrieval 触发时重新生成 |
| 作用 | 单文件的元信息 | 所有文件的"目录索引" |

**核心关系**：Manifest 是**对多个 memory 文件 frontmatter 的聚合摘要**，外加运行时信息（`mtimeMs`）。

**Manifest 绝对不包含文件正文**。`scanMemoryFiles()` 只读前 30 行（`FRONTMATTER_MAX_LINES = 30`），而且 `MemoryHeader` 类型里**根本没有 content 字段**。

### 1.3 Manifest 生成的完整流程（一字不漏）

**Step 1：扫描目录**（`memoryScan.ts:35-77`）

```typescript
const entries = await readdir(memoryDir, { recursive: true })
const mdFiles = entries.filter(
  f => f.endsWith('.md') && basename(f) !== 'MEMORY.md',
)
```

关键点：
- 只处理 `.md` 扩展名
- 排除 `MEMORY.md`（它已在 system prompt 中加载）
- 递归扫描子目录

**Step 2：并行读前 30 行**（`memoryScan.ts:48-51`）

```typescript
const { content, mtimeMs } = await readFileInRange(
  filePath, 0, FRONTMATTER_MAX_LINES,  // 30 行
)
```

**Step 3：解析 frontmatter**（`frontmatterParser.ts:130-175`）

```typescript
const { frontmatter } = parseFrontmatter(content, filePath)
return {
  filename: relativePath,
  filePath,
  mtimeMs,
  description: frontmatter.description || null,
  type: parseMemoryType(frontmatter.type),
}
```

**Step 4：按 mtime 降序排序 + 上限 200**（`memoryScan.ts:72-77`）

```typescript
.sort((a, b) => b.mtimeMs - a.mtimeMs)
.slice(0, MAX_MEMORY_FILES)  // MAX_MEMORY_FILES = 200
```

**Step 5：拼文本**（`formatMemoryManifest()`）

得到最终 manifest 字符串。

### 1.4 纯 LLM 语义选择的精确机制（一次 API 调用）

**关键事实：是一次 API 调用，不是两步**。

完整调用发生在 `selectRelevantMemories()`（`findRelevantMemories.ts:77-141`）：

```typescript
async function selectRelevantMemories(
  query: string,
  memories: MemoryHeader[],
  signal: AbortSignal,
  recentTools: readonly string[],
): Promise<string[]> {
  const validFilenames = new Set(memories.map(m => m.filename))
  const manifest = formatMemoryManifest(memories)
  const toolsSection = recentTools.length > 0
    ? `\n\nRecently used tools: ${recentTools.join(', ')}`
    : ''

  const result = await sideQuery({
    model: getDefaultSonnetModel(),
    system: SELECT_MEMORIES_SYSTEM_PROMPT,
    skipSystemPromptPrefix: true,
    messages: [
      { role: 'user',
        content: `Query: ${query}\n\nAvailable memories:\n${manifest}${toolsSection}` },
    ],
    max_tokens: 256,
    output_format: {
      type: 'json_schema',
      schema: {
        type: 'object',
        properties: {
          selected_memories: { type: 'array', items: { type: 'string' } },
        },
        required: ['selected_memories'],
        additionalProperties: false,
      },
    },
    querySource: 'memdir_relevance',
  })

  const textBlock = result.content.find(b => b.type === 'text')
  if (!textBlock) return []
  const parsed = jsonParse(textBlock.text)
  return parsed.selected_memories.filter(f => validFilenames.has(f))
}
```

**Sonnet 完整看到的 prompt 示例**：

```
[System Prompt]
You are selecting memories that will be useful to Claude Code as it
processes a user's query. You will be given the user's query and a list
of available memory files with their filenames and descriptions.

Return a list of filenames for the memories that will clearly be useful
to Claude Code as it processes the user's query (up to 5). Only include
memories that you are certain will be helpful based on their name and
description.
- If you are unsure if a memory will be useful, do not include it. Be
  selective and discerning.
- If there are no memories that would clearly be useful, return an empty list.
- If a list of recently-used tools is provided, do not select memories that
  are usage reference or API documentation for those tools (Claude Code is
  already exercising them). DO still select memories containing warnings,
  gotchas, or known issues about those tools.

[User Message]
Query: How do I configure TypeScript in this project?

Available memories:
- [project] build_setup.md (2026-04-15T10:30:00.000Z): TypeScript compilation flags
- [reference] external_apis.md (2026-04-14T08:15:00.000Z): API documentation links
- [feedback] testing_approach.md (2026-04-10T16:45:00.000Z): Do not use mocks for DB

Recently used tools: Bash, Glob
```

**Sonnet 返回结构化 JSON**：

```json
{ "selected_memories": ["build_setup.md", "testing_approach.md"] }
```

### 1.5 LLM 语义选择 vs RAG：设计哲学对比

**为什么 manifest 不包含正文**？

1. **Token 成本**：最多 200 个文件；若每个带正文平均 4KB，则 800KB，远超上下文
2. **两阶段按需加载**：
   - 阶段 1（廉价）：Sonnet 只读 metadata 做筛选
   - 阶段 2（按需）：主模型拿到被选中的文件后才读完整内容
3. **`max_tokens: 256`**：只需输出 JSON 文件名列表，够用

**为什么不用 embedding**？

- 没有向量数据库，零初始化成本
- 新加的 memory 立刻可选，无需重建索引
- Sonnet 的语义理解能力 > 固定向量相似度（能处理 "recently used tools" 这种复杂条件）
- 可解释、可调试（LLM 的选择有"理由"）

### 1.6 Sonnet 返回了 manifest 中不存在的文件名怎么办？

**防御代码**（`findRelevantMemories.ts:130`）：

```typescript
return parsed.selected_memories.filter(f => validFilenames.has(f))
```

**行为**：
- 构建 `validFilenames = new Set(memories.map(m => m.filename))`
- Sonnet 返回的每个文件名若不在集合里，**静默过滤**
- 不报错、不记录警告
- 后续流程只处理合法文件名

### 1.7 Manifest 核心小结

| 问题 | 答案 |
|------|------|
| Manifest 是文件还是 string？ | 运行时生成的 string，不落盘 |
| 和 frontmatter 是啥关系？ | Manifest = 多文件 frontmatter 的聚合摘要 + mtimeMs |
| 包含正文吗？ | 绝对不包含 |
| 一次 API 还是两次？ | 一次 sideQuery → Sonnet 返回 JSON |
| 选了正文哪里读？ | Sonnet 返回后，`readMemoriesForSurfacing` 再读完整内容 |
| 无效文件名处理？ | `validFilenames.has()` 静默过滤 |

---

## 二、Frontmatter 由谁写入？缺失或非 .md 格式如何处理？

### 2.1 Frontmatter 的权威格式定义

定义在 `source/src/memdir/memoryTypes.ts:261-271`：

```typescript
export const MEMORY_FRONTMATTER_EXAMPLE: readonly string[] = [
  '```markdown',
  '---',
  'name: {{memory name}}',
  'description: {{one-line description — used to decide relevance in future conversations, so be specific}}',
  `type: {{${MEMORY_TYPES.join(', ')}}}`,  // 即 user, feedback, project, reference
  '---',
  '',
  '{{memory content — for feedback/project types, structure as: rule/fact, then **Why:** and **How to apply:** lines}}',
  '```',
]
```

### 2.2 谁写入 frontmatter？两条路径

**路径 A：主 Claude 模型在对话中直接写（例如用户明确说"请记住 X"）**

权威指导在主系统 prompt 中（`memdir/memdir.ts:199-266`）：

```typescript
'Write each memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:',
'',
...MEMORY_FRONTMATTER_EXAMPLE,
```

这段 prompt 是主 Claude 的系统 prompt 的一部分（通过 `loadMemoryPrompt()` 注入），告诉模型：**写 memory 时必须用这个 frontmatter 模板**。

**路径 B：后台 extractMemories subagent 自动抽取时写**

权威指导在抽取 prompt 中（`services/extractMemories/prompts.ts:50-94`）：

```typescript
'Write each memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:',
'',
...MEMORY_FRONTMATTER_EXAMPLE,
```

**关键**：`MEMORY_FRONTMATTER_EXAMPLE` 是**同一个常量**，确保两条路径格式完全一致。

### 2.3 写入触发点（精确位置）

| 路径 | 触发器 | 实际写工具 | 写权限 |
|------|-------|----------|-------|
| 主模型路径 | 用户显式要求 或 模型自判决 | Write/Edit | 正常主模型权限 |
| 后台 extract 路径 | 每个 turn 结束时 stopHooks | Write/Edit（通过 forked agent） | `createAutoMemCanUseTool` 限制只能写 memory 目录 |

**后台抽取的权限白名单**（`services/extractMemories/extractMemories.ts:171-220`）：

```typescript
export function createAutoMemCanUseTool(memoryDir: string): CanUseToolFn {
  return async (tool: Tool, input: Record<string, unknown>) => {
    if (tool.name === REPL_TOOL_NAME) return { behavior: 'allow', updatedInput: input }
    if (tool.name === FILE_READ_TOOL_NAME ||
        tool.name === GREP_TOOL_NAME ||
        tool.name === GLOB_TOOL_NAME) return { behavior: 'allow', updatedInput: input }
    if (tool.name === BASH_TOOL_NAME) {
      const parsed = tool.inputSchema.safeParse(input)
      if (parsed.success && tool.isReadOnly(parsed.data))
        return { behavior: 'allow', updatedInput: input }
      return denyAutoMemTool(...)
    }
    if (tool.name === FILE_EDIT_TOOL_NAME || tool.name === FILE_WRITE_TOOL_NAME) {
      // 只允许目标路径在 memoryDir 内
      const filePath = (input as { file_path?: string }).file_path
      if (filePath && isWithinDir(filePath, memoryDir)) {
        return { behavior: 'allow', updatedInput: input }
      }
      return denyAutoMemTool(...)
    }
    return denyAutoMemTool(...)
  }
}
```

### 2.4 没有 frontmatter 的 .md 文件如何处理？

**`parseFrontmatter` 容错实现**（`source/src/utils/frontmatterParser.ts:130-175`）：

```typescript
export function parseFrontmatter(
  markdown: string,
  sourcePath?: string,
): ParsedMarkdown {
  const match = markdown.match(FRONTMATTER_REGEX)
  if (!match) {
    return {
      frontmatter: {},       // 空对象
      content: markdown,     // 全部作为 content
    }
  }
  // ... 解析 YAML ...
}
```

**行为**：
- 不抛异常
- 不跳过文件
- 返回 `frontmatter = {}`，导致 `description = null`、`type = undefined`

**Manifest 渲染效果**：

```
- user_notes.md (2026-04-15T10:30:00.000Z)      ← 无 [type] 标签，无 description
```

**Sonnet 选择影响**：
- 缺少 type 标签 → 失去一个语义信号
- 缺少 description → **几乎肯定不会被选中**（System prompt 明确要求"基于 name 和 description"判断相关性）
- 文件依然**会出现在 manifest 里**（不会被丢弃），只是很难被推荐

### 2.5 非 .md 格式（JSON / JSONL / YAML）怎么办？

**硬约束**（`source/src/memdir/memoryScan.ts:41-43`）：

```typescript
const mdFiles = entries.filter(
  f => f.endsWith('.md') && basename(f) !== 'MEMORY.md',
)
```

**结论**：
- **仅扫描 `.md` 文件**
- `.json`、`.jsonl`、`.yaml`、`.txt` **完全被忽略**
- 这些文件放到 memory 目录不会被 retrieval 机制看见
- 主模型可以通过 Read tool 显式读取它们，但不会进入自动召回流程

### 2.6 用户现有 JSON/JSONL memory 文件的处理建议

源码不支持，但可以选择：

**方案 A：迁移成 .md + frontmatter**

为每条 JSON 记录生成一个 `.md` 文件：

```markdown
---
name: legacy-config
description: Imported from config.json - build settings
type: reference
---

(content)
```

**方案 B：手写 wrapper（不推荐）**

修改 `memoryScan.ts` 的 filter 规则并写对应的 parser；但每次升级 Claude Code 需要重新 patch。

**方案 C：在 MEMORY.md 里用 Markdown link 引用 JSON 文件**

```markdown
- [Legacy config](./config.json) — imported from old system
```

MEMORY.md 进入 system prompt，主模型可看到链接，有需要时主动 Read。

### 2.7 Frontmatter 写入全流程小结

```
用户对话 / 模型判断需要记忆
    ↓
┌────────────────────────────────────┐
│ Path A (主模型)                      │
│ system prompt 含 FRONTMATTER_EXAMPLE │
│ 模型直接调用 Write tool              │
│ 权限 = 主模型权限                    │
└────────────────────────────────────┘
    or
┌────────────────────────────────────┐
│ Path B (后台 extract)                │
│ stopHooks → executeExtractMemories   │
│ forked agent, skipTranscript=true    │
│ prompt 含 FRONTMATTER_EXAMPLE        │
│ 权限 = createAutoMemCanUseTool       │
│        (仅 memory dir 内)            │
└────────────────────────────────────┘
    ↓
.md file with YAML frontmatter 落盘
    ↓
下一次 retrieval：
  scanMemoryFiles → parseFrontmatter
  → MemoryHeader.description / type
  → formatMemoryManifest 输出到 Sonnet
```

---

## 三、Auto Dream 何时执行？Four-Phase 实际如何跑？

### 3.1 触发点与调用链

**单一触发点**（`source/src/query/stopHooks.ts:154-156`）：

```typescript
if (!toolUseContext.agentId) {
  void executeAutoDream(stopHookContext, toolUseContext.appendSystemMessage)
}
```

- 每个主 query 循环结束时都检查一次
- `!toolUseContext.agentId` 保证仅主会话触发（subagent 停止时**不**触发）
- `void` 关键字：fire-and-forget，不阻塞主线程

### 3.2 完整门控链（按检查顺序）

**门控 0：isBareMode**（`stopHooks.ts:136`）
- `--bare` / `SIMPLE` 模式 → 跳过

**门控 1：isGateOpen**（`autoDream.ts:95-100`）

```typescript
function isGateOpen(): boolean {
  if (getKairosActive()) return false      // KAIROS 用独立 /dream
  if (getIsRemoteMode()) return false      // 远程模式禁用
  if (!isAutoMemoryEnabled()) return false // 依赖 auto memory
  return isAutoDreamEnabled()
}
```

`isAutoDreamEnabled()`（`config.ts:13-21`）优先级：
1. `settings.json` 里的 `autoDreamEnabled`（显式设置覆盖一切）
2. GrowthBook feature `tengu_onyx_plover.enabled`（默认 false）

**门控 2：时间门控**（`autoDream.ts:130-141`）

```typescript
let lastAt = await readLastConsolidatedAt()  // lock 文件的 mtime
const hoursSince = (Date.now() - lastAt) / 3_600_000
if (!force && hoursSince < cfg.minHours) return  // 默认 24h
```

**门控 3：扫描节流**（`autoDream.ts:143-151`）

```typescript
const SESSION_SCAN_INTERVAL_MS = 10 * 60 * 1000  // 10 分钟
const sinceScanMs = Date.now() - lastSessionScanAt
if (!force && sinceScanMs < SESSION_SCAN_INTERVAL_MS) return
lastSessionScanAt = Date.now()
```

**设计原因**：时间门控通过但会话门控不过时，lock mtime 不推进，每个 turn 都会重新检查。10 分钟节流避免频繁扫会话目录。

**门控 4：会话门控**（`autoDream.ts:153-171`）

```typescript
const sessionIds = (await listSessionsTouchedSince(lastAt))
  .filter(id => id !== getSessionId())  // 排除当前会话
if (!force && sessionIds.length < cfg.minSessions) return  // 默认 5
```

`listSessionsTouchedSince()` 扫描 `getProjectDir(cwd)` 下所有 session 目录的 mtime。

**门控 5：Lock 门控**（`autoDream.ts:173-190`）

```typescript
const priorMtime = await tryAcquireConsolidationLock()
if (priorMtime === null) return  // 被另一进程持有
```

Lock 文件语义（`consolidationLock.ts`）：
- 路径：`<memoryRoot>/.consolidate-lock`
- 内容：持有者 PID
- **mtime = `lastConsolidatedAt`**（一文件两用途）
- `HOLDER_STALE_MS = 3_600_000`（1 小时）：即使 PID 存活，超 1 小时可被回收
- 竞争机制：读 mtime → 写 PID → 再读验证 → 赢家继续

### 3.3 默认配置表

| 参数 | 默认值 | 来源 |
|------|-------|------|
| `minHours` | 24 小时 | `autoDream.ts:64` + `tengu_onyx_plover.minHours` |
| `minSessions` | 5 个会话 | `autoDream.ts:65` + `tengu_onyx_plover.minSessions` |
| `SESSION_SCAN_INTERVAL_MS` | 10 分钟 | `autoDream.ts:56` |
| `HOLDER_STALE_MS` | 1 小时 | `consolidationLock.ts:19` |
| `LOCK_FILE` | `.consolidate-lock` | `consolidationLock.ts:16` |
| `ENTRYPOINT_NAME` | `MEMORY.md` | `memdir.ts:34` |
| `MAX_ENTRYPOINT_LINES` | 200 | `memdir.ts:35` |
| `MAX_ENTRYPOINT_BYTES` | 25 KB | `memdir.ts:38` |

### 3.4 Four-Phase 的执行模型（关键理解）

**最关键的结论：Four-Phase 是模型在单次 forked agent 会话中自主按 prompt 指引分段执行，而不是代码层把 prompt 切成四次调用。**

**证据 1：单一 prompt 生成函数**（`consolidationPrompt.ts:10-65`）

```typescript
export function buildConsolidationPrompt(memoryRoot, transcriptDir, extra): string {
  return `# Dream: Memory Consolidation
  ...
  ## Phase 1 — Orient
  ...
  ## Phase 2 — Gather recent signal
  ...
  ## Phase 3 — Consolidate
  ...
  ## Phase 4 — Prune and index
  ...`
}
```

一个函数返回完整的 4-Phase prompt，**一次性交给模型**。

**证据 2：单次 runForkedAgent 调用，无 maxTurns**（`autoDream.ts:224-233`）

```typescript
const result = await runForkedAgent({
  promptMessages: [createUserMessage({ content: prompt })],
  cacheSafeParams: createCacheSafeParams(context),
  canUseTool: createAutoMemCanUseTool(memoryRoot),
  querySource: 'auto_dream',
  forkLabel: 'auto_dream',
  skipTranscript: true,
  overrides: { abortController },
  onMessage: makeDreamProgressWatcher(taskId, setAppState),
  // 注意：没设 maxTurns，模型可自由多轮
})
```

**证据 3：代码明确不解析 phase**（`DreamTask.ts:20-23`）

```typescript
// No phase detection — the dream prompt has a 4-stage structure
// (orient/gather/consolidate/prune) but we don't parse it. Just flip from
// 'starting' to 'updating' when the first Edit/Write tool_use lands.
export type DreamPhase = 'starting' | 'updating'
```

代码只维护两个状态 `starting` / `updating`（首次 Edit/Write 时翻转），**根本不关心**具体处于哪个 phase。phase 划分只是 prompt 对模型的建议性结构。

### 3.5 每个 Phase 模型实际做什么

#### Phase 1 — Orient（定向）

**Prompt 要求**：
```
- ls the memory directory to see what already exists
- Read MEMORY.md to understand the current index
- Skim existing topic files so you improve them rather than creating duplicates
- If logs/ or sessions/ subdirectories exist, review recent entries there
```

**模型实际调用的工具**：
- `Bash` 工具（仅 read-only，因 `createAutoMemCanUseTool`）：`ls -la <memoryRoot>`
- `Read` 工具：读 `MEMORY.md`
- `Read` / `Glob` / `Grep`：略读现有主题文件

#### Phase 2 — Gather recent signal（收集新信号）

**Prompt 要求**：
```
Sources in rough priority order:
1. Daily logs (logs/YYYY/MM/YYYY-MM-DD.md) if present
2. Existing memories that drifted
3. Transcript search:
   grep -rn "<narrow term>" ${transcriptDir}/ --include="*.jsonl" | tail -50
Don't exhaustively read transcripts. Look only for things you already suspect matter.
```

**模型实际调用**：
- `Read`：读日志文件（若存在）
- `Bash`：`grep -rn "<term>" /path/to/transcripts/ --include="*.jsonl" | tail -50`
- **窄搜索**：prompt 明确要求"narrow grep"，不能读整个 transcript

`transcriptDir` 来自 `getProjectDir(getOriginalCwd())`（`autoDream.ts:212`）。

#### Phase 3 — Consolidate（整合）

**Prompt 要求**：
```
Focus on:
- Merging new signal into existing topic files rather than creating near-duplicates
- Converting relative dates ("yesterday") to absolute dates
- Deleting contradicted facts
```

**模型实际调用**：
- `Edit` / `Write`：写或修改主题 memory 文件
- **只能写 memory 目录**（`createAutoMemCanUseTool` 白名单约束）
- 遵循 system prompt 中的 frontmatter 格式

#### Phase 4 — Prune and index（修剪 + 索引）

**Prompt 要求**：
```
Update MEMORY.md so it stays under 200 lines AND under ~25KB.
It's an index, not a dump — each entry should be one line under ~150 chars:
  - [Title](file.md) — one-line hook
Never write memory content directly into it.

- Remove pointers to memories that are now stale, wrong, or superseded
- Demote verbose entries
- Add pointers to newly important memories
- Resolve contradictions
```

**模型实际调用**：
- `Read`：读 MEMORY.md
- `Edit` / `Write`：更新 MEMORY.md
- 返回摘要文本："Return a brief summary of what you consolidated, updated, or pruned"

### 3.6 全流程时间线（从触发到完成）

```
stopHooks.ts:155 (主 query 结束)
    │
    │ void executeAutoDream(...)   ← fire-and-forget
    │
    ▼
autoDream.ts:125-273
    │
    ├─ isGateOpen()                 → 5 个开关检查
    ├─ readLastConsolidatedAt()     → 读 lock mtime
    ├─ 时间门控 (minHours=24)
    ├─ 扫描节流 (10 min)
    ├─ listSessionsTouchedSince()   → 会话门控 (minSessions=5)
    └─ tryAcquireConsolidationLock() → 赢得 lock
    │
    ▼
注册 UI 任务 (registerDreamTask)
    │
    │ AppState.tasks[taskId] = {
    │   type: 'dream',
    │   status: 'running',
    │   phase: 'starting',
    │   sessionsReviewing: N,
    │   filesTouched: [],
    │   turns: [],
    │   abortController
    │ }
    │ → 底部 nav 显示 "dreaming"
    │ → Shift+Down 对话框可见
    │
    ▼
buildConsolidationPrompt(memoryRoot, transcriptDir, extra)
    │
    │ extra 附加: Tool constraints + Sessions list
    │
    ▼
runForkedAgent({...})
    │
    │ (forkedAgent.ts)
    │ - createSubagentContext()    → 隔离 state
    │ - createAgentId('auto_dream')
    │ - query() 主循环（无 maxTurns）
    │
    │ 每轮模型消息触发 onMessage callback
    │   → makeDreamProgressWatcher
    │     → 提取 text, toolUseCount, Edit/Write paths
    │     → addDreamTurn() 更新 UI
    │     → 首次 Edit/Write 时 phase 'starting' → 'updating'
    │
    │ 模型按 Phase 1 → 2 → 3 → 4 顺序自主执行:
    │   Phase 1: Bash(ls) + Read(MEMORY.md) + Read/Glob(topic files)
    │   Phase 2: Read(daily logs) + Bash(grep transcripts)
    │   Phase 3: Edit/Write(topic files)    ← 首次写 → phase=updating
    │   Phase 4: Edit(MEMORY.md) + 返回摘要文本
    │
    ▼
┌─────────────────┬─────────────────┐
│    成功路径       │   失败/中止路径   │
└─────────────────┴─────────────────┘
    │                      │
    │                      ├─ abortController.aborted?
    │                      │   是 → 已在 kill 时处理，直接 return
    │                      │   否 → logEvent('tengu_auto_dream_failed')
    │                      │        failDreamTask(taskId)
    │                      │        rollbackConsolidationLock(priorMtime)
    │                      │         → utimes(lockPath, priorMtime)
    │                      │         → 或 unlink(lockPath) 若 priorMtime==0
    ▼                      ▼
completeDreamTask()       failDreamTask()
    │                      │
    │ status: 'completed'   │ status: 'failed'
    │ notified: true        │ notified: true
    │                       │
    ▼                      ▼
如果 filesTouched > 0:
    appendSystemMessage({
      verb: 'Improved',
      files: filesTouched
    })
    → 主转录显示 "Improved N memories"
    │
    ▼
logEvent('tengu_auto_dream_completed', {
  cache_read, cache_created,
  output_tokens, sessions_reviewed
})
```

### 3.7 UI 进度监视机制

**Watcher 函数**（`autoDream.ts:281-313`）：

```typescript
function makeDreamProgressWatcher(taskId, setAppState) {
  return msg => {
    if (msg.type !== 'assistant') return
    let text = ''
    let toolUseCount = 0
    const touchedPaths: string[] = []
    for (const block of msg.message.content) {
      if (block.type === 'text') text += block.text
      else if (block.type === 'tool_use') {
        toolUseCount++
        if (block.name === FILE_EDIT_TOOL_NAME || block.name === FILE_WRITE_TOOL_NAME) {
          const input = block.input as { file_path?: unknown }
          if (typeof input.file_path === 'string') touchedPaths.push(input.file_path)
        }
      }
    }
    addDreamTurn(taskId, { text: text.trim(), toolUseCount }, touchedPaths, setAppState)
  }
}
```

**UI 更新逻辑**（`DreamTask.ts:76-104`）：

```typescript
export function addDreamTurn(taskId, turn, touchedPaths, setAppState) {
  updateTaskState<DreamTaskState>(taskId, setAppState, task => {
    const seen = new Set(task.filesTouched)
    const newTouched = touchedPaths.filter(p => !seen.has(p) && seen.add(p))
    if (newTouched.length > 0) {
      return {
        ...task,
        phase: 'updating',  // ← 首次写触发切换
        filesTouched: [...task.filesTouched, ...newTouched],
        turns: task.turns.slice(-(MAX_TURNS - 1)).concat(turn),  // 保留最近 30 轮
      }
    }
    return { ...task, turns: ... }
  })
}
```

**可见位置**：
1. 底部 nav bar 的任务 pill（显示 "dreaming" 或 "updating N files"）
2. `Shift+Down` 打开后台任务对话框
3. 用户可 `x` / `kill` 来中止

### 3.8 中止处理（用户 kill）

**Kill 入口**（`DreamTask.ts:136-156`）：

```typescript
async kill(taskId, setAppState) {
  let priorMtime: number | undefined
  updateTaskState<DreamTaskState>(taskId, setAppState, task => {
    if (task.status !== 'running') return task
    task.abortController?.abort()  // ← 触发 abort signal
    priorMtime = task.priorMtime
    return { ...task, status: 'killed', endTime: Date.now(), notified: true, abortController: undefined }
  })
  if (priorMtime !== undefined) {
    await rollbackConsolidationLock(priorMtime)  // 倒回 lock mtime
  }
}
```

**autoDream.ts:258-271 中的防双重回滚**：

```typescript
catch (e: unknown) {
  if (abortController.signal.aborted) {
    logForDebugging('[autoDream] aborted by user')
    return  // 已由 kill 处理，不再重复 rollback
  }
  logForDebugging(`[autoDream] fork failed: ${e.message}`)
  logEvent('tengu_auto_dream_failed', {})
  failDreamTask(taskId, setAppState)
  await rollbackConsolidationLock(priorMtime)
}
```

### 3.9 后台模式：绝不阻塞主线程

关键代码：`void executeAutoDream(...)`（`stopHooks.ts:155`）
- `void` 显式丢弃 Promise
- 主 query 循环立即返回，用户可以继续下一个输入
- 与 `executeExtractMemories` 行为一致

**特别的：autoDream 不参与 `print.ts` 的 `drainPendingExtraction`**
- Extract memories 在 `-p` 模式下会被 drain 以保证 shutdown 前完成
- AutoDream 则完全异步，不保证完成

### 3.10 为什么要用 Lock 文件 mtime 双用途？

设计优雅性：
1. 一个文件解决**互斥** + **时间戳记录**两件事
2. 进程崩溃（未正常 `releaseConsolidationLock`）时，mtime 仍是上次开始时间，时间门控天然失效 1 小时（HOLDER_STALE_MS）直到自动回收
3. Dream 失败时 `rollbackConsolidationLock(priorMtime)` 精准倒回，使下次仍能触发
4. `priorMtime === 0` 时 `unlink()` → 恢复到"从未 consolidate"的状态

### 3.11 Auto Dream 执行条件核心小结

| 问题 | 答案 |
|------|------|
| 何时检查？ | 每个主 query 结束时（stopHook） |
| 何时跳过？ | 5+ 门控任一失败 |
| 多久执行一次？ | 最少 24h + 最少 5 个新会话 |
| 节流？ | 10 分钟扫描节流 |
| 跨进程安全？ | Lock file + PID + 1h stale timeout |
| 阻塞主线程？ | 完全不阻塞（void 丢弃 Promise） |
| Four-Phase 怎么执行？ | 模型在单次 forked agent 会话中自主按 prompt 分段执行 |
| 代码有 phase 分割逻辑吗？ | 没有，代码只跟踪 starting/updating 两状态 |
| 可多轮吗？ | 无 maxTurns 限制，模型自由多轮 |
| 失败会重试吗？ | 不会，但 rollback lock 使下次 stopHook 仍能触发 |

---

## 四、三个问题的最终整合答案

### 4.1 Manifest 的本质

Manifest = 多文件 frontmatter 摘要的文本清单 + 运行时 mtimeMs，**不落盘**、**不含正文**、**不含 embedding**。一次生成，一次 Sonnet sideQuery，一次返回 JSON。这就是"纯 LLM 语义选择 + Manifest 文本索引"的全部。

### 4.2 Frontmatter 写入

Frontmatter 由两种 agent 写入，都以 `MEMORY_FRONTMATTER_EXAMPLE` 为模板：
- **主 Claude**（通过 system prompt 中的 memory 段指导）
- **后台 extractMemories forked agent**（通过抽取 prompt 指导 + `createAutoMemCanUseTool` 权限约束）

没有 frontmatter 的 `.md` 不报错但很难被选中。非 `.md` 文件（JSON/JSONL/YAML）**直接被忽略**，不会进入 retrieval 流程。要让老 JSON memory 被系统识别，必须迁移成带 frontmatter 的 `.md`。

### 4.3 Auto Dream 触发 + Four-Phase 执行

- **触发点**：每个主 query 结束 stopHook，非 subagent 才会
- **门控链**：KAIROS / Remote / AutoMemory / AutoDream feature → 时间 24h → 扫描节流 10min → 会话 ≥5 → Lock 成功
- **执行**：构建一次性 4-Phase prompt → `runForkedAgent` 单次会话 → **模型自主**顺序调用 Bash/Read/Grep/Edit/Write 完成 4 个阶段
- **代码不切分 phase**，只跟踪 `'starting'` / `'updating'` 两个 UI 状态
- **Lock 机制**：用 lock 文件的 mtime 同时承担互斥和 `lastConsolidatedAt`，失败时 `utimes` 精准倒回
- **完全不阻塞主线程**（`void` 丢弃 Promise）

---

## 五、关键代码引用速查

| 问题 | 文件 | 行号 | 要点 |
|------|------|------|------|
| Manifest 生成 | `memdir/memoryScan.ts` | 84-94 | `formatMemoryManifest()` |
| Manifest 所用 metadata | `memdir/memoryScan.ts` | 13-19 | `MemoryHeader` 类型，无 content |
| 前 30 行读取限制 | `memdir/memoryScan.ts` | 22 | `FRONTMATTER_MAX_LINES = 30` |
| 只扫 .md | `memdir/memoryScan.ts` | 41-43 | `.endsWith('.md') && !== 'MEMORY.md'` |
| LLM 选择入口 | `memdir/findRelevantMemories.ts` | 77-141 | `selectRelevantMemories()` |
| Select system prompt | `memdir/findRelevantMemories.ts` | 18-24 | `SELECT_MEMORIES_SYSTEM_PROMPT` |
| validFilenames 过滤 | `memdir/findRelevantMemories.ts` | 130 | 静默过滤无效返回 |
| Frontmatter 容错解析 | `utils/frontmatterParser.ts` | 130-175 | 缺失返回 `{}` |
| Frontmatter 模板 | `memdir/memoryTypes.ts` | 261-271 | `MEMORY_FRONTMATTER_EXAMPLE` |
| 主模型写 prompt | `memdir/memdir.ts` | 199-266 | system prompt 指引 |
| Extract subagent 写 prompt | `services/extractMemories/prompts.ts` | 50-94 | auto-only 提示模板 |
| AutoMem 权限白名单 | `services/extractMemories/extractMemories.ts` | 171-220 | `createAutoMemCanUseTool` |
| AutoDream 触发 | `query/stopHooks.ts` | 154-156 | `void executeAutoDream(...)` |
| AutoDream 门控 | `services/autoDream/autoDream.ts` | 95-190 | 5 层检查 |
| Four-Phase prompt | `services/autoDream/consolidationPrompt.ts` | 10-65 | `buildConsolidationPrompt` |
| Fork 运行配置 | `services/autoDream/autoDream.ts` | 224-233 | 无 maxTurns |
| UI 状态 | `services/autoDream/DreamTask.ts` | 20-23 | 无 phase 解析，只有 starting/updating |
| Lock 文件 | `services/autoDream/consolidationLock.ts` | 1-108 | mtime 双用途 + rollback |
| Progress watcher | `services/autoDream/autoDream.ts` | 281-313 | `makeDreamProgressWatcher` |
| 完成/失败处理 | `services/autoDream/autoDream.ts` | 235-271 | `completeDreamTask` + `rollbackConsolidationLock` |
