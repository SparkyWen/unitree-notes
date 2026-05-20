# Claude Code Prompt 动态拼接 / 静态拼接 / 缓存加载机制全景架构图

- 仓库路径：`cc/claude_code`
- 当前主题：**Prompt 动态拼接、静态拼接、system prompt 组装、tool prompt 注入、context 注入、prompt caching、cache break、cache edits、dump prompts、compact 与 prompt 恢复**
- 当前目标：
  1. 彻底梳理代码库中任何和 prompt 组装、动态/静态拼接、缓存加载、cache break / cache editing 相关的机制
  2. 给出完整架构图
  3. 给出相对路径索引
  4. 对这个功能块涉及文件做职责总结

> 说明：这个功能块同样横跨多个子系统。这里的“prompt”不只指 system prompt 文本，还包括：
> - system prompt blocks
> - userContext / systemContext 注入
> - CLAUDE.md / memory / attachments 注入
> - tools 的 prompt/schema 描述
> - skills / commands 的 prompt content 生成
> - compact prompt
> - stop/prompt suggestion/extract memories 等子 agent prompt
> - prompt caching / cache breaks / cache edits
>
> 为了避免文档失控，我会优先聚焦**真正参与 prompt 构造、注入、缓存、恢复的主骨架文件**。纯展示层 message 组件不会作为这个功能块主骨架，但会在需要时提到其关系。

---

## 1. 这个功能块到底负责什么

Claude Code 的 prompt 不是一段固定字符串。

它实际上是多层拼接出来的：

1. **静态 system prompt 基底**
2. **system prompt sections / blocks**
3. **systemContext 注入**（如 git snapshot 等）
4. **userContext 注入**（如 CLAUDE.md、currentDate 等）
5. **messages 序列**（含 user / assistant / tool_result / attachments）
6. **工具 schema / tool descriptions / tool prompts**
7. **skills / commands 动态生成的 prompt 内容**
8. **compact / memory / extract / suggestion 等子流程专用 prompt**
9. **prompt caching / cache breaks / cache edits / microcompact**

一句话：

> **Claude Code 的 prompt 体系，本质上是一个“按运行状态实时拼接、按缓存策略分块、按恢复机制持续重写”的 prompt 编译系统。**

---

## 2. Prompt 总架构图（总览）

```text
Claude Code Prompt 体系
├── A. 静态 Prompt 基底层
│   ├── constants/prompts.ts
│   ├── constants/systemPromptSections.ts
│   ├── utils/systemPrompt.ts
│   └── utils/systemPromptType.ts
│
├── B. 运行时 Context 注入层
│   ├── context.ts
│   ├── utils/context.ts
│   ├── utils/claudemd.ts
│   ├── SessionMemory/**
│   ├── memdir/findRelevantMemories.ts
│   └── utils/attachments.ts
│
├── C. Query Prompt 编译层
│   ├── query.ts
│   ├── services/api/claude.ts
│   ├── utils/messages.ts
│   ├── utils/messages/mappers.ts
│   └── utils/messages/systemInit.ts
│
├── D. Tool / Skill / Command Prompt 层
│   ├── tools/**/prompt.ts
│   ├── utils/promptShellExecution.ts
│   ├── skills/loadSkillsDir.ts
│   ├── skills/bundledSkills.ts
│   ├── utils/plugins/loadPluginCommands.ts
│   └── 各 prompt command / bundled prompt 文件
│
├── E. Compact / Recovery Prompt 层
│   ├── services/compact/prompt.ts
│   ├── services/compact/compact.ts
│   ├── services/compact/microCompact.ts
│   ├── services/compact/apiMicrocompact.ts
│   └── services/api/promptCacheBreakDetection.ts
│
├── F. Prompt Cache / Dump / Debug 层
│   ├── services/api/dumpPrompts.ts
│   ├── services/api/promptCacheBreakDetection.ts
│   ├── utils/cachePaths.ts
│   ├── commands/break-cache/index.js
│   └── commands/clear/caches.ts
│
└── G. Prompt 派生子系统
    ├── services/PromptSuggestion/promptSuggestion.ts
    ├── services/SessionMemory/prompts.ts
    ├── services/MagicDocs/prompts.ts
    ├── services/extractMemories/prompts.ts
    ├── buddy/prompt.ts
    ├── utils/claudeInChrome/prompt.ts
    └── tools/AgentTool/prompt.ts 等各 tool family prompt
```

---

## 3. Prompt 动态拼接主流程图（最核心）

```text
启动 / query 开始
      │
      ▼
[静态系统 Prompt 基底]
  - constants/prompts.ts
  - constants/systemPromptSections.ts
  - utils/systemPrompt.ts
      │
      ▼
[运行时 Context 注入]
  - context.ts -> systemContext / userContext
  - utils/claudemd.ts -> CLAUDE.md
  - attachments.ts -> files/plans/memory deltas
  - SessionMemory / memdir -> relevant memories
      │
      ▼
[query.ts 组织 messages]
  - compact boundary 后消息
  - attachments / queued messages / tool results
  - buildQueryConfig / token budget / compact state
      │
      ▼
[services/api/claude.ts]
  - buildSystemPromptBlocks()
  - normalizeMessagesForAPI()
  - toolToAPISchema()
  - cache strategy / cache breakpoints
  - optional cache_edits
      │
      ▼
最终 API Request Prompt
  = system blocks + normalized messages + tools + cache directives
      │
      ▼
若超长 / 缓存断裂 / compact 触发
  -> promptCacheBreakDetection.ts
  -> microCompact.ts / apiMicrocompact.ts
  -> compact.ts / compact/prompt.ts
      │
      ▼
重组后的新 prompt 再进入下一轮 query
```

---

## 4. Prompt 体系的几个核心概念

为了读懂架构，先把 6 个核心概念讲清楚。

---

### 4.1 静态拼接（Static Assembly）

指的是：
- 代码中预定义的 prompt 基底
- prompt sections 常量
- 某些固定模板
- 各 tool family 的 `prompt.ts`
- bundled skills / prompt files

它们的特点是：
- 内容在源码里就存在
- 运行时只做少量参数化

---

### 4.2 动态拼接（Dynamic Assembly）

指的是运行时根据状态拼进来的内容：
- 当前日期
- git snapshot
- CLAUDE.md
- relevant memories
- attachments
- queued commands
- compact summaries
- dynamic skills / tool discovery deltas

---

### 4.3 Prompt 编译（Prompt Compilation）

真正发给模型前，并不是简单字符串拼接，而是：
- build system prompt blocks
- normalize messages
- 组织 tool schemas
- 决定 cache breakpoints
- optional cache_edits

所以 Claude Code 更像在做 prompt 的“编译”而不是单纯拼接。

---

### 4.4 Prompt Cache（提示词缓存）

Claude Code 非常重视 prompt caching。
原因是长对话里：
- system prompt 很长
- tools 很多
- 历史很多

如果不做 cache-aware 组织，成本会迅速上升。

所以它有：
- stable tool ordering
- system prompt blocks
- cache break detection
- cache_edits based microcompact
- compact cache sharing

---

### 4.5 Cache Break / Cache Edit

- **cache break**：某个地方变动大到让后续缓存前缀失效
- **cache edit**：尽量不重写整段 prompt，而只对缓存里的某些块做删除/编辑

这是 microcompact 与 prompt cache 体系联动的关键。

---

### 4.6 Prompt 恢复（Prompt Recovery）

当 prompt 太长、compact 发生、memory 需要重新注入时，系统会：
- 生成新的 compact summary prompt
- 恢复关键附件
- 再次构造 system/user context
- 再发起下一轮 query

所以 prompt 不是“一次生成完毕”，而是会在运行过程中被多次重建。

---

## 5. 相对路径索引（总表）

下面按功能层列出 prompt 相关核心路径。

---

### 5.1 静态 system prompt 基底层

| 相对路径 | 作用 |
|---|---|
| `source/src/constants/prompts.ts` | 静态 prompt 常量与模板集合 |
| `source/src/constants/systemPromptSections.ts` | system prompt 分段常量 |
| `source/src/utils/systemPrompt.ts` | system prompt 组装/构建逻辑 |
| `source/src/utils/systemPromptType.ts` | system prompt 相关类型定义 |

---

### 5.2 运行时 context / 注入层

| 相对路径 | 作用 |
|---|---|
| `source/src/context.ts` | 生成 systemContext / userContext |
| `source/src/utils/context.ts` | context 辅助逻辑 |
| `source/src/utils/contextAnalysis.ts` | 上下文分析辅助 |
| `source/src/utils/contextSuggestions.ts` | context 提示建议 |
| `source/src/utils/claudemd.ts` | 读取/聚合 CLAUDE.md 及相关上下文文档 |
| `source/src/utils/attachments.ts` | 组装 attachments 供 prompt 注入 |
| `source/src/services/SessionMemory/sessionMemory.ts` | SessionMemory 主服务 |
| `source/src/services/SessionMemory/sessionMemoryUtils.ts` | SessionMemory 辅助逻辑 |
| `source/src/services/SessionMemory/prompts.ts` | SessionMemory 相关 prompt |
| `source/src/memdir/findRelevantMemories.ts` | relevant memories 检索 |
| `source/src/memdir/memdir.ts` | durable memory 目录服务 |
| `source/src/memdir/memoryAge.ts` | memory 时间权重辅助 |
| `source/src/memdir/memoryScan.ts` | memory 扫描 |
| `source/src/memdir/memoryTypes.ts` | memory 类型 |
| `source/src/memdir/paths.ts` | auto-memory path 规则 |
| `source/src/memdir/teamMemPaths.ts` | team memory 路径 |
| `source/src/memdir/teamMemPrompts.ts` | team memory prompt |
| `source/src/utils/mcpInstructionsDelta.ts` | MCP 指令变化增量注入 |

---

### 5.3 Query / API Prompt 编译层

| 相对路径 | 作用 |
|---|---|
| `source/src/query.ts` | 主循环中组织 prompt 的核心入口 |
| `source/src/query/tokenBudget.ts` | continuation nudge / token budget 影响 prompt 继续策略 |
| `source/src/services/api/claude.ts` | 把 prompt/messages/tools 编译成 API 请求 |
| `source/src/services/api/dumpPrompts.ts` | dump prompts 调试输出 |
| `source/src/services/api/promptCacheBreakDetection.ts` | prompt cache break 检测 |
| `source/src/utils/messages.ts` | messages 结构操作 |
| `source/src/utils/messages/mappers.ts` | messages 到 API/content block 的映射辅助 |
| `source/src/utils/messages/systemInit.ts` | 系统初始化消息辅助 |
| `source/src/constants/messages.ts` | 消息常量 |

---

### 5.4 Compact / Prompt Cache / 恢复层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/compact/apiMicrocompact.ts` | API/cache-edit 微型 compact 支持 |
| `source/src/services/compact/autoCompact.ts` | 自动 compact 决策 |
| `source/src/services/compact/compact.ts` | full/partial compact 核心 |
| `source/src/services/compact/compactWarningHook.ts` | compact warning hook |
| `source/src/services/compact/compactWarningState.ts` | compact warning 状态 |
| `source/src/services/compact/grouping.ts` | compact 输入分组 |
| `source/src/services/compact/microCompact.ts` | 微型 compact / cache edit / tool_result 清理 |
| `source/src/services/compact/postCompactCleanup.ts` | compact 后清理 |
| `source/src/services/compact/prompt.ts` | compact prompt 生成 |
| `source/src/services/compact/sessionMemoryCompact.ts` | session memory compact |
| `source/src/services/compact/timeBasedMCConfig.ts` | time-based microcompact 配置 |
| `source/src/utils/cachePaths.ts` | cache 文件/路径辅助 |
| `source/src/commands/break-cache/index.js` | break-cache 调试命令 |
| `source/src/commands/clear/caches.ts` | clear caches 命令逻辑 |

---

### 5.5 Tool / Skill / Command Prompt 层

| 相对路径 | 作用 |
|---|---|
| `source/src/tools/AgentTool/prompt.ts` | AgentTool prompt/schema |
| `source/src/tools/AskUserQuestionTool/prompt.ts` | AskUserQuestionTool prompt/schema |
| `source/src/tools/BashTool/prompt.ts` | BashTool prompt/schema |
| `source/src/tools/BriefTool/prompt.ts` | BriefTool prompt/schema |
| `source/src/tools/ConfigTool/prompt.ts` | ConfigTool prompt/schema |
| `source/src/tools/EnterPlanModeTool/prompt.ts` | EnterPlanModeTool prompt/schema |
| `source/src/tools/EnterWorktreeTool/prompt.ts` | EnterWorktreeTool prompt/schema |
| `source/src/tools/ExitPlanModeTool/prompt.ts` | ExitPlanModeTool prompt/schema |
| `source/src/tools/ExitWorktreeTool/prompt.ts` | ExitWorktreeTool prompt/schema |
| `source/src/tools/FileEditTool/prompt.ts` | FileEditTool prompt/schema |
| `source/src/tools/FileReadTool/prompt.ts` | FileReadTool prompt/schema |
| `source/src/tools/FileWriteTool/prompt.ts` | FileWriteTool prompt/schema |
| `source/src/tools/GlobTool/prompt.ts` | GlobTool prompt/schema |
| `source/src/tools/GrepTool/prompt.ts` | GrepTool prompt/schema |
| `source/src/tools/LSPTool/prompt.ts` | LSPTool prompt/schema |
| `source/src/tools/ListMcpResourcesTool/prompt.ts` | ListMcpResourcesTool prompt/schema |
| `source/src/tools/MCPTool/prompt.ts` | MCPTool prompt/schema |
| `source/src/tools/NotebookEditTool/prompt.ts` | NotebookEditTool prompt/schema |
| `source/src/tools/PowerShellTool/prompt.ts` | PowerShellTool prompt/schema |
| `source/src/tools/ReadMcpResourceTool/prompt.ts` | ReadMcpResourceTool prompt/schema |
| `source/src/tools/RemoteTriggerTool/prompt.ts` | RemoteTriggerTool prompt/schema |
| `source/src/tools/ScheduleCronTool/prompt.ts` | Cron 工具家族 prompt/schema |
| `source/src/tools/SendMessageTool/prompt.ts` | SendMessageTool prompt/schema |
| `source/src/tools/SkillTool/prompt.ts` | SkillTool prompt/schema |
| `source/src/tools/SleepTool/prompt.ts` | SleepTool prompt/schema |
| `source/src/tools/TaskCreateTool/prompt.ts` | TaskCreateTool prompt/schema |
| `source/src/tools/TaskGetTool/prompt.ts` | TaskGetTool prompt/schema |
| `source/src/tools/TaskListTool/prompt.ts` | TaskListTool prompt/schema |
| `source/src/tools/TaskStopTool/prompt.ts` | TaskStopTool prompt/schema |
| `source/src/tools/TaskUpdateTool/prompt.ts` | TaskUpdateTool prompt/schema |
| `source/src/tools/TeamCreateTool/prompt.ts` | TeamCreateTool prompt/schema |
| `source/src/tools/TeamDeleteTool/prompt.ts` | TeamDeleteTool prompt/schema |
| `source/src/tools/TodoWriteTool/prompt.ts` | TodoWriteTool prompt/schema |
| `source/src/tools/ToolSearchTool/prompt.ts` | ToolSearchTool prompt/schema |
| `source/src/tools/WebFetchTool/prompt.ts` | WebFetchTool prompt/schema |
| `source/src/tools/WebSearchTool/prompt.ts` | WebSearchTool prompt/schema |
| `source/src/utils/promptShellExecution.ts` | 在 prompt/skill 中执行 shell 插值 |
| `source/src/utils/promptCategory.ts` | prompt 分类辅助 |
| `source/src/utils/promptEditor.ts` | prompt 编辑辅助 |
| `source/src/utils/toolSearch.ts` | tool search 与 deferred tool prompt/selection 相关逻辑 |
| `source/src/skills/loadSkillsDir.ts` | markdown skills -> PromptCommand |
| `source/src/skills/bundledSkills.ts` | bundled skills -> PromptCommand |
| `source/src/utils/plugins/loadPluginCommands.ts` | plugin markdown / inline prompt -> Command |

---

### 5.6 Prompt 派生子系统

| 相对路径 | 作用 |
|---|---|
| `source/src/services/PromptSuggestion/promptSuggestion.ts` | prompt suggestion 相关逻辑 |
| `source/src/services/MagicDocs/prompts.ts` | MagicDocs 相关 prompt |
| `source/src/services/extractMemories/prompts.ts` | extract memories 子流程 prompt |
| `source/src/buddy/prompt.ts` | buddy/子角色相关 prompt |
| `source/src/utils/claudeInChrome/prompt.ts` | Claude in Chrome 场景 prompt |
| `source/src/tools/BriefTool/attachments.ts` | brief 模式下与 prompt/attachment 相关的补充 |
| `source/src/commands/brief.ts` | brief 模式控制命令 |
| `source/src/commands/context/context.tsx` | 查看/分析当前上下文命令 |
| `source/src/commands/context/context-noninteractive.ts` | 非交互上下文查看 |
| `source/src/commands/compact/**` | compact 触发命令入口 |

---

## 6. Prompt 主骨架文件详细说明

下面先把真正构成 prompt 拼接与缓存主骨架的文件讲清楚。

---

### 6.1 `source/src/utils/systemPrompt.ts`

**定位：** system prompt 组装核心。

**负责：**
- 将静态 system prompt 基底、sections、context 信息组织成最终 system prompt blocks
- 为 API 请求编译 system prompt 部分

**为什么重要：**
Claude Code 的 system prompt 不只是常量文本，而是带 sections 与运行时注入的结构化块。

**一句话总结：**
> system prompt 的主组装器。

---

### 6.2 `source/src/constants/prompts.ts`

**定位：** prompt 常量基底层。

**负责：**
- 提供各种静态 prompt 模板、文本常量或基础提示片段

**一句话总结：**
> 静态 prompt 文本仓库。

---

### 6.3 `source/src/constants/systemPromptSections.ts`

**定位：** system prompt section 定义层。

**负责：**
- 定义 system prompt 的结构化 section 片段
- 供 system prompt 组装器拼出更稳定、可缓存的 prompt blocks

**一句话总结：**
> system prompt 的结构化骨架定义。

---

### 6.4 `source/src/context.ts`

**定位：** runtime context 注入核心。

**负责：**
- 生成 `systemContext`
- 生成 `userContext`
- 获取 git snapshot
- 注入 currentDate 与 CLAUDE.md 相关内容

**为什么重要：**
它是从“静态 prompt”走向“动态 prompt”的第一跳。

**一句话总结：**
> prompt 动态上下文的主入口。

---

### 6.5 `source/src/utils/claudemd.ts`

**定位：** CLAUDE.md 注入器。

**负责：**
- 搜索、读取、聚合 CLAUDE.md 与相关目录说明
- 供 `userContext` 注入 prompt

**一句话总结：**
> 本地项目说明文档到 prompt 的桥。

---

### 6.6 `source/src/query.ts`

**定位：** prompt 运行期总编排器。

**负责：**
- 组织 messages
- 注入 attachments / memory / queued commands
- 在 compact 后选择新的 prompt 视图
- 决定何时重构 prompt 再发起下一轮

**一句话总结：**
> prompt 编译流程的运行期总控。

---

### 6.7 `source/src/services/api/claude.ts`

**定位：** API 请求级 prompt 编译器。

**负责：**
- `buildSystemPromptBlocks(...)`
- `normalizeMessagesForAPI(...)`
- `toolToAPISchema(...)`
- 构造 cache strategy / cache breakpoints / cache edits
- 输出最终 API 请求参数

**为什么重要：**
真正发给模型的 prompt，就是在这里被“编译完成”的。

**一句话总结：**
> Claude Code prompt 的最终 API 编译器。

---

### 6.8 `source/src/services/api/promptCacheBreakDetection.ts`

**定位：** prompt cache 感知器。

**负责：**
- 判断 prompt cache 前缀何时断裂
- 给 microcompact、cache_edits、API request 组织方式提供依据

**一句话总结：**
> prompt cache 断点检测中枢。

---

### 6.9 `source/src/services/compact/microCompact.ts`

**定位：** cache-aware 轻量 prompt 重写层。

**负责：**
- cached microcompact
- time-based microcompact
- 删除旧 tool_result 但尽量保住 cache prefix

**一句话总结：**
> 面向 prompt cache 的轻量重写器。

---

### 6.10 `source/src/services/compact/compact.ts`

**定位：** full prompt 重构层。

**负责：**
- 历史摘要压缩
- 重建 compact 后 prompt 视图
- 恢复必要 attachments / files / plans / skills

**一句话总结：**
> prompt 超长后的重建器。

---

### 6.11 `source/src/services/api/dumpPrompts.ts`

**定位：** prompt 调试输出层。

**负责：**
- 导出当前 prompt / request 结构
- 帮助开发者观察最终发给模型的内容

**一句话总结：**
> prompt 编译结果的调试镜子。

---

### 6.12 `source/src/utils/promptShellExecution.ts`

**定位：** prompt 内 shell 插值执行层。

**负责：**
- 在 skill / command prompt 中执行 shell frontmatter 或内嵌 shell 片段
- 把结果再注入 prompt 内容

**为什么重要：**
这属于 prompt 动态拼接中最强的一种：prompt 自己还能执行外部命令来生成内容。

**一句话总结：**
> prompt 动态生成中的 shell 执行桥。

---

## 7. “所有涉及文件”的职责总结

下面把这个功能块涉及的文件逐项按层总结。

---

## 7.1 静态 system prompt 基底层文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/constants/prompts.ts` | 各类静态 prompt 文本、模板与片段常量仓库 |
| `source/src/constants/systemPromptSections.ts` | system prompt 的 section 分块定义 |
| `source/src/utils/systemPrompt.ts` | 组装最终 system prompt blocks 的主逻辑 |
| `source/src/utils/systemPromptType.ts` | system prompt 相关类型与结构定义 |

---

## 7.2 runtime context / 动态注入层文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/context.ts` | 运行时生成 systemContext / userContext |
| `source/src/utils/context.ts` | context 处理辅助逻辑 |
| `source/src/utils/contextAnalysis.ts` | context 分析辅助，用于理解上下文结构/问题 |
| `source/src/utils/contextSuggestions.ts` | 给上下文治理或用户提供 context 相关建议 |
| `source/src/utils/claudemd.ts` | 搜索、读取与聚合 CLAUDE.md 相关内容 |
| `source/src/utils/attachments.ts` | 将运行时副作用转成 attachment messages 注入 prompt |
| `source/src/services/SessionMemory/sessionMemory.ts` | SessionMemory 主服务，将当前 session 记忆组织进 prompt 体系 |
| `source/src/services/SessionMemory/sessionMemoryUtils.ts` | SessionMemory 的辅助逻辑 |
| `source/src/services/SessionMemory/prompts.ts` | SessionMemory 使用的 prompt 模板 |
| `source/src/memdir/findRelevantMemories.ts` | 找到与当前 query 最相关的 memories，用于 prompt 注入 |
| `source/src/memdir/memdir.ts` | durable memory 目录主服务 |
| `source/src/memdir/memoryAge.ts` | relevant memory 的时效权重辅助 |
| `source/src/memdir/memoryScan.ts` | 扫描 memory 文件，供 relevant memory 检索使用 |
| `source/src/memdir/memoryTypes.ts` | memory 类型定义 |
| `source/src/memdir/paths.ts` | 决定 memory 在哪里、哪些 path 合法 |
| `source/src/memdir/teamMemPaths.ts` | team memory 路径规划 |
| `source/src/memdir/teamMemPrompts.ts` | team memory 的 prompt 模板 |
| `source/src/utils/mcpInstructionsDelta.ts` | MCP instruction 变化量作为 prompt 注入材料 |

---

## 7.3 Query / API Prompt 编译层文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/query.ts` | 主循环中组织 messages / attachments / compact 结果并触发下一轮 prompt 编译 |
| `source/src/query/tokenBudget.ts` | 通过 continuation nudge 影响 prompt 的继续策略 |
| `source/src/services/api/claude.ts` | 把 prompt/messages/tools 编译成最终 API 请求 |
| `source/src/services/api/dumpPrompts.ts` | dump prompt 调试输出 |
| `source/src/services/api/promptCacheBreakDetection.ts` | 检测 prompt cache break |
| `source/src/utils/messages.ts` | 消息结构操作，支撑 prompt 编译 |
| `source/src/utils/messages/mappers.ts` | messages/content blocks 映射 |
| `source/src/utils/messages/systemInit.ts` | 系统初始化消息辅助 |
| `source/src/constants/messages.ts` | 消息相关常量 |

---

## 7.4 Compact / Cache / Recovery 层文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/compact/apiMicrocompact.ts` | API/cache-edit 方向的微型 compact 支持 |
| `source/src/services/compact/autoCompact.ts` | 何时开始重构/压缩 prompt 的阈值决策 |
| `source/src/services/compact/compact.ts` | full/partial compact，实现 prompt 大重构 |
| `source/src/services/compact/compactWarningHook.ts` | compact warning 与 hooks 协同 |
| `source/src/services/compact/compactWarningState.ts` | compact warning 状态持有 |
| `source/src/services/compact/grouping.ts` | compact 输入分组与 prompt 组织辅助 |
| `source/src/services/compact/microCompact.ts` | 轻量 prompt cache-aware 重写 |
| `source/src/services/compact/postCompactCleanup.ts` | compact 后清理与状态重置 |
| `source/src/services/compact/prompt.ts` | compact agent 的 prompt 构造 |
| `source/src/services/compact/sessionMemoryCompact.ts` | session memory 方向的 compact 支路 |
| `source/src/services/compact/timeBasedMCConfig.ts` | time-based microcompact 配置来源 |
| `source/src/utils/cachePaths.ts` | 缓存文件/路径组织辅助 |
| `source/src/commands/break-cache/index.js` | cache 调试/破坏缓存命令 |
| `source/src/commands/clear/caches.ts` | 清理缓存命令逻辑 |

---

## 7.5 Tool / Skill / Command Prompt 层文件职责总结

这一层数量很多，但结构很整齐：
- 大多数工具都有一个 `prompt.ts`
- skills / plugin commands 会把 markdown / inline content 变成 `PromptCommand`
- promptShellExecution 负责动态 shell 插值

### 7.5.1 tools/**/prompt.ts 系列

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/AgentTool/prompt.ts` | 定义 AgentTool 对模型可见的 prompt/schema 描述 |
| `source/src/tools/AskUserQuestionTool/prompt.ts` | AskUserQuestionTool prompt/schema |
| `source/src/tools/BashTool/prompt.ts` | BashTool prompt/schema |
| `source/src/tools/BriefTool/prompt.ts` | BriefTool prompt/schema |
| `source/src/tools/ConfigTool/prompt.ts` | ConfigTool prompt/schema |
| `source/src/tools/EnterPlanModeTool/prompt.ts` | EnterPlanModeTool prompt/schema |
| `source/src/tools/EnterWorktreeTool/prompt.ts` | EnterWorktreeTool prompt/schema |
| `source/src/tools/ExitPlanModeTool/prompt.ts` | ExitPlanModeTool prompt/schema |
| `source/src/tools/ExitWorktreeTool/prompt.ts` | ExitWorktreeTool prompt/schema |
| `source/src/tools/FileEditTool/prompt.ts` | FileEditTool prompt/schema |
| `source/src/tools/FileReadTool/prompt.ts` | FileReadTool prompt/schema |
| `source/src/tools/FileWriteTool/prompt.ts` | FileWriteTool prompt/schema |
| `source/src/tools/GlobTool/prompt.ts` | GlobTool prompt/schema |
| `source/src/tools/GrepTool/prompt.ts` | GrepTool prompt/schema |
| `source/src/tools/LSPTool/prompt.ts` | LSPTool prompt/schema |
| `source/src/tools/ListMcpResourcesTool/prompt.ts` | ListMcpResourcesTool prompt/schema |
| `source/src/tools/MCPTool/prompt.ts` | MCPTool prompt/schema |
| `source/src/tools/NotebookEditTool/prompt.ts` | NotebookEditTool prompt/schema |
| `source/src/tools/PowerShellTool/prompt.ts` | PowerShellTool prompt/schema |
| `source/src/tools/ReadMcpResourceTool/prompt.ts` | ReadMcpResourceTool prompt/schema |
| `source/src/tools/RemoteTriggerTool/prompt.ts` | RemoteTriggerTool prompt/schema |
| `source/src/tools/ScheduleCronTool/prompt.ts` | Cron 工具家族 prompt/schema |
| `source/src/tools/SendMessageTool/prompt.ts` | SendMessageTool prompt/schema |
| `source/src/tools/SkillTool/prompt.ts` | SkillTool prompt/schema |
| `source/src/tools/SleepTool/prompt.ts` | SleepTool prompt/schema |
| `source/src/tools/TaskCreateTool/prompt.ts` | TaskCreateTool prompt/schema |
| `source/src/tools/TaskGetTool/prompt.ts` | TaskGetTool prompt/schema |
| `source/src/tools/TaskListTool/prompt.ts` | TaskListTool prompt/schema |
| `source/src/tools/TaskStopTool/prompt.ts` | TaskStopTool prompt/schema |
| `source/src/tools/TaskUpdateTool/prompt.ts` | TaskUpdateTool prompt/schema |
| `source/src/tools/TeamCreateTool/prompt.ts` | TeamCreateTool prompt/schema |
| `source/src/tools/TeamDeleteTool/prompt.ts` | TeamDeleteTool prompt/schema |
| `source/src/tools/TodoWriteTool/prompt.ts` | TodoWriteTool prompt/schema |
| `source/src/tools/ToolSearchTool/prompt.ts` | ToolSearchTool prompt/schema |
| `source/src/tools/WebFetchTool/prompt.ts` | WebFetchTool prompt/schema |
| `source/src/tools/WebSearchTool/prompt.ts` | WebSearchTool prompt/schema |

### 7.5.2 skills / commands / plugin prompt 构造相关

| 相对路径 | 作用总结 |
|---|---|
| `source/src/skills/loadSkillsDir.ts` | 把 markdown skills 转成 PromptCommand，并做参数/allowed-tools/shell 处理 |
| `source/src/skills/bundledSkills.ts` | 把 bundled skills 转成 PromptCommand |
| `source/src/utils/plugins/loadPluginCommands.ts` | 把 plugin markdown / inline content 转成命令 prompt |
| `source/src/utils/promptShellExecution.ts` | 在 prompt 内容中执行 shell 插值并回填结果 |
| `source/src/utils/promptCategory.ts` | prompt 类别划分辅助 |
| `source/src/utils/promptEditor.ts` | prompt 编辑辅助 |
| `source/src/utils/toolSearch.ts` | ToolSearch 与 deferred tools 的 prompt/selection 协同 |

---

## 7.6 Prompt 派生子系统文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/PromptSuggestion/promptSuggestion.ts` | prompt suggestion 相关逻辑与模板使用 |
| `source/src/services/MagicDocs/prompts.ts` | MagicDocs 子系统 prompt 模板 |
| `source/src/services/extractMemories/prompts.ts` | extract memories 子流程 prompt 模板 |
| `source/src/buddy/prompt.ts` | buddy/辅助角色 prompt |
| `source/src/utils/claudeInChrome/prompt.ts` | Claude in Chrome 场景 prompt |
| `source/src/tools/BriefTool/attachments.ts` | brief 场景下和 prompt/attachment 结合的辅助逻辑 |
| `source/src/commands/brief.ts` | brief 模式命令入口 |
| `source/src/commands/context/context.tsx` | 上下文查看命令（帮助观察 prompt 组成） |
| `source/src/commands/context/context-noninteractive.ts` | 非交互上下文查看 |
| `source/src/commands/compact/compact.ts` | 手动触发 compact，进而重构 prompt |
| `source/src/commands/compact/index.ts` | compact 命令注册 |

---

## 8. Prompt 与缓存机制的五个核心结论

### 结论 1：Claude Code 的 prompt 不是“一段文本”，而是多层 block 编译结果

真正 API 请求里的 prompt 由这些部分组成：
- system prompt blocks
- normalized messages
- tool schemas
- cache strategy / cache breakpoints
- optional cache_edits

---

### 结论 2：动态拼接主要来自 context / memory / attachments / skills

也就是：
- `context.ts`
- `claudemd.ts`
- `attachments.ts`
- `SessionMemory/**`
- `memdir/**`
- `skills/loadSkillsDir.ts`
- `promptShellExecution.ts`

---

### 结论 3：prompt caching 是 Claude Code 设计中的一等目标

从这些地方都能看出来：
- stable tool ordering
- promptCacheBreakDetection
- cache_edits based microcompact
- compact cache sharing
- break-cache / clear caches / dump prompts

这说明代码库非常重视缓存命中，而不是把 prompt 当一次性字符串随便拼。

---

### 结论 4：microcompact 和 compact 本质上都是“prompt 重写机制”

- `microCompact.ts` = 尽量不破坏 cache 的轻量重写
- `compact.ts` = 必要时整体重构 prompt 视图

---

### 结论 5：tool prompt、skill prompt、system prompt 是三条并列的 prompt 来源

- system prompt：行为边界与全局规则
- tool prompt/schema：能力面定义
- skill/command prompt：高层任务模板

三者共同构成 Claude Code 最终给模型的运行语境。

---

## 9. 当前文档的覆盖边界说明

这份文档已经尽量按你的要求做到：

- 有 **prompt 动态拼接 / 静态拼接 / 缓存加载机制完整架构图**
- 有 **主流程图**
- 有 **相对路径索引**
- 有 **核心骨架文件详细说明**
- 有这个功能块所有涉及文件的**逐项职责总结**

说明一下粒度：

### 第一层：主骨架文件 = 详细说明
- `systemPrompt.ts`
- `constants/prompts.ts`
- `constants/systemPromptSections.ts`
- `context.ts`
- `claudemd.ts`
- `query.ts`
- `services/api/claude.ts`
- `promptCacheBreakDetection.ts`
- `microCompact.ts`
- `compact.ts`
- `dumpPrompts.ts`
- `promptShellExecution.ts`

### 第二层：支撑文件 = 逐项职责摘要
- `SessionMemory/**`
- `memdir/**`
- `tools/**/prompt.ts`
- `skills/loadSkillsDir.ts`
- `bundledSkills.ts`
- `loadPluginCommands.ts`
- compact/cache 相关辅助文件
- 派生 prompt 子系统文件

如果你后面还要更深，我建议继续拆成 3 份专项：

1. **system prompt 与 context 注入深拆**
2. **tool/skill/command prompt 深拆**
3. **prompt cache / compact / cache edits 深拆**

---

## 10. 当前输出结果

本轮已完成：
- **Prompt 动态拼接 / 静态拼接 / 缓存加载机制完整架构图**
- **Prompt 主流程图**
- **相对路径总索引**
- **主骨架文件详细说明**
- **该功能块所有涉及文件职责总结**

已保存到：
- `cc/cc_learn/20_arch_prompt_assembly_and_cache_framework.md`

---

## 11. 建议的下一步（如果继续深挖）

如果你还要继续沿这条线深入，我建议再拆成 3 个专门文档：

1. **System Prompt 与 Context 注入专项**
2. **Tool / Skill / Command Prompt 构造专项**
3. **Prompt Cache / Compact / Cache Edit / Dump Prompts 专项**

如果你愿意，我下一步可以直接继续做：

> **System Prompt 与 Context 注入专项深拆版**