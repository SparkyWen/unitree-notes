# QAI Design 1

## 基于 Claude Code 的完整多 Agent、多工具、有记忆系统设计

## 1. 设计定位

本文不是对 Claude Code 做表层模仿，而是基于以下两类材料，把你的原始 8 层方案升级成一个可在 **Web 后端** 跑起来的、可恢复、可审计、可扩展的 **一人公司多 Agent 运行时**：

### 1.1 直接依据的笔记

- `CCLearn/notes/notes_integrated/1. 全局框架与目录清单.md`
- `CCLearn/notes/notes_integrated/2. 全局架构图.md`
- `CCLearn/notes/notes_integrated/3. 多agent的通信.md`
- `CCLearn/notes/notes_integrated/4. 多agent4层通信机制和通信隔离.md`
- `CCLearn/notes/notes_integrated/5. 记忆召回与处理机制.md`
- `CCLearn/notes/notes_integrated/6. Transcript 注入、缓存、prompt拼接.md`

### 1.2 直接映射的源码

- `CCLearn/source/src/QueryEngine.ts`
- `CCLearn/source/src/query.ts`
- `CCLearn/source/src/Tool.ts`
- `CCLearn/source/src/tools.ts`
- `CCLearn/source/src/services/tools/toolExecution.ts`
- `CCLearn/source/src/utils/sessionStorage.ts`
- `CCLearn/source/src/assistant/sessionHistory.ts`
- `CCLearn/source/src/tools/AgentTool/agentToolUtils.ts`
- `CCLearn/source/src/tools/AgentTool/runAgent.ts`
- `CCLearn/source/src/tools/AgentTool/forkSubagent.ts`
- `CCLearn/source/src/tasks/LocalAgentTask/LocalAgentTask.tsx`
- `CCLearn/source/src/memdir/findRelevantMemories.ts`
- `CCLearn/source/src/memdir/memoryScan.ts`
- `CCLearn/source/src/services/extractMemories/extractMemories.ts`
- `CCLearn/source/src/utils/permissions/permissions.ts`

### 1.3 最核心的判断

你的原始分层方向是对的，但还不够完整。Claude Code 真正成熟的地方，不只是 Query Loop + Tool Use + Memory，而是把整个系统做成了：

1. **事件流驱动** 的消息运行时
2. **Append-only transcript** 的持久化系统
3. **同步子代理 + 异步任务代理** 并存的 agent runtime
4. **多通道通信总线**，而不是单一 agent call
5. **多层记忆体系**，而不是把 transcript 当作 memory
6. **可压缩、可恢复、可限权、可审计** 的后端内核

所以，面向 Web 后端，你的方案应该从 8 层升级为 **12 层运行架构 + 6 个核心引擎 + 4 条通信总线 + 3 级记忆平面 + 2 类 Agent 生命周期**。

---

## 2. 从 notes_integrated 读出的 6 个关键设计结论

### 2.1 来自笔记 1，整体框架不是单体脚本，而是门控式运行时

`1. 全局框架与目录清单.md` 的重点是：

- Feature Gates 决定功能是否编译/启用
- 动态导入降低初始化负担
- `buildTool()` / Tool factory 体现工具是运行时拼装的
- Query Loop 使用 `AsyncGenerator`
- 交互模式和 headless 模式共用同一内核

这意味着你的系统必须把 **UI、运行时、工具、任务、持久化** 解耦，Web 只是一个入口，不是系统本体。

### 2.2 来自笔记 2，系统必须分成交互层、引擎层、工具层、服务层、基础设施层

`2. 全局架构图.md` 很明确地说明：

- 入口和交互不等于执行内核
- Headless 和 REPL 只是两种前端外壳
- 关键分流点在 mode dispatch
- 主调用链分为启动链、单轮对话链、agent 链、bridge 链

所以你的 Web 系统也应该支持：

- 直接会话请求
- headless API 任务请求
- 子 agent 请求
- 跨会话/跨设备 bridge 请求

### 2.3 来自笔记 3 和 4，多 Agent 通信不是一条链路，而是多层协作

两份多 agent 笔记共同给出的最重要结论是：Claude Code 的 agent 通信不是“agent A 直接调用 agent B”，而是以下并存机制：

1. Tool-level orchestration
2. Task-centric communication
3. Mailbox / queued message communication
4. Swarm / teammate backend communication
5. Bridge / remote communication
6. Shared memory / team memory 间接通信

所以你的一人公司系统必须内建 **多条通信总线**，不能只做一个 `spawnAgent()`。

### 2.4 来自笔记 5，Memory 检索和 transcript 历史不是一回事

`5. 记忆召回与处理机制.md` 的核心结论非常关键：

- `.md` durable memory 才是 relevant memory 主检索面
- `JSONL transcript` 主要用于 resume、归档、窄搜索、自动提炼
- 代码事实检索依赖 Grep/Glob/Read，不走 memory manifest
- `CLAUDE.md + git + repo context` 是启动时静态注入层

因此你的系统必须区分：

- 工作记忆
- Durable memory
- Transcript archive
- 代码事实检索

### 2.5 来自笔记 6，Transcript 不是聊天记录，而是可恢复执行日志

`6. Transcript 注入、缓存、prompt拼接.md` 明确说明：

- JSONL 内有多种 record types，不只是 user/assistant
- `parentUuid` 是链式恢复关键
- `requestId` 关联一次 API 交互
- `signature` 和 thinking block 必须黑盒保留
- prompt 拼接、cache、附件、tool_result 都会进入 transcript 体系

所以 transcript 层必须按 **运行日志** 设计，不能按普通 IM 历史设计。

### 2.6 源码进一步证明，Claude Code 的核心其实是一个后端 runtime

从 `QueryEngine.ts`、`query.ts`、`toolExecution.ts`、`sessionStorage.ts`、`runAgent.ts` 看，Claude Code 本质上已经是一个强 runtime，只是默认壳子是 CLI/REPL。

你的目标若是 Web 后端化，那么正确方向不是“做个网页版聊天壳”，而是：

- 把 Claude Code 风格 runtime 服务化
- 把 session/task/memory/tool/agent 抽象成后端资源
- 把 UI 当作 observer 与 control plane

---

## 3. 升级后的总体架构，8 层改 12 层

```text
┌──────────────────────────────────────────────────────────────┐
│ Layer 0. 接入层 Ingress                                      │
│ Web API / WebSocket / Cron / Webhook / IDE / CLI            │
├──────────────────────────────────────────────────────────────┤
│ Layer 1. 交互呈现层 Interaction                              │
│ Chat UI / Agent Monitor / Task Panel / Admin Console        │
├──────────────────────────────────────────────────────────────┤
│ Layer 2. 会话与状态层 Session State                          │
│ SessionStorage / Transcript / Resume / AppState / TaskState │
├──────────────────────────────────────────────────────────────┤
│ Layer 3. 查询引擎层 Query Engine                             │
│ Prompt Assembly / Normalize / Query Loop / Follow-up        │
├──────────────────────────────────────────────────────────────┤
│ Layer 4. 模型运行时层 Model Runtime                          │
│ Streaming API / Retry / Fallback / Budget / Usage           │
├──────────────────────────────────────────────────────────────┤
│ Layer 5. 工具编排层 Tool Orchestration                       │
│ Registry / Permission Gate / Streaming Executor / ResultMap │
├──────────────────────────────────────────────────────────────┤
│ Layer 6. 权限安全层 Permission & Safety                      │
│ Rules / Hooks / Classifier / Approval / Audit               │
├──────────────────────────────────────────────────────────────┤
│ Layer 7. Agent 运行时层 Agent Runtime                        │
│ Sync Agent / Async Agent / Team / Worktree / Sidechain      │
├──────────────────────────────────────────────────────────────┤
│ Layer 8. 任务通信层 Task & Communication                     │
│ Task Bus / Mailbox / Notification / Bridge / Swarm          │
├──────────────────────────────────────────────────────────────┤
│ Layer 9. 记忆上下文层 Memory & Context                       │
│ CLAUDE.md / MemoryDir / Recall / Extract / Compact / Dream  │
├──────────────────────────────────────────────────────────────┤
│ Layer 10. 外部集成层 Integrations                            │
│ MCP / Filesystem / Git / Browser / Search / SaaS APIs       │
├──────────────────────────────────────────────────────────────┤
│ Layer 11. 基础设施层 Infrastructure                           │
│ JSONL Store / Queue / Object Store / Locks / Telemetry      │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 为什么必须升级为 12 层

因为你现在的目标不再是“对话助手”，而是“多 Agent 的一人公司操作系统”。

少掉其中任何一层，都会出问题：

- 没有 Layer 2，无法 resume、回放、审计
- 没有 Layer 4，无法优雅处理超长上下文、fallback、streaming 恢复
- 没有 Layer 8，多 Agent 就会退化成函数嵌套
- 没有 Layer 11，系统会缺少 durability、限流、幂等、队列与观测

---

## 4. 核心运行对象模型

## 4.1 Message 是系统第一公民

```ts
type RuntimeMessage =
  | UserMessage
  | AssistantMessage
  | ToolResultMessage
  | AttachmentMessage
  | SystemMessage
  | ProgressMessage
  | CompactBoundaryMessage
  | TaskNotificationMessage
```

设计原则：

- UI 渲染的是 Message
- Query Loop 消费和产出的是 Message
- Transcript 存的是 Message envelope
- Agent 间传递的也是 Message 或其变体
- 记忆提炼输入仍然从 Message 序列中抽取

## 4.2 Session 不是单个聊天窗口，而是可恢复执行域

```ts
type Session = {
  sessionId: string
  userId: string
  workspaceId: string
  mode: 'interactive' | 'headless' | 'bridge' | 'task'
  status: 'idle' | 'running' | 'blocked' | 'failed' | 'completed'
  transcriptPath: string
  currentModel: string
  permissionMode: 'default' | 'auto' | 'plan' | 'bypass'
  activeTaskIds: string[]
  rootAgentId: string
}
```

## 4.3 Agent 是运行时上下文，不只是 prompt persona

```ts
type AgentRuntime = {
  agentId: string
  sessionId: string
  agentType: string
  parentAgentId?: string
  mode: 'sync' | 'async' | 'remote'
  messages: RuntimeMessage[]
  readFileState: object
  abortController: AbortController
  toolPermissionContext: object
  worktree?: string
  sidechainTranscriptPath: string
}
```

## 4.4 Task 是多 Agent 协作总线

```ts
type Task = {
  taskId: string
  type: 'local_agent' | 'remote_agent' | 'workflow' | 'tool_job'
  status: 'queued' | 'running' | 'completed' | 'failed' | 'killed'
  ownerSessionId: string
  ownerAgentId: string
  outputPath?: string
  pendingMessages: string[]
  notificationState: 'none' | 'queued' | 'sent'
}
```

---

## 5. 你的 6 大模块，升级成可落地后端设计

# 模块 1，会话持久化引擎

你的原方案基本正确，但需要从“保存聊天历史”升级为“保存运行日志 + 恢复链 + 元数据尾索引”。

## 5.1 从源码抽出的真实设计点

来自 `utils/sessionStorage.ts`：

- `isTranscriptMessage()` 明确只把 user / assistant / attachment / system 视为 transcript message
- `isChainParticipant()` 明确 `progress` 不参与 `parentUuid` 链
- `getTranscriptPath()` / `getAgentTranscriptPath()` 将主会话与 sidechain transcript 物理隔离
- `recordTranscript()` 与 `recordSidechainTranscript()` 是主链和子链的两个入口
- `buildConversationChain()` 用 `parentUuid` 重建可恢复对话链
- `recoverOrphanedParallelToolResults()` 处理异常中断后的并行工具结果
- `reAppendSessionMetadata()` 把元数据重新写回文件尾部，供快速读取
- `loadTranscriptFile()` / `loadTranscriptFromFile()` 说明 transcript 是可回放状态源，而不只是日志

## 5.2 推荐的设计目标

### 你要保留的 Claude Code 特性

1. JSONL append-only
2. message-level UUID
3. parentUuid 链接
4. sidechain transcript 独立文件
5. EOF metadata 快速扫描
6. progress 与 durable message 分离
7. tool result / attachment / summary / compact boundary 统一个文件协议
8. resume 时可重建 conversation chain

## 5.3 推荐数据结构

```ts
type TranscriptEntry =
  | TranscriptMessageEntry
  | QueueOperationEntry
  | FileHistorySnapshotEntry
  | AttributionSnapshotEntry
  | CompactBoundaryEntry
  | ContentReplacementEntry
  | ContextCollapseCommitEntry
  | ContextCollapseSnapshotEntry
  | SessionMetadataEntry
  | AgentMetadataEntry

type TranscriptMessageEntry = {
  type: 'user' | 'assistant' | 'attachment' | 'system'
  uuid: string
  parentUuid: string | null
  logicalParentUuid?: string | null
  sessionId: string
  agentId?: string
  isSidechain: boolean
  requestId?: string
  timestamp: string
  cwd?: string
  gitBranch?: string
  version?: string
  message: unknown
}
```

## 5.4 关键接口，建议你这样改

```ts
interface SessionTranscriptStore {
  recordTranscript(messages: RuntimeMessage[]): Promise<void>
  recordSidechainTranscript(
    messages: RuntimeMessage[],
    agentId: string,
    parentUuid?: string | null,
  ): Promise<void>
  insertMessageChain(
    messages: RuntimeMessage[],
    options: {
      isSidechain: boolean
      agentId?: string
      tailParentUuid?: string | null
    },
  ): Promise<void>
  appendEntry(entry: TranscriptEntry): Promise<void>
  enqueueWrite(filePath: string, entry: TranscriptEntry): Promise<void>
  drainWriteQueue(): Promise<void>
  reAppendSessionMetadata(): void
  flush(): Promise<void>
  loadConversationChain(sessionId: string): Promise<RuntimeMessage[]>
}
```

## 5.5 写入路径应该这样分层

### 层 A，内存队列

- 接收每次 `recordTranscript()` 调用
- 基于 `uuid` 做幂等去重
- 同文件路径聚合写入批次
- 允许小延迟批量刷盘

### 层 B，物理文件路由

- 主 session 写 `sessionId.jsonl`
- 子 agent 写 `subagents/agent-{agentId}.jsonl`
- 远程 agent 写 `remote-agents/{taskId}.jsonl` 或 API ingress

### 层 C，尾部 metadata 更新

- 会话标题
- 标签
- 最后活动时间
- agent 颜色/名称
- worktree 状态
- compact state

## 5.6 Web 后端额外增强

建议增加双写：

- **JSONL** 作为原始事实源
- **Postgres/SQLite 索引表** 作为查询加速层

也就是：

```text
Runtime Event -> JSONL append -> Async indexer -> SQL/materialized views
```

这样你既保留 Claude Code 的恢复能力，也能在 Web UI 高效查询：

- 最近会话
- 子 agent 轨迹
- 任务列表
- requestId 维度的调用审计

## 5.7 必做的异常恢复

1. 写一半崩溃，必须允许 JSONL 尾部截断恢复
2. sidechain 缺失时，主任务状态仍可显示 basic state
3. 并行 tool result 孤儿化时，恢复逻辑要能桥接
4. compact boundary 前的 preserved tail 要先落盘，再写 compact marker
5. transcript 超大时，要有 lite read 和 tail read

## 5.8 会话持久化模块最终结论

你要实现的不是 chat history storage，而是：

**可恢复的执行日志系统 + sidechain event store + metadata tail index。**

---

# 模块 2，查询循环

这是全系统的心脏。

## 6.1 从源码抽出的真实结构

来自 `query.ts` 和 `QueryEngine.ts`：

- `QueryEngine` 负责会话入口、system prompt 组装、用户输入落 transcript、状态搭桥
- `query()` 才是真正的无限主循环，源码里明确存在 `while (true)`
- 一轮 query 内部还包含一次 API loop，用于 fallback / streaming retry
- turn 开始时会调用 `startRelevantMemoryPrefetch()`
- 在发 API 前会执行 `applyToolResultBudget()`、snip、microcompact、contextCollapse、autocompact
- 模型流式返回时，`StreamingToolExecutor` 可边流边执行工具
- 如果发生 `FallbackTriggeredError`、prompt-too-long、max-output-tokens 等错误，会走恢复路径而不是直接失败
- `QueryEngine.ts` 会在进入 query loop 前先把用户消息写入 transcript，确保中途崩溃也可 resume

## 6.2 你的查询引擎应该拆成两层

### A. Session Query Coordinator

职责类似 `QueryEngine.ts`：

- 处理入口请求
- 处理 slash/meta 指令
- 准备 `toolUseContext`
- 在 query 前先写入用户输入
- 将 SDK/UI/transport 与 query() 解耦

### B. Core Query Loop

职责类似 `query.ts`：

- 拼 prompt
- 调模型
- 流式解析
- 执行工具
- 收附件
- 继续 follow-up
- 压缩 / 恢复 / fallback
- 终止并输出最终结果

## 6.3 推荐状态机

```text
IDLE
 -> PREPARE_CONTEXT
 -> APPLY_MEMORY_PREFETCH
 -> PREPROCESS_MESSAGES
 -> CALL_MODEL_STREAM
 -> COLLECT_ASSISTANT_BLOCKS
 -> EXECUTE_TOOL_CALLS
 -> COLLECT_ATTACHMENTS
 -> PERSIST_MESSAGES
 -> NEEDS_FOLLOW_UP ? CALL_MODEL_STREAM : FINALIZE
 -> DONE
```

异常支路：

```text
PROMPT_TOO_LONG -> CONTEXT_COLLAPSE / REACTIVE_COMPACT -> RETRY
MAX_OUTPUT_TOKENS -> RAISE_LIMIT / FALLBACK_MODEL -> RETRY
ABORT -> RETURN ABORTED
MAX_TURNS -> YIELD MAX_TURNS_REACHED
FATAL_ERROR -> RETURN ERROR
```

## 6.4 你原流程需要补上的 8 个细节

### 细节 1，预查询处理不是只有 normalize

真实顺序应接近：

1. `startRelevantMemoryPrefetch()`
2. `applyToolResultBudget()`
3. `snipCompactIfNeeded()`
4. `microcompact()`
5. `contextCollapse.applyCollapsesIfNeeded()`
6. `autocompact()`
7. `appendSystemContext()`
8. `prependUserContext()`
9. `normalizeMessagesForAPI()`

### 细节 2，tool result 需要预算治理

`applyToolResultBudget()` 的意义是：

- 大工具结果不一定直接回灌给模型
- 需要改写为文件引用或压缩摘要
- 这是降低上下文爆炸的关键策略

### 细节 3，compact 不是一次功能，而是 4 级体系

你至少要有：

1. Snip compact
2. Microcompact
3. Context collapse
4. Auto/reactive compact

### 细节 4，流式响应期间就要启动工具执行

不能等 assistant message 整条结束才开始跑。

Claude Code 的思路是：

- 一边收流
- 一边发现 `tool_use`
- 一边把任务塞给 `StreamingToolExecutor`

这会显著降低端到端延迟。

### 细节 5，API loop 和 turn loop 不是同一层

建议保留两层循环：

```ts
while (turnNotFinished) {
  while (attemptWithFallback) {
    stream model
    if fallback triggered then retry
  }
  run tools
  if no tool use break
}
```

### 细节 6，用户消息要在 query 之前持久化

这是 `QueryEngine.ts` 的一个很重要的鲁棒性设计。否则用户刚发完消息，系统崩了，resume 会找不到这一轮起点。

### 细节 7，query 退出条件要完整

不是只有“没有 tool use”。还要包括：

- aborted
- maxTurns
- blocking limit
- unrecoverable invalid request
- permission dead-end
- stop hook blocked

### 细节 8，follow-up 消息不只是 tool_result

还应包含：

- attachments
- task notifications
- compact boundary messages
- discovered skill notices
- queued message drains

## 6.5 推荐伪代码

```ts
async function* queryLoop(state: QueryState): AsyncGenerator<RuntimeEvent> {
  using pendingMemoryPrefetch = startRelevantMemoryPrefetch(state.messages)

  while (true) {
    let messagesForQuery = cloneVisibleMessages(state.messages)

    messagesForQuery = await applyToolResultBudget(messagesForQuery)
    messagesForQuery = await snip(messagesForQuery)
    messagesForQuery = await microcompact(messagesForQuery)
    messagesForQuery = await contextCollapse(messagesForQuery)

    const compacted = await autoCompactIfNeeded(messagesForQuery)
    if (compacted) {
      yield* compacted.boundaryMessages
      state.messages = compacted.postCompactMessages
      continue
    }

    const fullSystemPrompt = assembleSystemPrompt(state)
    const apiMessages = normalizeMessagesForAPI(
      prependUserContext(messagesForQuery),
      state.tools,
    )

    const stream = callModelStream(apiMessages, fullSystemPrompt)
    const toolExecutor = new StreamingToolExecutor(...)

    for await (const chunk of stream) {
      const event = parseChunk(chunk)
      yield event
      if (event.type === 'tool_use') toolExecutor.addTool(event)
    }

    const toolResults = await toolExecutor.getRemainingResults()
    const attachments = await collectAttachments(state)

    state.messages.push(...assistantMessages, ...toolResults, ...attachments)
    await recordTranscript([...assistantMessages, ...toolResults, ...attachments])

    if (!hasToolUse(assistantMessages)) return
    if (state.turnCount >= state.maxTurns) return
  }
}
```

## 6.6 查询循环模块最终结论

你要实现的是：

**一个带恢复路径、带上下文治理、带流式工具执行、带递归 follow-up 的查询状态机。**

---

# 模块 3，工具注册与执行

你的原接口思路是对的，但 Claude Code 的真实工具系统比这个更厚。

## 7.1 从源码抽出的真实工具模型

来自 `Tool.ts`、`tools.ts`、`toolExecution.ts`：

- `Tool` 除了 `name / inputSchema / call` 外，还有 `description()`、`prompt()`、`isConcurrencySafe()`、`isReadOnly()`、`checkPermissions()`、`validateInput()`、`backfillObservableInput()`、`getToolUseSummary()`、`getActivityDescription()`、`interruptBehavior()`、`toAutoClassifierInput()` 等
- `tools.ts` 中 `getAllBaseTools()` 说明工具池是运行时组装的，不是写死数组
- `filterToolsByDenyRules()` 说明权限会在“工具暴露给模型之前”先做一轮裁剪
- `assembleToolPool()` / `getMergedTools()` 说明 built-in tools 与 MCP tools 需要统一管理
- `toolExecution.ts` 说明真实执行链是：validate -> pre hooks -> permission -> call -> map result -> post hooks -> telemetry

## 7.2 工具系统应拆成 5 层

### 层 A，Tool Definition

定义工具能力和 schema。

### 层 B，Tool Registry

动态加载 built-in、MCP、plugin、team tool。

### 层 C，Tool Exposure Filter

根据权限、agent 类型、模式、feature gates 过滤掉不能让模型看到的工具。

### 层 D，Tool Runtime Executor

负责 validate / hooks / permission / call / result storage / telemetry。

### 层 E，Streaming Execution Coordinator

负责在模型 streaming 过程中尽早并行启动工具。

## 7.3 推荐接口，应该比你原版更完整

```ts
interface Tool<Input, Output> {
  name: string
  aliases?: string[]
  inputSchema: ZodSchema<Input>
  outputSchema?: ZodSchema<Output>

  prompt(options: ToolPromptOptions): Promise<string>
  description(input: Input, options: ToolDescriptionOptions): Promise<string>

  validateInput?(input: Input, context: ToolUseContext): Promise<ValidationResult>
  checkPermissions(input: Input, context: ToolUseContext): Promise<PermissionResult>

  call(
    input: Input,
    context: ToolUseContext,
    canUseTool: CanUseToolFn,
    parentMessage: AssistantMessage,
    onProgress?: ToolCallProgress,
  ): Promise<ToolResult<Output>>

  mapToolResultToToolResultBlockParam?(
    content: Output,
    toolUseId: string,
  ): ToolResultBlockParam

  isConcurrencySafe(input: Input): boolean
  isReadOnly(input: Input): boolean
  isDestructive?(input: Input): boolean
  interruptBehavior?(): 'cancel' | 'block'
  isEnabled(): boolean
  requiresUserInteraction?(): boolean
  getToolUseSummary?(input: Partial<Input>): string | null
  getActivityDescription?(input: Partial<Input>): string | null
  toAutoClassifierInput(input: Input): unknown
}
```

## 7.4 真正的执行链

```text
assistant.tool_use
 -> locate tool
 -> backfill observable input
 -> validateInput
 -> runPreToolUseHooks
 -> checkPermissions / canUseTool
 -> tool.call
 -> processToolResultBlock
 -> runPostToolUseHooks
 -> persist oversized result if needed
 -> emit tool_result
```

## 7.5 并发策略不能只做布尔值，需要分区批执行

你原来写的 `isConcurrencySafe()` 是必要的，但不够。

建议执行器支持：

- 并发安全工具，同批并行
- 非并发安全工具，串行执行
- destructive 工具单独批次
- requiresUserInteraction 工具阻塞批次
- 同路径写操作，按资源锁串行

## 7.6 大结果处理必须升级成内容替换层

Claude Code 在 query 前就会应用 `applyToolResultBudget()`，这说明结果管理不是单点逻辑，而是：

1. 工具返回原始内容
2. 若超过阈值，保存到磁盘/object storage
3. transcript 记录 content replacement entry
4. 后续 query 只回灌 preview + path/reference

因此你的 Web 后端应提供：

```ts
interface ToolResultStorage {
  persistLargeResult(toolUseId: string, content: string | object): Promise<ResultRef>
  buildPreview(ref: ResultRef): string
  materialize(ref: ResultRef): Promise<string>
}
```

## 7.7 StreamingToolExecutor 必须成为独立组件

因为它解决的是两个问题：

- 提前执行 tool，降低延迟
- 统一管理 queued -> executing -> completed -> yielded 状态机

这不是单个工具能负责的。

## 7.8 工具模块最终结论

你要实现的是：

**动态工具池 + 暴露前过滤 + 流式执行器 + 权限包裹器 + 大结果治理层。**

---

# 模块 4，权限系统

这是你原方案里最容易低估的模块。

## 8.1 从源码抽出的真实权限结构

来自 `utils/permissions/permissions.ts` 和 `toolExecution.ts`：

- 工具权限不仅在 `checkPermissions()` 里，还会结合全局 `canUseTool` 执行
- 规则分 `allow / deny / ask`
- 规则按 tool name 和 rule content 匹配
- 存在 `filterToolsByDenyRules()` 这种 **暴露前过滤**
- 还存在 PermissionRequest hooks，用于 headless/async agent 环境的策略决策
- auto / plan 模式下，可由 classifier 自动决定是否放行
- 连续拒绝会做 denial tracking，避免重复询问
- 某些 safetyCheck 即使 auto 模式也不能自动放过

## 8.2 你的权限系统至少要有 4 层决策

### 第 0 层，暴露前过滤

模型压根看不到某些工具。

### 第 1 层，规则检查

allow/deny/ask，来源包括：

- 系统 policy
- workspace settings
- session overrides
- user grants
- agent-specific deny list

### 第 2 层，Hook 决策

例如：

- pre-tool hook
- permission request hook
- swarm/leader bridge permission sync
- remote permission bridge

### 第 3 层，interactive / classifier 决策

- 人工批准
- auto classifier
- plan-mode 批准
- dontAsk 自动拒绝

## 8.3 推荐权限对象模型

```ts
type PermissionRule = {
  tool: string
  pattern?: string
  source: 'system' | 'workspace' | 'session' | 'user' | 'policy' | 'agent'
  behavior: 'allow' | 'deny' | 'ask'
}

type PermissionContext = {
  mode: 'default' | 'auto' | 'plan' | 'dontAsk' | 'bypass'
  allowRules: PermissionRule[]
  denyRules: PermissionRule[]
  askRules: PermissionRule[]
  shouldAvoidPermissionPrompts: boolean
  denialTracking?: {
    consecutiveDenials: number
    lastToolName?: string
  }
}
```

## 8.4 推荐统一入口

```ts
async function checkPermissions(
  tool: Tool,
  input: unknown,
  context: ToolUseContext,
): Promise<{
  behavior: 'allow' | 'deny' | 'ask'
  updatedInput?: unknown
  reason?: string
  source?: string
}> {
  // 1. validate input
  // 2. static rule check
  // 3. hook check
  // 4. tool.checkPermissions
  // 5. classifier or user interaction
  // 6. denial tracking update
}
```

## 8.5 Agent 权限必须单独切面化

多 Agent 系统中最危险的是：父 Agent 把自己的全部工具权限继承给子 Agent。

Claude Code 风格里，至少有这些限制：

- `filterToolsForAgent()` 根据 agent source、mode、async/sync 过滤工具
- `ALL_AGENT_DISALLOWED_TOOLS` 一类全局禁止项
- async agent 只允许子集工具
- in-process teammate 和 background async agent 的权限不同
- `Agent(agentType)` 规则可以直接 deny 某类 agent

所以你必须做：

```ts
resolvedTools = resolveAgentTools(agentDefinition, availableTools)
resolvedTools = filterToolsForAgent(...)
resolvedTools = applyPermissionRules(...)
```

## 8.6 对 Web 后端的额外建议

### 把审批面板独立成一个服务面

你需要：

- 待批准操作队列表
- 批准 token / single-use approval
- 审批超时
- 审批消息回灌到 session

### 审计日志必须落地

每次决策至少记录：

- sessionId
- agentId
- toolName
- input hash
- final behavior
- decision source
- whether classifier involved

## 8.7 权限系统最终结论

你要实现的是：

**暴露前裁剪 + 规则系统 + hook 系统 + classifier / approval 系统 + denial tracking 的组合权限内核。**

---

# 模块 5，Agent 管理

这是整个一人公司系统的第二个心脏。

## 9.1 从源码抽出的真实 Agent 形态

来自 `agentToolUtils.ts`、`runAgent.ts`、`forkSubagent.ts`、`LocalAgentTask.tsx`：

- `filterToolsForAgent()` 会根据 built-in/custom、async、permissionMode 做工具过滤
- `resolveAgentTools()` 支持 wildcard、disallowedTools、allowedAgentTypes
- `runAgent.ts` 会创建子 agent context，并调用递归 `query()`
- 子 agent 会调用 `recordSidechainTranscript()` 把 sidechain 单独落盘
- `writeAgentMetadata()` 会记录 agentType/worktree/description
- `LocalAgentTaskState` 有 `pendingMessages`、`retain`、`diskLoaded`、`evictAfter`
- `queuePendingMessage()` / `drainPendingMessages()` 说明后台 agent 与主会话之间有 mailbox 机制
- `enqueueAgentNotification()` 用 XML `task-notification` 把任务结果投递回主会话
- `forkSubagent.ts` 体现了 fork child 与普通 subagent 的 prompt cache / worktree / message build 细节

## 9.2 你应该把 Agent 分成两大类

### A. 同步 Agent

特征：

- 在父 query 中调用
- 阻塞父 turn
- 本质是递归 query loop
- 常用于 Explore/Plan/Review/Research 这类短任务

### B. 异步 Agent

特征：

- 作为 task 后台运行
- 主对话立即返回 task handle
- 持续写 sidechain transcript
- 完成后发 notification
- 可跨 session 读取输出

## 9.3 Agent 运行时必须独立的资源

每个 agent 至少隔离：

1. `messages`
2. `readFileState`
3. `abortController`
4. `toolPermissionContext`
5. `todo/task state`
6. `transcript file`
7. `working directory / worktree`
8. `agent metadata`

如果这些不独立，你的多 agent 系统会出现：

- 文件状态串扰
- 上下文污染
- 权限泄漏
- 子 agent 写日志覆盖主链
- 取消信号误伤其他任务

## 9.4 推荐 Agent API

```ts
interface AgentManager {
  spawnSyncAgent(request: SpawnAgentRequest): Promise<AgentResult>
  spawnAsyncAgent(request: SpawnAgentRequest): Promise<TaskHandle>
  createSubagentContext(
    parent: ToolUseContext,
    overrides: SubagentOverrides,
  ): ToolUseContext
  filterToolsForAgent(tools: Tool[], agentDef: AgentDefinition): Tool[]
  enqueueNotification(taskId: string, payload: TaskNotification): Promise<void>
  sendMailboxMessage(taskId: string, text: string): Promise<void>
}
```

## 9.5 你必须实现的 4 条 Agent 通信总线

### 总线 1，递归 query 总线

同步子 agent 的最短路径。

### 总线 2，Task 总线

后台 agent 生命周期管理。

### 总线 3，Mailbox 总线

`pendingMessages` / queued messages，允许主会话向后台 agent 发新指令。

### 总线 4，Notification 总线

通过 `task-notification` 把结果回灌给主 session。

如果你要做到更完整，还应再加：

### 总线 5，Bridge / Remote 总线

支持跨设备/跨服务器 agent。

### 总线 6，Team Memory 总线

agent 之间通过共享记忆间接协作。

## 9.6 建议你保留 Claude Code 的 sidechain 模式

```text
main session transcript
  -> agent tool use
  -> spawn async agent
  -> agent-{id}.jsonl sidechain
  -> task output file
  -> xml notification injected back into main session
```

这是非常关键的设计，因为它同时解决了：

- 观测
- 恢复
- 输出读取
- UI 展示
- 后台执行解耦

## 9.7 Worktree 隔离建议

你的 Web 后端如果有 coding agent，应该支持：

- 默认共享 workspace
- 高风险任务新建 git worktree
- 每个 async coding task 可挂独立 worktreePath
- 最终通过 task result 返回 diff/PR/summary

## 9.8 Agent 管理模块最终结论

你要实现的是：

**同步递归 agent + 异步 task agent + sidechain transcript + mailbox + notification + worktree isolation 的统一 agent runtime。**

---

# 模块 6，记忆系统

这是 Claude Code 里最容易被误解，但对“一人公司系统”最重要的模块之一。

## 10.1 从笔记和源码抽出的真实记忆设计

### 来自笔记 5 的结论

- relevant memory 主体来自 `.md` durable memory
- JSONL transcript 不是 main recall 平面
- 代码检索依赖 Grep/Glob/Read
- `CLAUDE.md` 属于启动注入，不是 runtime recall

### 来自 `findRelevantMemories.ts`

- `scanMemoryFiles()` 先扫描 memory 目录 frontmatter header
- 再用 sideQuery 从 manifest 中选最多 5 个 relevant memories
- 已经 surfacing 过的 path 会被排除，避免重复占 recall budget

### 来自 `memoryScan.ts`

- memory 扫描是目录级、frontmatter aware、mtime aware
- 仅扫描 `.md`，并排除 `MEMORY.md`
- 产出 manifest 供 recall 选择器使用

### 来自 `extractMemories.ts`

- durable memory 提炼在每轮 query 完成后触发
- 它使用 forked agent 模式，而不是直接在主 agent 中硬编码抽取
- 提炼 agent 的工具权限被严格限制为 Read/Grep/Glob/read-only Bash 和 memoryDir 内的 Edit/Write

## 10.2 正确的 4 层记忆平面

### 平面 A，运行时工作记忆

- 当前 session messages
- 当前 turn 的 tool results
- pending notifications
- current prompt assembly

### 平面 B，项目规则与身份记忆

- `CLAUDE.md`
- system prompt fragments
- repo rules
- user/org policy

### 平面 C，durable memory

- `memory/*.md`
- `MEMORY.md`
- team memory
- agent memory

### 平面 D，历史档案与冷存储

- JSONL transcripts
- tool result artifacts
- task outputs
- logs

## 10.3 你的记忆系统不能只做 loadMemory + injectMemory

应该拆成 6 个子系统：

1. Startup memory injection
2. Relevant memory prefetch
3. Durable memory extraction
4. Team/shared memory sync
5. Context compaction
6. Archive search / transcript mining

## 10.4 推荐 API

```ts
interface MemoryRuntime {
  loadStartupMemory(projectPath: string): Promise<StartupMemory>
  startRelevantMemoryPrefetch(
    messages: RuntimeMessage[],
    context: ToolUseContext,
  ): DisposablePromise<RelevantMemory[]>
  injectMemory(
    systemPrompt: string,
    startupMemory: StartupMemory,
    recalledMemories: RelevantMemory[],
  ): string
  extractMemories(session: Session): Promise<ExtractionResult>
  compactMessages(messages: RuntimeMessage[]): Promise<CompactionResult>
  createCompactBoundary(meta: CompactMetadata): RuntimeMessage
  searchArchives(query: string): Promise<ArchiveHit[]>
}
```

## 10.5 relevant memory 机制应该怎样落地

建议完全保留 Claude Code 的思路：

### 第一步，轻量扫描

只读 memory file header/frontmatter，不全文 embed。

### 第二步，side model 选取

用一个小模型从 manifest 中选 3 到 5 个最相关 memory 文件。

### 第三步，异步预取

在 turn 开始时就启动，不阻塞主 query。

### 第四步，落到 user context 或 system fragment

在 prompt assembly 阶段拼接 recalled memory。

## 10.6 durable memory 提炼建议

Claude Code 风格说明了一个很聪明的点：

**记忆提炼最好由一个受限 forked agent 完成。**

原因：

- 和主 agent 解耦
- 可以共享 prompt cache
- 权限可严格限制
- 失败不会污染主线程
- 可渐进升级为 autoDream / nightly summarization

## 10.7 compact 不是单一 summarize，而是上下文治理总系统

### 你应该保留以下机制

1. **Snip**，删除不必要历史尾前段
2. **Microcompact**，对中间块做轻量压缩
3. **Context Collapse**，把历史折叠为投影视图并持久化 collapse commit/snapshot
4. **Auto Compact**，超阈值时自动摘要压缩
5. **Reactive Compact**，收到 prompt-too-long 后再触发恢复压缩

### 你需要显式保存 compact boundary

因为：

- resume 需要知道从哪之后是真实链
- preserved segment 需要 relink
- UI 需要显示“这里发生过压缩”

## 10.8 team memory 与一人公司系统的关系

对于“一人公司”来说，team memory 很重要，因为多个 agent 会各自形成局部认识。

建议增加：

- `org-memory/`
- `project-memory/`
- `department-memory/marketing.md`
- `department-memory/engineering.md`
- `agent-memory/{agentType}.md`

再通过 teamMemorySync 做归并。

## 10.9 记忆系统最终结论

你要实现的是：

**启动注入 + relevant recall + durable extraction + team memory sync + compact governance + archive mining 的完整记忆内核。**

---

## 11. 你的原始数据流，升级后的完整版本

```text
用户输入 / Webhook / Cron
  -> Ingress API
  -> Session Router
  -> Session Query Coordinator
      -> 记录 user message 到 transcript
      -> 构建 toolUseContext / permission context / appState
      -> 启动 relevant memory prefetch
      -> 进入 query loop

query loop:
  1. clone active messages
  2. applyToolResultBudget
  3. snip / microcompact / contextCollapse / autocompact
  4. assemble full system prompt
  5. prependUserContext + normalizeMessagesForAPI
  6. streaming model call
  7. parse text / thinking / tool_use / stop events
  8. StreamingToolExecutor 并发执行工具
  9. 收集 tool_result / attachment / task notification
 10. 持久化 assistant + tool_result + attachment
 11. 若还有 tool_use follow-up，则继续下一轮
 12. 若无，则进入 finalize

finalize:
  -> stop hooks
  -> extractMemories
  -> task notifications enqueue
  -> flush session storage
  -> return final response / task handle
```

---

## 12. 针对 Web 后端的一体化落地蓝图

## 12.1 建议拆成 8 个服务组件

### 1. API Gateway

负责：

- 用户请求接入
- WebSocket 推流
- 任务控制 API
- 审批 API

### 2. Session Service

负责：

- session create/resume/branch
- transcript load/save
- metadata tail read
- recent logs index

### 3. Query Runtime Service

负责：

- QueryEngine
- query loop
- model streaming
- follow-up recursion

### 4. Tool Runtime Service

负责：

- tool registry
- tool filtering
- tool execution sandbox
- large result storage

### 5. Agent Runtime Service

负责：

- sync subagents
- async task agents
- worktree lifecycle
- mailbox / notification

### 6. Memory Service

负责：

- startup memory load
- relevant memory recall
- durable extraction
- archive search
- team memory sync

### 7. Permission Service

负责：

- rules
- approval queue
- classifier
- audit log

### 8. Infra Service

负责：

- JSONL append queue
- object storage
- SQL index
- locks
- telemetry

## 12.2 推荐存储布局

```text
/storage
  /sessions/{workspaceId}/{sessionId}.jsonl
  /sessions/{workspaceId}/{sessionId}/subagents/agent-{agentId}.jsonl
  /sessions/{workspaceId}/{sessionId}/tasks/{taskId}.json
  /artifacts/tool-results/{toolUseId}.txt
  /artifacts/task-output/{taskId}.md
  /memory/project/*.md
  /memory/team/*.md
  /memory/agents/*.md
```

配套索引库：

- `sessions`
- `session_events`
- `tasks`
- `agents`
- `permission_decisions`
- `memory_files`
- `artifacts`

## 12.3 WebSocket 事件协议建议

```ts
type ServerEvent =
  | { type: 'assistant_delta'; sessionId: string; chunk: string }
  | { type: 'tool_use_started'; toolUseId: string; tool: string }
  | { type: 'tool_progress'; toolUseId: string; data: unknown }
  | { type: 'tool_result'; toolUseId: string; preview: string }
  | { type: 'task_started'; taskId: string; agentId: string }
  | { type: 'task_notification'; taskId: string; status: string }
  | { type: 'compact_boundary'; sessionId: string; meta: unknown }
  | { type: 'approval_required'; approvalId: string; action: unknown }
  | { type: 'session_completed'; sessionId: string }
```

---

## 13. 一人公司场景下的 Agent 组织建议

## 13.1 推荐的 agent 角色层级

### L1，CEO / Coordinator Agent

- 理解用户目标
- 分解任务
- 分配给部门 agent
- 汇总结果

### L2，部门 Agent

- Engineering Agent
- Product Agent
- Research Agent
- Marketing Agent
- Operations Agent
- Finance/Admin Agent

### L3，执行 Agent

- Coder Agent
- Reviewer Agent
- Search Agent
- Data Agent
- Outreach Agent
- Report Agent

### L4，后台守护任务

- Nightly memory extraction
- Inbox triage
- Monitoring agent
- Daily planning agent

## 13.2 为什么要把部门 Agent 和执行 Agent 分开

因为 `filterToolsForAgent()` 这种设计启示我们：不是所有 agent 都该拿到同一套工具。

例如：

- Marketing agent 可以有 web / docs / CRM 工具
- Coder agent 可以有 edit / bash / git / test 工具
- Finance agent 可以访问表格、账目 API，但不能写代码目录

这会极大降低权限面和上下文污染。

---

## 14. Claude Code 思想下，完整系统的 4 条主通信总线

## 14.1 总线一，Session Message Bus

用于：

- user -> assistant
- assistant -> tool_use
- tool_result -> follow-up assistant
- system / compact / attachment 注入

## 14.2 总线二，Task Bus

用于：

- 创建后台 agent
- 跟踪状态
- 读取输出
- kill/stop/retry

## 14.3 总线三，Mailbox / Notification Bus

用于：

- 主会话给后台 agent 发送补充消息
- 后台 agent 给主会话回投 XML task-notification

## 14.4 总线四，Memory Bus

用于：

- startup memory injection
- relevant memory recall
- team memory sync
- durable memory extract

### 可选扩展

- Bridge Bus，用于远程设备/远程 worker
- Swarm Bus，用于 leader-worker 团队型任务

---

## 15. 模块与源码的精确映射表

| 设计模块 | 关键源码/笔记 | 你应该继承的能力 |
| --- | --- | --- |
| 会话持久化 | `utils/sessionStorage.ts`, 笔记 6 | JSONL、parentUuid、metadata tail、resume、sidechain |
| 查询循环 | `query.ts`, `QueryEngine.ts`, 笔记 2/6 | while(true)、streaming、compact、fallback、memory prefetch |
| 工具系统 | `Tool.ts`, `tools.ts`, `toolExecution.ts`, 笔记 1/2 | 动态注册、暴露前过滤、hook、permission、streaming executor |
| 权限系统 | `utils/permissions/permissions.ts`, `toolExecution.ts` | allow/deny/ask、hooks、classifier、denial tracking |
| Agent 管理 | `runAgent.ts`, `forkSubagent.ts`, `LocalAgentTask.tsx`, 笔记 3/4 | sync/async agent、sidechain、mailbox、notification、worktree |
| 记忆系统 | `findRelevantMemories.ts`, `memoryScan.ts`, `extractMemories.ts`, 笔记 5 | durable memory、manifest recall、forked extraction、archive separation |

---

## 16. 对你原始 8 层设计的最终修订版

你原来的版本：

```text
UI -> Session -> Query Engine -> Tool Orchestration -> Permissions -> Agent -> Memory -> Integrations
```

修订为：

```text
Ingress
 -> Interaction
 -> Session State
 -> Query Engine
 -> Model Runtime
 -> Tool Orchestration
 -> Permission & Safety
 -> Agent Runtime
 -> Task & Communication
 -> Memory & Context
 -> Integrations
 -> Infrastructure
```

### 这个修订的意义

- 把 Task/Communication 抬成一级层，因为多 Agent 的核心不只是 spawn，而是 task bus
- 把 Model Runtime 抬成一级层，因为 streaming/fallback/retry/usage 不能塞进 query 杂糅
- 把 Infrastructure 抬成一级层，因为 JSONL append queue、artifact store、telemetry 是真正的 durability 基座

---

## 17. 你应该优先实现的 MVP 顺序

## Phase 1，先跑通 Claude Code 风格最小闭环

1. Session transcript JSONL
2. Query loop
3. Tool registry + permission gate
4. Sync subagent
5. Simple durable memory recall

## Phase 2，补齐一人公司最关键能力

1. Async agent task
2. Sidechain transcript
3. Task output / notification
4. Worktree isolation
5. Approval center

## Phase 3，做成真正的运营系统

1. Team memory sync
2. Remote agent / bridge
3. Scheduled agents / cron
4. Archive mining / autoDream
5. Department-level agent hierarchy

---

## 18. 最终结论

如果你真的要做一个基于 Claude Code 思想、可在 Web 后端运行的、完整的多 Agent 一人公司系统，那么它**不应该只是一个“会调用工具的聊天机器人”**，而应该是一个具备以下特征的运行时：

### 18.1 它的本质

- 一个 **消息驱动** 的 query runtime
- 一个 **append-only transcript event store**
- 一个 **带 sidechain 的 agent/task 操作系统**
- 一个 **多层 memory 管理系统**
- 一个 **可限权、可审计、可恢复** 的工具执行平台

### 18.2 它最重要的 6 个内核

1. Session Transcript Engine
2. Query Loop Engine
3. Tool Orchestration Engine
4. Permission & Safety Engine
5. Agent Runtime & Task Bus
6. Memory & Context Engine

### 18.3 最值得保留的 Claude Code 灵魂

不是它的 CLI，不是它的 UI，而是这 5 点：

1. **消息链持久化**
2. **递归式 query + tool follow-up**
3. **同步与异步 agent 并存**
4. **记忆与 transcript 分层**
5. **压缩、恢复、权限、通知全部内建**

把这 5 点做对，你的 Web 后端就不是“Claude Code 的网页版”，而会是一个真正能支撑多 agent 一人公司的运行内核。

---

## 19. 最终建议，一句话版本

你的目标系统最合理的定义是：

**一个以 JSONL transcript 为事实源、以 query loop 为执行核心、以 task bus 为多 agent 协作总线、以 durable memory 为长期认知层、以 permission engine 为安全边界的 Claude-Code-inspired Web runtime。**

# 设计补充细节

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
