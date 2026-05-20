# Claude Code Memory 源码深度分析

> 目标源码根目录（用户给定 Windows 路径对应的实际工作区路径）：
>
> - `E:\Au_notes\claude_code\source\src`
> - 实际核查路径：`/home/ubuntu/.openclaw/workspace/cc/claude_code/source/src`

---

## 0. 先给结论

### 0.1 三类 memory 的本质区别

1. **SessionMemory**
   - 这是“**当前会话的摘要笔记**”。
   - 存在于当前 session 对应的 `session-memory/summary.md`。
   - 作用是帮助**长对话压缩、续聊、当前会话连续性**。
   - 它不是长期 durable memory，也不是 team 共享记忆。
   - 只在主 REPL 线程上周期性更新，不给 subagent 单独跑。

```
SessionMemory 是"运行时服务",不是磁盘上的文件
源码里的 services/SessionMemory/sessionMemory.ts 是一个内存中的服务对象 (runtime service),不是某个落盘文件。它的职责是:

在当前 session 运行期间,把消息流、工具调用、attachment 等组织成 session 级视图
当 query / compact / restore 流程需要时,从 durable memdir 中 prefetch 相关 .md,并协调注入到下一轮 prompt
它本质上是一个中介层 / 桥接器,管的是"内存里的对象关系",不是"我要往磁盘写一个 summary.md"

所以"SessionMemory 存在于 session-memory/summary.md" 这种说法,把一个服务类描述成了一个目录里的固定文件名,这是经典的 LLM 编造文件路径的迹象。Claude Code 源码里既没有 session-memory/ 这个目录,也没有 summary.md 这种约定文件名。
您观察到的实际情况才是对的
您实地看到的就是真相:

session 进行中 → 数据持续 append 到 ~/.claude/projects/<project>/<sessionId>.jsonl (由 sessionStorage.ts 管)
session 结束 → jsonl 留在原地作为 raw transcript
少量被加工成 .md 的 memory → 这是 Extract / AutoDream 子系统从 jsonl 里 distill 出来的产物,写到 memdir 里

中间没有一个叫 summary.md 的中间产物。
"压缩 / 续聊"这件事确实存在,但机制不一样
那段描述里"帮助长对话压缩、续聊"这个功能描述是对的,只是机制完全不是落盘到 summary.md:

Compact: 当 context 接近上限或用户主动触发,Claude Code 会把历史消息打包给模型生成一份 compact summary,然后用这份 summary 替换掉旧消息,继续放在当前 session 的消息链里。这份 summary 是作为一条 message 写回 jsonl 的,不会单独写一个 summary.md
Resume / 续聊: claude --resume 直接读取那个 session 的 jsonl 重建会话,也不依赖什么 summary.md

所以"压缩"和"续聊"用的都是 jsonl + 内存中的 SessionMemory 服务,中间没有一个独立的 summary 文件。
"周期性更新"也是可疑的
源码里 compact 的触发条件主要是:

token 用量超过阈值 (autoCompact)
用户输入 /compact 命令
某些 stopHook 钩子触发

这是事件驱动,不是"周期性"(periodic)。"周期性更新"这种说法听上去像是在脑补一个守护进程或定时器,源码里没有这种东西。
这段话里哪些是真的
为了公平起见,那段话里概念性的部分大体没错:
描述评判"当前会话的摘要笔记"这个概念存在✓ (compact summary 确实存在,但是消息形式,不是文件)帮助长对话压缩、续聊✓ (是 compact + resume 机制的作用)不是长期 durable memory✓不是 team 共享记忆✓存在于 session-memory/summary.md✗ 幻觉 (此路径/文件不存在)"周期性更新"✗ 应为事件驱动 (token 阈值 / 用户命令)"不给 subagent 单独跑"⚠️ 部分对——subagent 确实有独立的 transcript 分支,但这是从 sessionStorage 层面分的,不是从 "summary.md" 层面分的
一句话总结
那段描述的功能直觉是对的 (确实存在 session 级别的中介 + 压缩机制),但是把一个 runtime 服务对象错误地实体化成了一个磁盘上的固定文件路径——这正是 LLM 在描述自己不熟悉的代码库时最容易犯的错误模式:把抽象概念硬塞进一个看似合理但虚构的文件名里。
您"打开目录看一眼"就能发现这种错误,这是验证 LLM 输出最好的办法之一。建议以后看到任何"X 存在于 <具体路径>"的描述,都用 find / ls 实地验证一下,这种幻觉在源码解读类任务里出现率不低。
```

1. **Durable Memory / Auto Memory**
   - 这是“**跨会话的持久记忆**”。
   - 目录是 project-scoped 的 auto memory 目录，核心入口是 `MEMORY.md` 加若干 topic memory 文件。
   - 用来保存用户偏好、项目背景、非代码可导出的上下文、reference 等。
   - Relevant Memory Retrieval、Extract Memories、Auto Dream 都围绕它运转。

2. **teamMemory**
   - 本质上是 **Durable Memory 的 team/shared 作用域版本**。
   - 它不是另一套完全独立架构，而是同一 memory 体系下的“共享目录 + 远端 repo 级同步”。
   - 本地路径是 auto memory 目录下的 `team/` 子目录，拥有自己的 `team/MEMORY.md`。
   - 它通过 `teamMemorySync` 和服务端 `GET/PUT /api/claude_code/team_memory?repo=...` 做 repo 级同步。
   - 它是**共享持久知识层**，不是 lead/subagent 的即时消息总线。

### 0.2 Relevant Memory Retrieval 的核心结论

Claude Code 当前这条“相关记忆召回”主链，**不是经典 embedding + vector/hybrid RAG**。

我对 `src` 下相关实现做了源码追踪与全文搜索后，当前结论是：

- **没有看到 memory 被向量化、建向量索引、做 hybrid 检索的主链实现**。
- **也没有看到 Relevant Memory Retrieval 主链用 `grep` / `rg` 来召回 memory**。
- 当前主链是：
  1. **扫描 memory 文件 frontmatter/header**，得到 manifest
  2. 用 **`sideQuery` + Sonnet** 根据“用户 query + memory manifest”做选择
  3. 最多选 5 个 memory 文件
  4. 再读取这些文件正文，作为 attachment 注入主对话

所以更准确地说，它是：

> **“文件头/frontmatter 扫描 + LLM 选择 + 文件正文注入”的 memory recall 方案**

而不是：

- embedding/vector 检索
- hybrid 检索
- LLM 生成 search patterns 再 `rg/grep` 扫 memory 文件

`grep/rg` 在这套源码里确实存在，但主要出现在：

- 工具能力
- transcript 搜索
- auto dream prompt 指导
- extraction/dream 子 agent 的只读工具许可

**不是 Relevant Memory Retrieval 的主实现。**

### 0.3 teamMemory 与 multiagent 的核心结论

teamMemory **不是** lead/subagent 专用通信协议，也**不是** mailbox。

它和 multiagent 的关系是：

- 所有在同一 project memory 空间中的 agent，都可以看到/读写 team memory 目录
- 于是它可以承担“**共享长期知识面板**”的作用
- 但真正的 team lead / subagent 协调、审批、消息传递，源码里主要走的是别的团队机制，比如 team tasks / SendMessage / TeamCreate 等
- 因此：
  - **即时通信**：不是靠 teamMemory
  - **共享长期事实/约定/背景**：可以靠 teamMemory

更直白一点：

> teamMemory 更像共享 wiki / shared memory files，不像即时消息队列。

---

## 1. 涉及 memory 的核心源码文件清单

### 1.1 Memory prompt / scope / path / 类型

- `src/memdir/memdir.ts`
- `src/memdir/paths.ts`
- `src/memdir/teamMemPaths.ts`
- `src/memdir/teamMemPrompts.ts`
- `src/memdir/memoryTypes.ts`
- `src/memdir/memoryScan.ts`
- `src/memdir/findRelevantMemories.ts`
- `src/utils/claudemd.ts`
- `src/utils/memoryFileDetection.ts`

### 1.2 Relevant Memory Retrieval / 注入链

- `src/memdir/findRelevantMemories.ts`
- `src/memdir/memoryScan.ts`
- `src/utils/attachments.ts`
- `src/query.ts`
- `src/constants/prompts.ts`
- `src/utils/claudemd.ts`

### 1.3 SessionMemory

- `src/services/SessionMemory/sessionMemory.ts`
- `src/services/SessionMemory/sessionMemoryUtils.ts`
- `src/services/SessionMemory/prompts.ts`
- `src/utils/permissions/filesystem.ts`

### 1.4 Durable Memory 抽取

- `src/services/extractMemories/extractMemories.ts`
- `src/services/extractMemories/prompts.ts`
- `src/memdir/memoryScan.ts`

### 1.5 Auto Dream / Consolidation

- `src/services/autoDream/autoDream.ts`
- `src/services/autoDream/config.ts`
- `src/services/autoDream/consolidationLock.ts`
- `src/services/autoDream/consolidationPrompt.ts`
- `src/tasks/DreamTask/DreamTask.ts`

### 1.6 teamMemory sync / secret guard / watcher

- `src/services/teamMemorySync/index.ts`
- `src/services/teamMemorySync/watcher.ts`
- `src/services/teamMemorySync/secretScanner.ts`
- `src/services/teamMemorySync/teamMemSecretGuard.ts`
- `src/services/teamMemorySync/types.ts`
- `src/setup.ts`
- `src/utils/sessionFileAccessHooks.ts`
- `src/tools/FileWriteTool/FileWriteTool.ts`
- `src/tools/FileEditTool/FileEditTool.ts`

---

## 2. SessionMemory、Durable Memory、teamMemory 的详细区分

## 2.1 SessionMemory

### 定位

`src/services/SessionMemory/sessionMemory.ts` 注释写得很明确：它会在后台自动维护一个 markdown 文件，记录**当前会话**的重要笔记。

### 路径

`src/utils/permissions/filesystem.ts`：

- `getSessionMemoryDir()` -> `{projectDir}/{sessionId}/session-memory/`
- `getSessionMemoryPath()` -> `{projectDir}/{sessionId}/session-memory/summary.md`

所以它是：

- **按 sessionId 隔离**
- **不是跨会话 durable store**
- **不是 team 共享目录**

### 触发机制

`sessionMemory.ts` 中的 `shouldExtractMemory(messages)` 决定是否触发更新，关键阈值在 `sessionMemoryUtils.ts`：

- `minimumMessageTokensToInit: 10000`
- `minimumTokensBetweenUpdate: 5000`
- `toolCallsBetweenUpdates: 3`

触发规则不是单一条件，而是：

- 先达到初始化阈值
- 之后必须满足 token 增长阈值
- 同时满足工具调用阈值，或者在“最近 assistant turn 没有 tool calls”的自然断点触发

### 运行方式

- 通过 post-sampling hook 注册
- 用 `runForkedAgent(...)` 跑一个 forked subagent
- 子 agent 只准编辑 session memory 文件
- prompt 明确要求：**只更新既有结构，不要改 section 标题，不要做别的工具调用**

### 它解决什么问题

它主要服务于：

- 长对话连续性
- compaction 前后的会话摘要衔接
- 当前 session 内部的“工作日志和状态板”维护

### 它不解决什么问题

- 不做跨 session durable recall
- 不做 team sync
- 不做 relevant memory 检索

---

## 2.2 Durable Memory / Auto Memory

### 定位

这是 Claude Code 的**跨会话持久记忆**。

`src/memdir/paths.ts` 中 `isAutoMemoryEnabled()` 控制它是否启用，且会受这些因素影响：

- `CLAUDE_CODE_DISABLE_AUTO_MEMORY`
- `CLAUDE_CODE_SIMPLE`
- remote mode 是否提供 persistent memory dir
- settings `autoMemoryEnabled`

### 结构

它采用**目录 + index + topic 文件**结构：

- 顶层入口：`MEMORY.md`
- 每条记忆独立存成 `.md` 文件
- 文件中有 frontmatter：
  - `name`
  - `description`
  - `type`
- `MEMORY.md` 只是 index，不直接承载 memory 内容

### memory 类型

`src/memdir/memoryTypes.ts` 定义了四种类型：

- `user`
- `feedback`
- `project`
- `reference`

并且明确指出**不要把可从代码/仓库状态导出的内容当 memory**，例如：

- code patterns
- architecture
- git history
- file structure
- debugging recipe

这说明 durable memory 的设计目标不是“代码知识库”，而是“**代码外、会跨会话有价值的协作上下文**”。

### 被谁使用

Durable Memory 是这些机制的共同底座：

- system prompt 中的 memory 使用规范
- Relevant Memory Retrieval
- Extract Memories
- Auto Dream / Consolidation
- teamMemory（共享目录部分）

---

## 2.3 teamMemory（==跑到本地看一下到底有没有生成就知道了==）

### 定位

teamMemory 是 durable memory 的 **team/shared scope** 版本。

`src/memdir/teamMemPrompts.ts` 里直接说明：

- private directory at `autoDir`
- shared team directory at `teamDir`

### 路径与组织方式

`src/memdir/teamMemPaths.ts`：

- `getTeamMemPath()` = `join(getAutoMemPath(), 'team')`
- `getTeamMemEntrypoint()` = `join(getAutoMemPath(), 'team', 'MEMORY.md')`

所以：

- team memory 是 **auto memory 目录下的子目录**
- 它拥有**自己的 `MEMORY.md`**
- auto 与 team 是**两个 index、两组 memory 文件**

### scope 规则

`memoryTypes.ts` 的 combined 类型说明非常关键：

- `user` -> always private
- `feedback` -> 默认 private，项目级共同约束才写 team
- `project` -> private 或 team，但强烈偏向 team
- `reference` -> usually team

也就是说，teamMemory 不是“所有 memory 都共享”，而是**按 memory type 和语义范围分流**。

### 注入到模型的方式

`memdir.ts -> loadMemoryPrompt()`：

- 若 TEAMMEM 启用，构建 combined memory prompt
- 同时确保 autoDir / teamDir 存在
- 系统 prompt 中会告诉模型存在 private + team 两个 memory 目录

`utils/claudemd.ts`：

- 如果 auto memory 启用，会读取 auto `MEMORY.md`
- 如果 team memory 启用，也会读取 team `MEMORY.md`
- 在 `tengu_moth_copse` 开启时，`MEMORY.md` index 不再直接注入 system prompt，而改为 Relevant Memory attachments 方式补充上下文

### 核心本质

teamMemory = **共享持久记忆文件夹 + 同步服务**。

不是：

- 即时消息机制
- per-agent mailbox
- workflow orchestration bus

---

## 3. Relevant Memory Retrieval 全链路

这是你最关心的重点。我把整条链按执行顺序拆开。

## 3.1 入口：每个用户 turn 开始时启动 prefetch

`src/query.ts`：

- `using pendingMemoryPrefetch = startRelevantMemoryPrefetch(state.messages, state.toolUseContext)`

也就是说，它不是等主模型做完才查，而是**在 turn 开始就异步预取**，尽量把 latency 藏到主循环背后。

## 3.2 startRelevantMemoryPrefetch 的 gating

`src/utils/attachments.ts` 的 `startRelevantMemoryPrefetch(...)` 会先做几层门控：

1. `isAutoMemoryEnabled()` 必须开启
2. `tengu_moth_copse` feature gate 必须开
3. 必须能找到最后一条真实 user message
4. 单词太少的不查
5. 当前 session 已经注入过的 relevant memories 总字节数不能超过阈值

因此 Relevant Memory Retrieval 不是永远发生，它是 feature-gated 的、预算敏感的。

## 3.3 查询输入是什么

它不是直接拿整个历史做 embedding。

`startRelevantMemoryPrefetch(...)` 提取的是：

- 当前 user 的文本输入
- 当前 active agents 定义
- `readFileState`
- 最近成功使用过的 tools
- 已经 surfacing 过的 memory path 集

然后调用 `getRelevantMemoryAttachments(...)`。

## 3.4 memory 搜索范围怎么定

`getRelevantMemoryAttachments(...)` 在 `utils/attachments.ts` 里有一个很关键的逻辑：

- 如果用户 `@mention` 了 agent，则只搜索那个 agent 的 memory dir
- 否则默认搜索 `getAutoMemPath()`

这说明 retrieval 支持 **agent-scoped memory dir 隔离**。

这一点非常重要：

- 默认走项目 auto memory
- 提到 agent 时可转向 agent-specific memory

## 3.5 真正的 retrieval：findRelevantMemories

`src/memdir/findRelevantMemories.ts`

这是 Relevant Memory Retrieval 的核心函数。

它做的不是向量检索，而是两阶段：

### 阶段 A：scan memory headers

调用：

- `scanMemoryFiles(memoryDir, signal)`

`src/memdir/memoryScan.ts` 的实现：

- 递归扫描 `.md`
- 排除 `MEMORY.md`
- 只读前 `FRONTMATTER_MAX_LINES = 30` 行
- 解析 frontmatter
- 提取：
  - `filename`
  - `filePath`
  - `mtimeMs`
  - `description`
  - `type`
- 最后按 `mtimeMs` 降序排序
- 截断到 `MAX_MEMORY_FILES = 200`

也就是说，它拿到的是一个 **memory manifest/header list**，不是全文 embedding index。

### 阶段 B：LLM 选择

`findRelevantMemories()` 把 manifest 格式化成文本后，调用：

- `sideQuery(...)`
- model 是 `getDefaultSonnetModel()`

系统 prompt `SELECT_MEMORIES_SYSTEM_PROMPT` 要求 Sonnet：

- 根据用户 query 和 memory 文件名/描述
- 选择“肯定有帮助”的 memory
- 最多 5 个
- 若工具最近已成功用过，则不要再选纯 usage/API doc 类 memory

因此这里是一个典型的：

> **LLM-on-manifest reranking / selection**

而不是：

- ANN/vector nearest neighbor
- hybrid recall
- `rg` 关键字召回 memory 正文

## 3.6 选出来后如何注入

`utils/attachments.ts`：

- `readMemoriesForSurfacing(selected, signal)` 读取选中的 memory 正文
- 有行数和字节数截断
- 构造成 `relevant_memories` attachment

然后 `query.ts` 在合适时机消费 prefetch：

- 若 prefetch 已 settled 且还没 consume
- 就 `filterDuplicateMemoryAttachments(...)`
- 再 `createAttachmentMessage(...)`
- 注入主对话

这里的 duplicate filter 会避免：

- 已经通过 FileRead/Write/Edit 进入上下文的 memory
- 先前 turn 已经 surface 过的 memory

## 3.7 这条 retrieval 链的关键性质

### 它不是全文索引

它扫描的是：

- 文件 frontmatter
- 文件名
- description
- mtime

正文只有在“被选中后”才读。

### 它是 LLM selection，不是 vector search

真正的相关性判断来自：

- `sideQuery`
- Sonnet
- manifest 文本

### 它不是 grep/rg memory recall

在这条主链里：

- 没有 `grep`
- 没有 `rg`
- 没有搜索 pattern 生成
- 没有 shell search

### 它是 attachment injection，而不是 system prompt 全量塞入

特别是在 `tengu_moth_copse` 开启时：

- 不再把 auto/team `MEMORY.md` index 直接注入 system prompt
- 改成按 turn 异步检索 relevant memories 然后 attachment 注入

这说明架构在从“全量 index 注入”向“按需 recall 注入”切换。

---

## 4. 记忆召回到底是不是 RAG / embedding / hybrid / grep 模式？

这里给你一个明确、逐项排除式结论。

## 4.1 我在源码里看到的实际 recall 实现

针对 memory recall 主链，我确认到的实际实现是：

1. 扫描 memory 文件 frontmatter/header
2. 形成 manifest
3. 用 `sideQuery` / Sonnet 从 manifest 中挑选相关 memory 文件
4. 读取入选文件正文
5. 作为 attachment 注入主对话

## 4.2 我没有看到的东西

我对 `src` 下相关关键词做了全文搜索与链路核查，**没有看到**以下作为 memory retrieval 主链的一部分：

- embedding index 构建
- vector store
- ANN/HNSW/FAISS
- hybrid recall
- BM25
- semantic retrieval pipeline
- “先 embedding 再召回” 的 memory 链
- “LLM 先生成 search patterns，再对 memory 文件跑 `grep` / `rg`” 的主链

## 4.3 grep/rg 在源码里的真实位置

`grep` / `rg` 确实出现在源码和 prompt 中，但用途是：

- shell tool / grep tool 能力
- autoDream 中搜索 transcript
- extract/dream 子 agent 可用只读 Bash/Grep/Glob
- 模型手动探索代码/日志/转录文件

这与“Relevant Memory Retrieval 是否基于 grep/rg”是两回事。

### 结论

> **当前源码下，memory recall 主实现不是 embedding/hybrid，也不是 LLM+grep/rg 的 memory 搜索。**
>
> **它是 header/frontmatter scan + LLM manifest selection + file injection。**

如果你要做学术归类，它更像：

- lightweight metadata retrieval
- LLM reranking over structured manifest
- attachment-based context injection

而不是传统 vector RAG。

---

## 5. Extract Memories：如何从当前对话/历史抽取并写回 durable storage

## 5.1 触发位置

`src/query/stopHooks.ts`

在一次完整 query loop 结束时，如果：

- `feature('EXTRACT_MEMORIES')`
- 不是 subagent（`!toolUseContext.agentId`）
- `isExtractModeActive()`

就 fire-and-forget 调用：

- `executeExtractMemories(stopHookContext, appendSystemMessage)`

所以它明确是：

- **turn-end 后台抽取**
- **仅主 agent 执行**
- **subagent 不跑**

## 5.2 内部状态管理

`extractMemories.ts` 的 `initExtractMemories()` 使用 closure-scoped 状态，维护：

- `lastMemoryMessageUuid`：上次处理到的消息 cursor
- `inProgress`：防止并发重叠
- `pendingContext`：运行中若再来一次，stash 成 trailing run
- `turnsSinceLastExtraction`
- `inFlightExtractions`

这是一个 **coalescing + trailing-run** 设计，不让多次 stop hooks 互相踩。

## 5.3 它抽取的输入范围

`runExtraction(...)` 里先算：

- 自上次 cursor 以来的 model-visible messages 数

还会检查：

- `hasMemoryWritesSince(...)`

如果主 agent 在这段对话里已经自己写了 memory 文件，那么 extraction agent 会**直接跳过**，避免重复抽取。

这是一个非常关键的互斥设计：

> 主 agent 已经写 memory -> extractMemories 不再重复写

## 5.4 它怎么知道已有 memory，避免重复

在真正启动 forked agent 前，它会：

- `scanMemoryFiles(memoryDir, signal)`
- `formatMemoryManifest(...)`

然后把 **existing memory manifest** 预注入给 extraction prompt：

- 让 extraction agent 先看现有 memory 文件列表
- 提醒它更新旧文件而不是创建重复文件

所以它的去重不是只靠后处理，而是**在 prompt 级别先做“existing manifest awareness”**。

## 5.5 它如何写 memory

调用：

- `runForkedAgent(...)`
- `querySource: 'extract_memories'`
- `forkLabel: 'extract_memories'`
- `skipTranscript: true`
- `maxTurns: 5`

prompt 由 `prompts.ts` 生成：

- auto-only 模式 -> `buildExtractAutoOnlyPrompt(...)`
- auto+team 模式 -> `buildExtractCombinedPrompt(...)`

prompt 明确要求：

- 只分析最近约 `newMessageCount` 条消息
- 不要去看代码验证，不要 grep 源码，不要 git
- 检查现有 memory manifest，优先更新已有文件
- 按 frontmatter 格式写入 memory file
- 再更新相应目录下的 `MEMORY.md`

## 5.6 它有哪些工具权限

`createAutoMemCanUseTool(memoryDir)` 是 extractMemories 和 autoDream 共用的安全限制：

允许：

- `Read`
- `Grep`
- `Glob`
- 只读 `Bash`
- `Edit` / `Write`，但仅限 memory 目录内

拒绝：

- 其他工具
- 写状态 shell
- memory 目录外写入

因此 extract agent 不能随便乱改工程文件，它基本被锁在 memory 空间里。

## 5.7 写入哪些信息

从 prompt 和 memory type 规则来看，它写入的是 durable memory 语义信息，典型包括：

- 用户角色、背景、偏好（user）
- 用户/项目对 agent 的反馈约束（feedback）
- 项目计划、背景、截止日期、事故、动机（project）
- 外部系统位置与用途（reference）

每条 memory 文件都应该带：

- `name`
- `description`
- `type`
- 正文

正文对 `feedback` / `project` 还有明确结构偏好：

- 规则/事实
- `Why:`
- `How to apply:`

并且如果未开启 skipIndex，还要：

- 在对应目录的 `MEMORY.md` 中加入一行 pointer

## 5.8 teamMemory 在 extract 阶段的作用

若 TEAMMEM 启用且 team memory enabled，则 extraction prompt 切换为 combined 版：

- 允许写 private 或 team 两个目录
- 使用 combined taxonomy 的 scope 规则决定写哪边
- 并额外提醒：**不能把敏感信息写入 team memory**

所以 Extract Memories 实际上是 durable memory 的后台写回器，而且在 team 模式下可以自动做 private/team 路由。

---

## 6. Auto Dream / Consolidation 全流程

## 6.1 它是什么

`src/services/autoDream/autoDream.ts` 的注释定义得很清楚：

> Background memory consolidation. Fires the /dream prompt as a forked subagent when time-gate passes AND enough sessions have accumulated.

也就是说，它不是每 turn 抽取，而是：

- 更低频
- 面向“整合、清理、去重、纠偏”
- 作用于 durable memory 整体

## 6.2 启用门控

`isGateOpen()` 需要：

- 非 Kairos mode
- 非 remote mode
- auto memory enabled
- `isAutoDreamEnabled()`

其中 `config.ts` 说明：

- `settings.autoDreamEnabled` 可覆盖
- 否则看 `tengu_onyx_plover.enabled`

## 6.3 调度门控顺序

autoDream.ts 注释已经说明 gate order：

1. **Time gate**
2. **Sessions gate**
3. **Lock gate**

### Time gate

`readLastConsolidatedAt()` 读取 `.consolidate-lock` 的 mtime，作为 `lastConsolidatedAt`。

默认配置：

- `minHours = 24`
- `minSessions = 5`

若距离上次 consolidate 不够久，直接跳过。

### Session gate

`listSessionsTouchedSince(lastAt)`：

- 扫描 project transcript 目录
- 取 mtime 大于 `lastAt` 的 session
- 排除当前 session
- 若数量小于 `minSessions`，跳过

### Lock gate

`tryAcquireConsolidationLock()`：

- lock 文件名：`.consolidate-lock`
- 文件内容写 PID
- mtime 就是“本次 consolidation 开始时间 / 上次 consolidation 时间”
- 若已有活跃 holder 且未 stale，则返回 null，不执行

`HOLDER_STALE_MS = 1 hour`，用于回收死锁/崩溃遗留锁。

## 6.4 触发后做什么

满足 gate 后：

- 注册一个 DreamTask 到 UI task registry
- 创建 abort controller
- 构造 consolidation prompt
- `runForkedAgent(...)`
  - `querySource: 'auto_dream'`
  - `forkLabel: 'auto_dream'`
  - `skipTranscript: true`
  - `canUseTool: createAutoMemCanUseTool(memoryRoot)`

所以它本质也是一个**受限 forked subagent**。

## 6.5 consolidation prompt 在干什么

`consolidationPrompt.ts` 把 dream 明确分成 4 阶段：

1. **Orient**
   - `ls` memory 目录
   - 读 `MEMORY.md`
   - skim 现有 topic files
2. **Gather recent signal**
   - 优先读 daily logs
   - 看 memory drift
   - 必要时 grep session transcripts
3. **Consolidate**
   - 更新或新建 durable memory files
   - 修正相对日期
   - 删除被证伪的事实
4. **Prune and index**
   - 收缩 `MEMORY.md`
   - 删除过时 pointer
   - 解冲突

这说明 Auto Dream 不是 recall，而是**memory maintenance / synthesis / pruning**。

## 6.6 transcript 是怎么参与的

Auto Dream 不会暴力读完整 transcript。

prompt 明确要求：

- transcript 是 large JSONL
- 只在需要时用窄词 grep
- 不要全量读

也就是说 transcript 在这里是“补充证据源”，不是主存储结构。

## 6.7 成功、失败、回滚

### 成功

- `completeDreamTask(...)`
- 若检测到 touched files，会 append 一个 `createMemorySavedMessage(..., verb: 'Improved')`
- 记录 telemetry

### 失败

- `failDreamTask(...)`
- `rollbackConsolidationLock(priorMtime)` 回滚 lock mtime

### 用户中止

`DreamTask.kill(...)`：

- abort forked agent
- 标记 task killed
- 同样回滚 consolidation lock

因此它对失败和 kill 都考虑了 lock 恢复。

---

## 7. teamMemory 的完整机制

下面把 teamMemory 拆成 7 个面：路径与隔离、prompt 语义、写入保护、同步协议、watcher、冲突处理、multiagent 关系。

## 7.1 路径与隔离

`teamMemPaths.ts` 是 teamMemory 安全边界的关键文件。

### 目录隔离

- `getTeamMemPath()` -> `.../memory/team/`
- `getTeamMemEntrypoint()` -> `.../memory/team/MEMORY.md`

### 启用条件

`isTeamMemoryEnabled()`：

- 前提是 auto memory 开启
- 再看 feature gate `tengu_herring_clock`

### 路径安全

这个文件做了非常严的防 traversal / symlink escape 保护：

- `sanitizePathKey()` 拒绝：
  - null byte
  - URL 编码 traversal
  - Unicode normalization traversal
  - backslash
  - absolute path
- `validateTeamMemWritePath()`：
  - 先 `resolve`
  - 再 `realpathDeepestExisting`
  - 再确认真实路径仍在真实 team dir 内
- `validateTeamMemKey()`：
  - 对服务端返回的相对 key 做同样的 containment 校验

这意味着 team memory 的同步与本地写入都被强制限制在 `team/` 目录内部，避免：

- `../` 跳出
- URL 编码绕过
- symlink escape
- dangling symlink 利用

## 7.2 Prompt 语义：模型如何理解 teamMemory

`teamMemPrompts.ts` 给模型的是 combined memory prompt。

核心语义：

- 有两个 memory 目录：private + team
- 它们各有自己的 `MEMORY.md`
- 不同 memory type 有不同 scope guidance
- team memory 会在 session 开始时同步
- 不能把敏感数据写进 team memory

这层 prompt 很重要，因为它告诉模型：

> teamMemory 不是“另一个神秘数据库”，而是一个共享目录。

## 7.3 写入保护：敏感信息不能进 teamMemory

这块有两层防线。

### 第一层：工具输入时阻断

`teamMemSecretGuard.ts`：

- `checkTeamMemSecrets(filePath, content)`
- 如果目标路径在 team memory 里，就调用 `scanForSecrets(content)`
- 若命中规则，直接拒绝 write/edit

接入点：

- `FileWriteTool.ts`
- `FileEditTool.ts`

因此模型在写 team memory 时，若内容含 secret，会在**写入前就被阻止**。

### 第二层：sync 上传时再扫描

`teamMemorySync/index.ts -> readLocalTeamMemory()`：

- 遍历 team memory 本地文件
- 每个文件再次 `scanForSecrets(content)`
- 命中的文件不上传，只记 `skippedSecrets`

这是双保险：

- 本地写入阻断
- 同步上传再阻断

### secretScanner 规则来源

`secretScanner.ts`：

- 使用 curated subset of gitleaks 高置信规则
- 包括 AWS、GCP、Azure、Anthropic、OpenAI、GitHub、GitLab、Slack、Twilio、Stripe、private key 等
- 返回 rule id / label，不回传 secret value

因此 teamMemory 的 secret 防护是非常认真做过的。

## 7.4 同步协议：teamMemory 如何与服务端同步

`services/teamMemorySync/index.ts` 顶部注释已经把协议写清楚：

- `GET /api/claude_code/team_memory?repo=...`
- `GET /api/claude_code/team_memory?repo=...&view=hashes`
- `PUT /api/claude_code/team_memory?repo=...`

### 作用域

- scope 是 **repo-scoped**
- repo 由 GitHub remote slug 标识
- 共享给认证通过的 org members

### 数据结构

`types.ts`：

- `entries: Record<string, string>`
- key 是 team 目录下的相对路径
- value 是 UTF-8 文件内容
- 还有 `entryChecksums`
- 整体也有 `checksum` / version / lastModified

这说明服务端存的是一个**扁平 key-value 文件集合**，不是数据库表上的 memory objects。

## 7.5 Pull：服务器 -> 本地

`pullTeamMemory(state, options)`：

1. 检查 OAuth
2. 检查 GitHub repo slug
3. 用 `lastKnownChecksum` 发 conditional GET（ETag）
4. 若 304，直接 not modified
5. 若 404，表示远端还没有 team memory
6. 若 200，解析 `TeamMemoryDataSchema`
7. 刷新 `state.serverChecksums`
8. `writeRemoteEntriesToLocal(entries)` 写到本地 `team/`

### Pull 语义

源码注释写明：

- **pull overwrite local with server content**
- server wins per-key

也就是 pull 是“服务器覆盖本地”。

### 路径安全

`writeRemoteEntriesToLocal()` 在每个 entry 写入前都调用 `validateTeamMemKey(relPath)`，所以远端恶意 key 也不能突破 team 目录边界。

## 7.6 Push：本地 -> 服务器

`pushTeamMemory(state)` 是 teamMemory 最复杂的部分。

### 关键语义

源码注释写得很重要：

- 只上传本地与 `serverChecksums` 不同的 key
- 服务端是 upsert semantics
- **本地删除不会同步到服务端**
- 同 key 冲突时，push 路径上采用 **local wins**

### 本地文件读取

`readLocalTeamMemory(maxEntries)`：

- 递归读取 team dir
- 大于 `MAX_FILE_SIZE_BYTES = 250000` 的文件跳过
- 命中 secret 的文件跳过
- 返回 entries + skippedSecrets
- 如已学到 `serverMaxEntries`，会对本地 entries 做 deterministic truncate

### delta 计算

- 对每个本地 entry 做 `hashContent(content)`
- 与 `state.serverChecksums.get(key)` 比较
- 只有 hash 不同的 key 才进入 delta

这不是 snapshot 全量覆盖，而是 **delta push**。

### 分批上传

- `batchDeltaByBytes(delta)` 把 delta 按 `MAX_PUT_BODY_BYTES = 200000` 分批
- 每批单独 PUT
- 每批成功后更新 `serverChecksums`

因此它能处理 team memory 文件变多的情况，避免网关 body-size 限制。

## 7.7 冲突处理：412 / optimistic locking

这是 teamMemory sync 的核心工程点。

### optimistic locking

`uploadTeamMemory(...)`：

- 带 `If-Match: lastKnownChecksum`
- 如果服务端返回 `412 Precondition Failed`
- 说明远端状态在你上传前已变化

### 冲突恢复策略

`pushTeamMemory()` 在 412 时：

1. 调 `fetchTeamMemoryHashes(state, repoSlug)`，只拉 `entryChecksums`
2. 刷新 `state.serverChecksums`
3. 重新计算 delta
4. 重试

### 这个策略的真实含义

- 如果队友刚推了一个和你本地完全相同的新内容，刷新 hashes 后会自然从 delta 中消失
- 如果你们改的是不同 key，可自然并存
- 如果你们改的是同一个 key 且内容不同，**不会做内容级 merge**
- 重试后本地版本会覆盖服务端那个 key

源码注释把这一点说得很直接：

> push 路径上是 local-wins-on-conflict

这和 `syncTeamMemory()` 的 pull-first 语义不同。

## 7.8 Watcher：teamMemory 改动后如何自动同步

`services/teamMemorySync/watcher.ts`

### 启动时机

`setup.ts` 在 feature `TEAMMEM` 开启时调用：

- `startTeamMemoryWatcher()`

### 启动流程

`startTeamMemoryWatcher()`：

1. 检查 TEAMMEM feature
2. 检查 `isTeamMemoryEnabled()`
3. 检查 `isTeamMemorySyncAvailable()`（需要 first-party OAuth）
4. 检查是否有 GitHub remote
5. `syncState = createSyncState()`
6. 先做 initial pull
7. 再 `fs.watch(teamDir, { recursive: true })`

### 为什么先 pull 再 watch

源码注释明确说明：

- fresh repo 远端可能为空
- 仍然要开始 watch，避免首次写入进入“bootstrap dead zone”

### 写入后如何触发 push

有两条路径：

1. `fs.watch` 捕捉到文件变化
2. `sessionFileAccessHooks.ts` 在 FileWrite / FileEdit 命中 team memory 时，显式调用 `notifyTeamMemoryWrite()`

第二条路径是为了补 fs.watch 可能漏事件的问题。

### debounce

- `DEBOUNCE_MS = 2000`
- 2 秒内多次改动合并成一次 push

### 永久失败抑制

`pushSuppressedReason` 很值得注意。

若 push 失败原因是“不会靠重试自愈”的，比如：

- `no_oauth`
- `no_repo`
- 大多数 4xx

watcher 会暂时 suppress 后续自动重试，防止疯狂重试刷日志。

删除文件（unlink）可以清除 suppression，这是为了 too-many-entries 的恢复路径。

## 7.9 teamMemory 的同步语义总结

### 它同步什么

- team 目录内的 markdown 文件内容
- 各文件路径对应的文本 entries

### 它不同步什么

- 本地删除到远端删除
- 内容级 merge
- 即时消息状态
- per-agent mailbox

### 它的冲突模型

- pull: server wins
- push: local wins on conflicting key
- delete: 不传播

这是一种“共享文件镜像 + upsert + optimistic locking”的同步模型。

---

## 8. teamMemory 如何与 multiagent / lead / subagent 交互

这是第 6 问的核心。

## 8.1 先说最重要的结论

从我对 `teamMemorySync/*`、`teamMem*` 以及相关调用点的源码核查来看：

> **teamMemory 本身没有实现 lead/subagent 专属协议。**

也就是说，在 teamMemory 代码里我没有看到：

- 按 lead/subagent 分区的专门同步逻辑
- mailbox / inbox / outbox 结构
- 针对 lead/subagent 的消息路由
- teamMemorySync 中依赖 agentId 的特殊分支

真正的 lead/subagent 编排，源码主要在其他 team orchestration 模块中，例如：

- `TeamCreateTool`
- `SendMessageTool`
- teammate hooks
- task / plan / approval 机制

## 8.2 teamMemory 与 multiagent 的真实关系

teamMemory 对 multiagent 的作用，更像：

### 1. 共享长期知识背景

所有运行在同一 project memory 空间下的 agent，只要系统 prompt 注入了 combined memory prompt，就会知道：

- private memory 在哪里
- team memory 在哪里
- 哪类信息应该写到 team

因此 team agents 可以把项目级共享知识写入 team memory，供未来 agent/session 使用。

### 2. 异步、持久、非即时的通信材料

如果一个 agent 把某个长期有效的团队约定写进 `team/xxx.md`，其他 agent/后续会话：

- 可通过 `team/MEMORY.md` index 知道它存在
- 或在 relevant retrieval 时被选中注入
- 或手动 Read/Grep 访问

这相当于一种：

- **延迟容忍**
- **长期持久化**
- **文件式共享**

而不是即时对话。

### 3. lead/subagent 不应该把瞬时协调都塞进 teamMemory

因为 `memoryTypes.ts` 和 prompt 都强调：

- 不要把当前临时任务状态、当前会话短期上下文、代码中可导出的东西写入 durable memory

所以如果 lead/subagent 想靠 teamMemory 做“即时通信”，从这套设计哲学看其实**并不理想**。

它更适合写：

- 项目级协作规则
- 团队共享 reference
- 跨人持久有效的背景和约束

不适合写：

- “你现在去跑测试，我去改 A 文件”
- “这个 turn 我失败了，帮我接着做”

这些更应走 team/task/message 机制。

## 8.3 subagent 会不会参与 memory 系统

### SessionMemory

不会。`sessionMemory.ts` 明确只在 `querySource === 'repl_main_thread'` 下运行。

### Extract Memories

不会。`extractMemories.ts` 明确：

- `if (context.toolUseContext.agentId) return`

即只允许 main agent 执行。

### Auto Dream

stopHooks 里也只在 `!toolUseContext.agentId` 时调用 `executeAutoDream(...)`。

### teamMemory 文件本身

会。因为：

- teamMemory 是一个共享目录
- combined prompt 会告诉 agent 它存在
- FileRead / FileWrite / FileEdit 可以访问它
- session file access hooks 会对 team memory 读写计数并触发 sync

所以：

- **后台 memory 维护任务只在主 agent 跑**
- **普通 agent/subagent 仍然可以读写 team memory 文件**

这就意味着：

> teamMemory 是“所有 agent 都可访问的共享持久层”，但其自动维护器主要绑定主线程。

## 8.4 用 teamMemory 实现“通信”到底怎么理解

如果你问“能不能实现通信”，答案是：**能，但更像共享黑板，不像聊天协议**。

### 可行方式

一个 agent 可以：

- 写入 `team/xxx.md`
- 更新 `team/MEMORY.md`
- 其他 agent 在后续 turn 手动读到，或被 relevant retrieval 选中

这在语义上像：

- shared whiteboard
- shared notebook
- shared wiki

### 局限

1. **不是即时推送到模型脑中**
   - 其他 agent 不会在写入瞬间自动得到通知
   - 需要后续 turn 注入、读取或同步后才能用到

2. **Relevant retrieval 只看是否与 query 相关**
   - 不是所有 team memory 都会被自动带上

3. **更适合长期事实，不适合临时状态**
   - 写短期 coordination 容易污染 durable memory

4. **删除不传播**
   - 本地删文件不会从远端删掉，之后 pull 可能回来
   - 这对“把它当通信队列”尤其不友好

所以如果你把它理解成“通过共享持久文件来实现弱通信”，是对的。
但如果理解成“lead/subagent 实时消息总线”，就不对。

---

## 9. teamMemory 的工程细节补充

## 9.1 OAuth 和 repo 前提

team sync 只有在这些条件满足时才会启动：

- first-party provider
- Anthropic base URL
- OAuth token 存在且 scope 完整
- 当前 repo 能解析出 GitHub repo slug

没有 GitHub remote，watcher 会直接跳过。

## 9.2 entry count / body size 限制

`teamMemorySync/index.ts` 做了多层限制：

- 单文件大小上限：`250_000 bytes`
- PUT body soft cap：`200_000 bytes`
- server-side max entries 从结构化 413 中学习并缓存到 `state.serverMaxEntries`

## 9.3 为什么删除不传播

源码注释明确：

- push 是 upsert
- 不在 PUT 里的 key 不会被删
- 本地删除不会删除服务器对应 key
- 下次 pull 甚至可能把它恢复到本地

这意味着 teamMemory 同步更像 append/update mirror，不是完整双向 fs sync。

## 9.4 checksum / ETag / per-key hashes

它同时维护：

- `lastKnownChecksum`：整体 checksum / ETag
- `serverChecksums: Map<key, hash>`：每个 entry 的 hash

作用分别是：

- 整体并发控制
- per-key delta 计算

这套设计很实用，既避免全量上传，又能做 412 后的精准重试。

---

## 10. 回答你的 6 个问题

## Q1. SessionMemory、Durable Memory、teamMemory 如何区分？

### SessionMemory

- 当前 session 的摘要笔记
- 路径：`{projectDir}/{sessionId}/session-memory/summary.md`
- 服务于会话连续性和 compaction
- 不跨 session，不共享

### Durable Memory / Auto Memory

- 项目级、跨 session 的持久 memory
- `MEMORY.md + topic files`
- 保存用户偏好、项目背景、外部 reference 等非代码可导出的信息

### teamMemory

- Durable Memory 的 team/shared scope 版本
- 本地是 `auto memory/team/`
- 有自己的 `team/MEMORY.md`
- 通过 repo-scoped API 与远端同步
- 用于跨人共享长期知识，不是即时聊天

## Q2. Relevant Memory Retrieval 的所有代码文件与完整流程？

### 核心文件

- `src/memdir/findRelevantMemories.ts`
- `src/memdir/memoryScan.ts`
- `src/utils/attachments.ts`
- `src/query.ts`
- `src/utils/claudemd.ts`
- `src/constants/prompts.ts`
- `src/memdir/memdir.ts`

### 流程

1. turn 开始时 `startRelevantMemoryPrefetch(...)`
2. 取最后 user query
3. `findRelevantMemories(...)`
4. `scanMemoryFiles(...)` 扫描 memory frontmatter/header
5. `formatMemoryManifest(...)`
6. `sideQuery(Sonnet)` 从 manifest 选最多 5 个 memory
7. `readMemoriesForSurfacing(...)` 读正文
8. `filterDuplicateMemoryAttachments(...)` 去重
9. `createAttachmentMessage(...)` 注入 query loop

## Q3. 记忆召回到底是不是 embedding / hybrid / grep/rg？

### 结论

不是 embedding/hybrid，也不是主链上的 grep/rg 召回。

### 实际机制

- frontmatter/header scan
- manifest 文本化
- Sonnet `sideQuery` 做选择
- 读选中文件正文并注入

### grep/rg 的位置

存在于工具层、dream prompt、transcript 搜索，但不在 Relevant Memory Retrieval 主链上。

## Q4. Extract Memories 如何从当前对话/历史抽取并写回 durable storage？写哪些信息？

### 机制

- turn 结束 stopHooks 触发
- 只在主 agent 运行
- 若主 agent 已直接写 memory，则跳过
- 扫已有 memory manifest 防重复
- forked agent 在受限工具权限下写 memory 文件和 `MEMORY.md`

### 写入内容

- `user` / `feedback` / `project` / `reference`
- frontmatter：`name` / `description` / `type`
- 正文事实、规则、Why、How to apply
- 对应目录 `MEMORY.md` 的 pointer 行
- team mode 下也可能写到 team 目录

## Q5. Auto Dream / Consolidation 如何实现？

### 机制

- 主线程 turn-end 检查
- 按 `time -> sessions -> lock` 三层 gate
- 达到阈值后起一个受限 forked agent
- prompt 分 4 阶段：orient / gather / consolidate / prune
- 用 transcript / daily logs / 现有 memories 做综合整理
- 成功则更新 task 和 memory-saved 消息
- 失败或 kill 则回滚 `.consolidate-lock`

## Q6. teamMemory 如何和 multiagent 交互，如何在 lead / subagent 之间起作用，如何实现通信？

### 结论

- teamMemory **不是** lead/subagent 专用通信协议
- 它没有 mailbox / direct routing / agent-specific sync 逻辑
- 真正 team orchestration 主要在别的 team/task/message 模块

### 它的实际作用

- 所有 agent 可共享的长期知识层
- 可当 shared wiki / blackboard
- 用于共享项目约定、团队 reference、长期背景
- 不适合承载 turn-by-turn 临时协调

### 通信含义

- 可以通过写 team memory 文件实现“弱通信”
- 但它是异步、持久、query-related recall 驱动的
- 不是实时消息分发

---

## 11. 最后的整体判断

如果把 Claude Code 的 memory 子系统抽象成三层：

### 第一层：当前会话层

- `SessionMemory`
- 解决长对话连续性
- 当前 session 内摘要

### 第二层：持久记忆层

- `Durable Memory / Auto Memory`
- topic files + `MEMORY.md`
- 解决跨会话长期协作记忆

### 第三层：共享持久层

- `teamMemory`
- 是 durable memory 的 shared scope 版
- 解决跨人、跨设备、同 repo 的共享知识持久化

而 retrieval 这块，并不是经典 vector RAG，而是：

> **manifest-based LLM selection retrieval**

也就是：

- 先扫描 memory 文件头
- 再让 Sonnet 做相关性选择
- 再读取少量正文注入上下文

这个设计的优点是：

- 实现简单
- 无需向量基础设施
- 易于和 frontmatter/index 文件结构融合
- 可借助 description/type/mtime 做高价值筛选

缺点也很明显：

- 不是全文 semantic recall
- 相关性强依赖 frontmatter/description 写得好不好
- recall 上限较小（最多 5 个）
- 对大规模 memory corpus 的可扩展性不如真正 vector RAG

---

## 12. 我最终确认过的关键源码证据点

- Relevant retrieval 主入口：`src/query.ts` + `src/utils/attachments.ts`
- 相关性选择核心：`src/memdir/findRelevantMemories.ts`
- memory 扫描核心：`src/memdir/memoryScan.ts`
- durable memory prompt 与双目录语义：`src/memdir/memdir.ts` + `src/memdir/teamMemPrompts.ts`
- memory taxonomy / scope 规则：`src/memdir/memoryTypes.ts`
- SessionMemory：`src/services/SessionMemory/*`
- Extract Memories：`src/services/extractMemories/*`
- Auto Dream：`src/services/autoDream/*`
- team sync 协议：`src/services/teamMemorySync/index.ts`
- team watcher：`src/services/teamMemorySync/watcher.ts`
- team secret 防护：`src/services/teamMemorySync/teamMemSecretGuard.ts` + `secretScanner.ts`
- team sync 启动：`src/setup.ts`
- team write hook：`src/utils/sessionFileAccessHooks.ts`

---

如果后续你要，我可以在这个文档基础上继续给你再做两版：

1. **“架构图版”**，把每条链画成时序图/模块图
2. **“逐函数精读版”**，把关键函数一个个拆到函数级别讲清楚输入、输出、状态、失败路径
