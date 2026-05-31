# Claude Code `agent / subagent / tool orchestration` 超深挖版

> 分析范围：`/home/ubuntu/.openclaw/workspace/cc/claude_code/source/src`
>
> 本文目标不是泛讲“agent loop 是什么”，而是**严格按这份代码库**解释：
>
> 1. orchestration 主循环到底在哪
> 2. tool orchestration 到底怎样发生
> 3. agent/subagent 到底怎样被创建、执行、转后台、恢复、回流
> 4. 哪些模块提及这些能力
> 5. 这些模块各自内部到底又包含哪些功能
> 6. 它们之间的真实调用链是什么

---

## 0. 一句话总结构

这套系统的真正内核可以压成一句话：

**`query.ts` 是总调度状态机，`services/api/claude.ts` 负责模型采样与流式协议，`StreamingToolExecutor` / `toolExecution.ts` 负责工具执行，`AgentTool` + `runAgent.ts` 负责把“调用 agent”变成“再起一个同构 query loop”，`LocalAgentTask` / `RemoteAgentTask` + `<task-notification>` 负责异步任务回流。**

所以它并不是“一个大模型一直自己想完一切”，而是更准确的：

1. 主线程 `query()` 发起一轮模型采样。
2. 模型流式吐出文本、`tool_use`、有时还有 `server_tool_use`。
3. runtime 一边接流，一边决定哪些工具可以并发执行、哪些必须独占。
4. 工具执行结果被包装成 `tool_result` 再喂给模型，进入下一轮。
5. 如果工具本身是 `AgentTool`，那不是普通函数调用，而是**启动一个新的子 query loop**。
6. 如果子 agent 走异步/后台路径，它不会直接把结果塞回父 assistant，而是通过 `task-notification` 进入消息队列，等父循环下一轮消化。

这就是 Claude Code 里真正的 orchestration 结构。

---

## 1. 先给完整模块地图

下面按“模块是否直接参与 orchestration 主链”分层。

---

## 2. 一级核心模块：直接构成主编排链

### 2.1 `query.ts`

这是**真正的总状态机**，不是普通 helper。

它负责：

- 维护整轮 query 的状态
- 调模型
- 接收流式 assistant 消息
- 收集 `tool_use`
- 驱动工具执行
- 合并 `tool_result`
- 在有 follow-up 时递归继续下一轮
- 处理 context compaction、microcompact、reactive compact
- 处理 `max_output_tokens_escalate` / `max_output_tokens_recovery`
- 处理 stop hooks
- 处理 queued commands / task notifications / memory attachments / skill attachments

关键点：

- `export async function* query(...)`
- 真正循环体在 `queryLoop(...)`
- `state` 内维护：
  - `messages`
  - `toolUseContext`
  - `turnCount`
  - `pendingToolUseSummary`
  - `maxOutputTokensRecoveryCount`
  - `transition`
  - compact tracking 等

**结论**：整个 Claude Code 的 orchestration 不是散落各处，而是被 `query.ts` 这一个循环驱动。

---

### 2.2 `services/api/claude.ts`

这是**模型协议层**，不是 orchestration 决策层，但它决定了主循环能收到什么事件。

它负责：

- 将内部 message transcript 变成 Claude API 请求
- 构造 system prompt blocks
- prompt caching
- 发送 streaming 请求
- 解析流式事件
- 将模型返回增量转成内部消息对象
- 兼容 `tool_use` / `server_tool_use`

它里面对 orchestration 最关键的事情有三件：

#### A. `normalizeMessagesForAPI(...)`

对应 `utils/messages.ts` 的正规化逻辑，作用是把内部 transcript 整理成 API 真正可接受的格式。

这意味着：

- 内部运行时 transcript 与 API payload 并不完全同构
- 发送前必须再做一次消息合法化

#### B. `ensureToolResultPairing(...)`

这一步非常关键，它会修正：

- assistant 中的 `tool_use`
- user 中的 `tool_result`
- 两者之间的配对合法性

这说明 Claude Code 已经把“tool_result 配对错误会炸 API”当成一等工程问题处理，而不是寄希望于上游逻辑永远完美。

#### C. `queryModelWithStreaming(...)`

它负责流式接收：

- `message_start`
- `content_block_start`
- `content_block_delta`
- `content_block_stop`
- `message_delta`
- `message_stop`

也正因为这层把 `tool_use` 增量地暴露给上层，`query.ts` 才能在同一轮里边收边执行工具。

---

### 2.3 `services/tools/StreamingToolExecutor.ts`

这是**流式工具编排器**，是整个“tool orchestration”最关键的实现之一。

它的核心职责不是“执行工具”本身，而是：

- 在模型流式产出 `tool_use` 的过程中，立刻接管这些 tool blocks
- 判断某个工具是否 concurrency-safe
- 并发执行所有可以并发的工具
- 保证独占工具不会与其它工具交错
- 即便并发执行，也要**按 tool_use 接收顺序回放结果**
- 在 streaming fallback / sibling error / interrupt 时合成 synthetic error tool_result

### 它内部的重要状态

`TrackedTool` 记录：

- `id`
- `block`
- `assistantMessage`
- `status`: `queued | executing | completed | yielded`
- `isConcurrencySafe`
- `promise`
- `results`
- `pendingProgress`
- `contextModifiers`

### 核心执行语义

#### `addTool(...)`

- 收到一个 `tool_use`
- 查 tool 定义
- 用 `inputSchema.safeParse` 先做输入解析
- 调 `toolDefinition.isConcurrencySafe(parsedInput.data)` 决定并发属性
- 放入队列后立即 `processQueue()`

#### `processQueue()`

- 遍历 queued tools
- 若当前执行状态允许，就 `executeTool(tool)`
- 对 non-concurrent 工具，一旦前面有执行中的不兼容工具，就停住

#### `executeTool(...)`

- 为每个工具建立独立 child abort controller
- 实际调用 `runToolUse(...)`
- 收集 progress / tool_result / contextModifier
- 如果某个 Bash 工具报错，会触发 sibling abort，取消并行兄弟工具
- 对被取消工具生成 synthetic `tool_result`

#### `getCompletedResults()`

- 立刻先吐出 progress
- 对已完成工具，按原始顺序回放结果
- 即便内部并发，外部看到的结果顺序仍然稳定

#### `getRemainingResults()`

- 在 query 主循环里等待所有工具完成
- 同时允许 progress 抢先露出

### 这个模块的真正意义

Claude Code 的“工具编排”并不是简单 `Promise.all(toolCalls)`。

它真正做的是：

- **运行时并发控制**
- **结果顺序稳定化**
- **中断传播**
- **错误级联**
- **progress 与 final result 分流**

这就是工程化 orchestration，而不是 prompt 层幻想。

---

### 2.4 `services/tools/toolExecution.ts`

这是**单个工具执行底座**。

如果说 `StreamingToolExecutor` 决定“什么时候执行哪些工具、怎么并发”，那 `toolExecution.ts` 决定“一个工具调用真正发生时，要走哪些步骤”。

它负责：

- 根据 `tool_use.name` 找到 tool 定义
- 兼容 alias / deprecated tool names
- 处理 unknown tool
- 输入 schema 校验
- deferred tool schema 提示
- permission check
- hook 执行
- progress 流
- 真实 tool.call
- tool_result 包装成内部 `user` message
- 错误变成 `<tool_use_error>`

### 关键函数

#### `runToolUse(...)`

输入是：

- `ToolUseBlock`
- 当前 assistant message
- `canUseTool`
- `ToolUseContext`

输出是：

- `AsyncGenerator<MessageUpdateLazy>`

这意味着 tool execution 本身也是流式的，而不是“一次调用返回一个定值”。

#### `checkPermissionsAndCallTool(...)`

这一层真正实现：

1. 输入解析
2. permission 决策
3. hooks / prompt / denial tracking
4. 调 `tool.call(...)`
5. 将结果包装回 `tool_result`

### 这个模块在 orchestration 中的地位

它是“模型发出 `tool_use` 后，运行时到底做了哪些工程动作”的真实落点。

所以主链实际上是：

`query.ts` 收到 tool_use → `StreamingToolExecutor`/`runTools` 决定执行顺序 → `runToolUse()` 真正跑工具 → 产生 `tool_result` → 再喂回 `query()`。

---

## 3. 二级核心模块：agent / subagent orchestration 层

### 3.1 `tools/AgentTool/AgentTool.tsx`

这是**多 agent orchestration 的中心入口**。

它不是“一个普通工具”，而是：

- tool schema 层的 agent 入口
- agent 选择器
- sync/async 决策器
- fork / remote / worktree / teammate 特殊分支总汇
- 子 agent 启动器
- 背景化中转站

### 它处理的分支比表面看起来多很多

#### 1. 普通 subagent
- 指定 `subagent_type`
- 选中某个 agent definition
- 构造 prompt
- 调 `runAgent(...)`

#### 2. implicit fork subagent
- `subagent_type` 省略
- 在 fork feature 开启时走 fork path
- 继承父 system prompt + 父上下文 + 父工具池

#### 3. async/background agent
- `run_in_background` 或 agent 定义 `background: true`
- 注册 `LocalAgentTask`
- 后台跑 `runAgent`
- 结束后发 `<task-notification>`

#### 4. foreground agent 可中途转后台
- 先同步运行
- 与 `backgroundPromise` race
- 一旦 background signal 触发，立刻切换为后台生命周期

#### 5. remote isolation agent
- `effectiveIsolation === 'remote'`
- 走 CCR / teleport / RemoteAgentTask

#### 6. worktree isolation agent
- `effectiveIsolation === 'worktree'`
- 先建 isolated worktree，再在该 cwd 里跑 agent

#### 7. teammate spawn 分支
- 传入 `name` 时，不走普通 subagent，而可能触发 `spawnTeammate(...)`

---

### 3.2 `AgentTool.tsx` 里的关键 orchestration 决策

#### A. analytics metadata

启动时会埋点：

- `agent_type`
- `model`
- `source`
- `color`
- `is_built_in_agent`
- `is_resume`
- `is_async`
- `is_fork`

这不是编排逻辑本身，但它告诉我们运行时显式区分这些路径。

#### B. `effectiveIsolation = isolation ?? selectedAgent.isolation`

这表示：

- tool call 参数优先级高于 agent definition
- isolation 可以在 invocation 时覆盖 agent 静态定义

#### C. remote isolation 分支

代码明确存在：

1. `checkRemoteAgentEligibility()`
2. eligibility 不通过时，拼接：
   - `Cannot launch remote agent:\n${reasons}`
3. `teleportToRemote({ initialMessage: prompt, description, signal, onBundleFail })`
4. 创建成功后 `registerRemoteAgentTask(...)`
5. 返回 `status: 'remote_launched'`

**注意**：当前源码分支被 `"external" === 'ant'` 保护，这是为了 build-time dead-code-elimination。也就是说：

- 代码逻辑真实存在
- 但 external 构建里这个分支会被裁掉
- 文档里不能把它误写成“任何构建运行时都会走到的逻辑”

#### D. fork path

fork path 时并不是给子 agent 一个新的普通 system prompt，而是：

- 尽量直接使用父线程已渲染好的 system prompt bytes
- `promptMessages = buildForkedMessages(prompt, assistantMessage)`
- `availableTools = parent exact tools`
- `useExactTools = true`

这都是为了**prompt cache 前缀最大复用**。

#### E. `shouldRunAsync`

它不仅受 `run_in_background` 控制，还受：

- `selectedAgent.background`
- coordinator mode
- fork subagent mode
- assistant/KAIROS mode
- proactive mode

影响。

这说明 async 不是单一参数触发，而是 orchestration policy 的综合结果。

#### F. foreground → background race

同步 agent 路径里，代码会：

- 提前 `registerAgentForeground(...)`
- 创建 `backgroundSignal`
- 在循环中 `Promise.race([agentIterator.next(), backgroundPromise])`

一旦用户或系统把它 background：

- 清理前台 iterator
- 再以 async 方式重新跑 `runAgent(...)`
- 注册 task progress / summarization / notification
- 立刻把当前 tool result 返回给父线程：`async_launched`

这个设计非常关键：

> 同一个 agent invocation 不是天生 sync 或 async 二选一，它可以先 foreground，再无缝转 background。

---

### 3.3 `runAgent.ts`

这是**subagent 真正的执行器**。

如果说 `AgentTool` 决定“要不要起一个 agent”，那 `runAgent.ts` 决定“一个 agent 被起起来后到底怎样跑”。

它做的事情非常多：

- 根据 agent 定义解析 model
- 构造 agent tools
- 构造 agent system prompt
- 建立 agent-specific MCP servers
- 创建 subagent context
- 注册 hooks
- 预加载 skills
- 写 agent metadata
- 写 transcript sidechain
- 最后调用 `query(...)`

**最重要的结论**：

> subagent 不是一个“特殊流程”，而是 `runAgent()` 里再次调用 `query()`，也就是“再起一个同构 orchestration loop”。

### `runAgent.ts` 的关键细节

#### A. `resolveAgentTools(...)`

正常 subagent 会自己解析工具池，而不是简单复用父线程工具池。

#### B. `override.systemPrompt`

fork 时可直接传父 prompt bytes，保持 cache-identical prefix。

#### C. abort controller 策略

- override 存在则用 override
- async agent 用新 controller
- sync agent 共享父 controller

#### D. SubagentStart hooks

`executeSubagentStartHooks(...)` 产生的 additional context 会作为 attachment/user message 注入子 agent 上下文。

#### E. frontmatter hooks / skills / MCP servers

agent 定义不是只有 prompt 和 tools，它还能带：

- hooks
- skills
- mcpServers
- memory scope
- permissionMode
- maxTurns
- isolation

这些都会在 `runAgent.ts` 里被真正落实到 agent runtime。

#### F. `createSubagentContext(...)`

这里把父 context 变成子 context：

- 新的 `agentId`
- 新的 `messages`
- 新的 tool pool
- 新的 mcpClients
- 可选共享 `setAppState`
- 可选共享 `setResponseLength`
- content replacement state 继承/重建

#### G. 写 transcript / metadata

- `recordSidechainTranscript(...)`
- `writeAgentMetadata(...)`

这就是为什么之后可以 `resumeAgentBackground(...)`。

#### H. 真正调用 `query(...)`

`for await (const message of query(...))`

这里等于说：

- 每个 subagent 自己拥有消息循环
- 自己也能触发 tools
- 自己也能再次用 AgentTool（某些模式下）
- 自己也经历 stop hooks / compaction / tool loop

#### I. finally 清理

结束时清理：

- MCP servers
- session hooks
- prompt cache tracking
- cloned file state
- transcript subdir
- todos
- shell tasks
- monitor tasks

说明子 agent 生命周期被当成真正的“独立运行体”处理。

---

### 3.4 `agentToolUtils.ts`

这是 AgentTool 家族的共享 runtime 工具库。

它最关键的能力有三块：

#### A. `resolveAgentTools(...)`

负责：

- wildcard `*` 展开
- disallowedTools 过滤
- agent tool spec 解析
- `allowedAgentTypes` 解析
- async / built-in / permissionMode 相关工具过滤

这意味着“一个 agent 拥有哪些工具”并不是简单数组，而是经过运行时过滤后的结果。

#### B. `finalizeAgentTool(...)`

负责：

- 从 agent messages 中抽最后有效文本
- 回退到最近一个带文本的 assistant message
- 统计 total tokens / tool uses / duration
- 埋点 `tengu_agent_tool_completed`
- 返回标准化 `AgentToolResult`

也就是说，subagent 的最终结果不是“最后一条消息原样透传”，而是经过 runtime 提炼与封装。

#### C. `runAsyncAgentLifecycle(...)`

这是 async 子 agent 生命周期驱动器，供：

- `AgentTool` async-from-start 分支
- `resumeAgentBackground(...)`

共用。

它负责：

1. 持续消费 `makeStream()` 产出的 agent messages
2. 更新 progress / summary
3. 完成后 `finalizeAgentTool(...)`
4. 标记 task completed
5. 生成 `enqueueAgentNotification(...)`
6. 异常时 fail / killed / partial result

这说明 async agent 的“后台编排”不是散在 `AgentTool.tsx` 里，而是已经被抽象成专用 lifecycle runner。

---

### 3.5 `forkSubagent.ts`

这是 Claude Code 里很容易被误解的一条分支。

它并不是“再起一个普通 agent，只是默认类型不同”，而是有自己非常特殊的上下文构造逻辑。

#### `isForkSubagentEnabled()`

开启后：

- `subagent_type` 可省略
- 省略时触发 implicit fork
- 所有 agent spawn 统一走 async / task-notification 交互模型
- coordinator mode 下互斥禁用

#### `FORK_AGENT`

定义了一个 synthetic built-in agent：

- `agentType: 'fork'`
- `tools: ['*']`
- `model: 'inherit'`
- `permissionMode: 'bubble'`

但它的 `getSystemPrompt()` 实际是空壳，真正用的是父线程已渲染 prompt bytes。

#### `buildForkedMessages(...)`

这是 fork 设计最关键的一段。

它会：

1. 克隆父 assistant message 的完整内容，包括所有 `tool_use`
2. 对每个 `tool_use` 生成一个统一 placeholder 的 `tool_result`
3. 在同一个 user message 末尾再附加当前 child 的 directive

为什么这么麻烦？

因为这样不同 fork child 的**请求前缀几乎完全相同**，只有最后 directive 不同，可以极大提高 prompt cache 复用率。

#### `isInForkChild(...)`

通过 `FORK_BOILERPLATE_TAG` 检测当前是不是 fork child，用于防止递归 fork。

**结论**：fork subagent 不是语义小变体，而是围绕“继承父上下文 + cache-identical prefix + 后台统一交互模型”设计的一套特殊 orchestration。

---

### 3.6 `resumeAgent.ts`

这是“停止/被驱逐的 agent 如何恢复”的核心实现。

它做的事情是：

1. 读取 transcript：`getAgentTranscript(...)`
2. 读取 metadata：`readAgentMetadata(...)`
3. 过滤 transcript 中不适合恢复的内容：
   - whitespace-only assistant
   - orphaned thinking-only
   - unresolved tool uses
4. 用 sidechain 中的 content replacement records 重建 replacement state
5. 恢复 worktree cwd（若存在）
6. 根据 metadata 重新确定 agent 类型
7. fork agent 的话重建父 system prompt
8. 重新 `registerAsyncAgent(...)`
9. 调 `runAsyncAgentLifecycle(...)` + `runAgent(...)`

### 它的重要意义

这说明 Claude Code 里的 background agent 不是只存在于内存 AppState 里，
而是：

- transcript 落盘
- metadata 落盘
- 状态可重建
- 执行可恢复

所以 `SendMessageTool` 才能做到“任务不在 state 里了，也尝试从 transcript resume”。

---

## 4. 三级核心模块：异步任务总线与结果回流

### 4.1 `tasks/LocalAgentTask/LocalAgentTask.tsx`

这个模块不是 UI 附件，而是**本地 background agent 的任务总线**。

它定义和管理：

- LocalAgentTaskState
- pendingMessages
- progress / summary
- foreground/background 切换
- terminal notification
- kill / fail / complete
- task registration

### 它内部有哪些关键能力

#### A. `pendingMessages`

任务状态里显式保存：

- `pendingMessages: string[]`

并提供：

- `queuePendingMessage(taskId, msg, setAppState)`
- `drainPendingMessages(taskId, getAppState, setAppState)`

这就是 SendMessage 向运行中 agent 注入新消息的真正落点。

#### B. `registerAsyncAgent(...)`

async agent 启动时：

- `initTaskOutputAsSymlink(...)`
- 建 abort controller
- 建 taskState
- `registerTask(...)`

也就是说，background agent 从一开始就进入统一 task framework，而不是临时变量。

#### C. `registerAgentForeground(...)`

同步 agent 也会先被注册成 foreground task，便于：

- UI 展示
- progress 汇报
- 随时转 background
- auto-background timer

#### D. `enqueueAgentNotification(...)`

当 agent 完成/失败/停止时，它会组装：

- `<task-notification>`
- `<task_id>`
- `<tool_use_id>`
- `<output_file>`
- `<status>`
- `<summary>`
- optional `<result>`
- optional `<usage>`
- optional worktree info

然后调用 `enqueuePendingNotification(...)`。

这一步非常关键，因为它说明：

> 异步 agent 的“回流”不是直接改父 assistant transcript，而是先变成一个队列中的 task-notification 消息。

#### E. `completeAgentTask / failAgentTask / killAsyncAgent`

这三者把 task 状态与通知分开：

- task 状态先转终态
- 输出文件可先被读
- notification 作为后续注入

这是一种非常典型的“状态转移优先、通知随后”的工程设计。

---

### 4.2 `tasks/RemoteAgentTask/RemoteAgentTask.tsx`

这是 remote agent 的对应总线。

它负责：

- `checkRemoteAgentEligibility(...)`
- `formatPreconditionError(...)`
- `registerRemoteAgentTask(...)`
- remote review / ultraplan 专门 notification
- 远端 log 抽取 review/plan/todo

### remote orchestration 的真实链路

1. `AgentTool` 判断 `effectiveIsolation === 'remote'`
2. 先 `checkRemoteAgentEligibility()`
3. 再 `teleportToRemote(...)`
4. 再 `registerRemoteAgentTask(...)`
5. remote session 的完成状态轮询/同步到本地 task
6. 最终也用 `<task-notification>` 回注主循环

### 关键结论

remote agent 并不是一个全新独立体系，而是：

- 前半段是 CCR/teleport
- 后半段仍然纳入同一套 task/notification 总线

也就是说它是“不同执行后端 + 同一个 orchestration bus”。

---

### 4.3 `cli/print.ts`

这是很多人第一次看会低估的模块。

它不仅负责显示输出，还负责**把 task-notification 重新送回模型循环**。

关键逻辑：

- 解析 `<task-notification>` XML
- 如果带 `<status>`，发一个 SDK system event：`subtype: 'task_notification'`
- **但不会就此消费掉**
- 注释写得很明确：`No continue -- fall through to ask() so the model processes the result`

这句话极其关键。

意思是：

> task-notification 不只是给 UI/SDK 看的，也是给主模型看的。

所以 async agent 的完成，不是“界面弹一下就完”，而是：

1. 任务完成
2. notification 入队
3. `print.ts` 解析出 SDK 事件
4. 同时继续把原始输入流到 `ask()`
5. `ask()`/`query()` 再开一轮，让主模型吸收这个结果继续 orchestration

这就是 async subagent 真正回到父 loop 的机制。

---

## 5. 四级关键模块：消息、上下文与 API 合法化

### 5.1 `utils/messages.ts`

虽然它不是“执行器”，但它对 orchestration 稳定性非常关键。

#### `normalizeMessagesForAPI(...)`

负责把内部消息修成发 API 的 shape。

它处理的意义在于：

- runtime transcript 可包含 UI-only / synthetic / attachment 等内部结构
- 但 Claude API 只接受严格约束的 messages

#### `ensureToolResultPairing(...)`

负责 tool_use / tool_result 配对修复。

这一步的重要性体现在：

- API 对 tool pairing 非常敏感
- 若不修复，query loop 可能在“还以为自己状态没问题”的情况下直接 400

### 结论

Claude Code 不是只在业务层做 orchestration，它还专门有一层“**消息协议修复层**”，来保证工具编排不会因为 transcript 细节坏掉。

---

### 5.2 `utils/attachments.ts`

这个模块里一个很重要但很容易忽略的点是：

#### `getAgentPendingMessageAttachments(...)`

它会：

- 根据 `toolUseContext.agentId`
- 调 `drainPendingMessages(...)`
- 把这些 message 包装成 `queued_command` attachment
- 注入给当前 agent

这就把 LocalAgentTask 里的 pendingMessages 与 query loop 真正接上了。

所以运行中 agent 收到新 message 的真实链路是：

`SendMessageTool.queuePendingMessage()`
→ `LocalAgentTask.pendingMessages`
→ `attachments.ts` 在下一轮工具边界 drain
→ 变成 attachment message
→ 子 agent 下一轮 query 看见它

这不是 side channel，而是被纳入正常消息系统。

---

## 6. 五级关键模块：agent 定义、工具边界与可用能力解析

### 6.1 `tools/AgentTool/loadAgentsDir.ts`

这是 agent definition 装载器。

它解析：

- JSON agents
- Markdown/frontmatter agents
- plugin agents
- built-in agents 合并
- tools / disallowedTools
- `mcpServers`
- `hooks`
- `skills`
- `memory`
- `background`
- `isolation`
- `permissionMode`
- `maxTurns`
- `effort`

### 为什么它属于 orchestration 相关代码

因为 orchestration 不只是“循环怎么跑”，还包括：

- 某个 agent 允许调用什么工具
- 某个 agent 是否后台运行
- 某个 agent 是否需要 worktree / remote isolation
- 某个 agent 是否预载 skills / hooks / MCP servers

这些能力都由这里决定。

### 特别关键的字段

- `background?: boolean`
- `memory?: 'user' | 'project' | 'local'`
- `isolation?: 'worktree' | 'remote'`
- `mcpServers?: AgentMcpServerSpec[]`
- `skills?: string[]`
- `hooks?: HooksSettings`

也就是说，agent definition 是一个小型 runtime policy 对象，而不只是 prompt 文本。

---

### 6.2 `tools/AgentTool/builtInAgents.ts`

负责 built-in agent 列表。

当前源码可见：

- `GENERAL_PURPOSE_AGENT`
- `STATUSLINE_SETUP_AGENT`
- `EXPLORE_AGENT`
- `PLAN_AGENT`
- `CLAUDE_CODE_GUIDE_AGENT`
- `VERIFICATION_AGENT`

并且在 coordinator mode 下会动态：

```ts
require('../../coordinator/workerAgent.js')
```

### 这里有一个重要源码事实

在当前 `source/src/coordinator` 目录中，我只看到了：

- `coordinatorMode.ts`

并没有看到：

- `workerAgent.ts`
- `workerAgent.js`

所以当前 source tree 里：

- `builtInAgents.ts` 明确提到了 coordinator workers
- 但 worker 定义源码不在当前 `source/src` 中
- 可能来自构建产物、生成文件或 source tree 缺失

因此，文档里可以确认：

- coordinator mode **确实存在**
- built-in agent 装载路径里**确实会尝试拿 coordinator workers**
- 但当前这份源码树里**缺该 worker 定义实现**，不能虚构其具体 worker prompt/agent list

---

### 6.3 built-in agent 各自表达了什么 orchestration 意图

#### `generalPurposeAgent.ts`
- 通用研究/搜索/多步任务 agent
- 工具基本全开
- 不主动创建文档文件

#### `exploreAgent.ts`
- 强限制 read-only
- 明确禁用 AgentTool / Edit / Write 等
- 鼓励并行 grep/read
- 偏“快速检索型子 agent”

#### `planAgent.ts`
- read-only planning agent
- 让它探索架构、输出实施计划
- 末尾要求列关键文件

#### `verificationAgent.ts`
- verification specialist
- background: true
- 禁止项目目录修改
- 强调必须真的跑验证命令
- 输出 `VERDICT: PASS|FAIL|PARTIAL`

这些 built-in agents 说明：

- Claude Code 的 subagent 不是一个“只有 prompt 不同”的薄层
- 它们在 tool availability、background 默认值、系统提醒、行为契约上都经过专门设计

---

### 6.4 `constants/tools.ts`

这是 orchestration 的“硬边界表”。

#### `ALL_AGENT_DISALLOWED_TOOLS`

所有 subagent 都默认禁掉一些工具，例如：

- `TaskOutput`
- `ExitPlanMode`
- `EnterPlanMode`
- 某些构建下的 `AgentTool`
- `AskUserQuestion`
- `TaskStop`
- workflow 工具

#### `ASYNC_AGENT_ALLOWED_TOOLS`

async agent 允许的工具集合。

这说明 async agent 不是“跟同步 agent 一样，只是后台跑”，它在工具能力上是专门受限的。

#### `IN_PROCESS_TEAMMATE_ALLOWED_TOOLS`

in-process teammate 会额外被允许：

- `TASK_CREATE`
- `TASK_GET`
- `TASK_LIST`
- `TASK_UPDATE`
- `SEND_MESSAGE`
- 某些 cron tools

这说明 teammate/swarm 机制是一条相邻但不同的多智能体路径。

#### `COORDINATOR_MODE_ALLOWED_TOOLS`

coordinator mode 下 coordinator 只允许：

- `AgentTool`
- `TaskStop`
- `SendMessage`
- `SyntheticOutput`

这非常关键，说明 coordinator 本质上是一个**纯调度者**，而不是全能执行者。

---

## 7. 六级相关模块：teammate / swarm 是相邻编排机制，不是主 subagent 链的同义词

用户要求“所有相关代码”。这部分必须单列，因为它和 AgentTool 交叉很多，但不是同一件事。

### 7.1 `tools/shared/spawnMultiAgent.ts`

这里实现了 teammate spawn。

它支持：

- in-process teammate
- out-of-process teammate（tmux / iTerm2 pane）

其中与主编排最相关的是：

#### `spawnTeammate(...)`
- AgentTool 也会调用它

#### `handleSpawnInProcess(...)`
- 创建 teammate identity
- 创建/注册 InProcessTeammateTask
- 启动 teammate execution loop

#### `registerOutOfProcessTeammateTask(...)`
- 即使是 pane/tmux teammate，也要注册进 task framework

### 结论

teammate/swarm 不是完全独立于 AgentTool，它们在入口层会交叉，但运行模型是另一套：

- 多偏向 mailbox/team 协作
- 有自己的 task type
- 有自己的 pending user messages
- 有自己的 permission / shutdown / idle 状态

---

### 7.2 `tasks/InProcessTeammateTask/InProcessTeammateTask.tsx`

这是 in-process teammate 的 task 管理器。

它维护：

- teammate identity
- pendingUserMessages
- idle 状态
- shutdown request/approval
- agentId → task 查找
- running teammates 列表

这和 `LocalAgentTask` 的定位不同：

- `LocalAgentTask` 是“一个后台 subagent task”
- `InProcessTeammateTask` 是“一个持续协作中的 teammate 任务体”

### 为什么要单独强调

因为如果把 teammate 与 subagent 混为一谈，就会误解：

- SendMessage 为什么有不同路由
- 为什么 constants/tools.ts 专门给 in-process teammate 额外工具
- 为什么 AgentTool 传 `name` 时可能走 `spawnTeammate()`

---

## 8. 七级相关模块：SendMessage 负责跨 agent 消息桥接

### `tools/SendMessageTool/SendMessageTool.ts`

这是多 agent 协作链里的桥。

它至少支持三类路径：

1. 发给外部地址（例如 socket / inter-claude）
2. 发给运行中的本地 agent
3. 发给已停止/已被驱逐但可 resume 的 agent

### 对本题最关键的是本地 agent 路径

#### 运行中的 local agent

若 task 仍是 running：

- `queuePendingMessage(agentId, input.message, ...)`
- 返回“Message queued for delivery ... at its next tool round.”

#### stopped 的 local agent

若 task 在但状态已终止：

- `resumeAgentBackground(...)`
- 自动在后台恢复
- 用户稍后收到通知

#### task 已被 evict，但 transcript 仍在

- 也会尝试 `resumeAgentBackground(...)`

### 这条链说明什么

agent 之间并不是只有“spawn -> finish”这种一次性交互。

它们可以：

- 运行中接续消息
- 停止后被自动恢复
- 被视为持续可通信实体

这把 subagent 从“一次函数调用”提升成了“可寻址、可恢复、可续跑的 actor”。

---

## 9. 八级相关模块：QueryEngine/ask/Task/print 之间的关系

### 9.1 `QueryEngine.ts`

`ask(...)` 是 one-shot 非交互封装器。

它做的事情是：

- 构造一个 `QueryEngine`
- 用给定工具、命令、agent definitions、messages、config 初始化它
- `yield* engine.submitMessage(...)`

这说明更上层入口并不是直接手写调用 `query()`，而是通过 QueryEngine/ask 包起来。

### 为什么重要

`cli/print.ts` 里 task-notification 解析后“fall through to ask()”，意味着：

- async agent 回流真正重新进入的是 `ask()` / `QueryEngine`
- 再由 QueryEngine 驱动底层 `query()`

因此主链更完整的说法是：

`print.ts` / `QueryEngine` / `ask()`
→ `query()`
→ `claude.ts`
→ tool execution
→ new messages
→ `query()` 下一轮

---

### 9.2 `Task.ts`

`Task.ts` 定义了统一 task abstraction：

- `TaskType`
  - `local_bash`
  - `local_agent`
  - `remote_agent`
  - `in_process_teammate`
  - `local_workflow`
  - `monitor_mcp`
  - `dream`

- `TaskStatus`
  - `pending`
  - `running`
  - `completed`
  - `failed`
  - `killed`

- `createTaskStateBase(...)`
- `generateTaskId(...)`

### 为什么重要

这意味着：

- agent orchestration 并不是私有特例
- 它被纳入更普遍的 task framework
- bash、agent、remote agent、workflow、teammate 都走统一任务模型

这也解释了为什么 `<task-notification>` 能成为统一回流协议。

---

## 10. 真实 end-to-end 调用链，按时间顺序彻底展开

下面按一条最典型的主链来展开。

---

### 10.1 用户消息进入系统

高层入口经：

- `print.ts`
- `QueryEngine.ask(...)`
- `QueryEngine.submitMessage(...)`
- 最终进入 `query()`

---

### 10.2 `query()` 准备本轮状态

它会：

- 取出当前 `messages`
- 挂上 `queryTracking`
- 做 budget/compact/snip/collapse 预处理
- 选模型
- 决定是否启用 `StreamingToolExecutor`

---

### 10.3 `query()` 调模型流式采样

`deps.callModel(...)` 最终进 `services/api/claude.ts`。

这时：

- system prompt blocks 被构造
- messages 被 `normalizeMessagesForAPI`
- tool use/result 被 `ensureToolResultPairing`
- 请求被发给 Claude

---

### 10.4 模型流式吐 assistant 内容

stream 可能产出：

- 普通 text
- thinking
- `tool_use`
- `server_tool_use`

`query.ts` 一边接收一边：

- 把 assistant messages 存起来
- 抽取 `msgToolUseBlocks`
- `toolUseBlocks.push(...)`
- 置 `needsFollowUp = true`

如果启用了 streaming tool execution：

- 对每个 tool block 立刻 `streamingToolExecutor.addTool(toolBlock, message)`

---

### 10.5 流式工具编排同时发生

`StreamingToolExecutor` 根据工具定义决定：

- 并发安全工具能并发跑
- 非并发工具必须独占
- progress 可以先冒出来
- 最终结果按原始顺序回放

这一步是真正的 tool orchestration。

---

### 10.6 工具真正执行

每个 `tool_use` 最终落到 `runToolUse(...)`：

- 找到 tool
- 校验输入
- 做 permission check
- 执行 hooks
- 调 tool.call
- 产出 `tool_result`

如果工具是普通文件/Bash/Web 工具，到这里就结束。

如果工具是 `AgentTool`，就进入下一层。

---

### 10.7 若工具是 `AgentTool`，则再起一个子 orchestration loop

`AgentTool.call(...)` 里会：

1. 选 agent definition
2. 决定 sync / async / fork / remote / worktree / teammate 分支
3. 构造 `runAgentParams`
4. 最终调 `runAgent(...)`

而 `runAgent(...)` 内部又会：

- 构造 agent-specific system prompt / tools / MCP / hooks / context
- 调 `query(...)`

所以**subagent 本质上就是一个递归 query loop**。

---

### 10.8 sync subagent 路径

若子 agent 走同步路径：

- 父 agent/tool 调用还保持打开
- `AgentTool` 消费 `runAgent()` 的消息流
- 收集 `agentMessages`
- 可能转发 `bash_progress` 给父级 UI
- 完成后 `finalizeAgentTool(...)`
- 把结果作为当前 `AgentTool` 的 tool_result 返回给父 query

于是父 query 会在同一轮结束后带着这个 `tool_result` 进入下一轮模型采样。

---

### 10.9 async subagent 路径

若子 agent 从一开始就 async，或者同步途中被 background：

- 先 `registerAsyncAgent(...)` 或已有 foreground task 转 background
- `runAsyncAgentLifecycle(...)` 在后台驱动 `runAgent()`
- 结束后 `enqueueAgentNotification(...)`
- notification 入消息队列

此时父线程并不会等子 agent 彻底跑完，而是当前 tool 调用尽快返回 `async_launched`。

---

### 10.10 async 结果如何回到父线程

这一步是很多人最关心的。

真实链路是：

1. 子 agent 完成
2. `LocalAgentTask` 组装 `<task-notification>`
3. `enqueuePendingNotification(...)`
4. 下一轮/下一次 drain 时，notification 进入 queued command snapshot
5. `query.ts` 通过 `getAttachmentMessages(...)` 把它变成 attachment/message 注入
6. `print.ts` 一方面把它解析成 SDK `task_notification` 事件
7. 另一方面继续 fall through 到 `ask()`
8. 主模型在下一轮看见这条 notification，继续决定后续动作

**所以 async 子 agent 不是“结果偷偷写到某个状态里”，而是通过 task-notification 明确进入主对话语境。**

---

## 11. 几条关键分支的差异对照

### 11.1 普通同步 subagent

- 入口：`AgentTool`
- 执行器：`runAgent()`
- 父线程是否等待：是
- 回流方式：直接 `tool_result`
- 适合：短任务、需要立即继续推理的任务

### 11.2 async/background subagent

- 入口：`AgentTool`
- 任务系统：`LocalAgentTask`
- 执行器：`runAsyncAgentLifecycle` + `runAgent`
- 父线程是否等待：否
- 回流方式：`<task-notification>`
- 适合：长任务、并行工作、统一后台交互模型

### 11.3 foreground 后中途 background 的 subagent

- 起初同步
- 中途通过 `backgroundSignal` 与 `agentIterator.next()` race
- 转后台后换成 async lifecycle
- 父线程立刻拿到 `async_launched`

### 11.4 fork subagent

- `subagent_type` 可省略触发
- 继承父 system prompt bytes
- 继承父 conversation slice
- 继承父 exact tools
- 通常强制 async
- 回流仍走 task-notification

### 11.5 remote agent

- 先 eligibility check
- 再 teleport/CCR
- 再 `registerRemoteAgentTask`
- 本地只维护 remote task 状态与回流
- 同样通过 task-notification 统一进入主线程

### 11.6 teammate/in-process swarm

- 不是普通 subagent
- 更像持续协作者/actor
- 通过 mailbox / pending messages / team context 协作
- AgentTool 有交叉入口，但生命周期和权限边界不同

---

## 12. tool orchestration 到底是怎么做到的，给最直接的代码级回答

如果只回答“工具编排到底怎么做的”，最准确的代码级说法是：

### 第 1 层：模型决定“想调用什么工具”

在 `query.ts` + `claude.ts` 流式采样中，模型输出 `tool_use` / `server_tool_use`。

### 第 2 层：runtime 决定“这些工具怎样执行”

`StreamingToolExecutor` / `runTools()` 决定：

- 是否立刻执行
- 是否能并发
- 是否需要独占
- 是否需要因为 sibling error 或用户中断而合成错误结果

### 第 3 层：单个工具执行器决定“调用一个工具需要经过哪些工程流程”

`runToolUse()` 决定：

- schema 是否合法
- 工具是否存在
- 是否需要 permission
- hook 是否拦截/修改
- tool.call 如何被包装

### 第 4 层：结果必须被重新编成消息

工具结果不会直接塞到某个隐藏变量里，而是必须被包装成：

- `user` message
- 内含 `tool_result`

然后再进入下一轮 `query()`。

### 第 5 层：agent tool 是特殊工具，但仍服从同样框架

`AgentTool` 并没有跳出工具编排系统，而是：

- 它自己就是一个 tool
- 只是其 `tool.call(...)` 的副作用不是读写文件，而是**启动一个新的 query loop**

这就是这套系统最关键的统一性。

---

## 13. 大模型“什么时候执行什么”

这个问题经常被描述得太抽象。按这份代码库，最准确答案如下。

### 模型执行的时机只有几类

#### 1. 初始用户输入后
主线程 `query()` 发起第一次采样。

#### 2. 本轮有 tool_result 后
工具执行结果被拼成新的 messages，`query()` 继续下一轮。

#### 3. stop-hook 阻断时
会插入 blocking errors 或 meta message 再重试。

#### 4. prompt-too-long / reactive compact / collapse drain 后
会用新压缩上下文重试。

#### 5. max output tokens hit 后
- 先可能 `max_output_tokens_escalate`
- 失败再 `max_output_tokens_recovery`
- 插入 meta “Resume directly...” 消息继续

#### 6. async task notification 到来后
主线程再开一轮，把通知作为新上下文处理。

### 模型不执行的时机

- 工具真正在跑时，模型不在“继续思考”，而是 runtime 在执行动作
- async 子 agent 后台跑时，父模型不会卡着等
- running subagent 接受 queued message 之前，父模型也不会提前知道内容，必须等注入下一轮

**因此这套系统本质是“采样 - 动作 - 采样 - 动作”的离散循环，而不是持续单流推理。**

---

## 14. 这份代码里几个非常关键但容易漏掉的工程点

### 14.1 tool_result pairing repair 是主链一部分，不是边角修补

如果没有 `ensureToolResultPairing(...)`，很多复杂 agent/tool 路径会在 API 侧直接炸掉。

### 14.2 async agent 的真正回流点不是 task state，而是 notification message

状态只是状态，**消息回流才会真正触发父模型继续编排**。

### 14.3 fork path 设计重点是 cache sharing，不只是 context inheritance

`buildForkedMessages(...)` 的复杂性几乎全是为了 prompt cache 前缀复用。

### 14.4 foreground/background 不是两套完全分离系统

同步 agent 可以动态转后台，说明 orchestration 被设计成连续体，而不是硬分叉。

### 14.5 agent 是可恢复 actor，不是一次性函数

有 transcript、metadata、resume、queued message，这些都说明 agent 被视为可寻址、可恢复、可续跑实体。

### 14.6 teammate/swarm 是相邻机制，不等同于普通 subagent

虽然入口与 task framework 有交叉，但 mailbox/team 协作语义不同，必须分开理解。

---

## 15. 模块提及关系总表

下面用“模块 -> 提及了什么 orchestration 能力 -> 自身内部包含什么功能”的方式汇总。

### A. 主循环与采样
- `query.ts`
  - 提及：tool orchestration、递归 query、attachments、task notification drain、token recovery
  - 包含：完整调度状态机
- `services/api/claude.ts`
  - 提及：tool_use、server_tool_use、message normalization、prompt caching
  - 包含：Claude API 流式协议层
- `QueryEngine.ts`
  - 提及：ask / one-shot query
  - 包含：高层 query engine 封装

### B. 工具执行
- `services/tools/StreamingToolExecutor.ts`
  - 提及：并发/独占工具执行
  - 包含：并发调度、顺序回放、sibling abort
- `services/tools/toolExecution.ts`
  - 提及：单个工具调用
  - 包含：schema、permission、hook、tool.call、tool_result
- `Tool.ts`
  - 提及：tool contract、`isConcurrencySafe`、`contextModifier`、permissions
  - 包含：tool runtime interface

### C. Agent / subagent
- `tools/AgentTool/AgentTool.tsx`
  - 提及：sync/async/fork/remote/worktree/teammate
  - 包含：agent spawn 决策总入口
- `tools/AgentTool/runAgent.ts`
  - 提及：subagent execution
  - 包含：真正的子 query loop
- `tools/AgentTool/agentToolUtils.ts`
  - 提及：agent tools 解析、finalize、async lifecycle
  - 包含：AgentTool 共享运行库
- `tools/AgentTool/forkSubagent.ts`
  - 提及：fork subagent
  - 包含：fork messages / cache-identical prefix / recursion guard
- `tools/AgentTool/resumeAgent.ts`
  - 提及：background agent resume
  - 包含：transcript 恢复 + 再次后台运行
- `tools/AgentTool/loadAgentsDir.ts`
  - 提及：agent 定义解析
  - 包含：tools/hooks/skills/mcpServers/memory/background/isolation 装载
- `tools/AgentTool/builtInAgents.ts`
  - 提及：built-in agents / coordinator workers
  - 包含：built-in agent 清单与条件装载

### D. 任务系统与回流
- `tasks/LocalAgentTask/LocalAgentTask.tsx`
  - 提及：background local agent
  - 包含：task state、progress、pendingMessages、notifications、foreground/background
- `tasks/RemoteAgentTask/RemoteAgentTask.tsx`
  - 提及：remote agent / remote review / ultraplan
  - 包含：eligibility、registerRemoteAgentTask、notification
- `cli/print.ts`
  - 提及：task-notification parsing
  - 包含：SDK event + fall through to ask() 回流
- `Task.ts`
  - 提及：统一任务抽象
  - 包含：TaskType/TaskStatus/TaskStateBase

### E. 多 agent 通信与 swarm 相关
- `tools/SendMessageTool/SendMessageTool.ts`
  - 提及：向 running/stopped/evicted agent 发消息
  - 包含：queuePendingMessage / resumeAgentBackground 路由
- `tools/shared/spawnMultiAgent.ts`
  - 提及：teammate spawn
  - 包含：in-process / pane teammate 启动
- `tasks/InProcessTeammateTask/InProcessTeammateTask.tsx`
  - 提及：in-process teammate lifecycle
  - 包含：task lookup、shutdown、pending messages
- `constants/tools.ts`
  - 提及：agent/coordinator/in-process teammate 工具边界
  - 包含：allowed/disallowed tool sets
- `coordinator/coordinatorMode.ts`
  - 提及：coordinator mode 开关与 prompt
  - 包含：coordinator role 定义

### F. 消息与附件补链
- `utils/messages.ts`
  - 提及：API message normalization / tool pairing repair
  - 包含：消息正规化与修复逻辑
- `utils/attachments.ts`
  - 提及：pendingMessages drain
  - 包含：把 queued agent messages 变成 attachments

---

## 16. 最终结论

如果把这份代码库里的 orchestration 真正讲透，可以浓缩成下面几条：

### 1. 主 orchestration 核不是 AgentTool，而是 `query.ts`
所有 agent/tool 分支最终都要回到 `query()` 这个循环。

### 2. tool orchestration 的核心不是 prompt，而是 runtime
真正决定并发、独占、顺序回放、取消传播的是 `StreamingToolExecutor` 和 `runToolUse()`。

### 3. subagent 的本质是“递归 query loop”
`runAgent.ts` 最终再次调用 `query()`，这就是 subagent 真正的执行方式。

### 4. async agent 通过 task-notification 回流，而不是直接把文本塞回父 assistant
`LocalAgentTask` / `RemoteAgentTask` 把完成事件写成 `<task-notification>`，再由 `print.ts` 和主循环重新吸收。

### 5. fork / remote / worktree / teammate 不是小配置，而是四种不同 orchestration 分支
- fork：为上下文继承与缓存共享优化
- remote：为 CCR/远端执行后端优化
- worktree：为文件系统隔离优化
- teammate：为持续协作 actor 优化

### 6. 这套系统已经明显从“prompt 编排”进化到“runtime 编排”
模型负责提出动作，runtime 负责：

- 合法化
- 权限
- 并发
- 生命周期
- 恢复
- 消息回流
- task 总线
- cache sharing
- context recovery

真正的 orchestration 在代码里，而不只在模型脑子里。

---

## 17. 当前源码树里的明确缺口 / 注意事项

### 17.1 coordinator worker 定义缺失

`builtInAgents.ts` 明确动态引用：

- `../../coordinator/workerAgent.js`

但当前 `source/src/coordinator` 目录只见：

- `coordinatorMode.ts`

未见：

- `workerAgent.ts`
- `workerAgent.js`

因此：

- 可以确认 coordinator mode 真实存在
- 可以确认 built-in agent 装载时尝试拿 coordinator workers
- 但当前源码树无法继续展开其具体 worker agent 定义与 prompt

### 17.2 remote isolation 分支是源码事实，但 external 构建下会被 DCE

不能把该分支写成“任意构建都运行时可达”。准确说法应是：

- 源码逻辑存在
- ant-only guard 允许外部构建裁剪该逻辑
- 文档中应明确区分“源码存在”与“当前构建是否生效”

---

## 18. 最简版心智模型（收尾）

最后用一句非常工程化的话总结：

**Claude Code 的 agent/subagent/tool orchestration，本质是一个递归的消息驱动状态机系统。**

- `query.ts` 负责每轮状态推进
- `claude.ts` 负责模型流事件
- `StreamingToolExecutor` 负责工具并发编排
- `runToolUse()` 负责单个工具调用生命周期
- `AgentTool -> runAgent()` 负责把“调用 agent”转成“再起一个 query loop”
- `LocalAgentTask / RemoteAgentTask` 负责把后台 agent 纳入统一任务总线
- `task-notification` 负责把异步结果重新注入父会话

这就是这份代码库里 agent/subagent/tool orchestration 的真实骨架。
