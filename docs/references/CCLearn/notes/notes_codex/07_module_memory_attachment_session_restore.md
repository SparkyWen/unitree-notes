# Claude Code 代码库学习地图 - 模块 6：Memory / Attachment / Session 恢复模块

- 模块名称：记忆、附件与会话恢复（SessionMemory / Attachments / Transcript Persistence / Resume / Auto-Memory Paths）
- 目标：还原 Claude Code 如何在长会话、多轮工具调用、压缩后恢复、`--resume` / `--continue` / sidechain / subagent 等场景中持久化并恢复状态

---

## 1. 功能概述

Claude Code 能像一个长期运行的 agent，而不是一次性聊天工具，靠的并不只是 `query.ts` 主循环。

更关键的是它有一整套“把运行中的上下文变成可恢复状态”的机制，包括：

- transcript JSONL 持久化
- sidechain / subagent transcript 分流
- compact boundary / snip / orphan branch 的恢复性加载
- file history / attribution / content replacement 恢复
- attachment message 注入
- session memory / relevant memory prefetch
- auto-memory 存储路径与作用域
- remote session / CCR hydration

这层可以理解成：

> **Agent Runtime 的持久化地基 + 恢复中间层。**

如果没有这一层，系统虽然能实时执行，但：
- 一旦重启就会严重失忆
- sidechain / agent fork / rewind / resume 会断链
- compact/snipping 之后的会话会恢复错误
- 记忆和附件无法稳定跨轮存在

---

## 2. 解决的问题

### 2.1 Transcript 不是简单 append log，而是要支持恢复链
会话里有：
- user / assistant / system / attachment
- progress（部分是 legacy）
- queue ops / snapshots / file history / content replacement
- compact boundary / snip / summary / metadata

恢复时要重新拼出“真实会话链”。

### 2.2 Resume 不是只读最后一条
要处理：
- parentUuid 链
- compact boundary 之前的 metadata
- preservedSegment relink
- snip removal relink
- parallel tool_use orphan repair
- legacy progress bridge

这已经是“恢复一个 append-only DAG”的问题，而不是简单 JSON 读写。

### 2.3 Attachments 是 query loop 的隐式上下文扩展层
它们承载：
- recently changed files
- plan file
- deferred tools delta
- agent listing delta
- hook additional context
- memory-related attachments

所以 attachment 并不是普通 UI 提示，而是模型下一轮上下文的关键来源之一。

### 2.4 Session memory 不能等于 transcript
session memory 的目标是：
- 对当前任务/会话的重要信息做额外结构化保存或提取
- 为 relevant memory prefetch / post-compact restore / background extraction 提供素材

### 2.5 同一 session 里还存在 subagent / remote agent / teammate transcript
它们不能直接混在主 transcript 里，否则 resume 与显示都会乱。

### 2.6 Auto-memory 的路径和作用域必须安全、稳定、可共享
特别是：
- worktrees 同仓共享内存目录
- project settings 不能随便把 memory 指到危险目录
- Cowork/remote 模式可能要重定向 memory path

---

## 3. 涉及文件（本轮深读）

1. `source/src/utils/attachments.ts`
2. `source/src/services/SessionMemory/sessionMemory.ts`
3. `source/src/services/SessionMemory/sessionMemoryUtils.ts`
4. `source/src/utils/messages.ts`
5. `source/src/utils/sessionStorage.ts`
6. `source/src/memdir/paths.ts`

---

## 4. 模块核心入口文件

### 核心入口文件
- `source/src/utils/sessionStorage.ts`
- `source/src/utils/attachments.ts`

### 最值得先读的 3~8 个文件
1. `source/src/utils/sessionStorage.ts`
2. `source/src/utils/attachments.ts`
3. `source/src/services/SessionMemory/sessionMemory.ts`
4. `source/src/services/SessionMemory/sessionMemoryUtils.ts`
5. `source/src/memdir/paths.ts`
6. `source/src/utils/messages.ts`

### 容易被忽视但关键的文件
- `source/src/utils/sessionStorage.ts`
- `source/src/memdir/paths.ts`
- `source/src/utils/messages.ts`

尤其 `sessionStorage.ts`，它虽然是 util，但实际上是整个 resume / transcript 持久化体系的核心基础设施之一。

---

## 5. 整体调用链 / 执行流程

### 5.1 运行中消息持久化链

```text
query/repl/tool execution
  -> recordTranscript(...) / recordSidechainTranscript(...)
  -> Project.insertMessageChain(...)
  -> appendEntry(...) / enqueueWrite(...)
  -> session JSONL / agent JSONL / remote ingress internal events
```

### 5.2 resume / continue 恢复链

```text
--resume / continue
  -> loadTranscriptFile(sessionFile)
      -> parse JSONL
      -> rebuild messages map / summaries / metadata maps
      -> applyPreservedSegmentRelinks()
      -> applySnipRemovals()
      -> compute leafUuids
  -> buildConversationChain(...)
      -> recoverOrphanedParallelToolResults(...)
  -> convertToLogOption(...) / restoreSessionMetadata(...)
```

### 5.3 auto-memory 路径解析链

```text
auto memory feature enabled?
  -> memdir/paths.ts
      -> env override / settings override / default projects/sanitized-git-root/memory/
  -> getAutoMemPath()
  -> getAutoMemEntrypoint() / getAutoMemDailyLogPath()
```

### 5.4 attachment 注入链

```text
query.ts tool loop end
  -> utils/attachments.ts::getAttachmentMessages(...)
      -> plan / file / memory / skill / delta attachments
  -> 作为下一轮 user/attachment messages 注入模型上下文
```

---

## 6. 核心文件详细讲解

---

## 6.1 `source/src/utils/sessionStorage.ts`

### 文件作用
这是整个项目里最重、最关键的持久化文件之一。

它负责：
- transcript JSONL 的写入
- 侧链/subagent transcript 的写入
- remote session hydration
- session metadata（title/tag/agent/mode/worktree/pr-link）缓存与重写
- compact / snip / preserved segment / fork branch 的恢复
- log listing / lite metadata enrichment / resume picker 数据源
- content replacement / file history / attribution snapshot 的持久化

一句话：

> **它是 Claude Code 的会话数据库实现。**

不是 SQL/SQLite，而是 append-only JSONL + 智能恢复算法。

---

### 设计总体特点

#### 1) append-only transcript
绝大多数条目都是 append，而不是原地编辑。

#### 2) 少量“重写”只用于 tombstone 或恢复性修正
例如：
- `removeMessageByUuid()` 处理 orphaned message tombstone

#### 3) metadata 用 re-append 策略保持在 tail window 中
因为很多 resume/light listing 只读尾部窗口。

#### 4) 读取时做大量“链修复”
说明作者接受 append-only 日志会包含旧形态/死分支/legacy progress，只要 load path 能修复即可。

---

### 关键结构：`Project` 类

#### 类职责
- 管理当前 session 的文件路径与缓存
- 维护 write queue / flush / cleanup
- 处理 current session 与其他 session 的 transcript 写入
- 负责 remote ingress / CCR v2 internal event 持久化

#### 关键成员变量
- `currentSessionTag/currentSessionTitle/...`：当前会话 metadata cache
- `sessionFile`：当前会话 JSONL 文件路径
- `pendingEntries`：sessionFile 未 materialize 前的缓冲 entry
- `remoteIngressUrl` / `internalEventWriter` / `internalEventReader`
- `writeQueues`：每文件独立写队列
- `flushTimer` / `activeDrain`

#### 为什么类化而不是一堆函数
因为它有大量跨调用状态：
- 当前会话 metadata cache
- queue state
- flush lifecycle
- remote writer/reader handle

这更像一个 session persistence runtime 对象。

---

### 关键方法 1：`materializeSessionFile()`

#### 作用
在“第一次 user/assistant message 出现时”才真正创建 session 文件。

#### 为什么重要
这样可以避免：
- 启动时只是缓存 metadata（如 `--name`）
- 但还没有真实对话
- 就创建出 metadata-only session orphan 文件

#### 流程
```ts
1. shouldSkipPersistence() -> return
2. ensureCurrentSessionFile()
3. reAppendSessionMetadata()
4. flush pendingEntries
```

### 设计意图
这是一种非常讲究的“延迟物化 transcript file”策略。

---

### 关键方法 2：`insertMessageChain(...)`

#### 作用
把一串 Message 变成带 parentUuid/session stamp 的 transcript entries。

#### 输入
- `messages`
- `isSidechain`
- `agentId?`
- `startingParentUuid?`
- `teamInfo?`

#### 执行步骤
```ts
1. 若 sessionFile 还没 materialize 且这一批有 user/assistant -> materialize
2. 取当前 git branch / plan slug / sessionId
3. 遍历 messages
   - 生成 transcriptMessage
   - 对 tool_result 消息可使用 sourceToolAssistantUUID 覆盖 parentUuid
   - compact boundary parentUuid=null, logicalParentUuid=previousParent
   - 附加 cwd/sessionId/version/gitBranch/userType 等 stamp 字段
4. appendEntry(transcriptMessage)
5. 更新 parentUuid cursor
6. 记录 currentSessionLastPrompt
```

### 为什么关键
它不仅做 append，还定义了 transcript 的拓扑结构。

尤其这个细节：
- tool_result 的 parent 可覆盖到 source assistant uuid

这是后面 `recoverOrphanedParallelToolResults()` 必须存在的根源之一，因为 parallel tool topology 已经不再是单链。

---

### 关键方法 3：`appendEntry(...)`

这是所有 entry 写入的总入口。

#### 它处理很多特殊 entry 类型：
- summary
- custom-title
- ai-title
- task-summary
- tag
- agent-name/color/setting
- mode
- worktree-state
- pr-link
- file-history-snapshot
- attribution-snapshot
- content-replacement
- marble-origami commit/snapshot
- queue-operation
- transcript messages

#### 对 transcript message 的关键逻辑
- 当前 session 与其他 session 区分
- agent sidechain 与 main session file 区分
- dedup by UUID
- remote persistence 仅 main-file-authoritative UUID 才会同步

### 很关键的注释含义
sidechain local transcript 和 remote persistence 的 dedup 语义不一样：
- sidechain 本地文件允许共享 UUID（继承父链）
- 但 remote ingress 是按同一 sessionId 的 last-uuid chain，重复 UUID 会 409

这类细节说明作者已经处理过很多 fork/resume 边界 bug。

---

### 关键方法 4：`reAppendSessionMetadata()`

#### 作用
把 title/tag/agent/mode/worktree/pr-link 等 metadata 再次写到 transcript 尾部。

#### 为什么必须这样做
因为 lite resume 只读取 transcript 尾部窗口。
如果自定义标题被后续大量消息挤出 tail：
- `--resume` 就会退回显示 firstPrompt

#### 关键设计
它会先 tail-read：
- 吸收外部 SDK/rename/tag 写入的新值
- 避免用 CLI 进程里的 stale cache 覆盖新 metadata

##### 这非常高级
说明它考虑了：
- 同一 transcript 可能被多个 writer 改
- 但仍然试图通过 tail scan + reappend 保持最终一致

---

### 关键函数 5：`loadTranscriptFile(...)`

这是 resume 读取链里最重要的函数。

#### 输出
```ts
{
  messages,
  summaries,
  customTitles,
  tags,
  agentNames,
  agentColors,
  agentSettings,
  prNumbers/prUrls/prRepositories,
  modes,
  worktreeStates,
  fileHistorySnapshots,
  attributionSnapshots,
  contentReplacements,
  agentContentReplacements,
  contextCollapseCommits,
  contextCollapseSnapshot,
  leafUuids,
}
```

#### 核心步骤
```ts
1. 对大 transcript 先做 precompact skip / readTranscriptForLoad
2. 若 boundaryStartOffset>0，scanPreBoundaryMetadata 恢复 pre-boundary metadata
3. parseJSONL(buf)
4. legacy progress bridge: progress_uuid -> nearest non-progress parent
5. 分类装入 messages / summaries / metadata maps / snapshots / content replacements
6. compact boundary 触发清空旧 contextCollapse commit snapshot
7. applyPreservedSegmentRelinks(messages)
8. applySnipRemovals(messages)
9. 计算 leafUuids
```

这已经不是“读 JSONL”，而是“恢复 transcript graph”。

---

### 三个极其关键的恢复算法

#### 1) `applyPreservedSegmentRelinks(messages)`

##### 解决的问题
compact 后 preserved segment 的消息在物理文件上仍保留原 parentUuid，
但逻辑上需要接到 compact summary/boundary 后。

##### 做法
- 找到 absolute-last boundary 和 last seg-boundary
- 从 tailUuid 向前 walk 到 headUuid，确认 preserved chain 存在
- 把 head.parentUuid 改为 anchorUuid
- 把 anchor 其他孩子改挂到 tailUuid
- 对 preserved assistant usage 清零，防止 resume 后 stale usage 导致 autocompact spiral
- 删掉 absolute-last boundary 之前、又不在 preservedUuids 里的消息

##### 为什么重要
没有这个，resume 后会：
- 丢 preserved segment
- 或重复加载 pre-compact history
- 或 usage 过大导致马上 autocompact 死循环

这是非常难实现但很核心的恢复逻辑。

---

#### 2) `applySnipRemovals(messages)`

##### 解决的问题
Snip 是“删中间一段”，不是 compact 那样砍前缀。
append-only 文件里，被删掉的消息仍在磁盘上。

##### 做法
- 读取 boundary 里的 `removedUuids`
- 从 map 中删除它们
- 对 parentUuid 落进 deleted region 的 survivor，沿着 deletedParent 向后走，重连到最近 non-deleted ancestor

##### 为什么重要
如果只删不 relink：
- chain 会在 gap 处断掉
- resume 只恢复到一半

这也是非常实战的恢复算法。

---

#### 3) `recoverOrphanedParallelToolResults(...)`

##### 解决的问题
并行 tool_use 会生成多个 assistant block，形成 DAG，而非单链。
单纯 `buildConversationChain()` 沿 parentUuid 走只会保留一条分支。

##### 做法
- 按 `assistant.message.id` 找 sibling assistant group
- 找出 off-chain siblings
- 再找每个 sibling 对应的 tool_result
- 按 timestamp 排序后插回 anchor assistant 后面

##### 为什么重要
否则 parallel tool execution resume 后会丢掉部分 tool_result / assistant block。

这是 Claude Code transcript 恢复里最高级的设计之一。

---

### 其他关键能力

#### `walkChainBeforeParse(buf)`
- 对大 transcript 做 byte-level 预过滤
- 只保留活跃 parent chain + metadata
- 大幅降低 parseJSONL 成本

#### `getSessionFilesLite()` + `readLiteMetadata()`
- resume picker 的轻量索引读取
- 只读 head/tail ~64KB，不全量 parse 文件

#### `hydrateRemoteSession()` / `hydrateFromCCRv2InternalEvents()`
- 从 remote ingress / CCR v2 internal events 把远程 session 重新 hydrate 到本地 transcript

#### `loadAllSubagentTranscriptsFromDisk()`
- 直接从磁盘扫描 subagent transcript，适合 task eviction 后恢复

---

## 6.2 `source/src/utils/attachments.ts`

### 文件作用
这是**attachment message 组装中心**。

在 query loop 中，每轮工具执行后，它会把各种运行副作用变成 attachment messages，供下一轮模型看到。

### 为什么关键
Claude Code 不是只靠 `messages + tool_results` 继续。
很多关键状态都靠 attachment message 再次注入，例如：
- 文件变更摘要
- 计划文件更新
- memory 提取结果
- deferred tool delta
- agent/team 状态变化
- hook additional context

### 设计价值
attachment 是一种：

> **不污染普通 user/assistant 对话结构，但能稳定注入额外上下文的机制。**

### 它在系统中的位置
- 上游：tool execution / plan / file history / memory / agent/task systems
- 下游：query.ts 在下一轮前会把 attachments 与普通消息一起送进模型

### 重点关注点
后续还需继续深挖 attachment 子函数，但从当前主链已可确认：
- 它是 post-tool / post-compact / post-memory 恢复的关键承接层
- 是“运行时隐式状态显式化”的主要工具

---

## 6.3 `source/src/services/SessionMemory/sessionMemory.ts`

### 文件作用
这是**会话记忆服务层**。

它不是长期自动内存（memdir）本身，而更偏：
- 当前 session 相关记忆的提取、存取与结构化管理
- 和 query/compact/post-turn/background extraction 连接

### 当前已识别的职责边界
从 query/autoCompact/stopHooks 的调用关系能确认它用于：
- relevant memory prefetch
- session memory compaction 尝试
- extract memories / auto memory flow 的中间状态承接

### 设计定位
它处在：
- transcript persistence
- auto-memory durable storage
- query-time memory injection

三者之间的中间层。

也就是说：
- transcript 是原始事件流
- memdir 是 durable memory store
- sessionMemory 则是让“当前会话需要哪些 memory 参与下一轮”这件事可管理

---

## 6.4 `source/src/services/SessionMemory/sessionMemoryUtils.ts`

### 文件作用
这是 SessionMemory 的辅助策略与工具函数层。

### 从路径与调用关系可确认的意义
它通常承担：
- memory 相关路径/格式/筛选逻辑
- relevant memory 提取与轻量预处理
- post-compact / background extraction 共用工具函数

### 为什么它值得关注
Claude Code 的 memory 不是“一个文件 + 一个 prompt 片段”那么简单。
需要：
- 和 readFileState、attachments、stop hooks、extract memories 形成配合
- 尽量避免重复注入
- 控制 token 成本

utility 层通常就在这里做裁剪与规范化。

---

## 6.5 `source/src/memdir/paths.ts`

### 文件作用
这是**auto-memory 目录解析与安全边界文件**。

这个文件非常关键，因为它定义了：
- memory 功能是否启用
- memory 存哪里
- worktrees 是否共享 memory 目录
- 设置/环境变量是否允许重定向 memory
- 哪些路径是危险的、必须拒绝的

---

### 关键函数 1：`isAutoMemoryEnabled()`

#### 逻辑优先级
1. `CLAUDE_CODE_DISABLE_AUTO_MEMORY`
2. `CLAUDE_CODE_SIMPLE`（bare）
3. remote 但没有 `CLAUDE_CODE_REMOTE_MEMORY_DIR`
4. settings `autoMemoryEnabled`
5. 默认 true

### 设计意图
memory 是增强能力，不应该：
- 在 bare 模式里偷偷运行
- 在 remote 无持久存储时假装可用

---

### 关键函数 2：`isExtractModeActive()`

#### 作用
判断 extract-memories 背景 agent 是否应工作。

#### 关键逻辑
- 受 feature gate `tengu_passport_quail` 控制
- 非交互会话默认关闭，除非另一个 gate 开启

### 含义
memory 提取不是全时全量开启，而是灰度受控的后台能力。

---

### 关键函数 3：`validateMemoryPath(raw, expandTilde)`

这是本文件最重要的安全函数之一。

#### 它拒绝的路径
- relative path
- root / near-root
- Windows drive root
- UNC path
- null byte
- `~/`, `~/.`, `~/..` 这类会退化到 home 或 parent 的路径

#### 返回值
- 规范化后、带唯一 trailing sep 的安全目录路径
- 或 `undefined`

### 为什么重要
源码注释明确说：
这是为了防止 auto-memory 目录被设置到危险位置，然后被文件系统写 carve-out 当成可信目录。

也就是说这不是普通路径规范化，而是一个明确的**安全边界守门函数**。

---

### 关键函数 4：`getAutoMemPathSetting()`

#### 设计亮点
只允许 trusted setting sources：
- `policySettings`
- `flagSettings`
- `localSettings`
- `userSettings`

**明确排除 `projectSettings`**。

### 为什么极其关键
因为 projectSettings 来自仓库内 `.claude/settings.json`。
如果允许 repo 控制 autoMemoryDirectory：
- 恶意 repo 可以把 memory 指向 `~/.ssh` 等敏感路径
- 再通过 write carve-out 获取危险写能力

这是非常成熟的 supply-chain / repo-trust 安全设计。

---

### 关键函数 5：`getAutoMemPath()`

#### 解析顺序
1. `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`
2. trusted settings `autoMemoryDirectory`
3. 默认：`<memoryBase>/projects/<sanitized-git-root>/memory/`

#### 为什么用 canonical git root
源码注释明确：
- 所有 worktrees of the same repo 共享一个 auto-memory dir

这非常重要。
否则：
- 同一仓库不同 worktree 会产生碎片化 memory
- long-term context 很难累积

---

### 关键函数 6：`isAutoMemPath(absolutePath)`

#### 作用
判断某绝对路径是否在 auto-memory 目录下。

#### 关键点
- 会 normalize，防止 `..` path traversal 绕过
- 但“override path true”不等于自动有写权限；文件系统 carve-out 仍额外检查 `!hasAutoMemPathOverride()`

### 设计含义
这再次说明：
- path matching
- write permission carve-out

是两个概念，不被混为一谈。

---

## 6.6 `source/src/utils/messages.ts`

### 文件作用
这是**消息操作与分类的基础工具文件**。

在当前模块视角下，它的重要性在于：
- compact boundary 识别
- transcript message 分类
- tag extraction
- message transformation/recovery 相关基础操作

### 为什么重要
`sessionStorage.ts`、`query.ts`、tool execution、compact 等模块都在依赖 message helpers。

在 Claude Code 里，“消息”不是一个松散结构，而是：
- transcript persistence 基础单位
- API normalization 基础单位
- tool_result pairing 与 compact recovery 的基础单位

所以 `messages.ts` 是消息领域模型的基础设施层。

---

## 7. 数据流 / 状态流

### 7.1 transcript 持久化状态流

```text
runtime messages
  -> cleanMessagesForLogging()
  -> recordTranscript()
  -> Project.insertMessageChain()
  -> appendEntry()/enqueueWrite()
  -> JSONL file / sidechain file / remote ingress
```

### 7.2 resume 恢复状态流

```text
sessionFile
  -> loadTranscriptFile()
  -> reconstruct maps + metadata
  -> applyPreservedSegmentRelinks()
  -> applySnipRemovals()
  -> buildConversationChain()
  -> recoverOrphanedParallelToolResults()
  -> LogOption / restored session state
```

### 7.3 attachment 注入流

```text
post-tool / post-compact / post-memory side effects
  -> getAttachmentMessages()
  -> attachment messages
  -> next query turn input
```

### 7.4 auto-memory 路径状态流

```text
env + trusted settings + project root/git root
  -> validateMemoryPath()
  -> getAutoMemPath()
  -> MEMORY.md / daily logs / memory dir containment checks
```

---

## 8. 配置项 / 环境变量 / 依赖注入方式

### 8.1 会话持久化相关

| 项目 | 来源 | 影响 |
|---|---|---|
| `ENABLE_SESSION_PERSISTENCE` | env | 启用 remote ingress persistence |
| `CLAUDE_CODE_SKIP_PROMPT_HISTORY` | env | 全局跳过 transcript persistence |
| `cleanupPeriodDays=0` | settings | 禁用会话持久化 |
| `TEST_ENABLE_SESSION_PERSISTENCE` | env | test 环境覆盖 |
| `CLAUDE_CODE_ENTRYPOINT` | env | 写入 transcript metadata |

### 8.2 auto-memory 相关

| 项目 | 来源 | 影响 |
|---|---|---|
| `CLAUDE_CODE_DISABLE_AUTO_MEMORY` | env | 关闭 auto-memory |
| `CLAUDE_CODE_SIMPLE` | env/mode | bare 模式禁 memory |
| `CLAUDE_CODE_REMOTE` | env | remote 模式语义分支 |
| `CLAUDE_CODE_REMOTE_MEMORY_DIR` | env | remote memory base dir |
| `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` | env | full-path override |
| `autoMemoryEnabled` | settings | 是否启用 auto-memory |
| `autoMemoryDirectory` | settings(trusted only) | memory dir override |

### 8.3 依赖注入方式

#### 方式 1：global bootstrap state
- `getSessionId()`
- `getSessionProjectDir()`
- `getOriginalCwd()`
- `switchSession()`

#### 方式 2：message graph fields
- `uuid`
- `parentUuid`
- `logicalParentUuid`
- `sourceToolAssistantUUID`
- `isSidechain`
- `agentId`

#### 方式 3：remote persistence adapters
- internal event writer/reader
- session ingress

#### 方式 4：trusted settings + env override
- auto-memory path / session persistence gates

---

## 9. 错误处理 / 边界条件

### sessionStorage.ts
- session file 不存在：大量路径 fail-soft
- tombstone 重写超过 50MB：放弃，避免 OOM
- malformed JSONL line：尽量保留
- remote hydrate 失败：记录并返回 false
- CCR epoch mismatch：直接上抛给上层处理
- progress legacy 通过 bridge 修链
- cycle in parentUuid chain：记录 telemetry，返回 partial transcript

### memdir/paths.ts
- root/near-root/UNC/null byte/relative 路径拒绝
- projectSettings 明确不能设置 autoMemoryDirectory
- override path 不自动等于 write carve-out

### attachments.ts / sessionMemory.ts
- 作为 query 附件与 memory 注入层，通常应 fail-soft，避免影响主 query
- 后续继续深挖具体子函数时还要补更多边界案例

---

## 10. 安全性 / 性能 / 扩展性分析

### 10.1 安全性

#### 做得好的地方
1. **projectSettings 被明确禁止控制 autoMemoryDirectory**
2. **memory path 有严格 validateMemoryPath 守卫**
3. **transcript persistence 与 remote persistence 分开处理 sidechain dedup 语义**
4. **resume 时有链修复，不轻信 append-only 原始拓扑就一定正确**

#### 风险点
- `sessionStorage.ts` 极其复杂，任何新增 entry type 都需要非常小心地接入 write-path 和 load-path
- append-only transcript 一旦出现新的拓扑形态，resume 逻辑可能还需继续打补丁

### 10.2 性能

#### 优化手段
1. `materializeSessionFile()` 延迟建文件
2. per-file write queue + chunk append
3. `readLiteMetadata()` 只读 head/tail 小窗口
4. `walkChainBeforeParse()` 对大 transcript 做 byte-level prefilter
5. metadata pre-scan `scanPreBoundaryMetadata()` 避免全量 parse
6. `getSessionMessages` memoize

#### 成本点
- `loadTranscriptFile()` 的恢复逻辑很重
- fork/compact/snip/parallel tool 拓扑越复杂，resume path 越重

### 10.3 扩展性
这层总体可扩展，但代价是接入规范必须非常严格。

新增持久化能力时通常要同时改：
1. 写路径：`appendEntry` / `record*`
2. 读路径：`loadTranscriptFile`
3. lite path（若需要在 resume picker 可见）
4. compact/snip 恢复兼容
5. remote hydrate 兼容

这就是“事件日志型系统”的典型维护成本。

---

## 11. 与其他模块的关系

### 上游
- `query.ts`
- tool execution
- compact system
- stop hooks / memory extraction / teammates / agents

### 下游
- resume picker
- `--resume` / `--continue`
- attachment reinjection
- post-compact restoration
- auto-memory durable store

### 关键耦合点
- `bootstrap/state.ts`
- `query.ts`
- `compact.ts`
- `messages.ts`
- memdir + SessionMemory services

---

## 12. 学习这个模块时建议的阅读顺序

### 推荐顺序
1. `source/src/utils/sessionStorage.ts`
2. `source/src/memdir/paths.ts`
3. `source/src/utils/attachments.ts`
4. `source/src/services/SessionMemory/sessionMemory.ts`
5. `source/src/services/SessionMemory/sessionMemoryUtils.ts`
6. `source/src/utils/messages.ts`

### 为什么这样排
- 先理解 transcript 持久化与恢复
- 再理解 memory path 与安全边界
- 再回到 query 周期中 attachment/memory 如何注入

---

## 13. 容易忽略但关键的隐藏细节

### 细节 1：session transcript 是 append-only，但恢复时会做复杂的图修复
包括：
- preserved segment relink
- snip removal relink
- orphaned parallel tool results recovery
- legacy progress bridge

### 细节 2：resume picker 大量依赖 head/tail lite metadata，而不是全量 parse
所以 metadata re-append 是 load-bearing 设计，不是锦上添花。

### 细节 3：worktrees 会共享 auto-memory 目录，因为 key 用的是 canonical git root
这对“同仓多工作树共享长期记忆”非常关键。

### 细节 4：project settings 明确不能控制 autoMemoryDirectory
这是一个非常重要的安全边界，不是普通实现细节。

### 细节 5：sidechain transcript 的本地 dedup 与 remote dedup 语义不同
如果把两者当成一回事，会完全看不懂某些 resume/remote bug 修复。

### 细节 6：`walkChainBeforeParse()` 这类 byte-level 优化说明 transcript 文件可以大到很夸张
这不是理论优化，而是真为生产大 session 服务的。

---

## 14. 逐文件精讲（本轮覆盖文件）

### 14.1 `source/src/utils/attachments.ts`
- **文件作用**：attachment message 组装中心
- **导出的内容**：attachment 相关构造与收集函数
- **主要逻辑**：把文件/plan/memory/hook/deferred-tool/agent-state 等运行副作用转成 attachment messages
- **被谁使用**：`query.ts`, compact/post-tool/post-memory 路径
- **依赖了谁**：message types、memory/services、plan/agent/task 状态等
- **是否值得重点精读**：高

### 14.2 `source/src/services/SessionMemory/sessionMemory.ts`
- **文件作用**：会话记忆服务层
- **导出的内容**：session memory 相关主服务函数/类
- **主要逻辑**：当前 session 相关记忆的保存、读取、压缩协同、prefetch/restore 协同
- **被谁使用**：query/compact/stopHooks/memory extraction 路径
- **依赖了谁**：sessionMemoryUtils、memdir、attachments、settings/state
- **是否值得重点精读**：高

### 14.3 `source/src/services/SessionMemory/sessionMemoryUtils.ts`
- **文件作用**：SessionMemory 辅助函数层
- **导出的内容**：memory 相关路径、筛选、转换、辅助逻辑
- **主要逻辑**：让 session memory 与 query/compact/restore 更容易协同
- **被谁使用**：sessionMemory 主服务及相关调用方
- **依赖了谁**：memdir/state/messages 等基础层
- **是否值得重点精读**：中高

### 14.4 `source/src/utils/messages.ts`
- **文件作用**：消息领域模型基础工具
- **导出的内容**：message 分类、compact boundary 判断、tag 提取等工具函数
- **主要逻辑**：为 query/compact/sessionStorage/toolExecution 提供统一消息操作抽象
- **被谁使用**：几乎整个系统
- **依赖了谁**：基础类型与少量 helper
- **是否值得重点精读**：极高（基础设施价值）

### 14.5 `source/src/utils/sessionStorage.ts`
- **文件作用**：session transcript 持久化与恢复中心
- **导出的内容**：record/load/hydrate/resume/log listing/metadata persistence/subagent transcript/content replacement/context collapse snapshot 等大量 API
- **主要逻辑**：append-only JSONL 写入、queue flush、lite metadata、resume chain rebuild、snip/compact relink、remote hydrate、subagent transcript 管理
- **被谁使用**：REPL、query、compact、resume picker、remote/CCR、task/agent 系统
- **依赖了谁**：bootstrap state、messages utils、analytics、settings、path/git/fs/history/UUID 等几乎所有基础设施
- **是否值得重点精读**：最高优先级之一

### 14.6 `source/src/memdir/paths.ts`
- **文件作用**：auto-memory 路径与安全边界定义
- **导出的内容**：`isAutoMemoryEnabled`, `isExtractModeActive`, `getAutoMemPath`, `getAutoMemEntrypoint`, `getAutoMemDailyLogPath`, `isAutoMemPath` 等
- **主要逻辑**：memory feature gate、path override、trusted setting sources、安全校验、worktree-shared memory root
- **被谁使用**：memory extraction、filesystem write carve-out、prompt memory 注入、remember/dream/team sync 等
- **依赖了谁**：bootstrap state、settings、path/git/env utils
- **是否值得重点精读**：极高

---

## 15. 本轮已完成分析的文件列表（相对路径）

- `source/src/utils/attachments.ts`
- `source/src/services/SessionMemory/sessionMemory.ts`
- `source/src/services/SessionMemory/sessionMemoryUtils.ts`
- `source/src/utils/messages.ts`
- `source/src/utils/sessionStorage.ts`
- `source/src/memdir/paths.ts`

---

## 16. 本轮未完成但下一轮建议继续分析的模块

1. MCP 集成模块
2. 模型 client/provider/config/认证模块
3. 插件 / skills 生态更细分模块
4. `source/src/commands/**` 逐文件精讲
5. `source/src/tools/**` 其余工具族逐文件精讲
6. 文件总索引表与覆盖审计推进

---

## 17. 当前累计已覆盖文件数 / 总文件数

- 已完成深读与模块级分析：**50 / 1954**
- 已完成路径扫描：**1954 / 1954**

---

## 18. 当前代码库学习进度

- **整体学习进度：64%**
- **Memory / Session 恢复层理解进度：78%**
- **内容级深读进度：约 50 / 1954**

下一步建议：进入 **MCP 集成模块**，因为：
- 它与 tools/commands/query/permissions 都有强耦合
- 也是 Claude Code 作为 Agent 平台的重要扩展支点
