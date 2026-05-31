# Claude Code 子功能架构图 01：启动与入口分流模块

- 仓库路径：`cc/claude_code`
- 对应总图文档：`cc/cc_learn/12_overall_architecture_framework.md`
- 当前主题：**启动与入口分流模块（Startup / Entrypoints / Setup / Interactive Boot）**
- 当前目标：
  1. 画出该功能的完整子架构图
  2. 整理该功能涉及的相对路径索引
  3. 逐个说明关键文件职责

---

## 1. 这个模块到底负责什么

这个模块负责把一个刚启动的 Node 进程，变成一个**已经具备运行 Claude Code 所需上下文的会话运行时**。

它解决的是：

- 当前命令应不应该走 fast-path
- 什么时候加载 `main.tsx`
- 什么时候启用 config / settings / telemetry
- 什么时候设置 cwd / projectRoot / sessionId
- trust / onboarding / setup dialogs 在哪里发生
- 什么时候进入 REPL
- 什么时候只走 headless/query 模式
- worktree / tmux / hooks / memory / messaging watcher 在何时初始化

一句话：

> **如果 `query.ts` 是心脏，那么启动模块就是开机引导、主板固件和运行时装配器。**

---

## 2. 子功能总体架构图（静态结构图）

```text
启动与入口分流模块
├── A. 真实入口层
│   └── source/src/entrypoints/cli.tsx
│
├── B. 进程级初始化层
│   └── source/src/entrypoints/init.ts
│       - safe env
│       - config enable
│       - TLS / proxy / telemetry pre-init
│       - remote managed settings / policy loading promise
│
├── C. 主控制器层
│   └── source/src/main.tsx
│       - CLI 选项注册
│       - 模式路由
│       - interactive vs headless 分发
│
├── D. 会话级 setup 层
│   └── source/src/setup.ts
│       - cwd / projectRoot / session
│       - worktree / tmux
│       - watchers / hooks / prefetch
│       - messaging / session memory / context collapse
│
├── E. 交互式引导层
│   └── source/src/interactiveHelpers.tsx
│       - onboarding
│       - trust dialog
│       - custom key / dangerous mode / auto mode / dev channels
│       - render context / root lifecycle
│
├── F. REPL 渲染装配层
│   └── source/src/replLauncher.tsx
│       - 动态 import App + REPL
│       - 进入交互主界面
│
├── G. 运行时全局状态层
│   └── source/src/bootstrap/state.ts
│       - sessionId / cwd / originalCwd / projectRoot
│       - telemetry state
│       - trust accepted
│       - runtime latches / feature state
│
├── H. 初始上下文预热层
│   └── source/src/context.ts
│       - systemContext
│       - userContext
│       - git snapshot
│       - CLAUDE.md 注入内容
│
└── I. 启动期依赖协议层
    └── source/src/Tool.ts
        - ToolUseContext
        - ToolPermissionContext
        - buildTool defaults
```

---

## 3. 启动主流程图（动态执行图）

这张图回答：**从用户启动，到进入 Claude Code 主会话，中间发生了什么。**

```text
用户执行 claude / Claude Code 入口
        │
        ▼
[source/src/entrypoints/cli.tsx]
  - 读取 argv
  - 判断是否命中 fast-path
  - 若只是 version/daemon/bridge/worker 等轻命令，直接处理
  - 否则懒加载 main.tsx
        │
        ▼
[source/src/main.tsx]
  - 进入 run()/main()
  - 注册 commander 选项与子命令
  - 解析 interactive/headless/remote/assistant 等模式
  - 调 init.ts 做进程级初始化
        │
        ▼
[source/src/entrypoints/init.ts]
  - enableConfigs()
  - applySafeConfigEnvironmentVariables()
  - setupGracefulShutdown()
  - configureGlobalMTLS()/proxy/telemetry pre-init
  - 初始化 remote managed settings / policy loading promise
        │
        ▼
[source/src/setup.ts]
  - 设置 sessionId / cwd / originalCwd / projectRoot
  - 启动 UDS messaging / file watcher / hooks snapshot
  - worktree / tmux / canonical repo root 处理
  - initSessionMemory() / initContextCollapse()
  - 启动 commands/plugins/hooks/background prefetch
        │
        ├──────────────► 若是 headless / print / bare / remote worker 路径
        │                 - 不进完整交互 setup screens
        │                 - 转向 query/headless pipeline
        │
        ▼
[source/src/interactiveHelpers.tsx]
  - showSetupScreens()
  - onboarding
  - trust dialog
  - MCP approvals / CLAUDE.md external include approvals
  - custom API key approval / dangerous permissions dialog
  - auto mode / dev channels / Claude in Chrome onboarding
  - trust 后 apply full env + telemetry init
        │
        ▼
[source/src/replLauncher.tsx]
  - 动态加载 App / REPL
  - renderAndRun(root, <App><REPL/></App>)
        │
        ▼
用户进入 Claude Code 主交互界面
```

---

## 4. 模块内部关系图（谁依赖谁）

```text
entrypoints/cli.tsx
  -> main.tsx

main.tsx
  -> entrypoints/init.ts
  -> setup.ts
  -> interactiveHelpers.tsx
  -> replLauncher.tsx
  -> bootstrap/state.ts
  -> context.ts
  -> Tool.ts

entrypoints/init.ts
  -> config.ts / settings.ts / auth.ts / telemetry / proxy / mtls

setup.ts
  -> bootstrap/state.ts
  -> commands.ts
  -> SessionMemory/**
  -> hook/watcher/worktree/tmux helpers

interactiveHelpers.tsx
  -> bootstrap/state.ts
  -> config.ts / GrowthBook / MCP approval / onboarding dialogs
  -> context.ts

replLauncher.tsx
  -> components/App
  -> screens/REPL

context.ts
  -> git/path/env/claudemd helpers

Tool.ts
  -> tool runtime protocols used later by tools/query
```

---

## 5. 该功能的相对路径索引（第一版）

下面是这个子功能当前最核心的路径索引。

### 5.1 入口与主控制路径

| 相对路径 | 角色 | 重要度 |
|---|---|---|
| `source/src/entrypoints/cli.tsx` | 真实 CLI 入口 / fast-path 分流器 | 极高 |
| `source/src/main.tsx` | 主控制器 / 模式路由中枢 | 极高 |

### 5.2 初始化与 setup 路径

| 相对路径 | 角色 | 重要度 |
|---|---|---|
| `source/src/entrypoints/init.ts` | 进程级初始化 | 极高 |
| `source/src/setup.ts` | 会话级 setup 编排 | 极高 |

### 5.3 交互式引导与 REPL 进入路径

| 相对路径 | 角色 | 重要度 |
|---|---|---|
| `source/src/interactiveHelpers.tsx` | onboarding / trust / render 上下文 | 极高 |
| `source/src/replLauncher.tsx` | App + REPL 动态装载入口 | 高 |

### 5.4 启动期共享状态与上下文路径

| 相对路径 | 角色 | 重要度 |
|---|---|---|
| `source/src/bootstrap/state.ts` | 运行态全局状态仓库 | 极高 |
| `source/src/context.ts` | system/user context 预热与构造 | 高 |
| `source/src/Tool.ts` | 工具协议与权限上下文定义 | 高 |

---

## 6. 启动模块分层说明

### 第 1 层：入口分流层

**代表文件：**
- `source/src/entrypoints/cli.tsx`

**职责：**
- 尽量在最小加载成本下识别当前命令意图
- 只在必要时加载重量级主系统

**本层特点：**
- 性能优先
- fast-path 优先
- 目标是减少冷启动成本

---

### 第 2 层：主控制器层

**代表文件：**
- `source/src/main.tsx`

**职责：**
- 注册 CLI options / subcommands
- 汇总 interactive/headless/remote/assistant/print 等模式分支
- 调用 init/setup/UI 相关子系统

**本层特点：**
- 这是全系统模式路由器
- 几乎所有运行模式都在这里分流

---

### 第 3 层：进程级初始化层

**代表文件：**
- `source/src/entrypoints/init.ts`

**职责：**
- 启用 config
- 先应用 safe env
- 配置网络/TLS/proxy/telemetry 基础能力
- 预热 remote settings / policy limits promise

**本层特点：**
- 这层更偏“全进程只做一次”的基础设施装配

---

### 第 4 层：会话级 setup 层

**代表文件：**
- `source/src/setup.ts`

**职责：**
- 与“当前工作目录、当前 session、当前 worktree”绑定
- 初始化 hooks/file watchers/messaging/session memory/context collapse
- 做启动阶段 prefetch

**本层特点：**
- 更偏“这一轮会话”的装配
- 与 `init.ts` 的“进程级一次性初始化”分开

---

### 第 5 层：交互式 setup screen 层

**代表文件：**
- `source/src/interactiveHelpers.tsx`

**职责：**
- 在正式进入 REPL 之前完成交互式 gating：
  - onboarding
  - trust
  - custom key approval
  - dangerous permissions warning
  - auto mode opt-in
  - dev channels

**本层特点：**
- 它是 trust boundary 的核心 UI 落点
- safe env / full env 的分界线也在这里

---

### 第 6 层：REPL 装载层

**代表文件：**
- `source/src/replLauncher.tsx`

**职责：**
- 动态加载重量级 TUI 组件
- 真正把 App 与 REPL 画到终端上

**本层特点：**
- 这层本身代码很薄
- 但它承担首屏性能优化职责

---

### 第 7 层：运行态状态与上下文层

**代表文件：**
- `source/src/bootstrap/state.ts`
- `source/src/context.ts`

**职责：**
- 管理 session/runtime 的关键全局状态
- 预热 systemContext/userContext 供 query 入口使用

**本层特点：**
- 它们不一定“看起来像启动文件”
- 但实际是启动模块最重要的共享底座

---

## 7. 逐文件职责说明（关键文件）

下面开始按文件逐个说明“它到底干什么、在这个模块中的位置是什么”。

---

## 7.1 `source/src/entrypoints/cli.tsx`

### 文件定位
这是 Claude Code 的**真实进程入口**。

### 主要职责
1. 读取 `process.argv`
2. 判断是否命中轻量级 fast-path
3. 对轻量子命令直接处理
4. 否则再动态导入 `main.tsx`

### 它在本模块中的角色
- 启动链的第一个节点
- 冷启动优化的关键点

### 它解决的核心问题
如果所有命令都直接进 `main.tsx`，那么：
- `--version`
- daemon worker
- bridge
- background session 工具
- remote worker

这些本来很轻的命令也要加载整个 TUI / query / tools / commands 体系，启动会变慢很多。

### 典型行为模式
- fast-path 命中：直接处理，尽量不加载主系统
- fast-path 未命中：导入 `main.tsx`

### 文件价值判断
**极高。**
虽然它不是业务逻辑最多的文件，但它是启动性能设计的核心。

---

## 7.2 `source/src/main.tsx`

### 文件定位
这是整个仓库的**主控制器**之一。

### 主要职责
1. 承接 `cli.tsx` 进入主运行时
2. 注册 commander 命令与选项
3. 区分 interactive/headless/remote/assistant/print 等模式
4. 调 `init.ts` / `setup.ts`
5. 决定是否进入 `interactiveHelpers.tsx` 与 `replLauncher.tsx`

### 它在本模块中的角色
- 模式路由总控文件
- 整个系统的启动总调度器

### 它解决的核心问题
Claude Code 不是一个只有单模式的 CLI。
它要兼容：
- 普通 REPL
- headless print
- remote session
- assistant mode
- worker/daemon/bridge
- worktree / tmux / resume

这些都需要统一从一个主控制器分流。

### 为什么重要
很多模块真正接上线，都是通过 `main.tsx`。
所以这个文件虽然大，但它确实是“系统装配总入口”。

### 文件价值判断
**最高优先级之一。**

---

## 7.3 `source/src/entrypoints/init.ts`

### 文件定位
这是**进程级初始化器**。

### 主要职责
1. `enableConfigs()`
2. 应用 safe env vars
3. 配置 TLS / proxy / graceful shutdown
4. 预热 remote managed settings / policy limits / telemetry 前置状态
5. 为 trust 后的 telemetry 初始化留好条件

### 它在本模块中的角色
- 主系统运行前的一次性基础设施装配器

### 它解决的核心问题
有一些事情必须在真正执行业务逻辑前就做好：
- config 系统 ready
- 安全 env 先应用
- TLS CA / proxy 准备好
- cleanup handlers 注册好

### 关键特点
- 这层偏“全进程一次性初始化”
- 与 `setup.ts` 的“当前 session 初始化”是不同层次

### 文件价值判断
**极高。**

---

## 7.4 `source/src/setup.ts`

### 文件定位
这是**会话级 setup orchestrator**。

### 主要职责
1. session 切换与 sessionId 绑定
2. cwd / originalCwd / projectRoot 设置
3. hooks snapshot / file watcher 初始化
4. worktree / tmux / canonical repo root 处理
5. initSessionMemory() / initContextCollapse()
6. background prefetch（commands/plugins/hooks/release notes/activity）

### 它在本模块中的角色
- 启动过程中“当前工作会话”的装配中心

### 它解决的核心问题
真正进入 Claude Code 主循环前，系统必须知道：
- 当前在哪个项目里
- 当前属于哪个 session
- 是否处于 worktree / tmux 模式
- 哪些 hooks / watchers / session memory 应该启动

### 关键特点
- 分支多
- 与 worktree、session、messaging、hooks、memory 等多个系统强耦合

### 文件价值判断
**极高。**

---

## 7.5 `source/src/interactiveHelpers.tsx`

### 文件定位
这是**交互式 setup screens 与 Ink root 辅助层**。

### 主要职责
1. onboarding 完成流程
2. trust dialog
3. MCP approval / CLAUDE.md include approval
4. custom API key approval
5. dangerous permissions / auto mode / dev channels dialogs
6. render context / fps tracker / stats store
7. root.render / graceful shutdown 包装

### 它在本模块中的角色
- 从“已经 setup 好的运行时”过渡到“正式交互会话”的桥

### 它解决的核心问题
Claude Code 不是一上来就直接把 REPL 打开。
很多安全与交互 gating 必须先发生：
- trust
- onboarding
- dangerous mode 警告
- 某些认证/功能 opt-in

### 特别关键的边界
- trust 前只能 safe env
- trust 后才 apply full env
- telemetry after trust 也在这条线上接起来

### 文件价值判断
**极高。**

---

## 7.6 `source/src/replLauncher.tsx`

### 文件定位
这是**REPL 动态装载入口**。

### 主要职责
1. 动态 import `components/App`
2. 动态 import `screens/REPL`
3. 调 `renderAndRun()` 进入主交互界面

### 它在本模块中的角色
- 交互式引导完成后的最后一跳

### 它解决的核心问题
避免在 `main.tsx` 启动早期直接静态依赖重量级 UI 组件，影响冷启动。

### 特点
- 文件很薄
- 但属于明确的性能优化拆分点

### 文件价值判断
**高。**

---

## 7.7 `source/src/bootstrap/state.ts`

### 文件定位
这是**运行态全局状态仓库**。

### 主要职责
1. 保存 sessionId / parentSessionId
2. 保存 cwd / originalCwd / projectRoot
3. 保存 sessionTrustAccepted
4. 保存 telemetry provider / meter / counters
5. 保存各种 runtime latches / prompt cache / post-compaction flags

### 它在本模块中的角色
- 启动期与运行期共享的单例状态底座

### 它解决的核心问题
启动过程中有很多模块并不在 React context 内，仍然需要共享：
- 当前项目路径
- 当前 session identity
- 当前 trust 状态
- 当前 telemetry / feature runtime state

### 关键特点
- 全局单例
- getter/setter 非常多
- 是全仓很多模块的隐藏耦合点

### 文件价值判断
**极高。**

---

## 7.8 `source/src/context.ts`

### 文件定位
这是**system/user context 生成器**。

### 主要职责
1. 生成 `systemContext`
2. 生成 `userContext`
3. 获取启动时 git snapshot
4. 读取并聚合 `CLAUDE.md` 注入内容

### 它在本模块中的角色
- 启动期上下文预热器
- 后续 query 的 prompt 基础输入之一

### 它解决的核心问题
在 query 开始之前，系统要知道：
- 当前仓库状态是什么
- 用户级文档（如 CLAUDE.md）该如何注入
- 哪些内容可以缓存、哪些要按需读取

### 文件价值判断
**高。**

---

## 7.9 `source/src/Tool.ts`

### 文件定位
这是**工具协议定义中心**。

### 主要职责
1. 定义 `ToolUseContext`
2. 定义 `ToolPermissionContext`
3. 定义 `ToolDef / Tool`
4. 提供 `buildTool()` 默认行为

### 它在本模块中的角色
- 虽然属于工具系统核心文件，但在启动阶段就必须参与
- 因为启动时就要准备工具上下文与权限上下文结构

### 它解决的核心问题
主系统后续所有工具都依赖一套统一协议；启动阶段必须先把协议环境准备好，后面 query 和 tool execution 才能衔接。

### 文件价值判断
**高。**

---

## 8. 文件职责总结表（适合后续继续扩展）

| 相对路径 | 在启动模块中的职责一句话总结 |
|---|---|
| `source/src/entrypoints/cli.tsx` | CLI 真实入口与冷启动分流器 |
| `source/src/main.tsx` | 启动总控制器与模式路由中枢 |
| `source/src/entrypoints/init.ts` | 进程级基础设施初始化器 |
| `source/src/setup.ts` | 会话级 setup 编排器 |
| `source/src/interactiveHelpers.tsx` | trust/onboarding/setup dialogs 与 render 辅助层 |
| `source/src/replLauncher.tsx` | App + REPL 动态装载入口 |
| `source/src/bootstrap/state.ts` | 运行态全局状态仓库 |
| `source/src/context.ts` | system/user context 预热器 |
| `source/src/Tool.ts` | 工具协议与权限上下文定义中心 |

---

## 9. 这个模块与其他模块怎么衔接

### 向下游衔接到：
1. **命令系统模块**
   - 启动后会预热/获取 `commands.ts`
2. **工具系统模块**
   - 启动后会准备 tool permission context / tool use context
3. **Agent 主循环模块**
   - setup 完成后最终进入 `query.ts`
4. **配置/认证模块**
   - `init.ts` / `main.tsx` 会调用 config/settings/auth/client
5. **memory/session 模块**
   - `setup.ts` 中初始化 SessionMemory / session-related watchers
6. **MCP 模块**
   - setup / interactive gating 中处理 MCP approvals 和后续 MCP runtime 初始化

---

## 10. 学这个模块时最该抓住的关键点

如果只抓最重要的 6 个点，我认为是：

1. **`cli.tsx` 是性能层面的入口，不是业务中心**
2. **`main.tsx` 是启动模式分流总控**
3. **`init.ts` 和 `setup.ts` 是两层不同粒度的初始化**
   - `init.ts` = 进程级
   - `setup.ts` = 会话级
4. **`interactiveHelpers.tsx` 是 trust boundary 最重要的 UI 落点**
5. **`bootstrap/state.ts` 是启动与运行期共享的隐形中枢**
6. **启动模块的最终目标不是“把界面打开”，而是“把 query runtime 所需条件全部装配好”**

---

## 11. 当前子功能图完成情况

本轮已完成：
- 启动与入口分流模块的**完整子架构图**
- 该模块的**主流程图**
- 该模块的**相对路径索引**
- 该模块的**关键文件逐项职责说明**
- 以及一份可继续扩展的**职责总表**

已保存到：
- `cc/cc_learn/13_arch_startup_entry_framework.md`

---

## 12. 下一步建议

按你要求“分功能一个个完成”，下一份最自然应该做：

### 优先推荐：命令系统模块
文件名建议：
- `cc/cc_learn/14_arch_command_system_framework.md`

因为它正好承接启动模块之后的第一层能力面：
- slash commands
- prompt commands
- local/local-jsx commands
- skills
- plugin commands
- MCP prompts/skills

如果继续往下做，下一张我就直接画：

> **命令系统模块：完整子架构图 + 相对路径索引 + 每个关键文件职责说明**
