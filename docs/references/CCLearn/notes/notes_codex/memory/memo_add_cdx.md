# 关于「大量 json/jsonl 会不会根本没进 retrieval」的源码级解释

> 源码核查路径：`/home/ubuntu/.openclaw/workspace/cc/claude_code/source/src`
>
> 本文重点回答你的核心疑问：
>
> 1. 如果 project 里有很多保存完整 session 的 `json/jsonl`，但 durable memory 的 `.md` 很少，那么 retrieval 是否天然会漏掉大量内容？
> 2. 搜索具体代码文件时，模型到底靠什么找到，显然不是靠 memory manifest，对吗？
> 3. 原始 transcript、durable memory、代码搜索，这三条链到底怎么分工？

---

## 0. 先给最短结论

**你的判断是对的，而且这是这套架构的设计结果，不是偶然。**

### 结论 1
**默认的 memory retrieval 主链，确实只覆盖 durable memory 的 `.md` 文件，不会自动把大量 `json/jsonl` transcript 全部纳入召回。**

源码证据：
- `memdir/memoryScan.ts`
- `memdir/findRelevantMemories.ts`
- `utils/attachments.ts`

这条链只会：
- 扫描 memory 目录下的 `.md`
- 跳过 `MEMORY.md`
- 读取每个 memory 文件前 30 行 frontmatter/header
- 生成 manifest
- 让 Sonnet 选最多 5 个
- 再把这些 `.md` 正文 attach 进当前对话

**它不会自动扫描你那 10~20 个 session `json/jsonl`。**

### 结论 2
**`json/jsonl` transcript 不是“主记忆召回层”，而是“原始历史档案层 / last resort 搜索层”。**

源码证据：
- `memdir/memdir.ts` 的 `buildSearchingPastContextSection(...)`
- `services/autoDream/consolidationPrompt.ts`
- `utils/sessionStorage.ts`

也就是说：
- `.md` memory = distilled / curated / 高信号长期记忆
- `.jsonl` transcript = raw log / 全量历史记录 / 按需 grep 的档案

### 结论 3
**搜索具体代码文件，不走 manifest。**

这完全是另一条链：
- `GlobTool` 按文件名/路径模式找文件
- `GrepTool` 用 ripgrep 按内容搜文件
- `FileReadTool` 读文件
- 必要时 `BashTool` 做只读探索
- REPL/Agent 模式里也内置这些 primitive tools

源码证据：
- `tools/GlobTool/GlobTool.ts`
- `tools/GrepTool/GrepTool.ts`
- `tools/FileReadTool/FileReadTool.ts`
- `tools/REPLTool/primitiveTools.ts`

所以：

> **manifest 只服务 memory `.md` 候选选择，不负责代码文件定位，也不负责 transcript 全库召回。**

---

## 1. 这套系统里其实有 3 个不同层次的“可找回信息”

你可以把它理解成 3 层。

### 第 1 层，Raw transcript 层
这是最原始、最完整的历史记录。

源码里 session transcript 路径在：
- `utils/sessionStorage.ts`
  - `getTranscriptPath()`
  - `getTranscriptPathForSession()`
  - `getAgentTranscriptPath()`

这里明确可以看到：
- 主 session 会写成 `{projectDir}/{sessionId}.jsonl`
- subagent 也有自己的 `agent-xxx.jsonl`

所以 **json/jsonl 是“完整会话存档”**。

它的特点：
- 信息最全
- 粒度最细
- 可能非常大
- 不适合每轮直接塞进上下文
- 默认不会自动全部参与 memory manifest 选择

---

### 第 2 层，Durable memory 层
这是被提炼后的长期记忆。

源码在：
- `memdir/memdir.ts`
- `services/extractMemories/extractMemories.ts`
- `services/extractMemories/prompts.ts`
- `services/autoDream/autoDream.ts`
- `services/autoDream/consolidationPrompt.ts`

其结构是：
- `MEMORY.md`：索引页 / 入口页
- 多个 topic `.md`：真正的 memory 内容
- 每个 topic `.md` 顶部有 frontmatter

它的特点：
- 内容很少，但更高密度
- 强调 durable / future useful
- 强调不是代码库镜像
- 强调不要保存“可从当前代码导出”的东西

`memdir/memoryTypes.ts` 的 `WHAT_NOT_TO_SAVE_SECTION` 非常关键，里面明确写了不要存：
- code patterns
- conventions
- architecture
- file paths
- project structure
- git history
- debugging recipes

这意味着：

> **系统本来就不想把“代码库本身”变成 memory。**

所以你看到 `.md` 少、范围窄，这不是 bug，而是设计目标。

---

### 第 3 层，Query-time search / live exploration 层
当模型真要找“当前仓库里的具体代码文件”或者“某个字符串在哪个文件出现”，它走的是实时搜索工具链，不是 memory。

核心工具：
- `GlobTool`，按路径/文件名模式找文件
- `GrepTool`，按内容搜索，底层就是 ripgrep
- `FileReadTool`，读文件内容
- `BashTool`，只读探索命令

源码证据：
- `tools/GlobTool/GlobTool.ts`
- `tools/GrepTool/GlobTool.ts`（应为 `GrepTool.ts`）
- `tools/GrepTool/GrepTool.ts`
- `tools/FileReadTool/FileReadTool.ts`
- `tools/REPLTool/primitiveTools.ts`

所以如果用户问：
- “`SessionMemory` 在哪？”
- “哪个文件处理 `teamMemory` sync？”
- “谁写 frontmatter？”

模型通常会：
1. 先猜可能的关键词/路径
2. `Glob` 找可疑文件名
3. `Grep` 搜函数名、类型名、字符串常量
4. `Read` 精读命中结果
5. 必要时再继续缩小范围

这条链和 manifest 没关系。

---

## 2. 为什么你会感觉“这会丢大量内容”，而且这个判断是对的

因为源码里这本来就是一个“强压缩 + 高精度”的架构。

---

## 2.1 Relevant Memory Retrieval 只扫 `.md`

`memdir/memoryScan.ts` 里：
- `readdir(memoryDir, { recursive: true })`
- 只保留 `f.endsWith('.md')`
- 且 `basename(f) !== 'MEMORY.md'`
- `FRONTMATTER_MAX_LINES = 30`
- `MAX_MEMORY_FILES = 200`

所以它只处理：
- memory 目录内的 topic markdown
- 最多 200 个
- 只看前 30 行头部信息

**不扫 `json/jsonl`。**

---

## 2.2 Relevant selector 只选最多 5 个

`memdir/findRelevantMemories.ts` 的系统 prompt 明确写：
- up to 5
- only include memories you are certain will be helpful
- unsure 就不要选

所以这条链是明显的：
- **precision-first**
- 不是 recall-first

这意味着：
- 很多弱相关信息不会回来
- 很多正文里有价值、但 description 不够强的 memory 会被漏掉
- 很多没进入 `.md` 的 transcript 内容更不可能被自动召回

所以你说：

> “那不就意味着 retrieval 的时候很多内容根本没被包含？”

**是的，默认主链上就是这样。**

而且从源码看，这不是副作用，而是为了节约 context、避免把长历史全塞进 prompt。

---

## 2.3 Extract Memories 也不是“全量转存 transcript”

`services/extractMemories/prompts.ts` 和 `services/extractMemories/extractMemories.ts` 说明得很清楚。

extract subagent 会：
- 分析最近一段新消息
- 把“值得长期记住”的东西写成 memory 文件
- 强调不要浪费 turn 去查源码、查 git、查额外上下文

prompt 里甚至直接要求：
- 只用最近约 `newMessageCount` 条消息
- 不要去 grep source files
- 不要读代码验证
- 优先更新已有 memory，避免重复

这说明它不是做：
- 全 transcript ingestion
- 全量语义压缩
- session -> memory 的完整镜像

它做的是：

> **从最近消息里抽取一小部分“值得长期保存”的事实。**

所以 raw transcript 和 durable memory 之间本来就是 **many-to-very-few** 的关系。

---

## 2.4 Auto Dream 也不是“全量重建所有 session”

`services/autoDream/consolidationPrompt.ts` 也很直白：

在 Phase 2 里，transcript search 被放在优先级 3，而且写明：
- 仅在需要特定上下文时才 grep JSONL
- narrow search
- 不要 exhaustively read transcripts

原文语义就是：
- transcript 很大
- 只能窄搜
- 只查你已经怀疑重要的东西

所以 Auto Dream 也不是：
- 把所有历史 session 全量吃一遍
- 然后构建完整知识库

而是：

> **以 memory/log 为主，transcript 为补充证据源。**

这再次证明：
- `json/jsonl` 是原始历史档案
- `.md` 才是被沉淀过的 durable layer

---

## 3. 那么，默认 retrieval 到底会不会遗漏大量 json/jsonl 内容？

### 答案：会，而且是结构性遗漏。

更准确地说：

#### 会自动进入主 retrieval 的内容
- `MEMORY.md` 索引（某些模式下注入 system prompt）
- 被 `findRelevantMemories(...)` 选中的 topic `.md`
- 当前对话中已 attach / 已 read 的文件

#### 不会自动进入主 retrieval 的内容
- 项目里的大多数 `json/jsonl` transcript
- 你自己额外放进项目里的普通 `json/jsonl` 文件
- 当前代码仓库的大部分源码文件
- 只存在于历史对话里、但没有被提炼进 `.md` 的细节

所以如果你的项目状态是：
- 10~20 个完整 session json/jsonl
- 只有 1 个或少量 `.md`

那么默认情况下：

> **memory retrieval 主要看到的是那几个 `.md`，不是那 10~20 个 transcript。**

你的理解完全正确。

---

## 4. 那这些没进 `.md` 的 transcript 内容，什么时候才会被用上？

它们不是“没法用”，而是 **不会自动上桌，只会按需检索**。

这里有两种情况。

---

## 4.1 场景 A，找的是“历史会话里说过什么”

这时走的是 transcript 搜索链，不是 manifest。

`memdir/memdir.ts` 的 `buildSearchingPastContextSection(...)` 明确告诉模型：

1. 先搜 memory 目录 `.md`
2. session transcript logs 是 last resort
3. 对 transcript 用窄关键词搜索：
   - error message
   - file path
   - function name

而且给了具体搜索形式：
- `grep -rn "<search term>" ${projectDir}/ --include="*.jsonl"`
- 或 `Grep` tool 配 `glob="*.jsonl"`

这说明：

> **当某条历史事实只存在于 json/jsonl 而不在 `.md` 里时，模型必须显式去 grep transcript，才能找回来。**

换句话说：
- 不是自动 recall
- 是按需 archival search

---

## 4.2 场景 B，找的是“当前仓库里的代码文件 / 实现位置”

这时根本不是 memory 问题，而是 live code search。

会走：
- `GlobTool`，找名字、目录模式
- `GrepTool`，找类名、函数名、字符串、注释、字段
- `FileReadTool`，读命中的文件

源码证据：
- `GlobTool` 描述里明确说，用于按 pattern 找文件
- `GrepTool` 描述里明确说，built on ripgrep，用于 search tasks
- `FileReadTool` 用于直接读文件
- `REPLTool/primitiveTools.ts` 把这些工具都列成基础原语

所以如果你要找某个代码文件：
- 它不需要先被写入 `.md`
- 也不需要进 manifest
- 只要它还在当前 workspace/代码树里，模型就可以靠搜索工具现场找到

因此：

> **“找历史记忆” 和 “找当前代码实现” 是两套完全不同的检索路径。**

---

## 5. 你提到的“具体代码文件不是 .md，那模型如何精确找到？”的真正答案

我把这个问题拆成两个版本，因为这两种很容易被混在一起。

---

### 版本 1，你想找“当前代码仓库里的某个实现文件”

例如：
- `findRelevantMemories` 的定义在哪
- `teamMemorySync` 的 watcher 在哪
- `SessionMemory` 哪个文件维护

这时：
- **不走 manifest**
- **不走 durable memory recall**
- 而是走 `Glob/Grep/Read` 实时搜索

这是“代码搜索”，不是“记忆召回”。

---

### 版本 2，你想找“过去某次 session 里提到过某个代码文件”

例如：
- 上周某次对话里提到过 `foo/bar/baz.ts`
- 但这个路径没有被写进 durable memory `.md`
- 当前用户又问“之前我们讨论过哪个文件？”

这时：
- manifest 也帮不上忙
- `.md` recall 也帮不上忙
- 必须去 grep `.jsonl` transcript

也就是说：

> **如果一个代码路径只存在于历史 transcript，没被提炼成 `.md`，它就不在默认 memory recall 主链里。**

这正是你担心的那个点。

---

## 6. 这套设计为什么要这样做？

因为源码明显在做一个权衡：

### 目标不是“最大召回”
而是：
- 避免上下文爆炸
- 避免把历史噪音都塞回来
- 把长期有价值的、非代码型事实提炼成小而稳的 memory
- 代码和 transcript 则按需搜索

所以它是三段式架构：

1. **Raw logs/transcripts** 保真保存
2. **Durable memory** 高压缩沉淀
3. **Live search** 针对当前问题现场定位

这和经典“把所有东西 embedding 进一个统一向量库然后 hybrid 检索”很不一样。

它更像：
- 持久记忆是 curated notes
- 历史 transcript 是 cold archive
- 代码库是 live source of truth

---

## 7. 这意味着什么，尤其对你这种“json/jsonl 很多”的项目

这意味着几个非常现实的结论。

### 7.1 如果历史细节没有被提炼到 `.md`，默认回忆时就是可能看不到
对。

尤其这些内容最容易漏：
- 某次 session 里的一次性讨论
- 具体代码路径
- 某段错误日志
- 某次临时实验过程
- 只出现过一次、没被抽取器判定为 durable 的信息

---

### 7.2 如果你希望“历史 session 内容更容易被找回”，只靠当前 manifest 机制不够
对。

因为 manifest 机制的输入就是 `.md` topic memory，不是 transcript 全量库。

---

### 7.3 当前架构里，`json/jsonl` 更像“需要时再查的历史档案”
对。

这也是为什么 prompt 里反复强调：
- grep transcript narrowly
- last resort
- 不要全读

---

### 7.4 当前架构里，代码文件定位依赖搜索工具，不依赖 memory
也对。

这恰恰解释了为什么系统可以在 `.md` 很少的情况下，仍然比较准地定位当前代码文件：
- 因为它不是靠 memory 找代码
- 它是靠 live search 找代码

---

## 8. 你现在这个问题，最精确的一句话总结

> **是的，这套源码里 durable memory `.md` 只是“提炼后的长期记忆层”，并不覆盖大多数 raw `json/jsonl` session 内容。默认的 relevant memory retrieval 主链不会自动把那些 transcript 纳入召回。对于历史 transcript 中的具体细节，需要模型显式去 grep `.jsonl`；对于当前仓库中的具体代码文件，则依赖 `Glob/Grep/Read` 这条实时搜索链，而不是 manifest。**

---

## 9. 从源码角度看，你这次疑问的最终回答

### 你的问题 1
**“我有很多 json/jsonl，只有少量 .md，这是不是意味着 retrieval 时很多内容根本没包含？”**

答：**是。默认主链上就是如此。**

---

### 你的问题 2
**“尤其我要搜具体代码文件时，又不是 .md，模型到底怎么精确找到？”**

答：**不是靠 manifest，而是靠 `Glob/Grep/Read` 等实时代码搜索工具链。**

---

### 你的问题 3
**“这明显不是通过 manifest 找到的吧？”**

答：**完全正确。manifest 只服务 memory `.md` 候选选择，不服务代码文件定位，也不服务 transcript 全库自动召回。**

---

## 10. 我认为最值得你记住的架构图

### 路径 A，Durable memory recall
用户 query
→ `scanMemoryFiles()` 扫 `.md` frontmatter
→ `formatMemoryManifest()`
→ `findRelevantMemories()` 调 Sonnet 选最多 5 个
→ `attachments.ts` 读取这些 `.md`
→ 注入当前对话

### 路径 B，历史 transcript 查找
用户 query 暗示“过去某次聊过/报过/提过”
→ 模型判断 durable memory 不够
→ `Grep` / `grep` 对 `*.jsonl` 窄搜
→ 命中后再读附近内容

### 路径 C，当前代码文件定位
用户 query 指向当前代码实现
→ `Glob` 找文件名/目录
→ `Grep` 找类名/函数名/字符串
→ `Read` 精读文件
→ 得出答案

这三条链不要混。

---

## 11. 最后一句非常直白的话

如果你的目标是：

> “我希望 10~20 个 session 里的大量历史内容都能像 RAG 一样稳定被召回”

那么根据当前源码，**答案是不是。**

当前实现更接近：
- `.md` 记忆做高信号长期沉淀
- `.jsonl` 当原始档案，必要时再 grep
- 代码靠实时搜索，不靠记忆

也就是说，它不是“全量历史统一检索库”，而是“分层持久化 + 按需搜索”的设计。
