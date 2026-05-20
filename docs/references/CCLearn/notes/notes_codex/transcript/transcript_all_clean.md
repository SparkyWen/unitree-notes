# Claude Code 会话持久化 / transcript / jsonl / sidecar 去重整合稿

## 0. 核心结论

Claude Code 的会话持久化，本质上不是“保存聊天记录文本”，而是：

**`append-only JSONL 事件流 + parentUuid 消息图 + sidecar 元数据 + resume 恢复流水线`**

换句话说：

1. **主会话**写入 `sessionId.jsonl`
2. **子代理**各自写入 sidechain transcript（也是 `.jsonl`）
3. **少量不适合塞进 transcript 事件流的身份/启动信息**写入 `.meta.json`
4. resume 时不是简单“读回消息数组”，而是：
   - 解析 JSONL Entry
   - 恢复 metadata / snapshots / replacements
   - 重建 parentUuid 链
   - 修复并行 tool results、legacy progress、compact / collapse 状态
   - 再把运行时状态恢复回去

所以，Claude Code 的 transcript 文件本质上是**会话事件日志**，不是纯聊天文本。

---

## 1. 关键源码文件

### 1.1 持久化主轴
- `src/utils/sessionStorage.ts`
- `src/types/logs.ts`

### 1.2 消息创建与结构
- `src/utils/messages.ts`
- `src/utils/messages/mappers.ts`

### 1.3 写盘触发层
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

### 1.6 远端同步
- `src/services/api/sessionIngress.ts`

### 1.7 路径清洗 / 轻量读取
- `src/utils/sessionStoragePortable.ts`

---

## 2. 文件布局：`.jsonl` 和 `.json` 各自负责什么

### 2.1 主会话 transcript

主文件路径：

```text
~/.claude/projects/<sanitized-project-path>/<sessionId>.jsonl
```

其中 `<sanitized-project-path>` 由 `sanitizePath()` 生成，主要规则是：

- 非字母数字字符替换成 `-`
- 路径过长时截断并追加 hash

### 2.2 子代理 transcript

```text
~/.claude/projects/<project>/<sessionId>/subagents/agent-<agentId>.jsonl
```

若 agent 配置了子目录，则可能是：

```text
~/.claude/projects/<project>/<sessionId>/subagents/<subdir>/agent-<agentId>.jsonl
```

### 2.3 子代理 sidecar

```text
agent-<agentId>.meta.json
```

主要保存：
- `agentType`
- `worktreePath?`
- `description?`

### 2.4 远程代理 sidecar

```text
~/.claude/projects/<project>/<sessionId>/remote-agents/remote-agent-<taskId>.meta.json
```

主要保存：
- `taskId`
- `remoteTaskType`
- `sessionId`
- `title`
- `command`
- `spawnedAt`
- 以及若干 remote task 标志位

---

## 3. 数据模型：`.jsonl` 每一行到底是什么

Claude Code 的 `.jsonl` 文件不是“只有 user / assistant 消息”的数组展开，而是**一行一个 `Entry` 对象**。

### 3.1 顶层 `Entry` 联合类型

`Entry` 覆盖的对象类型包括：

- `TranscriptMessage`
- `SummaryMessage`
- `CustomTitleMessage`
- `AiTitleMessage`
- `LastPromptMessage`
- `TaskSummaryMessage`
- `TagMessage`
- `AgentNameMessage`
- `AgentColorMessage`
- `AgentSettingMessage`
- `PRLinkMessage`
- `FileHistorySnapshotMessage`
- `AttributionSnapshotMessage`
- `QueueOperationMessage`
- `SpeculationAcceptMessage`
- `ModeEntry`
- `WorktreeStateEntry`
- `ContentReplacementEntry`
- `ContextCollapseCommitEntry`
- `ContextCollapseSnapshotEntry`

因此，一个 transcript 文件中会混合出现：

- 真正的会话消息
- 会话元数据
- 恢复辅助快照
- compaction / collapse / replacement 相关事件

### 3.2 真正的消息行：`TranscriptMessage`

`TranscriptMessage` 可以概括成：

```ts
TranscriptMessage = SerializedMessage & {
  parentUuid: UUID | null
  logicalParentUuid?: UUID | null
  isSidechain: boolean
  agentId?: string
  teamName?: string
  agentName?: string
  agentColor?: string
  promptId?: string
}
```

而 `SerializedMessage` 会统一带上：

```ts
cwd
userType
entrypoint?
sessionId
timestamp
version
gitBranch?
slug?
```

这意味着真正落盘的一条消息不是裸 `Message`，而是：

**消息本体 + transcript envelope（会话外壳）**

### 3.3 三套不同视角不能混淆

理解 Claude Code 时，至少要分清 3 套结构：

1. **运行时内存 messages**
2. **写入磁盘的 transcript messages**
3. **发给模型 API 的 normalized messages**

它们不是同一套东西。

---

## 4. 哪些内容会进入 transcript，哪些不会

### 4.1 会进入 transcript 的 message type

`isTranscriptMessage()` 认可的类型是：

- `user`
- `assistant`
- `attachment`
- `system`

### 4.2 `progress` 不属于 transcript 主链

源码明确把 `progress` 排除在 transcript message 之外，因此：

- UI 里能看到的 progress，通常不会直接落盘
- progress 不应推进 `parentUuid` 主链
- 老版本若有 progress 遗留，读路径会做 bridge 修复

### 4.3 `attachment` 不是无条件写入

对非 `ant` 用户，大量 attachment 会被过滤。只有特定条件下才会保留。

### 4.4 写盘前会统一清洗消息

`recordTranscript()` 会先走：

```ts
cleanMessagesForLogging(messages, allMessages)
```

其作用包括：
- 过滤不可记录消息
- 对 external transcript 做额外“去壳”

### 4.5 external transcript 会进一步变形

`transformMessagesForExternalTranscript()` 主要做两件事：

#### A. 去掉 REPL 包装层
- assistant 中特定 REPL `tool_use` 会被过滤
- user 中对应的 REPL `tool_result` 会被过滤

#### B. 将 virtual message 扁平化
- 去掉 `isVirtual`
- 让 resume 后看到的是更接近原生工具调用历史的结构

结论：

**磁盘 transcript ≠ 内存 messages 原样**

### 4.6 发给 API 的 messages 还会再次加工

`normalizeMessagesForAPI()` / `wrapMessagesInSystemReminder()` 等逻辑会在 API 发送前进一步处理，例如：

- attachment 重排
- tool reference 边界文本注入
- system reminder 包装
- tool_use input normalization
- unresolved pairing 修复
- synthetic tool_result 补齐
- virtual / 无效块清理

因此：

**API messages ≠ 落盘 transcript messages**

---

## 5. 主写盘链路：从消息变化到 JSONL

### 5.1 React hook 的增量刷盘入口

`useLogMessages.ts` 会在 `messages` 变化时调用：

```ts
recordTranscript(slice, teamInfo, parentHint, messages)
```

并维护：
- `lastRecordedLengthRef`
- `lastParentUuidRef`

目的是让增量写盘时 parent 链保持正确。

### 5.2 QueryEngine 会在真正请求模型前抢先落盘用户消息

这是一个关键的 crash-safety 设计：

- 用户输入刚进入 query loop，就先写进 transcript
- 即使 API 还没返回，进程中途被杀
- resume 仍能找到这轮会话的 user message

### 5.3 assistant / user / compact boundary 会持续增量落盘

查询流中出现可记录消息时，会继续触发 `recordTranscript()`。

---

## 6. `recordTranscript()` 真正做了什么

可以概括为 5 步：

1. **过滤与清洗消息**
2. **读取当前 session 已有 UUID 集合**
3. **做 dedup，只保留新增消息**
4. **根据前缀已记录消息计算 `startingParentUuid`**
5. **交给 `Project.insertMessageChain()` 真正落盘**

这就是 Claude Code transcript **append-only + UUID 去重** 的核心。

---

## 7. `insertMessageChain()`：最核心的写盘函数

### 7.1 会话文件不会一开始就创建

Claude Code 不想为了“只有 metadata、没有真正对话”的状态创建空 transcript。

典型逻辑是：

- metadata 先缓存在内存
- 直到出现第一条真正的 `user` / `assistant`
- 才 `materializeSessionFile()`
- 再把 pending entries 一次性 flush 到文件

### 7.2 `materializeSessionFile()` 做什么

主要做三件事：

1. 确定 transcript 路径
2. 先写缓存的 session metadata
3. 再 flush `pendingEntries`

### 7.3 `parentUuid` 的默认规则

默认情况下，新消息挂在前一个 chain participant 后面。

### 7.4 `parentUuid` 的两个关键特例

#### A. compact boundary
- `parentUuid = null`
- `logicalParentUuid = 原父节点`

含义：
- 物理链断开
- 逻辑关系保留

#### B. tool_result user message
若 user message 带 `sourceToolAssistantUUID`：

```ts
effectiveParentUuid = message.sourceToolAssistantUUID
```

这意味着 tool_result 必须挂到对应的 tool_use assistant message，而不是简单挂到“上一条消息”后面。

### 7.5 `chain participant` 的判定

只要 `m.type !== 'progress'`，通常都参与主链推进。

### 7.6 `insertMessageChain()` 统一重新盖章的字段

该函数会统一注入：

- `parentUuid`
- `logicalParentUuid`
- `isSidechain`
- `teamName`
- `agentName`
- `agentColor`
- `agentId`
- `promptId`
- `userType`
- `entrypoint`
- `cwd`
- `sessionId`
- `version`
- `gitBranch`
- `slug`

这一步对 resume / fork 场景非常重要，因为它能避免旧 sessionId 污染新 transcript。

### 7.7 `currentSessionLastPrompt`

主链写完后，会缓存“最后有意义的 prompt”，供后续 `last-prompt` entry 使用。

---

## 8. `appendEntry()`：Entry 级总分流

### 8.1 transcript message 的处理规则

对于 `user / assistant / attachment / system`：

- 主链通常按 UUID 去重
- sidechain 不能简单复用主链的 dedup 集，否则会误伤继承上下文
- 主链 transcript message 还可能继续走远端同步

### 8.2 metadata entry 的处理规则

可直接 append 的 entry 包括：

- `summary`
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
- `queue-operation`
- `speculation-accept`
- `mode`
- `worktree-state`
- `content-replacement`
- `marble-origami-commit`
- `marble-origami-snapshot`

### 8.3 `content-replacement` 的特殊路由

- 没有 `agentId`：写主 transcript
- 有 `agentId`：写对应 subagent transcript

---

## 9. 最底层文件写法：append-only，不是全量重写

底层基本等价于：

```ts
JSON.stringify(entry) + "\n"
```

然后 append 到文件。

常见权限策略：
- 目录：`0700`
- 文件：`0600`

### 9.1 写队列机制

`Project` 内部通常会维护按文件路径分组的 write queue，定时 drain。

### 9.2 也存在同步直写 helper

一些 metadata helper 会走同步 `appendFileSync` 风格的直接落盘逻辑。

所以源码里会同时看到：

1. **队列式异步 append**
2. **同步直写 append**

---

## 10. metadata 为什么会反复重挂到 EOF

Claude Code 有轻量 resume 列表读取模式，只读 transcript **头尾窗口** 来提取元数据。

如果某个 metadata 很早写进去、后面对话很长，它就可能被挤出 tail window。

因此 `reAppendSessionMetadata()` 会把关键 metadata 重写到文件尾部，例如：

- `last-prompt`
- `custom-title`
- `tag`
- `agent-name`
- `agent-color`
- `agent-setting`
- `mode`
- `worktree-state`
- `pr-link`

结论：

- 同一 session 的 metadata **可能重复出现多次**
- 读取时通常按 **last-wins** 理解

---

## 11. 非 message entry 全表

下表是去重后的统一整理版本：

| Entry 类型 | 作用 | 写入责任 / 链路 | 备注 |
|---|---|---|---|
| `summary` | 叶子链摘要 | 读路径与 `appendEntry()` 都支持 | 不是 compact summary |
| `custom-title` | 用户手动命名 session | `saveCustomTitle()`，并会被 `reAppendSessionMetadata()` 保活 | last-wins |
| `ai-title` | AI 自动标题 | `saveAiGeneratedTitle()` | 优先级低于 custom-title |
| `last-prompt` | resume 列表展示“最近在做什么” | `insertMessageChain()` 缓存，`reAppendSessionMetadata()` 写出 | tail-friendly |
| `task-summary` | `claude ps` / agent 当前任务摘要 | `saveTaskSummary()` | 滚动快照 |
| `tag` | 会话标签 | `saveTag()`，并会被 `reAppendSessionMetadata()` 重写 | last-wins |
| `agent-name` | agent 名称 | `saveAgentName()` | 可能重写到尾部 |
| `agent-color` | agent 颜色 | `saveAgentColor()` | 可能重写到尾部 |
| `agent-setting` | agent 配置 | `saveAgentSetting()` | 初期可能只缓存 |
| `pr-link` | 关联 PR 信息 | `linkSessionToPR()` | 常被重挂到尾部 |
| `mode` | `normal` / `coordinator` | `saveMode()` | metadata entry |
| `worktree-state` | worktree 状态 | `saveWorktreeState()` | metadata entry |
| `file-history-snapshot` | 文件历史快照恢复 | `recordFileHistorySnapshot()` | 以 `messageId` 为索引 |
| `attribution-snapshot` | attribution / commit attribution 恢复 | `recordAttributionSnapshot()` | 以 `messageId` 为索引 |
| `queue-operation` | 命令队列操作日志 | `messageQueueManager.logOperation()` → `recordQueueOperation()` | 类型文件定位不完整，但链路明确 |
| `speculation-accept` | speculation 命中统计 | 热路径在 `PromptSuggestion/speculation.ts` | 常见为直接 appendFile |
| `content-replacement` | tool result 等大内容替换记录 | `query.ts` → `recordContentReplacement()` | resume 时重建替换状态 |
| `marble-origami-commit` | context collapse commit 记录 | `recordContextCollapseCommit()` | collapse 恢复 |
| `marble-origami-snapshot` | context collapse snapshot | `recordContextCollapseSnapshot()` | last-wins 型快照 |

---

## 12. `summary`、compact summary、`task-summary` 不是一回事

### 12.1 `summary`

它是独立 Entry，形如：

```ts
{ type: 'summary', leafUuid, summary }
```

作用是给某条叶子链关联摘要。

### 12.2 compact summary

compact 流程里的 summary 本质上不是 `SummaryMessage`，而是：

- 一条普通 `user` message
- 只是附带 `isCompactSummary` / `summarizeMetadata`

所以：

**compact summary ≠ `summary` entry**

### 12.3 `task-summary`

这是给 agent / `claude ps` 场景使用的任务摘要快照，也不是上面两个概念。

---

## 13. 子代理与 sidecar 的职责边界

### 13.1 子代理 transcript

子代理通常通过：

- `runAgent.ts`
- `recordSidechainTranscript()`
- `insertMessageChain()`
- `appendEntry()`

形成自己的 sidechain transcript。

### 13.2 子代理 sidecar

`agent-<agentId>.meta.json` 主要保存：

- `agentType`
- `worktreePath`
- `description`

它更像“恢复入口信息”，而不是事件流本体。

### 13.3 子代理 resume

恢复子代理时，通常会：

1. 读 agent transcript
2. 读 sidecar metadata
3. 过滤无效 / 空白消息
4. 结合 replacement 记录恢复 tool result 状态
5. 恢复 cwd / worktree
6. 根据 `agentType` 重新选择 agent definition

### 13.4 远程代理 sidecar

`remote-agent-<taskId>.meta.json` 主要保存远端任务身份与连接信息。

本地 sidecar 只记录：
- task 身份
- 连接参数
- 恢复入口

**远端任务的实际状态以远端 session API 为准。**

---

## 14. 远端持久化：本地 transcript 之外还有 ingress 追加链

主 transcript message 除了落本地 JSONL，还可能：

- 通过 Session Ingress 远端追加
- 使用 `Last-Uuid` 做乐观并发控制
- 冲突时回退重试并对齐 server head

所以远端持久化模型仍然是：

**append-only chain**

而不是整文件上传覆盖。

---

## 15. 读取与 resume：不是读数组，而是重建图

### 15.1 `readLiteMetadata()`

轻量 resume 列表模式下，会只读 transcript 头尾窗口，抽取如下一类信息：

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

其中两个关键规则是：

- `last-prompt` 优先于最早的 user prompt
- `customTitle` 优先于 `aiTitle`

### 15.2 `loadTranscriptFile()`

完整解析时，通常会返回：

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

这已经说明：

**resume 不是只 parse 出一个 messages[]，而是把 JSONL 事件流拆成多个索引结构。**

### 15.3 大文件优化

在超大 transcript 场景下，读取路径还会做额外优化，例如：

- 跳过 compact boundary 之前的大块旧内容
- 先扫 pre-boundary metadata
- 按 parent 链提前裁掉 dead branches
- 对 attribution 等大 entry 做更谨慎处理

### 15.4 legacy progress bridge

旧 transcript 若混入 `progress`，会记录 progress 与其父节点关系，并把后续真正消息的 parent 重桥接回去，以兼容旧数据。

### 15.5 compact boundary 的读侧影响

读取时若遇到 compact boundary，通常会重新理解 collapse 相关状态，避免 boundary 前后的旧 collapse 信息污染当前链。

---

## 16. `buildConversationChain()` 与并行 tool result 修复

### 16.1 基础链路恢复

`buildConversationChain(messages, leafMessage)` 的核心思路是：

1. 从 leaf 开始
2. 沿 `parentUuid` 回溯到 root
3. reverse 成 root → leaf 顺序

### 16.2 为什么还要 `recoverOrphanedParallelToolResults()`

因为 Claude Code 的真实拓扑并不总是简单链表。

一旦出现：
- 并发 tool_use
- sibling assistant block
- 分叉式 tool_result 归属

磁盘结构就更接近 DAG，而不是单链。

因此恢复阶段还需要补回：

- sibling assistant
- 对应 tool_result
- 被并行工具调用“挂到侧枝”的消息

这正是为什么不能把 transcript 简单理解成“时间顺序聊天数组”。

---

## 17. `loadFullLog()`、`loadConversationForResume()`、`sessionRestore.ts`

### 17.1 `loadFullLog()`

它会把轻量 log 变成完整可 resume 的 log，过程通常包括：

- 调 `loadTranscriptFile()`
- 找最新 leaf
- 用 `buildConversationChain()` 重建主链
- 去掉 transcript-only 字段
- 再把 metadata / snapshots / replacements 等信息拼回完整 `LogOption`

### 17.2 `loadConversationForResume()`

这是恢复入口之一。其职责通常包括：

- 选择 log 来源
- 如有需要转成 full log
- 恢复 file history / plan / skill state / interrupt 状态
- 返回 resume 所需的完整运行时材料

### 17.3 `sessionRestore.ts`

负责把恢复结果重新灌回运行时状态，例如：

- file history
- attribution
- context collapse commit / snapshot
- TodoWrite 状态
- worktree
- mode / agent setting
- resumed session file 接管

---

## 18. compact / context collapse / replacement

### 18.1 compact boundary

compact boundary 写入后通常意味着：

- 物理链从这里断开
- 逻辑父关系通过 `logicalParentUuid` 保留

### 18.2 compact summary

compact summary 本质是普通 user message 的特殊形态，不是独立 `summary` entry。

### 18.3 `content-replacement`

当大 tool result 等内容被替换成 stub 时，会写 `content-replacement` 记录，resume 时再重建替换状态，以保证 prompt cache / context 控制逻辑可恢复。

### 18.4 `marble-origami-*`

它们用于 context collapse 的 commit / snapshot 恢复，不是普通聊天内容。

---

## 19. 删除 / tombstone：不是主模式，而是异常修补通道

Claude Code 的会话存储主模型是 append-only。

但确实存在一个异常修补入口，用来删除孤儿消息，常见策略是：

1. 优先只读 tail 窗口定位目标行
2. 命中则尝试截断 + 回写剩余尾部
3. 不行再走慢路径全文件重写过滤
4. 文件过大时直接放弃慢路径

因此：

**删除不是常规写盘模式，而是为异常残留准备的修补通道。**

---

## 20. 代码职责总表：哪部分内容由谁注入

| 内容 | 主要负责代码 | 说明 |
|---|---|---|
| `uuid` / `timestamp` / 基础 `message.role` / `message.content` | `createUserMessage()` / `createAssistantMessage()` / `createSystemMessage()` | 构造消息本体 |
| `parentUuid` / `logicalParentUuid` / `isSidechain` / `agentId` / `promptId` / `cwd` / `sessionId` / `version` / `gitBranch` / `slug` | `Project.insertMessageChain()` | 构造 transcript envelope |
| `teamName` / `agentName`（message 级） | `useLogMessages.ts` → `recordTranscript(teamInfo)` → `insertMessageChain()` | swarm / team 上下文注入 |
| `custom-title` | `saveCustomTitle()`，以及 `reAppendSessionMetadata()` | metadata entry |
| `ai-title` | `saveAiGeneratedTitle()` | metadata entry |
| `last-prompt` | `insertMessageChain()` 缓存，`reAppendSessionMetadata()` 写出 | metadata entry |
| `tag` | `saveTag()`，以及 `reAppendSessionMetadata()` | metadata entry |
| `agent-setting` | `saveAgentSetting()`，`materializeSessionFile()` / `reAppendSessionMetadata()` | metadata entry |
| `mode` | `saveMode()`，`materializeSessionFile()` / `reAppendSessionMetadata()` | metadata entry |
| `worktree-state` | `saveWorktreeState()` | metadata entry |
| `pr-link` | `linkSessionToPR()`，以及 `reAppendSessionMetadata()` | metadata entry |
| `file-history-snapshot` | `recordFileHistorySnapshot()` | 恢复辅助 entry |
| `attribution-snapshot` | `recordAttributionSnapshot()` | 恢复辅助 entry |
| `queue-operation` | `messageQueueManager.logOperation()` | 队列操作 entry |
| `speculation-accept` | `PromptSuggestion/speculation.ts` | 常见热路径为直接 appendFile |
| `content-replacement` | `query.ts` → `recordContentReplacement()` | 恢复替换状态 |
| `marble-origami-commit/snapshot` | `recordContextCollapseCommit/Snapshot()` | collapse 恢复 entry |
| 子代理 `agentType/worktreePath/description` | `writeAgentMetadata()` | sidecar `.meta.json` |
| 远程代理连接信息 | `writeRemoteAgentMetadata()` | sidecar `.meta.json` |

---

## 21. 冲突校正后的统一结论

### 21.1 `summary` 不是“只读兼容残留”

更准确的说法是：

1. `logs.ts` 中明确存在 `SummaryMessage`
2. `loadTranscriptFile()` 明确会读取 `summary`
3. `appendEntry()` 明确支持 `summary` 作为可直接 append 的 Entry
4. 因此不能再把它简单写成“当前只支持读取”

更稳妥的边界表述是：

> `summary` 在类型系统和 append 分流层里都被正式支持；  
> 若某次本地扫描没有直接看到具体 caller，应写成“调用点未完全穷尽”，而不是写成“没有写入”。

### 21.2 `speculation-accept` 的两种说法其实是不同层级

两句都成立，但层级不同：

- **热路径**：当前可见实现里，常由 `PromptSuggestion/speculation.ts` 直接 `appendFile()` 写入 transcript
- **通用分流层**：`appendEntry()` 也支持该 Entry 类型

所以最终应表述为：

> `speculation-accept` 的常见热路径是直接 appendFile；同时它在通用 transcript plumbing 中也被视为合法 Entry。

### 21.3 `queue-operation` 的边界说明

最终应表述为：

> `queue-operation` 的持久化链路是明确存在的；  
> 但独立类型定义文件在本地镜像中未直接完整定位到，因此应保留“类型文件缺失 / 镜像可能不完整”的边界说明。

### 21.4 `summary`、compact summary、`task-summary` 必须严格区分

它们分别是：

- **`summary`**：独立 Entry
- **compact summary**：普通 user message 的特殊形态
- **`task-summary`**：任务摘要快照

---

## 22. 仍需保留的诚实边界

1. 你本地那次源码扫描并没有穷尽所有 caller，因此“没看到写入点”不等于“没有写入点”。
2. 某些分析镜像仓库不一定完整保留原项目的全部类型文件。
3. Claude Code 版本迭代很快，必须区分：
   - **类型层支持**
   - **通用 plumbing 支持**
   - **当前热路径实际写法**

这三层不能混成一句。

---

## 23. 最终理解框架

如果只记一个模型，请记下面这 4 层：

### 23.1 写入层
`recordTranscript()` / `insertMessageChain()` / `appendEntry()`

### 23.2 消息结构层
`Message` / `TranscriptMessage` / `parentUuid` / `logicalParentUuid`

### 23.3 恢复层
`loadTranscriptFile()` / `buildConversationChain()` / `recoverOrphanedParallelToolResults()` / `sessionRestore.ts`

### 23.4 sidecar 层
`agent-*.meta.json` / `remote-agent-*.meta.json`

---

## 24. 一句话最终总结

**Claude Code 的会话持久化，不是“保存聊天数组”，而是“把消息图、元数据、恢复快照和 sidecar 身份信息共同组成一套可 append、可恢复、可修复的 session 系统”。**
