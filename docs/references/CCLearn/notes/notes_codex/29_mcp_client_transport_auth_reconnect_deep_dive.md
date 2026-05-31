# MCP 深拆 02：Client Transport / Auth / Reconnect

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/27_arch_mcp_full_framework.md`
- 当前主题：**MCP client transport / auth / reconnect 深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. MCP server 是如何按 transport 建连的
2. auth / needs-auth / step-up / session expired 如何处理
3. reconnect / stale connection / cache clear 如何协同

---

## 2. 主链图

```text
ScopedMcpServerConfig
      │
      ▼
services/mcp/client.ts::connectToServer()
  ├── stdio
  ├── sse
  ├── http
  ├── ws
  ├── sdk
  ├── in-process
  └── claudeai-proxy
      │
      ▼
auth / headers / step-up / timeout wrappers
      │
      ▼
connected / failed / needs-auth / pending / disabled
      │
      ▼
reconnect / clear cache / session expired recovery
```

---

## 3. 关键文件职责

### 3.1 `source/src/services/mcp/client.ts`
- 选择 transport 并连接 server
- 处理 auth / needs-auth / session expired / reconnect
- fetch tools/prompts/resources/skills
- MCP tool call timeout / elicitation retry / result processing

### 3.2 `source/src/services/mcp/auth.ts`
- MCP auth 辅助
- 协调 token/header/auth state

### 3.3 `source/src/services/mcp/headersHelper.ts`
- 远程 MCP 请求头动态生成

### 3.4 `source/src/services/mcp/claudeai.ts`
- Claude.ai proxy / connector MCP 路径支持

### 3.5 `source/src/services/mcp/oauthPort.ts`
- OAuth 回调端口辅助

### 3.6 `source/src/services/mcp/xaa.ts`
- XAA 认证支持

### 3.7 `source/src/services/mcp/xaaIdpLogin.ts`
- XAA/IDP 登录流程支撑

### 3.8 `source/src/services/mcp/elicitationHandler.ts`
- MCP 返回 URL elicitation 时的用户确认/重试流程

### 3.9 `source/src/services/mcp/InProcessTransport.ts`
- in-process MCP transport 实现

### 3.10 `source/src/services/mcp/SdkControlTransport.ts`
- SDK control transport 实现

### 3.11 `source/src/services/mcp/vscodeSdkMcp.ts`
- VSCode SDK MCP 接入支持

### 3.12 `source/src/utils/mcpWebSocketTransport.ts`
- MCP WebSocket transport 辅助

---

## 4. 关键结论

1. **MCP client.ts 是运行时连接中枢，transport 选择和 auth 恢复都在这里汇合**
2. **needs-auth 是 MCP 运行态的一等状态，不是普通失败**
3. **session expired 检测与 reconnect/cache clear 形成一套完整恢复闭环**
4. **claudeai-proxy、stdio、in-process、sdk 都是并列 transport 变体**
5. **MCP elicitation 让工具调用可进入“用户确认后继续”模式**
