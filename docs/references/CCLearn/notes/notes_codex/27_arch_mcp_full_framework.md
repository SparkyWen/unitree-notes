# Claude Code MCP 相关完整架构图（全量专项版）

- 仓库路径：`cc/claude_code`
- 当前主题：**MCP（Model Context Protocol）相关完整架构：配置、连接、认证、权限、导入、工具/命令/资源、UI、插件集成、运行时恢复**
- 当前目标：
  1. 给出 MCP 相关完整架构图
  2. 给出 MCP 相关相对路径索引
  3. 对这个功能块所有涉及文件总结作用

> 说明：这次不是之前那个“模块级概览版”，而是尽量按你现在要求，把 MCP 相关文件按层完整收拢成一份更完整的专项总文档。

---

## 1. MCP 在 Claude Code 里到底是什么

在 Claude Code 里，MCP 不是一个附加功能，而是：

> **一个一级扩展平台层。**

它同时影响：
- tools
- commands
- resources
- skills
- auth
- policy
- UI
- plugin integration
- runtime reconnect / needs-auth / session expired recovery

Claude Code 对 MCP 的支持不是“能连 server”这么简单，而是一整套：
- 配置发现与合并
- allow/deny/policy/approval
- 多 transport 连接
- OAuth / step-up / needs-auth
- tools/prompts/resources/skills 导入
- tool call / elicitation / output persistence
- UI 管理与重连
- plugin / claude.ai / SDK / in-process server 集成

---

## 2. MCP 完整总架构图

```text
Claude Code MCP 系统
├── A. 入口与命令层
│   ├── entrypoints/mcp.ts
│   ├── cli/handlers/mcp.tsx
│   └── commands/mcp/**
│
├── B. 配置与策略层
│   ├── services/mcp/types.ts
│   ├── services/mcp/config.ts
│   ├── services/mcp/utils.ts
│   ├── services/mcp/channelAllowlist.ts
│   ├── services/mcp/channelPermissions.ts
│   ├── services/mcp/normalization.ts
│   ├── services/mcp/envExpansion.ts
│   ├── services/mcp/officialRegistry.ts
│   └── services/mcpServerApproval.tsx
│
├── C. 认证与连接层
│   ├── services/mcp/auth.ts
│   ├── services/mcp/headersHelper.ts
│   ├── services/mcp/oauthPort.ts
│   ├── services/mcp/xaa.ts
│   ├── services/mcp/xaaIdpLogin.ts
│   ├── services/mcp/claudeai.ts
│   └── services/mcp/client.ts
│
├── D. Transport 与运行时层
│   ├── services/mcp/InProcessTransport.ts
│   ├── services/mcp/SdkControlTransport.ts
│   ├── services/mcp/vscodeSdkMcp.ts
│   ├── utils/mcpWebSocketTransport.ts
│   └── services/mcp/client.ts
│
├── E. 导入与运行能力层
│   ├── tools/MCPTool/**
│   ├── tools/McpAuthTool/**
│   ├── tools/ListMcpResourcesTool/**
│   ├── tools/ReadMcpResourceTool/**
│   ├── skills/mcpSkillBuilders.ts
│   ├── services/mcp/client.ts
│   └── utils/mcpOutputStorage.ts
│
├── F. UI 管理层
│   ├── services/mcp/MCPConnectionManager.tsx
│   ├── services/mcp/useManageMCPConnections.ts
│   ├── components/mcp/**
│   └── commands/mcp/mcp.tsx
│
├── G. Plugin / 内建 / in-process 集成层
│   ├── utils/plugins/mcpPluginIntegration.ts
│   ├── utils/plugins/mcpbHandler.ts
│   ├── plugins/builtinPlugins.ts
│   ├── utils/claudeInChrome/mcpServer.ts
│   └── utils/computerUse/mcpServer.ts
│
└── H. MCP 辅助工具层
    ├── utils/mcp/dateTimeParser.ts
    ├── utils/mcp/elicitationValidation.ts
    ├── utils/mcpValidation.ts
    ├── utils/mcpInstructionsDelta.ts
    └── services/mcp/mcpStringUtils.ts
```

---

## 3. MCP 动态运行流程图

```text
用户启动 /mcp 或运行时初始化
        │
        ▼
[services/mcp/config.ts]
  - 读取 enterprise/user/project/local/plugin/claudeai/dynamic configs
  - 合并、去重、approval、policy filtering
        │
        ▼
[services/mcp/client.ts]
  - connectToServer()
  - 根据 transport 选择 stdio/http/sse/ws/sdk/in-process/claudeai-proxy
  - 处理 auth / needs-auth / session expired / reconnect
        │
        ▼
导入能力
  ├── tools/list -> MCPTool
  ├── prompts/list -> Command
  ├── resources/list -> Resource tools
  └── skill/resource builders -> skill commands
        │
        ▼
query / tools.ts / commands.ts 使用这些 MCP 能力
        │
        ├── 若模型调用 MCP tool
        │      -> tools/MCPTool/MCPTool.ts
        │      -> services/mcp/client.ts::callMCPTool...
        │      -> processMCPResult / output storage / elicitation retry
        │
        └── 若用户操作 /mcp UI
               -> commands/mcp/** + components/mcp/** + MCPConnectionManager
```

---

## 4. 相对路径索引（全量）

下面按层把当前收拢到的 MCP 相关文件全部列出来。

---

### 4.1 入口与命令层

| 相对路径 | 作用 |
|---|---|
| `source/src/entrypoints/mcp.ts` | MCP 入口点 |
| `source/src/cli/handlers/mcp.tsx` | CLI 层 MCP handler |
| `source/src/commands/mcp/addCommand.ts` | 添加 MCP server 命令逻辑 |
| `source/src/commands/mcp/index.ts` | MCP 命令注册入口 |
| `source/src/commands/mcp/mcp.tsx` | /mcp 命令主 UI/逻辑入口 |
| `source/src/commands/mcp/xaaIdpCommand.ts` | XAA/IDP 相关 MCP 命令 |

---

### 4.2 配置与策略层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/mcp/types.ts` | MCP 配置、连接状态、transport 等类型与 schema |
| `source/src/services/mcp/config.ts` | MCP 配置发现、合并、approval、policy 过滤、写入 |
| `source/src/services/mcp/utils.ts` | MCP server 归属、stale cleanup、approval/scope 辅助 |
| `source/src/services/mcp/channelAllowlist.ts` | MCP channel allowlist 规则 |
| `source/src/services/mcp/channelPermissions.ts` | MCP channel 权限逻辑 |
| `source/src/services/mcp/normalization.ts` | MCP 配置/名称/内容正规化 |
| `source/src/services/mcp/envExpansion.ts` | MCP 配置中的环境变量展开 |
| `source/src/services/mcp/officialRegistry.ts` | 官方 MCP registry 元数据支持 |
| `source/src/services/mcpServerApproval.tsx` | 项目级 MCP server approval UI/流程 |

---

### 4.3 认证与连接层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/mcp/auth.ts` | MCP auth 辅助逻辑 |
| `source/src/services/mcp/headersHelper.ts` | MCP 动态 header 注入辅助 |
| `source/src/services/mcp/oauthPort.ts` | MCP OAuth 端口辅助 |
| `source/src/services/mcp/xaa.ts` | XAA 认证支持 |
| `source/src/services/mcp/xaaIdpLogin.ts` | XAA/IDP 登录流程支持 |
| `source/src/services/mcp/claudeai.ts` | Claude.ai connector / proxy MCP 相关支持 |
| `source/src/services/mcp/client.ts` | MCP 连接运行时、能力导入、tool call、needs-auth/reconnect 核心 |

---

### 4.4 Transport 与运行时层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/mcp/InProcessTransport.ts` | in-process MCP transport |
| `source/src/services/mcp/SdkControlTransport.ts` | SDK control transport |
| `source/src/services/mcp/vscodeSdkMcp.ts` | VSCode SDK MCP 集成 |
| `source/src/utils/mcpWebSocketTransport.ts` | MCP WebSocket transport 辅助 |
| `source/src/services/mcp/client.ts` | transport 选择与连接总中枢 |

---

### 4.5 导入与运行能力层

| 相对路径 | 作用 |
|---|---|
| `source/src/tools/MCPTool/MCPTool.ts` | MCP tool wrapper 主实现 |
| `source/src/tools/MCPTool/UI.tsx` | MCPTool UI |
| `source/src/tools/MCPTool/classifyForCollapse.ts` | MCP 输出分类（服务于 collapse/摘要） |
| `source/src/tools/MCPTool/prompt.ts` | MCPTool prompt/schema |
| `source/src/tools/McpAuthTool/McpAuthTool.ts` | MCP auth 修复工具 |
| `source/src/tools/ListMcpResourcesTool/ListMcpResourcesTool.ts` | 列出 MCP resources 的工具 |
| `source/src/tools/ListMcpResourcesTool/UI.tsx` | ListMcpResourcesTool UI |
| `source/src/tools/ListMcpResourcesTool/prompt.ts` | ListMcpResourcesTool prompt/schema |
| `source/src/tools/ReadMcpResourceTool/ReadMcpResourceTool.ts` | 读取 MCP resource 的工具 |
| `source/src/tools/ReadMcpResourceTool/UI.tsx` | ReadMcpResourceTool UI |
| `source/src/tools/ReadMcpResourceTool/prompt.ts` | ReadMcpResourceTool prompt/schema |
| `source/src/skills/mcpSkillBuilders.ts` | 把 MCP skill/resource/prompt 适配进 skills/commands 体系 |
| `source/src/utils/mcpOutputStorage.ts` | MCP 大输出持久化存储 |
| `source/src/utils/mcpInstructionsDelta.ts` | MCP instructions delta 注入 |

---

### 4.6 UI 管理层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/mcp/MCPConnectionManager.tsx` | MCP 连接管理 UI/状态中心 |
| `source/src/services/mcp/useManageMCPConnections.ts` | 管理 MCP connections 的 hook |
| `source/src/components/mcp/CapabilitiesSection.tsx` | MCP 能力区块 UI |
| `source/src/components/mcp/ElicitationDialog.tsx` | MCP elicitation 弹窗 |
| `source/src/components/mcp/MCPAgentServerMenu.tsx` | MCP agent server 菜单 UI |
| `source/src/components/mcp/MCPListPanel.tsx` | MCP server 列表面板 |
| `source/src/components/mcp/MCPReconnect.tsx` | MCP reconnect UI/逻辑 |
| `source/src/components/mcp/MCPRemoteServerMenu.tsx` | 远程 MCP server 菜单 UI |
| `source/src/components/mcp/MCPSettings.tsx` | MCP 设置面板 |
| `source/src/components/mcp/MCPStdioServerMenu.tsx` | stdio MCP server 菜单 UI |
| `source/src/components/mcp/MCPToolDetailView.tsx` | MCP tool 详情视图 |
| `source/src/components/mcp/MCPToolListView.tsx` | MCP tool 列表视图 |
| `source/src/components/mcp/McpParsingWarnings.tsx` | MCP parsing warnings UI |
| `source/src/components/mcp/index.ts` | MCP 组件统一导出 |
| `source/src/components/mcp/utils/reconnectHelpers.tsx` | reconnect 相关 UI 辅助 |

---

### 4.7 Plugin / 内建 / in-process 集成层

| 相对路径 | 作用 |
|---|---|
| `source/src/utils/plugins/mcpPluginIntegration.ts` | 插件提供 MCP server 的集成桥 |
| `source/src/utils/plugins/mcpbHandler.ts` | MCPB / plugin bundle 相关处理 |
| `source/src/plugins/builtinPlugins.ts` | 内建插件注册，其中可含 MCP 相关定义 |
| `source/src/utils/claudeInChrome/mcpServer.ts` | Claude in Chrome 的 in-process MCP server |
| `source/src/utils/computerUse/mcpServer.ts` | Computer Use 的 in-process MCP server |

---

### 4.8 MCP 辅助工具层

| 相对路径 | 作用 |
|---|---|
| `source/src/utils/mcp/dateTimeParser.ts` | MCP 时间/日期解析辅助 |
| `source/src/utils/mcp/elicitationValidation.ts` | MCP elicitation 输入校验 |
| `source/src/utils/mcpValidation.ts` | MCP 配置/内容校验 |
| `source/src/services/mcp/mcpStringUtils.ts` | MCP 字符串辅助工具 |
| `source/src/services/mcp/channelNotification.ts` | MCP channel 通知辅助 |

---

## 5. MCP 主骨架文件详细说明

下面先把真正支撑 MCP 体系的核心文件讲清楚。

---

### 5.1 `source/src/services/mcp/types.ts`

**定位：** MCP 类型与 schema 中枢。

**负责：**
- 定义 transport schema
- 定义 config schema
- 定义 `ScopedMcpServerConfig`
- 定义 `MCPServerConnection` 状态联合类型

**为什么重要：**
MCP 的复杂度很大一部分来自 transport / config / connection state 的多样性，这个文件给整个子系统提供统一类型骨架。

**一句话总结：**
> MCP 子系统的数据模型中心。

---

### 5.2 `source/src/services/mcp/config.ts`

**定位：** MCP 配置发现与准入中枢。

**负责：**
- 读取 enterprise/user/project/local/plugin/claudeai/dynamic sources
- 合并与 dedup
- 项目 approval 状态处理
- allow/deny/policy 过滤
- config add/remove/toggle

**为什么重要：**
MCP 的第一道安全与行为边界不是连接，而是“到底哪些 server 被允许存在”。

**一句话总结：**
> MCP 准入控制和配置总中枢。

---

### 5.3 `source/src/services/mcp/client.ts`

**定位：** MCP 运行时中枢。

**负责：**
- connectToServer()
- 选择 transport
- 处理 auth / needs-auth / session expired / reconnect
- fetch tools / prompts / resources / skills
- callMCPToolWithUrlElicitationRetry()
- processMCPResult()

**为什么重要：**
这是 MCP 从“配置上的 server”变成“运行时能力面”的核心桥梁。

**一句话总结：**
> MCP 从配置到运行能力的主执行器。

---

### 5.4 `source/src/services/mcp/auth.ts`

**定位：** MCP auth 辅助层。

**负责：**
- MCP 相关认证状态、header、auth token 支持逻辑
- 与远程 transport / OAuth / claude.ai 等路径协同

**一句话总结：**
> MCP 认证辅助核心。

---

### 5.5 `source/src/services/mcp/headersHelper.ts`

**定位：** MCP 动态 headers 生成层。

**负责：**
- 基于配置或 helper 动态生成远程 MCP 请求头
- 供 http/sse/ws transport 使用

**一句话总结：**
> 远程 MCP 请求头注入器。

---

### 5.6 `source/src/services/mcp/utils.ts`

**定位：** MCP 运维辅助与归属判断层。

**负责：**
- stale plugin clients 清理
- command/tool/resource 归属判断
- project approval 状态判定
- scope 反查与 display 辅助

**一句话总结：**
> MCP 子系统的运行态辅助层。

---

### 5.7 `source/src/services/mcp/MCPConnectionManager.tsx`

**定位：** MCP 连接管理 UI/状态层。

**负责：**
- 在 UI 中展示与维护 MCP 连接状态
- 协调 reconnect / disabled / needs-auth / connected 等状态

**一句话总结：**
> MCP 管理面的控制台。

---

### 5.8 `source/src/tools/MCPTool/MCPTool.ts`

**定位：** MCP tool wrapper 主实现。

**负责：**
- 把远程 MCP tool 包装成 Claude Code 内部 Tool
- 让 query/tool runtime 像用内建工具一样用 MCP tool

**一句话总结：**
> MCP tool 到本地 Tool 协议的桥。

---

### 5.9 `source/src/tools/McpAuthTool/McpAuthTool.ts`

**定位：** MCP auth 修复工具。

**负责：**
- 当 MCP server 处于 needs-auth 状态时，提供一条工具化修复路径

**一句话总结：**
> MCP needs-auth 的修复入口。

---

### 5.10 `source/src/skills/mcpSkillBuilders.ts`

**定位：** MCP skill / prompt / resource 到命令技能体系的桥。

**负责：**
- 让 MCP 不只提供 tools，还能提供 prompt/skill 风格能力

**一句话总结：**
> MCP 与技能/命令系统之间的桥。

---

## 6. MCP 所有涉及文件逐项职责总结

下面把这次收拢到的 MCP 相关文件全部逐项总结。

---

## 6.1 `services/mcp/**` 全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/mcp/InProcessTransport.ts` | 用于本进程运行 MCP server 的 transport 实现 |
| `source/src/services/mcp/MCPConnectionManager.tsx` | MCP connection 管理 UI/状态层 |
| `source/src/services/mcp/SdkControlTransport.ts` | SDK control transport，用于特定 SDK/控制通道接入 |
| `source/src/services/mcp/auth.ts` | MCP 认证辅助逻辑 |
| `source/src/services/mcp/channelAllowlist.ts` | MCP channel allowlist 规则定义与判断 |
| `source/src/services/mcp/channelNotification.ts` | MCP channel 通知辅助逻辑 |
| `source/src/services/mcp/channelPermissions.ts` | MCP channel 权限控制逻辑 |
| `source/src/services/mcp/claudeai.ts` | Claude.ai connector / proxy 侧的 MCP 集成 |
| `source/src/services/mcp/client.ts` | MCP 连接、导入、调用、重连、needs-auth、session expired 的运行时核心 |
| `source/src/services/mcp/config.ts` | MCP 配置合并、approval、policy 过滤、增删改写核心 |
| `source/src/services/mcp/elicitationHandler.ts` | 处理 MCP URL elicitation / 用户确认流程 |
| `source/src/services/mcp/envExpansion.ts` | MCP 配置中环境变量展开 |
| `source/src/services/mcp/headersHelper.ts` | 远程 MCP 请求头动态生成与 helper 支持 |
| `source/src/services/mcp/mcpStringUtils.ts` | MCP 字符串处理辅助 |
| `source/src/services/mcp/normalization.ts` | MCP 名称/配置/内容的正规化处理 |
| `source/src/services/mcp/oauthPort.ts` | MCP OAuth 回调端口相关辅助 |
| `source/src/services/mcp/officialRegistry.ts` | 官方 MCP registry 元数据与集成 |
| `source/src/services/mcp/types.ts` | MCP 配置、连接状态、transport 等类型与 schema |
| `source/src/services/mcp/useManageMCPConnections.ts` | 管理 MCP 连接的 hook |
| `source/src/services/mcp/utils.ts` | stale cleanup、approval/scope 归属、server 判断等辅助逻辑 |
| `source/src/services/mcp/vscodeSdkMcp.ts` | VSCode SDK MCP 集成适配 |
| `source/src/services/mcp/xaa.ts` | XAA 认证支持 |
| `source/src/services/mcp/xaaIdpLogin.ts` | XAA/IDP 登录流程支持 |

---

## 6.2 `commands/mcp/**` 全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/mcp/addCommand.ts` | 添加 MCP server 的命令逻辑 |
| `source/src/commands/mcp/index.ts` | MCP 命令注册入口 |
| `source/src/commands/mcp/mcp.tsx` | /mcp 命令的主 UI 与业务控制器 |
| `source/src/commands/mcp/xaaIdpCommand.ts` | XAA/IDP 登录或认证相关 MCP 命令 |

---

## 6.3 `components/mcp/**` 全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/components/mcp/CapabilitiesSection.tsx` | 展示 MCP server/tool 能力面 |
| `source/src/components/mcp/ElicitationDialog.tsx` | 在 MCP 需要用户打开 URL/确认时展示对话框 |
| `source/src/components/mcp/MCPAgentServerMenu.tsx` | agent 类 MCP server 菜单 UI |
| `source/src/components/mcp/MCPListPanel.tsx` | MCP server 列表面板 |
| `source/src/components/mcp/MCPReconnect.tsx` | 触发或展示 reconnect 逻辑 |
| `source/src/components/mcp/MCPRemoteServerMenu.tsx` | 远程 MCP server 菜单 UI |
| `source/src/components/mcp/MCPSettings.tsx` | MCP 设置面板 |
| `source/src/components/mcp/MCPStdioServerMenu.tsx` | stdio 类型 MCP server 菜单 UI |
| `source/src/components/mcp/MCPToolDetailView.tsx` | MCP tool 详情视图 |
| `source/src/components/mcp/MCPToolListView.tsx` | MCP tool 列表视图 |
| `source/src/components/mcp/McpParsingWarnings.tsx` | MCP 配置解析告警展示 |
| `source/src/components/mcp/index.ts` | MCP 组件统一导出 |
| `source/src/components/mcp/utils/reconnectHelpers.tsx` | reconnect 相关 UI 辅助工具 |

---

## 6.4 MCP 相关工具文件全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/tools/ListMcpResourcesTool/ListMcpResourcesTool.ts` | 列出 MCP resources 的工具主实现 |
| `source/src/tools/ListMcpResourcesTool/UI.tsx` | ListMcpResourcesTool UI |
| `source/src/tools/ListMcpResourcesTool/prompt.ts` | ListMcpResourcesTool prompt/schema |
| `source/src/tools/MCPTool/MCPTool.ts` | MCP tool wrapper 主实现 |
| `source/src/tools/MCPTool/UI.tsx` | MCPTool UI |
| `source/src/tools/MCPTool/classifyForCollapse.ts` | MCP 输出用于 collapse/压缩分类 |
| `source/src/tools/MCPTool/prompt.ts` | MCPTool prompt/schema |
| `source/src/tools/McpAuthTool/McpAuthTool.ts` | MCP auth 修复工具 |
| `source/src/tools/ReadMcpResourceTool/ReadMcpResourceTool.ts` | 读取 MCP resource 的工具主实现 |
| `source/src/tools/ReadMcpResourceTool/UI.tsx` | ReadMcpResourceTool UI |
| `source/src/tools/ReadMcpResourceTool/prompt.ts` | ReadMcpResourceTool prompt/schema |

---

## 6.5 MCP 相关 utils / integration 文件全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/mcpServerApproval.tsx` | 项目级 MCP server approval UI/流程 |
| `source/src/entrypoints/mcp.ts` | MCP 入口点 |
| `source/src/cli/handlers/mcp.tsx` | MCP CLI handler |
| `source/src/skills/mcpSkillBuilders.ts` | MCP 与 skills/commands 体系的桥接构造器 |
| `source/src/plugins/builtinPlugins.ts` | 内建插件中可能包含 MCP 相关定义 |
| `source/src/utils/plugins/mcpPluginIntegration.ts` | 插件提供 MCP server 的接入桥 |
| `source/src/utils/claudeInChrome/mcpServer.ts` | Claude in Chrome 内建/in-process MCP server |
| `source/src/utils/computerUse/mcpServer.ts` | Computer Use 内建/in-process MCP server |
| `source/src/utils/mcp/dateTimeParser.ts` | MCP 时间/日期解析辅助 |
| `source/src/utils/mcp/elicitationValidation.ts` | MCP elicitation 输入校验 |
| `source/src/utils/mcpInstructionsDelta.ts` | MCP 指令变化增量注入 |
| `source/src/utils/mcpOutputStorage.ts` | MCP 输出持久化存储 |
| `source/src/utils/mcpValidation.ts` | MCP 配置/输入/结构验证 |
| `source/src/utils/mcpWebSocketTransport.ts` | MCP WebSocket transport 辅助 |
| `source/src/utils/plugins/mcpbHandler.ts` | MCPB / plugin bundle 相关处理 |

---

## 7. MCP 体系最关键的设计结论

### 结论 1：MCP 在 Claude Code 里是一级扩展平台，不只是 tools 扩展

它同时扩展：
- tools
- prompts/commands
- resources
- skills
- auth
- UI
- plugin integration

---

### 结论 2：`config.ts` + `client.ts` 是 MCP 的双中枢

- `config.ts`：决定**哪些 server 存在**
- `client.ts`：决定**这些 server 怎么真正运行起来**

---

### 结论 3：MCP 的复杂度主要来自“来源多 + transport 多 + auth 多 + 能力面多”

它比普通 plugin 系统更复杂，因为要同时处理：
- stdio / http / sse / ws / sdk / in-process / claudeai-proxy
- auth / needs-auth / step-up / session expired
- tools / prompts / resources / skills

---

### 结论 4：MCP 的安全边界首先在配置准入层，其次才是运行时连接层

所以一定要先读：
- `types.ts`
- `config.ts`
- `utils.ts`

再去读 `client.ts`。

---

### 结论 5：MCP UI、命令层、工具层、plugin 层都只是同一运行时的不同表面

它们背后共用的是同一套：
- config merge
- connection runtime
- auth / approval / reconnect state
- tool/resource/prompt import

---

## 8. 当前输出结果

本轮已完成：
- **MCP 相关完整架构图**
- **MCP 动态运行流程图**
- **MCP 相对路径全量索引**
- **MCP 主骨架文件详细说明**
- **MCP 相关所有涉及文件职责总结**

已保存到：
- `cc/cc_learn/27_arch_mcp_full_framework.md`

---

## 9. 如果继续深挖 MCP，建议下一步怎么拆

如果你还要继续把 MCP 做到更细，我建议再拆成 4 份：

1. **MCP config merge / approval / policy 深拆**
2. **MCP client transport / auth / reconnect 深拆**
3. **MCP tool/prompt/resource/skill 导入链深拆**
4. **MCP UI 管理面与 plugin/in-process 集成深拆**

如果你愿意，我下一步可以直接继续做：

> **MCP config merge / approval / policy 深拆版**