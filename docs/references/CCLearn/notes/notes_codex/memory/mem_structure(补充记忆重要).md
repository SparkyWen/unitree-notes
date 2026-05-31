# Claude Code Memory 架构深度解析

> 本文针对你 agent 给出的"Memory 系统四层架构"图做逐条核对，区分**官方真实存在**、**存在但你没触发**、**纯属幻觉**三类；并解释 `~/.claude/projects/<project>/` 下 `subagents/` 和 `tool-results/` 的设计意图。

---

## 0. TL;DR（一句话结论）

你 agent 画的那张图里：
- **Managed / User / Project / Local 四层 CLAUDE.md**：✅ 真实存在，官方文档明确定义。你"找不到"Layer 1 和 Layer 4 不是因为它们不存在，而是**这两个文件不会自动创建**——企业没部署、你自己没写，它们当然就没有。
- **Auto Memory（`~/.claude/projects/<proj>/memory/MEMORY.md`）**：✅ 真实存在，Claude Code v2.1.59+ 的新特性。
- **`team/` 团队共享 memory**：❌ **官方不存在**。Auto Memory 按设计就是 machine-local 的，团队共享走的是 git 提交的 `CLAUDE.md`，不是这个子目录。这是你 agent 的幻觉。
- **Agent Memory**：⚠️ 部分真实。`~/.claude/agent-memory/<agentType>/` 这个 user 级的是真的；`project` 级和 `agent-memory-local` 这两个变体在官方文档里查不到，很可能是 agent 类推出来的。
- **Session Memory `sessionMemory/`**：❌ **官方不存在**。幻觉。
- **`tool-results/` 单独保存**：✅ 你的判断完全正确——就是为了不撑爆 context window，属于"上下文工程"的典型做法。

---

## 1. 真实的 Claude Code Memory 层次

官方文档（`code.claude.com/docs/en/memory`）把 memory 分成**两大系统**：

```
┌─────────────────────────────────────────────────────────┐
│  系统 A：CLAUDE.md 文件（你手写的持久指令）              │
│  系统 B：Auto Memory（Claude 自己写的学习笔记）          │
└─────────────────────────────────────────────────────────┘
        ↓ 会话开始时两套都加载进 context
```

### 1.1 CLAUDE.md 四层加载链（由高到低优先级）

| 层级 | 路径（平台相关） | 作用域 | 版本控制 | 是否自动创建 |
|------|------------------|--------|----------|--------------|
| **Managed / Enterprise** | Linux/WSL: `/etc/claude-code/CLAUDE.md`<br>macOS: `/Library/Application Support/ClaudeCode/CLAUDE.md`<br>Windows: `C:\ProgramData\ClaudeCode\CLAUDE.md` | 整台机器所有用户 | IT 部署 | ❌ 只有组织通过 MDM/脚本部署才有 |
| **User（全局）** | `~/.claude/CLAUDE.md` | 当前用户所有项目 | ❌ 不提交 | ❌ 手动创建 |
| **Project（团队共享）** | `<repo>/CLAUDE.md`（也会递归向上找）<br>`<repo>/.claude/CLAUDE.md` | 项目 | ✅ 提交到 git | `/init` 可生成 |
| **Local（本地私有）** | `<repo>/CLAUDE.local.md` | 项目，但只对你自己 | ❌ .gitignore | ❌ 手动创建（且官方已倾向用 `@import` 替代） |

**回答你的疑问**：

- **Layer 1 `/etc/claude-code/CLAUDE.md` 找不到** → 正常。这个文件是**企业策略文件**，只有公司 IT 给整个组织推了 Claude Code 策略才会存在。个人装的 Claude Code 永远是空的。你不是 enterprise 用户，没有就是没有。
- **Layer 4 `CLAUDE.local.md` 找不到** → 正常。这是**你自己**要在项目根目录手写的一个"个人脚注"文件（比如"我本地的测试 API 走 localhost:3001"），`.gitignore` 掉它不让队友看到。你没写，当然没有。它不是系统自动生成的。

**加载顺序**：Claude Code 从当前工作目录**向上递归**找所有 `CLAUDE.md` 和 `CLAUDE.local.md`，全部合并进 context。冲突时**更具体的层级覆盖更一般的层级**（Local > Project > User > Managed）。但注意官方说明：CLAUDE.md 内容是以 **user message** 的形式在 system prompt 之后注入的，不是 system prompt 本身，所以模型"尽量遵循但不保证严格执行"。

> 补充：`@path/to/file` 的 import 语法支持最多 5 层嵌套，是现在推荐的组织方式，可以替代老的 `CLAUDE.local.md`。

---

### 1.2 Auto Memory（Claude Code v2.1.59+）

这是官方在 2025 年底新加的功能——**Claude 自己给自己写笔记**。

**真实路径**（和你 agent 图里这一部分对上了）：

```
~/.claude/projects/<sanitized-project-path>/memory/
├── MEMORY.md            # 索引入口，短行标签 + 指向详细文件
├── debugging.md         # 按主题切分的详细笔记
├── api-conventions.md
└── ...
```

- `MEMORY.md` 是索引，每行一个短标签（< 150 字符）指向一个详细 md 文件；索引有 **200 行上限**（agent 说的"200行/25KB"——200 行有官方依据，25KB 这个数字我没在官方文档找到，可能是 agent 推测）。
- Claude 不是每次会话都写，它自己判断"这条信息将来会不会有用"再决定记不记。
- 可以用 `/memory` 命令查看/编辑，或用 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` 关掉。
- 所有 worktree 和子目录共享同一个项目的 auto memory 目录。
- `autoMemoryEnabled` 设置**不接受从 `.claude/settings.json`（project 级）写入**——这是个安全设计，防止共享项目偷偷把 auto memory 写到敏感位置。

**关于 `team/` 子目录** —— ❌ **官方文档明确说 Auto Memory 是 machine-local 的**。没有 `team/` 这个共享子目录的设计。团队共享靠的是把 `CLAUDE.md` 提交到 git，不走 auto memory 通道。你 agent 这里大概率是**把 project CLAUDE.md 的团队共享属性错位拼接到 auto memory 路径下**了。

---

### 1.3 Agent Memory（subagent 专属）

官方文档在"Create custom subagents"里提到：创建 subagent 时如果选 **User scope**，会给这个 subagent 分配一个持久 memory 目录：

```
~/.claude/agent-memory/<agentType>/
```

这个 subagent 在多次被调用之间可以把经验写进去累积（比如"这个 codebase 的测试总是用 vitest 不是 jest"）。

**你 agent 图里额外列出的：**
- `.claude/agent-memory/<agentType>/MEMORY.md`（project 级）
- `.claude/agent-memory-local/<agentType>/MEMORY.md`（本地）

这两个**我在官方文档里查不到**。可能：(a) 是更新的文档我没看到；(b) 是 agent 按"既然 CLAUDE.md 有 project/local 三层，agent-memory 大概也有"类推出来的幻觉。**建议把它们当"可能不存在"对待，除非你真在 `.claude/agent-memory/` 下看到了文件。**

---

### 1.4 你图里那个 `sessionMemory/`

❌ **查不到**。官方文档里的 session 概念对应的是 `~/.claude/projects/<proj>/` 下的 `.jsonl` transcript 文件，**不叫 sessionMemory，也没有这个独立子目录**。这一条几乎可以断定是 agent 的幻觉。

---

## 2. 你实际看到的 `projects/<sanitized>/` 目录到底是什么

根据你截图和上传的文件，你看到的是：

```
~/.claude/projects/<sanitized-proj-path>/
├── <sessionId>.jsonl               # 主会话 transcript（每条消息一行 JSON）
├── subagents/
│   ├── agent-<shortId>.jsonl       # subagent 的完整 transcript（isSidechain:true）
│   └── agent-<shortId>_meta.json   # { "agentType": "Explore", "description": "..." }
└── tool-results/
    └── <randomId>.txt              # 被卸载出主 context 的大块工具输出
```

（较新版本的 Claude Code 把 subagent 和 tool-results 单独放进子目录；早期版本是和主 session 的 jsonl 并排放在 projects 根目录下。）

看你上传的 `agent-a4cdbea807df60cf3.jsonl` 第一行就是：

```json
{
  "parentUuid": null,
  "isSidechain": true,       // ← 关键：标记这是 subagent 的旁路会话
  "agentId": "a4cdbea807df60cf3",
  "type": "user",
  "message": { "role": "user", "content": "I need a thorough understanding of the auth system..." },
  ...
}
```

而 `_meta.json` 是 `{"agentType":"Explore","description":"Explore auth codebase structure"}`——这正是你用 Task 工具派出去的一个 **Explore subagent**，任务是扫 auth 代码。

---

## 3. 为什么 `tool-results/` 要单独存？（你的判断完全对）

**是的，就是为了不让 context window 爆炸。** 这是 agent 系统里典型的 **context engineering（上下文工程）** 做法。我用你上传的那份 `bq4xfpia6.txt` 举例说明。

### 3.1 先看那个文件本身

`bq4xfpia6.txt` 是 **1211 行**，内容基本都是这种：

```
E:\Au_notes\5703-capstone\services\auth-server/node_modules/@types/node/assert.d.ts: ...reset calls of the call tracker...
E:\Au_notes\5703-capstone\services\auth-server/node_modules/@types/node/assert.d.ts: ...If a tracked function is passed...
E:\Au_notes\5703-capstone\services\auth-server/node_modules/@cspotcode/source-map-support/source-map-support.js: ...
...×1200 more lines
```

这显然是 subagent 里某一步 **Grep / Glob** 工具的输出——跨整个 `node_modules` 搜了一个关键字，全是噪声。

### 3.2 如果直接塞回主 context 会怎样

一份 1211 行的文件粗估 **15k–30k tokens**。一次工具调用就吃掉 200k context 的 10%+。一个 Explore 型 subagent 动辄跑 10–50 次 Grep/Read/Glob，如果每一次的原始输出都累积在 parent agent 的 context 里：

- 几轮就撑爆 context window
- Prompt cache 也救不了（每次改动都会让后续 cache 失效）
- 每个 token 你都在付钱（input token 计费）
- **模型的注意力被稀释**——1200 行 grep 结果淹没真正重要的业务信息

### 3.3 Claude Code 的应对策略（多层）

**策略 1：subagent 的隔离上下文（最核心）**

官方 Agent SDK 文档原文：

> "Each subagent runs in its own fresh conversation. **Intermediate tool calls and results stay inside the subagent; only its final message returns to the parent.**"

也就是说你派一个 Explore subagent 去扫 auth，它自己开一个独立 context window：
- subagent 内部：跑 50 次 Grep/Read/Glob，吃掉几十万 token——**但这些都在 subagent 自己的 jsonl 里**（就是你看到的 `agent-a4cdbea807df60cf3.jsonl`，84 行）
- 任务做完，subagent 只把**最终的总结消息**（比如："auth 系统用 JWT 双 token 策略，password hash 用 argon2id，数据库表 schema 如下……"）一条消息回传给 parent
- parent 主会话的 context 里只多了**一条 Agent tool result**，几百到几千 token，而不是几十万

这就是 subagent 的第一性用途——**上下文隔离**，不只是并行。

**策略 2：单次工具输出的落盘与引用**

对于不在 subagent 里、直接在主会话中调用的大工具结果，Claude Code 的做法是：

- 原始完整结果 → 写到 `tool-results/<randomId>.txt`（你看到的那个 `bq4xfpia6.txt`）
- 主 transcript（`.jsonl`）里只保留一个**引用**或**截断后的摘要** + 文件路径
- 模型需要细看时，可以用 `Read` / `Bash grep` / `Bash head` 去按需读取指定片段

这就是 Anthropic engineering blog 里讲的：

> "When Claude encounters large files, like logs or user-uploaded files, it will decide which way to load these into its context by using bash scripts like grep and tail. **In essence, the folder and file structure of an agent becomes a form of context engineering.**"

——agent 的**文件系统本身就是它的扩展记忆**，相当于 LLM 的"虚拟内存/交换分区"。主 context 是 RAM（快但小），磁盘上的 tool-results 是 swap（慢但大），要用时按地址取。

**策略 3：Context 压缩（compaction）**

当主 session 的 context 接近满时，Claude Code 会自动做 compaction——把前面的对话压缩成摘要。`PreCompact` hook 允许你在压缩前把当前 `.jsonl` 备份出来，防止重要细节在压缩中丢失。这是上下文管理的最后一道兜底。

### 3.4 一张图概括

```
┌────────────────────── Main Session Context (200k tokens) ──────────────────────┐
│                                                                                 │
│  User: "帮我梳理 auth 流程"                                                     │
│  Assistant: "我派一个 Explore subagent 去扫"                                    │
│  [Task tool call → Explore subagent]                                           │
│         │                                                                       │
│         │  ╔══════ Subagent Context (独立 200k) ══════╗                         │
│         │  ║ Grep → 1211 行结果                       ║                         │
│         │  ║    └─→ 写入 tool-results/bq4xfpia6.txt   ║──┐                     │
│         │  ║ Read routes/auth.ts → 500 行              ║  │ 磁盘               │
│         │  ║    └─→ 内嵌（小，直接带走）               ║  │                     │
│         │  ║ Grep, Read, Grep, Read... × 20            ║  │                     │
│         │  ║ 生成最终总结（~2k tokens）                ║  │                     │
│         │  ╚══════════════════════════════════════════╝  │                     │
│         ▼                                                 │                     │
│  [Agent tool result：只有最终总结 2k tokens]              │                     │
│                                                           │                     │
│  Assistant: "根据 subagent 的发现，auth 流程是..."        │                     │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
                                                            │
                          ~/.claude/projects/<proj>/  ◄─────┘
                            ├── <mainSession>.jsonl
                            ├── subagents/
                            │   ├── agent-a4cd...jsonl   ◄─ 整个 subagent transcript
                            │   └── agent-a4cd..._meta.json
                            └── tool-results/
                                └── bq4xfpia6.txt        ◄─ 1211 行 grep 原始输出
```

**所以你那个问题的答案是**：是的，`tool-results/` 单独保存**就是为了不让 context 冗长**；同时这份原始输出也被保留下来供审计/溯源/重读（你点开 `.jsonl` 里的那条工具调用记录，客户端会给你展示完整结果），但**模型的 context 里只回传了精简版**。这套设计是"context-as-filesystem"的核心思想。

---

## 4. 修正版的 Memory 架构图

基于官方文档，给你画一份**去幻觉**的版本：

```
┌──────────────────────────────────────────────────────────────────┐
│            系统 A：CLAUDE.md（人写的持久指令）                    │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1  Managed      /etc/claude-code/CLAUDE.md (Linux)          │
│                       需企业部署，个人装没有                       │
│ Layer 2  User         ~/.claude/CLAUDE.md                         │
│ Layer 3  Project      <repo>/CLAUDE.md  (提交到 git)              │
│                       <repo>/.claude/CLAUDE.md  也会读            │
│ Layer 4  Local        <repo>/CLAUDE.local.md  (gitignore)         │
│                       已推荐用 @import 语法替代                    │
├──────────────────────────────────────────────────────────────────┤
│            系统 B：Auto Memory（Claude 自己写，v2.1.59+）         │
├──────────────────────────────────────────────────────────────────┤
│ ~/.claude/projects/<sanitized-path>/memory/                       │
│   ├── MEMORY.md        ← 索引，≤200 行                            │
│   ├── debugging.md                                                │
│   ├── api-conventions.md                                          │
│   └── ... 主题文件（Claude 自己决定切分）                          │
│                                                                   │
│ 特性：machine-local；不跨机器同步；团队共享请用系统 A 的 Project  │
├──────────────────────────────────────────────────────────────────┤
│            系统 C：Subagent Memory（可选，user scope subagent）   │
├──────────────────────────────────────────────────────────────────┤
│ ~/.claude/agent-memory/<agentType>/                               │
│   └── 该类型 subagent 跨会话累积的经验                             │
│                                                                   │
│ （project 级 / local 级变体官方文档未明确记载，谨慎对待）          │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│   非 memory 但同目录下的：Session 持久化（不是 memory！）         │
├──────────────────────────────────────────────────────────────────┤
│ ~/.claude/projects/<sanitized-path>/                              │
│   ├── <sessionId>.jsonl           主会话完整 transcript            │
│   ├── subagents/                                                  │
│   │   ├── agent-<shortId>.jsonl   subagent 完整 transcript        │
│   │   └── agent-<shortId>_meta.json                               │
│   └── tool-results/                                               │
│       └── <randomId>.txt          落盘的大块工具输出              │
│                                                                   │
│ 这些是"会话回放 / 审计 / resume"用的，不在下一次 session 开始时    │
│ 自动注入 context。它们和 memory 不是一回事。                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 5. 给你的实操建议

1. **自己建 Layer 4**：在 `5703-capstone/` 根目录创建 `CLAUDE.local.md`，写你个人的东西（比如 Windows 路径怪癖、你本地的 Pinecone key 在哪个 `.env`），`.gitignore` 掉，队友看不到。
2. **用 `/memory` 命令**：在 Claude Code 会话里敲 `/memory` 可以看到**当前实际加载了哪些 CLAUDE.md 文件**——这是最权威的 debug 方法。如果某个文件没出现在列表里，就是没被加载。
3. **用 `claude --version` 检查 Auto Memory 可用性**：需要 v2.1.59+。
4. **想验证 agent 图的真伪**：最直接的办法是 `ls -la ~/.claude/` 和 `ls -la ~/.claude/projects/<你的项目>/`，看磁盘上到底有什么。**磁盘里没有的东西，它再怎么画架构图也不存在**。
5. **对 agent 生成的架构图保持警惕**：你这个 agent 的图犯了一个典型错误——**把"合理的扩展"和"实际存在的设计"混为一谈**。它看到 CLAUDE.md 有 managed/user/project/local 四层，就类推 agent-memory 也该有四层；看到 auto memory 是机器本地的，就脑补一个 team 子目录来补全"团队"这个缺失维度。**类推是 LLM 幻觉最常见的起源之一。**

---

## 6. 参考来源

- Claude Code 官方 memory 文档：`code.claude.com/docs/en/memory`
- Subagent 官方文档：`code.claude.com/docs/en/sub-agents`
- Agent SDK subagent 行为（"intermediate tool calls stay inside"）：`platform.claude.com/docs/en/agent-sdk/subagents`
- Anthropic engineering blog, "Building agents with the Claude Agent SDK"（context-as-filesystem 理念）
- `~/.claude/` 目录结构逆向分析：Sam Keen 的 gist（github.com/samkeen）
- Milvus blog, "Claude Code Memory System Explained"（MEMORY.md 200 行上限等细节）
