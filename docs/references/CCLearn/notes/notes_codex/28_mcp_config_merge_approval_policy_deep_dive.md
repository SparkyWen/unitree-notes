# MCP 深拆 01：Config Merge / Approval / Policy

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/27_arch_mcp_full_framework.md`
- 当前主题：**MCP config merge / approval / policy 深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. MCP server 配置从哪里来
2. 这些来源如何 merge / 覆盖 / 去重
3. project MCP server 为什么需要 approval
4. allow/deny/policy 如何在配置层拦截 MCP surface

---

## 2. 主链图

```text
enterprise/user/project/local/plugin/claudeai/dynamic
        │
        ▼
services/mcp/types.ts
  - 定义 config schema / scope / transport 结构
        │
        ▼
services/mcp/config.ts
  - 读取各 source
  - validate
  - dedup
  - approval gating
  - allow/deny/policy filtering
        │
        ▼
services/mcp/utils.ts
  - project approval 状态
  - stale cleanup
  - scope/归属判断
        │
        ▼
最终得到 ScopedMcpServerConfig map
```

---

## 3. 关键文件职责

### 3.1 `source/src/services/mcp/types.ts`
- 定义 MCP config schema、scope、transport、connection state
- 为 config merge/policy 提供统一数据模型

### 3.2 `source/src/services/mcp/config.ts`
- 读取与合并 enterprise/user/project/local/plugin/claudeai/dynamic configs
- dedup plugin servers / claude.ai connectors
- 应用 allow/deny/policy
- 处理 project MCP server approval
- 支持 add/remove/toggle/write config

### 3.3 `source/src/services/mcp/utils.ts`
- 计算 project MCP server 状态（approved/rejected/pending）
- stale plugin client 清理
- tool/command/resource/server scope 归属判断

### 3.4 `source/src/services/mcp/channelAllowlist.ts`
- 定义/判断 channel 级 allowlist 规则

### 3.5 `source/src/services/mcp/channelPermissions.ts`
- 处理 channel 级权限逻辑

### 3.6 `source/src/services/mcp/normalization.ts`
- 对配置与 server 表述做正规化，便于 dedup 与比较

### 3.7 `source/src/services/mcp/envExpansion.ts`
- 对配置中的环境变量做展开

### 3.8 `source/src/services/mcp/officialRegistry.ts`
- 提供官方 registry 相关元数据，用于配置发现与展示

### 3.9 `source/src/services/mcpServerApproval.tsx`
- project MCP server approval 的 UI/交互入口

---

## 4. 关键结论

1. **MCP 配置 merge 的第一关键不是连接，而是“谁有资格进入最终 config map”**
2. **project `.mcp.json` 不是自动信任的，必须经过 approval 语义**
3. **policy filtering 在配置层就发生，避免不该存在的 server 进入运行时**
4. **plugin / claude.ai / manual MCP server 要做签名级 dedup，不只是比名字**
5. **config.ts 是 MCP 安全与可见性的第一道防线**
