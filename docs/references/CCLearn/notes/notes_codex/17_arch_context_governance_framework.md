# Claude Code 子功能架构图 05：上下文治理与恢复层

- 仓库路径：`cc/claude_code`
- 对应总图文档：`cc/cc_learn/12_overall_architecture_framework.md`
- 对应主循环文档：`cc/cc_learn/16_arch_query_loop_framework.md`
- 当前主题：**上下文治理与恢复层（AutoCompact / Microcompact / Full Compact / Stop Hooks / Token Budget / Retry-Recovery 协同）**
- 当前目标：
  1. 画出上下文治理与恢复层的完整子架构图
  2. 给出该功能块涉及文件的相对路径索引
  3. 对这个功能块**所有涉及文件**总结作用

---

## 1. 这个功能块到底在解决什么问题

Claude Code 不是一次性短对话，而是长会话、带工具、带附件、带恢复逻辑的 agent runtime。

随着会话变长，系统会持续面对这些问题：

- 上下文越来越大，快超窗口了怎么办？
- 哪些旧工具结果该保留，哪些该清？
- 如果 prompt 已经过长，是先 compact、先 collapse、还是直接报错？
- 模型被 `max_output_tokens` 截断时，应该怎么优雅继续？
- 一轮结束后，真的该停了吗？还是还应该再往前推一轮？
- stop hooks 要不要阻止继续？
- 网络/API 出错时，哪些错误可以恢复，哪些应该直接抛给用户？

所以这个功能块本质上是：

> **Agent Runtime 的稳定器、减压阀、恢复器和继续/停止决策器。**

---

## 2. 上下文治理与恢复层总架构图（静态结构图）

```text
上下文治理与恢复层
├── A. 主入口接入层
│   └── source/src/query.ts
│       - 每轮 query 前接入 compact / microcompact / warning / retry
│       - 每轮结束时接入 stopHooks / tokenBudget
│
├── B. 自动 compact 决策层
│   └── source/src/services/compact/autoCompact.ts
│       - threshold / blocking / circuit breaker
│       - sessionMemoryCompact first
│       - fallback full compact
│
├── C. 轻量 compact 层
│   ├── source/src/services/compact/microCompact.ts
│   ├── source/src/services/compact/apiMicrocompact.ts
│   └── source/src/services/compact/timeBasedMCConfig.ts
│       - cached microcompact
│       - time-based microcompact
│       - cache_edits / tool_result clearing
│
├── D. Full compact 层
│   ├── source/src/services/compact/compact.ts
│   ├── source/src/services/compact/prompt.ts
│   ├── source/src/services/compact/grouping.ts
│   ├── source/src/services/compact/postCompactCleanup.ts
│   └── source/src/services/compact/sessionMemoryCompact.ts
│       - full/partial compact
│       - summary generation
│       - post-compact attachments restore
│
├── E. 警告与状态层
│   ├── source/src/services/compact/compactWarningState.ts
│   └── source/src/services/compact/compactWarningHook.ts
│
├── F. Turn 结束治理层
│   ├── source/src/query/tokenBudget.ts
│   └── source/src/query/stopHooks.ts
│
└── G. API 恢复协同层
    ├── source/src/services/api/withRetry.ts
    ├── source/src/services/api/errors.ts
    ├── source/src/services/api/errorUtils.ts
    └── source/src/services/api/promptCacheBreakDetection.ts
```

---

## 3. 上下文治理与恢复层动态流程图（运行图）

```text
query.ts 每轮开始
      │
      ▼
[1] 计算当前上下文风险
    - token estimate
    - warning / error / blocking state
      │
      ▼
[2] 轻量治理优先
    - applyToolResultBudget
    - snipCompactIfNeeded
    - microcompactMessages
      │
      ▼
[3] 中等治理
    - context collapse（若启用）
      │
      ▼
[4] 自动 compact
    - shouldAutoCompact()
    - autoCompactIfNeeded()
    - sessionMemoryCompact first
    - fallback compactConversation()
      │
      ▼
[5] 发模型请求
    - services/api/claude.ts
      │
      ├── 如果 prompt-too-long / media / 429 / 529 / timeout / overflow
      │      -> withRetry.ts / errors.ts / query.ts recovery
      │
      ▼
[6] 本轮运行结束时
    - stopHooks.ts
    - tokenBudget.ts
      │
      ├── preventContinuation / blockingErrors
      ├── continue with nudge
      └── natural completion
```

---

## 4. 相对路径索引（总表）

---

### 4.1 compact 核心文件

| 相对路径 | 作用 |
|---|---|
| `source/src/services/compact/autoCompact.ts` | 自动 compact 阈值判断与执行调度 |
| `source/src/services/compact/microCompact.ts` | 轻量级上下文清理（cached/time-based microcompact） |
| `source/src/services/compact/compact.ts` | full/partial compact 核心 |
| `source/src/services/compact/sessionMemoryCompact.ts` | session memory compact 分支 |

---

### 4.2 compact 辅助与状态文件

| 相对路径 | 作用 |
|---|---|
| `source/src/services/compact/apiMicrocompact.ts` | API/cache-edit 方向的 microcompact 支持 |
| `source/src/services/compact/compactWarningHook.ts` | compact warning 的 hook 协调层 |
| `source/src/services/compact/compactWarningState.ts` | compact warning 状态管理 |
| `source/src/services/compact/grouping.ts` | compact 相关分组辅助 |
| `source/src/services/compact/postCompactCleanup.ts` | compact 后清理逻辑 |
| `source/src/services/compact/prompt.ts` | compact prompt 生成 |
| `source/src/services/compact/timeBasedMCConfig.ts` | time-based microcompact 配置 |

---

### 4.3 turn 结束治理文件

| 相对路径 | 作用 |
|---|---|
| `source/src/query/tokenBudget.ts` | token budget 继续/停止决策 |
| `source/src/query/stopHooks.ts` | stop hooks 与收尾策略执行 |

---

### 4.4 API 恢复协同文件

| 相对路径 | 作用 |
|---|---|
| `source/src/services/api/withRetry.ts` | API 重试与恢复状态机 |
| `source/src/services/api/errors.ts` | 错误分类与用户消息映射 |
| `source/src/services/api/errorUtils.ts` | API 错误辅助解析 |
| `source/src/services/api/promptCacheBreakDetection.ts` | prompt cache break 检测 |

---

## 5. 上下文治理与恢复层的主线总结

可以把这一层的主线概括成：

```text
autoCompact.ts + microCompact.ts + compact.ts + stopHooks.ts + tokenBudget.ts + withRetry.ts
```

更准确地说，它的运行顺序通常是：

```text
query.ts
  -> compactWarningState / token thresholds
  -> microCompact.ts
  -> autoCompact.ts
      -> sessionMemoryCompact.ts
      -> compact.ts
          -> prompt.ts / grouping.ts / postCompactCleanup.ts
  -> 发模型请求
      -> withRetry.ts / errors.ts / errorUtils.ts / promptCacheBreakDetection.ts
  -> turn 结束
      -> stopHooks.ts
      -> tokenBudget.ts
```

---

## 6. 核心文件详细职责说明

---

### 6.1 `source/src/services/compact/autoCompact.ts`

**作用：** 自动 compact 决策与执行调度中心。

它负责：
- 计算有效上下文窗口与 compact 触发阈值
- 判断 warning / error / blocking / auto-compact threshold 状态
- 决定当前 querySource 是否允许 auto compact
- 维护 autocompact failure circuit breaker
- 先尝试 `sessionMemoryCompact`
- 再 fallback 到 full `compactConversation()`

**它解决的问题：**
系统不能等 prompt 真爆了才处理，必须在合适阈值前主动减压。

**一句话总结：**
> 上下文膨胀的第一道主动防线。

---

### 6.2 `source/src/services/compact/microCompact.ts`

**作用：** 轻量级上下文清理层。

它负责：
- cached microcompact（通过 cache edits 删除旧 tool results）
- time-based microcompact（在 server cache 已冷却时直接清理旧 tool_result 内容）
- 估算哪些工具结果适合 compact
- 保持尽量不破坏 prompt 语义与 cache prefix

**它解决的问题：**
不是所有会话都值得立即 full compact；很多时候只要先清掉旧工具输出就够了。

**一句话总结：**
> full compact 之前的轻量减压器。

---

### 6.3 `source/src/services/compact/compact.ts`

**作用：** full/partial compact 核心。

它负责：
- 整体会话摘要压缩
- partial compact
- compact prompt 构造
- post-compact boundary 与 summary 生成
- post-compact attachments / files / plan / skills / async agents 恢复
- compact 失败时的 PTL retry 路径

**它解决的问题：**
当轻量治理不够时，系统必须把大量旧上下文压成一份仍能继续工作的 summary + restored attachments 结构。

**一句话总结：**
> 上下文治理的重武器。

---

### 6.4 `source/src/services/compact/sessionMemoryCompact.ts`

**作用：** session memory compact 支路。

它负责：
- 尝试用更偏 memory-aware 的方式压缩当前会话
- 在成功时减少对 full compact 的依赖

**一句话总结：**
> full compact 之前更轻的替代压缩分支。

---

### 6.5 `source/src/query/tokenBudget.ts`

**作用：** continuation 预算决策器。

它负责：
- 跟踪 continuation 次数
- 跟踪最近几轮 token 增量
- 判断当前是否已经进入 diminishing returns
- 给 query loop 返回继续/停止决策

**一句话总结：**
> 控制“还要不要再往前推一轮”的预算器。

---

### 6.6 `source/src/query/stopHooks.ts`

**作用：** turn 收尾策略执行器。

它负责：
- 执行 stop hooks
- 产生 blockingErrors / preventContinuation
- 执行 teammate idle / task completed hooks
- 触发 prompt suggestion / extract memories / auto dream 等后台流程

**一句话总结：**
> 主循环结束时的治理与策略收尾器。

---

### 6.7 `source/src/services/api/withRetry.ts`

**作用：** API 恢复状态机。

它负责：
- 429 / 529 / timeout / auth / stale connection / context overflow 等错误的重试与恢复
- fast mode cooldown
- persistent unattended retry
- model fallback 触发信号
- max_tokens overflow recovery

**一句话总结：**
> 网络/API 错误侧的恢复引擎。

---

### 6.8 `source/src/services/api/errors.ts`

**作用：** 错误分类与用户消息映射中心。

它负责：
- 把底层错误变成 assistant/system 可见消息
- 保留 `errorDetails` 给恢复层解析
- 给 telemetry 统一错误类型

**一句话总结：**
> 恢复逻辑和用户可见错误之间的翻译器。

---

### 6.9 `source/src/services/api/errorUtils.ts`

**作用：** API 错误辅助解析层。

它负责：
- 提供错误模式识别、分类辅助与通用判断逻辑
- 给 `errors.ts` / `withRetry.ts` / API 层其他模块复用

**一句话总结：**
> API 错误处理的共用工具箱。

---

### 6.10 `source/src/services/api/promptCacheBreakDetection.ts`

**作用：** prompt cache break 检测层。

它负责：
- 判断 cache prefix 是否被打断
- 为 microcompact / API params/cache strategy 提供决策支持

**一句话总结：**
> 缓存友好型上下文治理的感知器。

---

## 7. 所有涉及文件逐项职责总结

下面把这个功能块当前涉及的文件逐个总结作用。

---

## 7.1 `services/compact/**` 全部文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/compact/apiMicrocompact.ts` | 在 API/cache-edit 语义下支持 microcompact，帮助保留缓存前缀 |
| `source/src/services/compact/autoCompact.ts` | 自动 compact 的阈值判断、warning 状态、熔断与执行调度核心 |
| `source/src/services/compact/compact.ts` | full/partial compact 主实现，负责摘要、恢复 attachments、构造 compact 边界 |
| `source/src/services/compact/compactWarningHook.ts` | 当会话接近 compact 阈值时与 hook 体系对接，产生 warning 行为 |
| `source/src/services/compact/compactWarningState.ts` | 记录 compact warning 是否已抑制/已触发等状态 |
| `source/src/services/compact/grouping.ts` | 对消息/API round/compact 输入做分组，服务于 compact 与 PTL retry |
| `source/src/services/compact/microCompact.ts` | 实现 cached microcompact 与 time-based microcompact |
| `source/src/services/compact/postCompactCleanup.ts` | compact 后清理状态、重置 warning 或缓存/标记等收尾逻辑 |
| `source/src/services/compact/prompt.ts` | 生成 compact agent 使用的 prompt / summary request 内容 |
| `source/src/services/compact/sessionMemoryCompact.ts` | 通过 session memory 路径做较轻量 compact 的尝试 |
| `source/src/services/compact/timeBasedMCConfig.ts` | time-based microcompact 的阈值与配置来源 |

---

## 7.2 `query/**` 中与治理层直接相关的文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/query/tokenBudget.ts` | 决定在未自然完成时是否继续推进一轮 query |
| `source/src/query/stopHooks.ts` | turn 结束时的 stop hooks、teammate hooks 与相关后台收尾动作 |

---

## 7.3 `services/api/**` 中与恢复层直接相关的文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/api/withRetry.ts` | API 错误恢复、重试、fallback、fast mode cooldown、persistent retry |
| `source/src/services/api/errors.ts` | 将底层错误映射成用户可理解且恢复层可识别的错误消息 |
| `source/src/services/api/errorUtils.ts` | API 错误识别和辅助逻辑 |
| `source/src/services/api/promptCacheBreakDetection.ts` | prompt cache break 检测，为 cache-aware compact / request 组织服务 |

---

## 8. 这个功能块内部的关键关系图

```text
autoCompact.ts
  -> 依赖 token estimation / warning state
  -> 先尝试 sessionMemoryCompact.ts
  -> fallback compact.ts

microCompact.ts
  -> 依赖 timeBasedMCConfig.ts
  -> 依赖 promptCacheBreakDetection.ts
  -> 可能产出 cache_edits / cleared tool results

compact.ts
  -> 依赖 prompt.ts
  -> 依赖 grouping.ts
  -> 完成后调用 postCompactCleanup.ts

query.ts 结束时
  -> stopHooks.ts
  -> tokenBudget.ts

模型调用失败时
  -> withRetry.ts
  -> errors.ts / errorUtils.ts
  -> 若可恢复，重新回到 query.ts 下一轮
```

---

## 9. 这个功能块最重要的设计结论

### 结论 1：Claude Code 的上下文治理是分层的，不是只有 compact

至少有这几层：
- warning / threshold
- microcompact
- context collapse（在主循环中）
- autocompact
- full compact
- reactive compact / retry-driven recovery

所以它不是单一策略，而是一个分层减压体系。

---

### 结论 2：microcompact 和 full compact 是两种完全不同的思路

- `microCompact.ts`：尽量不改主语义，只清理旧工具结果，优先保 cache
- `compact.ts`：直接做摘要重组，牺牲原始上下文细节换可持续运行

这是这个系统里非常关键的设计分层。

---

### 结论 3：tokenBudget 和 stopHooks 也是“恢复层”的一部分

它们虽然不属于 compact 文件夹，但本质上都是：
- 控制主循环别停太早
- 或者别继续太久
- 对结束条件做治理

所以它们属于同一个功能块，而不只是 query 的边角文件。

---

### 结论 4：API retry 不是外围逻辑，而是恢复层的另一半

如果没有 `withRetry.ts` 与 `errors.ts`：
- compact/recovery 很多路径根本没法协同
- `max_output_tokens`、429/529、timeout、auth refresh 都没法优雅恢复

所以“上下文治理”与“API 恢复”实际上是同一稳定性体系的两边。

---

### 结论 5：这层的核心价值不是“省 token”，而是“让 agent 持续可运行”

省 token 只是副作用。
更本质的目标是：

> **即使长会话、长任务、复杂工具调用、复杂错误场景出现，系统仍然尽量别死。**

---

## 10. 当前文档的覆盖边界说明

这份文档已经尽量按你的要求做到：

- 有 **上下文治理与恢复层完整子架构图**
- 有 **动态流程图**
- 有 **相对路径索引**
- 有 **核心骨架文件详细说明**
- 有这个功能块所有涉及文件的**逐文件作用总结**

说明一下层次：

### 第一层：核心文件 = 详细说明
- `autoCompact.ts`
- `microCompact.ts`
- `compact.ts`
- `sessionMemoryCompact.ts`
- `tokenBudget.ts`
- `stopHooks.ts`
- `withRetry.ts`
- `errors.ts`
- `errorUtils.ts`
- `promptCacheBreakDetection.ts`

### 第二层：其余相关文件 = 逐文件职责摘要
- `services/compact/**` 剩余文件
- 相关 `query/**` / `services/api/**` 恢复文件

如果你后面还要更细，我也可以再把它拆成两份：

1. **compact 系统深拆版**
2. **retry / stopHooks / tokenBudget 深拆版**

---

## 11. 当前子功能块输出结果

本轮已完成：
- **上下文治理与恢复层完整子架构图**
- **动态流程图**
- **相对路径总索引**
- **核心文件详细说明**
- **该功能块所有涉及文件的逐文件作用总结**

已保存到：
- `cc/cc_learn/17_arch_context_governance_framework.md`

---

## 12. 下一步建议

按当前顺序，下一块最自然应该做：

### Memory / Attachment / Session 恢复层
建议文件名：
- `cc/cc_learn/18_arch_memory_attachment_resume_framework.md`

因为它和主循环、compact、恢复逻辑强耦合，并且也是 Claude Code 长会话能力的另一块关键底座。

如果你继续要我做，我下一份就直接写这一块。