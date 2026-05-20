# Claude Code 总体架构总图（第一版）

- 仓库路径：`cc/claude_code`
- 输出目标：先给出**整体框架流程图 / 总体功能架构图**
- 当前文件定位：`cc_learn` 中的**总入口总图文档**，后续各功能分图都会从这里继续展开
- 对应需求：
  - 先完成整体框架图
  - 要求清晰、包含所有功能结构
  - 后续再按功能分别细拆全部架构图、相对路径索引、逐文件职责说明

---

## 1. 这份文档要解决什么问题

你现在已经在 `cc_learn/` 下积累了很多“模块分析文档”，但缺一个真正能总览全仓的：

1. **全局功能分层图**
2. **主执行链总流程图**
3. **系统级模块关系图**
4. **从启动到 query 到 tool/command/MCP/memory/config 的闭环图**

这份文档先不追求“每个子目录都讲透”，而是先把：

> **Claude Code 这个仓库，整体上到底是一台怎样运作的机器**

画清楚。

---

## 2. 一句话总览

Claude Code 的外表是一个 CLI / TUI 工具，但它的真实内核更像是一个：

> **本地可运行的 Agent Runtime 平台**

它由以下几层组成：

- 启动与模式分流层
- 运行态全局状态与设置/配置注入层
- 命令系统层
- 工具系统层
- Agent 主循环层
- 模型/API/认证层
- 上下文治理与恢复层
- 记忆/附件/会话恢复层
- MCP 扩展平台层
- 插件 / skills / workflows 生态层
- 多 Agent / task / teammate / remote 层
- TUI / AppState / 交互界面层
- 诊断 / 日志 / 遥测 / 安全策略层

---

## 3. 总体功能架构图（静态分层图）

下面这张图先回答：**系统有哪些层，它们怎么叠在一起。**

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Claude Code 整体系统                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ① 入口 / 启动 / 模式分流层                                                 │
│    entrypoints/cli.tsx, main.tsx, init.ts, setup.ts, replLauncher.tsx      │
│    - fast path 分流                                                         │
│    - 初始化 config / telemetry / trust / cwd / session                     │
│    - 进入 interactive REPL 或 headless query                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ② 运行态状态 / 配置 / 设置 / 认证注入层                                    │
│    bootstrap/state.ts, config.ts, settings.ts, auth.ts, api/client.ts      │
│    - global state                                                           │
│    - settings 多源合并                                                     │
│    - config 持久化                                                         │
│    - OAuth / API key / Bedrock / Vertex / Foundry                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            │                       │                       │
            ▼                       ▼                       ▼
┌───────────────────────┐  ┌───────────────────────┐  ┌────────────────────────┐
│ ③ 命令系统层          │  │ ④ 工具系统层          │  │ ⑤ TUI / 状态界面层      │
│ commands.ts           │  │ tools.ts, Tool.ts     │  │ components/**           │
│ commands/**           │  │ tools/**              │  │ state/**, screens/**    │
│ skills/**             │  │ services/tools/**     │  │ ink/**                  │
│ plugins command path  │  │ MCP tools merge       │  │ Settings / dialogs /    │
│ - slash commands      │  │ - ToolDef 协议        │  │ REPL / onboarding       │
│ - prompt commands     │  │ - 权限 / hook / exec  │  │                        │
│ - local / local-jsx   │  │ - streaming executor  │  │                        │
└───────────────────────┘  └───────────────────────┘  └────────────────────────┘
            │                       │
            └───────────────┬───────┘
                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ⑥ Agent 主循环层                                                           │
│    query.ts, query/config.ts, query/deps.ts                                │
│    - 组装 prompt/messages/tools/commands/context                            │
│    - 调模型 streaming API                                                  │
│    - 收 assistant / tool_use / tool_result                                 │
│    - 决定下一轮是否继续                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────────────┐  ┌───────────────────────┐  ┌────────────────────────┐
│ ⑦ 模型/API/重试层     │  │ ⑧ 上下文治理层        │  │ ⑨ 记忆/附件/恢复层      │
│ services/api/claude.ts│  │ compact/**            │  │ attachments.ts         │
│ withRetry.ts          │  │ tokenBudget.ts        │  │ sessionStorage.ts      │
│ errors.ts             │  │ stopHooks.ts          │  │ SessionMemory/**       │
│ logging.ts            │  │ microCompact.ts       │  │ memdir/paths.ts        │
│ - 请求构造            │  │ - auto/reactive compact│ │ - transcript / resume   │
│ - stream parse        │  │ - history snip        │  │ - memory prefetch       │
│ - fallback / retry    │  │ - continuation budget │  │ - attachment injection  │
└───────────────────────┘  └───────────────────────┘  └────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ⑩ 扩展平台层                                                               │
│    services/mcp/**, plugins/**, skills/**, workflows/**                    │
│    - MCP servers / prompts / resources / skills                             │
│    - plugins / bundled skills / builtin plugins                             │
│    - workflows / dynamic skills / project skills                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ⑪ 多 Agent / Task / Remote 协作层                                          │
│    AgentTool/**, tasks/**, assistant/**, bridge/**, remote/**, server/**   │
│    - subagent / teammate / coordinator                                      │
│    - background task / messaging / remote session                           │
│    - bridge / ssh / direct-connect / cowork                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ⑫ 基础设施与共用工具层                                                     │
│    utils/**, constants/**, types/**, schemas/**, native-ts/**              │
│    - path/fs/git/messages/token/schema/env                                  │
│    - 供所有上层复用                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 整体主流程图（动态运行图）

这张图回答：**系统启动之后，一次完整任务是怎么跑完的。**

```text
用户启动 Claude Code / 输入任务
        │
        ▼
[entrypoints/cli.tsx]
  - argv fast-path 分流
  - 简单命令直接处理
  - 复杂路径懒加载 main.tsx
        │
        ▼
[main.tsx]
  - 初始化主命令/模式
  - 调 init.ts / setup.ts
  - 决定 interactive 或 headless
        │
        ▼
[init.ts + setup.ts]
  - enableConfigs
  - safe env -> full env
  - trust / onboarding / hooks / cwd / projectRoot / session
  - worktree / tmux / messaging / watchers / prefetch
        │
        ▼
[构建运行时基础输入]
  - settings.ts 合并 settings
  - config.ts 读取 global/project config
  - auth.ts / api/client.ts 建立 auth/provider 状态
  - commands.ts 生成命令池
  - tools.ts + MCP 生成工具池
  - context.ts 生成 system/user context
        │
        ▼
[进入 REPL / Headless 执行]
        │
        ▼
[query.ts]
  - 准备 messages + system prompt + contexts + tools
  - 执行上下文治理：snip / microcompact / autoCompact / collapse
  - 调 services/api/claude.ts 发起模型请求
        │
        ▼
[services/api/claude.ts]
  - 构造 API params
  - 注入 model/provider/auth/tool schemas/cache strategy
  - streaming 接收 assistant blocks
        │
        ├──────────────► 若出现可恢复错误
        │                 - withRetry.ts
        │                 - prompt-too-long / media / max_tokens recovery
        │                 - fallback / retry / cooldown / compact retry
        │
        ▼
[assistant message / tool_use 到达]
        │
        ▼
[services/tools/StreamingToolExecutor.ts]
  - 调度工具
  - runToolUse -> toolExecution.ts
  - pre/post hooks + permission + progress + tool_result
        │
        ├──────────────► 若调用 MCP 工具
        │                 - services/mcp/client.ts
        │                 - connect/call/retry/auth/large output persistence
        │
        ▼
[工具结果回灌]
  - tool_result messages
  - file/plan/agent/deferred-tool/memory attachments
  - SessionMemory / relevant memory prefetch
        │
        ▼
[query.ts 决策]
  - 还需要继续吗？
  - stopHooks / tokenBudget / continuation
  - 若需要 -> 下一轮 queryLoop
  - 若结束 -> transcript / config / memory / telemetry 落盘
        │
        ▼
任务完成 / 会话继续等待下一次输入
```

---

## 5. 顶层框架总图（按“数据流 + 控制流”合并）

这张图把最重要的主链和外围子系统合并到一张“大图”里。

```text
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                                         用户 / CLI / UI                                   │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ 入口层：entrypoints/cli.tsx -> main.tsx -> init.ts / setup.ts / interactiveHelpers.tsx   │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                                              │
          ┌───────────────────────────────────┼───────────────────────────────────┐
          │                                   │                                   │
          ▼                                   ▼                                   ▼
┌──────────────────────┐         ┌────────────────────────┐         ┌────────────────────────┐
│ 配置/设置/认证层     │         │ 命令池构建             │         │ 工具池构建             │
│ config.ts            │         │ commands.ts            │         │ tools.ts               │
│ settings.ts          │         │ skills/loadSkillsDir   │         │ Tool.ts                │
│ auth.ts              │         │ plugin commands        │         │ services/tools/**      │
│ api/client.ts        │         │ MCP prompts/skills     │         │ MCP tools              │
└──────────────────────┘         └────────────────────────┘         └────────────────────────┘
          │                                   │                                   │
          └───────────────────────────────────┴───────────────────────────────────┘
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   Agent 主循环：query.ts                                 │
│  - messages / contexts / tools / commands / permissions                                  │
│  - continuation / transition / tool summaries                                            │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                                              │
            ┌─────────────────────────────────┼─────────────────────────────────┐
            │                                 │                                 │
            ▼                                 ▼                                 ▼
┌────────────────────────┐       ┌────────────────────────┐       ┌──────────────────────────┐
│ 模型/API 层            │       │ 上下文治理/恢复层      │       │ 记忆/会话恢复层           │
│ services/api/claude.ts │       │ compact/**             │       │ sessionStorage.ts        │
│ withRetry.ts           │       │ autoCompact.ts         │       │ attachments.ts           │
│ errors.ts/logging.ts   │       │ microCompact.ts        │       │ SessionMemory/**         │
│                        │       │ tokenBudget.ts         │       │ memdir/paths.ts          │
│                        │       │ stopHooks.ts           │       │                          │
└────────────────────────┘       └────────────────────────┘       └──────────────────────────┘
            │                                 │                                 │
            └─────────────────────────────────┴─────────────────────────────────┘
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                               工具执行 / 外部能力接入层                                   │
│ services/tools/toolExecution.ts / StreamingToolExecutor.ts / toolOrchestration.ts         │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                                              │
        ┌─────────────────────────────────────┼──────────────────────────────────────┐
        │                                     │                                      │
        ▼                                     ▼                                      ▼
┌──────────────────────┐        ┌────────────────────────┐          ┌────────────────────────┐
│ 本地工具             │        │ MCP 平台               │          │ 插件 / skills / team   │
│ Bash/File/Web/Grep   │        │ services/mcp/**        │          │ plugins/** skills/**   │
│ Notebook/LSP/etc     │        │ tools/prompts/resources│          │ tasks/** AgentTool/**  │
└──────────────────────┘        └────────────────────────┘          └────────────────────────┘
        │                                     │                                      │
        └─────────────────────────────────────┴──────────────────────────────────────┘
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                                结果回流到 query.ts 下一轮                                │
│   tool_result / attachments / memory / delta messages / stop hooks / budget decisions    │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 总体模块树（功能结构清单）

下面把“所有功能结构”先按一级功能树列出来，方便后续逐块出图。

```text
Claude Code
├── A. 启动与入口分流
│   ├── CLI entrypoint
│   ├── main runtime bootstrap
│   ├── trust / onboarding / interactive boot
│   ├── worktree / tmux / session startup
│   └── REPL / headless mode dispatch
│
├── B. 运行态状态、配置、设置、认证
│   ├── bootstrap state
│   ├── global config / project config
│   ├── settings merge
│   ├── auth sources / OAuth / API key helpers
│   ├── provider client creation
│   └── model / provider capability injection
│
├── C. 命令系统
│   ├── builtin slash commands
│   ├── prompt commands
│   ├── local commands
│   ├── local-jsx commands
│   ├── bundled skills
│   ├── project/user skills
│   ├── plugin commands / plugin skills
│   ├── workflow commands
│   └── MCP prompts / MCP skills
│
├── D. 工具系统
│   ├── Tool protocol
│   ├── built-in tools registry
│   ├── permission-aware tool filtering
│   ├── streaming tool executor
│   ├── tool hooks / progress / result mapping
│   ├── file tools
│   ├── shell tools
│   ├── web/search tools
│   ├── task/agent/team tools
│   ├── worktree/plan/memory tools
│   └── MCP tools
│
├── E. Agent 主循环
│   ├── query loop
│   ├── messages/systemPrompt/context assembly
│   ├── model streaming receive
│   ├── tool_use orchestration
│   ├── continuation / turn transition
│   └── terminal completion
│
├── F. 模型/API/重试
│   ├── API request compilation
│   ├── streaming / non-streaming fallback
│   ├── retry / timeout / watchdog
│   ├── error mapping
│   ├── usage / cost / telemetry
│   └── fallback model logic
│
├── G. 上下文治理与恢复
│   ├── token warning / blocking threshold
│   ├── auto compact
│   ├── microcompact
│   ├── reactive compact
│   ├── context collapse
│   ├── history snip
│   ├── stop hooks
│   └── token budget continuation
│
├── H. 记忆、附件、会话恢复
│   ├── transcript persistence
│   ├── session metadata persistence
│   ├── resume / continue / subagent transcript load
│   ├── attachment messages
│   ├── session memory
│   ├── relevant memory prefetch
│   └── auto-memory path & storage
│
├── I. MCP 平台
│   ├── MCP config merge / policy / approval
│   ├── transport connection runtime
│   ├── tools import
│   ├── prompts import
│   ├── resources import
│   ├── skill import
│   ├── needs-auth / reconnect / session expiry
│   └── MCP tool call pipeline
│
├── J. 插件 / Skills / Workflows 生态
│   ├── plugin loading
│   ├── builtin plugins
│   ├── plugin commands
│   ├── plugin skills
│   ├── bundled skills
│   ├── project skills / dynamic skills
│   └── workflow-driven commands
│
├── K. 多 Agent / Task / Remote
│   ├── AgentTool / teammate / coordinator
│   ├── tasks / task summaries / task state
│   ├── background sessions
│   ├── assistant mode
│   ├── bridge / remote-control
│   ├── remote sessions / cowork / CCR
│   └── server / direct-connect / ssh integration
│
├── L. TUI / 交互层
│   ├── Ink app shell
│   ├── REPL
│   ├── Settings / Config / Status UI
│   ├── Plugin / MCP manager UI
│   ├── dialogs / onboarding / trust
│   └── state/app store
│
└── M. 基础设施与诊断
    ├── utils / messages / path / fs / git
    ├── constants / schemas / types
    ├── diagnostics / logging / analytics
    ├── telemetry / tracing / gateway detection
    └── native-ts / vendor / platform glue
```

---

## 7. 系统主骨架：最关键的中枢文件

如果只看全仓最关键的一组“骨架文件”，当前可以归纳为：

| 角色 | 核心文件 | 作用 |
|---|---|---|
| 真实入口 | `source/src/entrypoints/cli.tsx` | 启动分流 |
| 总调度器 | `source/src/main.tsx` | 初始化与模式路由 |
| 命令中枢 | `source/src/commands.ts` | 统一命令聚合 |
| 工具中枢 | `source/src/tools.ts` | 统一工具聚合 |
| 工具协议 | `source/src/Tool.ts` | Tool 定义与上下文协议 |
| Agent 内核 | `source/src/query.ts` | 主循环状态机 |
| API 运行时 | `source/src/services/api/claude.ts` | 模型请求与流解析 |
| provider client | `source/src/services/api/client.ts` | 底层 client/provider 构造 |
| 上下文治理 | `source/src/services/compact/compact.ts` | full compact 核心 |
| transcript 持久化 | `source/src/utils/sessionStorage.ts` | 会话恢复基础设施 |
| MCP 配置中枢 | `source/src/services/mcp/config.ts` | MCP 来源与策略合并 |
| MCP 运行时中枢 | `source/src/services/mcp/client.ts` | MCP 连接与工具导入 |
| 认证中枢 | `source/src/utils/auth.ts` | auth source/refresh/state machine |
| settings 中枢 | `source/src/utils/settings/settings.ts` | 多源 settings 合并 |
| config 中枢 | `source/src/utils/config.ts` | 本地 config 持久层 |

### 最核心的一句话

当前全仓最重要的结构主轴，仍然可以概括为：

```text
main.tsx + query.ts + tools.ts + commands.ts
```

但如果扩展成真正完整的运行骨架，更准确的版本是：

```text
entrypoints/cli.tsx
  -> main.tsx
  -> config/settings/auth/api-client
  -> commands.ts + tools.ts
  -> query.ts
  -> services/api/claude.ts + services/tools/**
  -> compact/sessionStorage/memory/mcp
```

---

## 8. 全局主循环闭环图（最值得记住的一张图）

如果你只想记住一张“这个仓库怎么运作”的图，我认为应该是下面这张：

```text
             ┌─────────────────────────────┐
             │      用户输入 / 命令触发      │
             └──────────────┬──────────────┘
                            │
                            ▼
             ┌─────────────────────────────┐
             │  main.tsx 初始化运行环境     │
             │  config/settings/auth/tools  │
             │  commands/MCP/memory         │
             └──────────────┬──────────────┘
                            │
                            ▼
             ┌─────────────────────────────┐
             │        query.ts 主循环       │
             │  装配 messages + context     │
             └──────────────┬──────────────┘
                            │
                            ▼
             ┌─────────────────────────────┐
             │ services/api/claude.ts      │
             │ 发模型请求并流式收结果       │
             └──────────────┬──────────────┘
                            │
            ┌───────────────┴────────────────┐
            │                                │
            ▼                                ▼
┌─────────────────────────────┐  ┌─────────────────────────────┐
│ assistant 普通输出           │  │ assistant tool_use          │
└──────────────┬──────────────┘  └──────────────┬──────────────┘
               │                                │
               │                                ▼
               │              ┌────────────────────────────────┐
               │              │ toolExecution / MCP / hooks    │
               │              │ permissions / progress         │
               │              └────────────────┬───────────────┘
               │                               │
               │                               ▼
               │              ┌────────────────────────────────┐
               │              │ tool_result / attachments /    │
               │              │ memory / delta messages        │
               │              └────────────────┬───────────────┘
               │                               │
               └───────────────┬───────────────┘
                               ▼
              ┌──────────────────────────────────┐
              │ query.ts 决定是否继续下一轮       │
              │ compact / retry / stopHooks /    │
              │ tokenBudget / recovery           │
              └────────────────┬─────────────────┘
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
                 ▼                           ▼
   ┌──────────────────────────┐   ┌──────────────────────────┐
   │ 继续下一轮 queryLoop      │   │ 本轮结束 / transcript落盘 │
   └──────────────────────────┘   └──────────────────────────┘
```

---

## 9. 当前整体图覆盖到了哪些功能

这份“总图”已经明确纳入了当前已分析过的核心功能结构：

- 启动与入口分流
- 命令系统
- 工具系统
- Agent 主循环
- 上下文治理与恢复
- memory / attachment / session restore
- MCP 集成
- 模型 / 认证 / 配置注入

也就是说，它已经覆盖了目前 `cc_learn/` 中已完成的大模块主分析成果。

---

## 10. 当前还没有在这份图里展开到“逐子系统细图”的部分

虽然总图已经能用，但还没有细拆到以下层级：

1. `commands/**` 每个功能子树的详细结构图
2. `tools/**` 每个工具族的详细结构图
3. `plugins/**` / `skills/**` / `tasks/**` / `remote/**` 的详细结构图
4. `components/**` / `state/**` / `screens/**` 的 UI 子系统图
5. `utils/model/**`、`services/oauth/**`、`mcp/auth.ts` 等细分支图
6. “功能 -> ts/tsx 相对路径索引 -> 每个文件职责”的完整总表

这些都会是下一阶段要做的内容。

---

## 11. 推荐的下一步拆图顺序

既然你要求：
- 先画整体框架图
- 然后再分别根据功能，把所有功能涉及的架构图全部画出来
- 并且整理相对路径索引、逐文件作用

那我建议后续按下面顺序推进：

### 第一批：最重要的功能分图
1. **启动与入口分流总图**
2. **命令系统总图**
3. **工具系统总图**
4. **Agent 主循环总图**
5. **MCP 集成总图**

### 第二批：主循环外围
6. **模型/API/认证/Provider 总图**
7. **上下文治理/compact/retry 总图**
8. **memory / attachment / session restore 总图**

### 第三批：生态与扩展
9. **plugins / skills / workflows 总图**
10. **tasks / agent / teammate / remote 总图**
11. **TUI / state / screens / settings UI 总图**

### 第四批：最终落地文档
12. **每个功能的相对路径索引文件**
13. **每个功能的逐文件职责说明**
14. **最终 coverage audit 总表**

---

## 12. 本文件与现有文档的关系

这份总图文档不是替代你当前已有的模块分析，而是它们的“目录页 / 总地图”。

当前它主要汇总并承接：

- `00_stageA_stageB_global_scan.md`
- `02_module_startup_entry.md`
- `03_module_command_system.md`
- `04_module_tool_system.md`
- `05_module_query_loop.md`
- `06_module_context_governance_and_retry.md`
- `07_module_memory_attachment_session_restore.md`
- `08_module_mcp_integration.md`
- `09_module_model_auth_config_injection.md`

换句话说：

> 这份文档是当前 `cc_learn` 的“总体架构首页”。

---

## 13. 当前结论

如果用最简洁但准确的话来概括 Claude Code：

> 它不是一个“命令行聊天工具”，而是一个由 `main.tsx + query.ts` 驱动、用 `commands.ts + tools.ts` 暴露能力、再由 `config/settings/auth/api/mcp/sessionStorage` 提供运行底座的本地 Agent Runtime 平台。

而这份文档完成的工作是：

- 把这个平台的**整体层次**画清楚了
- 把它的**主执行链**画清楚了
- 把它的**功能结构树**画清楚了
- 为下一步“分功能逐张细图 + 文件索引 + 逐文件职责”打好了基线

---

## 14. 输出文件

- 当前总图文件：`cc/cc_learn/12_overall_architecture_framework.md`

后续建议新增的图文文件命名（草案）：

- `13_arch_startup_entry_framework.md`
- `14_arch_command_system_framework.md`
- `15_arch_tool_system_framework.md`
- `16_arch_query_loop_framework.md`
- `17_arch_mcp_framework.md`
- `18_arch_model_auth_config_framework.md`
- `19_arch_memory_attachment_resume_framework.md`
- `20_arch_plugins_skills_workflows_framework.md`
- `21_arch_tasks_agents_remote_framework.md`
- `22_arch_tui_state_ui_framework.md`

---

## 15. 本轮结果

已完成：
- **整体的框架流程图**
- **包含核心功能结构的总体架构图**
- **总功能树与主骨架说明**
- 并已保存到 `cc_learn` 文件夹

下一轮应进入：
- **按功能逐张细化架构图**
- 然后再给每个功能配：
  - 相对路径索引
  - 涉及文件列表
  - 每个 ts/tsx 文件职责详解
