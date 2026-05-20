# Claude Code 会话持久化源码深度拆解（transcript / jsonl / sidecar）

基于源码目录：`/home/ubuntu/.openclaw/workspace/cc/claude_code/source/src`

本文目标只有一个：**把 Claude Code 的 `.jsonl` 与 `.json` 会话信息到底怎么记录、记录了什么、什么时候写、谁负责注入、恢复时怎么读回来**，按源码完整拆开。

---

## 0. 核心结论先说清

Claude Code 的会话持久化不是“保存聊天记录”这么简单，而是一个**追加式事件日志系统**。

核心事实：

1. **主会话**主要落在一个 `sessionId.jsonl` 文件里。
2. **子代理**各自有独立的 sidechain transcript，也还是 `.jsonl`。
3. **少量不适合塞进主 transcript schema 的元数据**，用 sidecar `.meta.json` 单独存。
4. `.jsonl` 每一行不是统一结构，而是 `Entry` 联合类型中的某一种。
5. 文件是**append-only 为主**，不是“每次全量重写”。
6. resume 时也不是简单“把文件读成数组”，而是要：
   - 解析 entry
   - 恢复 metadata map
   - 建 parentUuid 链
   - 修复并行 tool result 的孤儿节点
   - 处理 compact / collapse / content replacement / worktree / PR link / agent metadata

所以，**一个 `.jsonl` 文件本质上是会话事件流，不是纯聊天 transcript。**

---

## 1. 涉及到的关键源码文件

### 1.1 持久化主轴
- `src/utils/sessionStorage.ts`
- `src/types/logs.ts`

### 1.2 消息创建与结构
- `src/utils/messages.ts`
- `src/utils/messages/mappers.ts`

### 1.3 UI / 主循环触发写盘
- `src/hooks/useLogMessages.ts`
- `src/QueryEngine.ts`
- `src/query.ts`
- `src/services/tools/toolExecution.ts`

### 1.4 恢复与 resume
- `src/utils/conversationRecovery.ts`
- `src/utils/sessionRestore.ts`

### 1.5 子代理 / 远程代理
- `src/tools/AgentTool/runAgent.ts`
- `src/tools/AgentTool/resumeAgent.ts`
- `src/tasks/RemoteAgentTask/RemoteAgentTask.tsx`

### 1.6 远端同步持久化
- `src/services/api/sessionIngress.ts`

### 1.7 路径清洗
- `src/utils/sessionStoragePortable.ts`

---

## 2. 文件布局，`.jsonl` 和 `.json` 分别在哪

## 2.1 主会话 transcript

主文件路径来自 `sessionStorage.ts`：

- `getProjectsDir()` 返回 `~/.claude/projects`
- `getTranscriptPath()` 返回：

```text
~/.claude/projects/<sanitized-project-path>/<sessionId>.jsonl
```

其中 `<sanitized-project-path>` 来自 `sessionStoragePortable.ts` 的 `sanitizePath()`，规则是：

- 非字母数字字符全部替换成 `-`
- 太长则截断并追加 hash

例如工作目录 `/home/ubuntu/.openclaw/workspace` 会被清洗成类似：

```text
-home-ubuntu--openclaw-workspace
```

## 2.2 子代理 transcript

子代理路径来自 `getAgentTranscriptPath(agentId)`：

```text
~/.claude/projects/<project>/<sessionId>/subagents/agent-<agentId>.jsonl
```

如果为该 agent 设置了 subdir，则变成：

```text
~/.claude/projects/<project>/<sessionId>/subagents/<subdir>/agent-<agentId>.jsonl
```

## 2.3 子代理 sidecar 元数据

```text
agent-<agentId>.meta.json
```

和子代理 transcript 同目录，路径由 `getAgentMetadataPath()` 生成。

## 2.4 远程代理 sidecar 元数据

```text
~/.claude/projects/<project>/<sessionId>/remote-agents/remote-agent-<taskId>.meta.json
```

由 `getRemoteAgentMetadataPath(taskId)` 生成。

---

## 3. `.jsonl` 里一行到底是什么

`src/types/logs.ts` 里定义了总联合类型 `Entry`。这决定了**一个 `.jsonl` 文件中的每一行都是什么对象**。

```ts
export type Entry =
  | TranscriptMessage
  | SummaryMessage
  | CustomTitleMessage
  | AiTitleMessage
  | LastPromptMessage
  | TaskSummaryMessage
  | TagMessage
  | AgentNameMessage
  | AgentColorMessage
  | AgentSettingMessage
  | PRLinkMessage
  | FileHistorySnapshotMessage
  | AttributionSnapshotMessage
  | QueueOperationMessage
  | SpeculationAcceptMessage
  | ModeEntry
  | WorktreeStateEntry
  | ContentReplacementEntry
  | ContextCollapseCommitEntry
  | ContextCollapseSnapshotEntry
```

这就是最关键的事实：

**`.jsonl` 不是只有 user / assistant message。**

它还混合了：
- 标题
- 标签
- PR 链接
- 模式
- worktree 状态
- 文件历史快照
- attribution 快照
- 队列操作
- speculation 命中
- content replacement 决策
- context collapse 的 commit / snapshot

---

## 4. 真正“消息行”的结构，也就是 TranscriptMessage

`src/types/logs.ts`：

```ts
export type SerializedMessage = Message & {
  cwd: string
  userType: string
  entrypoint?: string
  sessionId: string
  timestamp: string
  version: string
  gitBranch?: string
  slug?: string
}

export type TranscriptMessage = SerializedMessage & {
  parentUuid: UUID | null
  logicalParentUuid?: UUID | null
  isSidechain: boolean
  gitBranch?: string
  agentId?: string
  teamName?: string
  agentName?: string
  agentColor?: string
  promptId?: string
}
```

所以，一条真正落盘的 transcript message，实际是：

1. **原始 Message 本体**
2. 再包上一层 transcript 元数据

### 4.1 Message 本体可能是什么类型

从 `isTranscriptMessage()` 可知，当前可落入 transcript 的 message type 是：

- `user`
- `assistant`
- `attachment`
- `system`

`progress` **不再是 transcript message**。

### 4.2 所有 transcript message 统一追加的会话字段

这些字段由 `insertMessageChain()` 注入：

- `parentUuid`
- `logicalParentUuid`（compact boundary 才用）
- `isSidechain`
- `teamName`
- `agentName`
- `promptId`（仅 user）
- `agentId`（sidechain）
- `userType`
- `entrypoint`
- `cwd`
- `sessionId`
- `version`
- `gitBranch`
- `slug`

### 4.3 谁负责注入这些字段

就是 `sessionStorage.ts` 的 `Project.insertMessageChain()`：

- 负责 parent 链
- 负责 session stamp
- 负责 team / agent / promptId 注入
- 负责决定写主 transcript 还是 agent sidechain transcript

---

## 5. 一个 `.jsonl` 文件中到底可能出现哪些内容

下面按 entry 类型逐个拆。

## 5.1 `TranscriptMessage`

真正的会话图节点，包含：
- user message
- assistant message
- attachment
- system message

典型内容：
- 用户输入
- assistant 文本回答
- assistant 的 tool_use block
- user 侧的 tool_result block
- compact boundary system message
- 某些 attachment（受过滤规则影响）

写入责任：
- `useLogMessages.ts` 调 `recordTranscript()`
- `QueryEngine.ts` 调 `recordTranscript()`
- `runAgent.ts` 调 `recordSidechainTranscript()`
- 最终都落到 `insertMessageChain()` -> `appendEntry()`

## 5.2 `custom-title`

结构：

```ts
{
  type: 'custom-title'
  sessionId
  customTitle
}
```

用途：用户给 session 手动重命名。

写入责任：
- `saveCustomTitle()`
- `reAppendSessionMetadata()` 也会在尾部重写一份，防止被 compact 后挤出 tail window

## 5.3 `ai-title`

结构：

```ts
{
  type: 'ai-title'
  sessionId
  aiTitle
}
```

用途：AI 自动生成标题。

写入责任：
- `saveAiGeneratedTitle()`

特点：
- 读取时优先级低于 `custom-title`
- **不会**被 `reAppendSessionMetadata()` 再次尾插
- 设计上避免覆盖用户自己改的标题

## 5.4 `last-prompt`

结构：

```ts
{
  type: 'last-prompt'
  sessionId
  lastPrompt
}
```

用途：resume 列表里展示“最近正在做什么”。

写入责任：
- `insertMessageChain()` 在主链写完后，从本轮 messages 抽取第一条有意义的 user 文本，缓存到 `currentSessionLastPrompt`
- `reAppendSessionMetadata()` 再把它真正写到文件尾部

所以它不是每条 user message 都单独写一行，而是**按“缓存后重写元数据”**的方式持久化。

## 5.5 `task-summary`

结构：

```ts
{
  type: 'task-summary'
  sessionId
  summary
  timestamp
}
```

用途：`claude ps` 一类列表显示“这个 agent 现在在做什么”。

写入责任：
- `saveTaskSummary()`

特点：
- 是滚动快照，不会被 `reAppendSessionMetadata()` 反复补写
- tail 读最后一条即可

## 5.6 `tag`

结构：

```ts
{
  type: 'tag'
  sessionId
  tag
}
```

写入责任：
- `saveTag()`
- `reAppendSessionMetadata()` 也会补写到尾部

## 5.7 `agent-name`

结构：

```ts
{
  type: 'agent-name'
  sessionId
  agentName
}
```

写入责任：
- `saveAgentName()`
- `reAppendSessionMetadata()` 也会补写

## 5.8 `agent-color`

结构：

```ts
{
  type: 'agent-color'
  sessionId
  agentColor
}
```

写入责任：
- `saveAgentColor()`
- `reAppendSessionMetadata()` 也会补写

## 5.9 `agent-setting`

结构：

```ts
{
  type: 'agent-setting'
  sessionId
  agentSetting
}
```

写入责任：
- `saveAgentSetting()` 先只缓存，不立刻建 metadata-only 文件
- `materializeSessionFile()` 首次真正落盘时通过 `reAppendSessionMetadata()` 写出
- 后续 exit / compact 后也会由 `reAppendSessionMetadata()` 再写

## 5.10 `pr-link`

结构：

```ts
{
  type: 'pr-link'
  sessionId
  prNumber
  prUrl
  prRepository
  timestamp
}
```

写入责任：
- `linkSessionToPR()`
- `reAppendSessionMetadata()` 会继续保活到文件尾部

## 5.11 `mode`

结构：

```ts
{
  type: 'mode'
  sessionId
  mode: 'coordinator' | 'normal'
}
```

写入责任：
- `saveMode()` 先缓存
- `materializeSessionFile()` / `reAppendSessionMetadata()` 落盘

## 5.12 `worktree-state`

结构：

```ts
{
  type: 'worktree-state'
  sessionId
  worktreeSession: PersistedWorktreeSession | null
}
```

`PersistedWorktreeSession` 字段包括：
- `originalCwd`
- `worktreePath`
- `worktreeName`
- `worktreeBranch?`
- `originalBranch?`
- `originalHeadCommit?`
- `sessionId`
- `tmuxSessionName?`
- `hookBased?`

写入责任：
- `saveWorktreeState()`
- 若 session file 已存在，则立刻 append 一条
- 否则缓存，等首次 materialize 或后续 `reAppendSessionMetadata()` 再写

## 5.13 `file-history-snapshot`

结构：

```ts
{
  type: 'file-history-snapshot'
  messageId
  snapshot
  isSnapshotUpdate
}
```

写入责任：
- `recordFileHistorySnapshot()`
- `Project.insertFileHistorySnapshot()`
- `appendEntry()`

用途：resume 时恢复文件历史状态。

## 5.14 `attribution-snapshot`

结构：

```ts
{
  type: 'attribution-snapshot'
  messageId
  surface
  fileStates
  promptCount?
  promptCountAtLastCommit?
  permissionPromptCount?
  permissionPromptCountAtLastCommit?
  escapeCount?
  escapeCountAtLastCommit?
}
```

写入责任：
- `recordAttributionSnapshot()`
- `Project.insertAttributionSnapshot()`

用途：commit attribution 恢复。

## 5.15 `queue-operation`

当前源码树里 `types/messageQueueTypes.js` 的类型定义文件没有找到，但写入端在 `src/utils/messageQueueManager.ts` 很清楚：

```ts
const queueOp: QueueOperationMessage = {
  type: 'queue-operation',
  operation,
  timestamp: new Date().toISOString(),
  sessionId,
  ...(content !== undefined && { content }),
}
```

写入责任：
- `messageQueueManager.ts` 的 `logOperation()`
- `recordQueueOperation()`
- `Project.insertQueueOperation()`

用途：统一命令队列的 enqueue / dequeue / priority 之类操作日志。

## 5.16 `speculation-accept`

结构：

```ts
{
  type: 'speculation-accept'
  timestamp
  timeSavedMs
}
```

写入责任：
- `services/PromptSuggestion/speculation.ts`

这里比较特别，它不是走 `appendEntry()`，而是**直接 appendFile 到主 transcript**：

```ts
void appendFile(getTranscriptPath(), jsonStringify(entry) + '\n')
```

说明这个 entry 是一个较独立的优化统计事件。

## 5.17 `content-replacement`

结构：

```ts
{
  type: 'content-replacement'
  sessionId
  agentId?
  replacements: ContentReplacementRecord[]
}
```

`ContentReplacementRecord` 当前至少有：

```ts
{
  kind: 'tool-result'
  toolUseId: string
  replacement: string
}
```

写入责任：
- `query.ts` 的 `applyToolResultBudget(...)`
- 回调里调用 `recordContentReplacement(records, agentId)`
- `Project.insertContentReplacement()`
- `appendEntry()`

路由规则：
- 没有 `agentId`，写主 session transcript
- 有 `agentId`，写对应 agent sidechain transcript

用途：resume 时重建“大 tool result 被替换为 stub”的状态，保证 prompt cache 稳定。

## 5.18 `marble-origami-commit`

结构：

```ts
{
  type: 'marble-origami-commit'
  sessionId
  collapseId
  summaryUuid
  summaryContent
  summary
  firstArchivedUuid
  lastArchivedUuid
}
```

写入责任：
- `recordContextCollapseCommit()`

用途：恢复 context-collapse 的提交历史。真正被折叠的消息本体本来就在 transcript 中，这里只保存“如何把那段区间解释为 collapse”。

## 5.19 `marble-origami-snapshot`

结构：

```ts
{
  type: 'marble-origami-snapshot'
  sessionId
  staged: [{ startUuid, endUuid, summary, risk, stagedAt }]
  armed
  lastSpawnTokens
}
```

写入责任：
- `recordContextCollapseSnapshot()`

用途：恢复 staged queue 和 spawn 触发状态。

## 5.20 `summary`

类型仍在 `logs.ts` 中：

```ts
{
  type: 'summary'
  leafUuid
  summary
}
```

读取路径 `loadTranscriptFile()` 也会消费它，并把 `summary` 归到 `summaries: Map<leafUuid, summary>`。

但这次在当前源码树里用 `rg` 没找到明确的写入点。也就是说：

- **当前分支依然支持读这种 entry**
- 但当前可见源码中没有明显的主动写入调用点
- 它更像是兼容旧格式 / 其他路径保留

这个结论要如实说明，不能假装已经看到写入端。

---

## 6. 哪些消息会被写进 transcript，哪些不会

## 6.1 统一过滤入口

`sessionStorage.ts`：`isLoggableMessage()`

规则：

1. `progress` 直接过滤掉
2. 对于非 `ant` 用户：大部分 `attachment` 不保存
3. 只有 `hook_additional_context` 并且设置了 `CLAUDE_CODE_SAVE_HOOK_ADDITIONAL_CONTEXT` 时，attachment 才允许落盘

所以：
- UI 看得到的 progress，通常**不会**出现在 `.jsonl`
- attachment 也不是全量保存

## 6.2 对外部用户 transcript 的二次改写

`cleanMessagesForLogging()` 在非 `ant` 用户下还会执行：

```ts
transformMessagesForExternalTranscript(filtered, collectReplIds(allMessages))
```

这个函数会做两件关键事：

### A. 去掉 REPL 包装层
- assistant 中的 `tool_use(name === REPL_TOOL_NAME)` 被过滤
- user 中对应的 REPL `tool_result` 也被过滤

### B. 把 `isVirtual` 消息提升成真实 transcript 消息
- 通过去掉 `isVirtual` 字段，使 resume 后看到的是“扁平化的原生工具调用历史”

这解释了一个很重要的现象：

**磁盘 transcript 不一定等于内存 messages 原样。它可能是一个经过脱壳和净化的“外部可恢复 transcript 版本”。**

---

## 7. 主会话写盘全流程

这一段是核心中的核心。

## 7.1 入口一，React UI 正常增量写盘

文件：`src/hooks/useLogMessages.ts`

当 `messages` 数组变化时：

1. 判断是增量 append，还是 compaction / shrink / 首次 render
2. 只切出新 tail，避免每次 O(n)
3. 调：

```ts
recordTranscript(slice, teamInfo, parentHint, messages)
```

这里它还维护了两个很重要的状态：
- `lastRecordedLengthRef`
- `lastParentUuidRef`

用途：
- 让增量写盘知道新消息应该接到谁后面
- 避免 compaction 后 parent hint 被旧消息扰乱

## 7.2 入口二，QueryEngine 在 query loop 前抢先落盘用户消息

文件：`src/QueryEngine.ts`

在真正进入 API 查询循环之前，用户输入已经先被 push 到 `mutableMessages`。然后：

```ts
const transcriptPromise = recordTranscript(messages)
```

注释写得很明确，原因是：

- 如果用户消息接受后，API 还没返回，进程就被杀掉
- 那 transcript 里可能只有 queue-operation，没有正式消息
- `--resume` 就找不到会话

所以这里做了一个**非常关键的“预落盘”动作**：

**用户消息一进主循环，就先写进 transcript。**

这是保证 kill-mid-request 仍可 resume 的关键设计。

## 7.3 入口三，query loop 过程中继续写 assistant / user / compact boundary

在 `QueryEngine.ts` 的 `for await (const message of query(...))` 里：

如果消息类型是：
- `assistant`
- `user`
- `system` 且 `subtype === 'compact_boundary'`

则继续调用 `recordTranscript(messages)`。

其中：
- assistant 写盘通常 fire-and-forget
- user / compact boundary 会 await

## 7.4 入口四，progress 和 attachment 某些路径会 inline 写盘触发 dedup 对齐

`QueryEngine.ts` 里：

- `progress` 到来时，会 `messages.push(message)` 然后 `void recordTranscript(messages)`
- `attachment` 到来时，也会 `messages.push(message)` 然后 `void recordTranscript(messages)`

注意这里的微妙点：

虽然 `progress` 本身最终会被 `isLoggableMessage()` 过滤掉，但**调用 recordTranscript 仍然有意义**，因为它会推动 dedup / parent hint / 增量 slice 对齐，不然下一条真正要落盘的 message 可能 parent 链错乱。

## 7.5 真正的统一写盘函数，`recordTranscript()`

`sessionStorage.ts`：

```ts
recordTranscript(messages, teamInfo, startingParentUuidHint, allMessages)
```

步骤如下：

### 第 1 步，清洗消息

```ts
const cleanedMessages = cleanMessagesForLogging(messages, allMessages)
```

### 第 2 步，拿当前 session 已有 UUID 集合

```ts
const messageSet = await getSessionMessages(sessionId)
```

`getSessionMessages()` 会从当前 transcript 文件读出所有 message UUID，并 memoize。

### 第 3 步，做 dedup，只保留真正新增消息

循环里：
- 如果 UUID 已存在，则认为已记录
- 但如果这些“已存在消息”位于前缀位置，并且是 chain participant，它们仍会更新 `startingParentUuid`

这个前缀 tracking 逻辑极关键，用于处理：
- growing array 的正常增量场景
- compaction 后 `[新 boundary, 新 summary, 旧 messagesToKeep]` 混排场景

### 第 4 步，调用 `insertMessageChain()`

```ts
await getProject().insertMessageChain(newMessages, false, undefined, startingParentUuid, teamInfo)
```

### 第 5 步，返回最后真正记录的 chain participant UUID

供 `useLogMessages()` 更新 `lastParentUuidRef`，保持后续增量写链正确。

---

## 8. `insertMessageChain()` 如何构造真正的链

这是最核心的写盘函数。

## 8.1 首次 materialize 机制

如果当前 `sessionFile === null`，并且这批消息里出现了第一个 `user` 或 `assistant`，就会先执行：

```ts
await this.materializeSessionFile()
```

### 为什么这么设计

因为 Claude Code 不想为了纯 metadata 或纯 attachment / progress 提前创建一个空会话文件。

所以：
- 只有真正开始对话了，才“实体化” session transcript
- 之前的 entry 会先暂存在 `pendingEntries`

## 8.2 `materializeSessionFile()` 做什么

1. `ensureCurrentSessionFile()` 确定路径
2. `reAppendSessionMetadata()` 把缓存里的 mode / title / tag / agent-setting 等先写进去
3. 把 `pendingEntries` 依次 flush

这就是为什么：
- `saveAgentSetting()` / `cacheSessionTitle()` / `saveMode()` 这类函数可以先只缓存
- 真正第一次用户发话时再统一写盘

## 8.3 parentUuid 计算规则

每条 message 初始 parent 为当前 `parentUuid`。

但有两个特殊分支：

### A. compact boundary

如果是 compact boundary：
- `parentUuid = null`
- `logicalParentUuid = 原来的 parentUuid`

这表示：
- **物理 parent 链被断开**，resume 默认从 boundary 以后开始
- 但逻辑上保留“之前接在哪”的信息，供 compact / preserved segment 等逻辑使用

### B. tool_result user message

如果这条 user message 带了 `sourceToolAssistantUUID`：

```ts
effectiveParentUuid = message.sourceToolAssistantUUID
```

这是为了解决 tool_result 必须挂到对应 tool_use assistant block 上，而不是简单串行挂到上一条消息后面。

## 8.4 chain participant 的定义

`isChainParticipant(m)` 规则非常简单：

- 只要 `m.type !== 'progress'` 就是 chain participant

所以：
- progress 不参与 parent 链推进
- user / assistant / attachment / system 都会推进链

## 8.5 统一盖章 session fields

`insertMessageChain()` 在 `...message` 之后强制重盖：
- `userType`
- `entrypoint`
- `cwd`
- `sessionId`
- `version`
- `gitBranch`
- `slug`

源码注释明确说这是 load-bearing：

如果 resume / fork 后直接把旧 `SerializedMessage` 再写入新文件，不重新 stamp，可能出现：
- message 行还是旧 sessionId
- content-replacement entry 是新 sessionId
- 最终 `loadFullLog()` keyed lookup 对不上，replacement 记录丢失

所以这一步是**防 resume/fork 污染新 transcript 的关键保护**。

## 8.6 更新 `currentSessionLastPrompt`

主链写完后，如果不是 sidechain，会从本轮消息中抽出第一条有意义的 user 文本，裁成最多 200 字，缓存为 `currentSessionLastPrompt`，供 `reAppendSessionMetadata()` 尾插 `last-prompt` entry。

---

## 9. `appendEntry()` 如何真正写入文件

`appendEntry()` 是 entry 级统一出口。

## 9.1 总体分流

它先决定：
- 当前 session 还是其他 session
- 主 transcript 还是 agent sidechain transcript
- 哪些 entry 可以直接 append
- 哪些 message 需要 dedup

## 9.2 绝大多数 metadata entry 直接入队

例如：
- `custom-title`
- `ai-title`
- `last-prompt`
- `task-summary`
- `tag`
- `agent-name`
- `agent-color`
- `agent-setting`
- `pr-link`
- `file-history-snapshot`
- `attribution-snapshot`
- `speculation-accept`
- `mode`
- `worktree-state`
- `marble-origami-commit`
- `marble-origami-snapshot`

都直接：

```ts
void this.enqueueWrite(sessionFile, entry)
```

## 9.3 `content-replacement` 特殊路由

```ts
const targetFile = entry.agentId ? getAgentTranscriptPath(entry.agentId) : sessionFile
```

主线程 replacement 写主文件，agent replacement 写 agent 文件。

## 9.4 transcript message 的 dedup 规则

对 user / assistant / attachment / system：

1. 先看 UUID 是否已在 `messageSet` 中
2. 若是 agent sidechain local write，则允许绕过主 session 的 dedup
3. 若是新 UUID，才 enqueueWrite
4. 若是主链消息，还会 `messageSet.add(uuid)` 并尝试 remote persistence

这里有一条非常重要的注释：

**sidechain 本地写入不能拿主 session 的 messageSet 来 dedup**，否则 fork 继承来的消息因为 UUID 跟主链重复，会被错误跳过，agent transcript 会残缺。

## 9.5 真正的磁盘写入队列

`Project` 内部有：
- `writeQueues: Map<filePath, Entry[]>`
- `FLUSH_INTERVAL_MS = 100`
- `MAX_CHUNK_BYTES = 100 * 1024 * 1024`

流程：

1. `enqueueWrite()` 把 entry 放入对应文件的队列
2. `scheduleDrain()` 启动定时 drain
3. `drainWriteQueue()` 把多条 entry 拼成 `jsonStringify(entry) + '\n'`
4. `appendToFile()` 统一 append
5. 文件不存在时先 `mkdir(dirname(filePath), { recursive: true, mode: 0o700 })`
6. 文件 append 权限 `0o600`

所以磁盘层是：
- 目录权限 700
- 文件权限 600
- 小批量缓冲 append
- 按文件维度保持顺序

## 9.6 某些 metadata helper 走同步直写，不走队列

例如：
- `appendEntryToFile()` 被 `saveCustomTitle()`、`saveTag()`、`saveAgentName()`、`saveAgentColor()`、`saveAiGeneratedTitle()`、`saveTaskSummary()`、`linkSessionToPR()`、`reAppendSessionMetadata()` 等使用

它是同步 `appendFileSync`，失败则先 `mkdirSync` 再 append。

也就是说，源码里其实有**两种写法并存**：

1. `appendEntry()` -> enqueueWrite -> async batched append
2. metadata helper -> `appendEntryToFile()` -> sync immediate append

---

## 10. 远端持久化如何发生

只对 transcript message 走远端同步，metadata entry 不走这里。

## 10.1 触发点

在 `appendEntry()` 中：

```ts
if (isTranscriptMessage(entry)) {
  await this.persistToRemote(sessionId, entry)
}
```

## 10.2 两条路径

### A. CCR v2 internal event

若注册了 `internalEventWriter`：

```ts
await this.internalEventWriter('transcript', entry, meta)
```

附加 meta 会标出：
- `isCompaction`
- `agentId`

### B. v1 Session Ingress

否则如果启用了 `ENABLE_SESSION_PERSISTENCE` 且有 `remoteIngressUrl`，就调用：

```ts
sessionIngress.appendSessionLog(sessionId, entry, url)
```

## 10.3 Session Ingress 的并发控制

`src/services/api/sessionIngress.ts` 做了几件事：

1. `sequentialAppendBySession` 保证同一 session 串行 PUT
2. `Last-Uuid` header 做 optimistic concurrency control
3. 409 时尝试采用服务端 `x-last-uuid`
4. 或重新拉取 session log 来找到 server head
5. 最多重试 10 次，指数退避
6. 401 直接失败

这说明远端持久化本质上也是 append-only 链，只不过 server 端以 `Last-Uuid` 保证顺序一致性。

---

## 11. 子代理和 sidecar `.json` 的完整职责

## 11.1 `agent-<agentId>.jsonl`，子代理 transcript

写入入口：`runAgent.ts`

### 初始写入

子代理启动时先：

```ts
recordSidechainTranscript(initialMessages, agentId)
```

### 后续写入

query 流里每到一条 `isRecordableMessage(message)`：

```ts
await recordSidechainTranscript([message], agentId, lastRecordedUuid)
```

这让 agent transcript 自己形成一条独立 parent 链。

## 11.2 `agent-<agentId>.meta.json`，为什么单独存在

结构：

```ts
type AgentMetadata = {
  agentType: string
  worktreePath?: string
  description?: string
}
```

写入点：`runAgent.ts`

```ts
writeAgentMetadata(agentId, {
  agentType,
  worktreePath,
  description,
})
```

用途：
- resume 子代理时，如果没显式传 `subagent_type`，仍能知道原来是什么 agentType
- 能恢复 worktree cwd
- UI 通知还能显示原始 description

为什么不用塞进 `.jsonl`：
- 注释写得很明确，sidecar 避免改 JSONL schema
- 这类“启动配置身份信息”比“事件流”更适合单独 sidecar

## 11.3 子代理 resume 如何恢复

`resumeAgent.ts`：

1. `getAgentTranscript(agentId)` 读取 agent transcript
2. `readAgentMetadata(agentId)` 读取 sidecar
3. `filterUnresolvedToolUses()`、`filterWhitespaceOnlyAssistantMessages()` 等清洗消息
4. `reconstructForSubagentResume(...)` 用 transcript + replacement 记录恢复 tool result replacement state
5. 从 `meta.worktreePath` 恢复 cwd
6. 根据 `meta.agentType` 选择正确 agent definition
7. 再次运行 `runAgent()` 继续执行

## 11.4 `remote-agent-<taskId>.meta.json`

结构：

```ts
type RemoteAgentMetadata = {
  taskId: string
  remoteTaskType: string
  sessionId: string
  title: string
  command: string
  spawnedAt: number
  toolUseId?: string
  isLongRunning?: boolean
  isUltraplan?: boolean
  isRemoteReview?: boolean
  remoteTaskMetadata?: Record<string, unknown>
}
```

写入责任：
- `RemoteAgentTask.tsx` 的 `persistRemoteAgentMetadata()`
- 实际落盘是 `writeRemoteAgentMetadata()`

用途：
- session resume 后重新连上仍在运行的远端 CCR session

恢复责任：
- `restoreRemoteAgentTasks()`
- 扫描 `remote-agents/*.meta.json`
- 用 `fetchSession(meta.sessionId)` 拉 live 状态
- 如果 session 还活着，就把 task 重新注册回 AppState 并继续 polling
- 若已 archived 或 404，则删除 sidecar

这里也能看出一个设计边界：

**远端任务的本地 sidecar 只存“身份与连接信息”，实际状态以远端会话 API 为准。**

---

## 12. tombstone / 删除是怎么处理的

主 transcript 基本是 append-only，但有一个例外：删除孤儿消息。

入口：
- `removeTranscriptMessage(targetUuid)`
- `Project.removeMessageByUuid()`

策略：

1. 优先只读最后 64KB tail
2. 找到包含 `"uuid":"<target>"` 的整行
3. 尝试用 truncate + 回写尾部剩余内容的方式就地删除
4. 如果 tail 没找到，再慢路径全文件读出、过滤目标行、重写
5. 文件太大时直接放弃慢路径

用途：
- streaming 失败留下 orphan message 时，用 tombstone 清理

这个删除机制是一个**针对异常残留的修补通道**，不是常规的会话存储模式。

---

## 13. 读取全流程，`.jsonl` 如何被重新解释成会话

## 13.1 轻量列表读取，`readLiteMetadata()`

当只是做 `/resume` 列表，不想把所有大 transcript 全量 parse 时，`sessionStorage.ts` 会：

1. 只读文件头和文件尾大约各 64KB
2. 从 head / tail 通过字符串扫描抽取 lite metadata

抽取字段包括：
- `isSidechain`
- `cwd`
- `teamName`
- `agentSetting`
- `firstPrompt`
- `customTitle`
- `aiTitle`
- `summary`
- `tag`
- `gitBranch`
- `prNumber`
- `prUrl`
- `prRepository`

这里有几个很重要的设计：

### A. `last-prompt` 优先于 head 里的第一条 user prompt
因为它更能代表“最近在做什么”。

### B. `customTitle` 优先于 `aiTitle`
因为用户重命名永远优先。

### C. 不做全文件扫描
只靠 bounded head/tail 提取，用来保证 session 列表加载快。

## 13.2 完整读取，`loadTranscriptFile()`

这是完整解析器，返回：

- `messages`
- `summaries`
- `customTitles`
- `tags`
- `agentNames`
- `agentColors`
- `agentSettings`
- `prNumbers`
- `prUrls`
- `prRepositories`
- `modes`
- `worktreeStates`
- `fileHistorySnapshots`
- `attributionSnapshots`
- `contentReplacements`
- `agentContentReplacements`
- `contextCollapseCommits`
- `contextCollapseSnapshot`
- `leafUuids`

这基本就是“整个 transcript 文件被重新解释后的结构化结果”。

### 13.2.1 大文件优化

`loadTranscriptFile()` 在大文件上不是傻读：

- `readTranscriptForLoad()` 可先截掉 compact boundary 以前的大量老内容
- `scanPreBoundaryMetadata()` 会把 boundary 之前的 metadata 行先扫出来，避免 mode / tag / pr-link 丢失
- `walkChainBeforeParse()` 会在 parse 之前先按 parent 链剪掉 dead fork branches，减少 `JSON.parse` 成本

这说明 resume 读取器已经高度针对“超大 transcript、多次 compact、很多 fork”做优化。

### 13.2.2 legacy progress bridge

旧 transcript 里可能还存在 `progress` entry，新的 `Entry` 已不再包含它。

于是 loader 会：
- 遇到 legacy progress entry 时，记录 `progress uuid -> parentUuid`
- 如果后面真实 transcript message 的 `parentUuid` 指向 progress，就把它桥接到 progress 的非 progress 父节点

这就是为什么旧数据还能继续 resume。

### 13.2.3 compact boundary 的特殊处理

加载过程中如果碰到 compact boundary：
- 会清空已有的 `contextCollapseCommits`
- 清掉 `contextCollapseSnapshot`

因为 boundary 之前的一些 collapse 记录对 post-boundary chain 已经不再适用。

### 13.2.4 metadata 的聚合方式

非 message entry 被读入不同的 map：
- `sessionId -> customTitle / tag / agentName / agentColor / agentSetting / mode / worktree / pr-link`
- `messageId -> fileHistorySnapshot / attributionSnapshot`
- `sessionId -> contentReplacements`
- `agentId -> agentContentReplacements`
- `leafUuid -> summary`

## 13.3 如何确定 leaf

`loadTranscriptFile()` 最后会算 `leafUuids`。

逻辑是：
1. 先找没有子节点的 terminal messages
2. 再沿 parent 往回走
3. 找最近的 user / assistant 祖先作为 leaf
4. 必要时跳过“其实仍有 user/assistant 子节点”的中间节点

这样可以避免 attachment / system / legacy progress 干扰真正的会话叶子。

---

## 14. buildConversationChain 和 resume 不是简单链表，有修复后处理

## 14.1 基础 parent 链回溯

`buildConversationChain(messages, leafMessage)`：

1. 从 leaf 沿 `parentUuid` 一路往回走到 root
2. 检测 cycle
3. reverse 成 root -> leaf

## 14.2 `recoverOrphanedParallelToolResults()` 修复并行 tool use DAG

这是非常关键的读侧修复。

问题背景：
- streaming 时，一次 assistant 输出多个 content block
- 并行 tool_use 可能变成多个 assistant message，拥有同一个 `message.id`
- 每个 tool_result 又各自挂到不同 assistant UUID 上
- 这样磁盘拓扑其实是 DAG，不是单链表

单纯 parent walk 会丢掉：
- sibling assistant block
- 对应的 tool_result user message

于是 `recoverOrphanedParallelToolResults()` 会：
1. 找链上 assistant
2. 按 `message.id` 分组 sibling assistant
3. 找出没在主链上的 sibling
4. 再找它们对应的 tool_result
5. 按 timestamp 排序后插回 anchor assistant 后面

这一步很关键，否则 resume 后并行工具调用历史会残缺。

## 14.3 `checkResumeConsistency()`

resume 完成后还会拿 transcript 里的 `turn_duration` checkpoint 做一致性检查，统计 resume 后链长度和原本记录是否偏移，用来监控“写入态和恢复态不一致”的 bug。

---

## 15. `loadFullLog()` 如何把一个 lite log 变成可 resume 的 full log

`loadFullLog(log)` 会：

1. 调 `loadTranscriptFile(sessionFile)`
2. 找最新 leaf
3. `buildConversationChain(messages, mostRecentLeaf)`
4. `removeExtraFields()` 去掉 transcript-only 字段：
   - `isSidechain`
   - `parentUuid`
5. 重新装回 `LogOption`

同时补齐：
- `summary`
- `customTitle`
- `tag`
- `agentName`
- `agentColor`
- `agentSetting`
- `mode`
- `worktreeSession`
- `prNumber`
- `prUrl`
- `prRepository`
- `gitBranch`
- `fileHistorySnapshots`
- `attributionSnapshots`
- `contentReplacements`
- `contextCollapseCommits`
- `contextCollapseSnapshot`

这一步其实就是“把 JSONL 事件流重建成一个可展示、可继续对话的 session 对象”。

---

## 16. resume 全流程

## 16.1 入口，`loadConversationForResume()`

文件：`conversationRecovery.ts`

支持几种来源：
- `undefined`，表示继续最近会话
- 指定 session ID
- 指定 `.jsonl` 路径
- 传入已有 `LogOption`

流程：
1. 选定 log 或直接从 jsonl 路径加载
2. 如果是 lite log，则 `loadFullLog()`
3. 如果 sessionId 已知，`copyPlanForResume(log, sessionId)`
4. `copyFileHistoryForResume(log)`
5. `checkResumeConsistency(messages)`
6. `restoreSkillStateFromMessages(messages)`
7. `deserializeMessagesWithInterruptDetection(messages)`
8. 处理 session-start hooks
9. 返回 messages + 各种恢复所需 metadata

## 16.2 `sessionRestore.ts` 负责把恢复结果重新灌回运行时状态

### `restoreSessionStateFromLog()` 负责：
- file history state
- attribution state
- context-collapse commit log / snapshot
- TodoWrite state

### `processResumedConversation()` 负责：
- 切回原 sessionId（除非 fork-session）
- `resetSessionFilePointer()`
- `restoreCostStateForSession()`
- `restoreSessionMetadata(...)`
- `restoreWorktreeForResume(...)`
- `adoptResumedSessionFile()`
- 恢复 agent setting / mode / standalone agent context

## 16.3 `adoptResumedSessionFile()` 的意义

resume 时不是新建 transcript 文件，而是：

```ts
project.sessionFile = getTranscriptPath()
project.reAppendSessionMetadata(true)
```

这样做的目的：
- 当前进程接管已有 transcript 文件
- 即使 resume 后用户还没发新消息，exit cleanup 时也能把 metadata 正常回写

---

## 17. compact / context collapse 对 transcript 的影响

## 17.1 compact boundary 怎么写

`messages.ts` 里 `createCompactBoundaryMessage()` 会生成：

```ts
{
  type: 'system',
  subtype: 'compact_boundary',
  content: 'Conversation compacted',
  compactMetadata: {
    trigger,
    preTokens,
    userContext,
    messagesSummarized,
  },
  logicalParentUuid: lastPreCompactMessageUuid?,
}
```

真正写盘时 `insertMessageChain()` 会把它处理成：
- `parentUuid = null`
- `logicalParentUuid = 原 parent`

也就是：
- 物理链断开
- 逻辑链信息保留

## 17.2 compact summary 本质上是 user message

`compact.ts` 会构造：

```ts
createUserMessage({
  content: getCompactUserSummaryMessage(...),
  isCompactSummary: true,
  summarizeMetadata: {...},
})
```

所以 compact summary 并不是单独的 `summary` entry，而是**一条普通 user message，只是附加了 `isCompactSummary` / `summarizeMetadata`**。

## 17.3 metadata 为什么反复重写到 tail

compact 后，旧的 title / tag / mode / pr-link 可能离 EOF 太远。
`readLiteMetadata()` 只读尾部窗口，可能就看不到了。

所以 `compact.ts` 在 compact 后会主动：

```ts
reAppendSessionMetadata()
```

这是 resume 列表还能显示正确标题和 tag 的关键。

## 17.4 preserved segment 修复

若 compact boundary 带 preserved segment，`loadTranscriptFile()` 之后还会执行：

```ts
applyPreservedSegmentRelinks(messages)
```

因为 preserved messages 在磁盘上还保留原 parentUuid，需要读侧重接 head / tail / anchor，避免 resume 错把它们当 orphan。

---

## 18. 一个典型 `.jsonl` 文件长什么样

下面给一个根据源码结构抽象出来的“可能的实际组合”，不是逐字真实样本，但字段组织是对的：

```json
{"type":"custom-title","sessionId":"S","customTitle":"修 transcript 持久化"}
{"type":"agent-setting","sessionId":"S","agentSetting":"general-purpose"}
{"parentUuid":null,"isSidechain":false,"type":"user","message":{"role":"user","content":"请分析 transcript"},"uuid":"u1","timestamp":"...","userType":"external","entrypoint":"cli","cwd":"/repo","sessionId":"S","version":"...","gitBranch":"main","slug":"abc"}
{"parentUuid":"u1","isSidechain":false,"type":"assistant","message":{"id":"msg_1","role":"assistant","content":[{"type":"text","text":"我先检查源码"}]},"uuid":"a1","timestamp":"...","userType":"external","entrypoint":"cli","cwd":"/repo","sessionId":"S","version":"...","gitBranch":"main","slug":"abc"}
{"type":"file-history-snapshot","messageId":"u1","snapshot":{...},"isSnapshotUpdate":false}
{"type":"queue-operation","operation":"enqueue","timestamp":"...","sessionId":"S","content":"/compact"}
{"parentUuid":null,"logicalParentUuid":"a1","isSidechain":false,"type":"system","subtype":"compact_boundary","content":"Conversation compacted","uuid":"cb1","timestamp":"...","compactMetadata":{...},"userType":"external","entrypoint":"cli","cwd":"/repo","sessionId":"S","version":"...","gitBranch":"main","slug":"abc"}
{"parentUuid":"cb1","isSidechain":false,"type":"user","isCompactSummary":true,"summarizeMetadata":{...},"message":{"role":"user","content":"以下是压缩摘要..."},"uuid":"u2","timestamp":"...","userType":"external","entrypoint":"cli","cwd":"/repo","sessionId":"S","version":"...","gitBranch":"main","slug":"abc"}
{"type":"last-prompt","sessionId":"S","lastPrompt":"分析 transcript 落盘链路"}
{"type":"tag","sessionId":"S","tag":"storage"}
{"type":"pr-link","sessionId":"S","prNumber":123,"prUrl":"https://...","prRepository":"owner/repo","timestamp":"..."}
{"type":"worktree-state","sessionId":"S","worktreeSession":{...}}
{"type":"content-replacement","sessionId":"S","replacements":[{"kind":"tool-result","toolUseId":"toolu_1","replacement":"<persisted_output ...>"}]}
```

从这个组合就能看出来：

**一个 `.jsonl` 文件里混合的是：消息图节点 + 会话元数据 + 快照 + 修复指令 + UI/恢复辅助信息。**

---

## 19. “哪部分内容由哪些代码负责注入”总表

| 内容 | 负责代码 | 注入方式 |
|---|---|---|
| `parentUuid` / `logicalParentUuid` | `Project.insertMessageChain()` | 根据 parent 链和 compact boundary 计算 |
| `isSidechain` | `recordTranscript()` / `recordSidechainTranscript()` -> `insertMessageChain()` | 主链为 false，子代理为 true |
| `cwd` | `insertMessageChain()` | `getCwd()` 统一盖章 |
| `userType` | `insertMessageChain()` | `getUserType()` 统一盖章 |
| `entrypoint` | `insertMessageChain()` | `getEntrypoint()` 统一盖章 |
| `sessionId` | `insertMessageChain()` | 当前 session 强制重盖，防 resume/fork 污染 |
| `timestamp` | message 创建时已有，metadata helper 也会手写 | createUserMessage / createProgressMessage / saveTaskSummary 等 |
| `version` | `insertMessageChain()` | `VERSION` 统一盖章 |
| `gitBranch` | `insertMessageChain()` | 每次写链前 `getBranch()` 取一次 |
| `slug` | `insertMessageChain()` | 从 `getPlanSlugCache().get(sessionId)` 注入 |
| `promptId` | `insertMessageChain()` | 仅 user message，`getPromptId()` |
| `teamName` / `agentName`（message级） | `useLogMessages.ts` -> `recordTranscript(teamInfo)` -> `insertMessageChain()` | swarm/team context 注入 |
| `custom-title` | `saveCustomTitle()`，以及 `reAppendSessionMetadata()` | metadata entry |
| `ai-title` | `saveAiGeneratedTitle()` | metadata entry |
| `last-prompt` | `insertMessageChain()` 缓存，`reAppendSessionMetadata()` 写出 | metadata entry |
| `tag` | `saveTag()`，以及 `reAppendSessionMetadata()` | metadata entry |
| `agent-setting` | `saveAgentSetting()` 缓存，`materializeSessionFile()` / `reAppendSessionMetadata()` 写出 | metadata entry |
| `mode` | `saveMode()` 缓存，`materializeSessionFile()` / `reAppendSessionMetadata()` 写出 | metadata entry |
| `worktree-state` | `saveWorktreeState()` | metadata entry |
| `pr-link` | `linkSessionToPR()`，以及 `reAppendSessionMetadata()` | metadata entry |
| `file-history-snapshot` | `recordFileHistorySnapshot()` | entry |
| `attribution-snapshot` | `recordAttributionSnapshot()` | entry |
| `queue-operation` | `messageQueueManager.logOperation()` | entry |
| `speculation-accept` | `PromptSuggestion/speculation.ts` | 直接 appendFile |
| `content-replacement` | `query.ts` -> `recordContentReplacement()` | entry |
| `marble-origami-commit/snapshot` | `recordContextCollapseCommit/Snapshot()` | entry |
| 子代理 `agentType/worktreePath/description` | `writeAgentMetadata()` | sidecar `.meta.json` |
| 远程代理连接信息 | `writeRemoteAgentMetadata()` | sidecar `.meta.json` |

---

## 20. 最重要的理解框架

如果只记一个模型，请记这个：

### 20.1 主 transcript 不是“聊天记录文件”
它是：
- 一部分真正消息
- 一部分会话级 metadata
- 一部分恢复辅助快照
- 一部分 compact / collapse / replacement 修复信息

### 20.2 `.json` sidecar 不是主数据源
sidecar 只负责放那些：
- 不是事件流
- 或者不想污染 transcript schema
- 或者 resume 时只需要“身份与配置”，不需要事件回放

典型就是：
- agentType / worktreePath / description
- remote session identity

### 20.3 resume 不是读数组，是重建图
resume 真正做的是：
1. 解析 `.jsonl` entry 流
2. 分离 message / metadata / snapshots
3. 建 parent graph
4. 找 leaf
5. 恢复 compact 后结构
6. 恢复并行 tool result
7. 恢复 worktree / attribution / fileHistory / contentReplacement / remote tasks / agent context

---

## 21. 本次源码核对后，可以确认的几个关键判断

1. **`.jsonl` 是追加式事件日志，不是纯对话文本。**
2. **真正消息写盘主链是：**
   - `useLogMessages()` / `QueryEngine.ts`
   - `recordTranscript()`
   - `cleanMessagesForLogging()`
   - `insertMessageChain()`
   - `appendEntry()`
3. **子代理写盘主链是：**
   - `runAgent.ts`
   - `recordSidechainTranscript()`
   - `insertMessageChain()`
   - `appendEntry()`
4. **resume 主链是：**
   - `loadConversationForResume()`
   - `loadFullLog()` / `loadTranscriptFile()`
   - `buildConversationChain()`
   - `recoverOrphanedParallelToolResults()`
   - `sessionRestore.ts` 恢复运行时状态
5. **compact 并不删除历史，而是通过 compact boundary、summary user message、preserved segment relink、pre-boundary skip 等机制逻辑重构“当前可继续会话”。**
6. **sidecar `.json` 主要用于 agent / remote-agent 这种“启动身份和恢复入口”信息，不承担完整事件流。**

---

## 22. 仍需诚实标注的边界

本次源码扫描里，有两个点需要如实说明：

1. `SummaryMessage { type: 'summary', leafUuid, summary }` 的**读取支持是明确存在的**，但当前扫描到的源码里**没有找到清晰的主动写入点**。
2. `QueueOperationMessage` 的类型定义文件 `../types/messageQueueTypes.js` 在当前源码镜像里没有直接找到，但其实际写入对象结构可由 `messageQueueManager.ts` 明确反推出核心字段。

这两个点不影响主结论，但文档里必须保留这个事实，不能把“推断”写成“已证实源码存在”。

---

## 23. 最后一句总结

**Claude Code 的会话持久化，本质上是“基于 parentUuid 的消息图 + 一组附属 entry 与 sidecar 元数据”共同构成的恢复系统。**

所以你如果想真正学会它，不能只盯着 user / assistant 两种消息，而要把下面四层一起看：

1. **写入层**：`recordTranscript()` / `insertMessageChain()` / `appendEntry()`
2. **消息结构层**：`Message` / `TranscriptMessage` / compact summary / tool_result parent override
3. **恢复层**：`loadTranscriptFile()` / `buildConversationChain()` / `recoverOrphanedParallelToolResults()` / `sessionRestore.ts`
4. **sidecar 层**：`agent-*.meta.json` / `remote-agent-*.meta.json`

只有这四层合起来，`.jsonl` / `.json` 的会话记录机制才算真正被吃透。
