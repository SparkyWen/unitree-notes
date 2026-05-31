# MCP 深拆 04：UI 管理面与 Plugin / In-Process 集成

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/27_arch_mcp_full_framework.md`
- 当前主题：**MCP UI 管理面与 plugin / in-process 集成深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. /mcp UI 和 MCP 管理面是怎么组织的
2. plugin 如何向系统注入 MCP servers
3. in-process MCP servers（Claude in Chrome / Computer Use）如何接入

---

## 2. 管理面总图

```text
用户进入 /mcp
      │
      ▼
commands/mcp/mcp.tsx
      │
      ▼
services/mcp/MCPConnectionManager.tsx
  + useManageMCPConnections.ts
      │
      ▼
components/mcp/**
  - list panel
  - tool detail
  - settings
  - reconnect
  - elicitation dialog
      │
      ├── plugin 注入 MCP servers
      │      -> utils/plugins/mcpPluginIntegration.ts
      │      -> utils/plugins/mcpbHandler.ts
      │
      └── in-process MCP servers
             -> utils/claudeInChrome/mcpServer.ts
             -> utils/computerUse/mcpServer.ts
```

---

## 3. 关键文件职责

### 3.1 `source/src/commands/mcp/mcp.tsx`
- /mcp 命令主入口
- 把 MCP 运行态管理暴露给用户

### 3.2 `source/src/services/mcp/MCPConnectionManager.tsx`
- 管理 MCP 连接状态与管理面逻辑

### 3.3 `source/src/services/mcp/useManageMCPConnections.ts`
- 管理 MCP 连接的 hook，连接 UI 与 runtime

### 3.4 `source/src/components/mcp/**`
- MCP 列表、详情、settings、reconnect、elicitation dialog 等 UI 组件群

### 3.5 `source/src/utils/plugins/mcpPluginIntegration.ts`
- 插件向系统注入 MCP servers 的集成桥

### 3.6 `source/src/utils/plugins/mcpbHandler.ts`
- MCPB / plugin bundle 相关处理逻辑

### 3.7 `source/src/plugins/builtinPlugins.ts`
- 内建插件里可包含 MCP 相关能力定义

### 3.8 `source/src/utils/claudeInChrome/mcpServer.ts`
- Claude in Chrome 的 in-process MCP server 实现/接入桥

### 3.9 `source/src/utils/computerUse/mcpServer.ts`
- Computer Use 的 in-process MCP server 实现/接入桥

---

## 4. 关键结论

1. **/mcp 不是单纯配置页，而是 MCP runtime 的控制面**
2. **plugin integration 让 MCP server 也能成为插件生态的一部分**
3. **in-process MCP server 说明 MCP 不只连接外部进程，也可内嵌到 Claude Code 自身能力中**
4. **MCP 管理面其实是配置层、连接层、导入层的统一可视化表面**
5. **MCP UI 层与 runtime 层是强耦合的，不是纯展示壳**
