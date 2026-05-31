# Claude Code 子功能架构图 06：Memory / Attachment / Session 恢复层

- 仓库路径：`cc/claude_code`
- 对应总图文档：`cc/cc_learn/12_overall_architecture_framework.md`
- 对应主循环文档：`cc/cc_learn/16_arch_query_loop_framework.md`
- 当前主题：**Memory / Attachment / Session 恢复层（SessionMemory / Attachments / Transcript Persistence / Resume / Auto-Memory / Relevant Memory Prefetch）**
- 当前目标：
  1. 画出这个功能块的完整子架构图
  2. 给出该功能块涉及文件的相对路径索引
  3. 对这个功能块**所有涉及文件**总结作用

---

## 1. 这个功能块到底负责什么

Claude Code 之所以能像一个“持续运行的 agent”，并不是因为 `query.ts` 自己记得一切。

真正支撑长会话能力的，是这一层：

- 会话 transcript 持久化
- resume / continue / sidechain transcript 恢复
- compact 后的历史恢复与链修复
- attachment messages 注入
- SessionMemory 服务
- auto-memory 目录、路径与安全边界
- relevant memory 搜索与注入
- team memory / nested memory / daily memory 等存储路径语义

一句话：

> **这是 Claude Code 的“长期会话底座”和“恢复中间层”。**

如果没有这一层，系统会变成：
- 一重启就严重失忆
- 历史恢复不完整
- compact 后容易断链
- 工具副作用无法稳定回灌下一轮
- memory 相关能力只剩 prompt 里的临时文字，而不是可持久化的数据结构

---

## 2. 这个功能块的总架构图（静态结构图）

```text
Memory / Attachment / Session 恢复层
├── A. Transcript 持久化与恢复层
│   ├── source/src/utils/sessionStorage.ts
│   └── source/src/utils/sessionStoragePortable.ts
│       - append-only transcript
│       - session metadata
│       - resume / continue / hydrate
│       - subagent / sidechain transcripts
│
├── B. Attachment 注入层
│   └── source/src/utils/attachments.ts
│       - file / plan / memory / delta attachments
│       - post-tool / post-compact / post-memory injection
│
├── C. Message 领域基础层
│   └── source/src/utils/messages.ts
│       - compact boundary / message classification / message helpers
│
├── D. SessionMemory 服务层
│   └── source/src/services/SessionMemory/**
│       - sessionMemory.ts
│       - sessionMemoryUtils.ts
│       - prompts.ts
│
├── E. Auto-memory / memdir 层
│   └── source/src/memdir/**
│       - paths.ts
│       - memdir.ts
│       - findRelevantMemories.ts
│       - memoryScan.ts / memoryAge.ts / memoryTypes.ts
│       - teamMemPaths.ts / teamMemPrompts.ts
│
└── F. Query / Compact / Tool Runtime 接入层
    - query.ts 在每轮后注入 attachments / relevant memory
    - compact.ts 在 post-compact 里恢复 files / skills / memory context
    - tool execution / session persistence 把状态写回 transcript
```

---

## 3. 这个功能块的动态流程图（运行图）

```text
工具执行 / assistant 输出 / 系统事件发生
        │
        ▼
[sessionStorage.ts]
  - recordTranscript()
  - appendEntry()
  - insertMessageChain()
  - 写入当前 session transcript JSONL
        │
        ├── sidechain / subagent transcript 分流
        ├── metadata re-append
        └── remote/session ingress 持久化
        │
        ▼
下一轮 query 开始前
        │
        ├── SessionMemory / memdir 搜 relevant memories
        │
        ├── attachments.ts 组装 attachment messages
        │      - file changes
        │      - plan
        │      - memory/context deltas
        │
        ▼
query.ts 把 attachments / memories 注入下一轮 messages
        │
        ▼
若用户 / 系统执行 resume / continue
        │
        ▼
[sessionStorage.ts] loadTranscriptFile()
  - parse JSONL
  - 修复 compact boundary / snip / preserved segment / parallel tool results
  - 恢复 metadata / content replacement / snapshots
        │
        ▼
恢复出的 messages / session state 再交回运行时
```

---

## 4. 相对路径索引（总表）

---

### 4.1 transcript / attachments / message 基础层

| 相对路径 | 作用 |
|---|---|
| `source/src/utils/sessionStorage.ts` | session transcript 持久化与恢复中心 |
| `source/src/utils/sessionStoragePortable.ts` | 更便携/跨环境的 sessionStorage 支撑层 |
| `source/src/utils/attachments.ts` | attachment messages 组装中心 |
| `source/src/utils/messages.ts` | message 领域基础工具 |

---

### 4.2 SessionMemory 服务层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/SessionMemory/prompts.ts` | SessionMemory 相关 prompt 模板/构造 |
| `source/src/services/SessionMemory/sessionMemory.ts` | SessionMemory 主服务 |
| `source/src/services/SessionMemory/sessionMemoryUtils.ts` | SessionMemory 辅助逻辑 |

---

### 4.3 memdir / auto-memory 层

| 相对路径 | 作用 |
|---|---|
| `source/src/memdir/findRelevantMemories.ts` | 检索与当前任务最相关的 memories |
| `source/src/memdir/memdir.ts` | memory 目录主服务/读写辅助 |
| `source/src/memdir/memoryAge.ts` | memory 新旧/时效判断辅助 |
| `source/src/memdir/memoryScan.ts` | memory 扫描与枚举 |
| `source/src/memdir/memoryTypes.ts` | memory 类型定义 |
| `source/src/memdir/paths.ts` | auto-memory 路径、安全校验与作用域规则 |
| `source/src/memdir/teamMemPaths.ts` | team memory 路径规则 |
| `source/src/memdir/teamMemPrompts.ts` | team memory 相关 prompt |

---

## 5. 这个功能块的关键主线

这个功能块的主线可以概括为：

```text
sessionStorage.ts + attachments.ts + SessionMemory/** + memdir/**
```

更完整一点：

```text
事件发生（assistant/tool/system）
  -> sessionStorage.ts 持久化 transcript
下一轮 query 前
  -> SessionMemory / memdir 查找 relevant memories
  -> attachments.ts 组装 attachments
恢复场景
  -> sessionStorage.ts 读取 transcript 并修链
长期记忆层
  -> memdir/paths.ts + memdir.ts 决定 memory 存在哪里、怎么找
```

---

## 6. 核心文件详细职责说明

---

### 6.1 `source/src/utils/sessionStorage.ts`

**作用：** session transcript 持久化与恢复中心。

它负责：
- append-only transcript 写入
- user/assistant/tool/system entries 持久化
- title/tag/mode/worktree/pr-link 等 session metadata 持久化
- sidechain / subagent transcript 处理
- resume / continue / loadTranscriptFile
- compact boundary / preserved segment / snip / orphaned parallel tool results 修复
- content replacement / file history / attribution snapshot 的恢复

**它解决的问题：**
会话不是一条简单字符串历史，而是一个带拓扑结构、带 metadata、带 sidechain 的事件日志系统。

**一句话总结：**
> Claude Code 的会话数据库实现。

---

### 6.2 `source/src/utils/sessionStoragePortable.ts`

**作用：** 便携/跨环境的 session storage 支撑层。

它负责：
- 为不同运行环境、导出/导入或 portable 使用场景提供 transcript/session storage 相关能力辅助
- 补充 `sessionStorage.ts` 的环境适配边界

**一句话总结：**
> session 存储体系的 portable 适配层。

---

### 6.3 `source/src/utils/attachments.ts`

**作用：** attachment message 组装中心。

它负责：
- 收集文件变更、计划、memory、delta 信息
- 生成 attachment messages
- 让这些运行副作用以结构化方式回到下一轮 query

**它解决的问题：**
很多重要状态不适合直接混进普通对话消息，但又必须让模型在下一轮看到。

**一句话总结：**
> 运行时隐式状态显式化的注入器。

---

### 6.4 `source/src/utils/messages.ts`

**作用：** message 领域基础设施。

它负责：
- compact boundary 判断
- 消息分类与提取
- message 链操作基础逻辑
- 供 query / compact / sessionStorage / toolExecution 共用的消息 helper

**一句话总结：**
> 会话消息结构的共用工具层。

---

### 6.5 `source/src/services/SessionMemory/sessionMemory.ts`

**作用：** SessionMemory 主服务。

它负责：
- 当前 session 相关记忆的存取与组织
- query/compact/stopHooks 与 memory 体系之间的桥接
- relevant memory prefetch / restore 协同

**一句话总结：**
> 当前会话与 durable memory 之间的中介层。

---

### 6.6 `source/src/services/SessionMemory/sessionMemoryUtils.ts`

**作用：** SessionMemory 辅助逻辑层。

它负责：
- SessionMemory 的筛选、整理、转换、辅助计算
- 支撑 query / compact / restore 场景下的 memory 协同

**一句话总结：**
> SessionMemory 的工具函数与策略辅助层。

---

### 6.7 `source/src/services/SessionMemory/prompts.ts`

**作用：** SessionMemory 相关 prompt 生成层。

它负责：
- memory 提取、注入、摘要等场景使用的 prompt/模板内容

**一句话总结：**
> SessionMemory 与模型交互时的 prompt 模板层。

---

### 6.8 `source/src/memdir/paths.ts`

**作用：** auto-memory 路径、安全边界与作用域规则中心。

它负责：
- memory 功能是否启用
- memory 路径来源解析
- trusted settings only 的 path override
- worktree-shared memory root
- dangerous path 拒绝（root/UNC/relative/null-byte 等）

**一句话总结：**
> auto-memory 的路径与安全守门员。

---

### 6.9 `source/src/memdir/findRelevantMemories.ts`

**作用：** relevant memories 检索层。

它负责：
- 根据当前任务、上下文或会话，搜索最相关 memory 片段
- 给 query/session memory 注入阶段提供候选 memories

**一句话总结：**
> 从 memory 目录里找“当前最该带回来的记忆”。

---

### 6.10 `source/src/memdir/memdir.ts`

**作用：** memory 目录主服务层。

它负责：
- memory 文件的读写、组织、基础访问逻辑
- 为 memory 扫描、查询、写入提供统一入口

**一句话总结：**
> durable memory 目录的主服务封装层。

---

### 6.11 `source/src/memdir/memoryAge.ts`

**作用：** memory 时效/新旧判断辅助层。

它负责：
- 判断 memory 的新鲜度、时间权重、排序辅助

**一句话总结：**
> 为 relevant memory 排序提供时间维度判断。

---

### 6.12 `source/src/memdir/memoryScan.ts`

**作用：** memory 扫描器。

它负责：
- 扫描 memory 目录中的候选文件
- 为 relevant memory 检索或 memory index 构建提供输入

**一句话总结：**
> memory 目录内容的发现与枚举器。

---

### 6.13 `source/src/memdir/memoryTypes.ts`

**作用：** memory 类型定义层。

它负责：
- 定义 memory 记录、分类、候选项等相关类型

**一句话总结：**
> memory 子系统的数据模型定义文件。

---

### 6.14 `source/src/memdir/teamMemPaths.ts`

**作用：** team memory 路径规则层。

它负责：
- 协作/teammate 场景下的 memory 路径组织与归属规则

**一句话总结：**
> 团队/协作 memory 的路径规划器。

---

### 6.15 `source/src/memdir/teamMemPrompts.ts`

**作用：** team memory 相关 prompt 模板层。

它负责：
- 在 team memory 提取/使用时提供模型提示模板

**一句话总结：**
> 协作 memory 与模型交互时的 prompt 模板层。

---

## 7. 这个功能块所有涉及文件逐项职责总结

下面把这个功能块涉及文件逐个列出来总结。

---

### 7.1 transcript / attachments / message 基础层

| 相对路径 | 作用总结 |
|---|---|
| `source/src/utils/sessionStorage.ts` | session transcript 的 append-only 持久化、resume 恢复与链修复中心 |
| `source/src/utils/sessionStoragePortable.ts` | sessionStorage 的便携/跨环境适配支撑层 |
| `source/src/utils/attachments.ts` | 组装 file/plan/memory/delta 等 attachment messages |
| `source/src/utils/messages.ts` | 为 transcript/query/compact 提供消息级基础辅助 |

---

### 7.2 SessionMemory 服务层

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/SessionMemory/prompts.ts` | SessionMemory 相关 prompt 模板/构造逻辑 |
| `source/src/services/SessionMemory/sessionMemory.ts` | SessionMemory 主服务，承接当前 session 与 memory 系统之间的桥接 |
| `source/src/services/SessionMemory/sessionMemoryUtils.ts` | SessionMemory 的辅助函数与策略逻辑 |

---

### 7.3 memdir / auto-memory 层

| 相对路径 | 作用总结 |
|---|---|
| `source/src/memdir/findRelevantMemories.ts` | 搜索与当前上下文最相关的 memory 片段 |
| `source/src/memdir/memdir.ts` | durable memory 目录的主服务与基础读写层 |
| `source/src/memdir/memoryAge.ts` | memory 新鲜度/时间权重判断辅助 |
| `source/src/memdir/memoryScan.ts` | 扫描 memory 文件并产出候选列表 |
| `source/src/memdir/memoryTypes.ts` | memory 领域类型定义 |
| `source/src/memdir/paths.ts` | auto-memory 路径、安全边界与作用域规则中心 |
| `source/src/memdir/teamMemPaths.ts` | 团队/协作 memory 的路径规则 |
| `source/src/memdir/teamMemPrompts.ts` | team memory 相关 prompt 模板 |

---

## 8. 这个功能块内部的关键关系图

```text
sessionStorage.ts
  -> 写 transcript / metadata / snapshots
  -> 读 transcript / 修 compact/snip/parallel tool 链

attachments.ts
  -> 收集 runtime side effects
  -> 生成 attachment messages 给 query.ts

SessionMemory/sessionMemory.ts
  -> 调 memdir/**
  -> 与 query.ts / compact.ts / stopHooks.ts 协同

memdir/paths.ts
  -> 决定 memory 存放位置与安全边界
memdir/findRelevantMemories.ts
  -> 从 memdir.ts / memoryScan.ts / memoryAge.ts 中取候选并排序

messages.ts
  -> 为 sessionStorage.ts / compact.ts / query.ts 提供消息领域基础工具
```

---

## 9. 这个功能块最重要的设计结论

### 结论 1：resume 不是“读最后一条消息”，而是“恢复一个消息图”

`sessionStorage.ts` 里最关键的不是写文件，而是：
- compact boundary relink
- snip removal relink
- orphaned parallel tool results recovery
- metadata/snapshot 恢复

这说明 transcript 已经不是简单日志，而是一个带拓扑的事件流。

---

### 结论 2：attachments 是 query 的关键上下文回流机制

很多人容易把 attachment 当成 UI 附属物。
但在 Claude Code 里，它其实是：
- 工具结果外的额外上下文补充机制
- post-tool / post-compact / post-memory 的结构化回流层

所以 attachment 是运行时的一等公民。

---

### 结论 3：SessionMemory 与 transcript 不是一回事

- transcript = 原始事件流
- SessionMemory = 当前 session 记忆协作层
- memdir = durable memory 存储层

三者职责不同，但共同支撑长期会话能力。

---

### 结论 4：auto-memory 路径安全是一个硬边界，不是普通配置问题

`memdir/paths.ts` 里最重要的不是路径拼接，而是：
- 哪些 source 可以设置 memory path
- 哪些危险路径必须拒绝
- worktree 是否共享 memory root

这说明 memory 系统其实直接影响文件系统安全边界。

---

### 结论 5：这个功能块是 Claude Code 长期连续性的真正底座之一

没有它，就没有：
- 长期 session continuity
- compact 后继续工作
- resume/continue 的可靠恢复
- memory 驱动的下一轮上下文增强

---

## 10. 当前文档的覆盖边界说明

这份文档已经尽量按你的要求做到：

- 有 **Memory / Attachment / Session 恢复层完整子架构图**
- 有 **动态流程图**
- 有 **相对路径索引**
- 有 **核心文件详细说明**
- 有这个功能块所有涉及文件的**逐文件作用总结**

说明一下层次：

### 第一层：核心文件 = 详细说明
- `sessionStorage.ts`
- `sessionStoragePortable.ts`
- `attachments.ts`
- `messages.ts`
- `sessionMemory.ts`
- `sessionMemoryUtils.ts`
- `prompts.ts`
- `paths.ts`
- `findRelevantMemories.ts`
- `memdir.ts`

### 第二层：其余相关文件 = 逐文件职责摘要
- `memoryAge.ts`
- `memoryScan.ts`
- `memoryTypes.ts`
- `teamMemPaths.ts`
- `teamMemPrompts.ts`

如果你后面还要更细，我还可以把这个功能块再拆成两份：

1. **sessionStorage / resume 恢复链深拆版**
2. **memdir / SessionMemory / relevant memory 检索深拆版**

---

## 11. 当前子功能块输出结果

本轮已完成：
- **Memory / Attachment / Session 恢复层完整子架构图**
- **动态流程图**
- **相对路径总索引**
- **核心文件详细说明**
- **该功能块所有涉及文件的逐文件作用总结**

已保存到：
- `cc/cc_learn/18_arch_memory_attachment_resume_framework.md`

---

## 12. 下一步建议

按这个顺序，下一块最自然应该做：

### MCP 集成模块
建议文件名：
- `cc/cc_learn/19_arch_mcp_framework.md`

因为它同样是 Claude Code 的一级扩展平台，并且与：
- tools
- commands
- query
- config/policy/auth

都有强耦合。

如果你继续要我做，我下一份就直接写这一块。