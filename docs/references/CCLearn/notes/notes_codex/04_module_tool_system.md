# Claude Code 代码库学习地图 - 模块 3：工具系统模块

- 模块名称：工具系统（Tool Registry / Tool Definition / Tool Permission / Tool Execution）
- 目标：还原 Claude Code 中“工具是如何被定义、过滤、组合、授权、执行、流式回传结果”的完整机制

---

## 1. 功能概述

Claude Code 的工具系统，是整个 Agent Runtime 的核心基础设施之一。

如果命令系统回答的是：
- “用户/模型能触发哪些高层命令？”

那么工具系统回答的是：
- “模型在 agent loop 里能调用哪些具体能力？”
- “这些能力的参数 schema 是什么？”
- “它们何时可见？”
- “如何经过权限校验与 hook？”
- “怎么流式执行并把结果返回给模型与 UI？”

这个模块的核心不是单个 BashTool 或 FileReadTool，而是：

> **一套从 ToolDef 协议、到工具注册、到权限门控、再到执行器和结果映射的完整运行框架。**

---

## 2. 解决的问题

### 2.1 工具种类多且行为差异大
工具涵盖：
- Bash / PowerShell
- FileRead / FileEdit / FileWrite / NotebookEdit
- Grep / Glob / WebFetch / WebSearch
- Agent / Task / Team / Message / Cron / MCP / Skill
- 还有工作流、远程、LSP、REPL、Plan/Worktree 模式工具

它们需要统一协议。

### 2.2 工具可见性受模式/平台/feature gate 影响
例如：
- simple mode 只给 Bash/Read/Edit
- REPL mode 要隐藏 primitive tools
- embedded search tools 存在时不再暴露 Glob/Grep
- ant-only / feature-flagged 工具需要条件注入
- deny rules 需要在“模型看到工具前”就过滤

### 2.3 工具权限不能只在执行时检查
如果某工具被 blanket deny：
- 不能等模型调用了再拒绝
- 最好在工具列表阶段就剔除，减少无效调用和 prompt 污染

### 2.4 工具执行不是同步 RPC，而是流式带进度的状态机
一个 Bash 工具调用可能：
- 先排队
- 再执行
- 中间持续 progress update
- 可能 auto background
- 可能因 sibling bash error 被取消
- 最后再发 tool_result

### 2.5 工具结果既要面向模型，也要面向 UI
同一个 tool result，需要区分：
- UI 展示文本
- 搜索索引内容
- Claude API 的 `tool_result` block
- 大结果落盘后的 persisted-output 引导
- image/document/structured output 等特殊格式

### 2.6 Hook / Permission / Telemetry / ContextModifier 都要接入执行链
工具调用前后必须挂：
- pre-tool hooks
- permission decision
- post-tool hooks / failure hooks
- telemetry span/event
- context modifier
- progress message

这使得工具执行器比“调用一个函数”复杂很多。

---

## 3. 涉及文件（本轮深读）

1. `source/src/tools.ts`
2. `source/src/Tool.ts`
3. `source/src/services/tools/StreamingToolExecutor.ts`
4. `source/src/services/tools/toolExecution.ts`
5. `source/src/constants/tools.ts`
6. `source/src/tools/BashTool/BashTool.tsx`
7. `source/src/tools/FileReadTool/FileReadTool.ts`
8. `source/src/tools/FileEditTool/FileEditTool.ts`

另外本轮还扫描了整个：
- `source/src/tools/**`
- `source/src/services/tools/**`

---

## 4. 模块核心入口文件

### 核心入口文件
- `source/src/tools.ts`

### 最值得先读的 3~8 个文件
1. `source/src/Tool.ts`
2. `source/src/tools.ts`
3. `source/src/services/tools/toolExecution.ts`
4. `source/src/services/tools/StreamingToolExecutor.ts`
5. `source/src/tools/BashTool/BashTool.tsx`
6. `source/src/tools/FileReadTool/FileReadTool.ts`
7. `source/src/tools/FileEditTool/FileEditTool.ts`
8. `source/src/constants/tools.ts`

### 容易被忽视但关键的文件
- `source/src/Tool.ts`
- `source/src/services/tools/StreamingToolExecutor.ts`
- `source/src/constants/tools.ts`

很多人会先看具体工具实现，但如果不先理解 Tool 协议、执行器与 allowed/disallowed sets，就会只看到表层行为。

---

## 5. 整体调用链 / 执行流程

先给一个工具系统总图：

```text
main/query/repl
  -> tools.ts::getTools(permissionContext)
      -> getAllBaseTools()
      -> feature gate / mode filter / deny rule filter / isEnabled filter
  -> assembleToolPool(permissionContext, mcpTools)
      -> built-in tools + mcp tools 合并去重
  -> query.ts 收到 tool_use
      -> services/tools/StreamingToolExecutor.ts
          -> addTool()
          -> executeTool()
          -> services/tools/toolExecution.ts::runToolUse()
              -> schema parse
              -> validateInput
              -> pre-tool hooks
              -> permission decision
              -> tool.call(...)
              -> post-tool hooks / failure hooks
              -> mapToolResultToToolResultBlockParam
              -> 生成 user/tool_result/progress/attachment messages
```

这是一个非常完整的：

> **工具注册 -> 可见性裁剪 -> 执行编排 -> 结果映射** 主链路。

---

## 6. 核心文件详细讲解

---

## 6.1 `source/src/Tool.ts`

### 文件作用
这是工具系统的**核心协议定义文件**。

如果说 `types/command.ts` 是命令系统的领域模型，那么 `Tool.ts` 就是工具系统的领域模型。

### 为什么关键
因为所有工具最终都遵循这里定义的契约：
- 输入 schema
- 输出 schema
- 描述/提示词
- 权限检查
- UI 渲染
- 结果映射
- 是否只读/并发安全/搜索型工具
- activity / summary / auto-classifier input

### 当前从上下游关系可以确认的定位
- `tools.ts` 基于它聚合工具
- 各具体工具用 `buildTool(...)` 构造
- `toolExecution.ts` 基于它统一执行
- UI 与 query 主循环都依赖其协议字段

---

### 核心类型体系

#### 1) `ToolUseContext`
这几乎是工具执行的“运行时宇宙”。

它承载：
- app state getter/setter
- messages
- tools / commands
- notifications
- abort controller
- readFileState / fileHistory / content replacement state
- progress/state setters
- toolDecision 状态
- mcp clients
- query tracking
- 动态技能触发器
- nested memory attachment 触发器

#### 为什么重要
这说明工具不是纯函数：

> 工具运行在“整个 agent session 运行时上下文”里。

这也是为什么 tool execution 可以做到：
- 修改 app state
- 写 attachment message
- 更新 context
- 触发 skills discovery
- 发 progress message

---

#### 2) `ToolPermissionContext`
定义工具权限运行环境：
- mode
- alwaysAllowRules / deny rules / ask rules
- additional working dirs
- dangerous rule stripping
- auto mode availability
- sandbox / prePlan / automated checks 等

这是 tools.ts 过滤工具与 toolExecution.ts permission decision 的共同输入。

---

#### 3) `buildTool(def)`
这是统一工具构造器。

它给工具补默认行为，例如：
- `isEnabled -> true`
- `isConcurrencySafe -> false`
- `isReadOnly -> false`
- `isDestructive -> false`
- `checkPermissions -> allow`
- `toAutoClassifierInput -> ''`
- `userFacingName -> name`

### 为什么这个函数重要
它解决了两个工程问题：

#### 问题 1：工具定义很长，容易漏字段
统一默认值后，工具作者只需实现关键部分。

#### 问题 2：默认行为必须保守
特别是：
- 并发默认不安全
- 只读默认 false
- 权限默认不做额外冒险推断

这是偏安全的默认值策略。

---

## 6.2 `source/src/tools.ts`

### 文件作用
这是**工具注册与工具池装配中心**。

它负责：
- 给出所有 base tools 的完整候选集
- 按运行模式裁剪
- 按 feature gate 条件装载
- 按 deny rules 预过滤
- 与 MCP tools 合并
- 保持工具池顺序稳定以利 prompt cache

### 为什么它是中枢
因为 query/runtime 最终看到的工具列表，是从这里出来的。

---

### 关键函数拆解

#### 1) `getAllBaseTools()`

这是整个系统当前环境下“所有可能内建工具”的来源真相。

##### 返回内容特点
- 直接静态导入核心工具：Bash、Read、Edit、Write、Glob、Grep、Notebook、WebFetch、WebSearch、Todo 等
- 对 ant-only / feature-gated 工具用条件 `require`
- 对一些有循环依赖风险的工具，用 `getTeamCreateTool()` / `getSendMessageTool()` 这种 lazy require
- 会根据：
  - `USER_TYPE`
  - `feature(...)`
  - env flags
  - shell mode
  - worktree mode
  - todo v2
  - embedded search tools
  决定候选集

##### 设计亮点

###### 亮点 1：用 conditional require 做 dead code elimination / feature gate
这不仅是运行时开关，也是 bundle 大小与平台裁剪策略的一部分。

###### 亮点 2：用 lazy require 打破循环依赖
源码里明确写了：
- TeamCreateTool / TeamDeleteTool 等存在循环依赖风险

###### 亮点 3：`hasEmbeddedSearchTools()` 时不暴露 Glob/Grep
说明有些发行形态内建了更快的搜索工具，所以可以减少 tool surface。

---

#### 2) `filterToolsByDenyRules(tools, permissionContext)`

##### 作用
提前过滤“被 blanket deny 的工具”。

##### 关键设计
它使用与运行时权限检查相同的 matcher。

这意味着：
- 如果某工具被明确 deny
- 模型根本不会看到它

##### 为什么重要
这比“让模型调用后再拒绝”更高效也更安全：
- 减少 prompt 污染
- 减少无效 tool_use
- 对 MCP server prefix deny 也生效

---

#### 3) `getTools(permissionContext)`

这是 built-in tools 的主要入口。

##### 关键分支：simple mode
如果 `CLAUDE_CODE_SIMPLE`：
- 默认只给 Bash / FileRead / FileEdit
- 若 REPL mode 则改给 REPLTool
- coordinator mode 会再加 AgentTool / TaskStop / SendMessage

##### 普通模式流程
```ts
1. 拿 getAllBaseTools()
2. 剔除 special tools（MCP resources / synthetic output 等特殊注入）
3. 用 deny rules 过滤
4. 如果 REPL mode 开启且 REPLTool 存在，则隐藏 primitive tools
5. 再按 tool.isEnabled() 过滤
6. 返回结果
```

##### 重要设计点

###### 设计点 1：REPL mode 不只是“多一个工具”，而是“隐藏原始 primitive tools”
因为这些 primitive tools 在 REPL VM 内仍然可用，不需要直接暴露给模型。

###### 设计点 2：special tools 单独处理
说明不是所有工具都平铺在 base tool list 中，有些要通过后续合并逻辑注入。

---

#### 4) `assembleToolPool(permissionContext, mcpTools)`

##### 作用
把 built-in tools 和 MCP tools 合并成最终工具池。

##### 步骤
1. `getTools(permissionContext)`
2. 对 mcpTools 同样做 deny 过滤
3. built-in 与 mcp 各自按 name 排序
4. concat 后 `uniqBy('name')`

##### 为什么要先分区排序再合并
源码注释非常关键：
这是为了 **prompt cache stability**。

如果把 built-in 和 MCP flat sort：
- 某个新 MCP tool 排到 built-in 中间
- 会导致系统 prompt cache breakpoint 下游全部失效

所以它保持：
- built-in 作为连续前缀
- MCP 作为后缀分区

这是非常讲究的 cache-aware 排序设计。

---

#### 5) `getMergedTools(permissionContext, mcpTools)`

##### 作用
获取简单拼接后的 built-in + mcp tools

##### 适用场景
不是用于最终 prompt cache 稳定工具池，而是用于：
- tool search threshold
- token counting
- “考虑所有工具”的上下文

这说明：
- `assembleToolPool()` 是“最终稳定执行池”
- `getMergedTools()` 是“全量统计/判断视图”

---

## 6.3 `source/src/constants/tools.ts`

### 文件作用
这是**工具可用性策略常量文件**。

它定义哪些工具：
- 对 agent 不可用
- 对 async agent 可用
- 对 in-process teammate 可用
- 对 coordinator mode 可用

### 为什么重要
这不是简单常量，而是多 agent/多模式工具裁剪的重要策略层。

---

### 核心常量

#### `ALL_AGENT_DISALLOWED_TOOLS`
例如包含：
- `TASK_OUTPUT_TOOL_NAME`
- `EXIT_PLAN_MODE_V2_TOOL_NAME`
- `ENTER_PLAN_MODE_TOOL_NAME`
- 非 ant 情况下的 `AGENT_TOOL_NAME`
- `ASK_USER_QUESTION_TOOL_NAME`
- `TASK_STOP_TOOL_NAME`
- workflow tool（防止递归工作流）

##### 设计意图
防止子 agent / async agent 拿到不应该拥有的主线程能力。

---

#### `ASYNC_AGENT_ALLOWED_TOOLS`
允许 async agents 使用的工具，包括：
- FileRead / Grep / Glob / WebFetch / WebSearch
- shell tools
- FileEdit / FileWrite / NotebookEdit
- SkillTool / SyntheticOutput / ToolSearch
- Worktree enter/exit

这相当于定义了“异步子代理的能力边界”。

---

#### `IN_PROCESS_TEAMMATE_ALLOWED_TOOLS`
允许 in-process teammate 额外拥有：
- Task create/get/list/update
- SendMessage
- Cron create/delete/list（feature gated）

说明 in-process teammate 比普通 async agent 更接近主线程协作体。

---

#### `COORDINATOR_MODE_ALLOWED_TOOLS`
只允许：
- AgentTool
- TaskStopTool
- SendMessageTool
- SyntheticOutputTool

##### 设计意图
协调器本身不直接做生产性操作，而是：
- 分派 agent
- 停止任务
- 发送消息
- 产出协调性输出

这是很典型的 orchestrator/worker 分层。

---

## 6.4 `source/src/services/tools/StreamingToolExecutor.ts`

### 文件作用
这是**流式工具执行器**。

它不是单个工具逻辑，而是管理：
- 多个 streamed-in tool_use block
- 并发安全判断
- 队列调度
- progress 优先输出
- 错误级联取消
- 结果顺序输出

这是 query 主循环和 toolExecution 之间的关键桥梁。

---

### 核心数据结构

#### `TrackedTool`
包含：
- `id`
- `block`
- `assistantMessage`
- `status: queued | executing | completed | yielded`
- `isConcurrencySafe`
- `promise?`
- `results?`
- `pendingProgress`
- `contextModifiers?`

说明执行器不是简单 Promise.all，而是维护工具生命周期状态机。

---

### 核心方法拆解

#### 1) `addTool(block, assistantMessage)`

##### 作用
把 tool_use block 加入执行队列。

##### 关键逻辑
- 先 `findToolByName`
- 如果工具不存在，立刻构造 error tool_result
- 否则先用 `inputSchema.safeParse()` 判断输入是否合法
- 再调用 `toolDefinition.isConcurrencySafe(parsedInput.data)` 推断并发安全性
- 放入 `tools[]`
- 触发 `processQueue()`

##### 为什么先 parse 再判断并发安全
因为并发安全性可能依赖具体输入，比如：
- 某些 read-only 操作可并发
- 某些写操作不可并发

---

#### 2) `canExecuteTool(isConcurrencySafe)`

##### 逻辑
如果当前没有 executing tools，则可执行；
否则只有在：
- 当前工具并发安全
- 且所有 executing tools 都并发安全
时才能并发执行。

这是一种比较保守但安全的并发策略。

---

#### 3) `processQueue()`

##### 作用
扫描队列，启动能执行的工具。

##### 关键逻辑
- 对 queued tools 逐个看
- 若可执行则 `executeTool(tool)`
- 若遇到非并发安全工具且当前不能执行，则直接 break

##### 含义
这保证：
- 非并发安全工具不会被后面的工具“插队绕过”
- 顺序语义被保留

---

#### 4) `executeTool(tool)`

这是执行器最关键的函数。

##### 主要步骤
```ts
1. 标记 status=executing
2. 更新 inProgressToolUseIDs
3. 检查是否已被 sibling error / user interrupt / fallback 中断
4. 创建 toolAbortController（child of siblingAbortController）
5. 调用 runToolUse(...) 得到 async generator
6. for await 消费 generator：
   - progress -> pendingProgress
   - 普通消息 -> messages[]
   - contextModifier -> contextModifiers[]
   - 如果当前工具是 Bash 且出错 -> hasErrored=true, siblingAbortController.abort('sibling_error')
7. 结束后写回 results/contextModifiers/status
8. 非并发工具可把 contextModifiers 应用到全局 context
9. finally 触发 processQueue()
```

##### 最关键的设计点

###### 设计点 1：只有 Bash 错误会级联取消 sibling tools
源码注释明确：
- Bash 工具通常有隐式依赖链
- 一个 bash 失败，后续并行 bash 往往没意义
- 但 Read/WebFetch 这类通常相互独立，不应互相杀掉

这是非常有经验的差异化错误传播设计。

###### 设计点 2：progress message 和 result message 分开管理
`pendingProgress` 会被优先、即时 yield。

这能显著改善长命令体验。

###### 设计点 3：contextModifier 只有非并发工具才会真正应用到共享 context
因为并发工具同时改 context 容易出现语义冲突。

这是一个很明确的保守一致性策略。

---

#### 5) `getCompletedResults()` / `getRemainingResults()`

##### 作用
把执行结果按正确时序 yield 出去。

##### 特点
- progress message 可提前输出
- completed result 按接收顺序输出
- 若遇到 executing 且非并发安全工具，会阻止后续乱序输出

这保证：
- 用户看到的顺序合理
- 模型上下文中 tool_result 顺序稳定

---

## 6.5 `source/src/services/tools/toolExecution.ts`

### 文件作用
这是**单个工具调用的完整执行流水线**。

它处理：
- schema 校验
- validateInput
- pre-hook
- permission decision
- call tool
- telemetry
- tool result block 映射
- post-hook / failure hook
- attachment/progress/user messages 组装

这个文件是工具系统最复杂、最核心的执行层之一。

---

### 顶层入口

#### `runToolUse(toolUse, assistantMessage, canUseTool, toolUseContext)`

##### 作用
给定一个 Claude API 的 `tool_use` block，执行它并返回异步消息流。

##### 主要流程
```ts
1. 按名字找 tool（先从可见工具池，再 fallback 到 alias 对应 deprecated tool）
2. 若不存在 -> 返回 tool_result error
3. 否则调用 streamedCheckPermissionsAndCallTool(...)
4. 把内部 progress/result 转成统一 MessageUpdateLazy stream
```

##### 关键设计
支持“旧 transcript 用旧 alias 名调用已改名工具”的 fallback。

这对会话恢复、回放兼容非常重要。

---

### 核心函数：`checkPermissionsAndCallTool(...)`

这是整个工具执行链的真正主战场。

#### 输入
- `tool`
- `toolUseID`
- `input`
- `toolUseContext`
- `canUseTool`
- `assistantMessage`
- telemetry / request / mcp 信息
- `onToolProgress`

#### 返回
`Promise<MessageUpdateLazy[]>`

#### 执行步骤
高层伪代码：

```ts
1. zod safeParse(input)
   -> 失败则返回 InputValidationError tool_result

2. tool.validateInput(...)
   -> 失败则返回 validation error tool_result

3. 若是 Bash -> speculative classifier check

4. 若 tool.backfillObservableInput 存在
   -> clone processedInput
   -> 回填 legacy/observable 字段

5. runPreToolUseHooks(...)
   -> 收集 message / hookPermissionResult / updatedInput / stopReason
   -> 若 stop -> 返回 tool_result stop

6. start tracing spans

7. resolveHookPermissionDecision(...)
   -> 如果仍需 ask/deny/allow，通过 canUseTool 决策
   -> 记录 decision telemetry

8. 若 permission 非 allow:
   -> 构造 tool_result error / rejection message / image blocks / hook denied flow
   -> 返回

9. allow 情况下执行 tool.call(...)
   -> 可发 progress
   -> 收 result.data / structured_output / contextModifier / newMessages

10. mapToolResultToToolResultBlockParam(result.data, toolUseID)
    -> processToolResultBlock / storage / persistence

11. runPostToolUseHooks(...)
    -> 可能更新 MCP output / 追加消息

12. 若报错
    -> runPostToolUseFailureHooks(...)
    -> 生成 error tool_result
```

---

### 最关键的设计点

#### 设计点 1：输入处理分三层
1. `inputSchema.safeParse`：类型层
2. `tool.validateInput`：语义层
3. `checkPermissions` / `canUseTool`：权限层

这是非常标准而清晰的执行门控顺序。

#### 设计点 2：Hook 能修改输入，也能直接给权限决策
这说明 hooks 不是被动 observer，而是执行链参与者。

#### 设计点 3：backfillObservableInput 只影响 hook/permission 观察，不污染最终 tool.call 输入序列化
源码注释专门说明：
- 某些工具会扩展 `file_path`
- 但不应该改变最终 transcript/tool result 中嵌入的原始输入值

这是为了保证：
- transcript 稳定
- VCR fixture hash 稳定
- 用户看到的是模型原始输入语义

这个细节非常高级。

#### 设计点 4：tool_result 映射与持久化是统一层处理
不是每个工具自己操心大输出落盘逻辑，而是统一走：
- `processPreMappedToolResultBlock`
- `processToolResultBlock`

这有利于一致性。

#### 设计点 5：工具成功和失败都挂 hooks
- 成功走 `runPostToolUseHooks`
- 失败走 `runPostToolUseFailureHooks`

这使 hook 体系非常完整。

---

## 6.6 `source/src/tools/BashTool/BashTool.tsx`

### 文件作用
这是 Claude Code 里最复杂、最关键的工具之一：

> **shell 执行工具 + sandbox/permission/background/progress/semantic classification 的综合体。**

它不仅是“执行 bash 命令”，还承担：
- schema 定义
- 命令语义分类
- 只读判定
- sed edit 模拟写入
- sandbox 选择
- auto background
- progress 流式输出
- image output 识别
- persisted output 管理
- git/indexing/plugin hint/telemetry 收集

---

### 工具定义层关键字段

#### `isConcurrencySafe(input)`
逻辑：如果是只读命令，则可并发。

#### `isReadOnly(input)`
调用 `checkReadOnlyConstraints` 判断。

#### `preparePermissionMatcher({command})`
先 `parseForSecurity(command)`，再对 subcommands 做 wildcard/prefix 匹配。

##### 为什么关键
这样 `FOO=bar git push` 仍能匹配 `Bash(git *)` 规则。

#### `validateInput(input)`
会额外阻止：
- 长时间 `sleep N` 这类应该用 Monitor/后台的模式

#### `checkPermissions(input, context)`
调用 `bashToolHasPermission`

说明 Bash 的权限体系不是简单文件权限，而是专门一套 shell 规则判断。

---

### 几个关键辅助函数

#### `isSearchOrReadBashCommand(command)`

##### 作用
判断命令是否属于 search/read/list 类，可用于 UI collapse 与只读语义。

##### 核心逻辑
- 拆分 command operators
- 跳过 `echo/printf/true/false/:` 这种 semantic-neutral commands
- 若所有非中性子命令都属于 search/read/list 集，则整个命令视为可折叠只读类

##### 设计亮点
不是简单看第一个 token，而是分析整个 compound/pipeline 命令。

---

#### `detectBlockedSleepPattern(command)`
阻止 `sleep 5` / `sleep 5 && check` 这类长阻塞等待。

##### 设计意图
促使模型：
- 用 `run_in_background: true`
- 或用 Monitor tool

这是工具层对 agent 行为质量的约束。

---

#### `applySedEdit(simulatedEdit, toolUseContext, parentMessage)`

##### 作用
权限系统预览过的 sed 编辑，不再真的跑 sed，而是直接应用已批准结果。

##### 为什么重要
保证：
- 用户 preview 看到的内容
- 真正写入磁盘的内容

是一致的。

这是非常关键的安全/一致性设计。

---

### `call(...)` 主逻辑

#### 步骤概览
```ts
1. 若 _simulatedSedEdit -> 直接 applySedEdit
2. 创建 stdout accumulator
3. runShellCommand(...) 作为 async generator
4. 消费 progress updates
5. 获取最终 ExecResult
6. 语义解释 interpretCommandResult
7. 处理 sandbox failure / shell reset / git op tracking
8. 处理大输出 persistedOutputPath
9. telemetry / code indexing / plugin hint 记录
10. 处理 image output resize/compress
11. 返回 Out 数据结构
```

---

### `runShellCommand(...)` 主逻辑

这是 BashTool 真正的执行引擎。

#### 关键能力
- `exec(command, ...)`
- 支持 timeout
- 支持 progress callback
- 支持 shouldUseSandbox
- 支持 shouldAutoBackground
- 可显式 `run_in_background`
- 可 assistant mode auto-background
- 可 foreground -> background 切换
- 轮询 TaskOutput 获取增量输出

#### 设计亮点

##### 亮点 1：assistant mode 下 15s 后 auto-background
避免主 agent 被长命令卡死。

##### 亮点 2：foreground task 可 Ctrl+B 转 background
这属于非常强的交互式 shell 体验设计。

##### 亮点 3：即使 background race 和完成 race 交叉，也做了修补
源码里专门处理：
- 任务刚 background 就完成
- 避免重复 task notification
- reconstruct outputFilePath

这类 race 处理说明系统经历过实战打磨。

---

### BashTool 的安全设计
- shell permission 专门策略
- sandbox 可控
- sleep 阻断
- sed preview/approval 一致性
- persisted output 不直接塞爆上下文
- destructive/read-only/search/list 语义分类

### BashTool 的性能设计
- progress streaming
- auto background
- output truncation + persisted file
- image output resize
- classifier speculative start

### BashTool 的风险
能力太强，所以高度依赖：
- permission rules
- trust
- hooks
- sandbox
- external policy

---

## 6.7 `source/src/tools/FileReadTool/FileReadTool.ts`

### 文件作用
这是**统一的文件读取工具**，不仅支持文本，还支持：
- image
- notebook
- PDF
- extracted PDF pages
- file_unchanged stub

它是一个“多模态文件读取器”。

---

### 关键设计点

#### 1) `isConcurrencySafe() -> true`
读取天然适合并发。

#### 2) `isReadOnly() -> true`
这使它成为 streaming executor 中可安全并发的一类工具。

#### 3) `validateInput(...)`
除了权限 deny，还做：
- pages 参数解析
- UNC path 防护（避免 NTLM credential leak）
- binary extension 限制
- blocked device path 限制（如 `/dev/zero`, `/dev/tty`）

这不是简单读文件，安全边界很细。

---

### `call(...)` 主逻辑

#### 步骤概览
```ts
1. 读取 file reading limits
2. dedup: 如果同范围之前已读且 mtime 未变 -> 返回 file_unchanged stub
3. 触发 dynamic skill discovery / conditional skill activation
4. 根据文件类型分派到 callInner()
5. ENOENT 时做类似路径建议 / macOS screenshot thin-space fallback
```

#### dedup 设计很关键
如果同一个文件、同一个范围已经读过，而且文件未变：
- 不再把整段内容重新塞进模型上下文
- 只返回 `file_unchanged`

这对 cache_creation token 成本控制非常有价值。

---

### `callInner(...)` 分支

#### notebook
- 读 cells
- JSON 大小与 token 校验
- 存 readFileState
- 返回 notebook cells

#### image
- 单次读取 buffer
- resize / compress 到 token budget
- 返回 image block

#### PDF
- 支持 pages range
- 过大 PDF 强制 pages parameter
- 可在必要时提取页图像
- 支持 document block 注入

#### text
- `readFileInRange(...)`
- token 校验
- 更新 readFileState
- 通知 listeners
- line-number 格式化后返回

---

### 关键设计亮点

#### 亮点 1：FileRead 会触发 dynamic skills discovery
说明工具系统和技能系统是联动的。

#### 亮点 2：文件读取结果会写入 `readFileState`
后续 FileEdit/Write 工具会依赖这个状态，避免盲写。

#### 亮点 3：对 auto memory files 使用 freshness side-channel
通过 `WeakMap` 把 mtime 传给 mapper，而不污染输出 schema。

这是非常漂亮的“展示辅助信息 side-channel”设计。

#### 亮点 4：有专门的 malware analysis reminder 注入
读取文件后，tool_result 里会附带 cyber risk mitigation reminder（某些模型豁免）。

这体现了工具级安全引导，而不只是全局系统 prompt 约束。

---

## 6.8 `source/src/tools/FileEditTool/FileEditTool.ts`

### 文件作用
这是**受保护的精确文本编辑工具**。

它不是简单写文件，而是围绕：
- 必须先 Read 后 Edit
- old_string/new_string 精确匹配
- 文件未变更保护
- notebook 分流
- settings file 特殊校验
- file history / diff / LSP / VSCode 通知
- dynamic skills activation

构建的精确编辑器。

---

### `validateInput(...)` 关键步骤

```ts
1. expandPath(file_path)
2. 检查 team memory secret guard
3. old_string === new_string -> 拒绝
4. deny rule -> 拒绝
5. UNC path -> 直接放到权限系统处理，避免 NTLM 泄漏
6. stat size > 1 GiB -> 拒绝，防止 OOM
7. 读取当前文件内容（带 encoding 探测）
8. 文件不存在：
   - old_string=='' -> 允许作为新建文件
   - 否则给出 file not found + similar path 提示
9. 如果文件存在但 old_string=='' 且文件非空 -> 拒绝
10. .ipynb -> 提示改用 NotebookEditTool
11. 未先 Read 或 partial view -> 拒绝
12. 文件自上次 Read 后已修改 -> 拒绝
13. `findActualString(file, old_string)` 找真实匹配（含 quote normalization）
14. 多处匹配且 replace_all=false -> 拒绝并要求更多上下文
15. settings file 额外校验
```

这是一套极严谨的安全编辑门槛。

---

### `call(...)` 主逻辑

#### 步骤概览
```ts
1. expandPath
2. dynamic skill discovery / conditional activation
3. diagnosticTracker.beforeFileEdited
4. mkdir parent dir
5. fileHistoryTrackEdit
6. readFileForEdit() 读当前内容/encoding/line endings
7. 再次检查 read timestamp 防止竞态写入
8. findActualString + preserveQuoteStyle
9. getPatchForEdit()
10. writeTextContent()
11. 通知 LSP didChange/didSave
12. notifyVscodeFileUpdated
13. 更新 readFileState
14. 打 analytics / git diff / CLAUDE.md write event
15. 返回 structured patch result
```

### 最关键的设计点

#### 设计点 1：Read -> Edit 的强依赖
如果没读过文件或只是 partial view，不允许编辑。

这是防止模型盲改文件的核心安全约束。

#### 设计点 2：时间戳 + 内容回退校验
Windows 上 mtime 可能假变，所以：
- 先比 mtime
- 若是 full read 且内容未变，则允许继续

这是很实战的跨平台兼容处理。

#### 设计点 3：atomic-ish critical section 注释非常重要
源码明确说：
- 某些 await 不能放在 staleness check 和 write 之间
- 否则会引入竞态写入

说明作者非常清楚异步执行下的文件一致性问题。

#### 设计点 4：写完后会同步 LSP 和 VSCode 通知
这让 edit tool 不只是改文件，还能推动 IDE 状态刷新。

---

## 7. 数据流 / 状态流

### 7.1 工具池装配流

```text
permissionContext + feature/env/mode + mcpTools
  -> getAllBaseTools()
  -> getTools(permissionContext)
  -> assembleToolPool(permissionContext, mcpTools)
  -> query/runtime 拿到最终工具池
```

### 7.2 单次 tool_use 执行流

```text
tool_use block
  -> StreamingToolExecutor.addTool()
  -> executeTool()
  -> runToolUse()
  -> checkPermissionsAndCallTool()
      -> schema parse
      -> validateInput
      -> pre-hooks
      -> permission decision
      -> tool.call()
      -> post-hooks / failure hooks
      -> map tool result
  -> 返回 MessageUpdate stream
```

### 7.3 文件工具状态流

```text
FileReadTool
  -> readFileState.set(filePath, content/timestamp/offset/limit)

FileEditTool
  -> validateInput 依赖 readFileState
  -> call() 成功后更新 readFileState
  -> LSP/VSCode notify
```

### 7.4 Bash 执行状态流

```text
BashTool.call()
  -> runShellCommand() async generator
  -> progress output
  -> foreground/background transition
  -> final ExecResult
  -> interpret + persistence + telemetry
```

---

## 8. 配置项 / 环境变量 / 依赖注入方式

### 8.1 工具可见性受这些因素影响

| 项目 | 来源 | 影响 |
|---|---|---|
| `USER_TYPE` | env | ant-only tools 是否注入 |
| `feature(...)` | bundle feature gate | cron / monitor / browser / workflow / snip 等工具可用性 |
| `CLAUDE_CODE_SIMPLE` | env | simple mode 工具子集 |
| `ENABLE_LSP_TOOL` | env | LSPTool 是否启用 |
| `CLAUDE_CODE_VERIFY_PLAN` | env | VerifyPlanExecutionTool 是否注入 |
| `isPowerShellToolEnabled()` | runtime env/platform | PowerShellTool 是否可用 |
| `isReplModeEnabled()` | mode | 隐藏 REPL primitive tools |
| `isAgentSwarmsEnabled()` | feature/runtime | team tools 可用性 |
| `isWorktreeModeEnabled()` | feature/runtime | enter/exit worktree tools |
| `isToolSearchEnabledOptimistic()` | feature/runtime | ToolSearchTool 注入 |

### 8.2 工具执行依赖注入方式

#### 方式 1：ToolUseContext
几乎所有工具核心依赖都从这里来。

#### 方式 2：permissionContext
影响工具可见性与权限判断。

#### 方式 3：tool hooks / canUseTool callback
把外层交互授权系统注入到执行链里。

#### 方式 4：tool 内部 schema + helper utils
每个工具自己定义输入/输出与专用逻辑。

---

## 9. 错误处理 / 边界条件

### `tools.ts`
- deny rule blanket deny 直接从工具池剔除
- REPL simple/coordinator mode 做特殊子集裁剪

### `StreamingToolExecutor.ts`
- 未知工具：立即 error tool_result
- streaming fallback：discard pending tools
- Bash sibling error：级联 abort siblings
- user interrupt：生成 synthetic reject/error message

### `toolExecution.ts`
- schema parse error -> InputValidationError
- validateInput error -> tool_result error
- permission deny/ask -> tool_result reject
- tool.call error -> formatError + failure hooks
- alias fallback 支持旧 transcript

### `BashTool.tsx`
- shell syntax / security parse 失败 -> fail safe
- sleep pattern -> reject
- sed simulated edit -> bypass real sed execution but保持预览一致性
- large output -> persisted output
- race between backgrounding and completion handled specially

### `FileReadTool.ts`
- ENOENT -> suggest similar path
- blocked device path -> reject
- binary ext -> reject
- unsupported PDF / too many pages -> reject with instructions

### `FileEditTool.ts`
- no prior read / partial read -> reject
- file changed since read -> reject
- multiple matches -> reject
- notebook path -> redirect to NotebookEditTool
- oversized file -> reject

---

## 10. 安全性 / 性能 / 扩展性分析

### 10.1 安全性

#### 做得好的地方
1. **工具在可见性阶段就受 deny rules 过滤**
2. **Bash 与 File 工具有很多专属安全校验**
3. **UNC path / device path / path traversal / sed preview consistency 都有处理**
4. **Read-before-Edit 是强约束**
5. **MCP/base tool 都纳入统一 permission / hook 框架**

#### 风险点
- Bash/PowerShell 依然是高能力工具，策略和 hook 配置很关键
- 工具种类非常多，新增工具如果实现不规范，容易突破默认预期

### 10.2 性能

#### 优化手段
1. feature-gated lazy require
2. prompt cache aware tool pool sorting
3. tool progress streaming
4. Bash auto background + persisted output
5. FileRead dedup + conditional activation
6. Tool execution spans / telemetry for diagnosis

#### 成本点
- toolExecution.ts 很重，hook/permission/telemetry 全挂在一起
- 工具列表太大时 prompt token 成本高，所以才有 tool search / deferred tool 等体系

### 10.3 扩展性
工具系统扩展性非常强，原因是：
- 统一 `buildTool()` 协议
- 工具池注册中心明确
- 执行器统一
- hook / permission / telemetry / UI 渲染可复用

如果未来要新增工具，理论上只要：
1. 实现 ToolDef
2. 在 `tools.ts` 注册
3. 处理 prompt / UI / permissions 即可

---

## 11. 与其他模块的关系

### 上游
- 启动模块：提供 permission context / app state / mcp tools
- 命令系统：SkillTool 等会间接触发命令相关能力
- query 主循环：真正驱动 tool_use 执行

### 下游
- 文件系统
- shell/sandbox
- hooks
- telemetry
- MCP client
- task/background system
- LSP/VSCode integration

### 关键耦合点
- `Tool.ts`：协议中心
- `toolExecution.ts`：执行中枢
- `StreamingToolExecutor.ts`：流式调度
- `tools.ts`：可见性与组合中枢

---

## 12. 学习这个模块时建议的阅读顺序

### 推荐顺序
1. `source/src/Tool.ts`
2. `source/src/tools.ts`
3. `source/src/constants/tools.ts`
4. `source/src/services/tools/StreamingToolExecutor.ts`
5. `source/src/services/tools/toolExecution.ts`
6. `source/src/tools/FileReadTool/FileReadTool.ts`
7. `source/src/tools/FileEditTool/FileEditTool.ts`
8. `source/src/tools/BashTool/BashTool.tsx`
9. 然后按类别读其他 `source/src/tools/**`

### 为什么这样排
- 先读协议
- 再读注册中心
- 再读执行器
- 最后读典型工具样本

---

## 13. 容易忽略但关键的隐藏细节

### 细节 1：工具池排序是为 prompt cache 稳定性服务的
不是单纯为了好看。

### 细节 2：工具 deny 不只是执行期行为，也会影响模型能否看到工具
这是安全和成本双优化。

### 细节 3：StreamingToolExecutor 只会让 Bash 错误级联取消 siblings
这是精心区分依赖性后的设计，不是统一粗暴取消。

### 细节 4：backfillObservableInput 与 callInput 分离是为了 transcript 稳定性
这个细节非常容易漏掉，但很高级。

### 细节 5：FileRead 会激活 conditional skills / dynamic skills
说明工具调用会反过来改变后续工具/技能可见面。

### 细节 6：BashTool 不只是 shell wrapper，而是 background task runtime 的前台入口
它已经内嵌了任务系统能力。

---

## 14. 逐文件精讲（本轮覆盖文件）

### 14.1 `source/src/Tool.ts`
- **文件作用**：工具协议定义中心
- **导出的内容**：Tool/ToolDef/ToolUseContext/ToolPermissionContext/buildTool/helpers
- **主要逻辑**：统一工具定义契约与默认行为
- **被谁使用**：所有 tools、tools.ts、toolExecution.ts、query 主循环
- **依赖了谁**：基础类型与上下文类型
- **是否值得重点精读**：极高

### 14.2 `source/src/tools.ts`
- **文件作用**：工具注册与工具池装配中心
- **导出的内容**：getAllBaseTools/getTools/assembleToolPool/getMergedTools 等
- **主要逻辑**：按 env/feature/mode/deny-rules 过滤并组合工具
- **被谁使用**：main/query/repl/agent runtime
- **依赖了谁**：各工具实现、permissions、feature gates、constants/tools.ts
- **是否值得重点精读**：极高

### 14.3 `source/src/constants/tools.ts`
- **文件作用**：多 agent / mode 工具可用性策略常量
- **导出的内容**：ALL_AGENT_DISALLOWED_TOOLS / ASYNC_AGENT_ALLOWED_TOOLS / COORDINATOR_MODE_ALLOWED_TOOLS 等
- **主要逻辑**：定义不同代理和模式下允许/禁止的工具集合
- **被谁使用**：agent/coordinator/in-process runner/tool filtering 相关模块
- **依赖了谁**：各工具常量名与 shell tool names
- **是否值得重点精读**：高

### 14.4 `source/src/services/tools/StreamingToolExecutor.ts`
- **文件作用**：流式工具队列执行器
- **导出的内容**：`StreamingToolExecutor`
- **主要逻辑**：排队、并发安全控制、progress 优先输出、结果顺序产出、Bash sibling cancel
- **被谁使用**：query 主循环 / tool orchestration
- **依赖了谁**：runToolUse、ToolUseContext、message helpers
- **是否值得重点精读**：极高

### 14.5 `source/src/services/tools/toolExecution.ts`
- **文件作用**：单次工具执行总流水线
- **导出的内容**：`runToolUse` 及相关执行函数
- **主要逻辑**：schema 校验、input validation、hook、permission、tool.call、result mapping、telemetry、failure handling
- **被谁使用**：StreamingToolExecutor
- **依赖了谁**：Tool protocol、hooks、permissions、telemetry、tool result storage、MCP utils
- **是否值得重点精读**：极高

### 14.6 `source/src/tools/BashTool/BashTool.tsx`
- **文件作用**：shell 执行工具与后台任务桥梁
- **导出的内容**：`BashTool`，多个辅助函数与类型
- **主要逻辑**：命令校验、只读/搜索判定、sandbox/background/progress/output persistence/image output/sed edit handling
- **被谁使用**：tools.ts、toolExecution.ts
- **依赖了谁**：shell utils、sandbox、permissions、task system、analytics、file utilities
- **是否值得重点精读**：极高

### 14.7 `source/src/tools/FileReadTool/FileReadTool.ts`
- **文件作用**：多模态文件读取工具
- **导出的内容**：`FileReadTool`、辅助 listener/错误类型/图片读取辅助
- **主要逻辑**：文本/图像/PDF/notebook 读取，token/size 限制，read dedup，dynamic skills activation
- **被谁使用**：tools.ts、toolExecution.ts
- **依赖了谁**：pdf/image/file/path/permissions/skills/analytics utils
- **是否值得重点精读**：极高

### 14.8 `source/src/tools/FileEditTool/FileEditTool.ts`
- **文件作用**：精确文本编辑工具
- **导出的内容**：`FileEditTool`
- **主要逻辑**：先读后改、old/new 精确匹配、文件未变更保护、patch 生成、LSP/VSCode 通知、git diff/analytics
- **被谁使用**：tools.ts、toolExecution.ts
- **依赖了谁**：file/path/permissions/settings validate/diff/LSP/history/skills utils
- **是否值得重点精读**：极高

---

## 15. 本轮已完成分析的文件列表（相对路径）

- `source/src/tools.ts`
- `source/src/Tool.ts`
- `source/src/services/tools/StreamingToolExecutor.ts`
- `source/src/services/tools/toolExecution.ts`
- `source/src/constants/tools.ts`
- `source/src/tools/BashTool/BashTool.tsx`
- `source/src/tools/FileReadTool/FileReadTool.ts`
- `source/src/tools/FileEditTool/FileEditTool.ts`
- 以及 `source/src/tools/**`、`source/src/services/tools/**` 目录清单扫描

---

## 16. 本轮未完成但下一轮建议继续分析的模块

1. Agent 主循环模块（`query.ts`）
2. 上下文管理 / compact 模块
3. 模型/API 调用模块
4. `source/src/tools/**` 其他工具族的分组精讲（MCP/Agent/Task/Web/LSP/Worktree）
5. 文件总索引表第二批（tools/query/services）

---

## 17. 当前累计已覆盖文件数 / 总文件数

- 已完成深读与模块级分析：**31 / 1954**
- 已完成路径扫描：**1954 / 1954**

---

## 18. 当前代码库学习进度

- **整体学习进度：35%**
- **工具系统理解进度：70%**
- **内容级深读进度：约 31 / 1954**

下一步建议：直接进入 **Agent 主循环模块**，也就是 `source/src/query.ts` + `services/compact/**` + `services/api/**` + `services/tools/**` 的联动主链。
