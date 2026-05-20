# Claude Code 多 Agent 通信机制深度解析

> 本文基于 `@anthropic-ai/claude-code@2.1.88` 提取出的源码（`E:\Au_notes\claude_code\source\src`）撰写。
> 目的是把「多 Agent 协作」这件事从 4 个不同的抽象层次讲清楚：
>
> 1. **Tool-level orchestration**（工具级调度）
> 2. **Task-centric communication**（任务中心通信）
> 3. **Swarm / Teammate backend**（群体/队友后端）
> 4. **Bridge / Remote permission**（跨设备桥接）

这 4 层不是平行的「四种方案」，而是**由内到外、由同步到异步、由单进程到跨设备**的 4 个嵌套层次。先看这张总览图：

```
┌────────────────────────────────────────────────────────────┐
│  Layer 4: Bridge  (跨设备 / 跨会话, HTTPS 长轮询 + 子进程)   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Layer 3: Swarm / Teammate  (队友，同/跨进程，邮箱)  │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │  Layer 2: Task  (Local/Remote 异步任务，磁盘)   │  │  │
│  │  │  ┌──────────────────────────────────────────┐  │  │  │
│  │  │  │  Layer 1: Tool orchestration  (同进程)    │  │  │  │
│  │  │  │  query.ts → StreamingToolExecutor        │  │  │  │
│  │  │  │  → AgentTool → runAgent (sub-generator)  │  │  │  │
│  │  │  └──────────────────────────────────────────┘  │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

每一层的「通信介质」都不同：

| 层 | 通信载体 | 序列化 | 生命周期 | 典型例子 |
|---|---|---|---|---|
| Tool | JS generator yield | 内存对象 | 同步 | `Agent(subagent_type: "Explore", ...)` |
| Task | sidechain JSONL 文件 / HTTPS | JSON lines | 异步/可后台 | `run_in_background: true` |
| Swarm | 邮箱 JSON 文件 / AsyncLocalStorage | JSON | 长驻 | `team_name: "planners", name: "alice"` |
| Bridge | WebSocket/HTTPS 轮询 + 子进程 stdio | control_request JSON | 跨设备 | `claude rc` |

下面逐层展开。

---

## 一、Tool-Level Orchestration —— 同一个 query loop 里的「子生成器」

### 1.1 它要解决的问题

所有一切的起点是 `query.ts`。Claude 每回合（turn）做的事情就这四步：

1. 把 messages + system prompt + 可用工具池打包，向模型发 `messages.create`。
2. 流式解析返回内容，拆出 `text` 块和 `tool_use` 块。
3. 对每个 `tool_use` 块调度执行，把结果聚成 `tool_result` 块。
4. 把 `tool_result` 追加到 messages，如果还有 tool_use 就循环，否则本 turn 结束。

**Tool-level orchestration 就是第 3 步的实现细节**。关键文件：

- `source/src/query.ts` (~1700 行) — `queryLoop()` 在 L242–280
- `source/src/services/tools/StreamingToolExecutor.ts` — 真正的调度器
- `source/src/tools/AgentTool/AgentTool.tsx` — 当被调度的工具是 `Agent` 时触发
- `source/src/tools/AgentTool/runAgent.ts` — 子 Agent 的 query 生成器

### 1.2 执行细节：一次 `Agent(subagent_type: "Explore", ...)` 的完整过程

**Step 0 —— 主 query loop 收到 assistant 消息**

`query.ts:558–568` 流式读取到 assistant 消息后，扫描其 `content` 数组，找到所有 `content.type === 'tool_use'` 的块。每个块形如：

```json
{
  "type": "tool_use",
  "id": "toolu_01ABC...",
  "name": "Agent",
  "input": {
    "subagent_type": "Explore",
    "prompt": "Find all uses of foo()",
    "description": "Search foo usages"
  }
}
```

**Step 1 —— 交给 StreamingToolExecutor**

`StreamingToolExecutor.ts:40` 定义了这个类，它维护三样东西：

- `toolDefinitions`：当前可用工具（不是全部，可能被权限或 agent 定义限制过）。
- `canUseTool`：权限回调，调用时会走 hooks + permission mode。
- `toolUseContext`：贯穿整个 turn 的上下文（abort controller、appstate、session id 等）。

`addTool(block, assistantMessage)` 把工具入队。注意一点**关键设计**：

```
每个工具有 isConcurrencySafe 布尔
→ true:  可与其他并发安全工具并行
→ false: 独占执行（Agent 工具属于此类，或依赖于之前工具的写入）
```

`processQueue()` 负责根据这个标志串行或并行调度。

**Step 2 —— executeTool → runToolUse**

`StreamingToolExecutor.ts:265–310` 的 `executeTool` 做几件事：

1. `setInProgressToolUseIDs()` 告诉 UI 这个 tool_use_id 正在执行（显示 spinner）。
2. 检查 abort signal。如果用户已按 Esc，直接合成一个 `"Tool use was cancelled"` 错误结果，不跑工具。
3. 调用 `runToolUse()`（定义在 Tool.ts 附近），该函数：
   - 先做参数校验（tool 的 Zod schema）。
   - 走 `canUseTool`（权限 + hook）。
   - 执行 `tool.call(input, context)`。AgentTool 的 `call()` 定义在 `AgentTool.tsx:239–316`。
4. 把 `call()` 返回的 `AgentToolResult` 包装成 `tool_result` 块（`ToolResultBlockParam` 类型）。
5. 状态机迁移：`queued → executing → completed → yielded`。

**Step 3 —— AgentTool.call() 内部：分岔**

`AgentTool.tsx:239–316` 的 call 方法根据参数分三条路：

```ts
if (teamName && name) {
  // 分岔 A：Teammate 模式（见第三章）
  return spawnTeammate({...});
}
if (run_in_background) {
  // 分岔 B：Local async task（见第二章）
  return runAsyncAgentLifecycle({...});
}
// 分岔 C：同步子 agent（本章）
return runAgent({...});
```

**分岔 C 最常见**：一个同步子 agent 就是一个 **子 query loop**。`runAgent.ts:248` 定义：

```ts
export async function* runAgent(config, toolUseContext) {
  // 1. 根据 subagent_type 拿到 agent 定义（tools whitelist, system prompt）
  // 2. 构造子 ToolUseContext（共享 abort? 否，给一个 child abort）
  // 3. 调用内部的 query() 生成器 —— 递归！
  for await (const msg of query(subMessages, subToolCtx, ...)) {
    yield msg;                  // 进度事件冒泡到父 loop 的 UI
  }
  return terminalState;         // 最终的 AgentToolResult
}
```

**关键点：子 agent 其实就是同一个 `query()` 函数的递归调用**。差别只在于：

- 它用的是「受限工具集」（由 `subagent_type` 的定义文件指定，通常不包含 Agent 本身，防无限递归）。
- 它有独立的 abort controller，父 abort 会级联，但父继续跑时子可以先结束。
- 它的 messages 不会追加到父 messages，只最终结果（文本摘要）会回传。

**Step 4 —— 结果回流**

子 agent 跑完，`runAgent` 返回一个 `Terminal` 对象（成功/失败/abort）。
`agentToolUtils.ts` 的 `finalizeAgentTool()` 把它打包成：

```json
{
  "status": "completed",
  "content": [
    { "type": "text", "text": "I found 3 usages: ..." }
  ],
  "usage": { "input_tokens": 1234, "output_tokens": 567 }
}
```

被 `StreamingToolExecutor` 写成 `tool_result` 块，返回给 `query.ts` 的 `getCompletedResults()`（L852），最终追加到父 messages 的 user 角色里，开启下一轮 API 调用。

### 1.3 一个完整例子（带 ASCII 时序图）

用户说「帮我找出 repo 里所有用 lodash 的地方，然后决定要不要迁移」。

```
USER: "找出所有用 lodash 的地方，决定是否迁移"
 │
 ▼
MAIN query loop (turn 1)
 │ 发 API → assistant 返回：[text, tool_use(Agent, subagent_type=Explore)]
 │
 ▼
StreamingToolExecutor.addTool(tool_use_block)
 │ isConcurrencySafe? false → 独占
 │
 ▼
executeTool → runToolUse → AgentTool.call()
 │ 无 teamName、无 run_in_background → 走同步 runAgent
 │
 ▼
runAgent (子 generator)
 │ 构造 subAgentContext{ allowedTools: [Grep, Glob, Read, Bash] }
 │ 调用 query(subMessages, subCtx)
 │   │
 │   ▼
 │  SUB query loop (turn 1) 
 │   │ 发 API（模型看到子 system prompt "你是 Explore agent"）
 │   │ assistant 返回 tool_use(Grep pattern="lodash")
 │   │ (递归在这里止住：Explore 的 allowedTools 里没有 Agent)
 │   ▼
 │  runToolUse Grep → 实际执行 ripgrep → 返回 matches
 │  SUB query loop (turn 2)
 │   │ 发 API → assistant 返回 text "Found 15 files..."
 │   │ 无 tool_use → 子 loop 结束
 │   ▼
 │  return terminalState{ text: "Found 15 files using lodash: ..." }
 │
 ▼
finalizeAgentTool → { status: "completed", content: [...] }
 │
 ▼
写回 MAIN tool_result：user 消息追加 tool_result_block
 │
 ▼
MAIN query loop (turn 2)
 │ 发 API → assistant 看到子 Agent 的总结，基于它做判断
 │ 返回 text "建议保留 lodash，因为..."
 │ 无 tool_use → 主 loop 结束
```

==**核心观察**：子 agent 的 15 次 Grep 调用细节 **没有** 进入父 messages，只有那段总结 text 进了。这就是 Agent 工具「子上下文隔离、摘要回传」的意义 —— 它是 **一种压缩机制**，把 15 次搜索的噪音压成一句话，保护主 context。==

---

## 二、Task-Centric Communication —— 异步、可后台、可跨会话恢复

### 2.1 为什么要有 Task 这一层

Tool-level 的 `runAgent` 是 **同步阻塞** 的：主 loop 必须等子 agent 跑完才能继续。如果子 agent 要花 10 分钟搜整个 monorepo，用户的主对话就卡 10 分钟。

Task 层解决这个：**把 agent 放到后台，让主 loop 立刻返回，用户可以继续做别的事**。并且因为是异步的，它必须：

- 有一个 **agentId** 可以被后续工具引用（TaskGet/TaskOutput/TaskStop/SendMessage）。
- 有 **持久化**，以便 session 重启时恢复状态。
- 有 **进度回报** 机制，让 UI 显示「还在跑第 N 个工具」。

分两种：**LocalAgentTask**（本地异步）和 **RemoteAgentTask**（云端会话）。

### 2.2 LocalAgentTask：在同一 Node 进程里跑的后台 agent

#### 状态结构

`tasks/LocalAgentTask/LocalAgentTask.tsx:116–148`：

```ts
export type LocalAgentTaskState = TaskStateBase & {
  type: 'local_agent',
  agentId: string,                 // UUID，全局引用标识
  prompt: string,
  selectedAgent: string,           // subagent_type
  agentType: string,
  model: string,
  abortController?: AbortController,
  result?: AgentToolResult,        // 完成后有值
  progress?: AgentProgress,        // { toolUseCount, tokens, recentActivities }
  messages?: Message[],            // 重启时从 sidechain 恢复
  isBackgrounded: boolean,
  pendingMessages: string[],       // SendMessage 送进来的排队消息
  evictAfter?: number              // TTL，防止内存泄漏
}
```

#### 磁盘通信：sidechain.jsonl

Task 不依赖内存做通信，它依赖 **磁盘文件**：

```
~/.claude/sessions/{sessionId}/subagents/{agentId}/sidechain.jsonl
```

每一行是一条 `Message`（user/assistant/tool_result），以 UUID 为主键。
作用：

1. **实时读**：主 session 想看子 agent 当前在做什么，读最后 N 行即可。
2. **断线恢复**：session 重启时，根据 UUID 去重合并回 task state.messages。（这也是为什么断了之后能continue恢复）
3. **TaskOutputTool 的后端**：`TaskOutput(taskId)` 直接读这个文件。

#### 完整生命周期例子

用户说 `"启动一个后台 agent 审计所有 API 端点的安全性"`。

```
1. assistant → tool_use(Agent, run_in_background=true, description="Security audit")

2. AgentTool.call() 走 runAsyncAgentLifecycle():
   a) 生成 agentId = uuid()
   b) 创建 LocalAgentTaskState，压入 AppState.tasks[]
   c) fire-and-forget 启动子 query loop（不 await）
   d) 立即返回 { status: "async_launched", agentId, description }

3. 主 query loop 收到 tool_result，告诉用户「已启动后台任务 abc-123」
   用户可以继续聊别的。

4. 后台子 query loop 跑着，每产生一个 message：
   - 写入 sidechain.jsonl
   - 调用 ProgressTracker.updateProgressFromMessage() 累加 tokens/toolCount
   - 通过 emitTaskProgress() 向 SDK event stream 推进度

5. 用户随时可以：
   - TaskList() → 看到 task abc-123 status=running
   - TaskOutput(abc-123) → 读 sidechain 返回当前所有消息
   - SendMessage(abc-123, "也检查 CSRF")
       → 写入 task.pendingMessages
       → 子 agent 下一个 turn 前会被注入为 user message
   - TaskStop(abc-123) → abortController.abort()

6. 子 agent 跑完：
   - completeAgentTask() 标记 terminal
   - result 写入 state
   - sidechain 关闭
   - evictAfter 设为 now + 1h
```

**关键特性：SendMessage 是「邮箱」语义**。消息不是打断子 agent，而是排队，等子 agent 的下一个 turn 开始前，把 pending 消息作为新 user input 注入。这就是「异步双向通信」的实现方式。

### 2.3 RemoteAgentTask：云端长时会话

结构在 `tasks/RemoteAgentTask/RemoteAgentTask.tsx:22–59`：

```ts
export type RemoteAgentTaskState = TaskStateBase & {
  type: 'remote_agent',
  remoteTaskType: 'remote-agent' | 'ultraplan' | 'ultrareview' 
                | 'autofix-pr' | 'background-pr',
  sessionId: string,        // 云端 CCR session id
  log: SDKMessage[],         // 从云端拉下来的消息
  todoList: TodoList,
  reviewProgress?: {...},    // ultrareview 专用
  ultraplanPhase?: 'needs_input' | 'plan_ready'
}
```

#### 通信方式：HTTPS 轮询 + XML 事件

不是内存、不是文件，是 **HTTP**：

```
POST /v1/sessions                 → 创建，返回 sessionId
GET  /v1/sessions/{id}/events     → 增量拉取新消息（with lastEventId）
POST /v1/sessions/{id}/cancel     → TaskStopTool 调用
```

`RemoteAgentTask.tsx:150–250` 的 `pollRemoteSessionEvents()` 在一个独立的定时器里跑，每次把新消息追加到 `log`，并用正则解析 assistant 发出的 `<task-notification>` XML 块：

```xml
<task-notification>
  <status>complete</status>
  <summary>Fixed 3 bugs in auth flow</summary>
  <result>...</result>
</task-notification>
```

看到 `<status>complete</status>` 就认为任务终态，把 `log` 里的 summary 提出来作为 `AgentToolResult`。

#### 本地 vs 远程：同一把工具，两套后端

TaskCreate/TaskGet/TaskList/TaskOutput/TaskStop/TaskUpdate 这六个工具的实现都是 **多态的**：根据 `task.type === 'local_agent' | 'remote_agent'` 走不同后端：

- local → 读写 `AppState.tasks` 里的对象、读 sidechain.jsonl
- remote → 调 CCR HTTP API、读 log 数组

所以对 **模型（LLM）来说，本地和远程任务接口完全一致**。这是把「通信介质」抽象出去的好例子。

---

## 三、Swarm / Teammate Backend —— 多个 Agent 长期共存、互相说话

### 3.1 什么是 Agent Swarm？

在前两层，agent 之间的关系是 **父子树形**：一个 coordinator 派单子 agent 出去做活、收结果。子 agent 是 **一次性** 的，做完就销毁。

**Swarm（群体）** 的思想不同：

- 多个 agent **同时长驻**，每个有自己的身份（name、role、allowed tools、自己的历史）。
- 它们之间不是简单的 caller/callee，而是可以 **互相发消息**、**共享某些工件**、**看到彼此的进度**。
- Leader 只是协调者，不是「调用」队友，而是「通知」队友。

比如一个研发团队 swarm：

```
leader (你)
  ├── teammate "alice"  — 只能读代码、跑测试、不能改代码
  ├── teammate "bob"    — 可以改代码、但只在 src/backend/ 下
  └── teammate "carol"  — 只做 code review，禁用 Write/Edit
```

alice 发现 bug → 通过邮箱告诉 bob → bob 修 → carol review → alice 验证。
每个 teammate 都是一个独立的 query loop，有自己的 context 窗口。

### 3.2 为什么 Swarm 和 Teammate 放在一起？

因为在 Claude Code 的实现里，「Swarm」就是「Teammate」的集合。==`utils/swarm/` 目录下全是 teammate 相关代码：==

- `utils/swarm/backends/InProcessBackend.ts`
- `utils/swarm/backends/TmuxBackend.ts`
- `utils/swarm/backends/PaneBackendExecutor.ts`
- `utils/swarm/inProcessRunner.ts`
- `utils/swarm/teamHelpers.ts`
- `utils/swarm/leaderPermissionBridge.ts`
- `utils/teammateMailbox.ts`

==**Swarm 是抽象概念（一群 agent 一起干活），Teammate 是实现单位（群里的一个成员）**。所以代码层面两者合一 —— 你创建一个 swarm 的方式就是陆续 spawn 多个 teammate。==

证据：`AgentTool.tsx:282–316` 当传入 `team_name + name` 两个参数时，才走 teammate 路径：

```ts
if (teamName && name) {
  const result = await spawnTeammate({
    name, prompt, description, team_name: teamName,
    use_splitpane: true,                        // UI: 给这个队友单开一个面板
    plan_mode_required: spawnMode === 'plan',
    model: model ?? agentDef?.model,
    agent_type: subagent_type,
  }, toolUseContext);
  return { status: 'teammate_spawned', ... };
}
```

### 3.3 三种后端 —— 一个队友的三种「肉身」

==Swarm 最精彩的设计是 **后端可插拔**。`utils/swarm/backends/registry.ts` 里维护一个注册表，启动时检测环境（是否在 tmux 里、是否在 iTerm2 里、是否允许同进程），选一个合适的后端。==

#### 后端 A：InProcessBackend —— 同一 Node 进程

`InProcessBackend.ts:38–144`

```ts
export class InProcessBackend implements TeammateExecutor {
  async spawn(config) {
    // 1. 在当前进程里用 AsyncLocalStorage 创建一个隔离域
    const { handle } = await spawnInProcessTeammate(config);
    // 2. 启动队友的 query loop（fire-and-forget）
    startInProcessTeammate(handle);
  }
}
```

这个后端的精髓在 `AsyncLocalStorage`。Node 的这个 API 可以给**每条异步调用链**绑定独立的「thread-local」上下文。Claude Code 用它给每个队友绑定：

- 自己的 AppState（独立的 messages、tools、abort）
- 自己的 permission context
- 自己的日志流

结果是：**在同一 event loop 里并发跑 5 个 query loop，它们的状态互不污染**。

但出现一个问题：队友要执行工具前要征得 **leader** 的授权（因为 leader 是 UI 所在、是和人类对话的地方）。这就是 `leaderPermissionBridge.ts:25–54` 做的事：

```ts
// leader 启动时注册自己的 React setState
registerLeaderToolUseConfirmQueue(setter);

// 队友跑到权限检查时，拿 leader 的 setter
const leaderSet = getLeaderSetToolPermissionContext();
leaderSet({ request: {...}, resolve, reject });
// ↓ leader 的 REPL 弹出确认对话框
// ↓ 人类点 Approve
// ↓ resolve() 被调用
// ↓ 队友的 promise resolve，继续执行工具
```

这叫 **Permission Bridge** —— 权限请求从队友的 AsyncLocalStorage 域穿越到 leader 的 UI 域。**这是「同进程多 agent」能存在的关键胶水**。

#### 后端 B：TmuxBackend —— 不同 tmux pane 里的独立进程

`utils/swarm/backends/TmuxBackend.ts`

```ts
async spawn(config) {
  // tmux split-window -t :0 "claude --team swarm1 --name alice"
  execSync(`tmux split-window ... "claude --team ${team} --name ${name}"`);
}
```

队友是一个 **真正的子进程**，通过 tmux pane 可视化。
它和 leader 不共享内存，怎么通信？—— **邮箱文件**：

```
~/.claude/teams/{team_name}/teammates/{agentId}.json
~/.claude/teams/{team_name}/teammates/{agentId}.inbox.jsonl
```

`utils/teammateMailbox.ts` 定义：

- `writeToMailbox(agentId, message)` — 写一行 JSON
- `readTeammateMailbox(agentId)` — 读所有未读行
- 每 500ms 轮询一次

消息类型：

```json
{"type":"message","from":"leader","text":"alice, 你先跑一下测试"}
{"type":"heartbeat","timestamp":1713000000}
{"type":"result","toolUseId":"...","content":"..."}
```

权限怎么办？—— 各自独立。TmuxBackend 下每个 pane 是完整的 Claude 实例，它会在自己的 pane 里显示权限对话框。人类要到那个 pane 去批准。这是 **权限分散** 模型。

#### 后端 C：PaneBackendExecutor —— iTerm2、Warp 等的抽象父类

`PaneBackendExecutor.ts` 给非 tmux 的终端用（iTerm2 AppleScript、Windows Terminal 等），核心思路和 TmuxBackend 一样：**子进程 + 文件邮箱**，只是 spawn pane 的命令不同。

### 3.4 Coordinator Mode —— Swarm 的一种特化使用

`coordinator/coordinatorMode.ts:36` 定义了一个特殊启动模式：

```ts
export function isCoordinatorMode(): boolean {
  return process.env.CLAUDE_CODE_COORDINATOR_MODE === '1';
}
```

开启后，主 query loop 使用一个特殊 system prompt（L111–369）。大意：

> 你是协调者。不要自己写代码。把工作拆分成可并行的子任务，用 Agent(subagent_type='worker') 派给 worker。worker 跑完后它们的结果会以 `<task-notification>` 块形式出现在你的 user 消息里，带有 `<task-id>`。你综合多个 worker 的结果，给用户回答。

`ASYNC_AGENT_ALLOWED_TOOLS`（L29–35）定义了 worker 的工具集，**不包含 Agent 工具本身**（禁止 worker 再嵌套 spawn）。

Coordinator 模式本质就是：**用 Task 层（背后 LocalAgentTask）+ 特殊 prompt，把 Claude 的主 session 变成一个调度中心**。它用的还是第二章的机制。但它也可以和第三章的 Teammate 结合（coordinator 作为 leader，workers 作为 teammates）。

### 3.5 一个完整的 Swarm 例子

用户说 `"我想要一个 3 人的研发小组：planner/coder/reviewer，长期共存"`。

```
1. /team create devteam
2. Agent(team_name="devteam", name="planner", subagent_type="plan", 
         prompt="做需求分解", model="opus-4")
   → InProcessBackend.spawn()
   → spawnInProcessTeammate() 创建 AsyncLocalStorage 域
   → planner 开始跑
   → AgentTool 返回 { status: "teammate_spawned", agentId: "p-1" }
3. Agent(team_name="devteam", name="coder", subagent_type="general-purpose",
         prompt="待命，接到 planner 指令后实现")
   → 同上，coder 启动
4. Agent(team_name="devteam", name="reviewer", ...)
   → reviewer 启动

现在同一个进程里跑 4 个 query loop: leader + 3 teammates

5. planner 产出设计，通过 SendMessage(coder_id, "开始实现...") 
   → 写 coder 的邮箱
   → coder 下轮 turn 前看到新 user message，开始工作

6. coder 调用 Edit 工具，InProcessBackend 检测到需要权限：
   → 调 leaderPermissionBridge 的 setter
   → leader 的 REPL 弹出 "coder wants to edit src/x.ts, allow?"
   → 人类点允许
   → coder 的 Edit 真正执行

7. coder 完成，给 reviewer 发消息
   → reviewer 读代码、给出评审
   → reviewer 通过邮箱把结果发给 planner 和 coder

8. planner 汇总给 leader（你），leader 用自然语言给你汇报
```

**和第一层 AgentTool 的关键区别**：

| 维度 | Tool-level Agent | Swarm Teammate |
|---|---|---|
| 生命周期 | 一次调用一次创建销毁 | 长驻，可接消息 |
| 身份 | 匿名 | 有 name + role |
| 通信 | 只在结束时返回一个结果 | 运行中可双向收发 |
| 权限 | 随父继承 | 可定制 allowed_tools |
| 上下文 | 子 context 独立但短暂 | 独立且持久 |

---

## 四、Bridge / Remote Permission —— 让云端的 Claude 操控你本地的电脑

### 4.1 为什么需要这一层？

前三层全都在 **一台机器** 上。但有两个真实场景单机不够用：

**场景 A：你人在外地，但代码库在公司工作站上**
你想用手机 claude.ai 问问题，它需要运行 Bash / Read / Edit 去看你工作站的代码。
解法：公司工作站挂一个 **Bridge**，挂号到 Anthropic 的云端。云端 Claude 需要执行工具时，通过这个 Bridge 打到你的工作站。

**场景 B：长时间任务，关电脑也要继续**
比如一个大型重构，你希望 claude.ai 云端会话一直跑着，同时它能在你本地 repo 上做修改。
解法：同上，Bridge 把云端会话和本地 repo 桥起来。

**场景 C：把「危险工具」的权限决定权交还人类**
远程 Claude 要 `rm -rf dist/` 了，它不该自己说了算。Bridge 的 **permission bridge** 机制会把权限请求反向送回云端 Claude，云端给用户弹对话框，用户拍板，才让本地执行。

### 4.2 架构总览

```
[ claude.ai / 云端 Claude session ]       ← 人类通过浏览器交互
         │  HTTPS 长轮询 / SSE
         ▼
[ Anthropic Bridge API  /v1/bridge/... ]
         │
         │  (Bridge 每 1s 拉取 pending 事件)
         ▼
[ 你本地 ]  runBridgeLoop()   ← bridge/bridgeMain.ts
         │  spawn 子进程（沙箱）
         ▼
[ claude --bridge-worker --session-id ... ]
  ↑ stdin JSON line  │ stdout JSON line
  ↓                  │ 实际执行 Bash/Edit/Read
  (双向 stdio pipes)  │
                     ▼
              [ 本地文件系统、git ]
```

### 4.3 具体过程

#### 启动

用户在本地跑 `claude rc` 或 `claude --bridge`（取决于配置）。或者通过 `/register` 界面。

1. `bridge/initReplBridge.ts` 初始化：
   - 从 `~/.claude/.bridgerc`（或类似）读 `environmentId + environmentSecret`。
   - 用这俩去 Anthropic 换一个 JWT，注册本机为某个环境。
   - 启动 `runBridgeLoop()`（`bridge/bridgeMain.ts:141`）。

2. `runBridgeLoop()` 主循环（`bridgeMain.ts:141–200+`）：
   ```ts
   while (!signal.aborted) {
     const events = await api.pollSessionEvents();  // 长轮询 1000ms
     for (const ev of events) dispatch(ev);
     await refreshJwtIfNeeded();
   }
   ```

3. BridgeState 状态机（`bridgeMain.ts:83`）：
   ```
   ready → connected → reconnecting → connected / failed
   ```
   网络断了自动带指数退避重连。

#### 云端发起一个会话

人类在 claude.ai 打开一个「远程 session」，指定要用哪个 environment（= 哪台本地机器）。云端会创建一个 session，给它一个 ID，并往那个 environment 的 Bridge 队列里推一个 `session.start` 事件。

`bridgeMain.ts` 收到事件 → 调 `sessionRunner.ts` 的 `SessionSpawner.spawn()`：

```ts
// sessionRunner.ts:140+
const child = spawn('node', [
  cliPath,
  '--sdk-url', sdkUrl,
  '--session-id', sessionId,
  '--sandbox',                 // 沙箱模式：限 FS、限 shell、限 MCP
  '--bridge-worker',           // 特殊模式
  ...(config.worktree ? ['--worktree', worktreePath] : [])
], {
  env: { ...process.env, OAUTH_TOKEN: ..., MODEL: ... },
  stdio: ['pipe', 'pipe', 'pipe']
});
```

可选 **worktree 隔离**（`utils/worktree.ts`）：创建临时 git worktree，子进程在隔离目录里工作，改动不污染你本地的 main checkout，需要时可以走 PR 合并。

#### 消息往返

云端 Claude 做出 assistant 消息 → 需要执行 Bash → 这个 tool_use 通过云端 API 记下来。
Bridge 拉到这个事件 → 把它作为 `{type: "user_message", ...}` 写进子进程 stdin：

```ts
child.stdin.write(JSON.stringify({
  type: 'tool_use',
  name: 'Bash',
  input: { command: 'ls' },
  tool_use_id: 'toolu_xxx'
}) + '\n');
```

子进程其实是一个 **完整的 Claude CLI 在 `--bridge-worker` 模式下**。它 `stdin` 读入的 tool_use 被它内部的 `StreamingToolExecutor` 调度执行（和第一章一样！），结果从 `stdout` 以 JSON line 输出：

```ts
process.stdout.write(JSON.stringify({
  type: 'tool_result',
  tool_use_id: 'toolu_xxx',
  content: 'file1.txt\nfile2.txt'
}) + '\n');
```

Bridge 读到这行，POST 到云端：`/v1/sessions/{id}/results`。云端 Claude 看到结果，产出下一个 assistant 消息，循环继续。

#### 关键：Permission Bridge

危险工具的权限流：

```
云端 Claude 想执行 Bash("rm -rf dist")
     ↓
本地 bridge worker 子进程收到 tool_use
     ↓
canUseTool 回调触发，但本地 permissions 是 "default = ask"
     ↓
worker 输出 control_request 到 stdout:
  { type: "control_request",
    request: { subtype: "can_use_tool",
               tool_name: "Bash",
               input: {...},
               tool_use_id: "..." } }
     ↓
Bridge 读到，解析 (sessionRunner.ts:29-66 的 onPermissionRequest)
     ↓
Bridge 发 HTTPS POST /v1/sessions/{id}/permission_request
     ↓
云端 session 状态变为 "awaiting permission"
     ↓
人类在 claude.ai 界面上看到对话框："允许执行 Bash('rm -rf dist')?"
     ↓
人类点 Deny
     ↓
云端 POST /v1/sessions/{id}/permission_response {approved: false}
     ↓
Bridge 拉到响应
     ↓
写入子进程 stdin：{ type: "control_response",
                      response: { approved: false, reason: "..." } }
     ↓
worker 的 canUseTool 回调 resolve({ approved: false })
     ↓
Bash 工具不执行，返回 "permission denied"
     ↓
云端 Claude 看到结果，调整策略
```

**这就是 Permission Bridge 的意义**：让权限决定发生在「人类在场的那一端」—— 不管云端、本地哪边决定，只要人在哪里，权限对话框就在哪里。

#### JWT 刷新（跨设备认证）

`bridge/jwtUtils.ts` 维护一个 scheduler：每个 JWT 有 expiresAt，过期前 5 分钟自动用 refreshToken 换新 JWT。失败就把 state 拉回 `reconnecting`，走重连流程。

### 4.4 Bridge vs Swarm Pane Backend：表面像，本质不同

你可能注意到 Bridge 也是「子进程 + JSON 消息」，TmuxBackend 也是。它们的区别：

| 维度 | TmuxBackend（第三章） | Bridge（第四章） |
|---|---|---|
| 子进程的「主人」 | leader 是你（人类） | leader 是云端 Claude |
| 消息走向 | 文件邮箱，本地 | HTTPS，跨 Internet |
| 权限决定点 | 本机 | 云端（让远端人类批准） |
| 存在理由 | 多 agent 并行 | 跨地域、跨设备 |
| 是否需要公网鉴权 | 否 | 是（JWT） |

### 4.5 为什么做这件事有意义

1. **解耦 UI 和执行环境**：Claude 的 UI 可以在任何设备（浏览器、手机），算力和文件在你的工作站。
2. **长时会话友好**：你可以关掉浏览器，云端 session 依然在，Bridge 依然挂着，下次回来接着看。
3. **安全边界清晰**：本地 Bridge = 受信环境，云端 = 不受信请求方。Bridge 做的事情是 **代理执行 + 代理权限**，每一个高危操作都强制回到人类。
4. **组合前三层**：Bridge worker 内部仍然是一个完整 Claude，它自己也能用 Agent 工具、spawn Task、组 Swarm。所以 Bridge 是**第一到第三层的跨设备延伸**。

---

## 五、四层之间的关系与选择

回到文首那张嵌套图，用一个**真实工作流**把四层串起来：

> 你在家，想让 Claude 把公司代码库的一个大需求（重写认证模块）做完。

1. 在公司工作站挂上 **Bridge**（第四层）。
2. 在家用手机 claude.ai 开一个远程 session，连到那个 Bridge。
3. 云端 Claude 分析需求，决定启动 **Coordinator 模式 + Swarm**（第三层）：
   - Spawn `planner`、`backend-coder`、`frontend-coder`、`reviewer` 四个 teammate。
   - 这 4 个 teammate 在你工作站的 Bridge worker 子进程里以 InProcessBackend 共存。
4. `planner` 作为 leader 开始工作，它把大任务拆成 10 个小任务，每个用 **LocalAgentTask**（第二层）后台跑：
   - Task 1: 审计现有 auth 代码
   - Task 2: 设计新 schema
   - ...
5. 每个 Task 内部的执行，都是经典的 **Tool-level orchestration**（第一层）：
   - `query.ts` loop、`StreamingToolExecutor` 并发、必要时 spawn 一次性 Explore 子 agent。
6. 某个 Task 执行 `Bash("alembic downgrade ...")` 这样高危操作，**Permission Bridge**：
   - 本地 worker 发 `control_request` → Bridge → 云端 → 你手机收到通知 → 你点允许。
7. 全程你在家手机上看状态，工作站一边本地 git worktree 隔离、一边在跑活。

---

## 六、参考的关键文件清单

| 层 | 文件 | 关键行 |
|---|---|---|
| 1 | `source/src/query.ts` | 220–231, 242–280, 558–568, 831–846 |
| 1 | `source/src/services/tools/StreamingToolExecutor.ts` | 40–124, 265–310 |
| 1 | `source/src/tools/AgentTool/AgentTool.tsx` | 239–316 |
| 1 | `source/src/tools/AgentTool/runAgent.ts` | 248–329 |
| 1 | `source/src/tools/AgentTool/agentToolUtils.ts` | 全文件 |
| 2 | `source/src/tasks/LocalAgentTask/LocalAgentTask.tsx` | 33–148 |
| 2 | `source/src/tasks/RemoteAgentTask/RemoteAgentTask.tsx` | 22–250 |
| 2 | `source/src/utils/task/diskOutput.ts` | 全文件 |
| 2 | `source/src/tools/TaskCreateTool/`, `TaskGetTool/`, ... | 多态分派 |
| 3 | `source/src/coordinator/coordinatorMode.ts` | 29–41, 80–369 |
| 3 | `source/src/utils/swarm/backends/InProcessBackend.ts` | 38–144 |
| 3 | `source/src/utils/swarm/backends/TmuxBackend.ts` | 100+ |
| 3 | `source/src/utils/swarm/inProcessRunner.ts` | 全文件 |
| 3 | `source/src/utils/swarm/leaderPermissionBridge.ts` | 25–54 |
| 3 | `source/src/utils/teammateMailbox.ts` | 读写接口 |
| 3 | `source/src/utils/swarm/teamHelpers.ts` | TeamFile 管理 |
| 4 | `source/src/bridge/bridgeMain.ts` | 83, 141–400 |
| 4 | `source/src/bridge/sessionRunner.ts` | 29–66, 107–200 |
| 4 | `source/src/bridge/initReplBridge.ts` | 全文件 |
| 4 | `source/src/bridge/jwtUtils.ts` | 全文件 |
| 4 | `source/src/utils/worktree.ts` | 全文件 |

---

## 七、一句话小结

> Claude Code 的多 agent 体系不是「一种多 agent 架构」，而是**四层递进的通信抽象**：
> - **Tool-level** 用同进程的子生成器做 context 压缩；
> - **Task** 用磁盘/HTTPS 做异步后台；
> - **Swarm** 用邮箱 + AsyncLocalStorage 做长驻多体；
> - **Bridge** 用 HTTPS + 沙箱子进程做跨设备远程。
>
> 它们共享一个核心组件：`query.ts` 的 query loop。其他三层都是给 query loop 加上「更远的通信介质」和「更强的隔离边界」。
