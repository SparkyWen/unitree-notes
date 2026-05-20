# Memory ≠ 历史全文 ≠ 代码搜索：Claude Code 三层检索架构辨析

> 针对用户的核心疑问：
> - JSONL session 文件很多（10–20 个），但 .md memory 文件极少，retrieval 不就丢失大量内容吗？
> - 搜索具体代码文件（.ts/.py 等）时，明显不是 .md，模型如何精确找到？

**结论先行**：Memory retrieval **从来就不是**"对所有历史和项目内容的全量检索"。它只是 Claude Code 三大独立检索机制之一。三个机制各管一块，互不替代：

| 目标对象 | 用什么机制检索 | 是否经过 Manifest / Sonnet 选择？ |
|---------|---------------|----------------------------------|
| `.md` memory 文件 | `findRelevantMemories`（Sonnet + manifest） | ✅ 是 |
| 项目源码文件 (.ts/.py/.go...) | 主模型调用 Grep / Glob / Read 工具 | ❌ 否，**完全独立** |
| JSONL session transcripts | 只在 Auto Dream 阶段由模型 `grep` 主动搜 | ❌ 否 |

所以你的直觉**完全正确**：memory retrieval 视野是窄的、curated 的，它根本没想覆盖所有历史和代码。系统的设计是：**memory 负责结论，Grep/Glob/Read 负责原始数据**。

---

## 一、JSONL session transcripts 的真实角色

### 1.1 存储位置与格式

每个会话都会持续落盘到 JSONL：

- 路径：`~/.claude/projects/<sanitized-project-slug>/<sessionId>.jsonl`
- 格式：每行一个 JSON 对象（user / assistant / attachment / system / progress / summary / ...）
- 写入：**逐条追加**（`sessionStorage.ts:1128-1265`），通过 `enqueueWrite` 异步队列
- 去重：内存 `messageSet` 记录 UUID，避免重复
- 子代理：sidechain 写到独立的 `agent-<agentId>.jsonl`
- 上限：`MAX_TRANSCRIPT_READ_BYTES = 50 * 1024 * 1024`（50MB，防 OOM）

### 1.2 JSONL **不参与** relevant memory retrieval

这是一个 hard constraint，直接来自源码：

```typescript
// memdir/memoryScan.ts:41-43
const mdFiles = entries.filter(
  f => f.endsWith('.md') && basename(f) !== 'MEMORY.md',
)
```

- `scanMemoryFiles` 只扫 `.md`；`.jsonl` 完全被忽略
- `findRelevantMemories` 只把 `.md` 的 frontmatter description 放进 manifest 给 Sonnet
- Sonnet 的 system prompt 中**根本没提到 transcripts**

**结论**：你的 10-20 个 JSONL 文件里的对话全文，在新 session 的每 turn retrieval 中**零覆盖**。

### 1.3 JSONL 的三个真实用途

#### 用途 1：`/resume` 时重建上下文

- `sessionRestore.ts` 调用 `readTranscriptForLoad(filePath, fileSize)`
- 分块读取（8MB 缓冲区 + 256KB 分块）
- 过滤 progress 消息（不进主消息链）
- 恢复：messages、file history snapshots、attribution、TODO 列表、context-collapse 边界
- 超 50MB 的 JSONL **无法加载**

#### 用途 2：Auto Dream Phase 2 做窄 grep

这是 JSONL **被主动读取的唯一入口**（`consolidationPrompt.ts:22-40`）：

```
Session transcripts: `${transcriptDir}` (large JSONL files — grep narrowly, don't read whole files)
...
grep -rn "<narrow term>" ${transcriptDir}/ --include="*.jsonl" | tail -50
```

- `transcriptDir` = `getProjectDir(getOriginalCwd())`（autoDream.ts:212）
- 由 forked agent **自己执行** bash grep（受 `createAutoMemCanUseTool` 权限约束，仅 read-only bash）
- 结果 ≤ 50 行（`tail -50`）
- 模型看到的是**原始 JSONL 匹配行 + 行号**，自己解读

**核心点**：不是系统把 JSONL 预处理后灌给模型，而是**模型主动带着具体关键词去 grep**，然后把有价值的内容整合成新的 `.md` memory。(==比如说我提问了agent去搜索了， 就会生成.md文档是这个意思吗？==)

解释：

```
谁在 grep？什么时候 grep？
首先要分清两个完全不同的"agent":
主对话 agent (您正在交互的那个 Claude)

您提问 → 它回答 → 它可能调用 grep 搜代码、Read 看文件 —— 但它不会去 grep ~/.claude/projects/.../*.jsonl
它读的是您的项目代码,不读历史 transcript

Auto Dream agent (一个独立 fork 出来的后台 agent)

它是被 Claude Code 主动 fork 出来的另一个独立 Claude 实例
触发时机:session 结束、idle、或满足某些 stopHook 条件 (不是您每次提问都触发)
它拿到的 system prompt 就是您贴的 consolidationPrompt.ts 里那段——告诉它"transcript 在这个目录,你自己用 grep 去翻,然后蒸馏出 memory"
它有受限权限 (createAutoMemCanUseTool),只能用 read-only bash,不能写您的项目文件,但可以写 memdir 里的 .md

所以 grep JSONL 这个动作,不是您主动触发的搜索,而是后台 consolidation agent 在做"消化前一段对话"的工作。
那 .md 是什么时候、怎么生成的?
整个流程大致是:
您和主 Claude 聊天
    ↓
对话不断 append 到 sessionId.jsonl
    ↓
session 结束 / idle / 触发条件满足
    ↓
Claude Code fork 出 Auto Dream agent  ← 自动的,您看不到
    ↓
这个 agent 拿到 consolidationPrompt
    ↓
它自己决定要 grep 什么关键词 (Phase 2)
    ↓
读到 ≤50 行 jsonl 匹配
    ↓
它判断"这段值得做成长期 memory 吗?"
    ↓
是 → 写一个新的 .md 到 memdir / 更新已有 .md
否 → 丢弃,什么都不做
所以"生成 .md"是自动的,但不是每次都生成——Auto Dream agent 自己有判断:大量琐碎的对话 (改个 typo、问个无关问题) 不会沉淀成 memory,只有它认为有长期价值的模式/决定/约定才会写出来。
您说"我提问了 agent 去搜索就生成 .md"为什么不准确?
把这句话拆成三块,逐一对照:
您的理解实际情况"我提问触发的"✗ 是 session 生命周期事件触发的 (结束/idle/hook),与您单次提问没有直接因果"agent 去搜索"⚠️ 是 Auto Dream agent (不是主对话 agent) 去 grep transcript"就会生成 .md"⚠️ 不一定。agent 自己有蒸馏判断,大部分内容会被丢弃
更准确的说法应该是:"在某些时机,Claude Code 会自动派一个后台小 Claude 去翻最近的对话日志,如果它觉得有什么值得长期记住的,就写成 .md 放进 memdir。"
一个具体例子
假设您今天和 Claude Code 工作了 3 小时,内容包括:

修了 5 个 typo
讨论并最终决定 "这个项目里所有 API 路由都用 kebab-case"
调试了一个 Prisma 的奇怪报错,最后发现是 schema 没 regenerate
闲聊了几句天气

session 结束后 Auto Dream 触发,它 grep transcript,然后大概率会:

✓ 把 #2 写成或追加到一个 .md (这是项目约定,长期有价值)
✓ 把 #3 写成 .md (是一个值得记住的踩坑) —— 类似您之前提到的 "Prisma 迁移前必须先跑 generate"
✗ 忽略 #1 和 #4 (无长期价值)

所以您下次新开 session,MEMORY.md 或 findRelevantMemories 可能就把这两条带回来了——但整个过程您看不到、也不需要操心,是真正的"自动消化"。
为什么用 grep + tail -50 而不是把整个 jsonl 喂给模型?
这呼应了您之前问过的"为什么不用 RAG"那个问题:

jsonl 文件可能非常大 (几十 MB),整个塞进 context 既贵又会爆
agent 自己最清楚"我现在在找什么"——它知道自己想 distill 哪个主题,所以让它主动选关键词比预先索引更精准
tail -50 是粗暴但有效的截断:防止某个关键词命中太多导致 context 爆掉
这和主对话里 Claude 用 grep 搜代码是同一种哲学:LLM 当指挥,传统工具干活,只看精筛后的少量内容

一句话总结
.md 不是"您搜一次就生成一个",而是 Claude Code 在 session 结束/idle 这种时机自动 fork 一个后台 agent,让它自己拿着 grep 去翻 jsonl 历史,挑出真正值得长期记住的内容蒸馏成 .md。整个过程对您是透明的——您看到的"少部分对话变成了 memory .md",就是这个 Auto Dream 流水线的可见输出。
```



#### 用途 3：在线 session 内的 transcript 读取（已在内存）

当前 session 的对话历史本身就以 `Message[]` 的形式活在进程内存里，query loop 直接用内存，不经过 JSONL。JSONL 是持久化副本，不是 hot path。

### 1.4 为什么 .md 少而 JSONL 多是正常的

- JSONL = 完整原始对话（包括临时讨论、tool call 输出、一次性 debug 过程）
- `.md` memory = **经过两次抽取过滤**的精华：
  1. `extractMemories`（每 turn）只抽"值得长期记忆"的内容
  2. `memoryTypes.ts:183-195` 明确列出**不**存的内容：代码模式、架构、文件路径、git 历史、调试 recipe、临时任务状态

一次 3 小时调试 session 可能生成 2MB JSONL，但只产生 1–2 个 `.md` memory（比如"这个 repo 的 test 不能 mock DB"），这是**刻意的**。

---

## 二、代码文件如何被精确找到？（Grep / Glob / Read）

### 2.1 三件套工具底层

| 工具 | 底层实现 | 搜索对象 | 关键文件 |
|------|---------|---------|---------|
| Grep | **ripgrep**（C++） | 文件内容正则 | `tools/GrepTool/GrepTool.ts:21` import |
| Glob | Node `glob` | 文件名模式 | `tools/GlobTool/GlobTool.ts:11` |
| Read | `fs/promises.readFile` | 指定路径文件 | `tools/FileReadTool/` |

ripgrep 配置（`utils/ripgrep.ts:30-64`）：三种模式 `system` / `builtin`（vendored）/ `embedded`（bun 内嵌二进制）。

### 2.2 典型工作流：修复 foo.ts 里的 bug

没有 embedding、没有向量库、没有 semantic index。主模型自己按 prompt 指引走：

```
用户："修复 foo.ts 里的 bug"
    ↓
主模型自主决策：
    ↓
[1] Glob("**/foo.ts")            → 定位文件路径
[2] Read("src/.../foo.ts")        → 加载全文到上下文
[3] Grep("bug.*pattern")          → （可选）大文件时窄搜索关键行
[4] Edit / Write                  → 应用修复
```

**pattern 是模型自己写的**。源码里没有"pattern 生成器 helper"，schema 只给模型说明：

```typescript
// GrepTool input schema (GrepTool.ts:35-39)
pattern: z.string().describe('The regular expression pattern to search for in file contents')
// GlobTool input schema (GlobTool.ts:28)
pattern: z.string().describe('The glob pattern to match files against')
```

### 2.3 system prompt 对工具选择的硬编码指引

`constants/prompts.ts:174-250` 有明确规则：

> In general, do not propose changes to code you haven't read. If a user asks about or wants you to modify a file, read it first.
>
> Do not create files unless absolutely necessary.

Explore subagent 的 prompt（`exploreAgent.ts:12-56`）也直白：

> Use **Glob** for broad file pattern matching.
> Use **Grep** for searching file contents with regex.
> Use **Read** when you know the specific file path.
> Make efficient use of the tools... spawn multiple parallel tool calls.

**这不是 memory 系统的工作**。这是主模型常规 tool calling。

### 2.4 有没有向量索引 / 语义搜索？

**没有。** 全目录 grep `embedding` / `vector` / `codebaseIndex` / `semanticSearch` 都零命中。

唯一的"语义级"搜索来自 **LSP**（`tools/LSPTool/`）：
- `goToDefinition` / `findReferences` / `hover` / `documentSymbol` / `workspaceSymbol`
- 这是**语言服务器**提供的符号级查询（TypeScript / Python / Go 等），不是向量相似度
- 需要对应语言的 LSP server 已配置

`utils/codeIndexing.ts` 里的 `detectCodeIndexingFromCommand()` 只是用来**识别**用户是否启用第三方工具（如 Sourcegraph），Claude Code 自己**不维护**代码索引。

### 2.5 启动时加载了什么？

`context.ts:154-188`（`getUserContext`）+ `115-149`（`getSystemContext`）：
- **CLAUDE.md**：有就读（`filterInjectedMemoryFiles(await getMemoryFiles())`）
- **git status**：当前分支、main、最近 5 个 commit（`CLAUDE_CODE_REMOTE` 模式下跳过）
- **MEMORY.md**：通过 `loadMemoryPrompt()` 注入 system prompt

**不扫整个代码树**、不做文件树枚举、不做索引。

---

## ==三、三层机制的完整分工图==

```
┌──────────────────────────────────────────────────────────────────┐
│                       用户输入 / 新 turn                          │
└───────────────────────────────┬──────────────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Memory 系统      │    │ 主模型 tool call │    │ CLAUDE.md +      │
│ (.md only)      │    │ (codebase)      │    │ system context   │
│                 │    │                 │    │                 │
│ 被动后台预取    │    │ 主动按需使用    │    │ 启动时加载      │
│                 │    │                 │    │                 │
│ scanMemoryFiles │    │ Grep (ripgrep)  │    │ CLAUDE.md       │
│ formatManifest  │    │ Glob (node)     │    │ git status      │
│ sideQuery Sonnet│    │ Read (fs)       │    │ MEMORY.md       │
│ readForSurfacing│    │ LSPTool         │    │ recent commits  │
│                 │    │ (subagents)     │    │                 │
│ 上限: 20KB/turn │    │ 上限: 主模型    │    │ 上限: 一次性    │
│ 60KB/session    │    │ context quota   │    │ 注入 prompt     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                ▼
                         主模型上下文

                    额外的"离线通道":
                    ┌──────────────────────┐
                    │ Auto Dream (24h 触发) │
                    │                      │
                    │ forked agent grep    │
                    │ JSONL transcripts    │
                    │ 把信号整合回 .md     │
                    └──────────────────────┘
```

### 三层分别解决的问题

1. **Memory (.md)**：*"上次我学到过什么结论？"* — 回答语义性、跨会话的偏好与事实
2. **Grep/Glob/Read**：*"当前代码库里的事实是什么？"* — 回答结构性、可验证的代码真相
3. **CLAUDE.md + git**：*"这个 repo 的规则和近况是什么？"* — 启动时一次性注入的静态规则

它们是**互补**的，不是替代关系。

---

## 四、所以"为什么 .md 少 JSONL 多"不是 bug 而是特性

### 4.1 设计哲学

- **JSONL** 是原始物料（raw）
- **.md** 是经过提炼的结论（insight）
- **Grep/Glob** 是对代码现场的直接读取

如果每个 JSONL 都机械地转成一堆 `.md`：
- MEMORY.md 会在几天内突破 200 行/25KB 上限
- manifest 会臃肿到几百个文件，Sonnet 的选择噪声上升
- 大量调试过程、失败尝试会污染"精华"层

所以 `extractMemories` prompt 的规则（`memoryTypes.ts:183-195`）明确**禁止**存：
- 代码模式、架构、文件路径 → 读代码库就能拿到
- Git 历史 → `git log` / `git blame` 权威
- 调试配方 → commit message 已有上下文
- 临时任务状态

### 4.2 这就是为什么你看到：

> 10-20 个 JSONL，但可能只有 1 个 `.md`

这很正常。意味着这些 session 讨论的多是：
- 具体代码修改（信息在代码里，不必 memory）
- 一次性调试（信息在 git log / commit message 里）
- 临时方案（不值得长期持有）

而你**真正能写成 memory** 的东西（"这个项目禁止 mock DB"、"API deadline 是 3/5"）可能本来就稀少。

---

## 五、实用建议：让更多历史内容可用

### 5.1 如果你希望 memory retrieval 看到更多历史知识

**手动触发 Auto Dream**：在任意时刻执行 `/dream` 命令（如果可用）强制让模型 grep JSONL → 提炼新的 `.md`。

**在对话中显式请求保存**：
- "请记住：这个项目的 X 规则是 Y"
- 主模型会按 system prompt 指引，用 Write tool 写成带 frontmatter 的 `.md`

**把 auto dream 开关打开**：
- `settings.json` 里 `autoDreamEnabled: true`
- 或等 `tengu_onyx_plover` feature gate 打开
- 24 小时 + 5 个新 session 后自动触发

### 5.2 如果你希望精确检索代码

不要靠 memory，直接在对话中让主模型：
- 用 Grep 搜关键词
- 用 Glob 定位文件
- 用 Read 读具体实现

或者在一开始就把重要路径告诉模型（把它当作 context hint）。

### 5.3 如果你希望重用过往 session 的对话

- `/resume` 回到之前的 session（受 50MB 上限）
- 跨 session 的**具体对话内容**不会自动出现在新 session 里 —— 这是刻意的边界

### 5.4 如果你希望让 JSONL 转成可搜索的知识

最可靠的做法：
- 在每次有价值讨论结束时显式说 "记住 X"，让模型主动存成 `.md`
- 或手动写 `.md` 文件到 memory 目录（带 frontmatter，否则 Sonnet 很难选中）

---

## 六、关键事实速查

| 断言 | 真伪 |
|------|-----|
| Memory retrieval 覆盖 JSONL 历史 | ❌ 假 |
| Memory retrieval 覆盖项目代码 | ❌ 假 |
| 代码文件通过 Grep/Glob 工具找到 | ✅ 真 |
| 代码搜索有 embedding 或向量索引 | ❌ 假（只有 ripgrep + Node glob + LSP 符号） |
| Search pattern 由 LLM 生成 | ✅ 真（主模型自主写 regex / glob） |
| JSONL 被预索引到 memory 中 | ❌ 假 |
| Auto Dream 阶段会 grep JSONL | ✅ 真（唯一入口） |
| 10 个 JSONL 对 1 个 .md 算异常 | ❌ 假（预期的精炼比） |
| `.md` 文件是 JSONL 内容的全量备份 | ❌ 假（是精选结论） |
| `/resume` 能把旧 session 内容带到新 session | ✅ 真（但只在 resume 同一 session 时） |

---

## 七、核心代码引用

| 机制 | 关键文件 | 行号 |
|------|---------|------|
| Memory 只扫 .md | `memdir/memoryScan.ts` | 41-43 |
| 不存储代码/路径/git | `memdir/memoryTypes.ts` | 183-195 |
| JSONL 路径与格式 | `sessionStorage.ts` | 204, 1128-1265 |
| 50MB 读取上限 | `sessionStorage.ts` | 228-229 |
| /resume 分块读取 | `sessionStoragePortable.ts` | 717-793 |
| Auto Dream 读 JSONL | `services/autoDream/consolidationPrompt.ts` | 22-40 |
| transcriptDir 定义 | `services/autoDream/autoDream.ts` | 212 |
| Auto Dream 工具权限 | `services/extractMemories/extractMemories.ts` | 171-220 |
| Grep 用 ripgrep | `tools/GrepTool/GrepTool.ts` | 21 |
| Glob 用 Node glob | `tools/GlobTool/GlobTool.ts` | 11 |
| Explore subagent 只读 | `agents/exploreAgent.ts` | 63-82 |
| LSP 符号查询 | `tools/LSPTool/` | — |
| CLAUDE.md 加载 | `context.ts` | 154-188 |
| git status 加载 | `context.ts` | 115-149 |
| 工具使用指引 | `constants/prompts.ts` | 174-250 |

---

## 八、最终回答你的两个疑问

**Q1：10-20 个 JSONL 只有 1 个 .md，retrieval 时内容不是都"看不见"了吗？**

**是的，JSONL 内容在 retrieval 时确实看不见** —— 但这不是 bug。Memory 系统本来就不负责覆盖历史全文。它只存"跨会话值得长期记住的精华"，其余的：
- 代码相关 → 用 Grep/Glob/Read 即时读
- 历史 JSONL → 靠 Auto Dream 提炼，或 `/resume` 回到原 session
- Git 历史 → `git log` / `git blame`

**Q2：搜索具体 .ts / .py 等代码文件时，既然不是 .md，模型如何精确找到？**

**通过主模型自主调用 Grep / Glob / Read 工具。**
- 没有 manifest、没有 Sonnet 预选、没有 embedding
- pattern 完全由主模型根据上下文和工具 schema 自己生成
- 底层 Grep 走 ripgrep，Glob 走 Node glob
- LSP 可提供符号级（非向量）语义查询

这两条通道**完全独立**，一条处理"人给的结论"，一条处理"代码的事实"。理解这一点，你就能看清整个检索架构的边界了。
