# Claude Code 代码库学习地图 - 阶段 D 推进：commands/** 与 tools/** 分组索引（Part 1）

- 目标：从“最终必须覆盖所有文件”的要求出发，开始把 `source/src/commands/**` 与 `source/src/tools/**` 做分组索引，并补第一批高频文件的逐文件精讲。
- 说明：这一份不是替代前面的大模块分析，而是为最终的**全量覆盖审计**铺路。

---

## 1. 为什么现在切换到“目录分组覆盖”

前面我已经把主链路的核心模块基本打通了：
- 启动链
- 命令系统中枢
- 工具系统中枢
- query 主循环
- compact/retry
- memory/session restore
- MCP
- model/auth/config

接下来如果继续只按“大模块”讲，会越来越难满足你最初的硬要求：

> 所有文件都必须最终被覆盖，且最后要有文件覆盖审计表。

所以现在开始补第二条线：

1. **目录分组索引**：先把 `commands/**`、`tools/**` 全量分组
2. **分组内逐文件精讲**：每轮补一批
3. **最终 coverage audit**：把所有文件落到所属模块与分析状态上

---

## 2. `source/src/commands/**` 全量分组索引（第一版）

下面是按“命令功能组”做的实际目录分组，不是机械按字母表简单罗列。

### 2.1 核心会话/上下文/导航类命令

| 分组 | 相关文件 |
|---|---|
| 帮助与信息 | `commands/help/help.tsx`, `commands/status/status.tsx`, `commands/stats/stats.tsx`, `commands/usage/usage.tsx`, `commands/version.ts` |
| 会话/恢复/重命名 | `commands/session/session.tsx`, `commands/resume/resume.tsx`, `commands/rename/rename.ts`, `commands/tag/tag.tsx` |
| 清理/压缩/回退 | `commands/clear/*`, `commands/compact/compact.ts`, `commands/rewind/rewind.ts`, `commands/context/*` |
| 输出与复制 | `commands/copy/copy.tsx`, `commands/export/export.tsx`, `commands/output-style/output-style.tsx` |
| 文件与差异 | `commands/files/files.ts`, `commands/diff/diff.tsx` |

### 2.2 权限/模型/配置类命令

| 分组 | 相关文件 |
|---|---|
| 登录/认证 | `commands/login/login.tsx`, `commands/logout/logout.tsx` |
| 权限与模式 | `commands/permissions/permissions.tsx`, `commands/fast/fast.tsx`, `commands/plan/plan.tsx`, `commands/sandbox-toggle/sandbox-toggle.tsx`, `commands/effort/effort.tsx`, `commands/model/model.tsx` |
| 设置与主题 | `commands/config/config.tsx`, `commands/theme/theme.tsx`, `commands/color/color.ts`, `commands/keybindings/keybindings.ts`, `commands/terminalSetup/terminalSetup.tsx`, `commands/privacy-settings/privacy-settings.tsx`, `commands/rate-limit-options/rate-limit-options.tsx` |
| 插件与技能 | `commands/plugin/*`, `commands/skills/skills.tsx`, `commands/reload-plugins/reload-plugins.ts` |
| MCP 管理 | `commands/mcp/*` |

### 2.3 远程/桥接/IDE/设备类命令

| 分组 | 相关文件 |
|---|---|
| Remote/Bridge | `commands/bridge/*`, `commands/bridge-kick.ts`, `commands/remote-env/*`, `commands/remote-setup/*`, `commands/mobile/*`, `commands/desktop/*`, `commands/chrome/*` |
| IDE/LSP 相关 | `commands/ide/*` |

### 2.4 协作/任务/评审类命令

| 分组 | 相关文件 |
|---|---|
| 任务/agent/team | `commands/tasks/tasks.tsx`, `commands/agents/agents.tsx`, `commands/memory/memory.tsx`, `commands/btw/*`, `commands/brief.ts` |
| 评审/Review | `commands/review/*`, `commands/review.ts`, `commands/pr_comments/*` |
| Git / Branch / Commit / Share | `commands/branch/*`, `commands/commit.ts`, `commands/commit-push-pr.ts`, `commands/share/index.js` |

### 2.5 运营/升级/订阅/提示类命令

| 分组 | 相关文件 |
|---|---|
| 升级/发布/doctor | `commands/doctor/*`, `commands/upgrade/*`, `commands/release-notes/*`, `commands/install.tsx`, `commands/install-github-app/*`, `commands/install-slack-app/*` |
| 订阅/额度/extra usage | `commands/extra-usage/*`, `commands/passes/*`, `commands/usage/*`, `commands/cost/*` |
| onboarding / 提示 / 教学 | `commands/onboarding/*`, `commands/voice/*`, `commands/thinkback/*`, `commands/thinkback-play/*` |

### 2.6 内部/实验/ant-only/诊断命令

这一大组文件很多是：
- ant-only
- internal debug
- migration/helper 命令
- 实验路径

例如：
- `commands/ant-trace/index.js`
- `commands/debug-tool-call/index.js`
- `commands/backfill-sessions/index.js`
- `commands/ctx_viz/index.js`
- `commands/mock-limits/index.js`
- `commands/reset-limits/index.js`
- `commands/oauth-refresh/index.js`
- `commands/init-verifiers.ts`
- `commands/security-review.ts`
- `commands/insights.ts`

这些虽然很多不属于普通用户主链，但**不能漏**，后续覆盖审计会单独列出。

---

## 3. `source/src/tools/**` 全量分组索引（第一版）

### 3.1 核心文件/搜索/shell 工具族

| 分组 | 相关文件 |
|---|---|
| Shell 工具 | `tools/BashTool/*`, `tools/PowerShellTool/*` |
| 文件读写 | `tools/FileReadTool/*`, `tools/FileEditTool/*`, `tools/FileWriteTool/*`, `tools/NotebookEditTool/*` |
| 搜索定位 | `tools/GrepTool/*`, `tools/GlobTool/*`, `tools/WebFetchTool/*`, `tools/WebSearchTool/*` |
| REPL / primitive | `tools/REPLTool/*` |

### 3.2 协作 / agent / task 工具族

| 分组 | 相关文件 |
|---|---|
| Agent / Team | `tools/AgentTool/*`, `tools/TeamCreateTool/*`, `tools/TeamDeleteTool/*`, `tools/SendMessageTool/*` |
| Task 系列 | `tools/TaskCreateTool/*`, `tools/TaskGetTool/*`, `tools/TaskListTool/*`, `tools/TaskUpdateTool/*`, `tools/TaskStopTool/*`, `tools/TaskOutputTool/*` |
| 用户交互 | `tools/AskUserQuestionTool/*` |

### 3.3 模式/运行时/工作流工具族

| 分组 | 相关文件 |
|---|---|
| Plan / Worktree 模式 | `tools/EnterPlanModeTool/*`, `tools/ExitPlanModeTool/*`, `tools/EnterWorktreeTool/*`, `tools/ExitWorktreeTool/*` |
| Config / Brief / Skill | `tools/ConfigTool/*`, `tools/BriefTool/*`, `tools/SkillTool/*` |
| Todo / Search meta | `tools/TodoWriteTool/*`, `tools/ToolSearchTool/*`, `tools/SyntheticOutputTool/*` |

### 3.4 MCP / 外部资源 / 调度工具族

| 分组 | 相关文件 |
|---|---|
| MCP | `tools/MCPTool/*`, `tools/McpAuthTool/*`, `tools/ListMcpResourcesTool/*`, `tools/ReadMcpResourceTool/*` |
| Cron / Remote trigger | `tools/ScheduleCronTool/*`, `tools/RemoteTriggerTool/*` |
| LSP | `tools/LSPTool/*` |

### 3.5 共享/测试工具层

| 分组 | 相关文件 |
|---|---|
| shared | `tools/shared/*`, `tools/utils.ts` |
| testing | `tools/testing/TestingPermissionTool.tsx` |

---

## 4. 第一批逐文件精讲：commands 高频核心文件

下面开始对第一批代表性命令做逐文件讲解。这里选的是对整体理解最有帮助的一批：

1. `commands/help/help.tsx`
2. `commands/compact/compact.ts`
3. `commands/login/login.tsx`
4. `commands/mcp/mcp.tsx`
5. `commands/permissions/permissions.tsx`
6. `commands/plugin/plugin.tsx`

---

## 4.1 `source/src/commands/help/help.tsx`

### 文件作用
这是 `/help` 命令的 JSX 命令实现。

### 导出的内容
- `call: LocalJSXCommandCall`

### 主要逻辑
几乎是最简的一类本地 JSX 命令：

```ts
export const call = async (onDone, { options: { commands } }) => {
  return <HelpV2 commands={commands} onClose={onDone} />
}
```

### 输入参数
- `onDone`
- `context.options.commands`

### 返回值
- 一个 `HelpV2` Ink 组件树

### 被谁使用
- `commands.ts` 聚合后，由 slash command dispatcher 调用

### 依赖了谁
- `components/HelpV2/HelpV2.js`
- `types/command.js`

### 在整个系统中的定位
它很好地展示了 `local-jsx` 命令的最简单范式：

> 命令本身不做业务，只把一个 UI 组件挂进当前 Ink 会话。

### 是否值得重点精读
- 业务复杂度低
- 但非常适合用来理解 local-jsx 命令的最小模式

---

## 4.2 `source/src/commands/compact/compact.ts`

### 文件作用
这是 `/compact` 命令的核心实现。

### 导出的内容
- `call: LocalCommandCall`

### 它解决的问题
让用户手动触发 compact，而不是等 autocompact/reactive compact 自动发生。

### 内部执行步骤
高层伪代码：

```ts
call(args, context):
  messages = getMessagesAfterCompactBoundary(messages)
  if no messages -> error

  customInstructions = args.trim()

  if no customInstructions:
    trySessionMemoryCompaction()
    if success:
      clear cached userContext
      runPostCompactCleanup()
      notifyCompaction()
      markPostCompaction()
      suppressCompactWarning()
      return compact result

  if reactive-only mode:
    return compactViaReactive(...)

  microcompactMessages(messages, context)
  compactConversation(messagesForCompact, context, cacheSharingParams, ...)
  setLastSummarizedMessageId(undefined)
  suppressCompactWarning()
  clear userContext cache
  runPostCompactCleanup()
  return compact result
```

### 关键设计点

#### 设计点 1：手动 compact 也先走 session memory compact
如果没有自定义说明，优先尝试更轻量的 session-memory compaction。

#### 设计点 2：reactive-only mode 下，手动 `/compact` 也改走 reactive path
说明“reactive compact”已经不只是被动错误恢复机制，而能成为显式压缩通路。

#### 设计点 3：manual compact 前仍会做 microcompact
这有助于减少 summary 前 token 体积。

#### 设计点 4：displayText 会拼接：
- 查看完整摘要的快捷键
- userDisplayMessage
- model context upgrade 提示

说明命令返回值不只是数据结构，还要考虑用户交互体验。

### 核心辅助函数

#### `compactViaReactive(...)`
- 手动调用 pre-compact hooks
- 并行拿 hook result 与 cache-sharing params
- 调 `reactiveCompactOnPromptTooLong`
- 合并 pre/post compact userDisplayMessage

#### `getCacheSharingParams(...)`
- 重新构建 systemPrompt
- 并取 `getUserContext()` / `getSystemContext()`
- 用于 compact agent prompt cache sharing

### 被谁使用
- `/compact` slash command

### 依赖了谁
- `services/compact/*`
- `context.ts`
- `constants/prompts.ts`
- `utils/systemPrompt.ts`

### 是否值得重点精读
- 非常值得
- 因为它是 query 主循环外、最直接可读的 compact 总控入口

---

## 4.3 `source/src/commands/login/login.tsx`

### 文件作用
这是 `/login` 命令的 JSX/UI 实现。

### 导出的内容
- `call(onDone, context)`
- `Login(props)` 组件

### 主要逻辑
#### 外层 `call(...)`
返回 `<Login onDone=... />`，但在 `onDone(success)` 里做很多 post-login 副作用：

```ts
context.onChangeAPIKey()
context.setMessages(stripSignatureBlocks)
if success:
  resetCostState()
  refreshRemoteManagedSettings()
  refreshPolicyLimits()
  resetUserCache()
  refreshGrowthBookAfterAuthChange()
  clearTrustedDeviceToken()
  enrollTrustedDevice()
  resetBypassPermissionsCheck()
  checkAndDisableBypassPermissionsIfNeeded(...)
  if TRANSCRIPT_CLASSIFIER:
    resetAutoModeGateCheck()
    checkAndDisableAutoModeIfNeeded(...)
  context.setAppState(prev => ({...prev, authVersion: prev.authVersion+1}))
onDone('Login successful' | 'Login interrupted')
```

### 关键设计点

#### 设计点 1：登录后要 strip signature-bearing message blocks
源码注释明确指出：
- thinking / connector_text 等带签名的 blocks 与 API key 绑定
- 换了账号/密钥后，这些旧签名会失效

所以登录后要把它们从当前消息历史里清掉。

这非常关键，也很容易被忽略。

#### 设计点 2：authVersion++
登录成功后递增 `appState.authVersion`，以触发：
- hooks 中 auth-dependent data 重新拉取
- 比如 MCP servers / remote-managed settings / feature flags

#### 设计点 3：登录后不仅是 auth 变化，也是 org/gate/policy 变化
所以会刷新：
- remote managed settings
- policy limits
- GrowthBook
- trusted device enrollment
- bypass/auto mode killswitch checks

这说明登录不是“拿个 token 就完”，而是整个运行时权限环境的切换点。

### UI 组件 `Login(props)`
本体是一个 `Dialog + ConsoleOAuthFlow`：
- title = Login
- onCancel -> `props.onDone(false, mainLoopModel)`
- onDone -> `props.onDone(true, mainLoopModel)`

### 被谁使用
- `/login`

### 依赖了谁
- `ConsoleOAuthFlow`
- trustedDevice bridge
- growthbook / policy / remote settings refresh
- permission killswitch
- `stripSignatureBlocks`

### 是否值得重点精读
- 非常值得
- 因为它把“认证变化如何刷新运行时状态”这件事展现得很集中

---

## 4.4 `source/src/commands/mcp/mcp.tsx`

### 文件作用
这是 `/mcp` 命令的 JSX 命令入口。

### 导出的内容
- `call(onDone, _context, args?)`
- 内部辅助组件 `MCPToggle`

### 它支持的子命令语义
#### 1) `/mcp no-redirect`
- 直接打开 `MCPSettings`

#### 2) `/mcp reconnect <server>`
- 打开 `MCPReconnect`

#### 3) `/mcp enable [target]` / `/mcp disable [target]`
- 走 `MCPToggle`

#### 4) base `/mcp`
- ant 用户默认重定向到 `/plugin` 的 installed/manage tab
- 否则打开 `MCPSettings`

### `MCPToggle` 的关键逻辑
这是一个小 hack 组件，原因源码注释已经说明：
- `toggleMcpServer` 是 context hook 提供的
- 只能在组件里用，不能在普通命令函数里直接拿

#### 执行步骤
```ts
mcpClients = useAppState(s => s.mcp.clients)
toggleMcpServer = useMcpToggleEnabled()
didRun = useRef(false)

useEffect(() => {
  if already ran -> return
  mark didRun
  isEnabling = action === 'enable'
  clients = mcpClients.filter(name !== 'ide')
  toToggle =
    if target === all:
      enable -> currently disabled clients
      disable -> currently enabled clients
    else -> matching by name
  if none:
    onComplete(not found / already enabled/disabled)
  else:
    toggle each server
    onComplete(summary)
})
```

### 关键设计点
- 命令层与 React context 之间的桥接做成了专用组件
- `ide` client 被排除，不参与一般用户 toggle
- “enable all / disable all” 不是盲 toggle，而是先过滤已在目标状态中的服务器

### 被谁使用
- `/mcp`

### 依赖了谁
- `components/mcp/*`
- `services/mcp/MCPConnectionManager.js`
- `PluginSettings`

### 是否值得重点精读
- 很值得
- 因为它展示了命令系统如何把 MCP UI、MCP runtime 和 plugin UI 串起来

---

## 4.5 `source/src/commands/permissions/permissions.tsx`

### 文件作用
这是 `/permissions` 命令。

### 导出的内容
- `call: LocalJSXCommandCall`

### 主要逻辑
```ts
return <PermissionRuleList
  onExit={onDone}
  onRetryDenials={commands => {
    context.setMessages(prev => [
      ...prev,
      createPermissionRetryMessage(commands)
    ])
  }}
/>
```

### 关键设计点
#### 设计点 1：这不是单纯查看权限规则的 UI
它还支持“retry denied commands”：
- 把一个 permission retry meta message 注入当前消息历史
- 让模型下一轮重新尝试/重规划

#### 设计点 2：权限 UI 与 query 主循环是通过消息层耦合的
不是直接命令式调用工具重试，而是：
- UI 生成一条 message
- query loop 下一轮自己读取并继续

这是 Claude Code 很典型的设计风格：
**尽量通过消息/上下文回到主链，而不是旁路直接操作 agent。**

### 被谁使用
- `/permissions`

### 依赖了谁
- `PermissionRuleList`
- `createPermissionRetryMessage`

### 是否值得重点精读
- 中高
- 文件不大，但非常能体现“权限 UI -> 消息驱动重试”这一设计

---

## 4.6 `source/src/commands/plugin/plugin.tsx`

### 文件作用
这是 `/plugin` 命令入口。

### 导出的内容
- `call(onDone, _context, args?)`

### 主要逻辑
非常直接：

```ts
return <PluginSettings onComplete={onDone} args={args} />
```

### 它在系统中的定位
它与 `/help` 一样，属于“轻壳命令”：
- 命令文件本身很薄
- 真正复杂逻辑都在组件树里

### 为什么仍然重要
因为它说明：
- 插件管理能力在命令层是作为完整 JSX Flow 暴露的
- 也意味着 `commands/plugin/*` 子树后续非常值得专门逐文件覆盖

### 被谁使用
- `/plugin`

### 依赖了谁
- `PluginSettings.js`

### 是否值得重点精读
- 作为入口需要看
- 真正复杂度在 `commands/plugin/*` 与相关组件/服务里

---

## 5. 命令系统实现风格总结（从这批文件看）

通过这几类文件，可以归纳出 Claude Code 命令实现的几种典型模式：

### 模式 A：纯 UI 壳命令
例如：
- `help/help.tsx`
- `plugin/plugin.tsx`

特点：
- 文件很薄
- 真正复杂度在组件里

### 模式 B：命令型 orchestrator
例如：
- `compact/compact.ts`

特点：
- 直接编排多个服务层
- 会产生结构化结果返回给主链

### 模式 C：命令 + post-auth/post-state side effects
例如：
- `login/login.tsx`

特点：
- 用户行为完成后，需要刷新整条运行时依赖链

### 模式 D：命令 + UI + 全局状态 hack bridge
例如：
- `mcp/mcp.tsx`

特点：
- 为拿 React context/hook，专门包一个执行型组件

### 模式 E：命令 -> 追加消息 -> 回到 query 主链
例如：
- `permissions/permissions.tsx`

特点：
- 不直接“执行下一步”
- 而是通过 message injection 让 agent loop 自己继续

---

## 6. 本轮已完成分析的文件列表（相对路径）

### 目录级索引覆盖
- `source/src/commands/**`（完成第一版分组索引）
- `source/src/tools/**`（完成第一版分组索引）

### 本轮逐文件精讲
- `source/src/commands/help/help.tsx`
- `source/src/commands/compact/compact.ts`
- `source/src/commands/login/login.tsx`
- `source/src/commands/mcp/mcp.tsx`
- `source/src/commands/permissions/permissions.tsx`
- `source/src/commands/plugin/plugin.tsx`

---

## 7. 本轮未完成但下一轮建议继续分析的模块

1. `commands/plugin/*` 子树逐文件覆盖
2. `commands/status/*`, `commands/config/*`, `commands/session/*`, `commands/resume/*` 逐组覆盖
3. `tools/BashTool/*`, `tools/AgentTool/*`, `tools/MCPTool/*`, `tools/PowerShellTool/*` 子树逐文件覆盖
4. 生成 `commands/**` / `tools/**` 的文件覆盖清单初版
5. 开始最终 `coverage audit` 骨架文档

---

## 8. 当前累计已覆盖文件数 / 总文件数

- 已完成深读与模块级分析：**64 / 1954**
- 已完成路径扫描：**1954 / 1954**

> 这里把本轮新增的 6 个逐文件精讲文件计入深读覆盖。

---

## 9. 当前代码库学习进度

- **整体学习进度：83%**
- **commands/tools 分组覆盖推进度：35%**
- **内容级深读进度：约 64 / 1954**

下一步建议：
- 继续 `commands/**` 高频组覆盖
- 然后转入 `tools/**` 高频子树覆盖
- 最后补全全量文件覆盖表与审计表
