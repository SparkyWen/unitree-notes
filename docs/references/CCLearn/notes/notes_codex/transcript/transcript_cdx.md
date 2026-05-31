# Claude Code 会话记录源码深度拆解

本文基于源码目录：`~/.openclaw/workspace/cc/claude_code/source/src`

目标：彻底解释 `.jsonl` / `.json` 会话信息是如何记录的，记录了哪些内容，完整写入与读取流程是什么，哪些内容会进入 transcript，哪些只会注入给 API 但不会落盘，以及分别由哪些代码负责。

---

## 1. 先说结论

Claude Code 的会话持久化核心是：

- **主会话 transcript 文件**：`~/.claude/projects/<sanitized-project-path>/<sessionId>.jsonl`
- **子代理 transcript 文件**：`~/.claude/projects/<sanitized-project-path>/<sessionId>/subagents/.../agent-<agentId>.jsonl`
- **子代理元数据 sidecar**：`agent-<agentId>.meta.json`
- **远程代理元数据 sidecar**：`remote-agent-<taskId>.meta.json`

主逻辑几乎都集中在：

- `src/utils/sessionStorage.ts`
- `src/utils/messages.ts`
- `src/types/logs.ts`
- `src/utils/json.ts`
- `src/hooks/useLogMessages.ts`

**最重要的一点：**
`.jsonl` 不是只保存“用户一句 + 助手一句”这么简单，它保存的是一个**追加式事件日志**。其中混合了：

1. 真正的 transcript message（user / assistant / attachment / system）
2. 会话元数据事件（title、tag、agent-setting、PR link、worktree-state 等）
3. 快照/补丁类事件（file-history-snapshot、attribution-snapshot、content-replacement）
4. compaction / summary / collapse 相关事件

也就是说，一个 `.jsonl` 文件本质上是“**会话事件流**”，不是单纯聊天文本。

---

## 2. 文件路径与目录结构

### 2.1 主 transcript 路径
代码：`src/utils/sessionStorage.ts`

```ts
export function getProjectsDir(): string {
  return join(getClaudeConfigHomeDir(), 'projects')
}

export function getTranscriptPath(): string {
  const projectDir = getSessionProjectDir() ?? getProjectDir(getOriginalCwd())
  return join(projectDir, `${getSessionId()}.jsonl`)
}
```

结论：

- 根目录是 `~/.claude/projects`
- 每个项目 cwd 会被 `sanitizePath` 处理成一个目录名
- 每个 session 一个 `<sessionId>.jsonl`

### 2.2 子代理 transcript
代码：`getAgentTranscriptPath()`

路径形态：

```text
~/.claude/projects/<project>/<sessionId>/subagents/agent-<agentId>.jsonl
```

也支持带子目录：

```text
~/.claude/projects/<project>/<sessionId>/subagents/<subdir>/agent-<agentId>.jsonl
```

### 2.3 sidecar `.json`
不是所有数据都进 `.jsonl`，有些 metadata 单独放 `.json`：

- `agent-<agentId>.meta.json`
- `remote-agent-<taskId>.meta.json`

这些由：

- `writeAgentMetadata()` / `readAgentMetadata()`
- `writeRemoteAgentMetadata()` / `readRemoteAgentMetadata()`

负责。

---

## 3. `.jsonl` 每一行到底是什么

### 3.1 顶层 union
代码：`src/types/logs.ts`

`Entry` 是整个 JSONL 的总联合类型：

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

所以，**一个 `.jsonl` 文件中，每一行都是一个 `Entry` JSON 对象。**

不是只有 message。

---

## 4. 真正的 transcript message 长什么样

### 4.1 TranscriptMessage 结构
代码：`src/types/logs.ts`

```ts
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

而 `SerializedMessage = Message & { ...session fields... }`

额外统一打上的字段有：

```ts
cwd: string
userType: string
entrypoint?: string
sessionId: string
timestamp: string
version: string
gitBranch?: string
slug?: string
```

### 4.2 也就是说，每条真正消息至少包含两层信息

#### A. 消息本体
来自 `Message`，类型可能是：

- `user`
- `assistant`
- `attachment`
- `system`

#### B. transcript 持久化附加壳
统一再加上：

- `parentUuid`
- `isSidechain`
- `sessionId`
- `cwd`
- `userType`
- `version`
- `timestamp`
- `gitBranch`
- `slug`
- 可能还有 `promptId` / `agentId` / `teamName`

这就是为什么一条 JSONL message 行不是“纯 API message”，而是“**会话图节点 + 环境上下文**”。

---

## 5. 哪些消息会被真正写进 transcript

### 5.1 单一判定入口
代码：`isTranscriptMessage()` in `sessionStorage.ts`

```ts
export function isTranscriptMessage(entry: Entry): entry is TranscriptMessage {
  return (
    entry.type === 'user' ||
    entry.type === 'assistant' ||
    entry.type === 'attachment' ||
    entry.type === 'system'
  )
}
```

### 5.2 progress 不会作为 transcript message 持久化
源码明确写了：

- `progress` 不是 transcript message
- progress 是 UI ephemeral state
- 不能参与 parentUuid chain

这是一个关键点。

所以：

- 你在 UI 里看到的某些进度消息，不一定会落进 `.jsonl`
- 老版本历史里可能残留 legacy progress，需要读入时 bridge 修复

---

## 6. 写入从哪里开始

### 6.1 React hook 入口
代码：`src/hooks/useLogMessages.ts`

当内存中的 `messages` 数组变化时，这个 hook 会触发：

```ts
void recordTranscript(slice, teamInfo, parentHint, messages)
```

也就是说，**UI/app state 中 append 的 message，不会立刻直接写文件，而是由 `useLogMessages` 统一增量刷盘。**

### 6.2 recordTranscript 做了什么
代码：`sessionStorage.ts`

```ts
export async function recordTranscript(messages, teamInfo, startingParentUuidHint, allMessages)
```

核心步骤：

1. `cleanMessagesForLogging(messages, allMessages)`
2. 读取当前 session 已存在 UUID 集合 `getSessionMessages(sessionId)`
3. 去重，找出真正新增消息
4. 计算 `startingParentUuid`
5. 调 `getProject().insertMessageChain(...)`

这说明：

- transcript 是**增量 append**，不是每次全量重写
- dedup 依赖 message UUID
- parent chain 是写入时计算好的

---

## 7. 写入前的清洗逻辑

### 7.1 cleanMessagesForLogging
代码：`sessionStorage.ts`

```ts
export function cleanMessagesForLogging(messages, allMessages = messages): Transcript {
  const filtered = messages.filter(isLoggableMessage)
  return getUserType() !== 'ant'
    ? transformMessagesForExternalTranscript(filtered, collectReplIds(allMessages))
    : filtered
}
```

### 7.2 isLoggableMessage
规则：

- `progress` 一律不写
- `attachment` 对 external 用户大多不写
- 只有特定 hook additional context 在开关允许时可写

```ts
if (m.type === 'progress') return false
if (m.type === 'attachment' && getUserType() !== 'ant') { ... return false }
```

### 7.3 外部用户 transcript 还会做 REPL 去包装
`transformMessagesForExternalTranscript()` 会：

- 去掉 REPL tool_use/tool_result 包装层
- 把 `isVirtual` 消息“升格”为真实消息
- 最终让落盘 transcript 看起来像原生工具调用历史

这非常关键。

#### 含义
你在内存/UI/运行时看到的消息结构，**不等于** 最终落盘结构。

尤其是 REPL 包装会在 external transcript 中被剥掉。

---

## 8. 真正写入 JSONL 的核心函数

### 8.1 insertMessageChain
代码：`Project.insertMessageChain()` in `sessionStorage.ts`

它对每条 message 构建 `TranscriptMessage`：

```ts
const transcriptMessage: TranscriptMessage = {
  parentUuid: isCompactBoundary ? null : effectiveParentUuid,
  logicalParentUuid: isCompactBoundary ? parentUuid : undefined,
  isSidechain,
  teamName: teamInfo?.teamName,
  agentName: teamInfo?.agentName,
  promptId: message.type === 'user' ? (getPromptId() ?? undefined) : undefined,
  agentId,
  ...message,
  userType: getUserType(),
  entrypoint: getEntrypoint(),
  cwd: getCwd(),
  sessionId,
  version: VERSION,
  gitBranch,
  slug,
}
```

然后：

```ts
await this.appendEntry(transcriptMessage)
```

### 8.2 这里注入了哪些字段
由 `insertMessageChain()` 注入：

- `parentUuid`
- `logicalParentUuid`
- `isSidechain`
- `teamName`
- `agentName`
- `promptId`
- `agentId`
- `userType`
- `entrypoint`
- `cwd`
- `sessionId`
- `version`
- `gitBranch`
- `slug`

这就是你问的“哪部分内容由哪些代码负责注入”的一个核心答案。

---

## 9. parentUuid 链是怎么形成的

写入时维护一个 `parentUuid` 游标：

- 默认每条新消息接上前一条 chain participant
- 但 `progress` 不参与链
- `tool_result` 这种 user message，如果带 `sourceToolAssistantUUID`，会把 parent 直接指向对应 assistant tool_use 所在消息

代码：

```ts
if (
  message.type === 'user' &&
  'sourceToolAssistantUUID' in message &&
  message.sourceToolAssistantUUID
) {
  effectiveParentUuid = message.sourceToolAssistantUUID
}
```

#### 作用
这让 transcript 不是简单线性数组，而是**有向链 / 近似 DAG**。

尤其并发 tool use 时，这个结构非常重要。

---

## 10. compact boundary 的特殊处理

如果消息是 compact boundary：

```ts
parentUuid: isCompactBoundary ? null : effectiveParentUuid,
logicalParentUuid: isCompactBoundary ? parentUuid : undefined,
```

意思是：

- 物理链上断开，新的 transcript 从 compact boundary 重新起头
- 但保留 `logicalParentUuid` 说明它在逻辑上接在谁后面

这是 resume / compaction 能正常恢复的重要机制。

---

## 11. appendEntry 如何分流不同 Entry 类型

代码：`Project.appendEntry()`

这里会按 `entry.type` 分支：

- `summary` 直接写主 session 文件
- `custom-title` 直接写主 session 文件
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
- `content-replacement`
- `marble-origami-commit`
- `marble-origami-snapshot`
- 否则按 TranscriptMessage 处理

其中 `content-replacement` 有特殊路由：

```ts
const targetFile = entry.agentId
  ? getAgentTranscriptPath(entry.agentId)
  : sessionFile
```

也就是：

- 主线程 replacement 写主 JSONL
- 子代理 replacement 写子代理 JSONL

---

## 12. 最终如何 append 到文件

### 12.1 队列式批量写
`Project` 内部有 write queue，按文件路径分队列，定时 drain。

### 12.2 最底层写入
`appendToFile()` -> `fsAppendFile`

同步版本则是：

```ts
function appendEntryToFile(fullPath, entry) {
  const line = jsonStringify(entry) + '\n'
  fs.appendFileSync(fullPath, line, { mode: 0o600 })
}
```

所以 `.jsonl` 文件格式非常直接：

- 一行一个 `JSON.stringify(entry)`
- 换行分隔
- append-only

---

## 13. 会话刚开始时为什么不立刻建文件

代码：`materializeSessionFile()`

Claude Code 刻意避免创建“只有 metadata 没有真实对话”的 session 文件。

逻辑是：

- `sessionFile` 初始可能是 `null`
- metadata 先缓存到内存
- 直到出现第一条 `user` 或 `assistant` message，才真正 materialize session file
- 然后把 pending entries 补写进去

这样避免产生大量空会话/假会话文件。

---

## 14. 元数据是如何写入 JSONL 的

## 14.1 title/tag/agent-setting/mode/worktree/pr
这些不是都跟着 message 一起自动出现的。
有些是缓存后在特定时机补写。

关键函数：`reAppendSessionMetadata()`

它会向文件尾部重新追加：

- `last-prompt`
- `custom-title`
- `tag`
- `agent-name`
- `agent-color`
- `agent-setting`
- `mode`
- `worktree-state`
- `pr-link`

### 14.2 为什么要 re-append 到尾部
源码注释说得很清楚：
为了让 resume / lite metadata 读取时，在 tail window 中还能看到这些关键字段。

也就是说，**同一个 session 的 title/tag 等元数据，在 JSONL 里可能出现多次，读取时按 last-wins。**

这点非常关键。

---

## 15. `.jsonl` 里除了消息还会出现哪些 Entry

下面是按类型拆解。

### 15.1 `summary`

```ts
{ type: 'summary', leafUuid, summary }
```

用途：给某个叶子节点对应的会话链挂摘要。

### 15.2 `custom-title`

```ts
{ type: 'custom-title', sessionId, customTitle }
```

用户手动命名。

### 15.3 `ai-title`

```ts
{ type: 'ai-title', sessionId, aiTitle }
```

AI 自动生成标题。它与 custom-title 分开，是为了保证：

- 用户 title 优先
- resume 时不会把 AI title 又重刷成用户 title

### 15.4 `last-prompt`

```ts
{ type: 'last-prompt', sessionId, lastPrompt }
```

给 resume picker 看“最后在干什么”。

### 15.5 `task-summary`

```ts
{ type: 'task-summary', sessionId, summary, timestamp }
```

给 `claude ps` 之类查看当前做什么。

### 15.6 `tag`

```ts
{ type: 'tag', sessionId, tag }
```

### 15.7 `agent-name` / `agent-color` / `agent-setting`
用于 swarm / 子代理 / agent 配置恢复和展示。

### 15.8 `pr-link`

```ts
{ type: 'pr-link', sessionId, prNumber, prUrl, prRepository, timestamp }
```

把 session 关联到 GitHub PR。

### 15.9 `file-history-snapshot`

```ts
{ type: 'file-history-snapshot', messageId, snapshot, isSnapshotUpdate }
```

记录某个 message 对应的文件历史快照。

### 15.10 `attribution-snapshot`

记录 Claude 对各文件字符贡献度，供 attribution / commit attribution 用。

### 15.11 `content-replacement`

```ts
{ type: 'content-replacement', sessionId, agentId?, replacements }
```

表示上下文中某些大块内容被替换为更小 stub，resume 时要重建。

### 15.12 `mode`

```ts
{ type: 'mode', sessionId, mode: 'coordinator' | 'normal' }
```

### 15.13 `worktree-state`

记录当前是否在 worktree 里，以及 worktree 信息。

### 15.14 `marble-origami-commit`
context collapse 的 commit 事件。

### 15.15 `marble-origami-snapshot`
context collapse staged queue 的 last-wins 快照。

---

## 16. 一个 `.jsonl` 里 message 行本身又包含什么

虽然 `Message` 类型定义文件在这份源码镜像里没有直接找到单独 `types/message.ts`，但从 `createUserMessage` / `createAssistantMessage` / `createSystemMessage` 已可反推出持久化结构。

### 16.1 user message
由 `createUserMessage()` 构造，常见字段有：

- `type: 'user'`
- `message.role = 'user'`
- `message.content`，可为 string 或 content block 数组
- `uuid`
- `timestamp`
- `isMeta?`
- `isVisibleInTranscriptOnly?`
- `isVirtual?`
- `isCompactSummary?`
- `toolUseResult?`
- `mcpMeta?`
- `imagePasteIds?`
- `sourceToolAssistantUUID?`
- `permissionMode?`
- `origin?`

### 16.2 assistant message
由 `createAssistantMessage()` 构造，常见字段：

- `type: 'assistant'`
- `uuid`
- `timestamp`
- `message.id`
- `message.model`
- `message.role = 'assistant'`
- `message.stop_reason`
- `message.usage`
- `message.content`（text / thinking / tool_use 等 blocks）
- `requestId?`
- `apiError?`
- `error?`
- `errorDetails?`
- `isApiErrorMessage?`
- `isVirtual?`

### 16.3 system message
例如：

- `informational`
- `permission_retry`
- `bridge_status`
- `scheduled_task_fire`
- `stop_hook_summary`
- `turn_duration`
- `away_summary`

这些都可能作为 `type: 'system'` 的 transcript message 落盘。

### 16.4 attachment message
attachment 是否落盘取决于 `isLoggableMessage()` 和 userType。
external 用户大多数 attachment 默认不落盘。

---

## 17. message.content 里会有哪些 block

从 `messages.ts` 可看到 Claude API 相关 block 主要包括：

- `text`
- `thinking`
- `redacted_thinking`
- `tool_use`
- `tool_result`
- `image`
- `document`
- `tool_reference`
- 以及 server-side 特殊块如 `server_tool_use` / `*_tool_result`

所以一个 assistant/user message 不是纯文本，而可能是 block 数组。

这也是 transcript 很复杂的根源。

---

## 18. 哪些内容“只注入给 API，不会写进 transcript”

这是你问题里非常关键的一部分。

## 18.1 `normalizeMessagesForAPI()` 是 API 侧加工，不等于落盘
代码：`messages.ts`

这个函数会把内存中的 messages 转成发给模型 API 的格式，并做大量额外处理：

- attachment 上浮重排 `reorderAttachmentsForAPI`
- 去掉 virtual message
- 清理 tool_reference
- 处理过大的 document/image 错误
- 规范 tool_use input
- 合并 assistant 消息
- 做 tool_result pairing 修复
- 包装 system reminder

这些都是**API 发送前变换**，不是 transcript 原样落盘。

### 18.2 `wrapMessagesInSystemReminder()`
这个函数会把用户消息文本包进 system-reminder 标签：

```ts
content: wrapInSystemReminder(msg.message.content)
```

这类包装是 API-facing 注入，**不是 transcript 持久化的原始内容**。

### 18.3 tool reference boundary 注入
源码里还有这种逻辑：

- 在 API-prep 时给 tool_reference 附加 sibling text
- 避免模型错误停在 `<functions>` 一类 stop sequence

这也是 API 注入，不是 transcript 持久化本体。

### 18.4 normalizeToolInputForAPI
会对 tool_use input 做清洗和删字段，比如去掉 `caller`。
这同样是**发给 API 时**做，不等于 JSONL 里一定长那样。

### 18.5 unresolved pairing repair / synthetic tool_result
为了满足 API 结构要求，代码会在 API 前做 `ensureToolResultPairing` 一类修复，有时甚至插 synthetic tool_result placeholder。

这些修复是**为了 API 合法性**，并不意味着 transcript 原始写入一定就是这套形态。

---

## 19. resume 时如何从 JSONL 恢复

核心函数：`loadTranscriptFile(filePath)`

它返回：

- `messages: Map<UUID, TranscriptMessage>`
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

这已经说明：**恢复时不是只 parse 出一个 messages[]，而是把整个 JSONL 事件流拆成多个索引结构。**

---

## 20. loadTranscriptFile 的完整读取流程

### 20.1 先建各种 Map
按 entry type 分门别类。

### 20.2 大文件优化
如果 transcript 很大：

- 先做 boundary scan
- 跳过 attribution-snapshot 等大块
- 可跳过 compact boundary 前旧内容
- 必要时先扫描 pre-boundary metadata

这说明加载不是傻读全文件。

### 20.3 parseJSONL
底层由 `parseJSONL()` 解析：

- Bun.JSONL.parseChunk 优先
- 否则逐行 JSON.parse
- malformed line 会被跳过

### 20.4 legacy progress bridge
如果遇到老 transcript 中的 `progress` 行：

- 记录 progress_uuid -> parent_uuid bridge
- 后续真正 message 若 parent 指到 progress，则重写 parent 到 progress 的祖先

这是为兼容老版本 transcript。

### 20.5 分流每个 entry
对每行按 `entry.type` 分类塞入对应 map。

### 20.6 preserved segment / snip 修正
之后还会跑：

- `applyPreservedSegmentRelinks(messages)`
- `applySnipRemovals(messages)`

说明加载后还会做一次结构修复。

### 20.7 计算 leafUuids
通过 parentUuid 关系找 terminal messages，再回溯到 user/assistant 叶子。

---

## 21. 如何从所有 messages 中恢复出“当前对话链”

核心函数：`buildConversationChain(messages, leafMessage)`

算法：

1. 从 leafMessage 开始
2. 沿 `parentUuid` 一直往前找
3. 直到根节点或断链
4. reverse 成 root -> leaf 顺序
5. 再做 `recoverOrphanedParallelToolResults()` 修复并发工具调用丢枝

### 21.1 为什么还要 recover 并发 tool results
因为并发 tool_use 会把拓扑变成 DAG，不是简单链表。

源码明确解释了两种丢失模式：

1. sibling assistant orphaned
2. legacy progress fork

所以 buildConversationChain 之后还必须额外恢复 orphaned siblings 和 tool_results。

这也是 transcript 结构复杂的关键证据。

---

## 22. `.jsonl` 文件不是“最后状态”，而是“事件溯源”

这是另一个核心认识。

因为：

- title/tag 可重复出现，last-wins
- worktree-state 可多次出现，last-wins
- task-summary 是滚动快照
- content-replacement 是多次 append
- compact commit/snapshot 也是 append-only

所以读取时必须重放 entire event log 或至少重放相关片段。

换句话说：

**`.jsonl` 是 append-only event log + graph transcript，不是 normalized final state snapshot。**

---

## 23. sidecar `.json` 里记录什么

## 23.1 `agent-<agentId>.meta.json`
代码：`AgentMetadata`

```ts
{
  agentType: string,
  worktreePath?: string,
  description?: string
}
```

用途：

- 记录子代理类型
- 恢复 worktree path
- 恢复原始任务描述

### 23.2 `remote-agent-<taskId>.meta.json`
代码：`RemoteAgentMetadata`

包括：

- `taskId`
- `remoteTaskType`
- `sessionId`
- `title`
- `command`
- `spawnedAt`
- `toolUseId?`
- `isLongRunning?`
- `isUltraplan?`
- `isRemoteReview?`
- `remoteTaskMetadata?`

用途是 resume 时重新挂回远程 session/task。

---

## 24. 一个典型 `.jsonl` 的内容拆分示意

一个真实 session 文件大概会混合成这样：

```json
{"type":"custom-title","sessionId":"...","customTitle":"..."}
{"type":"tag","sessionId":"...","tag":"..."}
{"type":"mode","sessionId":"...","mode":"normal"}
{"type":"user", ... ,"uuid":"u1","parentUuid":null,"sessionId":"...","cwd":"..."}
{"type":"assistant", ... ,"uuid":"a1","parentUuid":"u1","sessionId":"..."}
{"type":"user", ... tool_result ...,"uuid":"u2","parentUuid":"a1","sessionId":"..."}
{"type":"assistant", ... ,"uuid":"a2","parentUuid":"u2","sessionId":"..."}
{"type":"file-history-snapshot","messageId":"a2", ...}
{"type":"attribution-snapshot","messageId":"a2", ...}
{"type":"last-prompt","sessionId":"...","lastPrompt":"fix test"}
{"type":"pr-link","sessionId":"...","prNumber":123,...}
{"type":"worktree-state","sessionId":"...","worktreeSession":{...}}
{"type":"marble-origami-commit", ...}
{"type":"system", "subtype":"turn_duration", ... ,"uuid":"s1","parentUuid":"a2"}
```

重点：

- 真正 transcript message 行，与 metadata 行交织出现
- 同一类 metadata 可能多次出现
- 不是所有 system 都是“只 UI 展示”，有些 system 会持久化

---

## 25. 哪些代码负责“注入哪些内容”总结表

## 25.1 写入 transcript message 外壳
负责代码：`Project.insertMessageChain()`

注入：

- `parentUuid`
- `logicalParentUuid`
- `isSidechain`
- `teamName`
- `agentName`
- `promptId`
- `agentId`
- `userType`
- `entrypoint`
- `cwd`
- `sessionId`
- `version`
- `gitBranch`
- `slug`

## 25.2 构造消息基础字段
负责代码：`createUserMessage` / `createAssistantMessage` / `createSystemMessage`

注入：

- `uuid`
- `timestamp`
- `message.role`
- `message.content`
- assistant 的 `message.id` / `usage` / `model` 等

## 25.3 元数据写入
负责代码：

- `saveCustomTitle`
- `saveAiGeneratedTitle`
- `saveTaskSummary`
- `saveTag`
- `saveAgentName`
- `saveAgentColor`
- `saveAgentSetting`
- `saveMode`
- `saveWorktreeState`
- `linkSessionToPR`
- `reAppendSessionMetadata`

## 25.4 文件快照与 attribution
负责代码：

- `recordFileHistorySnapshot`
- `recordAttributionSnapshot`
- `insertFileHistorySnapshot`
- `insertAttributionSnapshot`

## 25.5 大内容替换恢复信息
负责代码：

- `recordContentReplacement`
- `insertContentReplacement`

## 25.6 API 注入但不落盘
主要负责代码：`normalizeMessagesForAPI()` 与 `wrapMessagesInSystemReminder()`

注入/变换：

- system-reminder wrapper
- tool_reference boundary 文本
- tool_use input normalization
- attachment 重排
- synthetic pairing 修复
- virtual message 剔除

---

## 26. 读路径总结

从文件恢复会话时：

1. `loadTranscriptFile(filePath)` 读取并分类所有 JSONL 行
2. 建立 `messages Map<uuid, TranscriptMessage>`
3. 建立各种 metadata map
4. 计算 `leafUuids`
5. 通过 `buildConversationChain(messages, leaf)` 重建某条链
6. 用 `buildFileHistorySnapshotChain()` / `buildAttributionSnapshotChain()` 等恢复关联状态
7. 再拼成 `LogOption`

所以 resume 本质上是：

**JSONL 事件日志 → 分类索引 → parent graph 重建 → 当前链视图。**

---

## 27. 你真正应该记住的关键事实

### 27.1 `.jsonl` 不是聊天记录文本文件，而是事件流

### 27.2 每条 message 行都不是裸 message，而是加了一层 transcript envelope

### 27.3 transcript 的核心结构是 `uuid + parentUuid`，不是单纯时间顺序

### 27.4 同一个 session 的 title/tag/worktree 等元数据会重复出现，读取时 last-wins

### 27.5 UI 里看到的 message，不等于落盘后的 message
因为：

- progress 会被过滤
- attachment 常被过滤
- REPL 包装会被剥掉

### 27.6 发给 API 的 message，也不等于落盘 message
因为 API 前会再做 normalize / inject / repair

### 27.7 `.json` sidecar 用于保存不适合塞进 JSONL event stream 的 agent/remote metadata

---

## 28. 最后的“全流程”总图

```text
内存 messages[] 更新
  -> useLogMessages()
  -> recordTranscript()
  -> cleanMessagesForLogging()
       - 过滤 progress
       - 过滤部分 attachment
       - external transcript 去 REPL 包装
  -> getSessionMessages() 去重
  -> Project.insertMessageChain()
       - 计算 parentUuid
       - 注入 sessionId/cwd/version/gitBranch/promptId/... 
  -> appendEntry()
       - 按 Entry 类型分流
       - 主会话写主 .jsonl
       - 子代理写 agent-*.jsonl
  -> enqueueWrite()/appendToFile()
       - JSON.stringify(entry) + "\n"
       - append-only

恢复 / resume
  -> loadTranscriptFile()
       - parseJSONL
       - 分类 entry 到各种 map
       - 修复 legacy progress bridge
       - 处理 compact/snip
       - 计算 leafUuids
  -> buildConversationChain()
       - 沿 parentUuid 回溯
       - 恢复 orphaned parallel tool results
  -> build snapshots / metadata view
  -> LogOption / resume UI / API 继续会话

发给模型 API
  -> normalizeMessagesForAPI()
       - reorder attachments
       - strip virtual
       - inject system-reminder
       - normalize tool inputs
       - repair tool_result pairing
       - 这一步不等于 transcript 原文
```

---

## 29. 关键源码定位清单

如果你要继续自己深挖，最值得继续读的是这些位置：

- `src/utils/sessionStorage.ts`
  - `getTranscriptPath()`
  - `getAgentTranscriptPath()`
  - `recordTranscript()`
  - `insertMessageChain()`
  - `appendEntry()`
  - `reAppendSessionMetadata()`
  - `loadTranscriptFile()`
  - `buildConversationChain()`
  - `cleanMessagesForLogging()`
  - `isLoggableMessage()`

- `src/types/logs.ts`
  - `Entry`
  - `TranscriptMessage`
  - 各种 metadata entry type

- `src/utils/messages.ts`
  - `createUserMessage()`
  - `createAssistantMessage()`
  - `createSystemMessage()`
  - `normalizeMessagesForAPI()`
  - `wrapMessagesInSystemReminder()`

- `src/hooks/useLogMessages.ts`
  - message state 到 transcript 持久化的入口

- `src/utils/json.ts`
  - `parseJSONL()`
  - `readJSONLFile()`

---

如果你愿意，我下一步可以继续给你补一份：

1. **真实 `.jsonl` 样本字段级 annotated 示例**，我按源码推一个完整示例文件
2. **“主会话 / 子代理 / remote-agent / sidecar” 关系图**
3. **“哪些字段用于 UI，哪些用于 resume，哪些用于 API，哪些用于统计” 四分类表**

这三份会非常适合你后续彻底吃透。