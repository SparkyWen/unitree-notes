# Claude Code 子功能架构图 03：工具系统模块

- 仓库路径：`cc/claude_code`
- 对应总图文档：`cc/cc_learn/12_overall_architecture_framework.md`
- 当前主题：**工具系统模块（Tool Registry / Tool Protocol / Tool Permission / Tool Execution / Tool Families）**
- 当前目标：
  1. 画出工具系统的完整子架构图
  2. 给出该功能块涉及文件的相对路径索引
  3. 对该功能块**所有涉及文件**总结作用

---

## 1. 工具系统模块到底负责什么

如果说命令系统解决的是：

- 用户在会话层能触发什么高层动作

那么工具系统解决的是：

- 模型在 agent loop 里能直接调用什么执行能力
- 每个工具的 schema / permission / prompt / UI 怎么定义
- 工具如何被过滤、组合、执行、流式回传结果
- 本地工具、MCP 工具、agent/task/team 工具如何统一成一个能力面

一句话：

> **工具系统是 Claude Code 把“模型输出的 tool_use”变成真实执行行为的底层能力平台。**

---

## 2. 工具系统总架构图（静态结构图）

```text
工具系统模块
├── A. 工具协议层
│   └── source/src/Tool.ts
│       - Tool / ToolDef
│       - ToolUseContext
│       - ToolPermissionContext
│       - buildTool()
│
├── B. 工具注册与组合层
│   ├── source/src/tools.ts
│   └── source/src/constants/tools.ts
│       - built-in tool registry
│       - mode-based filtering
│       - agent/coordinator allowed sets
│       - MCP tool merge
│
├── C. 工具执行编排层
│   └── source/src/services/tools/**
│       - toolExecution.ts
│       - StreamingToolExecutor.ts
│       - toolOrchestration.ts
│       - toolHooks.ts
│
├── D. 工具家族实现层
│   └── source/src/tools/**
│       - File tools
│       - Bash / PowerShell tools
│       - Web tools
│       - MCP tools
│       - Agent / Team / Task tools
│       - Plan / Worktree / Skill / Config tools
│       - REPL / Synthetic / Testing tools
│
└── E. 工具共用辅助层
    ├── source/src/tools/shared/**
    ├── source/src/tools/testing/**
    └── source/src/tools/utils.ts
```

---

## 3. 工具系统动态流程图（运行图）

```text
启动 / main.tsx / query.ts
      │
      ▼
[source/src/tools.ts]
  - getAllBaseTools()
  - getTools(permissionContext)
  - assembleToolPool(permissionContext, mcpTools)
      │
      ▼
得到最终 Tool[]
      │
      ▼
query.ts 收到 assistant tool_use
      │
      ▼
[source/src/services/tools/StreamingToolExecutor.ts]
  - addTool()
  - 判断并发安全
  - 排队/执行/收集 progress 与结果
      │
      ▼
[source/src/services/tools/toolExecution.ts]
  - schema parse
  - validateInput
  - hooks
  - permission decision
  - tool.call(...)
  - result mapping / tool_result
      │
      ├── 若是 MCP 工具
      │     -> tools/MCPTool/** + services/mcp/**
      │
      ├── 若是本地文件/命令/Web 工具
      │     -> 对应 tools/<Family>/**
      │
      └── 若是 Agent/Task/Team 工具
            -> tools/AgentTool/** / Task* / Team*
      │
      ▼
tool_result / progress / attachments / contextModifier
      │
      ▼
回流到 query.ts 下一轮
```

---

## 4. 工具系统功能分层图

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 1. 协议层：Tool.ts                                                     │
│    定义工具是什么、执行上下文是什么、权限上下文是什么                  │
└────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. 注册组合层：tools.ts / constants/tools.ts                           │
│    决定有哪些工具、哪些模式下可见、如何与 MCP 工具合并                 │
└────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. 执行编排层：services/tools/**                                        │
│    决定 tool_use 如何被解析、调度、hook、授权、执行、产出结果           │
└────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 4. 工具家族实现层：tools/**                                             │
│    各个具体工具家族实现自己的 schema / validate / call / UI / prompt   │
└────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 5. Query / UI / MCP / Agent Runtime 使用层                              │
│    工具能力最终被 query.ts / REPL / model runtime / attachments 使用    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 该功能块涉及的文件范围（总览）

当前把工具系统涉及文件分成 6 类：

1. 工具协议文件
2. 工具注册/常量文件
3. 工具执行编排文件
4. 各工具家族实现文件
5. 工具共享辅助文件
6. 测试/特殊工具文件

---

## 6. 相对路径索引（总表）

---

### 6.1 协议与注册入口

| 相对路径 | 作用 |
|---|---|
| `source/src/Tool.ts` | 工具协议中心，定义 Tool / ToolUseContext / ToolPermissionContext |
| `source/src/tools.ts` | 工具注册与组合总入口 |
| `source/src/constants/tools.ts` | 多 agent / mode 工具可见性策略常量 |

---

### 6.2 工具执行编排层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/tools/StreamingToolExecutor.ts` | 流式工具队列执行器 |
| `source/src/services/tools/toolExecution.ts` | 单次 tool_use 执行总流水线 |
| `source/src/services/tools/toolHooks.ts` | 工具 hook 执行与桥接逻辑 |
| `source/src/services/tools/toolOrchestration.ts` | 非流式工具批处理编排 |

---

### 6.3 工具共享辅助层

| 相对路径 | 作用 |
|---|---|
| `source/src/tools/utils.ts` | 工具层通用辅助函数 |
| `source/src/tools/shared/gitOperationTracking.ts` | 工具执行过程中的 git 操作跟踪 |
| `source/src/tools/shared/spawnMultiAgent.ts` | 多 agent 相关工具的共享生成/调度辅助 |
| `source/src/tools/testing/TestingPermissionTool.tsx` | 测试权限/调试用工具 |

---

### 6.4 tools/** 全量文件索引

下面先完整列出当前 `tools/**` 的文件，再按家族分类总结职责。

```text
source/src/tools/AgentTool/AgentTool.tsx
source/src/tools/AgentTool/UI.tsx
source/src/tools/AgentTool/agentColorManager.ts
source/src/tools/AgentTool/agentDisplay.ts
source/src/tools/AgentTool/agentMemory.ts
source/src/tools/AgentTool/agentMemorySnapshot.ts
source/src/tools/AgentTool/agentToolUtils.ts
source/src/tools/AgentTool/built-in/claudeCodeGuideAgent.ts
source/src/tools/AgentTool/built-in/exploreAgent.ts
source/src/tools/AgentTool/built-in/generalPurposeAgent.ts
source/src/tools/AgentTool/built-in/planAgent.ts
source/src/tools/AgentTool/built-in/statuslineSetup.ts
source/src/tools/AgentTool/built-in/verificationAgent.ts
source/src/tools/AgentTool/builtInAgents.ts
source/src/tools/AgentTool/constants.ts
source/src/tools/AgentTool/forkSubagent.ts
source/src/tools/AgentTool/loadAgentsDir.ts
source/src/tools/AgentTool/prompt.ts
source/src/tools/AgentTool/resumeAgent.ts
source/src/tools/AgentTool/runAgent.ts
source/src/tools/AskUserQuestionTool/AskUserQuestionTool.tsx
source/src/tools/AskUserQuestionTool/prompt.ts
source/src/tools/BashTool/BashTool.tsx
source/src/tools/BashTool/BashToolResultMessage.tsx
source/src/tools/BashTool/UI.tsx
source/src/tools/BashTool/bashCommandHelpers.ts
source/src/tools/BashTool/bashPermissions.ts
source/src/tools/BashTool/bashSecurity.ts
source/src/tools/BashTool/commandSemantics.ts
source/src/tools/BashTool/commentLabel.ts
source/src/tools/BashTool/destructiveCommandWarning.ts
source/src/tools/BashTool/modeValidation.ts
source/src/tools/BashTool/pathValidation.ts
source/src/tools/BashTool/prompt.ts
source/src/tools/BashTool/readOnlyValidation.ts
source/src/tools/BashTool/sedEditParser.ts
source/src/tools/BashTool/sedValidation.ts
source/src/tools/BashTool/shouldUseSandbox.ts
source/src/tools/BashTool/toolName.ts
source/src/tools/BashTool/utils.ts
source/src/tools/BriefTool/BriefTool.ts
source/src/tools/BriefTool/UI.tsx
source/src/tools/BriefTool/attachments.ts
source/src/tools/BriefTool/prompt.ts
source/src/tools/BriefTool/upload.ts
source/src/tools/ConfigTool/ConfigTool.ts
source/src/tools/ConfigTool/UI.tsx
source/src/tools/ConfigTool/constants.ts
source/src/tools/ConfigTool/prompt.ts
source/src/tools/ConfigTool/supportedSettings.ts
source/src/tools/EnterPlanModeTool/EnterPlanModeTool.ts
source/src/tools/EnterPlanModeTool/UI.tsx
source/src/tools/EnterPlanModeTool/constants.ts
source/src/tools/EnterPlanModeTool/prompt.ts
source/src/tools/EnterWorktreeTool/EnterWorktreeTool.ts
source/src/tools/EnterWorktreeTool/UI.tsx
source/src/tools/EnterWorktreeTool/constants.ts
source/src/tools/EnterWorktreeTool/prompt.ts
source/src/tools/ExitPlanModeTool/ExitPlanModeV2Tool.ts
source/src/tools/ExitPlanModeTool/UI.tsx
source/src/tools/ExitPlanModeTool/constants.ts
source/src/tools/ExitPlanModeTool/prompt.ts
source/src/tools/ExitWorktreeTool/ExitWorktreeTool.ts
source/src/tools/ExitWorktreeTool/UI.tsx
source/src/tools/ExitWorktreeTool/constants.ts
source/src/tools/ExitWorktreeTool/prompt.ts
source/src/tools/FileEditTool/FileEditTool.ts
source/src/tools/FileEditTool/UI.tsx
source/src/tools/FileEditTool/constants.ts
source/src/tools/FileEditTool/prompt.ts
source/src/tools/FileEditTool/types.ts
source/src/tools/FileEditTool/utils.ts
source/src/tools/FileReadTool/FileReadTool.ts
source/src/tools/FileReadTool/UI.tsx
source/src/tools/FileReadTool/imageProcessor.ts
source/src/tools/FileReadTool/limits.ts
source/src/tools/FileReadTool/prompt.ts
source/src/tools/FileWriteTool/FileWriteTool.ts
source/src/tools/FileWriteTool/UI.tsx
source/src/tools/FileWriteTool/prompt.ts
source/src/tools/GlobTool/GlobTool.ts
source/src/tools/GlobTool/UI.tsx
source/src/tools/GlobTool/prompt.ts
source/src/tools/GrepTool/GrepTool.ts
source/src/tools/GrepTool/UI.tsx
source/src/tools/GrepTool/prompt.ts
source/src/tools/LSPTool/LSPTool.ts
source/src/tools/LSPTool/UI.tsx
source/src/tools/LSPTool/formatters.ts
source/src/tools/LSPTool/prompt.ts
source/src/tools/LSPTool/schemas.ts
source/src/tools/LSPTool/symbolContext.ts
source/src/tools/ListMcpResourcesTool/ListMcpResourcesTool.ts
source/src/tools/ListMcpResourcesTool/UI.tsx
source/src/tools/ListMcpResourcesTool/prompt.ts
source/src/tools/MCPTool/MCPTool.ts
source/src/tools/MCPTool/UI.tsx
source/src/tools/MCPTool/classifyForCollapse.ts
source/src/tools/MCPTool/prompt.ts
source/src/tools/McpAuthTool/McpAuthTool.ts
source/src/tools/NotebookEditTool/NotebookEditTool.ts
source/src/tools/NotebookEditTool/UI.tsx
source/src/tools/NotebookEditTool/constants.ts
source/src/tools/NotebookEditTool/prompt.ts
source/src/tools/PowerShellTool/PowerShellTool.tsx
source/src/tools/PowerShellTool/UI.tsx
source/src/tools/PowerShellTool/clmTypes.ts
source/src/tools/PowerShellTool/commandSemantics.ts
source/src/tools/PowerShellTool/commonParameters.ts
source/src/tools/PowerShellTool/destructiveCommandWarning.ts
source/src/tools/PowerShellTool/gitSafety.ts
source/src/tools/PowerShellTool/modeValidation.ts
source/src/tools/PowerShellTool/pathValidation.ts
source/src/tools/PowerShellTool/powershellPermissions.ts
source/src/tools/PowerShellTool/powershellSecurity.ts
source/src/tools/PowerShellTool/prompt.ts
source/src/tools/PowerShellTool/readOnlyValidation.ts
source/src/tools/PowerShellTool/toolName.ts
source/src/tools/REPLTool/constants.ts
source/src/tools/REPLTool/primitiveTools.ts
source/src/tools/ReadMcpResourceTool/ReadMcpResourceTool.ts
source/src/tools/ReadMcpResourceTool/UI.tsx
source/src/tools/ReadMcpResourceTool/prompt.ts
source/src/tools/RemoteTriggerTool/RemoteTriggerTool.ts
source/src/tools/RemoteTriggerTool/UI.tsx
source/src/tools/RemoteTriggerTool/prompt.ts
source/src/tools/ScheduleCronTool/CronCreateTool.ts
source/src/tools/ScheduleCronTool/CronDeleteTool.ts
source/src/tools/ScheduleCronTool/CronListTool.ts
source/src/tools/ScheduleCronTool/UI.tsx
source/src/tools/ScheduleCronTool/prompt.ts
source/src/tools/SendMessageTool/SendMessageTool.ts
source/src/tools/SendMessageTool/UI.tsx
source/src/tools/SendMessageTool/constants.ts
source/src/tools/SendMessageTool/prompt.ts
source/src/tools/SkillTool/SkillTool.ts
source/src/tools/SkillTool/UI.tsx
source/src/tools/SkillTool/constants.ts
source/src/tools/SkillTool/prompt.ts
source/src/tools/SleepTool/prompt.ts
source/src/tools/SyntheticOutputTool/SyntheticOutputTool.ts
source/src/tools/TaskCreateTool/TaskCreateTool.ts
source/src/tools/TaskCreateTool/constants.ts
source/src/tools/TaskCreateTool/prompt.ts
source/src/tools/TaskGetTool/TaskGetTool.ts
source/src/tools/TaskGetTool/constants.ts
source/src/tools/TaskGetTool/prompt.ts
source/src/tools/TaskListTool/TaskListTool.ts
source/src/tools/TaskListTool/constants.ts
source/src/tools/TaskListTool/prompt.ts
source/src/tools/TaskOutputTool/TaskOutputTool.tsx
source/src/tools/TaskOutputTool/constants.ts
source/src/tools/TaskStopTool/TaskStopTool.ts
source/src/tools/TaskStopTool/UI.tsx
source/src/tools/TaskStopTool/prompt.ts
source/src/tools/TaskUpdateTool/TaskUpdateTool.ts
source/src/tools/TaskUpdateTool/constants.ts
source/src/tools/TaskUpdateTool/prompt.ts
source/src/tools/TeamCreateTool/TeamCreateTool.ts
source/src/tools/TeamCreateTool/UI.tsx
source/src/tools/TeamCreateTool/constants.ts
source/src/tools/TeamCreateTool/prompt.ts
source/src/tools/TeamDeleteTool/TeamDeleteTool.ts
source/src/tools/TeamDeleteTool/UI.tsx
source/src/tools/TeamDeleteTool/constants.ts
source/src/tools/TeamDeleteTool/prompt.ts
source/src/tools/TodoWriteTool/TodoWriteTool.ts
source/src/tools/TodoWriteTool/constants.ts
source/src/tools/TodoWriteTool/prompt.ts
source/src/tools/ToolSearchTool/ToolSearchTool.ts
source/src/tools/ToolSearchTool/constants.ts
source/src/tools/ToolSearchTool/prompt.ts
source/src/tools/WebFetchTool/UI.tsx
source/src/tools/WebFetchTool/WebFetchTool.ts
source/src/tools/WebFetchTool/preapproved.ts
source/src/tools/WebFetchTool/prompt.ts
source/src/tools/WebFetchTool/utils.ts
source/src/tools/WebSearchTool/UI.tsx
source/src/tools/WebSearchTool/WebSearchTool.ts
source/src/tools/WebSearchTool/prompt.ts
source/src/tools/shared/gitOperationTracking.ts
source/src/tools/shared/spawnMultiAgent.ts
source/src/tools/testing/TestingPermissionTool.tsx
source/src/tools/utils.ts
```

---

## 7. 工具系统主线总结

工具系统的主线可以概括为：

```text
Tool.ts -> tools.ts -> services/tools/** -> tools/<Family>/**
```

更完整一点：

```text
source/src/Tool.ts
  -> 定义 Tool 协议与上下文
source/src/tools.ts
  -> 组合 base tools + MCP tools，做 mode/filter 过滤
source/src/constants/tools.ts
  -> 规定 agent/coordinator/in-process 等模式的工具边界
source/src/services/tools/toolExecution.ts
  -> 执行一次 tool_use
source/src/services/tools/StreamingToolExecutor.ts
  -> 管理多 tool_use 的并发/顺序/结果流
source/src/services/tools/toolHooks.ts
  -> 工具 hooks 接入
source/src/services/tools/toolOrchestration.ts
  -> 非流式批处理编排
source/src/tools/**
  -> 各工具家族提供具体 schema / validate / call / UI / prompt
```

---

## 8. 核心文件逐项职责说明

---

### 8.1 `source/src/Tool.ts`

**作用：** 工具协议中心。

它定义：
- `Tool`
- `ToolDef`
- `ToolUseContext`
- `ToolPermissionContext`
- `buildTool()`
- 工具 lookup / helper

**它解决的问题：**
所有工具种类都不一样，但必须用统一协议被 query/toolExecution 消费。

**一句话总结：**
> 工具系统的领域模型和统一执行契约。

---

### 8.2 `source/src/tools.ts`

**作用：** 工具注册与组合总入口。

它负责：
- 注册所有 built-in tools
- 根据 mode/feature/env 过滤工具
- 根据 deny rules 预过滤工具
- 和 MCP tools 合并成最终工具池

**它解决的问题：**
运行时不应该手工拼各个工具，只应拿到一份“当前上下文下可用的工具集”。

**一句话总结：**
> 工具系统的总注册中心和可见性裁剪器。

---

### 8.3 `source/src/constants/tools.ts`

**作用：** 多 agent / 多 mode 工具边界常量。

它定义：
- `ALL_AGENT_DISALLOWED_TOOLS`
- `ASYNC_AGENT_ALLOWED_TOOLS`
- `IN_PROCESS_TEAMMATE_ALLOWED_TOOLS`
- `COORDINATOR_MODE_ALLOWED_TOOLS`

**一句话总结：**
> 工具可见性策略层。

---

### 8.4 `source/src/services/tools/toolExecution.ts`

**作用：** 单次 tool_use 执行总流水线。

它负责：
- 找工具
- 解析/校验输入
- 运行 pre/post hooks
- 做权限判断
- 调 `tool.call()`
- 映射 tool_result
- 生成 progress / result / attachment messages

**一句话总结：**
> 工具执行的核心总管道。

---

### 8.5 `source/src/services/tools/StreamingToolExecutor.ts`

**作用：** 流式工具执行器。

它负责：
- 管理多个 tool_use 的状态
- 判断是否可并发执行
- 先 yield progress，再 yield result
- 处理 sibling bash error 级联取消

**一句话总结：**
> 多工具流式调度器。

---

### 8.6 `source/src/services/tools/toolOrchestration.ts`

**作用：** 非流式工具批量执行编排器。

它负责：
- 按并发安全性分组
- 串行/并发执行 tool_use 批次
- 在并发工具完成后顺序应用 context modifiers

**一句话总结：**
> 工具执行的批处理 fallback 编排器。

---

### 8.7 `source/src/services/tools/toolHooks.ts`

**作用：** 工具 hooks 执行桥接层。

它负责：
- pre-tool hooks
- post-tool hooks
- tool failure hooks
- hook 结果到执行流水线的连接

**一句话总结：**
> 工具 hook 与执行流水线的中间层。

---

## 9. 各工具家族逐组职责总结

下面开始覆盖 `tools/**` 全部文件，并按工具家族解释作用。

---

## 9.1 AgentTool 家族

这一组文件负责：

- 让模型创建/调度子 agent
- 管理 agent UI 表现、颜色、记忆、内置 agent 定义
- 处理 fork/resume/run agent 的运行流程

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/AgentTool/AgentTool.tsx` | AgentTool 主定义，提供创建/调度 agent 的工具实现 |
| `source/src/tools/AgentTool/UI.tsx` | AgentTool 的结果/UI 展示组件 |
| `source/src/tools/AgentTool/agentColorManager.ts` | 管理 agent 的颜色分配与显示颜色 |
| `source/src/tools/AgentTool/agentDisplay.ts` | agent 显示文本/展示信息辅助 |
| `source/src/tools/AgentTool/agentMemory.ts` | agent 记忆相关辅助逻辑 |
| `source/src/tools/AgentTool/agentMemorySnapshot.ts` | agent memory snapshot 的生成/恢复辅助 |
| `source/src/tools/AgentTool/agentToolUtils.ts` | AgentTool 通用辅助工具函数 |
| `source/src/tools/AgentTool/builtInAgents.ts` | 内建 agent 集合汇总 |
| `source/src/tools/AgentTool/constants.ts` | AgentTool 常量定义 |
| `source/src/tools/AgentTool/forkSubagent.ts` | fork 出子 agent 的逻辑 |
| `source/src/tools/AgentTool/loadAgentsDir.ts` | 从 agents 目录加载自定义 agent 定义 |
| `source/src/tools/AgentTool/prompt.ts` | AgentTool 的 prompt/schema 描述 |
| `source/src/tools/AgentTool/resumeAgent.ts` | 恢复已有 agent 的逻辑 |
| `source/src/tools/AgentTool/runAgent.ts` | 实际运行 agent 的执行逻辑 |
| `source/src/tools/AgentTool/built-in/claudeCodeGuideAgent.ts` | 内建 agent：Claude Code 引导型 agent |
| `source/src/tools/AgentTool/built-in/exploreAgent.ts` | 内建 agent：探索型 agent |
| `source/src/tools/AgentTool/built-in/generalPurposeAgent.ts` | 内建 agent：通用 agent |
| `source/src/tools/AgentTool/built-in/planAgent.ts` | 内建 agent：计划型 agent |
| `source/src/tools/AgentTool/built-in/statuslineSetup.ts` | 内建 agent 与状态线设置相关辅助 |
| `source/src/tools/AgentTool/built-in/verificationAgent.ts` | 内建 agent：验证型 agent |

---

## 9.2 AskUserQuestionTool

这组文件负责让模型显式向用户发问，而不是继续盲推。

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/AskUserQuestionTool/AskUserQuestionTool.tsx` | AskUserQuestion 工具主实现 |
| `source/src/tools/AskUserQuestionTool/prompt.ts` | AskUserQuestion 的 prompt/schema 描述 |

---

## 9.3 BashTool 家族

这一组是 shell 执行体系，负责：
- 命令语义判断
- 安全校验
- 权限判断
- sandbox 决策
- sed edit 特殊处理
- 结果展示

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/BashTool/BashTool.tsx` | BashTool 主实现 |
| `source/src/tools/BashTool/BashToolResultMessage.tsx` | Bash 工具结果消息/UI 组件 |
| `source/src/tools/BashTool/UI.tsx` | BashTool 的 UI 展示 |
| `source/src/tools/BashTool/bashCommandHelpers.ts` | Bash 命令解析/辅助函数 |
| `source/src/tools/BashTool/bashPermissions.ts` | Bash 权限判定逻辑 |
| `source/src/tools/BashTool/bashSecurity.ts` | Bash 安全分析与限制 |
| `source/src/tools/BashTool/commandSemantics.ts` | 命令语义分析（读/写/搜索/危险等） |
| `source/src/tools/BashTool/commentLabel.ts` | Bash 命令注释/标签辅助 |
| `source/src/tools/BashTool/destructiveCommandWarning.ts` | 危险命令警告逻辑 |
| `source/src/tools/BashTool/modeValidation.ts` | 模式相关校验 |
| `source/src/tools/BashTool/pathValidation.ts` | 路径安全校验 |
| `source/src/tools/BashTool/prompt.ts` | BashTool 的 prompt/schema 描述 |
| `source/src/tools/BashTool/readOnlyValidation.ts` | 只读命令识别与校验 |
| `source/src/tools/BashTool/sedEditParser.ts` | sed edit 解析与模拟编辑支持 |
| `source/src/tools/BashTool/sedValidation.ts` | sed 编辑校验 |
| `source/src/tools/BashTool/shouldUseSandbox.ts` | 是否启用 sandbox 的决策 |
| `source/src/tools/BashTool/toolName.ts` | BashTool 名称/常量 |
| `source/src/tools/BashTool/utils.ts` | BashTool 其他通用辅助 |

---

## 9.4 BriefTool 家族

这一组负责 brief 模式或压缩输出/摘要型工具交互。

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/BriefTool/BriefTool.ts` | BriefTool 主实现 |
| `source/src/tools/BriefTool/UI.tsx` | BriefTool UI 展示 |
| `source/src/tools/BriefTool/attachments.ts` | BriefTool 相关附件处理 |
| `source/src/tools/BriefTool/prompt.ts` | BriefTool prompt/schema |
| `source/src/tools/BriefTool/upload.ts` | BriefTool 相关上传/内容提交辅助 |

---

## 9.5 ConfigTool 家族

负责让模型或系统在受控范围内查看/调整配置型信息。

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/ConfigTool/ConfigTool.ts` | ConfigTool 主实现 |
| `source/src/tools/ConfigTool/UI.tsx` | ConfigTool UI |
| `source/src/tools/ConfigTool/constants.ts` | ConfigTool 常量 |
| `source/src/tools/ConfigTool/prompt.ts` | ConfigTool prompt/schema |
| `source/src/tools/ConfigTool/supportedSettings.ts` | ConfigTool 支持的设置项白名单/映射 |

---

## 9.6 Plan / Worktree 模式工具家族

负责让模型进入/退出计划模式、进入/退出 worktree。

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/EnterPlanModeTool/EnterPlanModeTool.ts` | 进入计划模式工具 |
| `source/src/tools/EnterPlanModeTool/UI.tsx` | EnterPlanModeTool UI |
| `source/src/tools/EnterPlanModeTool/constants.ts` | EnterPlanModeTool 常量 |
| `source/src/tools/EnterPlanModeTool/prompt.ts` | EnterPlanModeTool prompt/schema |
| `source/src/tools/ExitPlanModeTool/ExitPlanModeV2Tool.ts` | 退出计划模式工具 |
| `source/src/tools/ExitPlanModeTool/UI.tsx` | ExitPlanModeTool UI |
| `source/src/tools/ExitPlanModeTool/constants.ts` | ExitPlanModeTool 常量 |
| `source/src/tools/ExitPlanModeTool/prompt.ts` | ExitPlanModeTool prompt/schema |
| `source/src/tools/EnterWorktreeTool/EnterWorktreeTool.ts` | 进入 worktree 工具 |
| `source/src/tools/EnterWorktreeTool/UI.tsx` | EnterWorktreeTool UI |
| `source/src/tools/EnterWorktreeTool/constants.ts` | EnterWorktreeTool 常量 |
| `source/src/tools/EnterWorktreeTool/prompt.ts` | EnterWorktreeTool prompt/schema |
| `source/src/tools/ExitWorktreeTool/ExitWorktreeTool.ts` | 退出 worktree 工具 |
| `source/src/tools/ExitWorktreeTool/UI.tsx` | ExitWorktreeTool UI |
| `source/src/tools/ExitWorktreeTool/constants.ts` | ExitWorktreeTool 常量 |
| `source/src/tools/ExitWorktreeTool/prompt.ts` | ExitWorktreeTool prompt/schema |

---

## 9.7 文件工具家族（读/写/改/Notebook）

### FileEditTool

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/FileEditTool/FileEditTool.ts` | 精确文本编辑工具主实现 |
| `source/src/tools/FileEditTool/UI.tsx` | FileEditTool UI |
| `source/src/tools/FileEditTool/constants.ts` | FileEditTool 常量 |
| `source/src/tools/FileEditTool/prompt.ts` | FileEditTool prompt/schema |
| `source/src/tools/FileEditTool/types.ts` | FileEditTool 类型定义 |
| `source/src/tools/FileEditTool/utils.ts` | FileEditTool 辅助逻辑 |

### FileReadTool

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/FileReadTool/FileReadTool.ts` | 文件读取工具主实现（文本/图像/PDF/notebook） |
| `source/src/tools/FileReadTool/UI.tsx` | FileReadTool UI |
| `source/src/tools/FileReadTool/imageProcessor.ts` | 图像读取/压缩/缩放辅助 |
| `source/src/tools/FileReadTool/limits.ts` | 文件读取大小/token 限制 |
| `source/src/tools/FileReadTool/prompt.ts` | FileReadTool prompt/schema |

### FileWriteTool

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/FileWriteTool/FileWriteTool.ts` | 文件写入工具主实现 |
| `source/src/tools/FileWriteTool/UI.tsx` | FileWriteTool UI |
| `source/src/tools/FileWriteTool/prompt.ts` | FileWriteTool prompt/schema |

### NotebookEditTool

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/NotebookEditTool/NotebookEditTool.ts` | notebook 编辑工具主实现 |
| `source/src/tools/NotebookEditTool/UI.tsx` | NotebookEditTool UI |
| `source/src/tools/NotebookEditTool/constants.ts` | NotebookEditTool 常量 |
| `source/src/tools/NotebookEditTool/prompt.ts` | NotebookEditTool prompt/schema |

---

## 9.8 搜索 / 匹配 / 语言服务工具家族

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/GlobTool/GlobTool.ts` | 文件 glob 匹配工具 |
| `source/src/tools/GlobTool/UI.tsx` | GlobTool UI |
| `source/src/tools/GlobTool/prompt.ts` | GlobTool prompt/schema |
| `source/src/tools/GrepTool/GrepTool.ts` | 文本 grep 搜索工具 |
| `source/src/tools/GrepTool/UI.tsx` | GrepTool UI |
| `source/src/tools/GrepTool/prompt.ts` | GrepTool prompt/schema |
| `source/src/tools/LSPTool/LSPTool.ts` | LSP 查询/符号/语言服务工具主实现 |
| `source/src/tools/LSPTool/UI.tsx` | LSPTool UI |
| `source/src/tools/LSPTool/formatters.ts` | LSP 输出格式化 |
| `source/src/tools/LSPTool/prompt.ts` | LSPTool prompt/schema |
| `source/src/tools/LSPTool/schemas.ts` | LSPTool schema 定义 |
| `source/src/tools/LSPTool/symbolContext.ts` | LSP 符号上下文辅助 |

---

## 9.9 MCP 资源与 MCP 调用工具家族

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/MCPTool/MCPTool.ts` | MCP tool wrapper 主实现 |
| `source/src/tools/MCPTool/UI.tsx` | MCPTool UI |
| `source/src/tools/MCPTool/classifyForCollapse.ts` | MCP 结果用于 collapse/摘要分类辅助 |
| `source/src/tools/MCPTool/prompt.ts` | MCPTool prompt/schema |
| `source/src/tools/McpAuthTool/McpAuthTool.ts` | MCP 认证修复工具 |
| `source/src/tools/ListMcpResourcesTool/ListMcpResourcesTool.ts` | 列出 MCP resources 的工具 |
| `source/src/tools/ListMcpResourcesTool/UI.tsx` | ListMcpResourcesTool UI |
| `source/src/tools/ListMcpResourcesTool/prompt.ts` | ListMcpResourcesTool prompt/schema |
| `source/src/tools/ReadMcpResourceTool/ReadMcpResourceTool.ts` | 读取 MCP resource 的工具 |
| `source/src/tools/ReadMcpResourceTool/UI.tsx` | ReadMcpResourceTool UI |
| `source/src/tools/ReadMcpResourceTool/prompt.ts` | ReadMcpResourceTool prompt/schema |

---

## 9.10 PowerShellTool 家族

这是 Windows/PowerShell 对应的 shell 工具体系，和 BashTool 对位。

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/PowerShellTool/PowerShellTool.tsx` | PowerShellTool 主实现 |
| `source/src/tools/PowerShellTool/UI.tsx` | PowerShellTool UI |
| `source/src/tools/PowerShellTool/clmTypes.ts` | CLM（Constrained Language Mode）相关类型/常量 |
| `source/src/tools/PowerShellTool/commandSemantics.ts` | PowerShell 命令语义分析 |
| `source/src/tools/PowerShellTool/commonParameters.ts` | 常见参数处理 |
| `source/src/tools/PowerShellTool/destructiveCommandWarning.ts` | 危险命令警告 |
| `source/src/tools/PowerShellTool/gitSafety.ts` | git 安全辅助逻辑 |
| `source/src/tools/PowerShellTool/modeValidation.ts` | 模式校验 |
| `source/src/tools/PowerShellTool/pathValidation.ts` | 路径安全校验 |
| `source/src/tools/PowerShellTool/powershellPermissions.ts` | PowerShell 权限判定 |
| `source/src/tools/PowerShellTool/powershellSecurity.ts` | PowerShell 安全分析 |
| `source/src/tools/PowerShellTool/prompt.ts` | PowerShellTool prompt/schema |
| `source/src/tools/PowerShellTool/readOnlyValidation.ts` | 只读命令识别与校验 |
| `source/src/tools/PowerShellTool/toolName.ts` | 工具名/常量 |

---

## 9.11 REPL / 远程触发 / Synthetic 特殊工具

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/REPLTool/constants.ts` | REPLTool 相关常量 |
| `source/src/tools/REPLTool/primitiveTools.ts` | REPL 模式下 primitive tools 映射/隐藏逻辑 |
| `source/src/tools/RemoteTriggerTool/RemoteTriggerTool.ts` | 远程触发工具 |
| `source/src/tools/RemoteTriggerTool/UI.tsx` | RemoteTriggerTool UI |
| `source/src/tools/RemoteTriggerTool/prompt.ts` | RemoteTriggerTool prompt/schema |
| `source/src/tools/SyntheticOutputTool/SyntheticOutputTool.ts` | 合成输出工具，用于协调/包装非真实执行输出 |
| `source/src/tools/SleepTool/prompt.ts` | SleepTool 的 prompt/schema（实际执行逻辑可能在别处或特性门控下） |

---

## 9.12 任务 / team / message / cron / skill 工具家族

### ScheduleCronTool

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/ScheduleCronTool/CronCreateTool.ts` | 创建 cron 任务工具 |
| `source/src/tools/ScheduleCronTool/CronDeleteTool.ts` | 删除 cron 任务工具 |
| `source/src/tools/ScheduleCronTool/CronListTool.ts` | 列出 cron 任务工具 |
| `source/src/tools/ScheduleCronTool/UI.tsx` | ScheduleCronTool 结果 UI |
| `source/src/tools/ScheduleCronTool/prompt.ts` | Cron 工具家族 prompt/schema |

### SendMessageTool

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/SendMessageTool/SendMessageTool.ts` | 发送消息/agent 间消息工具 |
| `source/src/tools/SendMessageTool/UI.tsx` | SendMessageTool UI |
| `source/src/tools/SendMessageTool/constants.ts` | SendMessageTool 常量 |
| `source/src/tools/SendMessageTool/prompt.ts` | SendMessageTool prompt/schema |

### SkillTool

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/SkillTool/SkillTool.ts` | 调用/列出技能相关工具 |
| `source/src/tools/SkillTool/UI.tsx` | SkillTool UI |
| `source/src/tools/SkillTool/constants.ts` | SkillTool 常量 |
| `source/src/tools/SkillTool/prompt.ts` | SkillTool prompt/schema |

### Task 工具组

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/TaskCreateTool/TaskCreateTool.ts` | 创建任务工具 |
| `source/src/tools/TaskCreateTool/constants.ts` | TaskCreateTool 常量 |
| `source/src/tools/TaskCreateTool/prompt.ts` | TaskCreateTool prompt/schema |
| `source/src/tools/TaskGetTool/TaskGetTool.ts` | 获取单个任务工具 |
| `source/src/tools/TaskGetTool/constants.ts` | TaskGetTool 常量 |
| `source/src/tools/TaskGetTool/prompt.ts` | TaskGetTool prompt/schema |
| `source/src/tools/TaskListTool/TaskListTool.ts` | 列出任务工具 |
| `source/src/tools/TaskListTool/constants.ts` | TaskListTool 常量 |
| `source/src/tools/TaskListTool/prompt.ts` | TaskListTool prompt/schema |
| `source/src/tools/TaskOutputTool/TaskOutputTool.tsx` | 任务输出查看工具 |
| `source/src/tools/TaskOutputTool/constants.ts` | TaskOutputTool 常量 |
| `source/src/tools/TaskStopTool/TaskStopTool.ts` | 停止任务工具 |
| `source/src/tools/TaskStopTool/UI.tsx` | TaskStopTool UI |
| `source/src/tools/TaskStopTool/prompt.ts` | TaskStopTool prompt/schema |
| `source/src/tools/TaskUpdateTool/TaskUpdateTool.ts` | 更新任务工具 |
| `source/src/tools/TaskUpdateTool/constants.ts` | TaskUpdateTool 常量 |
| `source/src/tools/TaskUpdateTool/prompt.ts` | TaskUpdateTool prompt/schema |

### Team 工具组

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/TeamCreateTool/TeamCreateTool.ts` | 创建 team / teammate 工具 |
| `source/src/tools/TeamCreateTool/UI.tsx` | TeamCreateTool UI |
| `source/src/tools/TeamCreateTool/constants.ts` | TeamCreateTool 常量 |
| `source/src/tools/TeamCreateTool/prompt.ts` | TeamCreateTool prompt/schema |
| `source/src/tools/TeamDeleteTool/TeamDeleteTool.ts` | 删除 team / teammate 工具 |
| `source/src/tools/TeamDeleteTool/UI.tsx` | TeamDeleteTool UI |
| `source/src/tools/TeamDeleteTool/constants.ts` | TeamDeleteTool 常量 |
| `source/src/tools/TeamDeleteTool/prompt.ts` | TeamDeleteTool prompt/schema |

### Todo / Tool Search

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/TodoWriteTool/TodoWriteTool.ts` | 写入/更新 todo 列表工具 |
| `source/src/tools/TodoWriteTool/constants.ts` | TodoWriteTool 常量 |
| `source/src/tools/TodoWriteTool/prompt.ts` | TodoWriteTool prompt/schema |
| `source/src/tools/ToolSearchTool/ToolSearchTool.ts` | 搜索可用工具的工具 |
| `source/src/tools/ToolSearchTool/constants.ts` | ToolSearchTool 常量 |
| `source/src/tools/ToolSearchTool/prompt.ts` | ToolSearchTool prompt/schema |

---

## 9.13 WebFetch / WebSearch 工具家族

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/WebFetchTool/WebFetchTool.ts` | 网页抓取工具主实现 |
| `source/src/tools/WebFetchTool/UI.tsx` | WebFetchTool UI |
| `source/src/tools/WebFetchTool/preapproved.ts` | WebFetch 的预批准/预授权规则 |
| `source/src/tools/WebFetchTool/prompt.ts` | WebFetchTool prompt/schema |
| `source/src/tools/WebFetchTool/utils.ts` | WebFetchTool 辅助函数 |
| `source/src/tools/WebSearchTool/WebSearchTool.ts` | Web 搜索工具主实现 |
| `source/src/tools/WebSearchTool/UI.tsx` | WebSearchTool UI |
| `source/src/tools/WebSearchTool/prompt.ts` | WebSearchTool prompt/schema |

---

## 10. services/tools/** 文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/tools/StreamingToolExecutor.ts` | 流式工具执行队列管理与结果产出排序 |
| `source/src/services/tools/toolExecution.ts` | 单次 tool_use 的完整执行流水线 |
| `source/src/services/tools/toolHooks.ts` | 工具 hooks 的执行与结果桥接 |
| `source/src/services/tools/toolOrchestration.ts` | 非流式工具批处理执行编排 |

---

## 11. shared / testing / utilities 文件职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/shared/gitOperationTracking.ts` | 跟踪工具引发的 git 操作/变更 |
| `source/src/tools/shared/spawnMultiAgent.ts` | 多 agent 工具共享的 spawn 调度逻辑 |
| `source/src/tools/testing/TestingPermissionTool.tsx` | 测试权限判断和权限 UI 的测试工具 |
| `source/src/tools/utils.ts` | 工具层通用辅助函数 |

---

## 12. 工具系统模块的关键设计结论

### 结论 1：工具系统不是工具文件集合，而是一整套平台

它至少由这几层组成：
- 协议层
- 注册组合层
- 执行编排层
- 工具家族实现层
- 共用辅助层

所以不能只把它理解成“很多 Tool.ts 文件”。

---

### 结论 2：`Tool.ts` + `tools.ts` + `services/tools/**` 才是主骨架

如果只看具体 BashTool / FileReadTool，会看到局部实现；
但真正定义工具系统运行方式的是：

- `Tool.ts`
- `tools.ts`
- `toolExecution.ts`
- `StreamingToolExecutor.ts`

---

### 结论 3：工具池是“当前上下文下的能力面”，不是静态全集

工具是否可见，会被这些因素影响：
- permission context
- deny rules
- feature gates
- REPL mode
- coordinator mode
- async agent mode
- MCP tools 是否存在

也就是说，工具池是动态装配的。

---

### 结论 4：工具执行不是一次函数调用，而是完整状态机

一次 tool_use 可能涉及：
- 输入 schema parse
- validateInput
- pre hooks
- permission ask/allow/deny
- 实际执行
- progress updates
- post hooks
- tool_result 映射
- attachment/contextModifier 回流

所以工具执行器本身就是子系统。

---

### 结论 5：工具家族分工非常清晰

当前可以看出工具系统至少有这些能力簇：
- shell 工具
- 文件工具
- 搜索工具
- LSP 工具
- MCP 工具
- agent/task/team 工具
- plan/worktree/config/skill 工具
- web 工具
- 特殊 synthetic/testing 工具

---

## 13. 当前文档的覆盖边界说明

这份文档已经尽量满足你的要求：

- 有**工具系统完整子架构图**
- 有**动态流程图**
- 有**相对路径总索引**
- 有**核心文件详细说明**
- 有这个功能块所有涉及文件的**逐文件作用总结**

说明一下结构：

### 第一层：核心骨架文件 = 详细说明
- `Tool.ts`
- `tools.ts`
- `constants/tools.ts`
- `services/tools/**`

### 第二层：各工具家族文件 = 逐文件职责摘要
- `tools/**` 下全部文件按家族总结

如果你后面要更细，我还能继续把某一大工具家族（比如 `AgentTool/**` / `BashTool/**`）再拆成单独一份更细的深度文档。

---

## 14. 当前子功能块输出结果

本轮已完成：
- **工具系统模块完整子架构图**
- **工具系统动态流程图**
- **工具系统相对路径总索引**
- **核心文件详细职责说明**
- **该功能块所有涉及文件的逐文件作用总结**

已保存到：
- `cc/cc_learn/15_arch_tool_system_framework.md`

---

## 15. 下一步建议

按当前顺序，最自然的下一个功能块应该是：

### Agent 主循环模块
建议文件名：
- `cc/cc_learn/16_arch_query_loop_framework.md`

因为：
- 命令系统 = 高层入口
- 工具系统 = 底层能力面
- 下一层就应该是：
  **它们如何在 query.ts 里被模型驱动、串成完整 agent 循环**

下一份我建议继续做：

> **Agent 主循环模块的完整架构图 + 相对路径索引 + 所有涉及文件职责总结**
