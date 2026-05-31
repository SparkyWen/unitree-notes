# MCP 深拆 03：Tool / Prompt / Resource / Skill 导入链

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/27_arch_mcp_full_framework.md`
- 当前主题：**MCP tool / prompt / resource / skill 导入链深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. MCP server 连接成功后，能力如何被导入 Claude Code
2. tools / prompts / resources / skills 分别如何进入内部体系
3. MCP tool 调用结果如何映射回主运行时

---

## 2. 导入链总图

```text
MCP connected client
      │
      ├── tools/list
      │      -> tools/MCPTool/**
      │
      ├── prompts/list
      │      -> 命令系统 Command(prompt)
      │
      ├── resources/list
      │      -> ListMcpResourcesTool / ReadMcpResourceTool
      │
      └── skill/resource builders
             -> skills/mcpSkillBuilders.ts
      │
      ▼
最终进入：
  - tools.ts
  - commands.ts
  - query/tool runtime
```

---

## 3. 关键文件职责

### 3.1 `source/src/services/mcp/client.ts`
- `fetchToolsForClient(...)`
- `fetchCommandsForClient(...)`
- `fetchResourcesForClient(...)`
- `fetchMcpSkillsForClient(...)`
- `callMCPToolWithUrlElicitationRetry(...)`
- `processMCPResult(...)`

### 3.2 `source/src/tools/MCPTool/MCPTool.ts`
- 把 MCP tool 包装成内部 Tool
- 让 query/tool runtime 用统一协议调用它

### 3.3 `source/src/tools/ListMcpResourcesTool/ListMcpResourcesTool.ts`
- 暴露 MCP resources 列表查询能力

### 3.4 `source/src/tools/ReadMcpResourceTool/ReadMcpResourceTool.ts`
- 暴露 MCP resource 读取能力

### 3.5 `source/src/tools/McpAuthTool/McpAuthTool.ts`
- 当 server needs-auth 时提供 auth 修复入口

### 3.6 `source/src/skills/mcpSkillBuilders.ts`
- 把 MCP 资源/skill/prompt 构造成命令/技能体系中的对象

### 3.7 `source/src/utils/mcpOutputStorage.ts`
- 持久化大型 MCP 输出
- 防止直接塞爆上下文

### 3.8 `source/src/utils/mcpInstructionsDelta.ts`
- 管理 MCP instructions 的增量变化，用于注入后续 query

### 3.9 `source/src/tools/MCPTool/classifyForCollapse.ts`
- 为 MCP tool 输出提供 collapse/compact 分类支撑

---

## 4. 关键结论

1. **MCP 导入链不是只导工具，还导入 prompts/resources/skills**
2. **MCPTool 让远程能力在运行时看起来像本地 Tool**
3. **MCP prompt 会并入 commands 体系，MCP resource 会并入 resource tools 体系**
4. **大输出持久化和 collapse 分类说明 MCP 已深度接入主运行时治理链**
5. **MCP 能力导入完成后，对 query 来说基本就是“普通内部能力”**
