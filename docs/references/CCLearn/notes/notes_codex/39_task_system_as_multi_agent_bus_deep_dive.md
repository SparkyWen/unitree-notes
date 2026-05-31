# 多 Agent 通信深拆 02：Task 体系作为协作总线

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/37_multi_agent_communication_full_framework.md`
- 当前主题：**Task 体系作为多 agent 协作总线的深拆**

---

## 1. 为什么 task 是协作总线

在 Claude Code 的多 agent 协作里，真正稳定的协作对象往往不是直接 message，而是：

> **task 这个中间对象。**

因为 task 可以：
- 被创建
- 被查询
- 被更新
- 被列举
- 被停止
- 有独立 output

所以它天然适合做多 agent 协作总线。

---

## 2. 主链图

```text
leader / coordinator / agent
      │
      ▼
TaskCreateTool
  -> 创建 task
      │
      ▼
worker / teammate / subagent 处理 task
      │
      ├── TaskUpdateTool
      ├── TaskGetTool
      ├── TaskListTool
      ├── TaskOutputTool
      └── TaskStopTool
      │
      ▼
TaskAssignmentMessage / hooks/useTasksV2 / useTaskListWatcher
      │
      ▼
leader 看到状态、输出、完成度，再继续调度其他 agent
```

---

## 3. 关键文件职责

### `source/src/tools/TaskCreateTool/TaskCreateTool.ts`
- 创建 task
- 是协作总线的入口

### `source/src/tools/TaskGetTool/TaskGetTool.ts`
- 查询单个 task 状态

### `source/src/tools/TaskListTool/TaskListTool.ts`
- 列出 tasks
- 让 leader 能看到整体协作面板

### `source/src/tools/TaskUpdateTool/TaskUpdateTool.ts`
- 更新 task 状态/内容
- 是 worker 回报进度的重要入口

### `source/src/tools/TaskStopTool/TaskStopTool.ts`
- 停止 task
- 让 leader 能终止协作分支

### `source/src/tools/TaskOutputTool/TaskOutputTool.tsx`
- 查看 task 输出
- 把 task 结果显式回流给运行时和 UI

### `source/src/components/messages/TaskAssignmentMessage.tsx`
- task assignment 的消息展示

### `source/src/hooks/useTasksV2.ts`
- tasks 相关的 runtime hook

### `source/src/hooks/useTaskListWatcher.ts`
- 监听 task list 变化

---

## 4. 关键结论

1. **task 不是附属物，而是多 agent 协作的核心共享对象**
2. **TaskCreate/Get/List/Update/Stop/Output 这组工具共同构成了 task 总线协议面**
3. **message 更像局部通知，task 更像结构化协作实体**
4. **UI hooks 和 assignment message 说明 task 同时服务于 runtime 与界面层**
5. **如果要理解 Claude Code 的 agent 协作，task 体系必须优先于 mailbox 单独理解**
