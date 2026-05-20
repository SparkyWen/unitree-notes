# Claude Code 安全相关全景架构图（深入版）

- 仓库路径：`cc/claude_code`
- 当前主题：**安全相关全景架构（Trust / Permissions / Sandbox / Auth / Policy / MCP Security / Plugin Security / Hook Security / Path & File Safety / Session & Secret Safety）**
- 当前目标：
  1. 彻底深入梳理代码库中**任何安全相关**的整体架构
  2. 给出完整安全架构图
  3. 给出相对路径索引
  4. 对该安全功能块涉及的文件做职责总结

> 说明：安全相关范围非常大，这里不是只做“权限弹窗”或者“auth”某一小块，而是把 Claude Code 里涉及安全边界的关键系统**按安全子域整体收拢**。为了可读性，我会：
>
> - 先给总安全架构图
> - 再按安全子域拆层
> - 再给文件索引与逐项职责总结
>
> 这份文档会尽量覆盖安全主骨架与直接支撑文件。对于纯 UI 外壳或明显外围文件，会用“安全相关职责摘要”方式纳入，而不是每个 React 组件都展开成长文。

---

## 1. Claude Code 的安全，不是单点功能，而是多层防线

Claude Code 的安全体系不是一个单独模块，而是一组相互嵌套的边界：

1. **Workspace Trust 边界**
2. **Tool Permission 边界**
3. **Sandbox / Dangerous Mode 边界**
4. **Settings / Config 来源可信边界**
5. **Auth / Secret / Keychain 边界**
6. **MCP Server / Plugin / Hook 外部扩展边界**
7. **文件系统 / 路径 / 设备路径 / UNC 路径边界**
8. **Remote / Bridge / Session Ingress 边界**
9. **Telemetry / Logging / Redaction 边界**
10. **Session Persistence / Memory Path / Secret 持久化边界**

一句话：

> **Claude Code 的安全架构本质上是一套“多来源输入、多种执行能力、多种外部扩展”的分层信任控制系统。**

---

## 2. 安全总架构图（总览）

```text
Claude Code 安全总架构
├── A. Trust / Workspace 信任边界
│   ├── interactiveHelpers.tsx
│   ├── config.ts
│   └── settings / helper trust gating
│
├── B. Tool Permission 边界
│   ├── Tool.ts
│   ├── services/tools/toolExecution.ts
│   ├── utils/permissions/**
│   ├── hooks/toolPermission/**
│   └── components/permissions/**
│
├── C. Sandbox / Dangerous Mode 边界
│   ├── setup.ts
│   ├── BashTool/**
│   ├── PowerShellTool/**
│   ├── utils/sandbox/**
│   ├── commands/sandbox-toggle/**
│   └── components/sandbox/**
│
├── D. Auth / OAuth / Secret / Credential 边界
│   ├── utils/auth.ts
│   ├── authPortable.ts / authFileDescriptor.ts
│   ├── services/oauth/**
│   ├── services/api/client.ts / withRetry.ts / errors.ts
│   ├── constants/oauth.ts
│   └── keychain / secure storage / provider credential refresh
│
├── E. Settings / Policy / Managed Control 边界
│   ├── utils/settings/**
│   ├── services/policyLimits/**
│   ├── services/remoteManagedSettings/**
│   ├── config.ts
│   └── permissionValidation / pluginOnlyPolicy / managedPath
│
├── F. MCP 安全边界
│   ├── services/mcp/config.ts
│   ├── services/mcp/client.ts
│   ├── services/mcp/auth.ts
│   ├── services/mcp/channelAllowlist.ts
│   ├── services/mcp/channelPermissions.ts
│   ├── services/mcp/headersHelper.ts
│   ├── services/mcp/elicitationHandler.ts
│   ├── services/mcp/normalization.ts
│   ├── services/mcp/utils.ts
│   ├── mcpServerApproval.tsx
│   └── cli/handlers/mcp.tsx / commands/mcp/** / components/mcp/**
│
├── G. Plugin / Hook / Extension 安全边界
│   ├── utils/plugins/**
│   ├── commands/plugin/**
│   ├── utils/hooks/**
│   ├── schemas/hooks.ts
│   └── services/plugins/**
│
├── H. 文件系统 / 路径 / 写入安全边界
│   ├── FileReadTool / FileEditTool / FileWriteTool / NotebookEditTool
│   ├── BashTool path/security/validation
│   ├── PowerShellTool path/security/validation
│   ├── memdir/paths.ts
│   ├── utils/permissions/filesystem.ts
│   ├── settings/validateEditTool.ts
│   └── mcpValidation / SSRF guard / path validation
│
├── I. Remote / Bridge / Session 边界
│   ├── bridge/**
│   ├── remote/**
│   ├── sessionIngress.ts
│   ├── remotePermissionBridge.ts
│   ├── trustedDevice.ts / workSecret.ts / jwtUtils.ts
│   └── background remote preconditions / remoteSession helpers
│
└── J. Observability / Logging / Redaction 安全边界
    ├── services/api/logging.ts / errors.ts
    ├── permissionLogging.ts
    ├── utils/errors.ts
    ├── telemetry/pluginTelemetry.ts
    └── redaction / secret-safe logging helpers（分散在 auth/errors/API/permissions 中）
```

---

## 3. 安全主流程图（从用户输入到真实执行）

```text
用户输入 / 模型输出 tool_use / 外部配置 / plugin / mcp / hook
        │
        ▼
[Trust 边界]
  - 当前 workspace 是否可信？
  - trust 前哪些 helper/settings/env 可以执行？
        │
        ▼
[Settings / Policy 边界]
  - 哪些 source 生效？
  - policy 是否覆盖 user/project/local？
  - plugin-only / managed-only / allow/deny 规则是什么？
        │
        ▼
[Permission 边界]
  - ToolPermissionContext
  - allow/deny/ask rules
  - auto mode / bypass / dangerous mode checks
        │
        ▼
[Sandbox / Command 安全边界]
  - Bash/PowerShell 语义分析
  - read-only / destructive / path validation
  - sandbox enablement / dangerous warnings
        │
        ▼
[外部扩展边界]
  ├── MCP servers: auth / approval / allowlist / URL/headers / step-up
  ├── Plugins: trust / validation / blocklist / policy / options
  └── Hooks: hook config / HTTP/exec hook / SSRF guard / matcher rules
        │
        ▼
[实际执行]
  - toolExecution.ts / runToolUse()
  - canUseTool / permission prompts / sandbox / hooks
        │
        ▼
[结果回流]
  - tool_result / API response / session storage / logging
  - redaction / classified errors / auth-safe persistence
        │
        ▼
[恢复与持续运行]
  - retry / auth refresh / session expired recovery / compact / resume
```

---

## 4. 安全子域拆分

为了更清楚，这里把安全体系拆成 10 个安全子域。

---

### 4.1 子域 A：Workspace Trust / 信任边界

**核心问题：**
- 仓库里的配置和辅助命令，什么时候可以被执行？
- trust 前，哪些来源是不可信的？

**核心文件：**
- `source/src/interactiveHelpers.tsx`
- `source/src/utils/config.ts`
- `source/src/utils/auth.ts`
- `source/src/utils/settings/settings.ts`
- `source/src/setup.ts`

**关键结论：**
- trust dialog 是 workspace trust boundary
- trust 与 tool permission 是两套不同边界
- project/local settings 中的 helper 型配置不能在 trust 前运行

---

### 4.2 子域 B：Tool Permission / 权限边界

**核心问题：**
- 哪个工具能直接跑，哪个要 ask，哪个应该 deny？
- 权限 UI、规则解析、自动模式、dangerous bypass 怎么协作？

**核心文件：**
- `source/src/Tool.ts`
- `source/src/services/tools/toolExecution.ts`
- `source/src/utils/permissions/**`
- `source/src/hooks/toolPermission/**`
- `source/src/components/permissions/**`
- `source/src/commands/permissions/**`

---

### 4.3 子域 C：Sandbox / Dangerous Mode / Shell Security

**核心问题：**
- shell 命令是否危险？
- 是否只读？
- 是否该进 sandbox？
- 是否允许 dangerous skip permissions？

**核心文件：**
- `source/src/tools/BashTool/**`
- `source/src/tools/PowerShellTool/**`
- `source/src/utils/sandbox/**`
- `source/src/commands/sandbox-toggle/**`
- `source/src/components/sandbox/**`
- `source/src/setup.ts`

---

### 4.4 子域 D：Auth / OAuth / Credential Security

**核心问题：**
- API key / OAuth token / keychain / helper command 什么时候可信？
- 401、token stale、cross-process refresh 怎么处理？

**核心文件：**
- `source/src/utils/auth.ts`
- `source/src/utils/authPortable.ts`
- `source/src/utils/authFileDescriptor.ts`
- `source/src/services/oauth/**`
- `source/src/services/api/client.ts`
- `source/src/services/api/withRetry.ts`
- `source/src/services/api/errors.ts`
- `source/src/constants/oauth.ts`

---

### 4.5 子域 E：Settings / Policy / Managed Control

**核心问题：**
- 哪些设置源有资格控制权限、模型、插件、memory path、sandbox 等关键安全行为？
- 企业/远程/MDM 策略怎样覆盖本地设置？

**核心文件：**
- `source/src/utils/settings/**`
- `source/src/services/policyLimits/**`
- `source/src/services/remoteManagedSettings/**`
- `source/src/utils/config.ts`

---

### 4.6 子域 F：MCP 安全边界

**核心问题：**
- 哪些 MCP server 能连？
- 哪些 server 要 approval？
- URL / command / name allow/deny 怎么做？
- step-up auth / needs-auth / session expired 怎么恢复？

**核心文件：**
- `source/src/services/mcp/**`
- `source/src/services/mcpServerApproval.tsx`
- `source/src/commands/mcp/**`
- `source/src/components/mcp/**`
- `source/src/cli/handlers/mcp.tsx`

---

### 4.7 子域 G：Plugin / Hook / Extension 安全边界

**核心问题：**
- 插件是否可信？
- hooks 是否安全？
- marketplace / plugin loading / HTTP hook / exec hook 如何受限？

**核心文件：**
- `source/src/utils/plugins/**`
- `source/src/commands/plugin/**`
- `source/src/utils/hooks/**`
- `source/src/schemas/hooks.ts`
- `source/src/services/plugins/**`

---

### 4.8 子域 H：文件系统 / 路径 / Memory Path / 设备路径安全

**核心问题：**
- 工具能读写哪些路径？
- UNC / device path / root path / memory path override 是否安全？

**核心文件：**
- `source/src/tools/BashTool/pathValidation.ts`
- `source/src/tools/PowerShellTool/pathValidation.ts`
- `source/src/utils/permissions/filesystem.ts`
- `source/src/memdir/paths.ts`
- `source/src/utils/settings/validateEditTool.ts`
- `source/src/utils/mcpValidation.ts`
- `source/src/utils/hooks/ssrfGuard.ts`

---

### 4.9 子域 I：Remote / Bridge / Trusted Device / Session Boundary

**核心问题：**
- 远端 session / trusted device / work secret / JWT / bridge permission callback 如何构成边界？

**核心文件：**
- `source/src/bridge/**`
- `source/src/remote/**`
- `source/src/services/api/sessionIngress.ts`
- `source/src/utils/background/remote/**`

---

### 4.10 子域 J：日志 / 遥测 / Redaction / Error Safety

**核心问题：**
- 错误消息和遥测里如何避免泄露敏感数据？
- requestId / clientRequestId / gateway / auth-safe logging 怎么处理？

**核心文件：**
- `source/src/services/api/logging.ts`
- `source/src/services/api/errors.ts`
- `source/src/hooks/toolPermission/permissionLogging.ts`
- `source/src/utils/errors.ts`
- `source/src/utils/telemetry/pluginTelemetry.ts`

---

## 5. 安全相关相对路径索引（总表）

下面按安全子域列出索引。

---

### 5.1 Trust / Workspace 信任边界

| 相对路径 | 作用 |
|---|---|
| `source/src/interactiveHelpers.tsx` | trust dialog / onboarding / danger prompts 的核心交互落点 |
| `source/src/setup.ts` | dangerous skip permissions 环境校验 / startup trust 相关 setup |
| `source/src/utils/config.ts` | trust dialog 持久状态、project trust inheritance、config 安全读写 |
| `source/src/utils/auth.ts` | trust 前禁止执行 project/local helper 等关键 gating |
| `source/src/utils/settings/settings.ts` | trusted settings source 与 helper 执行安全边界 |

---

### 5.2 Permission / Permissions UI / Rules

| 相对路径 | 作用 |
|---|---|
| `source/src/Tool.ts` | ToolPermissionContext 协议定义 |
| `source/src/services/tools/toolExecution.ts` | 统一权限判断接入点 |
| `source/src/services/tools/toolHooks.ts` | tool hooks 和 permission 决策桥接 |
| `source/src/hooks/toolPermission/PermissionContext.ts` | permission context hook/runtime 层 |
| `source/src/hooks/toolPermission/handlers/coordinatorHandler.ts` | coordinator 模式下的权限处理 |
| `source/src/hooks/toolPermission/handlers/interactiveHandler.ts` | interactive 权限处理 |
| `source/src/hooks/toolPermission/handlers/swarmWorkerHandler.ts` | swarm/worker 权限处理 |
| `source/src/hooks/toolPermission/permissionLogging.ts` | 权限日志记录 |
| `source/src/hooks/useCanUseTool.tsx` | UI/runtime 获取 canUseTool 决策 |
| `source/src/hooks/useSwarmPermissionPoller.ts` | swarm 权限轮询协同 |
| `source/src/commands/permissions/index.ts` | permissions 命令注册 |
| `source/src/commands/permissions/permissions.tsx` | 权限配置/查看 UI |
| `source/src/components/permissions/**` | 各类权限请求 UI / 规则编辑 UI / shell/file/web 权限弹窗 |
| `source/src/utils/permissions/**` | 权限规则解析、路径/命令匹配、分类器、dangerous pattern、filesystem 限制等核心逻辑 |
| `source/src/types/permissions.ts` | 权限领域类型定义 |

---

### 5.3 Sandbox / Shell Security

| 相对路径 | 作用 |
|---|---|
| `source/src/entrypoints/sandboxTypes.ts` | sandbox 相关入口类型定义 |
| `source/src/commands/sandbox-toggle/index.ts` | sandbox-toggle 命令注册 |
| `source/src/commands/sandbox-toggle/sandbox-toggle.tsx` | sandbox 切换 UI/逻辑 |
| `source/src/components/sandbox/**` | sandbox 设置、doctor、依赖、覆盖项 UI |
| `source/src/utils/sandbox/sandbox-adapter.ts` | sandbox 适配层 |
| `source/src/utils/sandbox/sandbox-ui-utils.ts` | sandbox UI 辅助 |
| `source/src/tools/BashTool/**` | Bash 工具的安全、权限、危险命令、路径、sandbox 决策 |
| `source/src/tools/PowerShellTool/**` | PowerShell 工具对应的安全与 sandbox 逻辑 |

---

### 5.4 Auth / OAuth / Credential 安全

| 相对路径 | 作用 |
|---|---|
| `source/src/constants/oauth.ts` | OAuth 常量 |
| `source/src/cli/handlers/auth.ts` | CLI auth handler |
| `source/src/utils/auth.ts` | 认证状态机与 auth source priority 中枢 |
| `source/src/utils/authPortable.ts` | auth 的跨环境/portable 适配 |
| `source/src/utils/authFileDescriptor.ts` | file descriptor 注入 API key / OAuth token 的安全通道 |
| `source/src/services/oauth/auth-code-listener.ts` | OAuth auth-code 回调监听 |
| `source/src/services/oauth/client.ts` | OAuth client 逻辑 |
| `source/src/services/oauth/crypto.ts` | OAuth/认证相关加密辅助 |
| `source/src/services/oauth/getOauthProfile.ts` | 获取 OAuth profile |
| `source/src/services/oauth/index.ts` | OAuth 服务汇总入口 |
| `source/src/services/api/client.ts` | provider-specific client 构造与 auth refresh 前置接入 |
| `source/src/services/api/withRetry.ts` | 401/403/auth stale/refresh/retry 恢复 |
| `source/src/services/api/errors.ts` | auth 错误映射 |

---

### 5.5 Settings / Policy / Managed Control

| 相对路径 | 作用 |
|---|---|
| `source/src/utils/settings/allErrors.ts` | settings 错误汇总 |
| `source/src/utils/settings/applySettingsChange.ts` | settings 变更应用 |
| `source/src/utils/settings/changeDetector.ts` | settings 变化检测 |
| `source/src/utils/settings/constants.ts` | settings sources 常量与优先级 |
| `source/src/utils/settings/internalWrites.ts` | 内部写入辅助 |
| `source/src/utils/settings/managedPath.ts` | managed settings 路径 |
| `source/src/utils/settings/mdm/constants.ts` | MDM settings 常量 |
| `source/src/utils/settings/mdm/rawRead.ts` | 读取 MDM settings |
| `source/src/utils/settings/mdm/settings.ts` | MDM settings 适配 |
| `source/src/utils/settings/permissionValidation.ts` | 权限规则类 settings 的校验 |
| `source/src/utils/settings/pluginOnlyPolicy.ts` | plugin-only policy 逻辑 |
| `source/src/utils/settings/schemaOutput.ts` | settings schema 输出辅助 |
| `source/src/utils/settings/settings.ts` | 多源 settings 合并与 trusted source 边界 |
| `source/src/utils/settings/settingsCache.ts` | settings 缓存 |
| `source/src/utils/settings/toolValidationConfig.ts` | tool validation 配置 |
| `source/src/utils/settings/types.ts` | settings 类型 |
| `source/src/utils/settings/validateEditTool.ts` | EditTool 相关设置校验 |
| `source/src/utils/settings/validation.ts` | settings 通用验证 |
| `source/src/utils/settings/validationTips.ts` | settings 校验提示 |
| `source/src/services/policyLimits/index.ts` | policy limits 主服务 |
| `source/src/services/policyLimits/types.ts` | policy limits 类型 |
| `source/src/services/remoteManagedSettings/index.ts` | 远程托管设置服务 |
| `source/src/services/remoteManagedSettings/securityCheck.tsx` | 远程托管设置安全检查 UI/逻辑 |
| `source/src/services/remoteManagedSettings/syncCache.ts` | remote managed settings 同步缓存 |
| `source/src/services/remoteManagedSettings/syncCacheState.ts` | sync cache 状态 |
| `source/src/services/remoteManagedSettings/types.ts` | remote managed settings 类型 |
| `source/src/services/settingsSync/index.ts` | 设置同步服务 |
| `source/src/services/settingsSync/types.ts` | 设置同步类型 |
| `source/src/utils/config.ts` | global/project config 持久化与 auth-loss guard / trust persistence |
| `source/src/utils/configConstants.ts` | config 常量 |

---

### 5.6 MCP 安全边界

| 相对路径 | 作用 |
|---|---|
| `source/src/entrypoints/mcp.ts` | MCP 入口 |
| `source/src/cli/handlers/mcp.tsx` | CLI MCP handler |
| `source/src/commands/mcp/addCommand.ts` | 安全地添加 MCP server 的命令逻辑 |
| `source/src/commands/mcp/index.ts` | MCP 命令注册 |
| `source/src/commands/mcp/mcp.tsx` | MCP 管理 UI/逻辑 |
| `source/src/commands/mcp/xaaIdpCommand.ts` | XAA/IDP 相关 MCP 命令 |
| `source/src/components/mcp/**` | MCP server/tool 详情、设置、重连、elicitation 等 UI |
| `source/src/services/mcp/InProcessTransport.ts` | in-process MCP transport |
| `source/src/services/mcp/MCPConnectionManager.tsx` | MCP 连接管理 UI/状态层 |
| `source/src/services/mcp/SdkControlTransport.ts` | SDK control transport |
| `source/src/services/mcp/auth.ts` | MCP auth 辅助 |
| `source/src/services/mcp/channelAllowlist.ts` | MCP channel allowlist 规则 |
| `source/src/services/mcp/channelNotification.ts` | MCP 通知通道相关逻辑 |
| `source/src/services/mcp/channelPermissions.ts` | MCP channel 权限控制 |
| `source/src/services/mcp/claudeai.ts` | Claude.ai connector/MCP 相关逻辑 |
| `source/src/services/mcp/client.ts` | MCP 连接运行时、needs-auth、session expired 恢复 |
| `source/src/services/mcp/config.ts` | MCP config merge、approval、allow/deny、policy 过滤 |
| `source/src/services/mcp/elicitationHandler.ts` | MCP URL elicitation / consent 流程 |
| `source/src/services/mcp/envExpansion.ts` | MCP env 展开 |
| `source/src/services/mcp/headersHelper.ts` | MCP 头部辅助、动态 header 注入 |
| `source/src/services/mcp/mcpStringUtils.ts` | MCP 字符串辅助 |
| `source/src/services/mcp/normalization.ts` | MCP 配置/名称/结果正规化 |
| `source/src/services/mcp/oauthPort.ts` | MCP OAuth 端口辅助 |
| `source/src/services/mcp/officialRegistry.ts` | MCP 官方 registry 相关 |
| `source/src/services/mcp/types.ts` | MCP 类型与 schema |
| `source/src/services/mcp/useManageMCPConnections.ts` | 管理 MCP 连接 hook |
| `source/src/services/mcp/utils.ts` | MCP stale cleanup、approval、server-scope 过滤等辅助 |
| `source/src/services/mcp/vscodeSdkMcp.ts` | VSCode SDK MCP 集成 |
| `source/src/services/mcp/xaa.ts` | XAA 认证相关 MCP 支持 |
| `source/src/services/mcp/xaaIdpLogin.ts` | XAA/IDP 登录支持 |
| `source/src/services/mcpServerApproval.tsx` | 项目 MCP server approval UI / 流程 |
| `source/src/skills/mcpSkillBuilders.ts` | MCP skills/prompt builder |
| `source/src/utils/mcp/dateTimeParser.ts` | MCP 数据解析辅助 |
| `source/src/utils/mcp/elicitationValidation.ts` | MCP elicitation 输入校验 |
| `source/src/utils/mcpInstructionsDelta.ts` | MCP 指令变化 delta |
| `source/src/utils/mcpOutputStorage.ts` | MCP 输出存储 |
| `source/src/utils/mcpValidation.ts` | MCP 配置/输入验证 |
| `source/src/utils/mcpWebSocketTransport.ts` | MCP WebSocket transport 辅助 |
| `source/src/tools/MCPTool/**` | MCP tool wrapper 与 collapse 分类 |
| `source/src/tools/McpAuthTool/McpAuthTool.ts` | MCP 认证修复工具 |
| `source/src/tools/ListMcpResourcesTool/**` | MCP resource 列举工具 |
| `source/src/tools/ReadMcpResourceTool/**` | MCP resource 读取工具 |

---

### 5.7 Plugin / Hook / Extension 安全

| 相对路径 | 作用 |
|---|---|
| `source/src/commands/plugin/**` | 插件管理 UI，包含 trust warning / validate / settings / marketplace |
| `source/src/plugins/builtinPlugins.ts` | 内建插件注册表 |
| `source/src/plugins/bundled/index.ts` | bundled plugin 汇总 |
| `source/src/services/plugins/PluginInstallationManager.ts` | 插件安装管理 |
| `source/src/services/plugins/pluginCliCommands.ts` | 插件 CLI 操作 |
| `source/src/services/plugins/pluginOperations.ts` | 插件安装/卸载/更新操作 |
| `source/src/utils/plugins/**` | 插件 loader / policy / validation / marketplace / autoupdate / blocklist / flagging / MCP integration 等 |
| `source/src/commands/reload-plugins/**` | 插件重新加载命令 |
| `source/src/utils/hooks/**` | hook 配置、exec/http/prompt hook、session hook、SSRF guard、watcher 等 |
| `source/src/schemas/hooks.ts` | hooks schema |
| `source/src/commands/hooks/**` | hooks 管理 UI/命令 |
| `source/src/components/hooks/**` | hooks 配置 UI |

---

### 5.8 文件系统 / 路径 / Memory Path 安全

| 相对路径 | 作用 |
|---|---|
| `source/src/tools/BashTool/pathValidation.ts` | Bash 工具的路径安全校验 |
| `source/src/tools/BashTool/bashSecurity.ts` | Bash 命令安全分析 |
| `source/src/tools/BashTool/bashPermissions.ts` | Bash 权限判定 |
| `source/src/tools/BashTool/destructiveCommandWarning.ts` | Bash 危险命令警告 |
| `source/src/tools/BashTool/readOnlyValidation.ts` | Bash 只读命令识别 |
| `source/src/tools/BashTool/sedValidation.ts` | sed 编辑校验 |
| `source/src/tools/BashTool/sedEditParser.ts` | sed 编辑解析 |
| `source/src/tools/BashTool/shouldUseSandbox.ts` | Bash 是否进 sandbox 决策 |
| `source/src/tools/PowerShellTool/pathValidation.ts` | PowerShell 路径安全校验 |
| `source/src/tools/PowerShellTool/powershellSecurity.ts` | PowerShell 安全分析 |
| `source/src/tools/PowerShellTool/powershellPermissions.ts` | PowerShell 权限判定 |
| `source/src/tools/PowerShellTool/destructiveCommandWarning.ts` | PowerShell 危险命令警告 |
| `source/src/tools/PowerShellTool/readOnlyValidation.ts` | PowerShell 只读命令识别 |
| `source/src/tools/PowerShellTool/gitSafety.ts` | PowerShell 场景下 git 安全辅助 |
| `source/src/utils/permissions/filesystem.ts` | 文件系统权限与路径边界核心逻辑 |
| `source/src/utils/permissions/pathValidation.ts` | 权限层路径校验 |
| `source/src/utils/settings/validateEditTool.ts` | EditTool 相关配置/编辑安全校验 |
| `source/src/memdir/paths.ts` | auto-memory path override 的安全边界 |
| `source/src/utils/hooks/ssrfGuard.ts` | HTTP hooks / remote fetch 场景的 SSRF 防护 |
| `source/src/utils/mcpValidation.ts` | MCP config / path / input 验证 |
| `source/src/components/agents/validateAgent.ts` | agent 定义/配置校验 |
| `source/src/keybindings/validate.ts` | keybindings 配置校验 |

---

### 5.9 Remote / Bridge / Trusted Device / Session Boundary

| 相对路径 | 作用 |
|---|---|
| `source/src/bridge/bridgeApi.ts` | bridge API 层 |
| `source/src/bridge/bridgeConfig.ts` | bridge 配置 |
| `source/src/bridge/bridgeDebug.ts` | bridge 调试 |
| `source/src/bridge/bridgeEnabled.ts` | bridge 启用判断 |
| `source/src/bridge/bridgeMain.ts` | bridge 主入口 |
| `source/src/bridge/bridgeMessaging.ts` | bridge 消息通道 |
| `source/src/bridge/bridgePermissionCallbacks.ts` | bridge 权限回调 |
| `source/src/bridge/bridgePointer.ts` | bridge pointer/state 辅助 |
| `source/src/bridge/bridgeStatusUtil.ts` | bridge 状态工具 |
| `source/src/bridge/bridgeUI.ts` | bridge UI 相关 |
| `source/src/bridge/capacityWake.ts` | 容量唤醒/恢复辅助 |
| `source/src/bridge/codeSessionApi.ts` | code session API |
| `source/src/bridge/createSession.ts` | bridge 会话创建 |
| `source/src/bridge/debugUtils.ts` | bridge 调试辅助 |
| `source/src/bridge/envLessBridgeConfig.ts` | env-less bridge 配置 |
| `source/src/bridge/flushGate.ts` | bridge flush / gating |
| `source/src/bridge/inboundAttachments.ts` | bridge 入站 attachment 处理 |
| `source/src/bridge/inboundMessages.ts` | bridge 入站消息处理 |
| `source/src/bridge/initReplBridge.ts` | REPL bridge 初始化 |
| `source/src/bridge/jwtUtils.ts` | bridge JWT 辅助 |
| `source/src/bridge/pollConfig.ts` | bridge polling config |
| `source/src/bridge/pollConfigDefaults.ts` | bridge polling 默认值 |
| `source/src/bridge/remoteBridgeCore.ts` | remote bridge 核心 |
| `source/src/bridge/replBridge.ts` | REPL bridge 主逻辑 |
| `source/src/bridge/replBridgeHandle.ts` | REPL bridge handle |
| `source/src/bridge/replBridgeTransport.ts` | REPL bridge transport |
| `source/src/bridge/sessionIdCompat.ts` | sessionId 兼容层 |
| `source/src/bridge/sessionRunner.ts` | bridge session runner |
| `source/src/bridge/trustedDevice.ts` | trusted device 逻辑 |
| `source/src/bridge/types.ts` | bridge 类型 |
| `source/src/bridge/workSecret.ts` | work secret 管理 |
| `source/src/remote/RemoteSessionManager.ts` | remote session 管理 |
| `source/src/remote/SessionsWebSocket.ts` | remote session WebSocket |
| `source/src/remote/remotePermissionBridge.ts` | remote 权限桥接 |
| `source/src/remote/sdkMessageAdapter.ts` | remote SDK 消息适配 |
| `source/src/services/api/sessionIngress.ts` | session ingress 与 remote session 持久化接口 |
| `source/src/utils/background/remote/preconditions.ts` | remote 背景会话前置条件校验 |
| `source/src/utils/background/remote/remoteSession.ts` | remote session 辅助 |
| `source/src/commands/bridge/**` | bridge 命令与 UI |
| `source/src/commands/bridge-kick.ts` | bridge kick 命令 |
| `source/src/commands/remote-env/**` | remote env 检视 |
| `source/src/commands/remote-setup/**` | remote setup UI/命令 |
| `source/src/cli/remoteIO.ts` | remote IO 适配 |

---

### 5.10 日志 / 遥测 / Redaction / Error Safety

| 相对路径 | 作用 |
|---|---|
| `source/src/services/api/logging.ts` | API 请求/响应/错误/usage/tracing 日志 |
| `source/src/services/api/errors.ts` | 错误信息安全映射 |
| `source/src/hooks/toolPermission/permissionLogging.ts` | 权限事件日志 |
| `source/src/utils/errors.ts` | 通用错误处理辅助 |
| `source/src/utils/telemetry/pluginTelemetry.ts` | 插件相关遥测 |
| `source/src/services/analytics/config.ts` | analytics/config 相关 telemetry 设置 |
| `source/src/services/api/bootstrap.ts` | API telemetry/bootstrap 相关协助 |
| `source/src/services/api/metricsOptOut.ts` | metrics 关闭/隐私选择相关逻辑 |

---

## 6. 核心安全骨架文件详细说明

下面先把真正“撑住整个安全架构”的核心文件讲清楚。

---

### 6.1 `source/src/utils/auth.ts`

**定位：** 认证与凭据安全中枢。

**负责：**
- API key / OAuth token 来源优先级
- trust-gated helper execution
- OAuth refresh 与 cross-process cache invalidation
- AWS/GCP/Bedrock/Vertex/Foundry credential refresh
- account/subscription / org validation
- secure storage / keychain 读取

**安全意义：**
这是 Claude Code 里最关键的秘密材料边界之一。它决定：
- 哪些凭据可用
- 什么时候能用
- 哪些 repo-level 配置不能偷偷影响 auth

**一句话总结：**
> Claude Code 的认证安全状态机。

---

### 6.2 `source/src/utils/settings/settings.ts`

**定位：** 多源 settings 与 trusted source 安全边界中枢。

**负责：**
- user/project/local/flag/policy settings merge
- trusted-only helper 查询
- permission / plugin / model / memory path / sandbox 相关设置合并
- policy first-source-wins 语义

**安全意义：**
系统的大量安全行为最终都来自 settings，而这文件决定了：
- 谁说了算
- 谁不该有资格说了算

**一句话总结：**
> 安全配置来源的总裁判。

---

### 6.3 `source/src/utils/config.ts`

**定位：** global/project config 与 trust persistence 安全中枢。

**负责：**
- global config / project config 读写
- trust dialog persisted state
- auth-loss guard
- config corruption backup/recovery
- watch freshness / lock / stale write guard

**安全意义：**
如果 config 读写不安全，凭据、trust 状态、project settings 很容易被损坏或误覆盖。

**一句话总结：**
> 本地安全状态持久化守门员。

---

### 6.4 `source/src/services/tools/toolExecution.ts`

**定位：** 工具权限与执行安全中枢。

**负责：**
- schema validation
- semantic validation
- pre/post hooks
- permission decision
- deny/allow/ask
- tool.call 前后的安全边界整合

**安全意义：**
所有工具最后都要从这里经过；它是“真正落地执行前”的最后总闸门。

**一句话总结：**
> 工具执行安全总阀门。

---

### 6.5 `source/src/utils/permissions/**`

**定位：** 权限规则与风险分类核心。

**负责：**
- PermissionMode / PermissionRule / parser / loader
- shell rule matching
- filesystem restrictions
- dangerousPatterns
- classifierDecision / bashClassifier / yoloClassifier
- denialTracking / autoModeState / shadowed rule detection

**安全意义：**
这是 Claude Code 权限系统的规则引擎层。

**一句话总结：**
> 权限系统的规则引擎与风险识别层。

---

### 6.6 `source/src/services/mcp/config.ts`

**定位：** MCP server 安全准入中心。

**负责：**
- config merge
- enterprise / managed / project / plugin / claude.ai source precedence
- allowlist / denylist / policy filtering
- project MCP approval
- duplicate suppression

**安全意义：**
MCP 是外部扩展能力面，配置层准入是第一道防线。

**一句话总结：**
> MCP 扩展面的准入控制中心。

---

### 6.7 `source/src/services/mcp/client.ts`

**定位：** MCP runtime 安全执行中枢。

**负责：**
- transport connection
- auth / needs-auth / step-up / session expired recovery
- tool/prompt/resource import
- MCP tool call timeout / retry / elicitation

**安全意义：**
这是外部 MCP server 真正接入运行时的安全桥。

**一句话总结：**
> MCP 运行时的安全接入器。

---

### 6.8 `source/src/tools/BashTool/**` 与 `source/src/tools/PowerShellTool/**`

**定位：** shell 执行安全中枢。

**负责：**
- 命令语义分类
- destructive/read-only 判断
- path validation
- permissions / shell security
- sandbox usage 决策

**安全意义：**
shell 是系统中最强的执行能力，也是最大风险点。

**一句话总结：**
> Claude Code 最强能力面的安全护栏。

---

### 6.9 `source/src/utils/hooks/**`

**定位：** hooks 外部执行安全边界。

**负责：**
- hook config / matcher / event registration
- exec/http/prompt hooks
- SSRF guard
- session hooks / post-sampling hooks
- skill hooks registration

**安全意义：**
hooks 是用户自定义的强扩展能力，天然带外部执行与网络风险。

**一句话总结：**
> 用户自定义自动化的安全边界层。

---

### 6.10 `source/src/bridge/**` 与 `source/src/remote/**`

**定位：** remote / trusted-device / session bridge 安全边界。

**负责：**
- bridge transports
- permission callbacks
- trustedDevice / workSecret / JWT / inbound gating
- remote permission bridge
- remote session manager

**安全意义：**
Claude Code 的远端/桥接能力本质上是跨设备/跨环境信任传递，必须有单独安全边界。

**一句话总结：**
> 跨设备与远端会话的信任边界层。

---

## 7. “所有涉及文件”的职责总结说明

这份安全文档的范围远大于前几个功能块，因为安全横切全仓。
所以这里的“所有涉及文件”采用两层粒度：

### 第一层：安全主骨架文件
上面已做较详细说明，主要包括：
- `auth.ts`
- `settings.ts`
- `config.ts`
- `toolExecution.ts`
- `utils/permissions/**`
- `services/mcp/config.ts`
- `services/mcp/client.ts`
- `BashTool/**`
- `PowerShellTool/**`
- `utils/hooks/**`
- `bridge/**` / `remote/**`

### 第二层：安全相关支撑文件
上面在索引表中已经逐项给出职责摘要，包括：
- UI 组件
- 命令入口
- schema / types / validation 文件
- plugin / marketplace / policy / sync / telemetry 相关文件

这已经覆盖了当前扫描出的安全相关主文件和直接支撑文件。

---

## 8. 安全架构的五个总判断

### 判断 1：Claude Code 的安全设计是“trust + permission + policy + sandbox”四层叠加，而不是单一授权框

### 判断 2：repo-level config 默认不可信，这个原则贯穿 helper 执行、memory path、dangerous mode、project MCP approvals 等多个系统

### 判断 3：MCP、plugin、hooks 是三大外部扩展风险面，每一块都有自己独立的准入与执行边界

### 判断 4：shell 工具是最高风险执行面，因此 Bash/PowerShell 的安全逻辑明显比其他工具复杂得多

### 判断 5：远端/bridge/session ingress 不是普通功能扩展，而是新的信任边界，因此单独有 trustedDevice / workSecret / permissionBridge / JWT 体系

---

## 9. 当前输出结果

本轮已完成：
- **安全相关完整全景架构图**
- **安全主流程图**
- **安全子域拆分图**
- **安全相关相对路径索引**
- **安全骨架文件详细说明**
- **安全相关涉及文件职责总结**

已保存到：
- `cc/cc_learn/19_arch_security_full_framework.md`

---

## 10. 建议的下一步（如果继续深挖安全）

如果你还要继续沿安全方向深入，我建议再拆成 4 份细化文档：

1. **权限系统深拆**
   - `utils/permissions/**`
   - `components/permissions/**`
   - `toolExecution.ts`

2. **认证与凭据安全深拆**
   - `auth.ts`
   - `services/oauth/**`
   - `services/api/client.ts` / `withRetry.ts`

3. **MCP / Plugin / Hook 扩展安全深拆**
   - `services/mcp/**`
   - `utils/plugins/**`
   - `utils/hooks/**`

4. **Remote / Bridge / Trusted Device 安全深拆**
   - `bridge/**`
   - `remote/**`
   - `sessionIngress.ts`

如果你愿意，我下一步可以直接继续做：

> **权限系统安全深拆版**

因为它是整个安全体系里最核心、最落地、也是和工具执行绑定最紧的一层。