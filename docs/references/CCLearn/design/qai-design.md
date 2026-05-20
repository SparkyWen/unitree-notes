# QAI Design：基于 Claude Code 的多Agent、多工具、有记忆系统完整设计

## 1. 设计目标

本文基于以下两类材料综合重构：

- `CCLearn/notes/notes_integrated/*.md` 中对 Claude Code 架构、多 Agent 通信、Memory、Transcript、Query Loop 的总结
- `CCLearn/source/src` 中的关键源码，尤其是：
  - `query.ts`
  - `QueryEngine.ts`
  - `Tool.ts`
  - `tools.ts`
  - `services/tools/*`
  - `utils/sessionStorage.ts`
  - `tasks/LocalAgentTask/*`
  - `tasks/RemoteAgentTask/*`
  - `tools/AgentTool/*`
  - `memdir/*`
  - `services/extractMemories/*`
  - `services/autoDream/*`
  - `utils/swarm/*`

你的原始设计方向是正确的，但还不够完整。Claude Code 真正成熟的地方，不在于“有 Query Loop + Tool Call + Memory”这么简单，而在于它把系统做成了一个 **事件流驱动、任务化、多上下文隔离、分层记忆、可恢复、可压缩、可审计、可后台化** 的运行时。

所以，面向一个“Web 后端可运行的一人公司多 Agent 系统”，推荐把设计从 8 层扩展为 **12 层运行架构 + 6 个核心引擎 + 4 条通信总线 + 3 级记忆体系 + 2 类 Agent 生命周期**。

---

## 2. 总体架构，建议升级为 12 层

```text
┌──────────────────────────────────────────────────────────────┐
│ Layer 0. 接入层 (Ingress Layer)                              │
│ Web API / CLI / WebSocket / IDE / Cron / External Trigger    │
├──────────────────────────────────────────────────────────────┤
│ Layer 1. 交互与呈现层 (Interaction Layer)                     │
│ REPL / Web Chat / Admin Console / Agent Monitor / Task UI    │
├──────────────────────────────────────────────────────────────┤
│ Layer 2. 会话与状态层 (Session & State Layer)                 │
│ SessionStorage / Transcript / Resume / AppState / TaskState  │
├──────────────────────────────────────────────────────────────┤
│ Layer 3. 查询引擎层 (Query Engine Layer)                      │
│ QueryLoop / Prompt Assembly / Message Normalization          │
├──────────────────────────────────────────────────────────────┤
│ Layer 4. 模型调用层 (Model Runtime Layer)                     │
│ Streaming API / Retry / Fallback / Token Budget / Usage      │
├──────────────────────────────────────────────────────────────┤
│ Layer 5. 工具编排层 (Tool Orchestration Layer)                │
│ ToolRegistry / ToolExecution / StreamingExecutor             │
├──────────────────────────────────────────────────────────────┤
│ Layer 6. 权限与安全层 (Permission & Safety Layer)             │
│ Rules / Hooks / Classifier / Interactive Approval            │
├──────────────────────────────────────────────────────────────┤
│ Layer 7. Agent运行时层 (Agent Runtime Layer)                  │
│ Sync Subagent / Async Agent / Team / Swarm / Remote Agent    │
├──────────────────────────────────────────────────────────────┤
│ Layer 8. 任务与通信层 (Task & Communication Layer)            │
│ Task Bus / Mailbox / Notifications / Sidechain / Queue       │
├──────────────────────────────────────────────────────────────┤
│ Layer 9. 记忆与上下文层 (Memory & Context Layer)              │
│ CLAUDE.md / MemoryDir / Relevant Recall / Compaction         │
├──────────────────────────────────────────────────────────────┤
│ Layer 10. 外部集成层 (Integration Layer)                      │
│ MCP / Git / FS / Search / Browser / APIs / Webhooks          │
├──────────────────────────────────────────────────────────────┤
│ Layer 11. 基础设施层 (Infrastructure Layer)                   │
│ Write Queue / Locking / Worktree / Telemetry / Storage       │
└──────────────────────────────────────────────────────────────┘
```

### 为什么必须从 8 层升级到 12 层

因为 Claude Code 不是一个简单的“Agent + Tool”应用，而是：

1. **有独立会话持久化层**，不是 UI 附带存一下历史
2. **有独立模型运行时层**，负责 streaming/retry/fallback/token 恢复
3. **有独立任务通信层**，多 Agent 不是直接互调，而是 task + mailbox + notification
4. **有独立基础设施层**，比如 write queue、EOF metadata、worktree、telemetry、content replacement

如果你要做“web 后端一人公司系统”，这些都必须变成一级概念。

---

## 3. 系统核心设计原则

### 3.1 一切以 Message/Event 为中心

不是“函数调用驱动系统”，而是“消息事件驱动系统”。

核心事件类型至少包括：

- user
- assistant
- tool_use
- tool_result
- attachment
- system
- summary
- task-notification
- compact_boundary
- file-history-snapshot
- attribution-snapshot

### 3.2 主会话与子会话必须天然隔离

Claude Code 的一个重要启发是：

- 主对话 transcript
- sidechain / subagent transcript
- remote session transcript
- teammate mailbox

这些都不是一锅粥，而是多个并行但可关联的数据面。

### 3.3 多 Agent 的本质不是“多个模型实例”，而是“多个运行时上下文”

每个 Agent 至少要独立拥有：

- messages
- abortController
- readFileState
- toolPermissionContext
- task state
- transcript file
- working directory 或 worktree
- agent identity

### 3.4 Memory 不是历史全文检索

必须明确分层：

1. **热上下文**：当前 session messages
2. **durable memory**：`.md` 记忆文件
3. **冷历史**：JSONL transcripts
4. **代码事实**：Grep/Glob/Read/LSP 实时探索

### 3.5 Task 是多 Agent 协作总线，不是附属功能

Claude Code 中最关键的不是 SendMessage，而是 Task。

因为：

- Agent 可后台运行
- 主会话不阻塞
- 可以 list/get/update/output/stop
- 结果可通过 notification 注入下一轮

所以你的系统也应该把 Task 做成一等公民。

---

## 4. 升级后的完整系统视图

```text
User / Webhook / Scheduler
        │
        ▼
Ingress API
        │
        ▼
Session Router
        │
        ├── Main Session
        ├── Background Task Session
        ├── Subagent Session
        └── Remote/Team Session
        │
        ▼
Query Engine
        │
        ├── Prompt Assembly
        ├── Message Normalization
        ├── Model Stream Runtime
        ├── Streaming Tool Executor
        ├── Attachment Collector
        ├── Transcript Recorder
        ├── Memory Prefetch
        └── Recovery / Compact
        │
        ▼
Tool / Agent / Task Layer
        │
        ├── Local Tools
        ├── MCP Tools
        ├── Agent Tool
        ├── Task Tools
        ├── SendMessage Tool
        ├── Team Tools
        └── Notification Sink
        │
        ▼
Storage & Infra
        ├── session.jsonl
        ├── subagents/agent-*.jsonl
        ├── tool-results/*.txt
        ├── memory/*.md
        ├── task metadata
        ├── team mailboxes
        └── telemetry / logs
```

---

## 5. 模块 1，升级版会话持久化引擎

你的版本是对的，但还缺少 8 个关键点：

1. progress message 不参与 parentUuid 链
2. metadata entry 和 transcript message 要分流
3. sidechain message 不能污染主 messageSet
4. compact boundary 要断开物理 parentUuid，保留 logicalParentUuid
5. pre-materialization 缓冲队列
6. file-history / attribution snapshot
7. remote persistence 适配口
8. tail metadata 快速扫描

### 5.1 推荐职责

```ts
interface TranscriptStore {
  recordTranscript(messages: Message[]): Promise<void>
  recordSidechainTranscript(messages: Message[], agentId: string): Promise<void>
  insertMessageChain(messages: Message[], opts: ChainInsertOptions): Promise<void>
  appendEntry(entry: Entry, sessionId?: UUID): Promise<void>
  enqueueWrite(filePath: string, entry: Entry): Promise<void>
  drainWriteQueue(): Promise<void>
  reAppendSessionMetadata(skipTitleRefresh?: boolean): void
  materializeSessionFile(): Promise<void>
  flush(): Promise<void>
}
```

### 5.2 数据结构

```ts
type TranscriptMessage = {
  uuid: UUID
  parentUuid: UUID | null
  logicalParentUuid?: UUID | null
  isSidechain: boolean
  agentId?: string
  sessionId: UUID
  cwd: string
  gitBranch?: string
  timestamp: string
  version: string
  message: InternalMessage
}

type Entry =
  | TranscriptMessage
  | SummaryEntry
  | LastPromptEntry
  | FileHistorySnapshotEntry
  | AttributionSnapshotEntry
  | TagEntry
  | AgentSettingEntry
  | WorktreeStateEntry
  | QueueOperationEntry
  | CompactBoundaryEntry
```

### 5.3 目录布局建议

```text
runtime/
  sessions/
    <project-slug>/
      <sessionId>.jsonl
      <sessionId>/
        subagents/
          agent-<agentId>.jsonl
          agent-<agentId>.meta.json
        remote-agents/
          remote-agent-<taskId>.meta.json
        tool-results/
          <resultId>.txt
        snapshots/
          files/
          attribution/
```

### 5.4 关键机制

#### A. 写入队列

- 按 filePath 分桶
- 100ms 左右批量刷盘
- 支持 activeDrain promise，避免并发 flush 冲突
- 单次 chunk 大小限制，避免超大 write

#### B. UUID 去重

- 主 transcript 维护 `messageSet`
- sidechain 独立维护，不进入主集合
- dedup 只跳过重复写，不改变逻辑链构建规则

#### C. EOF metadata

尾部维护：

- last-prompt
- title
- tag
- agent-setting
- mode
- worktree-state

这样 UI 的 `/resume` 或 Web 会话列表无需读取整个文件。

#### D. Compact boundary

建议明确支持：

```ts
{
  type: 'system',
  subtype: 'compact_boundary',
  parentUuid: null,
  logicalParentUuid: prevLeafUuid,
  compactMetadata: {...}
}
```

这是后续 context collapse 与 transcript rebuild 的关键。

### 5.5 你要补充的实现函数

```ts
insertMessageChain(messages, isSidechain, agentId, startingParentUuid?)
appendEntry(entry, sessionId?)
enqueueWrite(filePath, entry)
drainWriteQueue()
materializeSessionFile()
reAppendSessionMetadata(skipTitleRefresh?)
recordTranscript(messages)
recordSidechainTranscript(messages, agentId)
flushSessionStorage()
```

---

## 6. 模块 2，升级版查询循环

你的 query loop 已经接近 Claude Code 主干，但还缺少下面这些关键阶段：

1. tool result budget
2. snip compact
3. microcompact
4. context collapse
5. autocompact
6. streaming tool executor
7. fallback model retry
8. max_output_tokens 恢复
9. stop hooks
10. tool use summary 生成

### 6.1 推荐总流程

```text
while (true):
  1. 检查 abort / maxTurns / budget
  2. startRelevantMemoryPrefetch()
  3. applyToolResultBudget()
  4. snipOldMessages()
  5. microcompact()
  6. contextCollapseIfNeeded()
  7. autocompactIfNeeded()
  8. assemble prompt/system/context
  9. normalize messages for API
  10. call model stream
  11. stream parse blocks
      - text
      - thinking
      - tool_use
  12. StreamingToolExecutor.addTool()
  13. 收集 assistant messages
  14. 等待/收集 tool results
  15. collect attachments
  16. persist transcript
  17. 若无 tool_use，则 return completed
  18. 否则 messages += assistant + toolResults + attachments，继续循环
```

### 6.2 推荐接口

```ts
interface QueryEngine {
  submitMessage(prompt: PromptInput, options?: SubmitOptions): AsyncGenerator<SDKMessage, void>
}

interface QueryLoopDeps {
  callModel(...): AsyncGenerator<AssistantChunk>
  autocompact(...): Promise<CompactResult>
  microcompact(...): Promise<CompactResult>
  contextCollapse(...): Promise<CollapseResult>
  runTools(...): AsyncGenerator<MessageUpdate>
  recordTranscript(...): Promise<void>
}
```

### 6.3 核心恢复机制

#### A. prompt-too-long / 413

恢复顺序建议：

1. context collapse drain
2. reactive compact
3. 再次重试
4. 失败则返回 error

#### B. max_output_tokens

恢复顺序建议：

1. 注入恢复消息，告诉模型延续输出
2. 必要时切换更高输出上限模型
3. 最多重试 N 次

#### C. fallback triggered

Claude Code 里是 `FallbackTriggeredError + fallbackModel`。

你也应该保留：

```ts
try {
  ...
} catch (err) {
  if (err instanceof FallbackTriggeredError && fallbackModel) {
    switchModel(fallbackModel)
    retry()
  }
}
```

### 6.4 Query Loop 里的重要边界

#### 不要让 UI 直接拥有 Query 逻辑

UI 只消费 generator 输出。

#### 不要让 Query 直接依赖具体 Web 前端

应通过 event stream / SDK message 暴露。

#### 不要让 Query 负责真正的工具细节

工具逻辑应该在 ToolExecution / ToolOrchestration 层。

---

## 7. 模块 3，升级版工具注册与执行系统

你的 Tool 接口已经很接近 Claude Code。但建议完全对齐为两层：

1. **Tool Definition Layer**
2. **Tool Execution Runtime Layer**

### 7.1 推荐 Tool 接口

```ts
interface Tool<Input = unknown, Output = unknown, Progress = unknown> {
  name: string
  description: string
  inputSchema: ZodSchema<Input>

  prompt(opts?: ToolPromptOptions): string

  call(input: Input, context: ToolUseContext): Promise<Output> | AsyncGenerator<Progress | Output>

  mapToolResultToToolResultBlockParam(output: Output, toolUseId: string): ToolResultBlock

  validateInput?(input: Input, context: ToolUseContext): Promise<ValidationResult>
  checkPermissions?(input: Input, context: ToolPermissionRuntimeContext): Promise<PermissionDecision>

  isConcurrencySafe(input: Input): boolean
  isReadOnly(input: Input): boolean
}
```

### 7.2 推荐执行流水线

```text
runToolUse(toolUseBlock)
  ├── findToolByName()
  ├── parse JSON input
  ├── zod validate
  ├── tool.validateInput()
  ├── canUseTool()
  │   ├── rules
  │   ├── hooks
  │   ├── classifier
  │   └── interactive approval
  ├── runPreToolUseHooks()
  ├── tool.call()
  ├── processToolResultBlock()
  ├── tool.mapToolResultToToolResultBlockParam()
  ├── runPostToolUseHooks()
  └── emit tool_result message
```

### 7.3 并发分区

建议沿用 Claude Code 的做法：

- 把 tool calls 划分成 batch
- 连续的 concurrency-safe 工具作为一组并行
- 非 concurrency-safe 的串行执行

```ts
partitionToolCalls(toolUses): Batch[]
```

### 7.4 Streaming Tool Executor 必须保留

这是非常关键的高级能力。不是等 assistant 整段输出完才跑工具，而是：

- 一旦 stream 中出现 `tool_use block stop`
- 立即 addTool
- 如果当前 batch 允许并发，立刻执行

这样可以显著降低端到端 latency。

### 7.5 大结果持久化

Claude Code 的重要设计之一是：

- 大工具结果不全部塞进 context
- 超限写入 `tool-results/*.txt`
- 返回一个截断说明 + 文件引用

你应该显式设计：

```ts
interface ToolResultStorage {
  persistLargeResult(toolUseId: string, content: string): Promise<{ path: string }>
}
```

这对 Web 后端非常重要，否则 context 爆炸得很快。

---

## 8. 模块 4，升级版权限系统

你的 3 阶段设计是对的，但还要补上：

- classifier
- deny tracking
- mode memory
- subagent prompt avoidance
- leader/worker permission bridge

### 8.1 推荐权限决策链

```text
checkPermissions(tool, input, context)
  1. explicit rules
     - alwaysAllow
     - alwaysDeny
     - alwaysAsk
  2. tool.checkPermissions()
  3. preToolUseHooks()
  4. classifier decision
  5. interactive dialog / web approval
  6. denial tracking
  7. final decision
```

### 8.2 权限模式

建议至少支持：

- `default`: 默认每次危险操作询问
- `acceptEdits` / `auto`: 自动允许低风险编辑
- `plan`: 只允许调研与计划，不允许写入
- `bypass`: 绕过交互审批，但必须有显式授权来源

### 8.3 推荐数据结构

```ts
type PermissionRule = {
  tool: string
  matcher: string | RegExp | PathPattern
  behavior: 'allow' | 'deny' | 'ask'
  source: 'settings' | 'cli' | 'session' | 'policy' | 'runtime'
}

type PermissionDecision =
  | { behavior: 'allow'; reason: string }
  | { behavior: 'deny'; reason: string }
  | { behavior: 'ask'; reason: string; prompt: UserPrompt }
```

### 8.4 Web 后端必须增加的能力

你的系统如果跑在 Web 后端，就不能假设 always 有 CLI dialog。

所以需要：

- Web approval queue
- async decision await
- timeout default deny
- background agent 自动拒绝交互弹窗，转 pending task/notification

---

## 9. 模块 5，升级版 Agent 管理系统

你写的 7 点已经很对，但还需要再升级成 **5 类 Agent 运行模式**。

### 9.1 Agent 类型应该分 5 类

#### 1. Sync Subagent

- 阻塞父 query
- 内部递归 `query()`
- 结果回传后父级继续
- 适合 Explore / Plan / Verify

#### 2. Async Local Agent Task

- 后台运行
- 主会话立即得到 launched result
- taskId / agentId 可追踪
- 支持 output/list/stop/sendMessage

#### 3. Remote Agent Task

- 真正远程长时运行
- 主会话只轮询远程事件
- 适合 long-running review / planning / execution

#### 4. Teammate / Swarm Agent

- 长驻、多身份、邮箱通信
- 不是一次性子调用
- 适合“一人公司”模拟多个职能角色

#### 5. Coordinator Agent

- 不直接干活，只负责拆任务、派单、汇总
- 非常适合你的“一人公司系统”主控角色

### 9.2 推荐 Agent Runtime 接口

```ts
interface AgentRuntime {
  spawnAgent(prompt: string, agentType: string, options: SpawnOptions): Promise<SpawnResult>
  runAgent(config: RunAgentConfig): AsyncGenerator<Message>
  createSubagentContext(parent: ToolUseContext, overrides?: Partial<ToolUseContext>): ToolUseContext
  filterToolsForAgent(tools: Tool[], agentDef: AgentDefinition): Tool[]
  enqueueNotification(agentId: string, payload: NotificationPayload): Promise<void>
}
```

### 9.3 createSubagentContext 必须做的隔离

```ts
createSubagentContext(parentContext, overrides) {
  return {
    ...parentContext,
    abortController: new AbortController(),
    readFileState: cloneFileStateCache(parentContext.readFileState),
    messages: [...],
    toolPermissionContext: derivedPermissionContext,
    agentId: newAgentId(),
    setAppState: noopOrScopedState,
    setAppStateForTasks: parentContext.setAppStateForTasks ?? parentContext.setAppState,
  }
}
```

### 9.4 Tool 过滤策略

Claude Code 的启发非常重要：

- 不能让 agent 默认拥有所有工具
- 必须有全局禁止列表 `ALL_AGENT_DISALLOWED_TOOLS`
- 再叠加 agent definition whitelist/blacklist

建议：

```ts
filterToolsForAgent(tools, agentDef) {
  return tools
    .filter(t => !GLOBAL_AGENT_DENYLIST.has(t.name))
    .filter(t => matchesAgentPolicy(t, agentDef))
}
```

### 9.5 Worktree 隔离必须保留

如果你要做一人公司系统，多个 coding agent 同时改代码时，强烈建议：

- 默认每个执行型 coding agent 使用 git worktree
- planner/reviewer 可以共享主目录只读

角色建议：

- CEO/Coordinator: 主目录，不直接改代码
- CTO/Engineer: 独立 worktree
- QA/Reviewer: 只读主目录或 review worktree
- Growth/Research: 独立 scratch/worktree

### 9.6 通知机制建议从 XML 升级成双格式

Claude Code 用 `<task-notification>` 很聪明，因为可嵌入 message 内容。

你的系统建议支持两种：

1. **LLM-friendly XML**
2. **System-friendly JSON metadata**

```xml
<task-notification>
  <task-id>task_123</task-id>
  <agent-id>agent_abc</agent-id>
  <status>completed</status>
  <summary>完成市场调研并输出竞品分析</summary>
</task-notification>
```

同时内部存：

```json
{
  "type": "task-notification",
  "taskId": "task_123",
  "agentId": "agent_abc",
  "status": "completed",
  "summary": "完成市场调研并输出竞品分析"
}
```

---

## 10. 模块 6，升级版记忆系统

这是你的设计中最需要补强的地方。Claude Code 的 memory 绝不是简单的 “CLAUDE.md + memory dir”。

建议明确成 **4 层记忆架构**。

### 10.1 四层记忆模型

#### Layer A. Session Working Memory

- 当前 messages
- 当前 turn 相关状态
- prompt 中直接可见

#### Layer B. Durable Memory (.md)

- 项目记忆文件
- curated memory
- relevant memory retrieval 主要面向它

#### Layer C. Transcript Archive (.jsonl)

- 原始历史
- 不直接参与常规 recall
- 供 AutoDream / grep / resume 使用

#### Layer D. Codebase Reality

- 当前代码库真实状态
- 通过 grep/glob/read/lsp 现查
- 不是 memory

### 10.2 记忆目录建议

```text
memory/
  MEMORY.md
  product.md
  architecture.md
  customers.md
  experiments.md
  ops.md
  team/
    shared.md
    planner.md
    sales.md
    engineer.md
```

### 10.3 推荐记忆服务接口

```ts
interface MemoryService {
  loadMemory(projectPath: string): Promise<LoadedMemory>
  findRelevantMemories(query: string, context: QueryContext): Promise<MemoryFile[]>
  injectMemory(systemPrompt: string, memory: LoadedMemory): Promise<string>
  extractMemories(messages: Message[]): Promise<MemoryUpdate[]>
  compactMessages(messages: Message[]): Promise<CompactResult>
  createCompactBoundary(metadata?: CompactMetadata): SystemMessage
  startRelevantMemoryPrefetch(query: string, context: QueryContext): DisposablePromise<MemoryFile[]>
}
```

### 10.4 relevant memory prefetch 必须是异步前置

Claude Code 的这点非常值得保留：

- 用户刚发问
- query loop 还在做别的准备
- 后台就开始做 relevant memory scan

这样能降低 memory recall latency。

### 10.5 自动记忆提取

建议引入两条写回路径：

#### A. turn-level extract

每轮结束后，提取少量 durable memory 候选

#### B. auto-dream / consolidation

在会话空闲、结束或后台定时触发时：

- 窄 grep transcript
- 生成长期有价值 `.md`
- 合并、去重、重写 memory 索引

### 10.6 压缩机制必须拆成三层

#### 1. snip / trim

直接裁掉最老且低价值的消息

#### 2. microcompact

对工具结果、cache edits、重复上下文做局部微压缩

#### 3. full compact / context collapse

生成摘要边界，保留重要上下文但减少 token

### 10.7 Compact Boundary 设计

```ts
createCompactBoundary(): Message {
  return {
    type: 'system',
    subtype: 'compact_boundary',
    uuid: randomUUID(),
    compactMetadata: {
      preservedSegment: false,
      collapsedRange: { startUuid, endUuid },
      summaryRef: summaryUuid,
    }
  }
}
```

---

## 11. 多 Agent 通信设计，建议正式纳入架构

这是你原设计里缺失的一块核心。

Claude Code 的多 Agent 不是单一通信方式，而是复合系统。你的系统也应该这样设计。

### 11.1 四条通信总线

#### 总线 A. Tool Call Return Bus

- Sync subagent 的结果直接作为 tool_result 回父级
- 适合同步短任务

#### 总线 B. Task Bus

- create/get/list/update/output/stop
- 多 Agent 协作主总线
- 适合异步后台任务

#### 总线 C. Mailbox Bus

- agent-to-agent 显式消息
- 适合 teammate/swarm

#### 总线 D. Memory Bus

- shared memory / team memory / snapshots
- 适合长期非实时协作

### 11.2 为什么一人公司系统必须有 Team / Mailbox

因为你的目标不是单一 assistant，而是多个职能体：

- CEO / Coordinator
- Researcher
- Product Manager
- Engineer
- Reviewer / QA
- Sales / Growth
- Ops / Finance

这些 Agent 不只是“一次性任务执行器”，而是持续角色。

所以需要：

- 身份
- inbox
- task ownership
- shared memory
- notification routing

### 11.3 推荐 mailbox 结构

```text
runtime/teams/<teamName>/
  config.json
  inboxes/
    ceo.json
    researcher.json
    engineer.json
    sales.json
```

消息格式：

```json
{
  "from": "ceo",
  "to": "engineer",
  "type": "message",
  "summary": "实现 landing page MVP",
  "text": "请基于最新 PRD 实现 landing page MVP，先只做 Web 首屏。",
  "timestamp": "2026-04-17T04:38:00Z",
  "read": false
}
```

### 11.4 一人公司角色编排建议

#### 主控角色

- `Coordinator/CEO Agent`
  - 只做任务拆解、优先级、资源分配、结果汇总

#### 执行角色

- `Research Agent`
- `PM Agent`
- `Engineer Agent`
- `Designer Agent`
- `Reviewer/QA Agent`
- `Growth/Sales Agent`
- `Ops Agent`

#### 工作模式

- CEO 创建目标
- PM 拆成任务树
- Research 提供输入
- Engineer 在 worktree 编码
- QA review / verify
- Growth 输出市场/内容/销售资产
- Ops 追踪 cron / budgets / external signals

---

## 12. 面向 Web 后端的运行架构建议

既然你的目标是“在 web 后端跑一个完整的一人公司系统”，建议增加以下后端服务。

### 12.1 推荐后端服务拆分

```text
services/
  api-gateway/
  session-service/
  query-service/
  tool-service/
  permission-service/
  task-service/
  agent-service/
  memory-service/
  notification-service/
  integration-service/
  telemetry-service/
```

### 12.2 最小可行单体版模块

如果你先做单体后端，也建议模块化：

```text
src/
  core/
    query/
    tools/
    agents/
    memory/
    permissions/
    tasks/
    transcript/
  adapters/
    llm/
    mcp/
    git/
    fs/
    browser/
    webhooks/
  runtime/
    scheduler/
    notification/
    telemetry/
  web/
    routes/
    ws/
    auth/
    admin/
```

### 12.3 Web 后端必须新增的运行能力

#### A. Task Dashboard

展示：

- running tasks
- agent status
- queue depth
- last notifications
- memory updates
- token/cost usage

#### B. Approval Center

替代 CLI permission dialog：

- pending permission requests
- approve / deny / allow once / allow session

#### C. Agent Inbox / Thread View

查看：

- teammate mailbox
- task conversations
- sidechain transcript

#### D. Memory Console

查看：

- relevant memories hit rate
- recent extracted memories
- auto-dream candidates
- compact boundaries

---

## 13. 重新整理后的核心模块定义

下面给你一个比原 plan 更完整的模块化实现蓝图。

### 13.1 模块 A，会话持久化引擎

```ts
class SessionPersistenceEngine {
  recordTranscript(messages)
  recordSidechainTranscript(messages, agentId)
  insertMessageChain(messages, isSidechain, agentId, startingParentUuid?)
  appendEntry(entry)
  enqueueWrite(filePath, entry)
  drainWriteQueue()
  reAppendSessionMetadata(skipTitleRefresh?)
  materializeSessionFile()
  loadTranscript(sessionId)
  loadConversationChain(leafUuid)
  flush()
}
```

### 13.2 模块 B，Query Engine

```ts
class QueryEngine {
  submitMessage(prompt, options?)
  queryLoop(state)
  assembleSystemPrompt(staticParts, dynamicParts, context)
  normalizeMessages(messages)
  streamAPICall(messages, tools, systemPrompt)
  extractToolUseBlocks(response)
  executeTools(toolBlocks)
  collectAttachments()
  handleRecovery(error)
}
```

### 13.3 模块 C，Tool Runtime

```ts
class ToolRuntime {
  getAllTools()
  assembleToolPool(permissionContext, agentContext)
  partitionToolCalls(toolUses)
  runTools(toolUses)
  runToolUse(toolUse)
  validateInput(tool, input)
  processToolResult(tool, output)
  persistLargeResultIfNeeded(result)
}
```

### 13.4 模块 D，Permission Engine

```ts
class PermissionEngine {
  checkPermissions(tool, input, context)
  resolveRules(tool, input)
  runHooks(tool, input)
  runClassifier(tool, input)
  requestInteractiveApproval(request)
  trackDenial(tool, input)
}
```

### 13.5 模块 E，Agent Runtime

```ts
class AgentRuntime {
  spawnAgent(prompt, agentType, options)
  runAgent(config)
  createSubagentContext(parentContext, overrides)
  filterToolsForAgent(tools, agentDef)
  enqueueNotification(agentId, result)
  createWorktree(agentId)
  recordSidechain(agentId, messages)
}
```

### 13.6 模块 F，Task Runtime

```ts
class TaskRuntime {
  createTask(payload)
  getTask(taskId)
  listTasks(filter?)
  updateTask(taskId, patch)
  stopTask(taskId)
  appendTaskOutput(taskId, message)
  notifyTaskCompletion(taskId, summary)
}
```

### 13.7 模块 G，Memory Runtime

```ts
class MemoryRuntime {
  loadMemory(projectPath)
  findRelevantMemories(query)
  injectMemory(systemPrompt, memory)
  startRelevantMemoryPrefetch(query)
  extractMemories(messages)
  compactMessages(messages)
  createCompactBoundary()
  runAutoDream(sessionId)
}
```

### 13.8 模块 H，Mailbox / Team Runtime

```ts
class TeamRuntime {
  createTeam(name)
  spawnTeammate(teamName, agentConfig)
  sendMessage(from, to, message)
  pollMailbox(agentId)
  syncPermissionRequests()
  updateSharedMemory(teamName, patch)
}
```

---

## 14. 完整数据流，升级版

```text
User Request / Webhook / Cron
        │
        ▼
Ingress Router
        │
        ▼
Session Resolver
        ├── main session
        ├── background task session
        ├── sidechain agent session
        └── team agent session
        │
        ▼
Query Engine
        │
        ├── load system prompt
        ├── load user context
        ├── load system context
        ├── start relevant memory prefetch
        ├── preprocess messages
        │   ├── tool result budget
        │   ├── snip
        │   ├── microcompact
        │   ├── context collapse
        │   └── autocompact
        │
        ├── normalize for API
        ├── stream model call
        │   ├── collect assistant text
        │   ├── collect thinking
        │   ├── collect tool_use
        │   └── start streaming tool execution
        │
        ├── run tool pipeline
        │   ├── validate input
        │   ├── permission check
        │   ├── hooks
        │   ├── tool.call
        │   ├── result mapping
        │   └── post hooks
        │
        ├── collect attachments
        │   ├── memory attachments
        │   ├── task notifications
        │   ├── file change attachments
        │   └── skill discovery attachments
        │
        ├── persist transcript
        │   ├── clean messages
        │   ├── dedup
        │   ├── parentUuid chain
        │   ├── enqueue write
        │   └── background drain
        │
        ├── if no tool_use → completed
        ├── if abort → aborted
        ├── if maxTurns → max_turns_reached
        ├── if recoverable error → recover and retry
        └── else continue loop
```

---

## 15. 面向“一人公司系统”的具体落地建议

这是最重要的部分，我直接给你推荐一个落地形态。

### 15.1 系统角色设计

#### 主控层

- `Founder/CEO Agent`
  - 接用户目标
  - 拆战略目标
  - 决定优先级
  - 读取汇总结果

#### 规划层

- `PM Agent`
  - 输出 PRD、roadmap、任务树

#### 情报层

- `Research Agent`
  - 竞品分析、市场研究、用户研究、技术调研

#### 执行层

- `Engineer Agent`
  - 编码、部署脚本、API、自动化
- `Designer/Content Agent`
  - landing page、文案、品牌、内容
- `Growth Agent`
  - SEO、投放、销售脚本、邮件

#### 质量与运营层

- `QA/Reviewer Agent`
  - 验证、review、测试
- `Ops Agent`
  - cron、预算、日志、告警、系统运行

### 15.2 运行模式建议

#### 模式 A，同步短任务

例如：

- “帮我总结今天项目状态”
- “帮我看这个文件怎么改”

走 sync subagent 即可。

#### 模式 B，后台深任务

例如：

- “做一份完整竞品分析”
- “实现 onboarding 功能并自测”
- “做增长实验方案并生成页面文案”

走 LocalAgentTask/RemoteAgentTask。

#### 模式 C，长驻职能团队

例如：

- CEO 持续派任务给 Engineer / Growth / Research
- 各 agent 有 inbox 和 shared memory
- 每天自动汇报

走 Teammate/Swarm 模式。

### 15.3 最推荐的最小起步版本

如果你要尽快把 Web 后端跑起来，我建议按这个顺序实现：

#### Phase 1，单会话智能体

- transcript
- query loop
- tool runtime
- permissions
- memory injection

#### Phase 2，后台 agent

- LocalAgentTask
- task list/get/output/stop
- XML/JSON notification
- sidechain transcript

#### Phase 3，多职能团队

- Agent definitions
- tool filtering
- shared memory
- mailbox
- coordinator

#### Phase 4，真正一人公司自动化

- cron
- webhook ingress
- remote tasks
- budget / KPI / dashboard
- auto-dream / long-term memory maintenance

---

## 16. 对你原始 plan 的直接修订结论

你的原始 plan 是一个很好的骨架，但要升级成真正可用的系统，需要做以下 10 个关键修订：

### 修订 1
把 8 层升级为 12 层，单独拆出：

- 模型运行时层
- 任务通信层
- 基础设施层

### 修订 2
会话层不能只写 `SessionStorage / Resume`，必须加入：

- JSONL event log
- metadata tail
- snapshots
- sidechain transcripts
- queue ops

### 修订 3
查询层不能只写 `QueryLoop`，必须加入：

- microcompact
- context collapse
- autocompact
- fallback recovery
- max_output_tokens recovery

### 修订 4
工具层不能只写 registry/execution，必须加入：

- partition batching
- streaming executor
- large result persistence
- result post-processing

### 修订 5
权限层必须扩展为：

- rules
- hooks
- classifier
- interactive approval
- denial tracking

### 修订 6
Agent 层必须从“spawn subagent”升级成：

- sync subagent
- async background agent
- remote task agent
- teammate/swarm
- coordinator

### 修订 7
Memory 层必须从“CLAUDE.md + memory dir”升级成：

- session memory
- durable memory
- transcript archive
- codebase reality
- extract + auto-dream

### 修订 8
加入 Task Bus 作为一等公民，不要让多 Agent 只靠 SendMessage。

### 修订 9
加入 Mailbox / Team Memory，用于持久角色协作。

### 修订 10
针对 Web 后端，增加：

- approval center
- task dashboard
- agent inbox
- memory console

---

## 17. 最终建议版本，一句话总结

> 你要做的不是“Claude Code 的一个简化版”，而是 **把 Claude Code 的 Query Loop、Tool Runtime、Session Transcript、Task Bus、Memory Runtime、Agent Swarm 这些核心思想抽象出来，做成一个面向 Web 后端的一人公司操作系统**。

它的核心不应该只是“多 Agent”，而应该是：

- **可恢复的会话系统**
- **可调度的任务系统**
- **可隔离的 Agent 运行时**
- **可分层的记忆系统**
- **可审计的工具执行系统**
- **可持续运行的团队协作系统**

如果你愿意，我下一步可以继续直接帮你把这个 `qai-design.md` 再往下扩成第二版，也就是：

1. **目录级工程结构设计**
2. **TypeScript 接口定义全集**
3. **数据库表结构 / JSONL 文件结构**
4. **Web 后端 API 设计**
5. **多 Agent 一人公司角色模板**
6. **最小可运行 MVP 实施路线图**

这个会非常适合你后面真正开工实现。