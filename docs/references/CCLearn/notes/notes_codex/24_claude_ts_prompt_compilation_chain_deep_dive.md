# 代码审计级深挖 01：`services/api/claude.ts` Prompt 编译链

- 仓库路径：`cc/claude_code`
- 当前主题：**`source/src/services/api/claude.ts` 如何把内部运行时状态编译成最终模型请求**

---

## 1. 这份文档聚焦什么

这里只看一条链：

> **内部 runtime state -> API request prompt**

也就是：
- messages 如何规范化
- system prompt blocks 如何构建
- tools 如何变成 API schema
- cache breakpoints / cache edits 如何接入
- streaming request 如何和 prompt 编译结果绑定

---

## 2. 编译链总图

```text
query.ts 提供：
  - messages
  - tools
  - systemPrompt
  - contexts
  - retryContext
        │
        ▼
services/api/claude.ts
  1. 解析 model / provider / betas / fallback 语义
  2. 处理 deferred tools / tool search
  3. toolToAPISchema(...)
  4. normalizeMessagesForAPI(...)
  5. ensureToolResultPairing(...)
  6. stripExcessMediaItems(...)
  7. buildSystemPromptBlocks(...)
  8. getCacheControl(...) / cache breakpoints / cache edits
  9. paramsFromContext(retryContext)
 10. 发 streaming / non-streaming 请求
```

---

## 3. 关键步骤详细拆解

### 3.1 tools schema 编译
- 输入是内部 Tool[]
- 输出是 Claude API 可接受的 tool schemas
- 会考虑：
  - model 能力
  - defer_loading
  - agent 类型
  - permission context
  - deferred tools/tool search

### 3.2 messages 归一化
- `normalizeMessagesForAPI(...)`
- 修复 `tool_use/tool_result` 配对
- 去掉过多 media
- 剥离某些模型不支持的旧字段

### 3.3 system prompt blocks 构建
- `buildSystemPromptBlocks(...)`
- 不只是字符串，而是结构化 blocks
- 为 prompt cache 友好组织 system prompt

### 3.4 cache strategy 注入
- prompt cache 开关
- cache break detection
- cache breakpoints
- cache edits / microcompact 结果
- 全局 cache scope / TTL / prompt editing

### 3.5 retryContext 驱动再编译
- 不是只编译一次
- retry/fallback 时 `paramsFromContext(retryContext)` 会重新生成：
  - model
  - max_tokens
  - thinking
  - speed/fastMode
  - extraBodyParams
  - cache controls

---

## 4. 为什么 `claude.ts` 是 prompt 编译链的真正中心

因为在这之前：
- `query.ts` 还只是“准备数据”
- `context.ts` 还只是“准备 runtime context”
- `tools/**/prompt.ts` 还只是“定义能力说明”

只有到了 `claude.ts`：
- 所有内容才真正被组织成**一次完整模型请求**

所以它不是普通 API wrapper，而是：

> **Prompt 编译器 + 请求运行时适配器**

---

## 5. 最关键的结论

1. `claude.ts` 是 prompt 编译链真正的汇合点
2. prompt 编译结果受 model / retryContext / tools / cache strategy 共同影响
3. prompt cache 逻辑是这里的内建机制，不是外围附加功能
4. messages normalization 与 system prompt blocks 一起决定最终 prompt 形态
5. retry/fallback 本质上会触发 prompt 的再编译
