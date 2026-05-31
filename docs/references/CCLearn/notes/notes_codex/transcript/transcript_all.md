# Claude Code 会话持久化 / transcript / jsonl / sidecar 综合整合稿

> 说明：
> - 本文将你提供的两篇 Claude Code 源码笔记整合为一份统一版本。
> - 我保留了两篇笔记的核心结论、细节拆解与流程图式理解，并对存在冲突或不确定之处做了**额外核验与显式标记**。
> - 为确保“不丢信息”，文末附上两篇原始笔记全文作为附录。

---

## 0. 先给最终统一结论

Claude Code 的会话持久化，本质上不是“聊天记录文本保存”，而是：

**`append-only JSONL 事件流 + parentUuid 消息图 + 少量 sidecar 元数据 + resume 时的恢复/修复流水线`**

也就是说：

1. **主会话**写入 `sessionId.jsonl`
2. **子代理**写入各自的 sidechain transcript（也是 `.jsonl`）
3. **少量不适合塞进 transcript 事件流的身份/启动信息**写入 `.meta.json`
4. resume 时不是“读回一个数组”，而是：
   - 解析 Entry
   - 恢复 metadata map
   - 重建 parentUuid 链
   - 修复 parallel tool results / legacy progress / compact / collapse / replacement
   - 再把运行时状态恢复回去

所以一个 Claude Code transcript 文件，本质上是**会话事件日志**，而不是简单聊天记录。

---

## 1. 关键源码文件总表

### 1.1 持久化主轴
- `src/utils/sessionStorage.ts`
- `src/types/logs.ts`

### 1.2 消息创建与结构
- `src/utils/messages.ts`
- `src/utils/messages/mappers.ts`

### 1.3 UI / 查询主循环触发写盘
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

### 1.7 路径清洗与轻量读取
- `src/utils/sessionStoragePortable.ts`

---

## 2. 文件布局：`.jsonl` 与 `.json` 各自放什么

## 2.1 主 transcript

主文件路径：

```text
~/.claude/projects/<sanitized-project-path>/<sessionId>.jsonl
```

其中 `<sanitized-project-path>` 由 `sanitizePath()` 生成，特点通常是：
- 非字母数字字符替换成 `-`
- 路径过长时截断并追加 hash

## 2.2 子代理 transcript

```text
~/.claude/projects/<project>/<sessionId>/subagents/agent-<agentId>.jsonl
```

如果 agent 设置了分组子目录，则为：

```text
~/.claude/projects/<project>/<sessionId>/subagents/<subdir>/agent-<agentId>.jsonl
```

## 2.3 子代理 sidecar 元数据

```text
agent-<agentId>.meta.json
```

用于保存：
- `agentType`
- `worktreePath?`
- `description?`

## 2.4 远程代理 sidecar 元数据

```text
~/.claude/projects/<project>/<sessionId>/remote-agents/remote-agent-<taskId>.meta.json
```

用于保存：
- `taskId`
- `remoteTaskType`
- `sessionId`
- `title`
- `command`
- `spawnedAt`
- 以及若干 remote task 标志位

---

## 3. `.jsonl` 每一行不是纯 message，而是 `Entry`

`src/types/logs.ts` 中，顶层联合类型 `Entry` 覆盖了整个 JSONL 每一行可能出现的对象类型。

核心理解：

- `.jsonl` **不是只有 user / assistant**
- 每一行可能是：
  - transcript message
  - title / tag / mode / pr-link 之类元数据
  - file-history / attribution 快照
  - queue-operation
  - speculation-accept
  - content-replacement
  - context collapse commit / snapshot
  - summary

这也是为什么不能把 Claude Code transcript 误解成“聊天文本导出”。

---

## 4. 真正的消息行：`TranscriptMessage`

统一结构可概括为：

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

而 `SerializedMessage` 又会统一盖这些字段：

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

所以一个真正写入 JSONL 的消息行，不是裸 `Message`，而是：

**原始消息本体 + transcript envelope（会话壳）**

---

## 5. 哪些消息会进 transcript，哪些不会

## 5.1 会进入 transcript 的 message type
`isTranscriptMessage()` 认可的类型是：
- `user`
- `assistant`
- `attachment`
- `system`

## 5.2 `progress` 不属于 transcript 主链
源码明确把 `progress` 排除在 transcript message 之外。

这意味着：
- UI 中可见的 progress 不一定会落盘
- progress 不应参与 `parentUuid` 主链
- 旧 transcript 若曾混入 progress，读路径会专门做 bridge 修复

## 5.3 `attachment` 也不是无条件写入
外部用户下，大量 attachment 会被过滤。
仅特定条件下（例如 hook additional context 且开关允许）才会被保留。

---

## 6. 磁盘 transcript 不等于内存 messages 原样

这点是整合两篇笔记后必须特别强调的：

### 6.1 写盘前会统一走清洗
`recordTranscript()` 会先调用：

```ts
cleanMessagesForLogging(messages, allMessages)
```

### 6.2 external transcript 会进一步“去壳”
`transformMessagesForExternalTranscript()` 会做两件重要的事：

1. **去掉 REPL 包装层**
   - assistant 中的特定 REPL `tool_use`
   - user 中对应 REPL `tool_result`

2. **把 virtual message 扁平化成可恢复 transcript**
   - 去掉 `isVirtual`
   - 让 resume 后看到的是更接近原生工具调用历史的结构

所以：
- **UI 看到的消息 ≠ 最终写盘消息**
- **发给 API 的消息 ≠ 最终写盘消息**

这两层必须分开理解。

---

## 7. 还有一层：发给 API 的 message 也不是落盘 message

另一篇笔记补充得非常关键，这部分必须并入最终稿。

`normalizeMessagesForAPI()` 在 API 发送前还会额外做加工，例如：

- attachment 重排
- tool reference 边界文本注入
- system reminder 包装
- tool_use input normalization
- unresolved pairing 修复
- synthetic tool_result 补齐
- virtual / 无效块清理

因此 Claude Code 至少有三套不同视角：

1. **运行时内存 messages**
2. **落盘 transcript messages**
3. **送给模型 API 的 normalized messages**

这三者不能混为一谈。

---

## 8. 主写盘流程：从 UI / Query loop 到磁盘

## 8.1 React hook 增量刷盘
`useLogMessages.ts` 会在 `messages` 变化时增量调用：

```ts
recordTranscript(slice, teamInfo, parentHint, messages)
```

它内部会维护：
- `lastRecordedLengthRef`
- `lastParentUuidRef`

用来保证增量写盘时 parent 链正确。

## 8.2 QueryEngine 会在真正请求模型前抢先落盘用户输入
这是一个很关键的 crash-safety 设计：

- 用户消息刚进入主循环
- 即使 API 还没返回，进程如果中途被杀
- transcript 里仍然已经有这轮 user message
- `/resume` 才不会完全找不到上下文

## 8.3 assistant / user / compact boundary 会持续增量落盘
查询流过程中只要出现可记录消息，就继续 `recordTranscript()`。

---

## 9. `recordTranscript()` 真正做了什么

可以概括为五步：

1. 过滤与清洗消息
2. 读取当前 session 已有 UUID 集合
3. dedup，只保留真正新增消息
4. 根据前缀已记录消息计算 `startingParentUuid`
5. 交给 `Project.insertMessageChain()` 真正落盘

这就是 Claude Code transcript **append-only + UUID 去重** 的核心。

---

## 10. `insertMessageChain()` 是最核心的写盘函数

它负责四件事：

### 10.1 决定是否 materialize 会话文件
Claude Code 不想为了“只有 metadata、还没有真正对话”的状态创建空 transcript。

所以通常：
- metadata 先缓存在内存
- 直到遇到第一条真正的 `user` / `assistant` 消息
- 才创建 session file 并 flush pending entries

### 10.2 计算 `parentUuid`
默认新消息挂在前一个 chain participant 后面。

但有两个关键特例：

#### A. compact boundary
- `parentUuid = null`
- `logicalParentUuid = 原父节点`

含义是：
- 物理链断开
- 逻辑关系保留

#### B. tool_result user message
如果 user message 带 `sourceToolAssistantUUID`：
- 它的父节点不一定是“上一条消息”
- 而是直接指向对应 tool_use assistant message

这解释了为什么 transcript 更接近 DAG，而不是单纯线性链表。

### 10.3 统一重新盖章会话字段
这一步很重要，尤其在 resume / fork 后避免旧 sessionId 污染新 transcript。

### 10.4 更新 `currentSessionLastPrompt`
供 `last-prompt` 尾部补写使用。

---

## 11. `appendEntry()`：Entry 级分流总闸门

`appendEntry()` 决定一条 entry 是：

- 写主 transcript
- 写 subagent transcript
- 走队列式 append
- 是否需要远端同步

### 11.1 transcript message 的规则
- 主链按 UUID 去重
- sidechain 允许继承上下文而出现重复 UUID
- 主链 transcript message 可继续同步到远端 ingress

### 11.2 metadata entry 的规则
典型 metadata 例如：
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
- `mode`
- `worktree-state`
- `summary`
- `speculation-accept`
- `marble-origami-*`

通常都可以直接 append。

### 11.3 `content-replacement` 的特殊路由
- 无 `agentId`：写主 transcript
- 有 `agentId`：写对应 subagent transcript

---

## 12. 最底层文件写法：不是全量重写，而是 append-only

队列 drain 后，底层基本等价于：

```ts
JSON.stringify(entry) + "\n"
```

然后 append 到文件。

权限通常是：
- 目录：`0700`
- 文件：`0600`

这保证了：
- 崩溃安全更好
- 日志型持久化更自然
- 最后不需要频繁整文件重写

---

## 13. metadata 为什么会反复被重挂到 EOF

这是两篇笔记都提到、且非常关键的实现理念。

Claude Code 有一个轻量读取模式，只读 transcript **头尾 64KB** 来快速展示 resume 列表。

这意味着：
- 如果 `custom-title` / `tag` / `mode` / `pr-link` 很早写进去
- 后续对话很长
- 它们就会被挤出 tail window

所以 `reAppendSessionMetadata()` 会把关键 metadata 再次写到文件尾部。

结论：
- 同一 session 的 metadata **可能重复出现多次**
- 读取时按 **last-wins** 理解

---

## 14. `summary`、compact summary 与 `task-summary` 不是一回事

这是整合后最容易混淆、也最需要校正的点之一。

### 14.1 `summary`
结构：

```ts
{ type: 'summary', leafUuid, summary }
```

它是**独立 Entry**，不是普通 message。

### 14.2 compact summary
compact 流程里还有一种“summary”，但它本质是：
- 一条普通 `user` message
- 只是附带 `isCompactSummary` / `summarizeMetadata`

所以它**不是**上面的 `SummaryMessage` entry。

### 14.3 `task-summary`
这是给 `claude ps` 等场景用的“当前任务摘要快照”，也是另一套东西。

---

## 15. 非 message entry 全表（统一整合版）

JSONL 中除了普通 transcript message 外，还可能出现：

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

其中：
- `queue-operation` 偏向内部命令队列日志
- `file-history-snapshot` / `attribution-snapshot` 偏向恢复辅助状态
- `content-replacement` 偏向恢复 prompt cache 稳定性
- `marble-origami-*` 偏向 context collapse 恢复

---

## 16. `speculation-accept` 的正确说法（冲突校正）

这是两篇笔记中最典型的“看似冲突、实则是两个层次”的点。

### 16.1 一篇笔记说
`speculation-accept` 当前热路径是在 `PromptSuggestion/speculation.ts` 里**直接 `appendFile()`** 到 transcript。

### 16.2 另一篇笔记说
`Project.appendEntry()` 的分流逻辑中也**支持** `speculation-accept` 这种 Entry。

### 16.3 校正后的正确表述
**两句话都不算完全错，但层级不同：**

- **热路径写入点**：当前可见源码中，`acceptSpeculation()` 的确直接 `appendFile(getTranscriptPath(), jsonStringify(entry)+'\n')`
- **通用 transcript plumbing**：`appendEntry()` 也确实把 `speculation-accept` 视为可直接 append 的 Entry 类型

所以最终应该写成：

> `speculation-accept` 在当前观察到的实际生产写入路径中，常由 `PromptSuggestion/speculation.ts` 直接 `appendFile()` 写入；与此同时，`sessionStorage.ts` 的 `appendEntry()` 通用分流层也支持该 Entry 类型。

---

## 17. `summary` 的正确说法（冲突校正）

这也是两篇笔记里最重要的冲突点。

### 17.1 一篇笔记的谨慎结论
“当前扫描里只确认了读支持，没有找到明确主动写入点。”

### 17.2 另一篇笔记的结论
“`appendEntry()` 明确把 `summary` 当作可直接写入主 session 文件的 Entry。”

### 17.3 补充核验后的最终表述
最稳妥的写法应该是：

1. `logs.ts` 中**确定存在** `SummaryMessage`
2. `loadTranscriptFile()` **确定会读取** `summary`
3. `appendEntry()` **确定支持** `summary` 作为可直接 append 的 Entry
4. 从公开可见的实际 Claude Code issue / 社区样本可观察到 `.jsonl` 文件中确实存在 `type: "summary"` 记录

因此，最终不能再写成“只支持读取、不确定是否会写”。更准确的说法是：

> `summary` 不是只读兼容残留；它在类型系统与 append 分流层中都被正式支持，而且真实会话文件中可以观察到 `summary` 行。  
> 但如果只看你本地那次扫描，**未直接定位到具体写入 caller** 这一点仍然可以保留为“调用点未完全穷尽”的诚实边界。

---

## 18. `QueueOperationMessage` 的正确说法（冲突校正）

这里不存在实质性逻辑冲突，但需要统一措辞：

- `queue-operation` 这个 Entry **确实存在**
- 写入对象结构可以从 `messageQueueManager.ts` 侧反推出
- `recordQueueOperation()` / `insertQueueOperation()` / `appendEntry()` 构成了写盘链路
- 但你本地扫描时，独立的 `messageQueueTypes` 类型文件没有在镜像里直接定位到

因此最终表述应为：

> `queue-operation` 的持久化链路是明确存在的；  
> 但本地镜像中独立类型定义文件未直接定位到，这一点应保留为“类型文件缺失/镜像不完整”的边界说明，而不是否定该 Entry 的存在。

---

## 19. sidecar `.json` 的职责边界

sidecar 不是主数据源，它只负责保存不适合塞进 JSONL 事件流的内容，例如：

### 19.1 子代理 sidecar
- `agentType`
- `worktreePath`
- `description`

### 19.2 远程代理 sidecar
- remote task 身份
- remote CCR session 连接信息
- task title / command / flags

所以 sidecar 更像：
- **恢复入口信息**
- **身份配置快照**

而不是完整事件流。

---

## 20. 远端持久化：本地 transcript 之外还有 ingress 追加链

Claude Code 的 transcript 不只是本地磁盘文件。

主 transcript message 还可能：
- 通过 Session Ingress 远端追加
- 使用 `Last-Uuid` 做乐观并发控制
- 遇到冲突重试并对齐 server head

这说明 Claude Code 的远端持久化模型，也仍然是 **append-only chain**，不是“整文件上传覆盖”。

---

## 21. 删除 / tombstone 不是主模式，而是补丁式修复通道

Claude Code 主模型是 append-only。

但确实存在一个“异常补救”路径：
- 删除孤儿消息
- 优先 tail 窗口内定位
- 不行再走慢路径整文件重写过滤

这更像：
- 对异常残留的修补
- 而不是日常会话写盘模式

---

## 22. 读取与 resume：不是读数组，而是重建图

resume 的核心并不是 `JSON.parse(lines)` 这么简单，而是：

1. 解析所有 Entry
2. 分类到不同 map
3. 构建 `messages: Map<uuid, TranscriptMessage>`
4. 建立 metadata / snapshots / replacements / collapse 结构
5. 计算 leaf
6. 沿 `parentUuid` 回溯出当前主链
7. 修复 orphaned parallel tool results
8. 再恢复 fileHistory / attribution / worktree / agent / remote task 等运行态

所以 resume 的本质是：

**JSONL 事件流 → 分类索引 → parent graph → 当前可继续会话视图**

---

## 23. `recoverOrphanedParallelToolResults()` 为什么存在

因为 Claude Code 的真实拓扑并不总是单链表。

一旦出现：
- 并发 tool_use
- sibling assistant block
- 分叉式 tool_result 归属

单纯 parent 回溯就会漏消息。

因此恢复阶段还需要额外补回：
- sibling assistant
- 对应 tool_result
- 由并行工具调用形成的 DAG 侧枝

这也是为什么 parentUuid 机制不能简单理解成“上一条消息指针”。

---

## 24. 一个典型 `.jsonl` 文件长什么样

真实 session 文件可能混合出现：

```json
{"type":"custom-title","sessionId":"...","customTitle":"..."}
{"type":"tag","sessionId":"...","tag":"..."}
{"type":"mode","sessionId":"...","mode":"normal"}
{"type":"user","uuid":"u1","parentUuid":null,"sessionId":"...","cwd":"..."}
{"type":"assistant","uuid":"a1","parentUuid":"u1","sessionId":"..."}
{"type":"user","uuid":"u2","parentUuid":"a1","sessionId":"..."}
{"type":"file-history-snapshot","messageId":"a1", "...":"..."}
{"type":"content-replacement","sessionId":"...","replacements":[...]}
{"type":"speculation-accept","timestamp":"...","timeSavedMs":1234}
{"type":"summary","leafUuid":"...","summary":"..."}
```

重点：
- 真正消息行与 metadata 行交织
- 同类 metadata 可能多次出现
- 最终读取时通常按 last-wins / replay-all / key-by-messageId 等不同规则解释

---

## 25. 哪些代码负责“注入哪些内容”——统一表述

### 25.1 构造基础消息
- `createUserMessage()`
- `createAssistantMessage()`
- `createSystemMessage()`

负责：
- `uuid`
- `timestamp`
- `message.role`
- `message.content`
- assistant 的 `message.id / usage / model` 等

### 25.2 写入 transcript envelope
- `Project.insertMessageChain()`

负责：
- `parentUuid`
- `logicalParentUuid`
- `isSidechain`
- `teamName`
- `agentName`
- `agentColor`
- `agentId`
- `promptId`
- `cwd`
- `userType`
- `entrypoint`
- `sessionId`
- `version`
- `gitBranch`
- `slug`

### 25.3 元数据写入
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

### 25.4 恢复辅助快照
- `recordFileHistorySnapshot`
- `recordAttributionSnapshot`
- `recordContentReplacement`
- `recordContextCollapseCommit`
- `recordContextCollapseSnapshot`

### 25.5 API 侧注入但不等于落盘
- `normalizeMessagesForAPI()`
- `wrapMessagesInSystemReminder()`
- tool reference boundary 注入
- pairing 修复与 synthetic tool_result 补齐

---

## 26. 最终理解框架（建议记住这一版）

如果只记一个模型，请记这个：

### 26.1 写入层
`recordTranscript()` / `insertMessageChain()` / `appendEntry()`

### 26.2 消息结构层
`Message` / `TranscriptMessage` / `parentUuid` / `logicalParentUuid` / compact summary / tool_result parent override

### 26.3 恢复层
`loadTranscriptFile()` / `buildConversationChain()` / `recoverOrphanedParallelToolResults()` / `sessionRestore.ts`

### 26.4 sidecar 层
`agent-*.meta.json` / `remote-agent-*.meta.json`

只有把这四层一起看，Claude Code 的 `.jsonl` / `.json` 会话机制才算真正看透。

---

## 27. 本次冲突点最终裁定（汇总版）

| 冲突点 | 最终裁定 |
|---|---|
| `summary` 是否只是“读兼容残留” | 不是。类型存在、读路径存在、`appendEntry()` 也支持，真实会话文件里也能观察到 `summary` 行；但你本地扫描未直接穷尽具体 caller，这个边界可保留。 |
| `speculation-accept` 到底走 `appendEntry()` 还是直接 `appendFile()` | 两者都成立，但层级不同：当前热路径是 `PromptSuggestion/speculation.ts` 直接 `appendFile()`；同时 `sessionStorage.ts` 的通用 `appendEntry()` 也支持这个 Entry 类型。 |
| `queue-operation` 是否真实存在 | 存在，且写盘链路明确；只是独立类型文件在你本地镜像/公开镜像中未直接完整定位到。 |
| `summary` 与 compact summary 是否同一回事 | 不是。`SummaryMessage` 是独立 Entry；compact summary 本质是普通 user message 的一种特殊形态。 |

---

## 28. 仍需保留的诚实边界

1. 你本地那次源码扫描并没有穷尽所有 caller，因此“未看到写入点”不等于“没有写入点”。
2. 某些镜像仓库是分析镜像，不一定 100% 完整保留原始项目的所有类型文件。
3. 因为 Claude Code 不同版本迭代很快，某些实现可能在版本间发生迁移；因此“类型支持”“通用 plumbing 支持”“当前生产热路径”这三个层面要分开写，不能混成一句。

---

## 29. 一句话最终总结

**Claude Code 的会话持久化，不是“保存聊天数组”，而是“把消息图、元数据、恢复快照与 sidecar 身份信息共同组成一套可 append、可恢复、可修复的 session 系统”。**

---

# 附录 A：原始笔记 1（完整保留）

```markdown
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

```

# 附录 B：原始笔记 2（完整保留）

```markdown
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
```
