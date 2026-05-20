# Memory 机制补充深析：Manifest、Frontmatter、Auto Dream

> 源码根目录：`/home/ubuntu/.openclaw/workspace/cc/claude_code/source/src`
>
> 本文件专门回答你新增的 3 个问题，并补上相关细节。

---

## 0. 先给最短结论

### Q1. Manifest 到底是什么？

它**不是另一套独立存储**，也不是经典搜索引擎里的倒排索引/向量索引。

它本质上是：

> **运行时把 memory 文件的“文件名 + frontmatter 里的 type/description + mtime”整理成一段纯文本目录，发给 Sonnet 做一次小型候选选择。**

所以它和 frontmatter 的关系是：

- **frontmatter** = 每个 `.md` memory 文件顶部的 YAML 元数据，存在文件里
- **manifest** = 程序运行时把很多 memory 文件的 frontmatter 和文件信息抽出来，拼成一段文本清单

换句话说：

> frontmatter 是单文件元数据，manifest 是多文件候选目录。

### Q2. frontmatter 是谁写的？

**不是某个固定后端函数自动帮你补的。**

当前源码下，frontmatter 主要由以下几类“模型写文件动作”负责写入：

1. **主模型自己写 durable memory** 时，按 system prompt 里的 memory 格式要求写
2. **`Extract Memories` forked agent** 写 durable memory 时，按 extraction prompt 里的格式要求写
3. **`Auto Dream` forked agent** 做 consolidation 时，按系统 prompt 里 memory file format 约定写

也就是说，frontmatter 的“写入责任”主要在**模型输出 + Write/Edit tool**，不是硬编码 serializer。

### Q3. Auto Dream 四阶段什么时候执行？

关键点：

> **四阶段是 prompt 里的工作说明，不是代码中的四段状态机。**

也就是说：

- 代码只负责在合适时机触发一个 forked agent
- 然后把 `Dream: Memory Consolidation` 这段 prompt 丢给它
- prompt 里把工作分成 4 phases
- 但代码本身**没有 phase1/phase2/phase3/phase4 的显式枚举状态流转**

UI 侧 `DreamTask` 注释甚至直接写了：

- `No phase detection`
- 只在 UI 上粗分成 `starting` 和 `updating`

所以 Four-Phase Prompt 是**认知工作流**，不是代码状态机。

---

## 1. Manifest 到底是什么，它做了什么？

这是你这次最核心的困惑，我分 6 层拆开。

## 1.1 它不是“索引文件”，而是“运行时展开出来的候选目录文本”

Relevant Memory Retrieval 的核心代码在：

- `src/memdir/memoryScan.ts`
- `src/memdir/findRelevantMemories.ts`

先看 `scanMemoryFiles(memoryDir, signal)`：

- 递归扫描 memory 目录
- 只保留 `.md` 文件
- 排除 `MEMORY.md`
- 只读取每个文件前 `FRONTMATTER_MAX_LINES = 30` 行
- `parseFrontmatter(...)`
- 抽出：
  - `filename`
  - `filePath`
  - `mtimeMs`
  - `description`
  - `type`

==也就是说，它先把一堆 memory 文件变成很多个 `MemoryHeader` 对象。==

然后 `formatMemoryManifest(memories)` 再把这些 `MemoryHeader` 变成文本：

```ts
- [type] filename (timestamp): description
```

例如：

```text
- [user] user_role.md (2026-03-15T10:45:23.000Z): Senior Go engineer, new to React
- [feedback] testing_policy.md (2026-03-14T09:20:00.000Z): Don't mock database in tests
- [project] sprint_status.md (2026-03-10T14:32:15.000Z): Mobile release frozen 2026-03-15
```

所以这里的 manifest：

- 不落盘
- 不是 memory 文件本体
- 不是新的数据结构存储层
- 是**临时生成出来给 Sonnet 看的候选列表**

---

## 1.2 它和 frontmatter 的关系到底是什么？

### frontmatter 是单个文件头

`parseFrontmatter` 在 `src/utils/frontmatterParser.ts`。

如果 markdown 顶部存在：

```md
---
name: xxx
description: yyy
type: user
---
```

它就会解析出 YAML 字段。

### manifest 是多文件摘要列表

`formatMemoryManifest(...)` 则会把**很多文件**的关键信息拼成一个大的文本块。

所以它们的关系可以这样理解：

- `frontmatter`：每个 memory 文件自己的 metadata
- `manifest`：==把所有 memory 文件的 metadata 摘出来，组成一个目录页==

如果用类比：

- frontmatter 像每本书书页里的“题名页”
- manifest 像图书馆临时打印的一张“书目单”

所以你说“这不就是记忆前的 header 吗？”

**对，但不完全。**

更精确的说法是：

> 它是“基于每个文件 header 重新汇总出来的一份跨文件目录文本”。

不是原始 header 本身，也不是 YAML 原样透传。

---

## 1.3 “文本索引”这里的“索引”到底是什么意思？

这里的“索引”不是数据库索引、向量索引、倒排索引的那个技术含义。

在这段源码语义里，它更接近：

- catalog
- listing
- table of contents
- inventory

所以“文本索引”的真实意思是：

> **给 LLM 看的一段文本化候选目录**

它不是让程序本身做关键词查找的索引结构，而是让 LLM 作为选择器读这张目录。

这也是为什么 `formatMemoryManifest(...)` 只是把它们串成字符串，而不是建立什么 search tree / embedding matrix。

---

## 1.4 纯 LLM 语义选择到底是怎么做的？

Relevant retrieval 核心函数是：

- `findRelevantMemories(...)`
- `selectRelevantMemories(...)`

在 `selectRelevantMemories(...)` 里，流程是：

1. 把 memory headers 通过 `formatMemoryManifest(...)` 变成一段 manifest 文本
2. 把当前用户 query 拼进去
3. 可选地再带上 recently-used tools
4. 发给 `sideQuery(...)`
5. model 是 `getDefaultSonnetModel()`
6. 要求输出一个 JSON schema：

```json
{
  "selected_memories": ["file1.md", "file2.md"]
}
```

所以“纯 LLM 语义选择”具体是：(==所以其实就是交给大模型去选了， 然后让大模型给出要访问的文件==)

> **Sonnet 阅读 `Query + Available memories manifest`，根据文件名和 description 判断哪些 memory 会明显有用，然后返回文件名列表。**

它不是：

- 先算 embedding 相似度再 rerank
- 先 BM25 召回再交给 LLM
- 先 grep memory body 再排序

而是一步到位地：

- 读 manifest
- 做语义判断
- 只返回文件名

然后外层代码再根据文件名映射回真正的 memory 文件路径。

---

## 1.5 你担心“会丢大量弱相关记忆”，这个判断对不对？

**对，这个担心是合理的，而且源码设计本身就是明显偏 precision-first，而不是 recall-first。**

我把会造成“缺失”的原因逐条列给你。

### 原因 1：只保留最多 5 个

`findRelevantMemories.ts` system prompt 写明：

- up to 5
- unsure 就不要选
- be selective and discerning

这不是广撒网召回，而是**高置信度少量注入**。

也就是说，它的目标不是“尽量把所有可能相关都拿回来”，而是：

> **只把最可能真的有帮助的极少数 memory 带进上下文。**

### 原因 2：只看文件名 + description，不看正文

Relevant selection 阶段里，Sonnet 看到的是：

- filename
- type
- timestamp
- description

**看不到 memory 正文。**

因此如果：

- 文件名很普通
- description 写得弱
- 真正有价值的信息藏在正文

那它就很可能在选择阶段被错过。

### 原因 3：只扫描前 30 行 frontmatter 区域

`memoryScan.ts`：

- `FRONTMATTER_MAX_LINES = 30`

它只读前 30 行。

因此如果某个 memory 文件的 metadata 不规范，或者重要说明没在前部，就不会进入 manifest。

### 原因 4：最多只扫描最近 200 个 `.md` 文件

`memoryScan.ts`：

- `MAX_MEMORY_FILES = 200`
- 扫描后按 `mtimeMs` 降序排序
- 再 `slice(0, MAX_MEMORY_FILES)`

这意味着：

> **较旧的 memory 文件，可能在进入 LLM 选择之前就已经被截掉了。**

这点很关键，也很容易被忽略。

所以 recall 缺失不只是“LLM 只选 5 个”，而是前面还有一层：

- 老文件可能根本没进入候选池

### 原因 5：prompt 明确要求“不确定就别选”

system prompt 的策略是保守的。

这使得它天然偏向：

- 高 precision
- 低 noise
- 低 recall

换句话说，它宁可漏掉一些边缘相关，也不想把大量可疑 memory 塞给主模型。

---

## 1.6 那为什么源码会故意这样设计？

因为它优化的目标不是“检索完整率”，而是“上下文注入性价比”。

Relevant memory 最终是要进入主模型上下文的。

如果它走高召回，会带来几个问题：

1. **上下文污染**
   - 注入太多弱相关 memory，会稀释主问题

2. **token 成本增加**
   - 每个 memory 正文被读出来后都占上下文

3. **误导风险增加**
   - memory 是可能 stale 的
   - 注入太多，会提高误导主模型的概率

4. **重复信息增加**
   - 很多 memory 可能和当前对话里已读内容重复

所以这条 retrieval 主链明显是：

> **宁可少而准，不求多而全。**

这和经典 RAG 的设计哲学不一样。

经典 RAG 经常是：

- 先高 recall 召回一批
- 再 rerank
- 再压缩

而这里没有那种多阶段粗到细召回，它更像：

- 一次性小规模精挑

---

## 1.7 这是不是意味着 retrieval 的 recall 确实有限？

**是的。**

从源码角度，当前这条链的 recall 局限是非常明确的：

- 仅 `.md`
- 排除 `MEMORY.md`
- 前 30 行 metadata
- 候选最多 200
- LLM 只选最多 5 个
- 还要求高置信

所以如果你从信息检索角度评价它：

### 优点

- 实现轻量
- 无需向量基础设施
- 对 metadata 友好
- 成本低
- 噪声少

### 缺点

- 对 metadata 质量依赖极强
- recall 容易不足
- 对长尾旧记忆不友好
- 无法做正文级 semantic match

因此你的判断“会有很多缺失”是**有代码依据支持的**，并不是误解。

---

## 1.8 这是不是意味着 header/frontmatter 质量极其关键？

**对。**

因为 Relevant retrieval 在 selection 阶段几乎完全依赖：

- `filename`
- `description`
- `type`
- `mtime`

其中真正承载语义浓度的，主要就是：

- 文件名
- `description`

所以如果 durable memory 文件：

- 文件名模糊
- `description` 太泛
- `type` 缺失

那么 manifest 对 Sonnet 来说就是低信息密度的，召回效果会明显下降。

这也是为什么 memory prompt 一直强调：

- Keep the name, description, and type fields up-to-date

这不是装饰字段，而是 retrieval 入口的一部分。

---

## 2. frontmatter 谁写，在哪一步完成？

这是第二个关键问题。

## 2.1 先说结论

frontmatter **不是某个后端自动补全步骤统一生成的**。

从源码看，它主要是通过“模型按 prompt 规范写 markdown 文件”产生的。

也就是说：

- Claude 主模型写 memory 时写 frontmatter
- Extract Memories 子 agent 写 memory 时写 frontmatter
- Auto Dream consolidation 子 agent 写/改 memory 时维持 frontmatter

程序负责的是：

- 告诉模型格式是什么
- 允许它在 memory 目录里写文件
- 后续读取时解析 frontmatter

程序**不负责自动为普通 markdown 文件补 frontmatter**。

---

## 2.2 哪些 prompt 在要求它写 frontmatter？

### 主 memory prompt

`src/memdir/memdir.ts` 和 `src/memdir/teamMemPrompts.ts` 里都嵌入了：

- `MEMORY_FRONTMATTER_EXAMPLE`

格式示例来自 `src/memdir/memoryTypes.ts`：

```md
---
name: {{memory name}}
description: {{one-line description — used to decide relevance in future conversations, so be specific}}
type: {{user, feedback, project, reference}}
---

{{memory content}}
```

所以主模型如果决定“记住这个”，它理论上应按这个格式写。

### Extract Memories prompt

`src/services/extractMemories/prompts.ts`

无论 auto-only 还是 combined 版，都会明确告诉 extraction subagent：

- memory file 用这个 frontmatter format
- 再更新 `MEMORY.md` pointer

### Auto Dream prompt

`src/services/autoDream/consolidationPrompt.ts`

它没有重复粘贴完整 frontmatter 示例，但明确说：

- 使用 system prompt 的 memory file format 和 type conventions

所以 auto dream 同样依赖那套 frontmatter 约定。

---

## 2.3 谁真正“落盘”？

真正落盘的是模型通过工具调用：

- `FileWrite`
- `FileEdit`

完成写入。

因此 frontmatter 的形成链是：

1. prompt 提供 memory file format
2. 模型决定写某个 durable memory
3. 模型输出 Write/Edit tool call
4. 文件落盘
5. 后续 `scanMemoryFiles()` / `parseFrontmatter()` 再读取解析

所以它不是“程序先存 JSON，再渲染 md”，而是：

> **模型直接写 markdown memory 文件，frontmatter 就在那次写文件动作里形成。**

---

## 2.4 如果 `.md` 文件没有 frontmatter，会发生什么？

`parseFrontmatter(...)` 在 `utils/frontmatterParser.ts` 里：

- 如果没有 frontmatter，直接返回：
  - `frontmatter: {}`
  - `content: markdown`

所以：

### 没有 frontmatter 不会报错

系统不会因为一个 memory markdown 没有 frontmatter 就整体崩。

### 但 retrieval metadata 会退化

因为 `memoryScan.ts` 只会拿到：

- `description: null`
- `type: undefined`

于是 `formatMemoryManifest(...)` 生成的 manifest 行会退化成：

```text
- filename.md (timestamp)
```

没有 `type`，也没有 `description`。

这意味着：

- Sonnet 只能靠文件名做选择
- recall 质量通常会明显变差

### 但正文并不是完全不可用

如果模型/用户手动读这个文件正文，内容还是能用。

只是它在 Relevant Memory Retrieval 的“候选筛选阶段”会吃很大亏。

---

## 2.5 如果 durable memory 是 json / jsonl 文件，没有 frontmatter，怎么办？

这点要说得很直接：

> **按当前这条 memory 主链，它们基本不属于标准 durable memory 文件。**

原因很简单，`scanMemoryFiles(...)` 只看：

```ts
f.endsWith('.md') && basename(f) !== 'MEMORY.md'
```

这意味着：

- `.json`
- `.jsonl`
- 其他非 `.md`

**不会进入 Relevant Memory Retrieval 的扫描候选池。**

也不会进入 extraction 的 existing memory manifest。

所以如果你有大量 durable memory 是 `json/jsonl`：

### 对当前 memory 系统来说会怎样？

1. **Relevant retrieval 不会扫到它们**
2. **Extract Memories 不会把它们当作现有 memory 候选来避免重复**
3. **Auto Dream prompt 默认也是围绕 markdown memory files 工作**

换句话说：

> 它们可能是你自己的“外部持久资料”，但不是这套 Claude Code memory pipeline 的一等公民。

### 那 `.md` 没 frontmatter 和 `json/jsonl` 哪个更糟？

- `.md` 没 frontmatter：还能被扫描到，只是 metadata 很差
- `json/jsonl`：连候选池都进不去

所以如果你希望它们参与当前 memory 系统的 retrieval / extraction / dream，最现实的结论是：

- **至少要转成 `.md`**
- 最好带：
  - `name`
  - `description`
  - `type`

否则当前这套源码主链几乎不会好好利用它们。

---

## 2.6 `MEMORY.md` 为什么又没有 frontmatter？

这是容易混淆的一点。

`MEMORY.md` 在 prompt 里被明确规定为：

- **index，不是 memory**
- 每行一个 pointer
- 不要写 frontmatter
- 不要直接在里面写 memory 正文

因此：

- **topic memory files** 才需要 frontmatter
- **`MEMORY.md`** 不需要 frontmatter

Relevant retrieval 也专门把 `MEMORY.md` 排除了。

这说明整个设计是：

- `MEMORY.md` 负责“目录入口”
- topic `.md` 负责“可检索记忆单元”
- frontmatter 只属于后者

---

## 3. Auto Dream 什么时候执行？四个 phase 到底如何落地？

## 3.1 Auto Dream 的触发时机

触发代码在：

- `src/query/stopHooks.ts`

在每个完整 query loop 结束后，主线程会 fire-and-forget：

- `executeAutoDream(stopHookContext, appendSystemMessage)`

但真正执行前，`autoDream.ts` 里还要过多层 gate。

所以准确说法是：

> **Auto Dream 的检查时机是“主线程每轮对话结束后”。真正执行时机取决于 gate 是否通过。**

---

## 3.2 它必须先被初始化

初始化发生在：

- `src/utils/backgroundHousekeeping.ts`
- `initAutoDream()`

也就是说，session 启动后的后台 housekeeping 会注册 auto dream runner。

之后 stop hooks 才能实际调用到有效 runner。

---

## 3.3 哪些 gate 决定它会不会跑？

`autoDream.ts` 的门控顺序非常明确。

### Gate 0: 基础开关

`isGateOpen()`：

- Kairos active -> 不跑
- remote mode -> 不跑
- auto memory disabled -> 不跑
- `isAutoDreamEnabled()` 为 false -> 不跑

其中 `isAutoDreamEnabled()` 在 `config.ts` 中：

- 优先看 settings `autoDreamEnabled`
- 否则看 GrowthBook `tengu_onyx_plover.enabled`

### Gate 1: Time gate

`readLastConsolidatedAt()` 读取 `.consolidate-lock` 的 mtime。

默认配置：

- `minHours = 24`

若距离上次 consolidation 不满 24 小时，则跳过。

### Gate 2: Scan throttle

即使 time gate 过了，也不会每 turn 都扫 transcript。

- `SESSION_SCAN_INTERVAL_MS = 10 min`

如果上次 session-scan 太近，会跳过。

### Gate 3: Session gate

`listSessionsTouchedSince(lastAt)`：

- 列出上次 consolidation 之后被触碰过的 session transcript
- 排除当前 session
- 默认要求至少 `minSessions = 5`

达不到，就不跑。

### Gate 4: Lock gate

`tryAcquireConsolidationLock()`：

- 若别的进程正在 consolidation，则不跑
- 若旧 holder 已 stale，则回收锁

因此 auto dream 是一个非常保守的低频后台维护任务，不是高频 per-turn 提炼。

---

## 3.4 Four-Phase Prompt 是不是代码里的四个阶段？

**不是。**

这是整个问题最关键的一句。

Four-Phase 来自：

- `src/services/autoDream/consolidationPrompt.ts`

它只是构造了一个 prompt 文本：

1. Phase 1 — Orient
2. Phase 2 — Gather recent signal
3. Phase 3 — Consolidate
4. Phase 4 — Prune and index

然后 `autoDream.ts` 做的是：

- `const prompt = buildConsolidationPrompt(...)`
- `runForkedAgent({ promptMessages: [createUserMessage({ content: prompt })], ... })`

也就是说，代码只做了：

- 触发
- 传 prompt
- 约束工具权限
- 观察输出

并没有：

- 一个 phase enum = orient/gather/consolidate/prune
- 明确分阶段函数
- state machine
- 每个 phase 单独 API / 单独工具白名单

所以四阶段**只是 prompt 内的工作指导**。

---

## 3.5 那四个 phase 分别“在哪个阶段被执行”？

如果严格按源码回答：

### 它们都在同一个 forked agent run 里面执行

也就是：

- 一次 `runForkedAgent(...)`
- 同一条 prompt
- 同一个受限工具集
- 模型自己决定先后顺序

所以不存在代码层面的：

- “现在进入 phase 2 函数”
- “phase 3 调另一个模块”

正确理解是：

> 四阶段是模型在一次 dream 子任务中的内部工作顺序建议。

### 更细一点地说

#### Phase 1 — Orient

模型通常会先：

- `ls` memory 目录
- 读 `MEMORY.md`
- skim 现有 topic files

但这只是 prompt 建议，不是强制代码顺序。

#### Phase 2 — Gather recent signal

模型可能会：

- 看 daily logs
- 对 transcript 做窄词 grep
- 看旧 memory 是否 drift

#### Phase 3 — Consolidate

模型通过：

- `FileWrite`
- `FileEdit`

更新 durable memory topic files

#### Phase 4 — Prune and index

模型最后可能：

- 改 `MEMORY.md`
- 删除/收缩过时 index line
- 修正冲突

但 again，这些只是 prompt 驱动的工作流，不是代码状态机。

---

## 3.6 UI 里为什么还会有 phase？

`src/tasks/DreamTask/DreamTask.ts` 很关键，注释写得很清楚：

- `No phase detection`
- dream prompt 有 4-stage structure
- 但代码不解析它
- UI 只在第一次出现 Edit/Write tool_use 时，从 `starting` 翻到 `updating`

也就是说，UI 根本没有去识别：

- 现在是 orient
- 现在是 gather
- 现在是 consolidate
- 现在是 prune

只做了一个非常粗的两态：

- `starting`
- `updating`

这进一步证明：

> Four-Phase Prompt 并不是程序级 phase machine。

---

## 3.7 Auto Dream 和 manual `/dream` 是什么关系？

源码注释表明两者概念上共用同一 dream/consolidation 语义。

你能在这些地方看到证据：

- `autoDream.ts` 顶部注释：`Fires the /dream prompt as a forked subagent`
- `consolidationLock.ts`：`recordConsolidation()` 注释里提到 `manual /dream`
- `DreamTask` 注释和 memory selector UI 里也提到 `/dream`

这说明：

- auto dream 是后台自动触发版本
- `/dream` 是手动触发版本
- 它们围绕同一种 consolidation prompt/workflow 思路

但你这次问的 auto dream，本质上就是后台时机控制 + forked agent 跑 dream prompt。

---

## 3.8 Auto Dream 运行失败或被中止会怎样？

这也值得补一下。

### 失败

`autoDream.ts` catch 分支：

- `failDreamTask(...)`
- `rollbackConsolidationLock(priorMtime)`

### 用户 kill

`DreamTask.kill(...)`：

- abort controller 终止 forked agent
- 标记 task killed
- 同样回滚 consolidation lock

所以四阶段并不是每阶段 checkpoint 持久化，而是整个 dream run 成败靠 lock + task 状态管理。

---

## 4. 把这 3 个问题合起来看，真正的设计哲学是什么？

现在可以把三件事串起来：

### 4.1 Relevant retrieval 依赖 metadata，不依赖正文 semantic index

所以：

- frontmatter 质量决定 retrieval 质量
- manifest 是 frontmatter 的 runtime 压缩目录
- 这条链天然高 precision、低 recall

### 4.2 frontmatter 不是后端自动修复的

所以：

- memory 文件规范性依赖写入方
- 写入方主要是主模型、extract 子模型、dream 子模型
- 不规范文件不会立即报错，但 retrieval 效果会退化

### 4.3 Auto Dream 是“事后整顿者”，不是 schema enforcement engine

所以：

- 它可以帮助整理、修正、合并 memory
- 但它不是一个 deterministic migration job
- 它仍然是 LLM 驱动的 consolidation 行为

也就是说，整个 memory 子系统高度依赖：

- prompt 约束
- 模型执行 discipline
- 文件命名与 description 质量

而不是依赖某个严格 schema compiler。

---

## 5. 最终回答你的三个问题

## 问题 1：manifest 到底是什么？是不是就是 header？纯 LLM 语义选择会不会漏很多？

### 简短回答

- manifest 不是存储，只是运行时把多个 memory 文件 header 摘成一段文本目录
- frontmatter 是单文件 YAML header，manifest 是多文件汇总文本
- 纯 LLM 语义选择确实可能漏掉很多“弱相关但可能有用”的记忆

### 更准确的源码结论

- 候选只来自 `.md` memory files
- 只读取前 30 行 frontmatter 区域
- 候选按 mtime 排序后最多 200 个
- Sonnet 只看 filename + description + type + timestamp
- 只返回最多 5 个
- prompt 明确要求“高置信、宁缺毋滥”

所以这条链的设计目标是：

> **少量高置信 memory 注入**

不是：

> **高召回完整检索**

你的“会缺失很多记忆”的判断，是成立的。

---

## 问题 2：frontmatter 谁写？没有 frontmatter / 是 json/jsonl 怎么办？

### 简短回答

- frontmatter 主要由模型在写 durable memory 文件时写入
- 没有统一后端自动补 frontmatter 的步骤
- `.md` 没 frontmatter 还能被扫到，但 metadata 很弱
- `json/jsonl` 基本不进入这条 memory 主链

### 更准确的源码结论

- 主 memory prompt 提供 frontmatter 模板
- `Extract Memories` prompt 也要求按该格式写
- `Auto Dream` prompt 依赖系统 prompt 里的 memory 格式约定
- `parseFrontmatter()` 对无 frontmatter 文件容错，不报错
- `scanMemoryFiles()` 只扫描 `.md`

所以：

- `.md` 无 frontmatter -> 可用但 retrieval 退化
- `json/jsonl` -> 基本不被 Relevant retrieval / extract manifest 使用

如果你希望这些 durable memory 被当前系统有效利用，最实际的路径是：

- 转成 `.md`
- 补 `name` / `description` / `type` frontmatter

---

## 问题 3：auto dream 什么时候执行？Four-Phase Prompt 四阶段分别在哪里执行？

### 简短回答

- auto dream 在主线程每轮对话结束后的 stop hooks 阶段检查是否触发
- 真正执行还要过 time/session/lock 等门控
- 四阶段不是代码里的四个阶段，而是同一次 forked agent run 里的 prompt 工作指南

### 更准确的源码结论

- 初始化：`backgroundHousekeeping.ts -> initAutoDream()`
- 调用：`query/stopHooks.ts -> executeAutoDream(...)`
- gate：
  - enabled
  - non-remote
  - auto memory on
  - hours since last consolidation >= minHours
  - sessions touched since last consolidation >= minSessions
  - lock available
- 执行：一次 `runForkedAgent(...)`
- Four phases 全部由同一个 forked agent 在同一轮 run 中完成
- UI 不识别四阶段，只粗分 `starting` / `updating`

所以 Four-Phase Prompt 是：

> **LLM 工作计划，不是代码状态机。**

---

## 6. 一句话总总结

如果你把这套设计翻译成人话：

> Claude Code 的 memory 不是“重检索系统”，而是“文件化记忆 + LLM 轻量目录选择 + 后台 LLM 整理维护”。

manifest 是目录页，frontmatter 是每张卡片的题头，auto dream 是夜里整理卡片盒的人。
