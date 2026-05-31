# 多 Agent 通信深拆 01：AgentTool / fork / run / resume 链

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/37_multi_agent_communication_full_framework.md`
- 当前主题：**AgentTool / fork / run / resume 链深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. leader agent 如何创建子 agent
2. fork / run / resume 的主链如何组织
3. AgentTool 在多 agent 协作里的职责边界

---

## 2. 主链图

```text
leader agent / query runtime
      │
      ▼
AgentTool.tsx
  - 决定调用哪类 agent
      │
      ├── forkSubagent.ts
      │      -> 创建新 agent 分支
      │
      ├── runAgent.ts
      │      -> 真正运行 agent
      │
      └── resumeAgent.ts
             -> 恢复已有 agent
      │
      ▼
spawnMultiAgent.ts / builtInAgents / loadAgentsDir
      │
      ▼
返回 agent handle / task / status / output 回流
```

---

## 3. 关键文件职责

### `source/src/tools/AgentTool/AgentTool.tsx`
- AgentTool 主实现
- 多 agent 调度入口
- 让 leader agent 能发起子 agent 行为

### `source/src/tools/AgentTool/forkSubagent.ts`
- fork 新 agent 分支
- 建立新的 agent runtime 关系

### `source/src/tools/AgentTool/runAgent.ts`
- 真正执行 agent
- 连接 query runtime、任务、输出回流

### `source/src/tools/AgentTool/resumeAgent.ts`
- 恢复已有 agent
- 让多 agent 会话具备可继续性

### `source/src/tools/shared/spawnMultiAgent.ts`
- 多 agent 并发 spawn 的共享编排逻辑

### `source/src/tools/AgentTool/loadAgentsDir.ts`
- 加载自定义 agents

### `source/src/tools/AgentTool/builtInAgents.ts`
- 汇总内建 agent 定义

### `source/src/tools/AgentTool/built-in/*.ts`
- 具体内建 agent（guide/explore/generalPurpose/plan/verification 等）定义

### `source/src/tools/AgentTool/agentToolUtils.ts`
- AgentTool 通用辅助逻辑

### `source/src/tools/AgentTool/agentDisplay.ts`
- agent 展示辅助

### `source/src/tools/AgentTool/agentColorManager.ts`
- agent 颜色/UI 区分辅助

### `source/src/tools/AgentTool/prompt.ts`
- AgentTool prompt/schema

---

## 4. 关键结论

1. **AgentTool 是多 agent 调度入口，不是 agent 本体**
2. **fork / run / resume 是 3 条不同运行路径**
3. **spawnMultiAgent 是多 agent 并发生成的重要共享层**
4. **built-in agents 与 loadAgentsDir 说明 agent 能力既可内建，也可外部加载**
5. **AgentTool 本身更偏 orchestration，而不是任务协作总线；task/message/mailbox 还在下游**
