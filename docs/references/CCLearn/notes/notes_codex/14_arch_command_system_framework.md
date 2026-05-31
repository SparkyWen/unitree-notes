# Claude Code 子功能架构图 02：命令系统模块

- 仓库路径：`cc/claude_code`
- 对应总图文档：`cc/cc_learn/12_overall_architecture_framework.md`
- 当前主题：**命令系统模块（Slash Commands / Prompt Commands / Local Commands / Skills / Plugin Commands / MCP Prompt Commands）**
- 当前目标：
  1. 画出命令系统的完整子架构图
  2. 给出该功能块涉及文件的相对路径索引
  3. 尽量覆盖该功能块**所有涉及文件**，总结它们各自的作用

---

## 1. 命令系统模块到底负责什么

Claude Code 里的“命令”不是单一概念。

它至少统一了这几类来源：

- 内建 slash commands
- 本地逻辑命令（local commands）
- 本地 JSX/Ink 界面命令（local-jsx commands）
- prompt 型命令（markdown / skill 命令）
- bundled skills
- project/user/local skills
- plugin commands
- plugin skills
- MCP prompts / MCP skills
- workflow 风格命令

也就是说，这个模块真正负责的是：

> **把“用户或模型在会话层能触发的高层操作入口”统一成一个命令平台。**

---

## 2. 命令系统总架构图（静态结构图）

```text
命令系统模块
├── A. 命令协议层
│   └── source/src/types/command.ts
│       - CommandBase
│       - PromptCommand
│       - LocalCommand
│       - LocalJSXCommand
│
├── B. 命令聚合总入口
│   └── source/src/commands.ts
│       - builtin commands
│       - skill dir commands
│       - bundled skills
│       - builtin plugin skills
│       - plugin commands / plugin skills
│       - workflow / MCP command integration
│
├── C. 本地技能系统
│   ├── source/src/skills/loadSkillsDir.ts
│   ├── source/src/skills/bundledSkills.ts
│   ├── source/src/skills/bundled/**
│   └── source/src/skills/mcpSkillBuilders.ts
│
├── D. 插件命令系统
│   ├── source/src/plugins/builtinPlugins.ts
│   ├── source/src/plugins/bundled/index.ts
│   └── source/src/utils/plugins/loadPluginCommands.ts
│
├── E. 插件命令生态支撑层
│   └── source/src/utils/plugins/**
│       - plugin loader / marketplace / validation / policy / options / cache
│
└── F. 命令实现树
    └── source/src/commands/**
        - 每个命令目录/文件的具体实现
        - local / local-jsx / prompt 等不同形态命令的落地实现
```

---

## 3. 命令系统动态流程图（运行图）

```text
main.tsx / setup.ts / REPL
      │
      ▼
[source/src/commands.ts] getCommands(cwd)
      │
      ├── 收 builtin slash commands
      │
      ├── 收本地技能目录命令
      │     └── source/src/skills/loadSkillsDir.ts
      │         - skills/
      │         - legacy commands/
      │         - dynamic/conditional skills
      │
      ├── 收 bundled skills
      │     └── source/src/skills/bundledSkills.ts
      │
      ├── 收 builtin plugin skills
      │     └── source/src/plugins/builtinPlugins.ts
      │
      ├── 收 plugin commands / plugin skills
      │     └── source/src/utils/plugins/loadPluginCommands.ts
      │
      ├── 收 MCP prompts / MCP skills
      │     └── services/mcp/client.ts + skills/mcpSkillBuilders.ts
      │
      ▼
统一得到 Command[]
      │
      ├── 用于 REPL autocomplete / help / slash dispatch
      ├── 用于 local/local-jsx command 执行
      ├── 用于 prompt command 生成 prompt blocks
      └── 用于模型看到的 skill/command 能力面
```

---

## 4. 命令系统功能分层图

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 1. 协议层：types/command.ts                                          │
│    定义命令是什么、分几种类型、执行契约是什么                        │
└──────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. 聚合层：commands.ts                                               │
│    把所有来源的命令汇总成统一 Command[]                              │
└──────────────────────────────────────────────────────────────────────┘
                                │
      ┌─────────────────────────┼─────────────────────────┐
      │                         │                         │
      ▼                         ▼                         ▼
┌───────────────┐     ┌────────────────────┐    ┌────────────────────┐
│ 3A 本地技能    │     │ 3B 插件命令/技能   │    │ 3C 内建/打包技能    │
│ loadSkillsDir │     │ loadPluginCommands │    │ bundledSkills      │
│               │     │ builtinPlugins     │    │ skills/bundled/**  │
└───────────────┘     └────────────────────┘    └────────────────────┘
      │                         │                         │
      └─────────────────────────┴──────────────┬──────────┘
                                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 4. 命令实现层：commands/**                                            │
│    每个命令文件实际提供 local / local-jsx / prompt 入口               │
└──────────────────────────────────────────────────────────────────────┘
                                               │
                                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 5. UI / Runtime 使用层                                                │
│    help / autocomplete / dispatcher / REPL / model-visible commands   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. 该功能块涉及的文件范围（总览）

当前把命令系统涉及文件分成 6 类：

1. **命令协议文件**
2. **命令聚合文件**
3. **skills 相关文件**
4. **plugin command / plugin skill 相关文件**
5. **commands/** 真正的命令实现文件**
6. **插件生态支撑文件（因为 plugin commands 依赖它们）**

下面先给总索引，再逐类解释。

---

## 6. 相对路径索引（总表）

---

### 6.1 命令协议与总入口

| 相对路径 | 作用 |
|---|---|
| `source/src/types/command.ts` | 命令协议中心，定义 Command 的类型系统 |
| `source/src/commands.ts` | 命令聚合总入口，汇总所有来源命令 |

---

### 6.2 skills 相关文件

| 相对路径 | 作用 |
|---|---|
| `source/src/skills/loadSkillsDir.ts` | 从本地 skills/commands 目录加载 markdown 技能命令 |
| `source/src/skills/bundledSkills.ts` | 管理 bundled skills 注册与转换 |
| `source/src/skills/mcpSkillBuilders.ts` | 把 MCP 资源/skill 适配成命令/技能构造逻辑 |
| `source/src/skills/bundled/batch.ts` | bundled skill：批处理相关 |
| `source/src/skills/bundled/claudeApi.ts` | bundled skill：Claude API 相关 |
| `source/src/skills/bundled/claudeApiContent.ts` | bundled skill：Claude API 技能内容 |
| `source/src/skills/bundled/claudeInChrome.ts` | bundled skill：Claude in Chrome 相关 |
| `source/src/skills/bundled/debug.ts` | bundled skill：调试相关 |
| `source/src/skills/bundled/index.ts` | bundled skills 汇总入口 |
| `source/src/skills/bundled/keybindings.ts` | bundled skill：快捷键相关 |
| `source/src/skills/bundled/loop.ts` | bundled skill：循环/迭代相关 |
| `source/src/skills/bundled/loremIpsum.ts` | bundled skill：示例/测试内容 |
| `source/src/skills/bundled/remember.ts` | bundled skill：记忆相关 |
| `source/src/skills/bundled/scheduleRemoteAgents.ts` | bundled skill：远程 agent 调度 |
| `source/src/skills/bundled/simplify.ts` | bundled skill：简化/整理相关 |
| `source/src/skills/bundled/skillify.ts` | bundled skill：把内容变成 skill 的辅助能力 |
| `source/src/skills/bundled/stuck.ts` | bundled skill：卡住时的引导 |
| `source/src/skills/bundled/updateConfig.ts` | bundled skill：配置更新相关 |
| `source/src/skills/bundled/verify.ts` | bundled skill：验证/核对 |
| `source/src/skills/bundled/verifyContent.ts` | bundled skill：验证技能附带内容 |

---

### 6.3 plugin command / plugin skill 相关文件

| 相对路径 | 作用 |
|---|---|
| `source/src/plugins/builtinPlugins.ts` | 内建插件注册表，并可导出内建插件技能命令 |
| `source/src/plugins/bundled/index.ts` | 内建/打包插件内容汇总入口 |
| `source/src/utils/plugins/loadPluginCommands.ts` | 加载插件 commands/skills 的核心文件 |

---

### 6.4 commands/** 命令实现文件（完整索引）

下面先按路径完整列出当前 `commands/**` 中的文件，后面再给功能分组与职责总结。

```text
source/src/commands/add-dir/add-dir.tsx
source/src/commands/add-dir/index.ts
source/src/commands/add-dir/validation.ts
source/src/commands/advisor.ts
source/src/commands/agents/agents.tsx
source/src/commands/agents/index.ts
source/src/commands/ant-trace/index.js
source/src/commands/autofix-pr/index.js
source/src/commands/backfill-sessions/index.js
source/src/commands/branch/branch.ts
source/src/commands/branch/index.ts
source/src/commands/break-cache/index.js
source/src/commands/bridge-kick.ts
source/src/commands/bridge/bridge.tsx
source/src/commands/bridge/index.ts
source/src/commands/brief.ts
source/src/commands/btw/btw.tsx
source/src/commands/btw/index.ts
source/src/commands/bughunter/index.js
source/src/commands/chrome/chrome.tsx
source/src/commands/chrome/index.ts
source/src/commands/clear/caches.ts
source/src/commands/clear/clear.ts
source/src/commands/clear/conversation.ts
source/src/commands/clear/index.ts
source/src/commands/color/color.ts
source/src/commands/color/index.ts
source/src/commands/commit-push-pr.ts
source/src/commands/commit.ts
source/src/commands/compact/compact.ts
source/src/commands/compact/index.ts
source/src/commands/config/config.tsx
source/src/commands/config/index.ts
source/src/commands/context/context-noninteractive.ts
source/src/commands/context/context.tsx
source/src/commands/context/index.ts
source/src/commands/copy/copy.tsx
source/src/commands/copy/index.ts
source/src/commands/cost/cost.ts
source/src/commands/cost/index.ts
source/src/commands/createMovedToPluginCommand.ts
source/src/commands/ctx_viz/index.js
source/src/commands/debug-tool-call/index.js
source/src/commands/desktop/desktop.tsx
source/src/commands/desktop/index.ts
source/src/commands/diff/diff.tsx
source/src/commands/diff/index.ts
source/src/commands/doctor/doctor.tsx
source/src/commands/doctor/index.ts
source/src/commands/effort/effort.tsx
source/src/commands/effort/index.ts
source/src/commands/env/index.js
source/src/commands/exit/exit.tsx
source/src/commands/exit/index.ts
source/src/commands/export/export.tsx
source/src/commands/export/index.ts
source/src/commands/extra-usage/extra-usage-core.ts
source/src/commands/extra-usage/extra-usage-noninteractive.ts
source/src/commands/extra-usage/extra-usage.tsx
source/src/commands/extra-usage/index.ts
source/src/commands/fast/fast.tsx
source/src/commands/fast/index.ts
source/src/commands/feedback/feedback.tsx
source/src/commands/feedback/index.ts
source/src/commands/files/files.ts
source/src/commands/files/index.ts
source/src/commands/good-claude/index.js
source/src/commands/heapdump/heapdump.ts
source/src/commands/heapdump/index.ts
source/src/commands/help/help.tsx
source/src/commands/help/index.ts
source/src/commands/hooks/hooks.tsx
source/src/commands/hooks/index.ts
source/src/commands/ide/ide.tsx
source/src/commands/ide/index.ts
source/src/commands/init-verifiers.ts
source/src/commands/init.ts
source/src/commands/insights.ts
source/src/commands/install-github-app/ApiKeyStep.tsx
source/src/commands/install-github-app/CheckExistingSecretStep.tsx
source/src/commands/install-github-app/CheckGitHubStep.tsx
source/src/commands/install-github-app/ChooseRepoStep.tsx
source/src/commands/install-github-app/CreatingStep.tsx
source/src/commands/install-github-app/ErrorStep.tsx
source/src/commands/install-github-app/ExistingWorkflowStep.tsx
source/src/commands/install-github-app/InstallAppStep.tsx
source/src/commands/install-github-app/OAuthFlowStep.tsx
source/src/commands/install-github-app/SuccessStep.tsx
source/src/commands/install-github-app/WarningsStep.tsx
source/src/commands/install-github-app/index.ts
source/src/commands/install-github-app/install-github-app.tsx
source/src/commands/install-github-app/setupGitHubActions.ts
source/src/commands/install-slack-app/index.ts
source/src/commands/install-slack-app/install-slack-app.ts
source/src/commands/install.tsx
source/src/commands/issue/index.js
source/src/commands/keybindings/index.ts
source/src/commands/keybindings/keybindings.ts
source/src/commands/login/index.ts
source/src/commands/login/login.tsx
source/src/commands/logout/index.ts
source/src/commands/logout/logout.tsx
source/src/commands/mcp/addCommand.ts
source/src/commands/mcp/index.ts
source/src/commands/mcp/mcp.tsx
source/src/commands/mcp/xaaIdpCommand.ts
source/src/commands/memory/index.ts
source/src/commands/memory/memory.tsx
source/src/commands/mobile/index.ts
source/src/commands/mobile/mobile.tsx
source/src/commands/mock-limits/index.js
source/src/commands/model/index.ts
source/src/commands/model/model.tsx
source/src/commands/oauth-refresh/index.js
source/src/commands/onboarding/index.js
source/src/commands/output-style/index.ts
source/src/commands/output-style/output-style.tsx
source/src/commands/passes/index.ts
source/src/commands/passes/passes.tsx
source/src/commands/perf-issue/index.js
source/src/commands/permissions/index.ts
source/src/commands/permissions/permissions.tsx
source/src/commands/plan/index.ts
source/src/commands/plan/plan.tsx
source/src/commands/plugin/AddMarketplace.tsx
source/src/commands/plugin/BrowseMarketplace.tsx
source/src/commands/plugin/DiscoverPlugins.tsx
source/src/commands/plugin/ManageMarketplaces.tsx
source/src/commands/plugin/ManagePlugins.tsx
source/src/commands/plugin/PluginErrors.tsx
source/src/commands/plugin/PluginOptionsDialog.tsx
source/src/commands/plugin/PluginOptionsFlow.tsx
source/src/commands/plugin/PluginSettings.tsx
source/src/commands/plugin/PluginTrustWarning.tsx
source/src/commands/plugin/UnifiedInstalledCell.tsx
source/src/commands/plugin/ValidatePlugin.tsx
source/src/commands/plugin/index.tsx
source/src/commands/plugin/parseArgs.ts
source/src/commands/plugin/plugin.tsx
source/src/commands/plugin/pluginDetailsHelpers.tsx
source/src/commands/plugin/usePagination.ts
source/src/commands/pr_comments/index.ts
source/src/commands/privacy-settings/index.ts
source/src/commands/privacy-settings/privacy-settings.tsx
source/src/commands/rate-limit-options/index.ts
source/src/commands/rate-limit-options/rate-limit-options.tsx
source/src/commands/release-notes/index.ts
source/src/commands/release-notes/release-notes.ts
source/src/commands/reload-plugins/index.ts
source/src/commands/reload-plugins/reload-plugins.ts
source/src/commands/remote-env/index.ts
source/src/commands/remote-env/remote-env.tsx
source/src/commands/remote-setup/api.ts
source/src/commands/remote-setup/index.ts
source/src/commands/remote-setup/remote-setup.tsx
source/src/commands/rename/generateSessionName.ts
source/src/commands/rename/index.ts
source/src/commands/rename/rename.ts
source/src/commands/reset-limits/index.js
source/src/commands/resume/index.ts
source/src/commands/resume/resume.tsx
source/src/commands/review.ts
source/src/commands/review/UltrareviewOverageDialog.tsx
source/src/commands/review/reviewRemote.ts
source/src/commands/review/ultrareviewCommand.tsx
source/src/commands/review/ultrareviewEnabled.ts
source/src/commands/rewind/index.ts
source/src/commands/rewind/rewind.ts
source/src/commands/sandbox-toggle/index.ts
source/src/commands/sandbox-toggle/sandbox-toggle.tsx
source/src/commands/security-review.ts
source/src/commands/session/index.ts
source/src/commands/session/session.tsx
source/src/commands/share/index.js
source/src/commands/skills/index.ts
source/src/commands/skills/skills.tsx
source/src/commands/stats/index.ts
source/src/commands/stats/stats.tsx
source/src/commands/status/index.ts
source/src/commands/status/status.tsx
source/src/commands/statusline.tsx
source/src/commands/stickers/index.ts
source/src/commands/stickers/stickers.ts
source/src/commands/summary/index.js
source/src/commands/tag/index.ts
source/src/commands/tag/tag.tsx
source/src/commands/tasks/index.ts
source/src/commands/tasks/tasks.tsx
source/src/commands/teleport/index.js
source/src/commands/terminalSetup/index.ts
source/src/commands/terminalSetup/terminalSetup.tsx
source/src/commands/theme/index.ts
source/src/commands/theme/theme.tsx
source/src/commands/thinkback-play/index.ts
source/src/commands/thinkback-play/thinkback-play.ts
source/src/commands/thinkback/index.ts
source/src/commands/thinkback/thinkback.tsx
source/src/commands/ultraplan.tsx
source/src/commands/upgrade/index.ts
source/src/commands/upgrade/upgrade.tsx
source/src/commands/usage/index.ts
source/src/commands/usage/usage.tsx
source/src/commands/version.ts
source/src/commands/vim/index.ts
source/src/commands/vim/vim.ts
source/src/commands/voice/index.ts
source/src/commands/voice/voice.ts
```

---

### 6.5 plugin command 生态支撑文件（因为命令系统依赖它们）

```text
source/src/utils/plugins/addDirPluginSettings.ts
source/src/utils/plugins/cacheUtils.ts
source/src/utils/plugins/dependencyResolver.ts
source/src/utils/plugins/fetchTelemetry.ts
source/src/utils/plugins/gitAvailability.ts
source/src/utils/plugins/headlessPluginInstall.ts
source/src/utils/plugins/hintRecommendation.ts
source/src/utils/plugins/installCounts.ts
source/src/utils/plugins/installedPluginsManager.ts
source/src/utils/plugins/loadPluginAgents.ts
source/src/utils/plugins/loadPluginCommands.ts
source/src/utils/plugins/loadPluginHooks.ts
source/src/utils/plugins/loadPluginOutputStyles.ts
source/src/utils/plugins/lspPluginIntegration.ts
source/src/utils/plugins/lspRecommendation.ts
source/src/utils/plugins/managedPlugins.ts
source/src/utils/plugins/marketplaceHelpers.ts
source/src/utils/plugins/marketplaceManager.ts
source/src/utils/plugins/mcpPluginIntegration.ts
source/src/utils/plugins/mcpbHandler.ts
source/src/utils/plugins/officialMarketplace.ts
source/src/utils/plugins/officialMarketplaceGcs.ts
source/src/utils/plugins/officialMarketplaceStartupCheck.ts
source/src/utils/plugins/orphanedPluginFilter.ts
source/src/utils/plugins/parseMarketplaceInput.ts
source/src/utils/plugins/performStartupChecks.tsx
source/src/utils/plugins/pluginAutoupdate.ts
source/src/utils/plugins/pluginBlocklist.ts
source/src/utils/plugins/pluginDirectories.ts
source/src/utils/plugins/pluginFlagging.ts
source/src/utils/plugins/pluginIdentifier.ts
source/src/utils/plugins/pluginInstallationHelpers.ts
source/src/utils/plugins/pluginLoader.ts
source/src/utils/plugins/pluginOptionsStorage.ts
source/src/utils/plugins/pluginPolicy.ts
source/src/utils/plugins/pluginStartupCheck.ts
source/src/utils/plugins/pluginVersioning.ts
source/src/utils/plugins/reconciler.ts
source/src/utils/plugins/refresh.ts
source/src/utils/plugins/schemas.ts
source/src/utils/plugins/validatePlugin.ts
source/src/utils/plugins/walkPluginMarkdown.ts
source/src/utils/plugins/zipCache.ts
source/src/utils/plugins/zipCacheAdapters.ts
```

---

## 7. 命令系统模块的关键主线

命令系统的核心主线可以概括成一句话：

```text
types/command.ts -> commands.ts -> 各类加载器(skills/plugins/MCP) -> commands/** 真正实现
```

更完整一点：

```text
source/src/types/command.ts
  -> 定义 Command 协议
source/src/commands.ts
  -> 聚合 builtin / skills / bundled / plugins / MCP commands
source/src/skills/loadSkillsDir.ts
  -> 本地 markdown 技能 -> PromptCommand
source/src/skills/bundledSkills.ts
  -> bundled skill -> PromptCommand
source/src/utils/plugins/loadPluginCommands.ts
  -> plugin markdown / inline content -> Command
source/src/plugins/builtinPlugins.ts
  -> builtin plugin skills -> Command
source/src/commands/**
  -> 具体 local/local-jsx 命令实现
```

---

## 8. 核心文件逐项职责说明

下面先把命令系统中最核心的一层文件讲清楚。

---

### 8.1 `source/src/types/command.ts`

**作用：** 命令协议中心。

它定义了：
- `CommandBase`
- `PromptCommand`
- `LocalCommand`
- `LocalJSXCommand`
- `Command`
- 相关 helper（如 `isCommandEnabled`、命令名解析等）

**它解决的问题：**
Claude Code 的命令来源和执行方式都很多样，必须先统一抽象“命令是什么”。

**它在命令系统中的位置：**
- 最底层协议文件
- 上游没有业务逻辑
- 下游所有命令聚合、UI、调度都依赖它

**一句话总结：**
> 命令系统的领域模型定义文件。

---

### 8.2 `source/src/commands.ts`

**作用：** 命令聚合总入口。

它负责：
- 汇总 builtin commands
- 汇总技能目录命令
- 汇总 bundled skills
- 汇总 builtin plugin skills
- 汇总 plugin commands / plugin skills
- 汇总 workflow / MCP prompt 型命令
- 最终返回统一 `Command[]`

**它解决的问题：**
调用方不应该分别知道命令来自哪里，只应该拿到一份统一命令池。

**一句话总结：**
> 命令系统的总注册中心和统一出口。

---

### 8.3 `source/src/skills/loadSkillsDir.ts`

**作用：** 本地 skills / legacy commands 加载器。

它负责：
- 扫描 `skills/` 与旧的 `commands/` 目录
- 解析 markdown frontmatter
- 构造 `PromptCommand`
- 处理 dynamic skills / conditional skills / paths 激活
- 做 file identity dedup 与 settings-aware skills discovery

**它解决的问题：**
让本地磁盘上的 skill markdown 变成可执行命令，而不是静态文档。

**一句话总结：**
> 本地技能命令转译器。

---

### 8.4 `source/src/skills/bundledSkills.ts`

**作用：** bundled skill 注册与运行期 materialization。

它负责：
- 注册代码内置的技能定义
- 把 skill definition 转成 `PromptCommand`
- 如果 skill 附带参考文件，则在首次调用时安全落盘

**它解决的问题：**
打包进 CLI 的技能，也要像磁盘 skill 一样可被调用、可被 Read/Grep 使用参考文件。

**一句话总结：**
> 代码内置技能到命令对象的桥。

---

### 8.5 `source/src/plugins/builtinPlugins.ts`

**作用：** 内建插件注册表与内建插件技能导出器。

它负责：
- 注册 built-in plugins
- 判断启停状态
- 导出内建插件附带的 skill commands

**它解决的问题：**
有些能力不是总该常驻开启，而更适合被建模为可开关的 built-in plugin。

**一句话总结：**
> 内建插件与命令/技能系统之间的桥。

---

### 8.6 `source/src/plugins/bundled/index.ts`

**作用：** bundled plugin 汇总入口。

它负责：
- 汇总打包插件定义
- 供 builtin plugin / marketplace / plugin loader 体系引用

**一句话总结：**
> 打包插件内容的集中入口。

---

### 8.7 `source/src/utils/plugins/loadPluginCommands.ts`

**作用：** 插件 commands / plugin skills 加载器。

它负责：
- 读取 plugin manifest 中的 commandsPath/skillsPath/metadata/inline content
- 收集 markdown 文件
- 解析 frontmatter
- 替换 plugin variables / user config
- 生成 plugin namespace 下的 `Command`

**它解决的问题：**
让插件像一等公民一样提供命令和技能，而不是附属脚本。

**一句话总结：**
> 插件命令与技能的核心装配器。

---

### 8.8 `source/src/skills/mcpSkillBuilders.ts`

**作用：** MCP 资源/skills 到命令对象的适配层。

**它解决的问题：**
MCP 不只是外部工具，还可能带 prompt/skill/resource；这些能力也要进入统一命令面。

**一句话总结：**
> MCP 技能命令构造桥。

---

## 9. `skills/bundled/**` 文件职责说明（逐个总结）

这一组文件都是“内置技能定义文件”。它们不是命令聚合器本身，而是**bundled skill 的内容来源**。

| 相对路径 | 作用总结 |
|---|---|
| `source/src/skills/bundled/index.ts` | 汇总所有 bundled skills 定义 |
| `source/src/skills/bundled/batch.ts` | 批量处理/批量执行场景的内置技能 |
| `source/src/skills/bundled/claudeApi.ts` | 与 Claude API 使用相关的内置技能定义 |
| `source/src/skills/bundled/claudeApiContent.ts` | 为 Claude API 相关技能提供具体内容模板/参考内容 |
| `source/src/skills/bundled/claudeInChrome.ts` | 与 Claude in Chrome 场景相关的内置技能 |
| `source/src/skills/bundled/debug.ts` | 调试问题、排查错误用的内置技能 |
| `source/src/skills/bundled/keybindings.ts` | 快捷键/操作方式说明型技能 |
| `source/src/skills/bundled/loop.ts` | 循环推进、继续执行或迭代处理型技能 |
| `source/src/skills/bundled/loremIpsum.ts` | 示例/测试型技能内容 |
| `source/src/skills/bundled/remember.ts` | 记忆/记录相关的内置技能 |
| `source/src/skills/bundled/scheduleRemoteAgents.ts` | 远程 agent 调度或计划相关技能 |
| `source/src/skills/bundled/simplify.ts` | 简化、重写、压缩信息相关技能 |
| `source/src/skills/bundled/skillify.ts` | 把已有内容或流程整理成技能的内置能力 |
| `source/src/skills/bundled/stuck.ts` | “卡住了怎么办” 类辅助技能 |
| `source/src/skills/bundled/updateConfig.ts` | 配置变更/更新类技能 |
| `source/src/skills/bundled/verify.ts` | 验证结果/核对正确性相关技能 |
| `source/src/skills/bundled/verifyContent.ts` | 给 verify 技能提供附带内容/参考材料 |

> 这一组文件共同作用：
> **为命令系统提供一批内建 prompt/skill 型能力。**

---

## 10. `commands/**` 的功能分组与职责总结

`commands/**` 文件非常多。为了满足你“这个功能块所有涉及文件都要总结作用”的要求，这里先按功能组完整整理。

---

### 10.1 命令系统基础与迁移辅助

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/init.ts` | 命令系统初始化/注册辅助入口之一 |
| `source/src/commands/init-verifiers.ts` | 命令初始化阶段的 verifier 注册或校验辅助 |
| `source/src/commands/createMovedToPluginCommand.ts` | 为已迁移到插件的命令生成兼容/引导命令 |
| `source/src/commands/statusline.tsx` | 状态线相关命令/UI 入口 |
| `source/src/commands/version.ts` | 版本命令实现 |
| `source/src/commands/brief.ts` | brief 模式/简洁输出相关命令 |
| `source/src/commands/advisor.ts` | advisor 相关命令入口 |
| `source/src/commands/insights.ts` | insights 相关命令入口 |
| `source/src/commands/review.ts` | review 相关命令总入口之一 |
| `source/src/commands/security-review.ts` | 安全审查相关命令入口 |
| `source/src/commands/commit.ts` | commit 操作高层命令入口 |
| `source/src/commands/commit-push-pr.ts` | commit + push + PR 一体化命令入口 |
| `source/src/commands/ultraplan.tsx` | ultraplan 类高层命令入口 |

---

### 10.2 目录 / session / workspace 操作类命令

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/add-dir/add-dir.tsx` | 添加目录到工作上下文的命令 UI/逻辑 |
| `source/src/commands/add-dir/index.ts` | add-dir 命令注册入口 |
| `source/src/commands/add-dir/validation.ts` | add-dir 参数与目录合法性校验 |
| `source/src/commands/branch/branch.ts` | 分支切换/分支相关会话命令 |
| `source/src/commands/branch/index.ts` | branch 命令注册入口 |
| `source/src/commands/session/session.tsx` | session 信息/remote session 展示命令 |
| `source/src/commands/session/index.ts` | session 命令注册入口 |
| `source/src/commands/resume/resume.tsx` | resume 会话恢复 UI/逻辑 |
| `source/src/commands/resume/index.ts` | resume 命令注册入口 |
| `source/src/commands/rename/rename.ts` | 重命名 session |
| `source/src/commands/rename/index.ts` | rename 命令注册入口 |
| `source/src/commands/rename/generateSessionName.ts` | 自动生成 session 名称的辅助逻辑 |
| `source/src/commands/tag/tag.tsx` | 给 session 打标签 |
| `source/src/commands/tag/index.ts` | tag 命令注册入口 |
| `source/src/commands/files/files.ts` | 文件列表/文件概览相关命令 |
| `source/src/commands/files/index.ts` | files 命令注册入口 |
| `source/src/commands/copy/copy.tsx` | 复制输出/内容相关命令 |
| `source/src/commands/copy/index.ts` | copy 命令注册入口 |

---

### 10.3 对话 / 上下文治理类命令

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/help/help.tsx` | help 命令 UI 入口 |
| `source/src/commands/help/index.ts` | help 命令注册入口 |
| `source/src/commands/compact/compact.ts` | 手动 compact 的业务控制器 |
| `source/src/commands/compact/index.ts` | compact 命令注册入口 |
| `source/src/commands/context/context.tsx` | 上下文查看命令的交互式版本 |
| `source/src/commands/context/context-noninteractive.ts` | 上下文查看命令的非交互实现 |
| `source/src/commands/context/index.ts` | context 命令注册入口 |
| `source/src/commands/clear/clear.ts` | clear 命令主入口 |
| `source/src/commands/clear/conversation.ts` | 清理对话内容相关逻辑 |
| `source/src/commands/clear/caches.ts` | 清理缓存相关逻辑 |
| `source/src/commands/clear/index.ts` | clear 命令注册入口 |
| `source/src/commands/rewind/rewind.ts` | rewind 历史/回退命令 |
| `source/src/commands/rewind/index.ts` | rewind 命令注册入口 |
| `source/src/commands/memory/memory.tsx` | memory 相关命令 UI/逻辑 |
| `source/src/commands/memory/index.ts` | memory 命令注册入口 |
| `source/src/commands/skills/skills.tsx` | skills 查看/管理命令 |
| `source/src/commands/skills/index.ts` | skills 命令注册入口 |
| `source/src/commands/plan/plan.tsx` | plan 模式/计划相关命令 |
| `source/src/commands/plan/index.ts` | plan 命令注册入口 |

---

### 10.4 设置 / 配置 / 模型 /权限 类命令

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/config/config.tsx` | config 页入口（Settings 子应用） |
| `source/src/commands/config/index.ts` | config 命令注册入口 |
| `source/src/commands/status/status.tsx` | status 页入口（Settings 子应用） |
| `source/src/commands/status/index.ts` | status 命令注册入口 |
| `source/src/commands/model/model.tsx` | 模型切换/模型设置命令 |
| `source/src/commands/model/index.ts` | model 命令注册入口 |
| `source/src/commands/permissions/permissions.tsx` | 权限设置/权限 retry 相关命令 |
| `source/src/commands/permissions/index.ts` | permissions 命令注册入口 |
| `source/src/commands/effort/effort.tsx` | effort 设置命令 |
| `source/src/commands/effort/index.ts` | effort 命令注册入口 |
| `source/src/commands/fast/fast.tsx` | fast mode 切换命令 |
| `source/src/commands/fast/index.ts` | fast 命令注册入口 |
| `source/src/commands/output-style/output-style.tsx` | 输出风格设置命令 |
| `source/src/commands/output-style/index.ts` | output-style 命令注册入口 |
| `source/src/commands/theme/theme.tsx` | 主题设置命令 |
| `source/src/commands/theme/index.ts` | theme 命令注册入口 |
| `source/src/commands/color/color.ts` | 颜色/样式相关设置命令 |
| `source/src/commands/color/index.ts` | color 命令注册入口 |
| `source/src/commands/keybindings/keybindings.ts` | 快捷键设置命令 |
| `source/src/commands/keybindings/index.ts` | keybindings 命令注册入口 |
| `source/src/commands/vim/vim.ts` | vim 模式切换命令 |
| `source/src/commands/vim/index.ts` | vim 命令注册入口 |
| `source/src/commands/privacy-settings/privacy-settings.tsx` | 隐私设置命令 |
| `source/src/commands/privacy-settings/index.ts` | privacy-settings 命令注册入口 |
| `source/src/commands/rate-limit-options/rate-limit-options.tsx` | 限流/配额选项设置命令 |
| `source/src/commands/rate-limit-options/index.ts` | rate-limit-options 注册入口 |
| `source/src/commands/sandbox-toggle/sandbox-toggle.tsx` | 沙箱切换命令 |
| `source/src/commands/sandbox-toggle/index.ts` | sandbox-toggle 注册入口 |

---

### 10.5 登录 / 认证 / 额度 / 账户相关命令

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/login/login.tsx` | 登录命令 UI 与登录完成后的状态切换 |
| `source/src/commands/login/index.ts` | login 命令注册入口 |
| `source/src/commands/logout/logout.tsx` | 登出命令 |
| `source/src/commands/logout/index.ts` | logout 命令注册入口 |
| `source/src/commands/usage/usage.tsx` | usage 使用量命令 |
| `source/src/commands/usage/index.ts` | usage 命令注册入口 |
| `source/src/commands/cost/cost.ts` | cost 成本统计命令 |
| `source/src/commands/cost/index.ts` | cost 命令注册入口 |
| `source/src/commands/passes/passes.tsx` | passes / 配额通行证相关命令 |
| `source/src/commands/passes/index.ts` | passes 命令注册入口 |
| `source/src/commands/extra-usage/extra-usage.tsx` | extra usage 交互式命令 |
| `source/src/commands/extra-usage/extra-usage-noninteractive.ts` | extra usage 非交互命令 |
| `source/src/commands/extra-usage/extra-usage-core.ts` | extra usage 核心业务逻辑 |
| `source/src/commands/extra-usage/index.ts` | extra-usage 命令注册入口 |

---

### 10.6 插件 / MCP / hooks / remote 相关命令

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/plugin/plugin.tsx` | /plugin 命令外层入口 |
| `source/src/commands/plugin/index.tsx` | plugin 命令注册入口 |
| `source/src/commands/plugin/ManagePlugins.tsx` | 已安装插件/MCP 统一管理子应用 |
| `source/src/commands/plugin/BrowseMarketplace.tsx` | 浏览插件市场 UI |
| `source/src/commands/plugin/ManageMarketplaces.tsx` | 管理插件市场源 |
| `source/src/commands/plugin/DiscoverPlugins.tsx` | 发现插件流程 |
| `source/src/commands/plugin/AddMarketplace.tsx` | 添加 marketplace UI |
| `source/src/commands/plugin/PluginErrors.tsx` | 插件错误展示 |
| `source/src/commands/plugin/PluginOptionsDialog.tsx` | 插件配置对话框 |
| `source/src/commands/plugin/PluginOptionsFlow.tsx` | 插件多步配置流程 |
| `source/src/commands/plugin/PluginSettings.tsx` | 插件设置面板 |
| `source/src/commands/plugin/PluginTrustWarning.tsx` | 插件信任警告 UI |
| `source/src/commands/plugin/UnifiedInstalledCell.tsx` | 插件/MCP 统一列表单元渲染 |
| `source/src/commands/plugin/ValidatePlugin.tsx` | 插件校验 UI/流程 |
| `source/src/commands/plugin/parseArgs.ts` | plugin 命令参数解析 |
| `source/src/commands/plugin/pluginDetailsHelpers.tsx` | 插件详情展示辅助逻辑 |
| `source/src/commands/plugin/usePagination.ts` | 插件列表分页 hook |
| `source/src/commands/mcp/mcp.tsx` | /mcp 命令 UI/逻辑入口 |
| `source/src/commands/mcp/index.ts` | mcp 命令注册入口 |
| `source/src/commands/mcp/addCommand.ts` | 添加 MCP server 命令逻辑 |
| `source/src/commands/mcp/xaaIdpCommand.ts` | XAA/IDP 相关 MCP 命令 |
| `source/src/commands/hooks/hooks.tsx` | hooks 管理命令 |
| `source/src/commands/hooks/index.ts` | hooks 命令注册入口 |
| `source/src/commands/reload-plugins/reload-plugins.ts` | 重新加载插件命令 |
| `source/src/commands/reload-plugins/index.ts` | reload-plugins 注册入口 |
| `source/src/commands/bridge/bridge.tsx` | bridge 相关命令 |
| `source/src/commands/bridge/index.ts` | bridge 命令注册入口 |
| `source/src/commands/bridge-kick.ts` | bridge kick 命令入口 |
| `source/src/commands/desktop/desktop.tsx` | desktop 模式/集成命令 |
| `source/src/commands/desktop/index.ts` | desktop 命令注册入口 |
| `source/src/commands/mobile/mobile.tsx` | mobile 模式/集成命令 |
| `source/src/commands/mobile/index.ts` | mobile 命令注册入口 |
| `source/src/commands/ide/ide.tsx` | IDE 集成命令 |
| `source/src/commands/ide/index.ts` | ide 命令注册入口 |
| `source/src/commands/chrome/chrome.tsx` | Chrome 相关命令 |
| `source/src/commands/chrome/index.ts` | chrome 命令注册入口 |
| `source/src/commands/remote-env/remote-env.tsx` | 远端环境查看/管理命令 |
| `source/src/commands/remote-env/index.ts` | remote-env 注册入口 |
| `source/src/commands/remote-setup/remote-setup.tsx` | 远端 setup 命令 UI |
| `source/src/commands/remote-setup/api.ts` | remote-setup API/调用辅助 |
| `source/src/commands/remote-setup/index.ts` | remote-setup 注册入口 |

---

### 10.7 任务 / agent / review / diagnostics 相关命令

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/tasks/tasks.tsx` | tasks 查看/管理命令 |
| `source/src/commands/tasks/index.ts` | tasks 命令注册入口 |
| `source/src/commands/agents/agents.tsx` | agents 查看/管理命令 |
| `source/src/commands/agents/index.ts` | agents 命令注册入口 |
| `source/src/commands/review/reviewRemote.ts` | review remote 流程辅助 |
| `source/src/commands/review/ultrareviewCommand.tsx` | ultra review 命令 UI/逻辑 |
| `source/src/commands/review/ultrareviewEnabled.ts` | ultra review 是否可用判断 |
| `source/src/commands/review/UltrareviewOverageDialog.tsx` | ultra review overage 警告对话框 |
| `source/src/commands/doctor/doctor.tsx` | doctor 诊断命令 |
| `source/src/commands/doctor/index.ts` | doctor 命令注册入口 |
| `source/src/commands/stats/stats.tsx` | stats 统计命令 |
| `source/src/commands/stats/index.ts` | stats 命令注册入口 |
| `source/src/commands/feedback/feedback.tsx` | feedback 反馈命令 |
| `source/src/commands/feedback/index.ts` | feedback 命令注册入口 |
| `source/src/commands/release-notes/release-notes.ts` | release notes 命令 |
| `source/src/commands/release-notes/index.ts` | release-notes 注册入口 |
| `source/src/commands/upgrade/upgrade.tsx` | 升级命令 |
| `source/src/commands/upgrade/index.ts` | upgrade 注册入口 |
| `source/src/commands/heapdump/heapdump.ts` | heapdump 调试命令 |
| `source/src/commands/heapdump/index.ts` | heapdump 注册入口 |
| `source/src/commands/diff/diff.tsx` | diff 查看/展示命令 |
| `source/src/commands/diff/index.ts` | diff 注册入口 |
| `source/src/commands/export/export.tsx` | 导出会话/输出命令 |
| `source/src/commands/export/index.ts` | export 注册入口 |
| `source/src/commands/voice/voice.ts` | voice 相关命令 |
| `source/src/commands/voice/index.ts` | voice 注册入口 |
| `source/src/commands/stickers/stickers.ts` | stickers 相关命令 |
| `source/src/commands/stickers/index.ts` | stickers 注册入口 |
| `source/src/commands/terminalSetup/terminalSetup.tsx` | terminal setup 命令 |
| `source/src/commands/terminalSetup/index.ts` | terminalSetup 注册入口 |
| `source/src/commands/thinkback/thinkback.tsx` | thinkback 命令 |
| `source/src/commands/thinkback/index.ts` | thinkback 注册入口 |
| `source/src/commands/thinkback-play/thinkback-play.ts` | thinkback-play 命令 |
| `source/src/commands/thinkback-play/index.ts` | thinkback-play 注册入口 |
| `source/src/commands/btw/btw.tsx` | btw 相关命令 |
| `source/src/commands/btw/index.ts` | btw 注册入口 |

---

### 10.8 GitHub / App 安装 / 集成引导类命令

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/install-github-app/install-github-app.tsx` | 安装 GitHub App 主流程 UI |
| `source/src/commands/install-github-app/index.ts` | install-github-app 注册入口 |
| `source/src/commands/install-github-app/setupGitHubActions.ts` | 配置 GitHub Actions 的辅助逻辑 |
| `source/src/commands/install-github-app/ApiKeyStep.tsx` | 安装流程中的 API key 步骤 |
| `source/src/commands/install-github-app/CheckExistingSecretStep.tsx` | 检查已有 secret 步骤 |
| `source/src/commands/install-github-app/CheckGitHubStep.tsx` | 检查 GitHub 环境步骤 |
| `source/src/commands/install-github-app/ChooseRepoStep.tsx` | 选择仓库步骤 |
| `source/src/commands/install-github-app/CreatingStep.tsx` | 创建资源步骤 |
| `source/src/commands/install-github-app/ErrorStep.tsx` | 错误展示步骤 |
| `source/src/commands/install-github-app/ExistingWorkflowStep.tsx` | 现有 workflow 检测步骤 |
| `source/src/commands/install-github-app/InstallAppStep.tsx` | 安装 App 步骤 |
| `source/src/commands/install-github-app/OAuthFlowStep.tsx` | OAuth 流程步骤 |
| `source/src/commands/install-github-app/SuccessStep.tsx` | 成功完成步骤 |
| `source/src/commands/install-github-app/WarningsStep.tsx` | 警告说明步骤 |
| `source/src/commands/install-slack-app/install-slack-app.ts` | 安装 Slack App 命令 |
| `source/src/commands/install-slack-app/index.ts` | install-slack-app 注册入口 |
| `source/src/commands/install.tsx` | 通用安装命令/入口 |

---

### 10.9 内部 / 调试 / 迁移 / 特殊命令

这一组大多是内部工具、开发调试、迁移、实验性或 ant-only 命令。

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/ant-trace/index.js` | ant trace 调试命令 |
| `source/src/commands/autofix-pr/index.js` | autofix PR 内部命令 |
| `source/src/commands/backfill-sessions/index.js` | 回填 session 数据的内部命令 |
| `source/src/commands/break-cache/index.js` | 破坏/重置 cache 的调试命令 |
| `source/src/commands/bughunter/index.js` | bughunter 调试命令 |
| `source/src/commands/ctx_viz/index.js` | context visualization 调试命令 |
| `source/src/commands/debug-tool-call/index.js` | 调试单个 tool call |
| `source/src/commands/env/index.js` | 打印/调试环境相关命令 |
| `source/src/commands/good-claude/index.js` | 内部/实验命令 |
| `source/src/commands/issue/index.js` | issue 相关内部命令 |
| `source/src/commands/mock-limits/index.js` | mock 限流/配额命令 |
| `source/src/commands/oauth-refresh/index.js` | 强制 OAuth refresh 调试命令 |
| `source/src/commands/onboarding/index.js` | onboarding 相关内部命令 |
| `source/src/commands/perf-issue/index.js` | 性能问题调试命令 |
| `source/src/commands/reset-limits/index.js` | 重置限制相关命令 |
| `source/src/commands/share/index.js` | share 相关内部命令 |
| `source/src/commands/summary/index.js` | 会话/结果 summary 内部命令 |
| `source/src/commands/teleport/index.js` | teleport 相关内部命令 |
| `source/src/commands/pr_comments/index.ts` | PR comments 相关命令入口 |

---

## 11. plugin 生态支撑文件职责总结（命令系统相关视角）

因为 plugin commands / plugin skills 是命令系统的重要来源，所以这些文件也必须纳入这个功能块的解释范围。

> 注意：这部分不是“插件系统全量深挖”，而是**从命令系统视角**说明它们在 command loading 里的作用。

| 相对路径 | 作用总结 |
|---|---|
| `source/src/utils/plugins/loadPluginCommands.ts` | 插件 commands/skills 的核心加载器 |
| `source/src/utils/plugins/pluginLoader.ts` | 插件装载主入口，供命令加载器获取启用插件 |
| `source/src/utils/plugins/walkPluginMarkdown.ts` | 遍历插件内 markdown 命令/技能文件 |
| `source/src/utils/plugins/pluginDirectories.ts` | 解析插件目录位置 |
| `source/src/utils/plugins/pluginIdentifier.ts` | 插件 ID/命名标识辅助 |
| `source/src/utils/plugins/schemas.ts` | 插件 manifest / 配置 schema |
| `source/src/utils/plugins/pluginOptionsStorage.ts` | 插件 options / user config 持久化 |
| `source/src/utils/plugins/validatePlugin.ts` | 插件合法性校验 |
| `source/src/utils/plugins/pluginPolicy.ts` | 插件策略限制，与命令可见性有关 |
| `source/src/utils/plugins/cacheUtils.ts` | 插件缓存辅助 |
| `source/src/utils/plugins/zipCache.ts` | 插件 zip 缓存 |
| `source/src/utils/plugins/zipCacheAdapters.ts` | zip cache 适配层 |
| `source/src/utils/plugins/managedPlugins.ts` | 受管插件逻辑 |
| `source/src/utils/plugins/marketplaceHelpers.ts` | 插件市场辅助函数 |
| `source/src/utils/plugins/marketplaceManager.ts` | 插件市场管理 |
| `source/src/utils/plugins/officialMarketplace.ts` | 官方市场定义 |
| `source/src/utils/plugins/officialMarketplaceGcs.ts` | 官方市场 GCS 后端支持 |
| `source/src/utils/plugins/officialMarketplaceStartupCheck.ts` | 启动时官方市场检查 |
| `source/src/utils/plugins/pluginAutoupdate.ts` | 插件自动更新 |
| `source/src/utils/plugins/pluginVersioning.ts` | 插件版本管理 |
| `source/src/utils/plugins/pluginBlocklist.ts` | 插件 blocklist |
| `source/src/utils/plugins/pluginFlagging.ts` | 插件标记/风险标记 |
| `source/src/utils/plugins/pluginStartupCheck.ts` | 插件启动校验 |
| `source/src/utils/plugins/performStartupChecks.tsx` | 插件启动检查 UI/流程 |
| `source/src/utils/plugins/refresh.ts` | 刷新插件装载状态 |
| `source/src/utils/plugins/reconciler.ts` | 插件状态协调/对账 |
| `source/src/utils/plugins/dependencyResolver.ts` | 插件依赖解析 |
| `source/src/utils/plugins/installedPluginsManager.ts` | 已安装插件管理 |
| `source/src/utils/plugins/pluginInstallationHelpers.ts` | 插件安装辅助逻辑 |
| `source/src/utils/plugins/headlessPluginInstall.ts` | headless 插件安装路径 |
| `source/src/utils/plugins/parseMarketplaceInput.ts` | 解析 marketplace 输入 |
| `source/src/utils/plugins/installCounts.ts` | 插件安装计数/统计 |
| `source/src/utils/plugins/fetchTelemetry.ts` | 插件拉取/市场相关遥测 |
| `source/src/utils/plugins/hintRecommendation.ts` | 插件提示推荐逻辑 |
| `source/src/utils/plugins/lspRecommendation.ts` | LSP 插件推荐逻辑 |
| `source/src/utils/plugins/gitAvailability.ts` | 检查 git 可用性（插件相关流程需要） |
| `source/src/utils/plugins/addDirPluginSettings.ts` | add-dir 与插件设置联动辅助 |
| `source/src/utils/plugins/loadPluginAgents.ts` | 加载插件提供的 agents |
| `source/src/utils/plugins/loadPluginHooks.ts` | 加载插件 hooks |
| `source/src/utils/plugins/loadPluginOutputStyles.ts` | 加载插件 output styles |
| `source/src/utils/plugins/lspPluginIntegration.ts` | LSP 插件集成 |
| `source/src/utils/plugins/mcpPluginIntegration.ts` | 插件提供的 MCP server 集成 |
| `source/src/utils/plugins/mcpbHandler.ts` | 处理 MCPB/plugin bundle 相关逻辑 |
| `source/src/utils/plugins/orphanedPluginFilter.ts` | 过滤孤儿/失效插件 |

> 这一整组文件的共同作用：
> **支撑 plugin commands / plugin skills 成为命令系统中的稳定来源。**

---

## 12. 命令系统模块的关键设计结论

### 结论 1：命令系统不是静态表，而是多来源聚合平台

不是简单：
- `/help` 对应一个文件
- `/clear` 对应一个文件

而是：
- builtin
- local skills
- bundled skills
- plugin skills
- plugin commands
- MCP prompts/skills
- workflow commands

统一聚合后再对外暴露。

---

### 结论 2：命令协议是强类型三分法

核心命令类型实际上是：

1. `prompt`
2. `local`
3. `local-jsx`

这三种类型把：
- 纯 prompt skill
- 纯逻辑命令
- 带 UI 交互命令

统一进一个体系。

---

### 结论 3：skills 实际上是“可执行 prompt command”

本地 markdown / bundled skill / plugin skill / MCP skill，最后都会变成 `PromptCommand`。

也就是说：

> 命令系统其实是 skill 系统的主要执行面之一。

---

### 结论 4：插件命令不是外挂，而是一级命令来源

插件可以提供：
- commandsPath
- commandsPaths
- skillsPath
- skillsPaths
- commandsMetadata
- inline content

它已经不是“附带脚本”，而是深度接入命令系统。

---

### 结论 5：`commands/**` 更多是“命令实现树”，不是整个命令系统本身

真正的命令系统骨架其实在：
- `types/command.ts`
- `commands.ts`
- `skills/loadSkillsDir.ts`
- `loadPluginCommands.ts`
- `bundledSkills.ts`

`commands/**` 是这些协议与聚合器落地后的具体实现层。

---

## 13. 当前文档的覆盖边界说明

这份文档已经尽量按你的要求做到：

- 给出命令系统完整子架构图
- 给出相对路径索引
- 对这个功能块涉及的文件做职责总结

但有一件事需要明确：

### 当前这一版的“所有涉及文件职责说明”分为两层

#### 第一层：核心文件 = 详细解释
我已经对以下核心文件做了较详细说明：
- `types/command.ts`
- `commands.ts`
- `skills/loadSkillsDir.ts`
- `skills/bundledSkills.ts`
- `plugins/builtinPlugins.ts`
- `utils/plugins/loadPluginCommands.ts`
- `skills/mcpSkillBuilders.ts`

#### 第二层：其余涉及文件 = 功能职责摘要
包括：
- `skills/bundled/**`
- `commands/**`
- `utils/plugins/**`（从命令系统视角）

这些目前是“逐文件一句话职责总结”。

如果你后面要更极致的版本，我下一轮还可以继续把：

> `commands/**` 再拆成按目录逐文件详讲版

也就是从“摘要式职责表”继续升级成“每个文件展开说明”。

---

## 14. 当前子功能块输出结果

本轮已完成：
- **命令系统模块完整子架构图**
- **命令系统动态流程图**
- **命令系统相对路径总索引**
- **命令系统关键文件详细职责说明**
- **命令系统其余涉及文件职责摘要表**

已保存到：
- `cc/cc_learn/14_arch_command_system_framework.md`

---

## 15. 下一步建议

按照这个顺序，最自然的下一个功能块应该是：

### 工具系统模块
建议文件名：
- `cc/cc_learn/15_arch_tool_system_framework.md`

原因：
- 命令系统解决“高层入口”
- 工具系统解决“底层能力面”
- 两者正好构成 Claude Code 用户入口与模型执行入口的双核心

下一份我建议继续做：

> **工具系统模块的完整架构图 + 相对路径索引 + 所有涉及文件职责总结**
