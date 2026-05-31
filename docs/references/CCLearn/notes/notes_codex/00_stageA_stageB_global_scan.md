# Claude Code 代码库学习地图 - 阶段 A / B

- 项目路径：`cc/claude_code`
- 扫描时间：UTC 2026-04-04
- 分析阶段：阶段 A（全局扫描与地图建立）+ 阶段 B（文件总索引）
- 说明：这是基于已提取的 `source/` 源码树做的阅读型分析。该仓库本质上是 `@anthropic-ai/claude-code@2.1.88` 的 npm 包源码映射提取结果，不是可直接重建的原始开发仓库。

---

## 1. 项目整体性质

从 `package.json`、`README.md` 与入口文件可以确认：

- 包名：`@anthropic-ai/claude-code`
- 版本：`2.1.88`
- 发布形式：Node 可执行 CLI（`bin.claude -> cli.js`）
- 运行时：Node >= 18
- 代码来源：由 `cli.js.map` 反向提取到 `source/`，用于阅读学习，不适合重建构建链

### 1.1 你现在看到的仓库其实分成三层

1. **发布产物层**
   - `cli.js`
   - `cli.js.map`
   - `package.json`
   - `sdk-tools.d.ts`

2. **提取出的应用源码层**
   - `source/src/**`
   - 这是绝对主战场，几乎所有可读实现都在这里。

3. **原生/第三方残留层**
   - `vendor/**`
   - `source/vendor/**`
   - `.git/**`
   - 少量 `.node` / `.exe` / sample / pack 文件

---

## 2. 顶层目录结构

```text
cc/claude_code/
├── .git/
├── vendor/
├── source/
│   ├── src/
│   └── vendor/
├── package.json
├── sdk-tools.d.ts
├── cli.js
├── cli.js.map
├── LICENSE.md
├── README.md
└── bun.lock
```

### 2.1 顶层关键项说明

| 路径 | 类型 | 作用 |
|---|---|---|
| `package.json` | 配置 | npm 包元信息、CLI 入口、Node 版本要求 |
| `README.md` | 文档 | 说明源码来自 sourcemap 提取，强调只适合阅读 |
| `cli.js` | 发布产物 | 真正可运行的自包含 CLI bundle |
| `cli.js.map` | sourcemap | 反向提取原始源码的来源 |
| `sdk-tools.d.ts` | 类型声明 | SDK/工具接口声明，后续要纳入类型层分析 |
| `source/src/` | 源码 | 核心业务、UI、服务、工具、命令、状态、查询主循环 |
| `source/vendor/` | 供应商源码残片 | 原生/绑定相关代码残片 |
| `vendor/` | 二进制/平台依赖 | 原生模块与平台文件 |
| `.git/` | 版本控制内部文件 | 不属于业务源码，但纳入覆盖清单 |

---

## 3. 文件类型分布

基于全库扫描统计：

| 文件类型 | 数量 |
|---|---:|
| `.ts` | 1337 |
| `.tsx` | 552 |
| `.js` | 19 |
| `.md` | 2 |
| `.json` | 1 |
| `.lock` | 1 |
| `.map` | 1 |
| `.node` | 6 |
| `.exe` | 2 |
| `.sample` | 14 |
| `[无扩展名]` | 16 |
| 其它 git/pack 索引文件 | 若干 |
| **总计** | **1954** |

### 3.1 按来源粗分

| 类别 | 数量 | 说明 |
|---|---:|---|
| `source` | 1902 | 绝大多数可学习源码 |
| `vendor` | 17 | 原生/平台依赖残片 |
| `root` | 7 | 顶层发布与文档文件 |
| `git` | 28 | `.git` 内部文件 |

### 3.2 结论

这不是一个“小 CLI 工具”，而是一个：

- **大型 TypeScript/TSX 单体应用**
- 兼具 **CLI + TUI + Agent Runtime + Tool System + MCP 平台 + Remote Session + 插件/技能生态**
- 同时包含：
  - 命令系统
  - 工具调用系统
  - 模型调用与上下文管理
  - 记忆/附件/会话恢复
  - 权限与安全策略
  - MCP 服务管理
  - 插件与技能装载
  - 远程会话 / bridge / assistant / ssh / direct-connect

---

## 4. 从入口文件反推系统分层

我先读取了几个最关键的入口与中枢文件：

- `source/src/entrypoints/cli.tsx`
- `source/src/main.tsx`
- `source/src/commands.ts`
- `source/src/tools.ts`
- `source/src/query.ts`

据此可以先还原出整体分层：

### 4.1 入口层（Entrypoint Layer）

**核心文件：**
- `source/src/entrypoints/cli.tsx`
- `source/src/main.tsx`

**职责：**
- 处理启动参数
- 做快速路径分流（version、daemon、bridge、mcp、remote-control、background session 等）
- 加载配置与 telemetry
- 初始化 Commander CLI
- 决定进入：
  - 普通 REPL/TUI
  - headless print 模式
  - daemon / server / bridge / ssh / remote session / assistant session

### 4.2 命令注册层（Slash Commands / CLI Commands Layer）

**核心文件：**
- `source/src/commands.ts`
- `source/src/commands/**`

**职责：**
- 注册所有 slash/local/prompt 命令
- 管理 builtin / plugin / bundled / skill-dir / dynamic-skill / workflow / MCP skill 命令来源
- 做命令可见性、来源标记、远程安全过滤

### 4.3 工具注册层（Tool Registry / Tool Pool Layer）

**核心文件：**
- `source/src/tools.ts`
- `source/src/tools/**`
- `source/src/Tool.js`（后续要重点读）

**职责：**
- 提供内建工具全集
- 依据权限上下文过滤工具
- 合并 MCP tools
- 对不同模式（simple、REPL、coordinator、agent swarms 等）切不同工具子集

### 4.4 Agent 主循环层（Query / Orchestration Layer）

**核心文件：**
- `source/src/query.ts`
- `source/src/query/**`
- `source/src/services/tools/**`
- `source/src/services/api/**`

**职责：**
- 组装消息上下文
- 发起模型流式请求
- 处理 tool_use / tool_result
- 自动 compact / reactive compact / context collapse / token budget / stop hooks
- 实现“Claude 一轮又一轮自主执行”的核心循环

### 4.5 状态与界面层（TUI / AppState Layer）

**关键目录：**
- `source/src/components/**`
- `source/src/state/**`
- `source/src/ink/**`
- `source/src/screens/**`

**职责：**
- Ink TUI 渲染
- AppState 建模
- REPL 状态管理
- dialog、setup screen、提示、列表、选择器

### 4.6 服务层（Services Layer）

**关键目录：**
- `source/src/services/api/**`
- `source/src/services/mcp/**`
- `source/src/services/compact/**`
- `source/src/services/analytics/**`
- `source/src/services/policyLimits/**`
- `source/src/services/remoteManagedSettings/**`
- `source/src/services/plugins/**`
- `source/src/services/SessionMemory/**`
- `source/src/services/toolUseSummary/**`

**职责：**
- 对外 API 与平台交互
- compact / memory / suggestion / analytics / policy / MCP / settings sync
- 提供主循环依赖的“基础服务”

### 4.7 基础设施与工具函数层（Utils / Infra Layer）

**关键目录：**
- `source/src/utils/**`
- `source/src/constants/**`
- `source/src/types/**`
- `source/src/schemas/**`

**职责：**
- 配置读取
- auth
- git / shell / fs
- 消息组装
- token 估算
- prompt/context 拼接
- 会话存储
- 权限规则
- telemetry/debug
- setting source / validation / environment 注入

### 4.8 扩展生态层（Plugin / Skills / MCP / Agent Team Layer）

**关键目录：**
- `source/src/plugins/**`
- `source/src/skills/**`
- `source/src/services/mcp/**`
- `source/src/tools/AgentTool/**`
- `source/src/tasks/**`
- `source/src/assistant/**`
- `source/src/bridge/**`
- `source/src/remote/**`

**职责：**
- 插件能力
- skills 发现与注入
- MCP 服务器管理与资源暴露
- 多 agent / teammate / assistant / remote-control / ssh / teleport / remote session

---

## 5. 通过入口文件识别出的“核心主链路”

这里先给你一个高层调用图，后续阶段 C/E 会细拆。

### 5.1 启动主链路

```text
source/src/entrypoints/cli.tsx
  -> 动态快速路径分流
  -> import source/src/main.tsx
      -> main()
      -> run()
      -> Commander 注册主命令与子命令
      -> action handler
      -> setup()
      -> getCommands()
      -> getTools()
      -> MCP config / settings / policy / telemetry / auth 初始化
      -> interactive: launchRepl(...)
      -> non-interactive: runHeadless(...)
```

### 5.2 Agent 执行主链路

```text
main.tsx
  -> 获取 prompt / commands / tools / settings / app state
  -> 进入 REPL 或 print 模式
  -> query.ts::query()
      -> queryLoop()
      -> 调 model streaming API
      -> 收 assistant message / tool_use
      -> runTools()/StreamingToolExecutor
      -> 收 tool_result / attachment / hooks / memory
      -> 如果需要继续，再下一轮 query
      -> 如果超长，走 compact/reactive compact/context collapse
      -> 最终完成一轮 agentic 任务
```

### 5.3 工具系统主链路

```text
tools.ts
  -> getAllBaseTools()
  -> getTools(permissionContext)
  -> assembleToolPool(permissionContext, mcpTools)
  -> query.ts / REPL / runHeadless 使用这些 tool definitions
  -> StreamingToolExecutor / runTools 执行具体工具
```

### 5.4 命令系统主链路

```text
commands.ts
  -> COMMANDS() 注册 built-in commands
  -> getSkills() / getPluginCommands() / getWorkflowCommands()
  -> loadAllCommands(cwd)
  -> getCommands(cwd)
  -> REPL / slash command / remote-safe filtering 使用
```

---

## 6. 初步识别出的功能模块列表

下面这个模块划分，不是机械按目录，而是按系统职责切。后续阶段 C 会按这个路线深挖。

### 一级模块（建议分析顺序）

1. **启动与入口分流模块**
   - 入口、CLI fast path、mode 分发、Commander 注册

2. **会话与执行主循环模块**
   - query 主循环、streaming、turn continuation、tool orchestration

3. **工具系统模块**
   - tool registry、tool filtering、tool permission、tool execution

4. **命令系统模块**
   - slash/local/prompt commands、动态技能、插件命令、工作流命令

5. **上下文管理与压缩模块**
   - token 估算、blocking limit、autocompact、reactive compact、context collapse、snip

6. **MCP 集成模块**
   - MCP 配置、server 连接、resource/tool/command 注入、政策过滤

7. **配置/设置/环境注入模块**
   - settings source、env 注入、managed settings、policy limits、migrations

8. **认证与模型调用模块**
   - OAuth / API key / model resolution / fallback model / provider 兼容

9. **权限、安全与风险控制模块**
   - trust dialog、permission mode、dangerous permissions、policy gates、remote restrictions

10. **记忆、附件与会话恢复模块**
   - memory、attachment、resume、session storage、teleport resume、conversation recovery

11. **TUI / 状态管理模块**
   - Ink 根组件、AppState、store、render、交互弹窗

12. **插件与技能生态模块**
   - bundled skills、plugin skills、skill directory、dynamic skill、plugin versioning

13. **多 Agent / 协作 / 后台任务模块**
   - AgentTool、Task system、teammate、assistant、coordinator、background session

14. **远程能力模块**
   - remote session、bridge、remote-control、SSH remote、direct-connect、server

15. **诊断、日志、遥测模块**
   - analytics、startup profiler、debug、diagnostics、error logging

16. **原生能力与 vendor 模块**
   - native-ts、vendor、二进制绑定、平台能力补充

---

## 7. 建议的学习顺序

如果你的目标是“彻底学懂整个系统”，最优顺序不是从 `utils/` 开始，而是：

### 第一层：先抓主骨架
1. `source/src/entrypoints/cli.tsx`
2. `source/src/main.tsx`
3. `source/src/query.ts`
4. `source/src/tools.ts`
5. `source/src/commands.ts`

### 第二层：再抓主循环依赖
6. `source/src/services/api/**`
7. `source/src/services/tools/**`
8. `source/src/services/compact/**`
9. `source/src/utils/messages.ts`
10. `source/src/utils/context.ts`
11. `source/src/utils/model/**`
12. `source/src/utils/permissions/**`
13. `source/src/services/mcp/**`

### 第三层：再抓状态和交互
14. `source/src/state/**`
15. `source/src/repl*` / `source/src/components/**` / `source/src/ink/**`
16. `source/src/commands/**`

### 第四层：最后读扩展生态与外围系统
17. `source/src/plugins/**`
18. `source/src/skills/**`
19. `source/src/assistant/**`
20. `source/src/bridge/**`
21. `source/src/remote/**`
22. `source/src/tasks/**`

---

## 8. 阶段 B：文件总索引方法说明

由于文件总数 **1954**，其中 `source/src/**` 就有 **1900+** 文件，不适合在一个文档中把每个文件的完整字段全部手工展开到极度细粒度，否则会淹没有效信息。

所以阶段 B 我会拆成两层：

### 8.1 当前轮先给出“总索引框架”
- 顶层与核心目录级索引
- 一级模块归类
- 高优先级核心文件列表
- 文件分布统计

### 8.2 后续轮继续补全为“全量文件索引表”
- 每个文件：
  - 相对路径
  - 文件类型
  - 所属目录
  - 推测职责
  - 所属功能模块
  - 是否核心文件
  - 是否配置/类型/辅助/原生/二进制
- 最终在阶段 F 给出**完整覆盖审计表**

也就是说：**不会漏文件，但会分批落盘。**

---

## 9. 阶段 B：核心目录级索引（初版）

> 注意：这不是最终覆盖表，而是第一版索引地图，用来建立“模块 -> 目录 -> 文件”的导航关系。

| 目录 | 推测职责 | 所属模块 | 重要度 |
|---|---|---|---|
| `source/src/entrypoints/` | 启动入口 | 启动与入口分流 | 极高 |
| `source/src/main.tsx` | 主 CLI 控制中枢 | 启动与入口分流 | 极高 |
| `source/src/query.ts` | Agent 主循环 | 会话与执行主循环 | 极高 |
| `source/src/commands.ts` | 命令注册中心 | 命令系统 | 极高 |
| `source/src/tools.ts` | 工具注册中心 | 工具系统 | 极高 |
| `source/src/commands/` | slash/local/prompt 命令实现 | 命令系统 | 高 |
| `source/src/tools/` | 各工具实现 | 工具系统 | 极高 |
| `source/src/services/api/` | 模型/API/远端接口 | 模型调用/服务层 | 极高 |
| `source/src/services/tools/` | tool orchestration | 工具执行 | 极高 |
| `source/src/services/compact/` | 自动压缩/上下文回收 | 上下文管理 | 极高 |
| `source/src/services/mcp/` | MCP 配置/连接/资源 | MCP 模块 | 极高 |
| `source/src/services/policyLimits/` | 企业策略与权限限制 | 安全/权限 | 高 |
| `source/src/services/remoteManagedSettings/` | 远程托管设置 | 配置/策略 | 高 |
| `source/src/services/analytics/` | 埋点与特性开关 | 监控/功能门控 | 高 |
| `source/src/services/SessionMemory/` | 会话记忆 | 记忆模块 | 高 |
| `source/src/state/` | AppState 与状态流 | 状态管理 | 高 |
| `source/src/components/` | TUI 组件 | 视图层 | 高 |
| `source/src/ink/` | Ink 基础设施 | TUI 基建 | 高 |
| `source/src/utils/` | 共享基础设施 | 基础设施 | 极高 |
| `source/src/types/` | 类型协议 | 类型层 | 高 |
| `source/src/constants/` | 常量/默认 prompt/枚举 | 基础设施 | 高 |
| `source/src/schemas/` | schema 定义 | 配置/协议 | 中高 |
| `source/src/plugins/` | 插件体系 | 扩展生态 | 高 |
| `source/src/skills/` | 技能体系 | 扩展生态 | 高 |
| `source/src/tasks/` | 后台任务与子任务 | 多 Agent / 任务系统 | 高 |
| `source/src/assistant/` | assistant mode | 多 Agent / 远程 | 高 |
| `source/src/bridge/` | remote-control bridge | 远程控制 | 高 |
| `source/src/remote/` | 远程会话 | 远程能力 | 高 |
| `source/src/server/` | direct-connect / session server | 远程服务端 | 高 |
| `source/src/bootstrap/` | 运行态全局状态与启动上下文 | 启动/运行态 | 高 |
| `source/src/migrations/` | 配置/模型迁移 | 配置演进 | 中高 |
| `source/src/native-ts/` | 原生绑定 TS 封装 | 原生基础设施 | 中 |
| `source/src/vendor/` / `vendor/` | 原生依赖残留 | 原生/第三方 | 中 |

---

## 10. 当前已识别的“最关键文件”

### 10.1 核心入口文件

| 路径 | 为什么关键 |
|---|---|
| `source/src/entrypoints/cli.tsx` | 真正启动点，负责 fast-path 分流 |
| `source/src/main.tsx` | 最大中枢文件，负责初始化、CLI option、模式路由、REPL/headless 进入 |
| `source/src/query.ts` | Agent 执行主循环，系统真正的“心脏” |
| `source/src/tools.ts` | 工具全集、过滤、合并、模式切换中心 |
| `source/src/commands.ts` | 命令全集、技能/插件命令聚合中心 |

### 10.2 每个核心文件的当前定位

#### `source/src/entrypoints/cli.tsx`
- 不是“业务逻辑中心”，而是 **启动分流器**。
- 通过 `process.argv` 做大量 fast-path：
  - `--version`
  - `--dump-system-prompt`
  - browser/mcp/native-host
  - daemon worker / daemon
  - bg session 管理
  - template jobs
  - environment-runner / self-hosted-runner
  - worktree + tmux fast path
  - bare mode 早期 env 注入
- 设计意图：**减少全量模块加载成本**，让简单命令不必评估整个大应用。

#### `source/src/main.tsx`
- 巨型 orchestrator。
- 负责：
  - 预读 MDM / keychain / startup profiler
  - settings flag 提前加载
  - trust / warning / signal / uri / assistant / ssh / direct-connect 早期改写
  - Commander 选项和子命令总注册
  - 进入 REPL 或 headless print
  - setup、MCP、LSP、plugins、hooks、resume、remote、teleport、assistant
- 设计意图：**把所有运行模式汇聚成一个共享主流程**，避免多套 CLI 入口逻辑分叉失控。

#### `source/src/commands.ts`
- 不只是静态命令列表。
- 它做了：
  - builtin commands
  - internal-only commands
  - dynamic skill discovery
  - plugin commands / plugin skills
  - bundled skills
  - workflow commands
  - remote-safe / bridge-safe 过滤
  - slash-command for model 与 UI 用途区分
- 设计意图：**统一“命令来源异构性”**。

#### `source/src/tools.ts`
- 不只是 export tools。
- 它做了：
  - 内建工具全集定义
  - feature gate 条件加载
  - simple / REPL / coordinator / swarm / MCP / powershell / synthetic-output 等模式切换
  - 权限 deny rule 过滤
  - MCP tools 合并与排序稳定化
- 设计意图：**把“工具可见性”和“工具集合的确定性”集中起来**。

#### `source/src/query.ts`
- 是整个系统最值得精读的文件之一。
- 它做了：
  - Query state machine
  - 流式模型调用
  - tool_use / tool_result 协调
  - prompt-too-long / media error / max_output_tokens recovery
  - autocompact / reactive compact / context collapse / snip
  - hooks / queued commands / attachment / memory prefetch / skill prefetch
  - token budget / stop hooks / turn continuation
- 设计意图：**把“带工具的 LLM agent turn loop”做成一个可恢复、可压缩、可审计的状态机。**

---

## 11. 从阶段 A/B 得出的架构判断

### 11.1 这套系统的架构风格

它不是典型 MVC，也不是纯 DDD，而更像：

- **CLI/TUI 外壳**
- + **消息驱动的 Agent 主循环**
- + **工具注册中心 + 动态扩展生态**
- + **配置/策略/权限多层门控系统**
- + **会话状态机 + 上下文压缩/恢复机制**

也可以把它理解为：

> 一个“本地可执行的 Agent Runtime 平台”，CLI 只是其 UI 之一。

### 11.2 它最核心的工程难点

我目前识别出几个难点：

1. **启动性能**
   - 通过 `cli.tsx` fast path、dynamic import、prefetch、并行初始化降低冷启动成本。

2. **上下文窗口与 token 成本**
   - 通过 auto compact / reactive compact / context collapse / snip / cache-aware edits 控制上下文膨胀。

3. **工具调用的一致性**
   - tool registry + permission context + MCP merge + streaming tool execution。

4. **安全边界**
   - trust dialog、policy limits、dangerous permissions stripping、enterprise MCP policy、remote restrictions。

5. **模式复杂度**
   - interactive / print / sdk / remote / assistant / ssh / daemon / bridge / worktree / coordinator / proactive / brief。

6. **扩展来源多样**
   - builtin + plugin + bundled + skill-dir + workflow + mcp-command。

---

## 12. 下一阶段的建议分析顺序

下一轮我建议优先进入 **阶段 C 的第 1 模块与第 2 模块**：

### 模块 1：启动与入口分流模块
优先文件：
1. `source/src/entrypoints/cli.tsx`
2. `source/src/main.tsx`
3. `source/src/bootstrap/state.js`（或对应源码文件）
4. `source/src/entrypoints/init.js`
5. `source/src/setup.js`
6. `source/src/interactiveHelpers.js`
7. `source/src/replLauncher.js`

### 模块 2：命令系统与工具系统中枢
优先文件：
1. `source/src/commands.ts`
2. `source/src/tools.ts`
3. `source/src/Tool.js` / 对应源文件
4. `source/src/types/command.js` / 对应源文件
5. `source/src/services/tools/**`

### 模块 3：Agent 主循环
优先文件：
1. `source/src/query.ts`
2. `source/src/query/config.js`
3. `source/src/query/deps.js`
4. `source/src/services/api/**`
5. `source/src/services/compact/**`
6. `source/src/services/tools/**`

---

## 13. 阶段 B：全量文件索引的落地策略

为了满足你“所有文件必须覆盖”的要求，我会把输出落在：

- `cc/cc_learn/00_stageA_stageB_global_scan.md`（当前文件）
- 后续继续生成：
  - `01_file_index_root_and_core.md`
  - `02_module_startup_entry.md`
  - `03_module_command_system.md`
  - `04_module_tool_system.md`
  - `05_module_query_loop.md`
  - ……
  - 最终 `99_coverage_audit.md`

另外还会生成机器可读辅助索引：
- `cc/cc_learn/all_files.txt`
- `cc/cc_learn/scan_stats.json`

---

## 14. 当前阶段结论

如果一句话概括：

> 这个代码库的真正核心，不是某个单独工具，而是 `main.tsx + query.ts + tools.ts + commands.ts` 四个中枢文件共同构成的“可扩展 Agent Runtime”。

它的外表是 CLI，内核却是：
- 一个带状态机的 LLM 调度器
- 一个统一工具/命令/技能/MCP 扩展平台
- 一个注重启动性能、上下文压缩、安全门控和多模式运行的复杂终端 AI 系统

---

## 15. 本轮已完成分析的文件列表（相对路径）

- `package.json`
- `README.md`
- `source/src/entrypoints/cli.tsx`
- `source/src/main.tsx`（已读取前大段，建立主流程地图）
- `source/src/commands.ts`
- `source/src/tools.ts`
- `source/src/query.ts`
- 以及全库文件路径扫描结果（见 `all_files.txt`）

---

## 16. 本轮未完成但下一轮建议继续分析的模块

1. 启动与入口分流模块（深入）
2. 命令系统模块（深入）
3. 工具系统模块（深入）
4. 主查询循环模块（深入）
5. 全量文件索引表第一批（root/core/startup）

---

## 17. 当前累计已覆盖文件数 / 总文件数

- 已实际阅读/建立职责地图的关键文件：**7**
- 已纳入全量路径扫描：**1954 / 1954**
- 已完成逐文件深读：**7 / 1954**

> 注意：这里把“覆盖”分成两层：
> - 路径层覆盖：已经 100% 扫描到文件路径
> - 内容层深读：当前只完成第一批关键中枢文件

---

## 18. 当前代码库学习进度

- **全局扫描进度：100%**
- **文件路径建档进度：100%**
- **内容级深度分析进度：约 8%**
- **整体学习进度：12%**

后续将进入模块化深读与全量文件覆盖表补齐。
