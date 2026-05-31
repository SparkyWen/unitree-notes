# Claude Code 代码库学习地图 - 模块 5：上下文治理与恢复层

- 模块名称：上下文治理与恢复层（AutoCompact / Microcompact / Token Budget / Stop Hooks / API Retry & Error Pipeline）
- 目标：把 `query.ts` 周边最复杂的“上下文控制、自动压缩、继续/停止决策、API 重试和错误分类”这一圈核心能力彻底讲透

---

## 1. 功能概述

这一层不是单独的业务模块，而是整个 Agent Runtime 的“稳定器”。

它解决的问题是：
- 上下文越来越长怎么办
- 什么时候应该自动 compact
- 哪些工具结果应该被轻量清除
- 模型什么时候应该“再继续干一点”而不是就此停止
- turn 结束时 stop hooks 如何介入
- API 报错时该不该重试、怎么重试、何时 fallback、何时彻底停止
- 错误怎么映射成用户可理解、系统可恢复、埋点可追踪的结构化事件

如果没有这一层，Claude Code 仍然能“跑”，但会：
- 更容易爆 context
- 更容易死在瞬时网络/容量问题上
- 更容易在长会话中逐渐退化
- 更容易在自动化模式里停得太早或继续得太久

所以这层本质上是：

> **为 Agent Runtime 提供弹性、稳定性和可恢复性。**

---

## 2. 解决的问题

### 2.1 长会话上下文膨胀
系统不能只靠一次性 `/compact`，必须有：
- proactive auto compact
- reactive compact
- microcompact
- time-based tool result clearing
- blocking threshold / warning threshold

### 2.2 工具结果并不都值得永久保留
例如大量：
- FileRead 结果
- Bash 输出
- Grep / Glob / WebFetch / WebSearch 结果

这些信息对“刚执行完的下一轮”很重要，但对很久之后的上下文价值会下降。

### 2.3 模型自然停下不等于任务真正完成
有些场景下：
- token budget 还没达到，希望模型继续完成
- 但如果已经连续多轮收益很小，就应该停

### 2.4 Turn 结束时需要外部策略介入
stop hooks 可能要求：
- 阻止继续
- 输出错误
- 触发 teammate/task completed hooks
- 触发 prompt suggestion / memory extraction / auto-dream

### 2.5 API 失败有不同恢复语义
- 429 / 529：可能重试
- fast mode 失败：降级 speed
- 401 / 403：可能 refresh auth / clear cache
- context overflow：可以动态调整 max tokens
- stream timeout：可以 fallback non-streaming
- 背景 query：很多错误没必要放大重试

### 2.6 错误不能只“显示出来”，还要被精细分类
系统需要同时服务：
- 用户 UI 文案
- 自动恢复逻辑
- telemetry / Datadog / OTLP
- resume/replay/debug

---

## 3. 涉及文件（本轮深读）

1. `source/src/services/compact/autoCompact.ts`
2. `source/src/services/compact/microCompact.ts`
3. `source/src/query/tokenBudget.ts`
4. `source/src/query/stopHooks.ts`
5. `source/src/services/api/withRetry.ts`
6. `source/src/services/api/errors.ts`
7. `source/src/services/api/logging.ts`

---

## 4. 模块核心入口文件

### 核心入口文件
- `source/src/services/compact/autoCompact.ts`
- `source/src/services/api/withRetry.ts`

### 最值得先读的 3~8 个文件
1. `source/src/services/compact/autoCompact.ts`
2. `source/src/services/compact/microCompact.ts`
3. `source/src/services/api/withRetry.ts`
4. `source/src/services/api/errors.ts`
5. `source/src/query/stopHooks.ts`
6. `source/src/query/tokenBudget.ts`
7. `source/src/services/api/logging.ts`

### 容易被忽视但关键的文件
- `source/src/query/tokenBudget.ts`
- `source/src/query/stopHooks.ts`
- `source/src/services/api/logging.ts`

这些文件通常不被当成“核心业务”，但它们正是系统看起来稳定、可用、可解释的关键原因。

---

## 5. 整体调用链 / 执行流程

### 5.1 上下文治理链

```text
query.ts 每轮开始
  -> autoCompact.shouldAutoCompact(...)
  -> autoCompact.autoCompactIfNeeded(...)
      -> trySessionMemoryCompaction()
      -> compactConversation()
  -> microcompactMessages(...)
      -> time-based MC / cached MC / no-op
  -> 若还超限 -> reactive compact / blocking limit
```

### 5.2 停止/继续决策链

```text
query.ts 本轮无 needsFollowUp
  -> handleStopHooks(...)
      -> Stop hooks / TeammateIdle / TaskCompleted
      -> 可能阻止继续或注入 blockingErrors
  -> checkTokenBudget(...)
      -> continue? 注入 nudge meta msg
      -> stop? 记录 completion event
```

### 5.3 API 恢复链

```text
claude.ts queryModel(...)
  -> withRetry(...)
      -> 429/529/401/403/5xx/timeout/context-overflow
      -> maybe fast-mode fallback / auth refresh / model fallback / retry
  -> errors.ts
      -> APIError -> Assistant API error message / error category
  -> logging.ts
      -> success/error telemetry, gateway detection, request chain linkage
```

---

## 6. 核心文件详细讲解

---

## 6.1 `source/src/services/compact/autoCompact.ts`

### 文件作用
这是**自动 compact 决策与执行调度中心**。

它不负责具体“怎么 summary”，而负责：
- 算阈值
- 判断何时该 compact
- 做 circuit breaker
- 优先尝试 session memory compact
- 再 fallback 到 full compactConversation

它是 proactive context governance 的核心入口。

---

### 关键常量与设计意图

#### `MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000`
compact 不是白送的，它自己也要留足输出 token 空间。

#### `AUTOCOMPACT_BUFFER_TOKENS = 13_000`
#### `WARNING_THRESHOLD_BUFFER_TOKENS = 20_000`
#### `ERROR_THRESHOLD_BUFFER_TOKENS = 20_000`
#### `MANUAL_COMPACT_BUFFER_TOKENS = 3_000`

这些 buffer 体现一种策略：
- 自动 compact 要更保守，提前触发
- 手动 `/compact` 的 blocking limit 则尽量晚一点，给用户留操作空间

#### `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3`
这是一个非常关键的 circuit breaker。

源码注释给了背景：
- 有些 session 会出现几十上百次连续 autocompact 失败
- 导致全局大量无效 API hammering

所以这里不是“失败了就下轮再试”，而是：
- 连续失败达到阈值后停止自动 compact

这非常工程化。

---

### 关键函数 1：`getEffectiveContextWindowSize(model)`

#### 输入
- `model: string`

#### 返回
- `context window - reserved summary output tokens`

#### 内部步骤
```ts
1. reserved = min(getMaxOutputTokensForModel(model), 20000)
2. contextWindow = getContextWindowForModel(model, getSdkBetas())
3. 若 env 设置 CLAUDE_CODE_AUTO_COMPACT_WINDOW，则取更小值
4. return contextWindow - reserved
```

#### 设计意义
真正可用的输入窗口，不等于模型名义上下文窗口。
必须给 compact summary 留出输出预算。

---

### 关键函数 2：`getAutoCompactThreshold(model)`

#### 作用
计算自动 compact 触发阈值。

#### 逻辑
```ts
autoCompactThreshold = effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS
如果设置 CLAUDE_AUTOCOMPACT_PCT_OVERRIDE:
  用 percentage threshold，但不会比默认阈值更激进
```

#### 为什么重要
这定义了“系统多早开始自我压缩”。

---

### 关键函数 3：`calculateTokenWarningState(tokenUsage, model)`

#### 输出
```ts
{
  percentLeft,
  isAboveWarningThreshold,
  isAboveErrorThreshold,
  isAboveAutoCompactThreshold,
  isAtBlockingLimit
}
```

#### 作用
把同一套 token usage 映射成多级风险状态：
- warning
- error
- auto-compact threshold
- hard blocking

#### 设计点
blocking limit 还支持：
- `CLAUDE_CODE_BLOCKING_LIMIT_OVERRIDE`

这让测试和灰度验证更容易。

---

### 关键函数 4：`shouldAutoCompact(...)`

这是 proactive compact 的主要决策器。

#### 输入
- `messages`
- `model`
- `querySource?`
- `snipTokensFreed = 0`

#### 关键分支

##### 分支 1：递归守卫
以下 source 不做 autocompact：
- `session_memory`
- `compact`
- `marble_origami`（context collapse agent）

##### 为什么
否则 forked agent 之间会互相踩共享状态、甚至死锁。

##### 分支 2：全局禁用
- `DISABLE_COMPACT`
- `DISABLE_AUTO_COMPACT`
- user config `autoCompactEnabled`

##### 分支 3：reactive-only 模式
如果启用 `REACTIVE_COMPACT` 且指定 growthbook 开关：
- suppress proactive autocompact
- 改由 API prompt-too-long 时再 reactive compact

##### 分支 4：context collapse 启用时 suppress autocompact
这是一个非常重要的设计。

原因是：
- context collapse 已经是上下文治理系统
- 若 autocompact 在 90%-95% 之间插进来，会抢在 collapse 之前把粒度更高的上下文直接 summary 掉

所以这里明确：
- context collapse on -> proactive autocompact off
- 但 reactive compact 仍保留作为 413/overflow fallback

##### 分支 5：token count 判断
最后通过 `tokenCountWithEstimation(messages) - snipTokensFreed` 与阈值比较。

---

### 关键函数 5：`autoCompactIfNeeded(...)`

#### 返回
```ts
{
  wasCompacted: boolean
  compactionResult?: CompactionResult
  consecutiveFailures?: number
}
```

#### 执行步骤
```ts
1. 若 DISABLE_COMPACT -> false
2. 若 consecutiveFailures >= 3 -> false
3. 调 shouldAutoCompact
4. 若不该 compact -> false
5. 先 trySessionMemoryCompaction(...)
6. 成功则：
   - reset summarized message id
   - runPostCompactCleanup
   - notifyCompaction
   - markPostCompaction
   - return success
7. 否则 fallback compactConversation(...)
8. 成功 -> reset failure count
9. 失败 -> 递增 consecutiveFailures
```

### 为什么先试 session memory compaction
这说明作者在尝试一种：
- 比 full compact 更轻量
- 对主上下文破坏更小

的实验性治理路径。

### 失败处理很关键
不是直接抛错，而是：
- 记录失败
- 递增连续失败计数
- 超阈值后熔断

这让系统在 irrecoverable session 上能“优雅放弃自动治理”。

---

## 6.2 `source/src/services/compact/microCompact.ts`

### 文件作用
这是**轻量级上下文清理层**，目标不是生成摘要，而是：

> **尽量不改主语义，只清掉旧的、价值下降的工具结果。**

它的思想和 full compact 完全不同。

---

### 核心设计思路
microcompact 主要有两条路径：

1. **cached microcompact**
   - 不直接改本地消息内容
   - 通过 cache editing / cache_edits block 删除旧工具结果
   - 尽量保住缓存前缀

2. **time-based microcompact**
   - 当上次 assistant 距现在太久，说明 server cache 已过期
   - 这时直接 content-clear 旧 tool results
   - 因为缓存本来就冷了，不需要再顾虑 preserve prefix

这非常聪明。

---

### 关键常量

#### `COMPACTABLE_TOOLS`
只 compact 某些工具：
- FileRead
- shell tools
- Grep / Glob
- WebSearch / WebFetch
- FileEdit / FileWrite

这说明 microcompact 不是对所有工具结果一视同仁，而是专挑“高体积、短时效”的类型。

---

### 关键函数 1：`estimateMessageTokens(messages)`

#### 作用
做粗略 token 估算。

#### 特点
- 文本、tool_result、image/document、thinking、tool_use 都分别处理
- 最后乘 `4/3` 作保守放大

#### 设计意义
在没有 API 精确 token 的时候，也要尽量偏保守，避免低估上下文风险。

---

### 关键函数 2：`microcompactMessages(messages, toolUseContext?, querySource?)`

#### 逻辑顺序
```ts
1. clearCompactWarningSuppression()
2. 先尝试 maybeTimeBasedMicrocompact()
   -> 触发就直接返回
3. 否则若支持 cached MC 且在主线程 querySource:
   -> cachedMicrocompactPath()
4. 否则 no-op
```

### 为什么 time-based 先于 cached-MC
源码注释写得很清楚：
- 如果 gap 太长，server cache 已经过期
- 这时 cache editing 没意义
- 直接内容清空更划算

这很有实际效果导向。

---

### 关键函数 3：`cachedMicrocompactPath(...)`

#### 核心思想
- 不修改消息内容
- 只跟踪 compactable tool result ids
- 生成 pending `cache_edits`
- 等下一次 API 请求时在 API 层插入 cache_edits block

#### 关键状态
- `cachedMCState`
- `pendingCacheEdits`
- `pinnedEdits`
- `registeredTools`
- `deletedRefs`

#### 执行步骤
```ts
1. collectCompactableToolIds(messages)
2. 遍历 user messages 中的 tool_result，注册到 state
3. getToolResultsToDelete(state)
4. createCacheEditsBlock(state, toolsToDelete)
5. pendingCacheEdits = cacheEdits
6. suppressCompactWarning()
7. notifyCacheDeletion()
8. 返回 messages 原样 + compactionInfo.pendingCacheEdits
```

### 设计亮点
#### 亮点 1：本地 transcript 不改，API 请求层再做 cache_edit
这能让：
- 对话显示稳定
- prompt cache 保留最大化

#### 亮点 2：有 baselineCacheDeletedTokens
因为 API 返回的是 cumulative `cache_deleted_input_tokens`，要用 baseline 算本次 delta。

这很细。

---

### 关键函数 4：`evaluateTimeBasedTrigger(...)`

#### 作用
判断是否该触发 time-based microcompact。

#### 条件
- config enabled
- querySource 必须显式存在且是 main thread
- 与上次 assistant message 的 gap > threshold

#### 为什么 querySource 必须显式 main thread
源码注释解释：
- 一些分析型路径（如 `/context`, `/compact`, analyzeContext）调用 microcompactMessages 只是分析用途
- 不该误触发实际清理

这是很谨慎的限定。

---

### 关键函数 5：`maybeTimeBasedMicrocompact(...)`

#### 核心逻辑
```ts
1. evaluateTimeBasedTrigger()
2. collectCompactableToolIds()
3. keepRecent 至少保留 1 个
4. clearSet = 老的 compactable tool results
5. 把 tool_result.content 替换为 TIME_BASED_MC_CLEARED_MESSAGE
6. 统计 tokensSaved
7. suppressCompactWarning()
8. resetMicrocompactState()
9. notifyCacheDeletion(querySource)
10. return mutated messages
```

### 为什么至少保留 1 个
源码注释很到位：
- `slice(-0)` 会把全部都保留，反直觉
- 清空全部工具结果也不合理
- 所以 floor 到至少 1 个

### 为什么 time-based 清理后要 reset cachedMCState
因为：
- 本地 prompt 内容已经变了
- 之前记录的 cached-MC tool ids 可能不再对应服务端可删除缓存项
- 不 reset，下轮 cached MC 会基于 stale state 做错误删除

这属于很容易漏掉、但非常关键的一致性处理。

---

## 6.3 `source/src/query/tokenBudget.ts`

### 文件作用
这是**“模型是否应该继续做更多工作”** 的 budget 决策器。

它不管总上下文，而管：
- 本轮/本次任务已经消耗了多少 turn tokens
- 继续一轮是否仍划算
- 是否进入 diminishing returns

---

### 核心结构

#### `BudgetTracker`
```ts
{
  continuationCount,
  lastDeltaTokens,
  lastGlobalTurnTokens,
  startedAt,
}
```

### 设计意义
它不是一次性判断，而是跨 continuation 的小状态机。

---

### 关键函数：`checkTokenBudget(...)`

#### 输入
- `tracker`
- `agentId`
- `budget`
- `globalTurnTokens`

#### 输出
- `ContinueDecision`
- 或 `StopDecision`

#### 逻辑
```ts
1. 若是 subagent 或 budget 无效 -> stop(null)
2. pct = turnTokens / budget
3. deltaSinceLastCheck = globalTurnTokens - tracker.lastGlobalTurnTokens
4. isDiminishing = continuationCount>=3 && 当前增量<500 && 上次增量<500
5. 若未 diminishing 且 turnTokens < 0.9 * budget:
   -> continuationCount++
   -> 记录本次 delta
   -> return continue(nudgeMessage)
6. 若 isDiminishing 或 continuationCount>0:
   -> return stop(completionEvent)
7. 否则 stop(null)
```

### 关键设计点

#### 设计点 1：不是简单“没到预算就继续”
它额外加入了 diminishing returns 检测：
- 连续多轮只增加很少 token，说明模型可能已经在原地打转或收尾过细

#### 设计点 2：subagent 不做 token budget 继续逻辑
说明这个机制主要针对主线程 agent loop。

#### 设计点 3：`getBudgetContinuationMessage(...)`
继续不是静默完成，而是给模型一个明确 nudge。

这使 continuation 成为显式引导，而不是隐式重试。

---

## 6.4 `source/src/query/stopHooks.ts`

### 文件作用
这是**turn 收尾阶段的 hook 编排器**。

它把“本轮模型输出完了，接下来需不需要额外策略动作”这件事统一起来。

它不是单纯执行 Stop hooks，还负责：
- prompt suggestion
- extract memories
- auto dream
- Chicago MCP cleanup
- teammate idle hooks
- task completed hooks
- stop hook summary / notifications / interruption recovery

这是 query 末尾治理层的核心文件。

---

### 核心函数：`handleStopHooks(...)`

#### 输入
- `messagesForQuery`
- `assistantMessages`
- `systemPrompt`
- `userContext`
- `systemContext`
- `toolUseContext`
- `querySource`
- `stopHookActive?`

#### 返回
`AsyncGenerator<... , StopHookResult>`

#### 结果类型
```ts
{
  blockingErrors: Message[]
  preventContinuation: boolean
}
```

---

### 执行阶段 1：构造 `REPLHookContext`

```ts
{
  messages: [...messagesForQuery, ...assistantMessages],
  systemPrompt,
  userContext,
  systemContext,
  toolUseContext,
  querySource,
}
```

### 设计点
这说明 hooks 拿到的是一个“完整 turn 视图”，而不是零散片段。

---

### 阶段 2：保存 cache-safe params
仅对：
- `repl_main_thread`
- `sdk`

保存 `createCacheSafeParams(stopHookContext)`。

#### 为什么重要
这些快照之后会被：
- `/btw`
- side_question SDK control_request
等路径使用。

---

### 阶段 3：非 bare 模式的后台 bookkeeping
如果不是 bare：
- `executePromptSuggestion(...)`
- `executeExtractMemories(...)`
- `executeAutoDream(...)`

#### 设计点
这几个动作是 fire-and-forget，不阻塞主路径。

而且：
- extract memories 仅在 extract mode active 且非 subagent
- auto dream 仅主线程

---

### 阶段 4：执行 Stop hooks

#### 执行器
`executeStopHooks(...)`

#### 循环中处理的内容
- progress messages -> 直接 yield
- attachment -> 收集 hook output / errors / duration
- blockingError -> 转成 meta user message
- preventContinuation -> 记录 stopReason，并发 attachment `hook_stopped_continuation`

#### 关键设计点

##### 点 1：hook summary message
如果有 hooks 跑过，会发：
- `createStopHookSummaryMessage(...)`

这意味着用户不仅看到零散 progress，还能在最后看到结构化总结。

##### 点 2：blockingErrors 与 preventContinuation 区分
这两个语义不是一回事：
- blockingErrors：需要模型下一轮处理这些错误
- preventContinuation：这轮就该停住，别继续了

##### 点 3：hook 运行中被 abort 要立刻转成 interruption
如果 `abortController.signal.aborted`：
- logEvent
- yield interruption message
- return preventContinuation

这是与 query 主循环取消语义对齐的。

---

### 阶段 5：teammate 专属 hooks
如果 `isTeammate()`：

#### 先跑 TaskCompleted hooks
- 找当前 teammate owner 的 in-progress tasks
- 对每个 task 运行 `executeTaskCompletedHooks(...)`

#### 再跑 TeammateIdle hooks
- `executeTeammateIdleHooks(...)`

### 设计点
这说明 stopHooks.ts 同时也是 team/agent collaboration runtime 的末端编排器。

普通主线程和 teammate 在收尾阶段行为不同。

---

### 错误处理
如果整个 stop hook 流程抛异常：
- 记录 `tengu_stop_hook_error`
- yield 一个对用户可见、对模型不可见的 system warning message
- 不阻断主流程

这很合理，因为 hook 是策略增强，不应轻易炸掉主会话。

---

## 6.5 `source/src/services/api/withRetry.ts`

### 文件作用
这是**API 调用的重试状态机**。

它不是单纯的 exponential backoff util，而是：
- 区分 querySource 前后台重要性
- 处理 fast mode cooldown/fallback
- 处理 OAuth / Bedrock / Vertex auth 问题
- 处理 context overflow 的 max_tokens 调整
- 处理 persistent unattended retry
- 处理 Opus -> fallback model 切换触发

这是 Claude Code 网络鲁棒性的核心之一。

---

### 核心结构

#### `RetryContext`
```ts
{
  maxTokensOverride?,
  model,
  thinkingConfig,
  fastMode?
}
```

#### `RetryOptions`
包含：
- `maxRetries`
- `model`
- `fallbackModel?`
- `thinkingConfig`
- `fastMode?`
- `signal?`
- `querySource?`
- `initialConsecutive529Errors?`

---

### 关键异常类

#### `CannotRetryError`
表示：
- 已确定不该再 retry
- 并保留 `originalError + retryContext`

#### `FallbackTriggeredError`
表示：
- 不是普通错误
- 而是应该切换模型重来
- 由上层 `query.ts` 负责真正 model fallback

这是非常清晰的职责边界。

---

### 核心函数：`withRetry(...)`

#### 输入
- `getClient`
- `operation(client, attempt, context)`
- `options`

#### 返回
`AsyncGenerator<SystemAPIErrorMessage, T>`

##### 注意
它不是普通 Promise，而是 generator：
- 中间可以 yield “系统级 API retry message”
- 最终 return 成功结果

这就是为什么 UI 能看到“将在 X 秒后重试”的系统提示。

---

### 重试主逻辑分解

#### 阶段 1：初始化 retryContext 与 counters
- `consecutive529Errors`
- `persistentAttempt`
- `client`
- `lastError`

#### 阶段 2：每次 attempt 前检查 abort
若 signal 已 abort：
- 直接 `APIUserAbortError`

#### 阶段 3：client refresh 条件
以下情况会强制重建 client：
- first attempt
- 401
- OAuth token revoked
- Bedrock auth error
- Vertex auth error
- stale connection (`ECONNRESET/EPIPE`)

##### stale connection 特别关键
如果 GrowthBook 开关允许：
- 发生 `ECONNRESET/EPIPE`
- 会 disable keep-alive 再重连

这明显是踩过连接池 stale socket 坑后的补丁。

---

#### 阶段 4：fast mode 特殊逻辑
如果当前是 fast mode 且 429/529：

##### 短 retry-after
- 短等一会儿
- 继续 fast mode
- 尽量 preserve prompt cache

##### 长 retry-after / 无 retry-after
- 触发 fast mode cooldown
- 切回 standard speed
- 避免 cache thrashing

##### 额外分支：overage disabled
如果 429 其实是 extra usage/overage 不可用：
- `handleFastModeOverageRejection(...)`
- 永久 disable fast mode

### 设计价值
这不是简单“遇限流就退避”，而是结合产品形态考虑：
- fast mode 继续 vs cooldown
- cache preservation vs user latency

---

#### 阶段 5：前台/后台 query 的 529 策略不同
`FOREGROUND_529_RETRY_SOURCES` 定义哪些 querySource 遇 529 才值得 retry。

例如：
- `repl_main_thread`
- `sdk`
- `agent:*`
- `compact`
- `side_question`
- auto-mode / security classifiers

而背景型 source：
- 直接放弃，不放大容量风暴

这非常重要。

---

#### 阶段 6：连续 529 与 model fallback
如果：
- 命中 529
- 又满足 Opus/fallback 条件
- 连续达到阈值

则抛出 `FallbackTriggeredError(originalModel, fallbackModel)`

##### 设计点
这里不自己切模型，而是把决策信号抛回 `query.ts`。

这保持了重试层“只负责网络/API恢复，不负责 query 主循环状态切换”。

---

#### 阶段 7：persistent unattended retry
如果开启：
- `CLAUDE_CODE_UNATTENDED_RETRY`
- 且是 429/529 transient capacity error

则：
- 长时间持续重试
- chunk long sleep 为 heartbeat interval
- 周期性 yield system retry messages
- 防止宿主把会话当 idle 杀掉

这是非常实战的 unattended automation 设计。

---

#### 阶段 8：max_tokens context overflow 自适应
如果 APIError 中可解析出：
- `input + max_tokens > context limit`

则：
- 动态算出 `availableContext`
- 扣 safetyBuffer
- 保证 thinking budget + 至少 1 output token
- 把 `retryContext.maxTokensOverride` 调低
- 下一次 attempt 用更小 max_tokens 重试

这是相当优雅的 overflow recovery。

---

### 辅助函数亮点

#### `shouldRetry529(querySource)`
把 retry amplification 风险和 query 重要性绑定起来。

#### `isPersistentRetryEnabled()`
受 feature gate + env 双控。

#### `getRetryDelay(...)`
支持 `retry-after`，否则指数退避 + jitter。

#### `parseMaxTokensContextOverflowError(...)`
把错误字符串解析成结构化数值，供自适应恢复使用。

---

## 6.6 `source/src/services/api/errors.ts`

### 文件作用
这是**API 错误分类与用户消息映射中心**。

它负责把各种底层错误，变成：
- 用户可读提示
- 可恢复错误标签
- SDK 错误类别
- analytics error type

这是 query.ts/claude.ts 的错误出口之一。

---

### 核心函数 1：`getAssistantMessageFromError(...)`

#### 作用
把 `unknown error` 映射成 `AssistantMessage` 形式的 API error message。

#### 它覆盖的错误极广，包括：
- timeout
- image size / image resize
- emergency capacity off switch
- rate limit (含新 unified headers)
- extra usage required for 1M context
- prompt too long
- PDF too large / invalid / password protected
- image dimensions exceed many-image limit
- AFK beta header rejected
- request too large (413)
- tool_use/tool_result mismatch
- duplicate tool_use id
- invalid model
- credit balance low
- API key invalid / OAuth revoked / org not allowed
- Bedrock model access problem
- 404 model unavailable
- generic auth / generic connection / generic error

### 为什么它重要
用户体验和自动恢复能否配合，很大程度上取决于这里怎么把错误“翻译”出来。

---

### 几个特别关键的设计点

#### 点 1：PromptTooLong 的 content 与 errorDetails 分离
- content 只保留稳定文案：`Prompt is too long`
- raw token counts 放进 `errorDetails`

这样：
- UI 可用固定字符串识别
- reactive compact 还能从 `errorDetails` 里解析 token gap

这是非常漂亮的双通道设计。

#### 点 2：media errors 同样保留 raw `errorDetails`
供 reactive compact 判断是否值得 strip/retry。

#### 点 3：429 不是都当 rate limit quota
如果没有 unified quota headers：
- 可能其实是 extra usage entitlement 问题
- 也可能是暂时 capacity
- 文案会尽量反映真实原因

#### 点 4：CCR mode 下 auth error 文案不同
remote 模式里 auth 由基础设施 JWT 管理，不应让用户去 `/login`。

这说明错误文案不是单纯 status code -> text，而是强依赖运行模式。

#### 点 5：tool_use/tool_result mismatch 错误会做专门 telemetry
还会在 ant 用户场景提示 `/share` 和 `/rewind`。

说明这类错误是已知、难查、但非常重视的线上问题。

---

### 核心函数 2：`classifyAPIError(error)`

#### 作用
给 telemetry / analytics 一个标准错误类别字符串。

包括：
- `aborted`
- `api_timeout`
- `repeated_529`
- `capacity_off_switch`
- `rate_limit`
- `server_overload`
- `prompt_too_long`
- `pdf_too_large`
- `image_too_large`
- `tool_use_mismatch`
- `duplicate_tool_use_id`
- `invalid_model`
- `credit_balance_low`
- `invalid_api_key`
- `auth_error`
- `bedrock_model_access`
- `ssl_cert_error`
- `connection_error`
- `unknown`

### 设计价值
让上层日志不必理解每个错误细节，只用统一 errorType 聚合分析。

---

## 6.7 `source/src/services/api/logging.ts`

### 文件作用
这是**API 层的成功/失败遥测与 request-chain 记录中心**。

它不只是埋点，还承担：
- gateway detection
- x-client-request-id / requestId 链接
- previousRequestId 追踪
- model output / thinking output / tool_use payload 大小统计
- total duration state 累加
- post-compaction 标记消费
- teleported session first message success/error tracking
- OTLP event 写入

这对复杂 query loop 的可观测性非常关键。

---

### 关键能力 1：Gateway detection
通过 response headers / base URL detect：
- litellm
- helicone
- portkey
- cloudflare ai gateway
- kong
- braintrust
- databricks

### 为什么重要
Claude Code 并不只跑在 Anthropic 一方环境里。
想理解线上问题，必须知道请求经过了哪个网关。

---

### 关键函数 1：`logAPIQuery(...)`

在请求发出前记录：
- model
- messagesLength
- temperature
- betas
- permissionMode
- querySource
- queryChainId / depth
- thinkingType / effort
- fastMode
- previousRequestId
- anthropic env metadata

### 设计点
这为后面 success/error 事件提供了完整因果前缀。

---

### 关键函数 2：`logAPIError(...)`

#### 记录内容
- errorType / errStr / status
- duration / attempt
- requestId / clientRequestId
- gateway
- queryTracking / querySource
- fastMode / previousRequestId
- invocation metadata

#### 关键细节
##### 点 1：`clientRequestId`
即使超时没拿到服务端 requestId，也能用 x-client-request-id 去后端查日志。

##### 点 2：connection details 会额外写 debug log
尤其是 SSL/TLS / ECONNRESET 这类。

##### 点 3：错误事件也会结束 tracing span
所以 beta tracing 不会丢尾巴。

---

### 关键函数 3：`logAPISuccessAndDuration(...)`

#### 作用
请求成功后，整合：
- usage
- costUSD
- duration
- ttft
- messageCount / messageTokens
- global cache strategy
- toolUse content lengths
- text/thinking length
- connector text count
- betas / previousRequestId

然后：
- 写 analytics
- 写 OTLP
- 结束 tracing span
- 记录 teleported session first success

### 设计点
#### 点 1：newMessages 会被进一步解析
提取：
- modelOutput
- thinkingOutput（ant only）
- hasToolCall

用于 tracing。

#### 点 2：`consumePostCompaction()`
logAPI success 时会把“这次是不是 post-compaction request”一起打出。

这对分析 compact 前后 cache hit / token cost 很有帮助。

---

## 7. 数据流 / 状态流

### 7.1 proactive compact 决策流

```text
messages + model + querySource
  -> shouldAutoCompact()
      -> env/user config/feature gate/context collapse/reactive-only/recursion guards
      -> token estimation vs threshold
  -> autoCompactIfNeeded()
      -> sessionMemoryCompact first
      -> compactConversation fallback
      -> failure count / circuit breaker
```

### 7.2 microcompact 状态流

```text
messages
  -> maybeTimeBasedMicrocompact()
      -> if cache cold gap big -> clear old tool_result content
  -> else cachedMicrocompactPath()
      -> pending cache_edits
      -> API layer inserts cache_edits later
```

### 7.3 token budget 决策流

```text
globalTurnTokens + budget + tracker
  -> checkTokenBudget()
      -> under 90% and non-diminishing => continue
      -> diminishing or enough => stop
```

### 7.4 stop hook 状态流

```text
turn end
  -> executeStopHooks()
  -> maybe blockingErrors / preventContinuation
  -> teammate-specific hooks
  -> background bookkeeping (prompt suggestion / extract memories / autoDream)
  -> return StopHookResult
```

### 7.5 API retry / error 映射流

```text
operation()
  -> withRetry()
      -> auth refresh / fast mode fallback / persistent retry / context overflow adjust / model fallback trigger
  -> on final error -> errors.ts classify/map
  -> logging.ts emit telemetry + tracing close
```

---

## 8. 配置项 / 环境变量 / 依赖注入方式

### 8.1 compact / context governance 相关

| 项目 | 来源 | 影响 |
|---|---|---|
| `DISABLE_COMPACT` | env | 禁用 compact |
| `DISABLE_AUTO_COMPACT` | env | 只禁用 auto-compact |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | env | 覆盖 autocompact context 窗口 |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | env | 以百分比改写 autocompact threshold |
| `CLAUDE_CODE_BLOCKING_LIMIT_OVERRIDE` | env | 覆盖 blocking limit |
| `tengu_cobalt_raccoon` | GrowthBook | reactive-only compact mode |
| `CONTEXT_COLLAPSE` | feature gate | 开启 collapse 时 suppress proactive autocompact |
| `CACHED_MICROCOMPACT` | feature gate | 启用 cache-edit based MC |

### 8.2 token budget / hooks

| 项目 | 来源 | 影响 |
|---|---|---|
| `TOKEN_BUDGET` | feature gate | 启用 token budget continuation |
| `CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION` | env | stopHooks 中 prompt suggestion |
| `EXTRACT_MEMORIES` | feature gate | stopHooks 中 extract memories |
| `TEMPLATES` | feature gate | stopHooks 中 job classification |
| `CHICAGO_MCP` | feature gate | turn end cleanup |

### 8.3 API retry / error

| 项目 | 来源 | 影响 |
|---|---|---|
| `CLAUDE_CODE_UNATTENDED_RETRY` | env + feature | 长时间 persistent retry |
| `CLAUDE_CODE_MAX_RETRIES` | env | 默认 max retries |
| `FALLBACK_FOR_ALL_PRIMARY_MODELS` | env | 529 时模型 fallback 条件 |
| `CLAUDE_CODE_REMOTE` | env | CCR auth/retry 语义 |
| `CLAUDE_CODE_USE_BEDROCK` | env | Bedrock auth / model access handling |
| `CLAUDE_CODE_USE_VERTEX` | env | Vertex auth handling |
| `tengu_disable_keepalive_on_econnreset` | GrowthBook | stale keep-alive socket 时 disable keepalive |

---

## 9. 错误处理 / 边界条件

### autoCompact.ts
- autocompact 连续失败 3 次后熔断
- context collapse / reactive-only / recursive querySource 下会 suppress
- sessionMemoryCompact 成功后需 reset summarized state + notify compaction

### microCompact.ts
- time-based trigger 只对显式 main-thread querySource 生效
- keepRecent floor 到 1
- time-based MC 后必须 reset cachedMCState
- cached MC 只在主线程 querySource 用，避免 forked agent 污染全局 state

### tokenBudget.ts
- subagent / invalid budget 直接 stop(null)
- diminishing returns 基于连续 3 次 continuation 后小增量判断

### stopHooks.ts
- hook abort 直接转 interruption
- hook 异常转 system warning，不炸主流程
- teammate hooks 与 main stop hooks 分层处理

### withRetry.ts
- 非 foreground querySource 遇 529 不重试
- fast mode 有专门 cooldown / short retry / overage rejection 路径
- auth / stale connection 会强制刷新 client
- persistent retry 用 heartbeat chunk sleep 避免宿主 idle kill
- context overflow 会动态下调 max_tokens

### errors.ts
- prompt-too-long / media errors 保留 raw errorDetails 供恢复层解析
- CCR / Bedrock / Vertex / external API key / OAuth revoked / org disabled 都有不同文案
- duplicate tool_use / mismatch tool_result 专门 telemetry

### logging.ts
- requestId/clientRequestId 双通道
- teleported session first message success/error 单独埋点
- tracing span 成功/失败都闭环

---

## 10. 安全性 / 性能 / 扩展性分析

### 10.1 安全性

#### 做得好的地方
1. stop hooks 与 teammate hooks 允许阻止 continuation，而不是只能旁观
2. compact/microcompact 都有 recursion/main-thread 边界，避免 forked agent 污染主状态
3. auth 错误文案按运行模式区分，避免误导用户
4. tool result clearing 只作用于选定 compactable tools，不盲删所有上下文

#### 风险点
- module-level cached MC state 如果未来接入更多 forked querySource，很容易再次踩共享状态问题
- hook 能力很强，外部脚本质量会直接影响 stop path 稳定性

### 10.2 性能

#### 优化手段
1. sessionMemoryCompact 优先于 full compact
2. cached microcompact 尽量 preserve cache prefix
3. foreground/background 529 retry 差异化，避免全局放大流量
4. fast mode fallback 兼顾缓存和用户体验
5. logAPI 成功/失败都尽量只捕获标量，避免 pin 大对象内存

#### 成本点
- context governance 层 feature gates 多、状态多，理解与调试成本高
- stop hooks 末端后台流程很多，若用户自定义 hook 很重，可能拖慢收尾阶段

### 10.3 扩展性
扩展点相对清晰：
- 新 compact trigger：加在 autoCompact.ts / microCompact.ts
- 新 stop strategy：加在 stopHooks.ts
- 新 retry policy：加在 withRetry.ts
- 新错误映射：加在 errors.ts
- 新日志字段/追踪：加在 logging.ts

这层已经很像“可持续演进的平台层”，不是一次性脚本。

---

## 11. 与其他模块的关系

### 上游
- `query.ts`
- `services/api/claude.ts`
- hooks / task / teammate / memdir / prompt suggestion / auto dream

### 下游
- `compactConversation()`
- cache editing API 层
- assistant message error mapping
- telemetry / OTLP / tracing
- session memory / stop hooks external commands

### 关键耦合点
- `query.ts`：调用 autoCompact / microcompact / stopHooks / tokenBudget
- `claude.ts`：调用 withRetry / errors / logging
- `bootstrap/state.ts`：post-compaction / API completion timestamps / teleported session state

---

## 12. 学习这个模块时建议的阅读顺序

### 推荐顺序
1. `source/src/services/compact/autoCompact.ts`
2. `source/src/services/compact/microCompact.ts`
3. `source/src/services/api/withRetry.ts`
4. `source/src/services/api/errors.ts`
5. `source/src/query/stopHooks.ts`
6. `source/src/query/tokenBudget.ts`
7. `source/src/services/api/logging.ts`

### 为什么这样排
- 先把上下文治理路径理解掉
- 再读网络/API 恢复层
- 最后读结束时的 stop/continue 逻辑

---

## 13. 容易忽略但关键的隐藏细节

### 细节 1：context collapse 开启时会 suppress proactive autocompact
这不是重复功能，而是为了防止两个治理系统互相抢跑。

### 细节 2：cached microcompact 不改本地消息，只在 API 层发 cache_edits
这对保留缓存前缀非常关键。

### 细节 3：time-based microcompact 触发后，必须 reset cachedMCState
否则下一轮 cached MC 会基于旧的服务端缓存假设做错误删除。

### 细节 4：foreground/background querySource 对 529 的重试策略完全不同
这能显著降低容量风暴时的 retry amplification。

### 细节 5：prompt-too-long / media size 的 raw errorDetails 会被保留下来，供恢复层二次解析
这是错误文案层与恢复逻辑层之间的一个非常优雅的桥。

### 细节 6：token budget continuation 不是“没到预算就继续”，而是带 diminishing returns 刹车
这个小文件很短，但设计很成熟。

---

## 14. 逐文件精讲（本轮覆盖文件）

### 14.1 `source/src/services/compact/autoCompact.ts`
- **文件作用**：自动 compact 阈值与执行调度中心
- **导出的内容**：threshold/state helpers、`shouldAutoCompact`、`autoCompactIfNeeded`
- **主要逻辑**：阈值计算、上下文警告状态、session memory compact 优先、failure circuit breaker
- **被谁使用**：`query.ts`
- **依赖了谁**：compactConversation、sessionMemoryCompact、token estimation、config/growthbook/state
- **是否值得重点精读**：极高

### 14.2 `source/src/services/compact/microCompact.ts`
- **文件作用**：轻量级工具结果清理层
- **导出的内容**：`microcompactMessages`、cached MC state helpers、time-based trigger helpers
- **主要逻辑**：cached microcompact、time-based microcompact、tool result token estimation、cache deletion notifications
- **被谁使用**：`query.ts`, `claude.ts`（cache_edits insertion 配合）
- **依赖了谁**：cachedMicrocompact、promptCacheBreakDetection、timeBasedMCConfig、token estimation
- **是否值得重点精读**：极高

### 14.3 `source/src/query/tokenBudget.ts`
- **文件作用**：token budget continuation 决策器
- **导出的内容**：`createBudgetTracker`, `checkTokenBudget`
- **主要逻辑**：按预算百分比与 diminishing returns 决定继续/停止
- **被谁使用**：`query.ts`
- **依赖了谁**：`utils/tokenBudget.ts`
- **是否值得重点精读**：高

### 14.4 `source/src/query/stopHooks.ts`
- **文件作用**：turn 收尾 hooks 编排器
- **导出的内容**：`handleStopHooks`
- **主要逻辑**：Stop hooks、TaskCompleted、TeammateIdle、prompt suggestion、memory extraction、auto dream、cleanup、summary/notification
- **被谁使用**：`query.ts`
- **依赖了谁**：hooks utils、attachments、tasks、teammate、autoDream、PromptSuggestion、extractMemories
- **是否值得重点精读**：极高

### 14.5 `source/src/services/api/withRetry.ts`
- **文件作用**：API 重试状态机
- **导出的内容**：`withRetry`, `CannotRetryError`, `FallbackTriggeredError`, retry helpers
- **主要逻辑**：指数退避、fast mode fallback、foreground/background 529 策略、persistent retry、context overflow 调整、auth refresh
- **被谁使用**：`services/api/claude.ts`
- **依赖了谁**：auth、fastMode、growthbook、proxy、sleep、errors utils
- **是否值得重点精读**：极高

### 14.6 `source/src/services/api/errors.ts`
- **文件作用**：API 错误映射与分类中心
- **导出的内容**：大量错误常量、`getAssistantMessageFromError`, `classifyAPIError` 等
- **主要逻辑**：把底层错误映射成用户消息与 analytics 分类，保留 errorDetails 供恢复层使用
- **被谁使用**：`claude.ts`, SDK/日志层
- **依赖了谁**：auth、model、limits、message helpers、error utils
- **是否值得重点精读**：极高

### 14.7 `source/src/services/api/logging.ts`
- **文件作用**：API 成功/失败日志与 tracing 桥
- **导出的内容**：`logAPIQuery`, `logAPIError`, `logAPISuccessAndDuration`
- **主要逻辑**：gateway detection、request chain logging、usage/cost/tracing/OTLP/teleport reliability logging
- **被谁使用**：`claude.ts`
- **依赖了谁**：analytics、telemetry、agentContext、bootstrap state、error classifier
- **是否值得重点精读**：高

---

## 15. 本轮已完成分析的文件列表（相对路径）

- `source/src/services/compact/autoCompact.ts`
- `source/src/services/compact/microCompact.ts`
- `source/src/query/tokenBudget.ts`
- `source/src/query/stopHooks.ts`
- `source/src/services/api/withRetry.ts`
- `source/src/services/api/errors.ts`
- `source/src/services/api/logging.ts`

---

## 16. 本轮未完成但下一轮建议继续分析的模块

1. Memory / attachment / session 恢复模块
2. MCP 集成模块
3. 模型 client/provider/config/认证模块
4. `source/src/commands/**` / `source/src/tools/**` 的逐子目录补齐
5. 文件总索引表第二批与覆盖审计推进

---

## 17. 当前累计已覆盖文件数 / 总文件数

- 已完成深读与模块级分析：**44 / 1954**
- 已完成路径扫描：**1954 / 1954**

---

## 18. 当前代码库学习进度

- **整体学习进度：56%**
- **上下文治理与恢复层理解进度：80%**
- **内容级深读进度：约 44 / 1954**

下一步建议：进入 **Memory / attachment / session 恢复模块**，因为 query loop 下一圈最强耦合的就是这部分：
- attachment messages
- SessionMemory
- conversation/session restore
- relevant memory prefetch
- nested memory / files / post-compact restoration
