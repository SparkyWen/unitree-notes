# Claude Code 代码库学习地图 - 模块 4：Agent 主循环模块

- 模块名称：Agent 主循环（Query Loop / Model Streaming / Recovery / Compaction / Tool Orchestration）
- 目标：还原 Claude Code 一次完整 agentic turn 的核心状态机，包括模型请求、流式消息处理、tool_use 执行、compact/retry/recovery、附件注入与继续下一轮的全过程

---

## 1. 功能概述

这是整个 Claude Code 代码库里最核心的模块。

如果你只能精读少数几个文件，那么：

- `source/src/main.tsx`
- `source/src/query.ts`
- `source/src/services/api/claude.ts`
- `source/src/services/tools/toolExecution.ts`
- `source/src/services/compact/compact.ts`

就是最不能跳过的一组。

这个模块负责：
- 把已有消息、系统 prompt、上下文、工具、权限、记忆和附件，组装成一次模型请求
- 以流式方式接收 assistant message / tool_use / thinking / error
- 发现 tool_use 后执行工具，再把 tool_result 回灌给模型
- 在 prompt-too-long、media error、max_output_tokens 等情况下做自动恢复
- 在长上下文下做 microcompact / autocompact / reactive compact / context collapse / history snip
- 在每轮工具完成后重新注入 attachment / memory / queued prompt / skill discovery
- 最终反复迭代，直到本轮真正结束

一句话概括：

> `query.ts` 是 Claude Code 的“Agent Runtime 状态机内核”。

---

## 2. 解决的问题

### 2.1 LLM agent 不是一次请求，而是多轮状态机
一次用户任务往往会变成：
1. 模型思考
2. 调工具
3. 读结果
4. 再调工具
5. 再继续输出

系统必须支持多轮自动继续。

### 2.2 工具、附件、记忆、停止钩子都会影响下一轮 prompt
也就是说不是简单“messages + model call”，而是每轮都要动态再装配上下文。

### 2.3 大上下文与 token 限制是长期主问题
系统需要同时处理：
- proactive autocompact
- reactive compact
- microcompact
- snip compact
- context collapse
- tool result budget

### 2.4 API 不可靠与运行环境复杂
需要处理：
- streaming fallback -> non-streaming fallback
- model fallback
- prompt too long
- media size error
- max output tokens
- 404 streaming endpoint
- stream idle timeout watchdog

### 2.5 query loop 还要兼容很多模式
例如：
- repl main thread
- sdk
- agent subagent
- compact agent
- session_memory agent
- hook agent
- verification_agent

这让它必须做大量 querySource 分支处理。

---

## 3. 涉及文件（本轮深读）

1. `source/src/query.ts`
2. `source/src/query/config.ts`
3. `source/src/query/deps.ts`
4. `source/src/services/api/claude.ts`
5. `source/src/services/compact/compact.ts`
6. `source/src/services/tools/toolOrchestration.ts`

另外已扫描目录：
- `source/src/services/compact/**`
- `source/src/services/api/**`
- `source/src/query/**`

---

## 4. 模块核心入口文件

### 核心入口文件
- `source/src/query.ts`

### 最值得先读的 3~8 个文件
1. `source/src/query.ts`
2. `source/src/services/api/claude.ts`
3. `source/src/services/compact/compact.ts`
4. `source/src/query/config.ts`
5. `source/src/query/deps.ts`
6. `source/src/services/tools/toolOrchestration.ts`
7. `source/src/query/tokenBudget.ts`（下一轮补）
8. `source/src/query/stopHooks.ts`（下一轮补）

### 容易被忽视但关键的文件
- `source/src/query/config.ts`
- `source/src/query/deps.ts`
- `source/src/services/tools/toolOrchestration.ts`

这三个文件体量不一定最大，但非常能体现作者如何把 `query.ts` 的复杂度做分层。

---

## 5. 整体调用链 / 执行流程

先给你最核心的主链路图：

```text
main.tsx / repl / headless
  -> query(params)
      -> queryLoop(state)
          -> buildQueryConfig()
          -> memory prefetch / skill prefetch
          -> applyToolResultBudget()
          -> snipCompactIfNeeded()
          -> microcompactMessages()
          -> contextCollapse.applyCollapsesIfNeeded()
          -> autoCompactIfNeeded()
          -> queryModelWithStreaming()
              -> services/api/claude.ts
          -> assistant stream 中收 tool_use blocks
          -> StreamingToolExecutor / runTools
              -> toolExecution.ts
          -> attachment / memory / queued commands / skill discovery 注入
          -> stop hooks / token budget / continuation decision
          -> 若需继续 -> 下一轮 queryLoop
          -> 否则结束
```

这个循环就是整个 Agent Runtime 的主脉络。

---

## 6. 核心文件详细讲解

---

## 6.1 `source/src/query.ts`

### 文件作用
这是 Claude Code 的**主查询循环与 turn 状态机**。

它导出：
- `query(params)`

但真正核心逻辑在内部：
- `queryLoop(...)`

### 设计定位
如果 `main.tsx` 是应用总调度器，那么 `query.ts` 是：

> **每一轮 agent 执行的主引擎。**

---

### 顶层接口

#### `query(params)`

##### 输入参数
`QueryParams` 包含：
- `messages`
- `systemPrompt`
- `userContext`
- `systemContext`
- `canUseTool`
- `toolUseContext`
- `fallbackModel?`
- `querySource`
- `maxOutputTokensOverride?`
- `maxTurns?`
- `skipCacheWrite?`
- `taskBudget?`
- `deps?`

##### 返回值
`AsyncGenerator<StreamEvent | RequestStartEvent | Message | TombstoneMessage | ToolUseSummaryMessage, Terminal>`

##### 意味着什么
这个函数不是“返回最终字符串”，而是一个流式状态机：
- 会不断 yield 中间事件和消息
- 最终 return 一个 terminal reason

这是整个系统很多 UI / SDK 能实时更新的基础。

---

### `State` 结构是主循环核心

```ts
State = {
  messages,
  toolUseContext,
  autoCompactTracking,
  maxOutputTokensRecoveryCount,
  hasAttemptedReactiveCompact,
  maxOutputTokensOverride,
  pendingToolUseSummary,
  stopHookActive,
  turnCount,
  transition,
}
```

### 为什么重要
这表明 query loop 并不是靠递归堆消息，而是维护一份明确的跨迭代状态。

尤其关键的字段：
- `messages`：当前会话上下文
- `toolUseContext`：工具运行上下文
- `autoCompactTracking`：自动压缩状态
- `hasAttemptedReactiveCompact`：防止 compact 死循环
- `maxOutputTokensRecoveryCount`：防止无限恢复
- `pendingToolUseSummary`：异步生成下轮 UI 摘要
- `transition`：记录上一轮为什么继续，用于调试和测试

---

### `queryLoop(...)` 详细流程

这是整个文件最重要的函数。

#### 阶段 1：初始化与配置快照

```ts
const deps = params.deps ?? productionDeps()
const budgetTracker = feature('TOKEN_BUDGET') ? createBudgetTracker() : null
const config = buildQueryConfig()
using pendingMemoryPrefetch = startRelevantMemoryPrefetch(...)
```

##### 设计点
- `buildQueryConfig()` 在 query 入口只做一次快照，避免循环内重复读取 env/statsig
- `deps` 让测试可以注入假实现
- `pendingMemoryPrefetch` 在整轮 query 生命周期内托管，减少重复启动

---

#### 阶段 2：每轮开始前的上下文整理

##### 2.1 从 compact boundary 后取消息
```ts
messagesForQuery = [...getMessagesAfterCompactBoundary(messages)]
```

这是为了让 compact 后的消息视图正确生效。

##### 2.2 tool result budget
```ts
messagesForQuery = await applyToolResultBudget(...)
```

作用：
- 对工具结果总量做预算控制
- 在必要时替换/压缩历史 tool results

##### 2.3 history snip
```ts
snipCompactIfNeeded(messagesForQuery)
```

如果启用 `HISTORY_SNIP`，会在 autocompact 前先做更轻量的裁切。

##### 2.4 microcompact
```ts
const microcompactResult = await deps.microcompact(...)
```

这是比 full compact 更轻量、偏 cache/edit oriented 的压缩。

##### 2.5 context collapse
```ts
contextCollapse.applyCollapsesIfNeeded(...)
```

目的是：
- 先投影 collapsed view
- 如果 collapse 已足够减压，就可以避免更激进的 autocompact

##### 2.6 autocompact
```ts
const { compactionResult, consecutiveFailures } = await deps.autocompact(...)
```

如果触发：
- 会生成 compact boundary + summary + attachments + hook results
- 这些 post-compact messages 立刻进入当前 query 继续执行

##### 设计意图
在真正打 API 之前，先尽量把上下文维持在合理规模。

---

#### 阶段 3：模型请求前 setup

```ts
streamingToolExecutor = new StreamingToolExecutor(...)
currentModel = getRuntimeMainLoopModel(...)
dumpPromptsFetch = createDumpPromptsFetch(...)
```

##### 关键点
- tool executor 每轮新建
- model 可能按 permission mode / token exceed 情况动态选
- dumpPromptsFetch 只创建一次，避免 retention 问题

---

#### 阶段 4：blocking limit 预拦截
如果：
- 没 compact 成功
- 不是 compact/session_memory query
- 没开启 reactive compact fallback owner
- token count 已到 blocking limit

则直接：
- yield `PROMPT_TOO_LONG_ERROR_MESSAGE`
- 终止

##### 为什么这样设计
这是在 auto-compact 关闭时，留给用户手动 `/compact` 的保底空间。

---

#### 阶段 5：模型流式请求

核心调用：
```ts
for await (const message of deps.callModel({...}))
```
这里默认就是：
- `queryModelWithStreaming()`

##### 流中处理的关键事情

###### 1) streaming fallback tombstone
如果流式请求中途 fallback：
- 已收到的 partial assistant messages 变成 orphaned
- 需要发 tombstone，从 UI/Transcript 中删除
- 重置 assistantMessages/toolResults/toolUseBlocks
- 重建 StreamingToolExecutor

###### 2) backfill observable input for yield-only message clone
为了 SDK stream 和 transcript 看到 legacy/derived 字段，但又不污染真正的 API message 对象。

###### 3) 可恢复错误的 withholding
对以下错误，不立刻 yield 给外部：
- prompt-too-long
- reactive compact 可恢复 media error
- max_output_tokens

因为系统还可能自动恢复；若太早把 error 暴露给 SDK caller，caller 可能直接结束会话。

这是一个非常精细的“先扣住错误，等看 recovery 能否成功”的设计。

---

#### 阶段 6：assistant message 收集与 tool_use 提取

每收到 assistant message：
- push 到 `assistantMessages`
- 提取 `tool_use` blocks
- `needsFollowUp = true`
- 如果启用了 streaming tool execution，则立即 `streamingToolExecutor.addTool(...)`

##### 含义
模型一边流式输出，工具就可以一边开始执行。

这比“等整条 assistant message 完成后再统一执行工具”更低延迟。

---

#### 阶段 7：工具结果流式回收

如果使用 `StreamingToolExecutor`：
- 每次流式消息循环中，会先拉 `getCompletedResults()`
- 及时 yield progress/tool_result
- 并同步更新 `toolResults`

这一层把：
- 模型流
- 工具流

两条异步流编织成单一会话流。

---

#### 阶段 8：模型/流式错误恢复

这是 `query.ts` 最复杂也最有价值的部分之一。

##### 8.1 prompt-too-long 恢复
流程顺序：
1. 如果 context collapse 有 staged collapse，先 drain collapse 重试
2. 否则 reactiveCompact.tryReactiveCompact(...)
3. 若成功，yield post-compact messages 后继续
4. 若失败，才真正 surface error

##### 设计意图
优先尝试保留更细粒度上下文的恢复手段，再退到摘要式 compact。

---

##### 8.2 media error 恢复
如果 reactive compact 支持 media strip/retry：
- 做一次 reactive compact
- 成功则继续
- 失败才 surface image/media error

---

##### 8.3 max_output_tokens 恢复
分两级：

###### 第一级：8k -> 64k escalate
如果当前是 capped default 且没显式 override：
- 直接把 `maxOutputTokensOverride` 提到 `ESCALATED_MAX_TOKENS`
- 重试同一请求

###### 第二级：meta recovery message
如果仍 hit cap：
- 给模型补一条 meta user message：
  “继续，不要道歉，不要 recap，直接接着做”
- 最多尝试 `MAX_OUTPUT_TOKENS_RECOVERY_LIMIT = 3`

###### 超过上限
才真正 surface error

##### 设计意图
尽量减少用户看见“输出被截断”的次数，并鼓励模型用更碎片化的方式继续完成任务。

---

#### 阶段 9：stop hooks / token budget / natural completion
如果这轮没有 `needsFollowUp`：

1. 先跑 `handleStopHooks(...)`
2. 若 hook 有 blockingErrors，则把错误注入消息，再继续下一轮
3. 若启用了 token budget，则 `checkTokenBudget(...)`
   - 若要继续：注入 nudge meta message，再继续
   - 若完成：记录 completion event
4. 否则自然 return `{ reason: 'completed' }`

##### 设计意图
“没有 tool_use”并不代表这轮一定结束：
- stop hooks 可能要求再修一次
- token budget 策略可能要求再收尾一次

---

#### 阶段 10：工具执行后的附件/记忆/队列注入

当这轮执行过工具，并准备进入下一轮时，会额外做很多工作：

##### 10.1 `getAttachmentMessages(...)`
注入：
- 文件变更附件
- 计划模式附件
- MCP delta / deferred tools delta / agent listing delta
- 其他运行时附件

##### 10.2 memory prefetch consume
如果相关 memory prefetch 已完成：
- 注入 memory attachments
- 并用 `readFileState` 过滤重复内容

##### 10.3 skill discovery prefetch consume
如果 skill prefetch 已完成：
- 注入 skill discovery attachments

##### 10.4 queued commands snapshot
把 pending prompt/task-notification 从全局队列里转换为 attachment 给模型

##### 设计意图
工具执行后的下一轮 query，必须尽量拿到“刚刚这轮发生的上下文副作用”。

这正是 Claude Code 比普通 REPL 更像 Agent Runtime 的关键之一。

---

#### 阶段 11：递归进入下一轮
最后构造新的 `State`：

```ts
state = {
  messages: [...messagesForQuery, ...assistantMessages, ...toolResults],
  toolUseContext: updatedToolUseContext,
  autoCompactTracking: tracking,
  turnCount: nextTurnCount,
  ...
  transition: { reason: 'next_turn' },
}
continue
```

这就是完整 loop 的回环。

---

## 6.2 `source/src/query/config.ts`

### 文件作用
这是 query loop 的**只读配置快照构造器**。

### 核心函数
`buildQueryConfig()`

### 返回内容
```ts
{
  sessionId,
  gates: {
    streamingToolExecution,
    emitToolUseSummaries,
    isAnt,
    fastModeEnabled,
  }
}
```

### 为什么单独拆出来
源码注释已经说明：
- 这是为了把 query 的“动态状态”与“入口时快照配置”分开
- 为未来把 query loop 抽成更纯粹 reducer/step() 做准备

### 设计价值
- 避免循环里反复读 env/statsig
- 降低 `query.ts` 内部对全局模块的散依赖
- 测试更容易稳定

---

## 6.3 `source/src/query/deps.ts`

### 文件作用
这是 query loop 的**I/O 依赖注入层**。

### 核心内容
`QueryDeps` 目前只暴露 4 类依赖：
- `callModel`
- `microcompact`
- `autocompact`
- `uuid`

### 为什么这个文件很重要
它体现了作者正在逐步把 `query.ts` 从“直接 import 一切的超级函数”往“可测试状态机”方向重构。

### 设计亮点
- `typeof fn` 自动跟真实实现同步签名
- 测试里可以直接塞 fake deps，不必到处 spy module
- 范围控制得很克制，不一次性全抽象化

这是很成熟的增量重构方式。

---

## 6.4 `source/src/services/tools/toolOrchestration.ts`

### 文件作用
这是**非 streaming tool execution 的编排器**。

### 核心函数
- `runTools(...)`
- `partitionToolCalls(...)`
- `runToolsSerially(...)`
- `runToolsConcurrently(...)`

### 为什么它仍然重要
即使现在有 `StreamingToolExecutor`，这个文件仍然是：
- fallback 路径
- 更简单的批量工具执行模型
- 工具调度语义的另一个实现参照

---

### `partitionToolCalls(...)`

#### 作用
把 tool_use blocks 切成若干批：
1. 单个非并发安全工具
2. 一串连续的并发安全工具

#### 关键点
它会先：
- `findToolByName`
- `inputSchema.safeParse(toolUse.input)`
- 再调用 `tool.isConcurrencySafe(parsedInput.data)`

如果判断失败/抛错：
- 保守地视为不可并发

##### 设计价值
比一刀切更智能，又比乐观并发更安全。

---

### `runTools(...)`

#### 逻辑
- 遍历 partition 后的 batch
- 并发 batch 用 `runToolsConcurrently`
- 非并发 batch 用 `runToolsSerially`
- 并发 batch 里的 contextModifier 先排队，结束后按 toolUse 顺序应用

##### 关键设计
contextModifier 不在并发执行中立刻修改共享 context，而是等 batch 完成后再顺序应用。

这与 `StreamingToolExecutor` 的思路是一致的：
- 并发结果可以先跑
- 共享上下文修改要保守处理

---

## 6.5 `source/src/services/compact/compact.ts`

### 文件作用
这是**完整 compact 系统的核心文件**。

它负责：
- 全量会话压缩
- partial compact
- compact API 调用
- compact 前后 hooks
- compact boundary / summary / post-compact attachments 构造
- prompt-too-long during compact 的再恢复
- post-compact 文件/plan/skill/agent/mcp/instructions 恢复

这是 query.ts 上下文治理能力的另一个中枢。

---

### 核心导出
- `compactConversation(...)`
- `partialCompactConversation(...)`
- `buildPostCompactMessages(...)`
- `createCompactCanUseTool()`
- `stripImagesFromMessages(...)`
- `createPostCompactFileAttachments(...)`
- `createSkillAttachmentIfNeeded(...)`
- `createPlanAttachmentIfNeeded(...)`
- `createAsyncAgentAttachmentsIfNeeded(...)`

---

### `compactConversation(...)` 主逻辑

#### 步骤概览
```ts
1. 计算 preCompactTokenCount
2. executePreCompactHooks()
3. 组装 compact prompt + summaryRequest
4. streamCompactSummary(...)
   - 优先 prompt cache sharing forked agent
   - 失败 fallback 到 regular streaming path
   - 如 compact request 自己 PTL，则 truncateHeadForPTLRetry 重试
5. 获得 summary 文本
6. 保存并清空 readFileState / nestedMemory paths
7. 并行生成 post-compact attachments:
   - recently read files
   - async agents
   - plan file / plan mode
   - invoked skills
   - deferred tools delta / agent listing delta / MCP instructions delta
8. processSessionStartHooks('compact')
9. createCompactBoundaryMessage(...)
10. create compact summary user message
11. logEvent('tengu_compact', ...)
12. notifyCompaction() / markPostCompaction()
13. reAppendSessionMetadata()
14. executePostCompactHooks()
15. return CompactionResult
```

---

### 最关键的设计点

#### 设计点 1：compact 自己也可能 PTL，需要 retry
`truncateHeadForPTLRetry(...)` 是非常关键的兜底：
- 如果 compact request 本身 prompt too long
- 就截掉最旧的一些 api-round groups 再试

这说明 compact 不被神化，它自己也是普通模型请求，也可能失败。

#### 设计点 2：compact 不是只返回 summary
而是返回一整套 post-compact context：
- boundary marker
- summary messages
- recently read files
- plan file
- invoked skills
- async agent state
- deferred tools delta
- MCP instructions delta
- hook results

这就是为什么 compact 后模型还能“接着工作”，而不是只剩一句摘要。

#### 设计点 3：prompt cache sharing
如果启用：
- compact 会通过 `runForkedAgent` 尝试复用主对话已有的 prompt cache 前缀

这是一种非常高级的 cache reuse 设计。

#### 设计点 4：post-compact file restore 做了预算控制
- 最多恢复若干最近读过文件
- 还受总 token budget 约束
- 并会跳过 preserved tail 中已经可见的 Read result

这是很细腻的“上下文恢复而不浪费 token”策略。

#### 设计点 5：invoked skills 会被单独附件保留
否则 compact 后模型会忘记本轮已经调用过哪些技能，以及这些技能的关键内容。

---

### `partialCompactConversation(...)`

#### 作用
支持围绕用户选中的消息做部分压缩：
- `from`：压缩后半段，保留前缀
- `up_to`：压缩前半段，保留后缀

#### 关键区别
- `up_to` 会去掉旧 compact boundary / old compact summaries
- `from` 保留 prefix cache 更友好

##### 设计价值
这让 compact 不只是全自动防爆，还支持交互式历史整理。

---

### `createCompactCanUseTool()`

#### 作用
compact agent 调工具一律 deny。

#### 意味着什么
compact agent 是：
- 纯摘要 agent
- 不允许任何工具副作用

这个约束非常必要，否则 compact 本身可能引入额外复杂行为。

---

## 6.6 `source/src/services/api/claude.ts`

### 文件作用
这是 Claude Code 的**模型/API 调用核心层**。

它负责：
- 把内部 message/tool/systemPrompt/options 转换成 Anthropic Beta Messages API 请求
- 处理 streaming/non-streaming
- 处理 retry/fallback
- 构造 beta headers / metadata / prompt caching / cache editing / tool search / advisor / effort / task budget
- 解析流事件并回灌成内部 AssistantMessage / StreamEvent

这是整个“Claude 与外部 API 交互”的主战场。

---

### 你应该怎么理解这个文件
它不是简单 HTTP wrapper，而是：

> **“Claude Code 内部消息模型 -> Claude API 请求协议”的编译器 + 流式运行时适配器。**

---

### 核心函数层级

#### 第一层：外部入口
- `queryModelWithStreaming(...)`
- `queryModelWithoutStreaming(...)`
- `queryHaiku(...)`
- `queryWithModel(...)`

#### 第二层：真正实现
- `queryModel(...)`

#### 第三层：辅助能力
- prompt caching / cache breaks
- extra body params
- metadata
- tool schema building
- message normalization
- streaming fallback / non-streaming fallback
- usage/cost accounting

---

### `queryModel(...)` 主逻辑分解

#### 步骤 1：预检查与模型解析
- Opus off-switch 检查
- previousRequestId 从历史消息中提取
- Bedrock inference profile backing model 解析
- 计算 `isAgenticQuery`
- 组装 betas
- advisor model 决定

#### 步骤 2：tool search 与 deferred tools
- `isToolSearchEnabled(...)`
- 预计算 `deferredToolNames`
- 若无 deferred tools 且无 pending MCP servers，则停用 tool search
- 按 discovered-tool set 过滤 deferred tools

##### 意味着什么
模型默认并不总看到全部 deferred tools。
必须先通过 ToolSearchTool “发现”后，schema 才会真正被发送到 API。

这和 query.ts 里的 `buildSchemaNotSentHint()` 形成闭环。

---

#### 步骤 3：构建 tool schemas
```ts
toolToAPISchema(tool, {
  getToolPermissionContext,
  tools,
  agents,
  allowedAgentTypes,
  model,
  deferLoading,
})
```

##### 关键设计
- schema 不是静态 JSON，而是和模型、权限上下文、agent type 有关
- `defer_loading` 会影响 API 如何处理工具 schema

---

#### 步骤 4：消息归一化
```ts
messagesForAPI = normalizeMessagesForAPI(messages, filteredTools)
messagesForAPI = ensureToolResultPairing(messagesForAPI)
messagesForAPI = stripExcessMediaItems(messagesForAPI, API_MAX_MEDIA_PER_REQUEST)
```

##### 关键设计点

###### 点 1：tool_result pairing repair
恢复远程/teleport/resume 时若 tool_use/tool_result 不匹配，自动修复。

###### 点 2：media 超限先静默剔除最旧媒体
因为 API 的报错很难恢复，尤其对 CCD/Cowork 更糟。

###### 点 3：tool-search-specific field model-aware strip
如果当前模型不支持 tool search，需要把旧历史里的 tool-search 相关字段剥掉，否则 400。

这说明系统非常关注“模型切换 / resume / 历史污染”问题。

---

#### 步骤 5：构建 system prompt blocks 与 cache strategy
- `buildSystemPromptBlocks(...)`
- `getPromptCachingEnabled(model)`
- `getCacheControl(...)`
- prompt cache 1h TTL 资格判断
- global cache scope 策略

##### 特别关键
这个文件里有大量 cache 相关逻辑，说明 API 请求的组织方式高度服务于：
- prompt caching
- cache break detection
- cache editing microcompact
- global/system prompt cache scope

---

#### 步骤 6：构造 paramsFromContext(retryContext)
这是非常关键的闭包。

它根据 retry context 每次动态构造本次 API 参数：
- model
- messages（含 cache breakpoints）
- system
- tools
- betas
- metadata
- max_tokens
- thinking
- context_management
- output_config
- speed(fast mode)
- extraBodyParams

##### 为什么关键
因为 retry/fallback 时，这些参数可能变化：
- maxOutputTokens cap
- fallback model
- fast mode
- cache editing
- effort
- task budget

---

#### 步骤 7：真正的 streaming request
通过 `withRetry(...)`：
- 构造 anthropic client
- 调 `.beta.messages.create(..., {stream:true}).withResponse()`
- 记录 headers / requestId / response
- 然后消费 raw stream

##### 重要设计：不用 SDK 的 BetaMessageStream，而自己消费 raw stream
原因是：
- SDK 的 partial JSON parsing 有 O(n²) 问题
- 这里作者自己维护 content block accumulation

这是明显的性能导向实现。

---

#### 步骤 8：流事件累积为内部 AssistantMessage
处理事件类型：
- `message_start`
- `content_block_start`
- `content_block_delta`
- `content_block_stop`
- `message_delta`
- `message_stop`

##### 关键设计
在 `content_block_stop` 时，立刻把当前 block 归一化成内部 `AssistantMessage` 并 yield。

因此上层 query loop 才能做到：
- 一有 tool_use block 就尽快开工具执行

---

#### 步骤 9：streaming watchdog 与 fallback
这个文件有一整套流健壮性策略：

##### 9.1 stream idle watchdog
- `CLAUDE_ENABLE_STREAM_WATCHDOG`
- 超过 `CLAUDE_STREAM_IDLE_TIMEOUT_MS` 无 chunk，则主动 abort

##### 9.2 streaming -> non-streaming fallback
如果 streaming error：
- 可回退到 `executeNonStreamingRequest(...)`
- 但若禁用 fallback，则错误直接上抛

##### 9.3 404 stream creation fallback
有些网关 streaming endpoint 返回 404，但 non-streaming 正常。
于是专门处理“创建 stream 时 404 -> 改走 non-streaming”。

##### 为什么重要
这套逻辑说明作者非常在意：
- 企业代理
- 非标准网关
- 网络不稳定
- 流式超时

---

#### 步骤 10：usage / cost / telemetry / request chain 记录
- `updateUsage(...)`
- `accumulateUsage(...)`
- `calculateUSDCost(...)`
- `logAPIQuery(...)`
- `logAPISuccessAndDuration(...)`
- `logAPIError(...)`
- `setLastMainRequestId(...)`

##### 关键点
- previousRequestId 从消息历史而不是全局状态导出，避免并发 query chain 相互污染
- fallback/non-streaming 的 cost 也会在 finally 里补记
- requestId/clientRequestId 双链路追踪

---

## 7. 数据流 / 状态流

### 7.1 一次完整 agentic turn 的主数据流

```text
messages + systemPrompt + userContext + systemContext + toolUseContext
  -> query.ts
  -> compact/snip/microcompact/contextCollapse/toolBudget
  -> claude.ts 构造 API 请求
  -> streaming assistant messages
  -> 提取 tool_use blocks
  -> toolExecution / toolOrchestration
  -> tool_result / attachment / progress
  -> memory/skill/queued command attachment 注入
  -> state.messages 扩展
  -> 下一轮 queryLoop
```

### 7.2 API 请求参数构造流

```text
internal Message[] / Tool[] / SystemPrompt
  -> normalizeMessagesForAPI()
  -> buildSystemPromptBlocks()
  -> toolToAPISchema()
  -> addCacheBreakpoints()
  -> queryModel(...)
  -> Anthropic Beta Messages params
```

### 7.3 compact 数据流

```text
messages
  -> compactConversation()
  -> streamCompactSummary()
  -> summary text
  -> boundary marker + summary user msg + restored attachments
  -> buildPostCompactMessages()
  -> query.ts 继续使用 postCompactMessages
```

### 7.4 恢复链状态流

```text
API error / PTL / media / max_output_tokens
  -> query.ts withheld error
  -> collapse drain / reactive compact / escalate max tokens / recovery meta msg
  -> 成功则 next state
  -> 失败则 surface error + terminal reason
```

---

## 8. 配置项 / 环境变量 / 依赖注入方式

### 8.1 query loop 相关关键开关

| 项目 | 来源 | 影响 |
|---|---|---|
| `tengu_streaming_tool_execution2` | Statsig | 是否使用 `StreamingToolExecutor` |
| `CLAUDE_CODE_EMIT_TOOL_USE_SUMMARIES` | env | 是否生成 tool use summary |
| `CLAUDE_CODE_DISABLE_FAST_MODE` | env | fast mode 是否可用 |
| `TOKEN_BUDGET` | feature gate | 启用 token budget continuation |
| `REACTIVE_COMPACT` | feature gate | 启用 reactive compact |
| `CONTEXT_COLLAPSE` | feature gate | 启用 collapse/recoverFromOverflow |
| `HISTORY_SNIP` | feature gate | 启用 snip compact |
| `BG_SESSIONS` | feature gate | task summary / bg session 支持 |

### 8.2 API 层关键环境变量/动态配置

| 项目 | 来源 | 影响 |
|---|---|---|
| `CLAUDE_CODE_EXTRA_BODY` | env | 追加 API extra body params |
| `CLAUDE_CODE_EXTRA_METADATA` | env | metadata 附加字段 |
| `DISABLE_PROMPT_CACHING*` | env | 禁用 prompt cache |
| `ENABLE_PROMPT_CACHING_1H_BEDROCK` | env | Bedrock 1h TTL |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | env | 覆盖 output token 上限 |
| `CLAUDE_ENABLE_STREAM_WATCHDOG` | env | 启用 streaming idle watchdog |
| `CLAUDE_STREAM_IDLE_TIMEOUT_MS` | env | watchdog 超时 |
| `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK` | env | 禁用 streaming->non-streaming fallback |
| `CLAUDE_CODE_REMOTE` | env | 影响 non-streaming timeout default |
| `tengu_otk_slot_v1` | Statsig | 默认 8k output cap + escalate 到 64k |
| `tengu_compact_cache_prefix` | Statsig | compact prompt cache sharing |
| `tengu_compact_streaming_retry` | Statsig | compact streaming retry |

### 8.3 依赖注入方式

#### 方式 1：`QueryDeps`
测试可替换 callModel/autocompact/microcompact/uuid

#### 方式 2：`ToolUseContext`
提供 app state、tools、commands、abort、notifications、attachment 等

#### 方式 3：feature gate + env + growthbook
大量运行时行为靠这三者共同决定

#### 方式 4：`paramsFromContext(retryContext)`
把 retry 动态状态注入到 API 层

---

## 9. 错误处理 / 边界条件

### `query.ts`
- prompt-too-long：collapse drain -> reactive compact -> surface
- media error：reactive compact strip/retry -> surface
- max_output_tokens：escalate -> recovery meta msg -> surface
- streaming fallback orphan messages -> tombstone
- abort during streaming / tools：合成缺失 tool_result 与 interruption message
- stop hooks API error 死循环避免

### `compact.ts`
- compact 自己 PTL：truncateHeadForPTLRetry
- no summary / api error summary：直接 fail
- manual compact 才弹 error notification
- compact agent tools 一律 deny

### `claude.ts`
- streaming idle watchdog
- streaming 404 fallback
- raw stream incomplete/no events fallback
- APIUserAbortError 与 timeout 区分
- strip excess media
- ensureToolResultPairing
- normalize 旧 transcript / tool-search mismatch / advisor blocks

### `toolOrchestration.ts`
- isConcurrencySafe 抛错时保守串行
- contextModifier 并发场景延后应用

---

## 10. 安全性 / 性能 / 扩展性分析

### 10.1 安全性

#### 做得好的地方
1. compact agent 不允许工具调用
2. 历史 tool_use/tool_result pairing 会修复，减少 resume 错乱
3. API 请求前 strip 过量 media，减少难恢复错误
4. withheld recoverable errors，避免 SDK/bridge 提前把会话打死
5. queued commands / task notifications 有 agentId 范围控制

#### 风险点
- `query.ts` 主循环极其复杂，新增分支时非常容易引入 recovery 死循环
- feature gates 太多，某些组合态可能难以完全测试覆盖

### 10.2 性能

#### 优化手段
1. `buildQueryConfig()` 一次快照
2. `QueryDeps` 便于瘦身与测试隔离
3. memory prefetch / skill prefetch 与主循环并行
4. streaming tool execution
5. raw stream 替代 SDK O(n²) partial JSON parsing
6. prompt cache / cache editing / compact cache sharing
7. microcompact + snip + collapse + reactive compact 多层上下文治理

#### 代价
- 状态机复杂度高
- 调试门槛高
- 需要大量 telemetry 才能定位问题

### 10.3 扩展性
这套架构非常强，但扩展点需要小心：
- 新 recovery 策略：适合加在 `query.ts`
- 新 compact 机制：适合挂 `services/compact/**`
- 新 API provider/betas/output mode：适合挂 `claude.ts` / model utils
- 新 turn-level policy：适合 `query/config.ts` 或 `query/deps.ts` 分层接入

---

## 11. 与其他模块的关系

### 上游
- `main.tsx` / REPL / headless runner
- 启动模块提供的 `toolUseContext` / settings / state

### 下游
- 工具系统：`services/tools/**`, `tools/**`
- API 系统：`services/api/**`
- compact 系统：`services/compact/**`
- hook 系统：`utils/hooks/**`
- attachment/memory/skill systems

### 核心耦合点
- `ToolUseContext`
- `normalizeMessagesForAPI`
- `queryModelWithStreaming`
- `buildPostCompactMessages`
- `StreamingToolExecutor`

---

## 12. 学习这个模块时建议的阅读顺序

### 推荐顺序
1. `source/src/query.ts`
2. `source/src/query/config.ts`
3. `source/src/query/deps.ts`
4. `source/src/services/tools/toolOrchestration.ts`
5. `source/src/services/api/claude.ts`
6. `source/src/services/compact/compact.ts`
7. 然后继续读：
   - `source/src/services/compact/autoCompact.ts`
   - `source/src/services/compact/microCompact.ts`
   - `source/src/query/stopHooks.ts`
   - `source/src/query/tokenBudget.ts`
   - `source/src/services/api/withRetry.ts`

### 为什么这样排
- 先看 query 主循环框架
- 再看 deps/config 的分层
- 再看工具执行 fallback
- 再看 API 请求构造
- 最后看上下文压缩

---

## 13. 容易忽略但关键的隐藏细节

### 细节 1：recoverable errors 会被暂时 withheld
这是为了不让 SDK/bridge 过早把错误当最终结果处理掉。

### 细节 2：streaming fallback 时需要 tombstone orphaned messages
否则 transcript 里会留下无效 thinking/tool_use 片段。

### 细节 3：tool summary 不是同步生成，而是上一轮结束后异步生成，下一轮开头再 emit
这是典型的 latency hiding。

### 细节 4：compact 后恢复的不是“全部历史”，而是 carefully curated attachments
包括 recently read files、plan、skills、agent 状态、delta attachments。

### 细节 5：`paramsFromContext` 是 API retry/fallback 正确性的关键枢纽
很多人读 `claude.ts` 时会忽略这一闭包，但它几乎控制了每次请求的全部动态参数。

### 细节 6：`query/deps.ts` 暗示未来 query loop 会继续往更纯状态机方向重构
这对理解代码演进路线很重要。

---

## 14. 逐文件精讲（本轮覆盖文件）

### 14.1 `source/src/query.ts`
- **文件作用**：Agent 主循环与 turn 状态机
- **导出的内容**：`query` 及内部 `queryLoop`
- **主要逻辑**：消息准备、compact/recovery、模型流式调用、工具执行、附件注入、继续下一轮
- **被谁使用**：REPL、headless、agent runtime
- **依赖了谁**：api、compact、tools、attachments、memory、stopHooks、tokenBudget
- **是否值得重点精读**：最高优先级

### 14.2 `source/src/query/config.ts`
- **文件作用**：query 入口配置快照
- **导出的内容**：`QueryConfig`, `buildQueryConfig`
- **主要逻辑**：把 env/statsig/session state 快照成不可变配置
- **被谁使用**：`query.ts`
- **依赖了谁**：bootstrap state、growthbook、env utils
- **是否值得重点精读**：高

### 14.3 `source/src/query/deps.ts`
- **文件作用**：query I/O 依赖注入层
- **导出的内容**：`QueryDeps`, `productionDeps`
- **主要逻辑**：封装可被测试替换的外部依赖
- **被谁使用**：`query.ts`
- **依赖了谁**：claude.ts、autoCompact、microCompact、crypto UUID
- **是否值得重点精读**：高

### 14.4 `source/src/services/tools/toolOrchestration.ts`
- **文件作用**：非流式工具批处理编排器
- **导出的内容**：`runTools`
- **主要逻辑**：按并发安全性分批，串行/并发执行工具并安全合并 contextModifiers
- **被谁使用**：`query.ts`（当不用 StreamingToolExecutor 时）
- **依赖了谁**：runToolUse、ToolUseContext、tool lookup
- **是否值得重点精读**：中高

### 14.5 `source/src/services/compact/compact.ts`
- **文件作用**：完整 compact 核心
- **导出的内容**：full/partial compact、post-compact messages/attachments 相关函数
- **主要逻辑**：摘要历史、PTL retry、compact cache sharing、post-compact restoration、hooks、boundary 构造
- **被谁使用**：query.ts、手动 /compact、session memory / 其他压缩路径
- **依赖了谁**：forkedAgent、prompt、hooks、attachments、analytics、session storage、tool search、token utils
- **是否值得重点精读**：极高

### 14.6 `source/src/services/api/claude.ts`
- **文件作用**：Claude API 适配与流式运行时
- **导出的内容**：queryModelWithStreaming/queryModelWithoutStreaming/queryHaiku/queryWithModel 及大量辅助函数
- **主要逻辑**：构造 API 请求、tool schema、message normalization、prompt caching、stream parsing、fallback/retry、usage/cost 统计
- **被谁使用**：query.ts、compact.ts、side-question/haiku/model-query 场景
- **依赖了谁**：Anthropic SDK、Tool helpers、messages utils、prompt cache、retry、telemetry、growthbook
- **是否值得重点精读**：最高优先级之一

---

## 15. 本轮已完成分析的文件列表（相对路径）

- `source/src/query.ts`
- `source/src/query/config.ts`
- `source/src/query/deps.ts`
- `source/src/services/api/claude.ts`
- `source/src/services/compact/compact.ts`
- `source/src/services/tools/toolOrchestration.ts`
- 以及 `source/src/services/compact/**`、`source/src/services/api/**`、`source/src/query/**` 目录清单扫描

---

## 16. 本轮未完成但下一轮建议继续分析的模块

1. 上下文治理深挖模块（autoCompact / microCompact / tokenBudget / stopHooks）
2. 模型与重试/错误模块（withRetry / errors / logging / client）
3. Memory / attachment / session 恢复模块
4. MCP 集成模块
5. 文件总索引表第二批（query/api/compact/services）

---

## 17. 当前累计已覆盖文件数 / 总文件数

- 已完成深读与模块级分析：**37 / 1954**
- 已完成路径扫描：**1954 / 1954**

---

## 18. 当前代码库学习进度

- **整体学习进度：46%**
- **Agent 主循环理解进度：75%**
- **内容级深读进度：约 37 / 1954**

下一步建议：进入 **上下文治理深挖模块**，也就是：
- `services/compact/autoCompact.ts`
- `services/compact/microCompact.ts`
- `query/tokenBudget.ts`
- `query/stopHooks.ts`
- `services/api/withRetry.ts`

这会把 query 主循环里最复杂的恢复与治理分支全部补齐。
