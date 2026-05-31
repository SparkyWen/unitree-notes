# Claude Code 子功能架构图 04：Agent 主循环模块

- 仓库路径：`cc/claude_code`
- 对应总图文档：`cc/cc_learn/12_overall_architecture_framework.md`
- 当前主题：**Agent 主循环模块（Query Loop / Model Streaming / Tool Orchestration / Recovery / Continuation）**
- 当前目标：
  1. 画出 Agent 主循环模块的完整子架构图
  2. 给出该功能块涉及文件的相对路径索引
  3. 对这个功能块**所有涉及文件**总结作用

---

## 1. 为什么这个模块非常关键

你特别强调了这一点，这个判断是对的。

在 Claude Code 里，真正让它从“一个会调工具的聊天壳”变成“一个能持续执行任务的 Agent Runtime”的核心，就是这个模块。

它负责：

- 接收当前会话消息、system prompt、contexts、tools、commands
- 决定如何调用模型
- 流式接收 assistant 输出
- 发现 tool_use 并执行工具
- 把 tool_result、attachments、memory、delta messages 再回灌进下一轮
- 处理上下文过长、输出截断、media 错误、流失败等恢复逻辑
- 决定到底要不要继续下一轮，还是本轮结束

一句话：

> **`query.ts` 及其周边文件，是 Claude Code 的“Agent 状态机内核”。**

---

## 2. Agent 主循环模块总架构图（静态结构图）

```text
Agent 主循环模块
├── A. 主循环入口层
│   └── source/src/query.ts
│       - query()
│       - queryLoop()
│       - turn state
│       - continuation/recovery
│
├── B. Query 配置与依赖注入层
│   ├── source/src/query/config.ts
│   ├── source/src/query/deps.ts
│   ├── source/src/query/tokenBudget.ts
│   └── source/src/query/stopHooks.ts
│
├── C. 模型请求与流式运行时层
│   └── source/src/services/api/**
│       - claude.ts
│       - withRetry.ts
│       - errors.ts
│       - logging.ts
│       - usage.ts
│       - prompt cache / dump / bootstrap / ingress 等
│
├── D. 上下文治理与 compact 层
│   └── source/src/services/compact/**
│       - autoCompact.ts
│       - compact.ts
│       - microCompact.ts
│       - sessionMemoryCompact.ts
│       - warning / grouping / cleanup / prompt
│
├── E. 工具编排执行层
│   └── source/src/services/tools/**
│       - StreamingToolExecutor.ts
│       - toolExecution.ts
│       - toolHooks.ts
│       - toolOrchestration.ts
│
└── F. 结果回流层
    - tool_result messages
    - attachments
    - memory prefetch
    - queued commands
    - stop hooks / token budget decisions
```

---

## 3. Agent 主循环动态流程图（最核心的一张图）

```text
用户消息 / 命令结果 / 先前工具结果
        │
        ▼
[source/src/query.ts] query()
  - 初始化 State
  - buildQueryConfig()
  - deps = productionDeps()
  - 启动 relevant memory prefetch
        │
        ▼
queryLoop(state)
  - getMessagesAfterCompactBoundary()
  - applyToolResultBudget()
  - snipCompactIfNeeded()
  - microcompactMessages()
  - context collapse / autocompact
        │
        ▼
[services/api/claude.ts]
  - 构建 API params
  - 构建 tool schemas
  - normalize messages
  - 发 streaming 请求
        │
        ▼
流式收到 assistant blocks
        │
        ├── 普通文本 / thinking / metadata
        │      -> 收集 assistantMessages
        │
        └── tool_use
               -> StreamingToolExecutor.addTool()
               -> toolExecution.ts / toolOrchestration.ts
               -> 真正执行工具
               -> 产生 progress / tool_result / attachments
        │
        ▼
query.ts 聚合本轮输出
  - 合并 assistantMessages + toolResults
  - 注入 attachments / memory / queued commands / skill discovery
  - 运行 stopHooks / tokenBudget
        │
        ├── 若还需要继续
        │      -> 构造下一轮 State
        │      -> continue queryLoop
        │
        └── 若结束
               -> return terminal reason
```

---

## 4. 主循环的分层解释

---

### 第 1 层：主循环状态机层

**代表文件：**
- `source/src/query.ts`

**职责：**
- 一轮一轮推进 agent turn
- 管理 messages / turnCount / transition / recovery 状态
- 协调模型调用、工具执行、附件注入、继续/停止决策

---

### 第 2 层：Query 配置与决策辅助层

**代表文件：**
- `source/src/query/config.ts`
- `source/src/query/deps.ts`
- `source/src/query/tokenBudget.ts`
- `source/src/query/stopHooks.ts`

**职责：**
- 把 query 入口时的 flags/gates 冻结成配置快照
- 抽象外部依赖，便于测试与减耦
- 决定是否继续下一轮
- 在 turn 结束时执行 stop hooks

---

### 第 3 层：模型/API 运行时层

**代表文件：**
- `source/src/services/api/claude.ts`
- `source/src/services/api/withRetry.ts`
- `source/src/services/api/errors.ts`
- `source/src/services/api/logging.ts`
- `source/src/services/api/usage.ts`

**职责：**
- 把内部消息模型转换成模型 API 请求
- 流式消费结果
- retry / fallback / timeout / auth refresh / error mapping
- usage/cost 统计与日志记录

---

### 第 4 层：上下文治理与恢复层

**代表文件：**
- `source/src/services/compact/**`

**职责：**
- 控制上下文膨胀
- 自动/反应式 compact
- microcompact
- compact 后恢复 attachments / files / plans / skills
- 提供 warning / cleanup / prompt 生成能力

---

### 第 5 层：工具执行编排层

**代表文件：**
- `source/src/services/tools/**`

**职责：**
- 在主循环收到 tool_use 后把它变成真实执行
- 管理并发安全、progress、hook、tool_result 与错误传播

---

## 5. 相对路径索引（总表）

---

### 5.1 主循环与 query 辅助文件

| 相对路径 | 作用 |
|---|---|
| `source/src/query.ts` | Agent 主循环与 turn 状态机核心 |
| `source/src/query/config.ts` | query 入口配置快照 |
| `source/src/query/deps.ts` | query 外部依赖注入层 |
| `source/src/query/tokenBudget.ts` | token budget continuation 决策 |
| `source/src/query/stopHooks.ts` | turn 结束时的 hooks 编排层 |

---

### 5.2 services/api/** 文件（该模块相关）

| 相对路径 | 作用 |
|---|---|
| `source/src/services/api/adminRequests.ts` | 管理类 API 请求辅助 |
| `source/src/services/api/bootstrap.ts` | API 运行时 bootstrap 辅助 |
| `source/src/services/api/claude.ts` | 模型请求编译器 + 流式运行时核心 |
| `source/src/services/api/client.ts` | provider/client 构造层 |
| `source/src/services/api/dumpPrompts.ts` | dump prompts 能力 |
| `source/src/services/api/emptyUsage.ts` | 空 usage/默认 usage 辅助 |
| `source/src/services/api/errorUtils.ts` | API 错误辅助函数 |
| `source/src/services/api/errors.ts` | 错误映射与分类中心 |
| `source/src/services/api/filesApi.ts` | 文件相关 API 辅助 |
| `source/src/services/api/firstTokenDate.ts` | 首 token 时间相关记录/辅助 |
| `source/src/services/api/grove.ts` | Grove 相关 API/能力支持 |
| `source/src/services/api/logging.ts` | API 请求成功/失败日志与 tracing |
| `source/src/services/api/metricsOptOut.ts` | metrics opt-out API/状态辅助 |
| `source/src/services/api/overageCreditGrant.ts` | overage/额度授予相关 API 辅助 |
| `source/src/services/api/promptCacheBreakDetection.ts` | prompt cache break 检测 |
| `source/src/services/api/referral.ts` | referral 相关 API 支持 |
| `source/src/services/api/sessionIngress.ts` | session ingress / remote persistence API |
| `source/src/services/api/ultrareviewQuota.ts` | ultrareview quota 相关 API |
| `source/src/services/api/usage.ts` | usage/cost 聚合统计 |
| `source/src/services/api/withRetry.ts` | API 重试状态机 |

---

### 5.3 services/compact/** 文件（该模块相关）

| 相对路径 | 作用 |
|---|---|
| `source/src/services/compact/apiMicrocompact.ts` | API/cache-edit 方向的 microcompact 支持 |
| `source/src/services/compact/autoCompact.ts` | autocompact 决策与执行调度 |
| `source/src/services/compact/compact.ts` | full/partial compact 核心 |
| `source/src/services/compact/compactWarningHook.ts` | compact warning hook 相关逻辑 |
| `source/src/services/compact/compactWarningState.ts` | compact warning 状态管理 |
| `source/src/services/compact/grouping.ts` | compact / transcript grouping 辅助 |
| `source/src/services/compact/microCompact.ts` | 轻量级工具结果清理层 |
| `source/src/services/compact/postCompactCleanup.ts` | compact 后清理逻辑 |
| `source/src/services/compact/prompt.ts` | compact prompt 生成 |
| `source/src/services/compact/sessionMemoryCompact.ts` | session memory compact 支路 |
| `source/src/services/compact/timeBasedMCConfig.ts` | time-based microcompact 配置 |

---

### 5.4 services/tools/** 文件（该模块相关）

| 相对路径 | 作用 |
|---|---|
| `source/src/services/tools/StreamingToolExecutor.ts` | 流式工具执行器 |
| `source/src/services/tools/toolExecution.ts` | 单次 tool_use 总执行管线 |
| `source/src/services/tools/toolHooks.ts` | 工具 hooks 编排桥接 |
| `source/src/services/tools/toolOrchestration.ts` | 非流式工具批处理编排 |

---

## 6. 主循环模块的关键主线

主循环模块最关键的主线可以概括为：

```text
query.ts -> services/api/claude.ts -> services/tools/** -> compact/** -> 回到 query.ts
```

更展开一点：

```text
source/src/query.ts
  -> buildQueryConfig()
  -> deps.callModel() = services/api/claude.ts
  -> deps.microcompact() = services/compact/microCompact.ts
  -> deps.autocompact() = services/compact/autoCompact.ts
  -> tool_use -> services/tools/StreamingToolExecutor.ts
      -> toolExecution.ts
      -> toolHooks.ts
  -> stopHooks.ts / tokenBudget.ts
  -> 若继续则进入下一轮 state
```

---

## 7. 主循环核心文件逐项职责说明

---

### 7.1 `source/src/query.ts`

**作用：** Agent 主循环与 turn 状态机核心。

它负责：
- 暴露 `query()` 作为外部入口
- 在内部维护 `queryLoop()`
- 管理当前 turn 的 `State`
- 在每轮调用前做 compact/snipping/tool result budget/context preparation
- 调模型请求
- 收流式 assistant messages 与 tool_use
- 驱动工具执行
- 注入 memory / attachment / queued commands
- 决定是否继续下一轮

**一句话总结：**
> Claude Code 的主执行内核。

---

### 7.2 `source/src/query/config.ts`

**作用：** Query 入口配置快照层。

它负责：
- 把 query 入口时的 env / growthbook / session state 冻结成 `QueryConfig`
- 避免在 query loop 里反复读取散落的全局状态

**一句话总结：**
> 给 query loop 提供稳定的只读配置快照。

---

### 7.3 `source/src/query/deps.ts`

**作用：** Query 外部依赖注入层。

它负责：
- 把 `callModel`、`microcompact`、`autocompact`、`uuid` 等外部依赖封装成 `QueryDeps`
- 让 query loop 更容易测试与替换依赖

**一句话总结：**
> Query 状态机与外部 I/O 之间的适配层。

---

### 7.4 `source/src/query/tokenBudget.ts`

**作用：** token budget continuation 决策器。

它负责：
- 记录 continuation 次数与 token 增量
- 判断当前是否还应该再继续一轮
- 避免在 diminishing returns 状态下无意义循环

**一句话总结：**
> 控制“该不该再推进一轮”的轻量预算器。

---

### 7.5 `source/src/query/stopHooks.ts`

**作用：** turn 结束阶段的 hook 编排层。

它负责：
- 执行 stop hooks
- 收集 blockingErrors / preventContinuation
- 执行 teammate idle / task completed hooks
- 触发 prompt suggestion / extract memories / auto dream 等收尾逻辑

**一句话总结：**
> 主循环收尾阶段的策略执行器。

---

## 8. services/api/** 文件职责总结（从主循环视角）

这部分文件共同作用是：

> **把 query loop 中的一次“模型调用”变成可重试、可流式、可记录、可恢复的 API 运行过程。**

---

### 8.1 核心主文件

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/api/claude.ts` | 把内部消息模型编译成 Claude API 请求，并流式解析返回结果 |
| `source/src/services/api/withRetry.ts` | 管理 API 重试、fallback、fast mode cooldown、auth refresh、context overflow recovery |
| `source/src/services/api/errors.ts` | 把底层错误映射成用户消息与可恢复错误类型 |
| `source/src/services/api/logging.ts` | 记录 API 请求、成功、失败、usage、gateway、tracing 信息 |
| `source/src/services/api/usage.ts` | 统计 usage/cost 等数据 |
| `source/src/services/api/client.ts` | 底层 provider/client 构造器，给 claude.ts 提供实际 client |

---

### 8.2 其余 API 辅助文件逐项总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/api/adminRequests.ts` | 管理/后台管理类 API 请求辅助，供特定功能调用 |
| `source/src/services/api/bootstrap.ts` | API 层启动/引导相关辅助 |
| `source/src/services/api/dumpPrompts.ts` | 把当前 prompt/request 结构导出/调试出来的能力 |
| `source/src/services/api/emptyUsage.ts` | 构造默认/空 usage 对象 |
| `source/src/services/api/errorUtils.ts` | API 错误解析与共用判断辅助 |
| `source/src/services/api/filesApi.ts` | 与文件相关的 API 操作辅助 |
| `source/src/services/api/firstTokenDate.ts` | 首 token 时间或首响应时间相关辅助记录 |
| `source/src/services/api/grove.ts` | Grove 相关 API 能力支持 |
| `source/src/services/api/metricsOptOut.ts` | 指标/遥测 opt-out 相关 API/状态处理 |
| `source/src/services/api/overageCreditGrant.ts` | overage / extra credit / 授权额度相关 API 支持 |
| `source/src/services/api/promptCacheBreakDetection.ts` | 检测 prompt cache 是否断裂、为 cache 策略服务 |
| `source/src/services/api/referral.ts` | referral 相关 API 辅助 |
| `source/src/services/api/sessionIngress.ts` | remote / ingress / session persistence 相关 API 辅助 |
| `source/src/services/api/ultrareviewQuota.ts` | ultrareview quota / 配额获取与判断 |

---

## 9. services/compact/** 文件职责总结（从主循环视角）

这一组文件共同作用是：

> **在主循环每轮开始或溢出时，治理上下文规模，并在压缩后尽可能恢复关键执行语义。**

---

### 9.1 核心 compact 文件

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/compact/autoCompact.ts` | 自动 compact 决策、阈值计算、失败熔断 |
| `source/src/services/compact/compact.ts` | full/partial compact 核心，实现摘要与 post-compact 恢复 |
| `source/src/services/compact/microCompact.ts` | 轻量级 compact，用于清理旧工具结果或走 cache_edits |
| `source/src/services/compact/sessionMemoryCompact.ts` | 尝试走 session memory compact 这条更轻量的分支 |

---

### 9.2 其余 compact 辅助文件逐项总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/compact/apiMicrocompact.ts` | 和 API/cache editing 更贴近的 microcompact 支持层 |
| `source/src/services/compact/compactWarningHook.ts` | compact warning 的 hook 接入逻辑 |
| `source/src/services/compact/compactWarningState.ts` | compact warning 状态持有与查询 |
| `source/src/services/compact/grouping.ts` | compact / transcript / API round 分组辅助 |
| `source/src/services/compact/postCompactCleanup.ts` | compact 成功后的状态清理与收尾 |
| `source/src/services/compact/prompt.ts` | compact 时用的 prompt 构造逻辑 |
| `source/src/services/compact/timeBasedMCConfig.ts` | time-based microcompact 的配置与阈值来源 |

---

## 10. services/tools/** 文件职责总结（从主循环视角）

在主循环里，这一组文件负责把 tool_use 从“模型输出”变成“真实执行结果”。

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/tools/StreamingToolExecutor.ts` | 主循环下最重要的多工具流式执行器 |
| `source/src/services/tools/toolExecution.ts` | 真正执行单次 tool_use 的总管线 |
| `source/src/services/tools/toolHooks.ts` | 工具 hooks 在主循环中的接入桥 |
| `source/src/services/tools/toolOrchestration.ts` | 不走 StreamingToolExecutor 时的批量工具执行路径 |

---

## 11. Agent 主循环模块最关键的状态流

### 11.1 一次完整 turn 的状态流

```text
messages/state
  -> query.ts::queryLoop()
  -> compact/snipping/budgeting
  -> claude.ts 发模型请求
  -> assistant stream 到达
  -> tool_use 提取
  -> StreamingToolExecutor 执行工具
  -> tool_result / attachments / memory
  -> stopHooks / tokenBudget
  -> 下一轮 state 或 terminal reason
```

---

### 11.2 recoverable error 的状态流

```text
API / streaming / media / output error
  -> query.ts 暂时 withholding error
  -> 尝试 collapse / reactive compact / max token escalate / retry
  -> 若恢复成功：继续下一轮
  -> 若失败：正式 surface error 并结束/上抛
```

---

### 11.3 工具执行在主循环中的状态流

```text
assistant tool_use block
  -> StreamingToolExecutor.addTool()
  -> toolExecution.runToolUse()
  -> validate + permission + hooks + tool.call()
  -> progress / result / contextModifier
  -> query.ts 合并到 messages
```

---

### 11.4 compact 在主循环中的状态流

```text
每轮 query 前
  -> tool result budget
  -> snip
  -> microcompact
  -> context collapse
  -> autocompact
  -> 若仍溢出：reactive compact / blocking limit
```

---

## 12. Agent 主循环模块的关键设计结论

### 结论 1：`query.ts` 不是普通函数，而是显式状态机

它维护：
- messages
- turnCount
- transition
- autoCompactTracking
- recovery counters
- pending summaries
- hook state

这就是典型状态机设计，而不是“一次请求一次响应”。

---

### 结论 2：主循环的核心是“模型流 + 工具流 + 恢复流”的三流编织

它同时要处理：
- 模型流式输出
- 工具的异步/并发执行流
- compact/retry/error 的恢复流

所以这个模块天然复杂，而且是系统最关键的地方。

---

### 结论 3：上下文治理不是外围功能，而是主循环的一部分

`compact/**` 不是一个独立小工具，而是 query 每轮都可能进入的核心控制环节。

---

### 结论 4：API 层不是简单 HTTP 包装，而是 query runtime 的下半身

`services/api/claude.ts`、`withRetry.ts`、`errors.ts`、`logging.ts` 共同构成：
- 流式调用
- fallback
- retry
- error mapping
- usage/tracing

这其实已经是主循环的“API 执行半边内核”。

---

### 结论 5：主循环结束并不意味着“模型没输出 tool_use”

真正结束前还要经过：
- stop hooks
- token budget continuation
- queued commands / attachment injection
- memory prefetch consume

所以“没有 tool_use”不等于“本轮完成”。

---

## 13. 当前文档的覆盖边界说明

这份文档已经尽量按你的要求做到：

- 有 **Agent 主循环模块完整子架构图**
- 有 **动态流程图**
- 有 **相对路径索引**
- 有 **主骨架文件详细说明**
- 有这个功能块所有涉及文件的**逐文件作用总结**

说明一下层次：

### 第一层：主骨架文件 = 详细解释
- `query.ts`
- `query/config.ts`
- `query/deps.ts`
- `query/tokenBudget.ts`
- `query/stopHooks.ts`
- `services/api/claude.ts`
- `services/api/withRetry.ts`
- `services/api/errors.ts`
- `services/api/logging.ts`
- `services/api/usage.ts`
- `services/compact/autoCompact.ts`
- `services/compact/compact.ts`
- `services/compact/microCompact.ts`
- `services/tools/StreamingToolExecutor.ts`
- `services/tools/toolExecution.ts`

### 第二层：其余涉及文件 = 逐文件职责摘要
- `services/api/**`
- `services/compact/**`
- `services/tools/**`

如果你还要更深，我下一轮也可以继续把这个模块拆成 3 份更细：

1. `query.ts` 主循环逐函数详解
2. `services/api/**` 主循环相关深拆
3. `compact/** + stopHooks/tokenBudget` 恢复链深拆

---

## 14. 当前子功能块输出结果

本轮已完成：
- **Agent 主循环模块完整子架构图**
- **Agent 主循环动态流程图**
- **相对路径总索引**
- **主骨架文件详细说明**
- **该功能块所有涉及文件的逐文件作用总结**

已保存到：
- `cc/cc_learn/16_arch_query_loop_framework.md`

---

## 15. 下一步建议

按这个顺序，下一块最自然应该做：

### 上下文治理与恢复层（单独深拆）
建议文件名：
- `cc/cc_learn/17_arch_context_governance_framework.md`

虽然它已被主循环文档覆盖，但它本身复杂度足够高，完全值得再单独做成一个独立功能块：
- autoCompact
- microCompact
- compactConversation
- warning state
- tokenBudget
- stopHooks
- retry / recovery 协同

如果你继续要我做，我下一份就直接写这一块。