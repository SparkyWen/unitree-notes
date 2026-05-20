# 多 Agent 通信系统 — 全部代码深度分析

---

## 一、概览

| 指标 | 值 |
|------|-----|
| 涉及文件 | ~25 个核心通信文件 |
| 总代码行数 | ~10,000+ 行 |
| 通信机制 | 文件 Mailbox + 内存队列 + UI Bridge + 结构化消息 |
| 参与角色 | Leader（主线程）、Worker（子进程）、InProcess Teammate（进程内） |

---

## 二、通信架构全景

```
┌═══════════════════════════════════════════════════════════════════════════════┐
│                         多 Agent 通信架构全景                                 │
│                                                                               │
│  ┌─────────────────────────────────┐                                         │
│  │ Leader (主线程/团队领导)         │                                         │
│  │                                  │                                         │
│  │  REPL.tsx                        │                                         │
│  │  ├── useInboxPoller (1s轮询)    │ ←── 文件 Mailbox ──── Worker 进程       │
│  │  ├── useSwarmPermissionPoller   │                                         │
│  │  ├── leaderPermissionBridge     │ ←── 内存直连 ──── InProcess Teammate    │
│  │  ├── messageQueueManager       │                                         │
│  │  └── PermissionRequest UI       │                                         │
│  └────────┬──────────┬─────────────┘                                         │
│           │          │                                                        │
│    ┌──────▼──┐  ┌────▼────────┐                                              │
│    │Mailbox  │  │ 内存直连     │                                              │
│    │(文件)   │  │ (同进程)     │                                              │
│    └──┬───┬──┘  └──┬──────────┘                                              │
│       │   │        │                                                          │
│  ┌────▼─┐ │   ┌────▼───────────────┐                                         │
│  │Worker│ │   │InProcess Teammate   │                                         │
│  │(tmux │ │   │                     │                                         │
│  │进程) │ │   │ inProcessRunner.ts  │                                         │
│  │      │ │   │ ├── leaderConfirmQ  │ → Leader 的 PermissionRequest UI        │
│  │      │ │   │ ├── waitForPrompt   │ → Mailbox 轮询                         │
│  │      │ │   │ └── idleNotify      │ → Mailbox 写入                         │
│  └──────┘ │   └─────────────────────┘                                         │
│           │                                                                    │
│    ┌──────▼──────┐                                                            │
│    │Worker (iTerm│                                                            │
│    │ 进程)       │                                                            │
│    └─────────────┘                                                            │
│                                                                               │
│  通信通道:                                                                    │
│  ═══ 文件 Mailbox: ~/.claude/teams/{team}/inboxes/{agent}.json               │
│  ─── 内存直连: leaderPermissionBridge (module-level 注册)                     │
│  ─── 内存队列: messageQueueManager + pendingMessages                          │
│  ─── 结构化消息: JSON 中 type 字段区分消息类型                                │
└═══════════════════════════════════════════════════════════════════════════════┘
```

---

## 三、通信通道详解

### 通道 1: 文件 Mailbox (`teammateMailbox.ts`, 1183行)

**机制**: 每个 agent 有一个 JSON 文件作为收件箱，其他 agent 通过文件锁安全追加消息。

```
路径: ~/.claude/teams/{team_name}/inboxes/{agent_name}.json

文件格式 (JSON 数组):
[
  {
    "from": "team-lead",
    "text": "请检查 src/foo.ts 的测试覆盖率",
    "timestamp": "2026-04-04T10:00:00.000Z",
    "read": false,
    "color": "blue",
    "summary": "检查测试覆盖率"
  },
  {
    "from": "worker-1",
    "text": "{\"type\":\"permission_request\",\"id\":\"perm_123\",...}",
    "timestamp": "2026-04-04T10:01:00.000Z",
    "read": false
  }
]
```

**核心函数**:

```
writeToMailbox(recipientName, message, teamName?):
├── ensureInboxDir() → 确保目录存在
├── lockfile.lock(inboxPath) → 获取文件锁
│   ├── retries: 10次
│   ├── minTimeout: 5ms
│   └── maxTimeout: 100ms
├── readMailbox() → 重新读取（锁后读取最新状态）
├── messages.push({ ...message, read: false })
├── writeFile(inboxPath, JSON) → 写入
└── release() → 释放文件锁

readUnreadMessages(agentName, teamName?):
├── readMailbox(agentName) → 读取所有消息
└── messages.filter(m => !m.read) → 只返回未读

markMessageAsReadByIndex(agentName, teamName, index):
├── lockfile.lock → 获取锁
├── readMailbox → 重新读取
├── messages[index].read = true
├── writeFile → 写入
└── release → 释放锁

markMessagesAsRead(agentName, teamName?):
├── lockfile.lock → 获取锁
├── readMailbox → 重新读取
├── for (m of messages) m.read = true
├── writeFile → 写入
└── release → 释放锁
```

**结构化消息类型**（通过 `text` 字段中的 JSON 编码）:

```
消息类型辨别:

[1] 普通文本消息
    text: "请做这件事..." (纯文本)

[2] 权限请求
    text: JSON.stringify({ type: "permission_request", id, workerId, toolName, input, ... })
    isPermissionRequest(msg) → 检测

[3] 权限响应
    text: JSON.stringify({ type: "permission_response", requestId, behavior, updatedInput, ... })
    isPermissionResponse(msg) → 检测

[4] 沙箱权限请求/响应
    text: JSON.stringify({ type: "sandbox_permission_request/response", ... })

[5] 关机请求
    text: JSON.stringify({ type: "shutdown_request", requestId, from, reason })
    isShutdownRequest(msg) → 检测
    createShutdownRequestMessage({requestId, from, reason}) → 创建

[6] 关机批准/拒绝
    text: JSON.stringify({ type: "shutdown_approved/rejected", requestId, from, paneId, backendType })
    isShutdownApproved(msg) → 检测

[7] 空闲通知
    text: JSON.stringify({ type: "idle_notification", from, summary })
    isIdleNotification(msg) → 检测
    createIdleNotification({from, summary}) → 创建

[8] 团队权限更新
    text: JSON.stringify({ type: "team_permission_update", updates })
    isTeamPermissionUpdate(msg) → 检测

[9] 模式设置请求
    text: JSON.stringify({ type: "mode_set_request", mode })
    isModeSetRequest(msg) → 检测

[10] 计划审批请求/响应
    text: JSON.stringify({ type: "plan_approval_request/response", requestId, plan, approve, feedback })
    isPlanApprovalRequest(msg) / isPlanApprovalResponse(msg) → 检测
```

---

### 通道 2: SendMessageTool (`SendMessageTool.ts`, 917行)

**角色**: Agent 可调用的**工具级消息发送 API**。

```
SendMessageTool 输入:
{
  to: string,       ← 收件人名称 / "*" 广播 / "uds:<path>" / "bridge:<id>"
  summary?: string,  ← 5-10词摘要
  message: string | StructuredMessage
}

StructuredMessage 类型:
├── { type: "shutdown_request", reason? }
├── { type: "shutdown_response", request_id, approve, reason? }
└── { type: "plan_approval_response", request_id, approve, feedback? }
```

**消息路由逻辑**:

```
SendMessageTool.call(input, context):
│
├── [路由 1] 广播 (to === "*")
│   ├── readTeamFileAsync(teamName) → 获取团队成员
│   ├── 过滤掉自己
│   └── 对每个成员: writeToMailbox(name, message)
│
├── [路由 2] 结构化消息 (message 是对象)
│   ├── shutdown_request → handleShutdownRequest()
│   │   └── createShutdownRequestMessage → writeToMailbox(target)
│   ├── shutdown_response → handleShutdownApproval/Rejection()
│   │   ├── createShutdownApprovedMessage → writeToMailbox(TEAM_LEAD_NAME)
│   │   ├── in-process → abortController.abort()
│   │   └── tmux/iTerm → gracefulShutdown()
│   └── plan_approval_response → writeToMailbox(TEAM_LEAD_NAME)
│
├── [路由 3] 进程内子 agent (LocalAgentTask)
│   ├── 在 AppState.tasks 中查找匹配名称的 LocalAgentTask
│   ├── queuePendingMessage(taskId, message, setAppState)
│   │   └── task.pendingMessages.push(message)
│   └── 如果 agent 已停止 → resumeAgentBackground() 重启
│
├── [路由 4] 文件 Mailbox (团队成员)
│   ├── writeToMailbox(recipientName, { from, text, summary, timestamp, color })
│   └── 发送到: ~/.claude/teams/{team}/inboxes/{recipient}.json
│
├── [路由 5] UDS 直连 (feature: UDS_INBOX)
│   └── parseAddress("uds:<socket>") → Unix Domain Socket 发送
│
└── [路由 6] Bridge 直连
    └── parseAddress("bridge:<session>") → 通过 Bridge 中继
```

---

### 通道 3: Leader 权限 Bridge (`leaderPermissionBridge.ts`, 54行)

**角色**: 让进程内 teammate 能在 Leader 的 UI 中显示权限对话框。

```
机制: 模块级注册（全局变量）

Leader 端 (REPL.tsx):
├── registerLeaderToolUseConfirmQueue(setter) → 注册权限确认队列设置器
├── registerLeaderSetToolPermissionContext(setter) → 注册权限上下文设置器
└── 在 unmount 时: unregister*()

Teammate 端 (inProcessRunner.ts):
├── const leaderQueue = getLeaderToolUseConfirmQueue()
├── if (leaderQueue):
│   ├── leaderQueue(prev => [...prev, confirmEntry]) → 添加到 Leader 的确认队列
│   ├── Leader UI 渲染 PermissionRequest 对话框
│   ├── 用户点击 Allow/Deny
│   └── confirmEntry.resolve(decision) → 返回决策给 teammate
└── else: 降级到文件 Mailbox 权限请求

数据流:
  Teammate → getLeaderToolUseConfirmQueue() → 直接写入 Leader 的 React state
  Leader UI → 用户点击 → resolve() → Promise 返回给 Teammate
  零文件 I/O，零延迟
```

---

### 通道 4: 权限同步 (`permissionSync.ts`, 928行)

**角色**: Worker 和 Leader 之间的**权限决策传递**。

```
Worker 请求权限:
│
├── [1] 创建请求
│   SwarmPermissionRequest = {
│     id: string, workerId, workerName, workerColor,
│     teamName, toolName, toolUseId,
│     description, input, permissionSuggestions,
│     status: 'pending'
│   }
│
├── [2] 通过 Mailbox 发送
│   sendPermissionRequestViaMailbox(leaderName, request):
│   ├── createPermissionRequestMessage(request) → 结构化消息
│   └── writeToMailbox(TEAM_LEAD_NAME, message)
│
├── [3] 等待响应
│   Worker 轮询自己的 Mailbox:
│   ├── readUnreadMessages(workerName)
│   ├── 检查 isPermissionResponse(msg)
│   └── 匹配 requestId → 获取决策
│
└── [4] 也通过文件系统（备用）
    writePermissionRequest(teamDir, request) → permissions/pending/{id}.json
    readResolvedPermission(teamDir, id) → permissions/resolved/{id}.json

Leader 响应权限:
│
├── [1] useInboxPoller 检测权限请求
│   ├── readUnreadMessages(TEAM_LEAD_NAME)
│   ├── isPermissionRequest(msg) → 检测
│   └── 解析 SwarmPermissionRequest
│
├── [2] 显示到 UI
│   ├── leader 的 ToolUseConfirmQueue.push(confirmEntry)
│   └── PermissionRequest 组件渲染
│
├── [3] 用户决策
│   ├── Allow → behavior:'allow' + updatedInput + permissionUpdates
│   └── Deny → behavior:'deny' + message
│
└── [4] 通过 Mailbox 响应
    sendPermissionResponseViaMailbox(workerName, response):
    ├── createPermissionResponseMessage(response)
    └── writeToMailbox(workerName, message)

沙箱权限 (额外通道):
├── sendSandboxPermissionRequestViaMailbox(leaderName, host)
├── sendSandboxPermissionResponseViaMailbox(workerName, allow, host)
└── 用于网络访问审批 (域名级)
```

---

### 通道 5: 消息队列 (`messageQueueManager.ts`, 547行)

**角色**: 统一的**进程内消息队列**，连接 agent 通知和用户 prompt。

```
核心设计:
├── 全局单例队列
├── 优先级: 'now' > 'next' > 'later'
├── Agent 范围: 每个消息可标记 agentId
└── 主线程 vs 子线程: 不同的排空规则

关键函数:
├── enqueue(command, priority?) → 入队
├── enqueuePendingNotification(message) → 系统通知入队 (priority='later')
├── dequeue(filter?) → 出队
├── getCommandsByMaxPriority(maxPriority) → 按优先级获取
│   └── query.ts 中:
│       ├── sleepRan → 'later' (Sleep 工具运行后允许所有优先级)
│       └── 否则 → 'next' (只取高优先级)
└── removeByFilter(filter) → 条件移除

Agent 通知流:
  Agent 完成 → enqueueAgentNotification() → enqueuePendingNotification()
    → query.ts 的 getCommandsByMaxPriority() 获取
    → 作为 attachment 注入到下一轮 API 调用
    → Claude 看到: <task-notification>Agent "xxx" completed</task-notification>

Agent 范围过滤 (query.ts 行 1567-1578):
├── 主线程: 只取 agentId === undefined 的通知
├── 子 agent: 只取自己 agentId 的 task-notification
└── 防止跨 agent 消息泄漏
```

---

### 通道 6: InProcess Teammate 内存通信

**角色**: 进程内 teammate 的**高效内存通信**。

```
=== 前向通信 (Leader → Teammate) ===

方式 1: pendingMessages (LocalAgentTask)
├── queuePendingMessage(taskId, text, setAppState)
│   └── task.pendingMessages.push(text)
├── drainPendingMessages(taskId, getAppState, setAppState)
│   └── 取出所有待处理消息 + 清空队列
└── 在 runAgent 的每个工具轮次边界检查

方式 2: Mailbox (用于文本消息)
├── writeToMailbox(teammateName, message)
└── inProcessRunner.ts 的 waitForNextPromptOrShutdown() 轮询

方式 3: 直接 AbortController.abort() (用于关机)
├── task.abortController.abort()
└── runAgent 的循环立即中断

=== 反向通信 (Teammate → Leader) ===

方式 1: AppState.tasks 更新
├── updateTaskState<LocalAgentTaskState>(taskId, setAppState, updater)
├── 进度: task.progress = { toolUseCount, tokenCount, lastActivity }
├── 状态: task.status = 'completed' / 'failed' / 'idle'
└── Leader 的 React 组件自动重渲染

方式 2: enqueuePendingNotification (完成通知)
├── enqueueAgentNotification({ taskId, description, status, ... })
└── 通过 messageQueueManager 进入主线程

方式 3: 空闲通知 (Mailbox)
├── createIdleNotification({ from: agentName, summary })
└── writeToMailbox(TEAM_LEAD_NAME, message)

方式 4: 权限请求 (leaderPermissionBridge)
├── 优先: getLeaderToolUseConfirmQueue() → 直接 UI
└── 降级: sendPermissionRequestViaMailbox()
```

---

### 通道 7: useInboxPoller (`useInboxPoller.ts`, 969行)

**角色**: Leader 的**消息接收引擎**，每秒轮询一次所有消息。

```
useInboxPoller({ enabled, isLoading, ... }):
│
├── 轮询间隔: 1000ms
├── 轮询目标: 自己的 Mailbox (TEAM_LEAD_NAME 或 agent name)
│
├── 每次轮询:
│   readUnreadMessages(myName, teamName) → 获取未读消息
│   │
│   ├── 对每条消息分类处理:
│   │
│   │   [类型 1] isPermissionRequest(msg)
│   │   ├── 解析 SwarmPermissionRequest
│   │   ├── 添加到 ToolUseConfirmQueue → Leader UI 显示
│   │   ├── 用户决策后: sendPermissionResponseViaMailbox()
│   │   └── markMessageAsReadByIndex()
│   │
│   │   [类型 2] isPermissionResponse(msg)
│   │   ├── hasPermissionCallback(requestId)? → 有进程内回调
│   │   ├── processMailboxPermissionResponse() → 触发回调
│   │   └── markMessageAsReadByIndex()
│   │
│   │   [类型 3] isSandboxPermissionRequest(msg)
│   │   ├── 添加到 AppState.workerSandboxPermissions.queue
│   │   └── Leader UI 显示网络访问审批
│   │
│   │   [类型 4] isSandboxPermissionResponse(msg)
│   │   ├── processSandboxPermissionResponse() → 触发回调
│   │   └── markMessageAsReadByIndex()
│   │
│   │   [类型 5] isShutdownRequest(msg)
│   │   ├── 提交为用户消息 → Claude 模型看到关机请求
│   │   └── markMessageAsReadByIndex()
│   │
│   │   [类型 6] isShutdownApproved(msg)
│   │   ├── 提取 paneId + backendType
│   │   ├── getBackendByType(backendType).destroyPane(paneId) → 销毁面板
│   │   ├── removeTeammateFromTeamFile() → 移除团队成员
│   │   └── markMessageAsReadByIndex()
│   │
│   │   [类型 7] isTeamPermissionUpdate(msg)
│   │   ├── 解析 PermissionUpdate[]
│   │   ├── applyPermissionUpdate() → 应用到本地权限上下文
│   │   └── markMessageAsReadByIndex()
│   │
│   │   [类型 8] isModeSetRequest(msg)
│   │   ├── 切换权限模式 (auto/plan/default)
│   │   └── markMessageAsReadByIndex()
│   │
│   │   [类型 9] isPlanApprovalRequest(msg)
│   │   ├── 自动批准 + 发送 plan_approval_response
│   │   └── markMessageAsReadByIndex()
│   │
│   │   [类型 10] isPlanApprovalResponse(msg)
│   │   ├── handlePlanApprovalResponse() → 解析反馈
│   │   └── markMessageAsReadByIndex()
│   │
│   │   [类型 11] 普通文本消息
│   │   ├── 格式化: <teammate-message from="worker-1">内容</teammate-message>
│   │   ├── 空闲时: 立即提交为用户消息 → 模型处理
│   │   ├── 忙碌时: 入队到 AppState.inbox.messages → 等待下一个空闲
│   │   └── markMessageAsReadByIndex()
│   │
│   └── 终端通知: sendNotification() (如果终端不在焦点)
│
└── 排除: in-process teammate 不使用此 poller（它们用 waitForNextPromptOrShutdown）
```

---

## 四、完整消息流程图

### 流程 1: Agent → Agent 普通消息

```
Agent-A 调用 SendMessageTool({ to: "Agent-B", message: "请检查测试" })
    │
    ▼
SendMessageTool.call()
    ├── 查找 Agent-B 是进程内还是进程外
    │
    ├── [进程内] queuePendingMessage("Agent-B-taskId", "请检查测试", setAppState)
    │   └── Agent-B 的 runAgent → drainPendingMessages → 在下一个工具轮次边界收到
    │
    └── [进程外] writeToMailbox("Agent-B", { from:"Agent-A", text:"请检查测试", ... })
        │
        ▼
    Agent-B 的 useInboxPoller (每 1s 轮询)
        ├── readUnreadMessages("Agent-B")
        ├── 检测到普通文本消息
        ├── 格式化: <teammate-message from="Agent-A">请检查测试</teammate-message>
        ├── onSubmitMessage(formattedText) → 作为用户消息提交
        ├── markMessageAsReadByIndex()
        └── Agent-B 的 Claude 模型看到消息并响应
```

### 流程 2: Worker 请求权限

```
Worker-1 执行 BashTool("rm -rf ./tmp")
    │
    ├── checkPermissions → behavior: 'ask' (需要用户确认)
    │
    ▼
inProcessRunner.ts :: createInProcessCanUseTool()
    │
    ├── [优先路径] Leader 的 PermissionBridge
    │   ├── getLeaderToolUseConfirmQueue() → 非 null
    │   ├── leaderQueue(prev => [...prev, {
    │   │     toolName: 'Bash', input: { command: 'rm -rf ./tmp' },
    │   │     onAllow: (input, permUpdates) => resolve({ behavior:'allow', ... }),
    │   │     onReject: (message) => resolve({ behavior:'deny', ... }),
    │   │   }])
    │   ├── Leader REPL 渲染 PermissionRequest 对话框
    │   ├── 用户点击 "Allow"
    │   └── resolve({ behavior:'allow', updatedInput }) → Worker 继续执行
    │
    └── [降级路径] Mailbox 权限请求
        ├── sendPermissionRequestViaMailbox(TEAM_LEAD_NAME, {
        │     id: "perm_xxx", workerId, workerName: "worker-1",
        │     toolName: "Bash", toolUseId, input, description,
        │     permissionSuggestions: ["Bash(rm:*)"]
        │   })
        ├── writeToMailbox(TEAM_LEAD_NAME, message)
        │
        ├── Leader: useInboxPoller 检测 isPermissionRequest
        │   ├── 添加到 ToolUseConfirmQueue
        │   ├── 用户点击 "Allow"
        │   └── sendPermissionResponseViaMailbox("worker-1", {
        │         requestId: "perm_xxx", behavior: 'allow',
        │         updatedInput, permissionUpdates
        │       })
        │
        └── Worker-1: 轮询 Mailbox → 检测 isPermissionResponse
            └── resolve({ behavior: 'allow' }) → 继续执行
```

### 流程 3: Agent 完成通知

```
LocalAgentTask 内的 runAgent() 完成
    │
    ▼
completeAsyncAgent(taskId, result, setAppState)
    │
    ├── [1] updateTaskState(taskId, { status: 'completed', result })
    │   └── AppState.tasks[taskId].status = 'completed'
    │
    ├── [2] enqueueAgentNotification({
    │     taskId, description: "test-runner",
    │     status: 'completed', finalMessage: "All tests passed",
    │     usage: { totalTokens, toolUses, durationMs },
    │     toolUseId, worktreePath, worktreeBranch
    │   })
    │   │
    │   ├── 原子设置 notified 标记（防重复）
    │   ├── abortSpeculation() → 中止推测执行
    │   └── enqueuePendingNotification(formattedMessage, { priority: 'later' })
    │       └── messageQueueManager.enqueue()
    │
    └── [3] 主线程的 query.ts
        ├── getCommandsByMaxPriority('next'|'later') → 获取通知
        ├── 过滤: isMainThread → 只取 agentId === undefined
        ├── 作为 attachment 注入:
        │   <task-notification>
        │     <task-id>xxx</task-id>
        │     <status>completed</status>
        │     <summary>Agent "test-runner" completed</summary>
        │     <result>All tests passed</result>
        │     <output-file>/tmp/claude/task-xxx.jsonl</output-file>
        │   </task-notification>
        └── Claude 模型看到通知并可以使用 TaskOutputTool 查看详细结果
```

### 流程 4: 关机协调

```
Leader 决定关闭 Worker-1
    │
    ▼
Leader 调用 SendMessageTool({ to: "worker-1", message: { type: "shutdown_request", reason: "任务完成" } })
    │
    ├── createShutdownRequestMessage({ requestId, from, reason })
    └── writeToMailbox("worker-1", message)
        │
        ▼
Worker-1: useInboxPoller 检测 isShutdownRequest
    ├── 提交为用户消息 → Worker-1 的 Claude 看到关机请求
    ├── Claude 决定是否同意
    │
    ├── [同意] Claude 调用 SendMessageTool({ to: "team-lead", message: { type: "shutdown_response", request_id, approve: true } })
    │   ├── createShutdownApprovedMessage({ requestId, from, paneId, backendType })
    │   ├── writeToMailbox(TEAM_LEAD_NAME, message)
    │   ├── in-process → abortController.abort()
    │   └── tmux/iTerm → gracefulShutdown() → process.exit()
    │
    └── [拒绝] Claude 调用 SendMessageTool({ to: "team-lead", message: { type: "shutdown_response", request_id, approve: false, reason: "还有未完成的任务" } })
        ├── createShutdownRejectedMessage({ requestId, from, reason })
        └── writeToMailbox(TEAM_LEAD_NAME, message)
            │
            ▼
Leader: useInboxPoller 检测 isShutdownApproved/isShutdownRejected
    ├── 批准 → destroyPane(paneId) + removeTeammateFromTeamFile()
    └── 拒绝 → 作为用户消息提交 → Leader 的 Claude 看到拒绝原因
```

---

## 五、关键设计决策

### 决策 1: 文件 Mailbox 而非 IPC/WebSocket
**做法**: JSON 文件 + 文件锁
**原因**: 跨进程通信最可靠的方式。tmux 面板中的进程没有共享内存。文件系统是唯一保证可用的通信通道。文件锁（proper-lockfile）处理并发写入。

### 决策 2: 双通道权限决策（UI Bridge + Mailbox）
**做法**: 进程内 → 直接 UI；进程外 → Mailbox 中继
**原因**: 进程内 teammate 可以直接访问 Leader 的 React state（零延迟）。进程外必须走 Mailbox（有 ~1s 轮询延迟）。优先使用快速路径。

### 决策 3: 消息类型通过 JSON text 字段编码
**做法**: TeammateMessage.text 既可以是纯文本，也可以是 JSON 结构化消息
**原因**: 向后兼容。最初只有纯文本消息。后来需要权限/关机/计划审批等结构化消息，通过 JSON 编码复用同一通道。每种类型有对应的 `isXxxRequest()` 检测器。

### 决策 4: Agent 范围的消息队列过滤
**做法**: `query.ts` 中按 `agentId` 过滤通知
**原因**: 多个 agent 共享一个全局 messageQueueManager。主线程只看 agentId=undefined 的通知，子 agent 只看自己的 task-notification。防止跨 agent 消息泄漏。

### 决策 5: 空闲通知的推模式
**做法**: Agent 完成后主动 writeToMailbox(TEAM_LEAD_NAME, idleNotification)
**原因**: Leader 不需要轮询每个 agent 的状态。Agent 完成时主动通知 Leader，Leader 只需轮询自己的收件箱即可知道哪些 agent 空闲了。

### 决策 6: 关机需要双方确认
**做法**: Leader 发 shutdown_request → Worker 决定 approve/reject
**原因**: Worker 可能有未完成的工作（未提交的 git 变更、运行中的测试）。强制关机会丢失工作。让 Worker 的 Claude 模型决定是否安全关闭。

---

## 六、涉及文件完整清单

| # | 文件路径 | 行数 | 通信角色 |
|---|---------|------|---------|
| 1 | `utils/teammateMailbox.ts` | 1,183 | **文件 Mailbox 核心**：读/写/锁/消息类型检测 |
| 2 | `tools/SendMessageTool/SendMessageTool.ts` | 917 | **Agent 消息发送 API**：路由+广播+结构化消息 |
| 3 | `hooks/useInboxPoller.ts` | 969 | **Leader 消息接收**：1s轮询+11种消息处理 |
| 4 | `utils/swarm/permissionSync.ts` | 928 | **权限请求/响应**：文件+Mailbox 双通道 |
| 5 | `utils/swarm/inProcessRunner.ts` | 1,552 | **进程内 Teammate 运行**：权限桥接+消息等待 |
| 6 | `utils/swarm/leaderPermissionBridge.ts` | 54 | **Leader UI Bridge**：模块级注册 |
| 7 | `hooks/useSwarmPermissionPoller.ts` | 330 | **权限回调注册**：进程内回调等待 |
| 8 | `utils/messageQueueManager.ts` | 547 | **统一消息队列**：优先级+Agent范围过滤 |
| 9 | `tasks/LocalAgentTask/LocalAgentTask.tsx` | 682 | **Agent 任务状态**：pendingMessages+通知 |
| 10 | `tasks/InProcessTeammateTask/InProcessTeammateTask.tsx` | 125 | **进程内 Teammate 任务** |
| 11 | `tasks/InProcessTeammateTask/types.ts` | 121 | **Teammate 任务类型** |
| 12 | `tools/AgentTool/AgentTool.tsx` | 1,397 | **Agent 生成入口** |
| 13 | `tools/AgentTool/runAgent.ts` | 973 | **Agent 执行循环** |
| 14 | `tools/shared/spawnMultiAgent.ts` | 1,093 | **多 Agent 生成共享逻辑** |
| 15 | `utils/swarm/spawnInProcess.ts` | 328 | **进程内 Teammate 生成** |
| 16 | `utils/swarm/teamHelpers.ts` | 683 | **团队文件 I/O** |
| 17 | `utils/swarm/constants.ts` | ~30 | **常量** (TEAM_LEAD_NAME 等) |
| 18 | `utils/swarm/backends/InProcessBackend.ts` | 339 | **进程内后端** |
| 19 | `utils/swarm/backends/TmuxBackend.ts` | 764 | **tmux 后端** |
| 20 | `utils/agentContext.ts` | 178 | **Agent 上下文隔离** |
| 21 | `utils/teammateContext.ts` | 96 | **Teammate 上下文隔离** |
| 22 | `utils/teammate.ts` | ~200 | **Teammate 身份工具函数** |
| 23 | `utils/inProcessTeammateHelpers.ts` | 102 | **进程内 Teammate 辅助** |
| 24 | `coordinator/coordinatorMode.ts` | 369 | **协调器模式** |
| 25 | `hooks/toolPermission/handlers/swarmWorkerHandler.ts` | 159 | **Worker 权限处理器** |
