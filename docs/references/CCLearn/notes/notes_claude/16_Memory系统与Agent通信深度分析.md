# Memory 系统与 Agent 通信机制深度分析

> 基于 `@anthropic-ai/claude-code@2.1.88` 源码的全面逆向分析  
> 分析日期: 2026-04-12

---

## 目录

- [一、Memory 系统全局架构](#一memory-系统全局架构)
- [二、核心模块: memdir/ 目录](#二核心模块-memdir-目录)
  - [2.1 paths.ts — 路径解析与安全验证](#21-pathsts--路径解析与安全验证)
  - [2.2 memdir.ts — Memory Prompt 构建主入口](#22-memdirts--memory-prompt-构建主入口)
  - [2.3 memoryTypes.ts — 类型分类体系与指导文本](#23-memorytypests--类型分类体系与指导文本)
  - [2.4 memoryScan.ts — Memory 文件发现与清单](#24-memoryscants--memory-文件发现与清单)
  - [2.5 memoryAge.ts — 陈旧度跟踪](#25-memoryagets--陈旧度跟踪)
  - [2.6 findRelevantMemories.ts — 查询时 Memory 智能选择](#26-findrelevantmemoriests--查询时-memory-智能选择)
  - [2.7 teamMemPaths.ts — 团队 Memory 安全验证](#27-teammempathsts--团队-memory-安全验证)
  - [2.8 teamMemPrompts.ts — 团队 Memory Prompt 构建](#28-teammempromptsts--团队-memory-prompt-构建)
- [三、CLAUDE.md 文件发现与加载系统](#三claudemd-文件发现与加载系统)
- [四、Context 构建与注入流程](#四context-构建与注入流程)
  - [4.1 context.ts — 系统/用户上下文构建](#41-contextts--系统用户上下文构建)
  - [4.2 prompts.ts — System Prompt 生成](#42-promptsts--system-prompt-生成)
  - [4.3 api.ts — Context 注入 API 调用](#43-apits--context-注入-api-调用)
  - [4.4 queryContext.ts — 上下文获取编排](#44-querycontextts--上下文获取编排)
- [五、Memory 在查询引擎中的流转](#五memory-在查询引擎中的流转)
  - [5.1 Memory Prefetch — 异步预取](#51-memory-prefetch--异步预取)
  - [5.2 Attachment 系统 — Memory 注入消息流](#52-attachment-系统--memory-注入消息流)
  - [5.3 Context 压缩与 Compact](#53-context-压缩与-compact)
- [六、Session 持久化与恢复](#六session-持久化与恢复)
- [七、Memory 提取服务](#七memory-提取服务)
  - [7.1 extractMemories — 后台自动提取](#71-extractmemories--后台自动提取)
  - [7.2 SessionMemory — 会话内记忆](#72-sessionmemory--会话内记忆)
  - [7.3 Team Memory Sync — 团队同步](#73-team-memory-sync--团队同步)
- [八、Agent Memory — Agent 专属记忆](#八agent-memory--agent-专属记忆)
- [九、Agent 与 SubAgent 通信机制](#九agent-与-subagent-通信机制)
  - [9.1 AgentTool — Agent 生成入口](#91-agenttool--agent-生成入口)
  - [9.2 forkSubagent — Fork 模式上下文继承](#92-forksubagent--fork-模式上下文继承)
  - [9.3 runAgent — 核心执行与上下文传递](#93-runagent--核心执行与上下文传递)
  - [9.4 resumeAgent — Agent 恢复与续接](#94-resumeagent--agent-恢复与续接)
- [十、Agent 间通信系统](#十agent-间通信系统)
  - [10.1 SendMessageTool — 消息路由](#101-sendmessagetool--消息路由)
  - [10.2 File-based Mailbox — 文件邮箱系统](#102-file-based-mailbox--文件邮箱系统)
  - [10.3 LocalAgentTask — 本地 Agent 任务管理](#103-localagentTask--本地-agent-任务管理)
  - [10.4 Coordinator Mode — 协调者模式](#104-coordinator-mode--协调者模式)
- [十一、In-Process Teammate — 进程内队友系统](#十一in-process-teammate--进程内队友系统)
  - [11.1 TeammateContext — AsyncLocalStorage 隔离](#111-teammatecontext--asynclocalstorage-隔离)
  - [11.2 Teammate 身份解析](#112-teammate-身份解析)
  - [11.3 InProcessBackend — 进程内后端](#113-inprocessbackend--进程内后端)
- [十二、Memory 共享矩阵与数据流总图](#十二memory-共享矩阵与数据流总图)
- [十三、权限与安全机制](#十三权限与安全机制)
- [十四、Feature Gates 与环境变量](#十四feature-gates-与环境变量)
- [十五、目录结构总览](#十五目录结构总览)
- [十六、关键文件索引](#十六关键文件索引)

---

## 一、Memory 系统全局架构

Claude Code 的 Memory 系统是一个**多层级、多作用域**的持久化架构，允许 Claude 跨会话维护上下文。整体分为以下层次：

```
┌───────────────────────────────────────────────────────────┐
│                    Memory 系统四层架构                      │
├───────────────────────────────────────────────────────────┤
│ Layer 1: Managed Memory                                   │
│   /etc/claude-code/CLAUDE.md (组织级全局指令)              │
├───────────────────────────────────────────────────────────┤
│ Layer 2: User Memory                                      │
│   ~/.claude/CLAUDE.md (用户级全局指令)                     │
├───────────────────────────────────────────────────────────┤
│ Layer 3: Project Memory                                   │
│   CLAUDE.md, .claude/CLAUDE.md, .claude/rules/*.md        │
│   (项目级指令，提交到版本控制)                              │
├───────────────────────────────────────────────────────────┤
│ Layer 4: Local Memory                                     │
│   CLAUDE.local.md (本地私有指令，不提交)                   │
├───────────────────────────────────────────────────────────┤
│ Auto Memory (私有持久化)                                   │
│   ~/.claude/projects/<sanitized-path>/memory/              │
│   ├── MEMORY.md (索引入口，200行/25KB上限)                 │
│   ├── *.md (主题文件)                                      │
│   └── team/ (团队共享 memory)                              │
├───────────────────────────────────────────────────────────┤
│ Agent Memory (Agent 专属持久化)                            │
│   ~/.claude/agent-memory/<agentType>/MEMORY.md (user级)    │
│   .claude/agent-memory/<agentType>/MEMORY.md (project级)   │
│   .claude/agent-memory-local/<agentType>/MEMORY.md (本地)  │
├───────────────────────────────────────────────────────────┤
│ Session Memory (会话级提取)                                │
│   ~/.claude/projects/<project>/sessionMemory/              │
└───────────────────────────────────────────────────────────┘
```

**核心设计原则：**
1. **优先级由低到高**：Managed → User → Project → Local
2. **MEMORY.md 有严格限制**：200 行 OR 25KB（取先触达者）
3. **类型分类为封闭体系**：user / feedback / project / reference 四种
4. **安全优先**：防路径穿越、防符号链接逃逸、防 Unicode 规范化攻击

---

## 二、核心模块: memdir/ 目录

### 2.1 paths.ts — 路径解析与安全验证

**文件路径：** `source/src/memdir/paths.ts`

此文件是 Memory 系统的路径基础设施，负责解析所有 Memory 目录路径并进行安全验证。

#### 核心函数

**`isAutoMemoryEnabled()`**
```
优先级链：
1. CLAUDE_CODE_DISABLE_AUTO_MEMORY 环境变量 → 禁用
2. --bare 模式 → 禁用
3. CCR 无持久存储 → 禁用
4. settings.json 中 autoMemoryEnabled → 按配置
5. 默认: 启用
```

**`getMemoryBaseDir()`** — 返回 `~/.claude` 或 `CLAUDE_CODE_REMOTE_MEMORY_DIR` 覆盖值

**`getAutoMemPath()`** — 核心路径解析函数
```
解析优先级：
1. CLAUDE_COWORK_MEMORY_PATH_OVERRIDE 环境变量 (完全覆盖)
2. settings.json 中 autoMemoryDirectory (支持 ~/ 展开)
3. 默认: ~/.claude/projects/<sanitized-git-root>/memory/

路径清洁处理:
- NFC Unicode 规范化
- 结果会被 memoize 缓存
```

**`getAutoMemEntrypoint()`** — 返回 `<autoMemPath>/MEMORY.md`

**`getAutoMemDailyLogPath()`** — KAIROS 模式日志路径: `<autoMemPath>/logs/YYYY/MM/YYYY-MM-DD.md`

**`isAutoMemPath(absolutePath)`** — 检查路径是否在 auto-memory 目录内

#### 安全验证

拒绝以下危险路径：
- 相对路径
- 根目录或近根路径
- Windows 驱动器根路径
- UNC 路径
- 包含 null 字节的路径

---

### 2.2 memdir.ts — Memory Prompt 构建主入口

**文件路径：** `source/src/memdir/memdir.ts`

这是 Memory 系统的**主编排文件**，负责将 Memory 内容组装为 system prompt 的一部分。

#### 关键常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `ENTRYPOINT_NAME` | `'MEMORY.md'` | 索引文件名 |
| `MAX_ENTRYPOINT_LINES` | `200` | 最大行数 |
| `MAX_ENTRYPOINT_BYTES` | `25000` (25KB) | 最大字节数 |

#### 核心函数

**`loadMemoryPrompt()`** — 主加载函数
```typescript
// 调度逻辑：
if (KAIROS) → buildAssistantDailyLogPrompt()  // 助手模式，追加日志
if (TEAMMEM) → buildCombinedMemoryPrompt()    // 团队 + 个人
else         → buildMemoryPrompt()            // 仅个人
```
- 确保 memory 目录存在 (`ensureMemoryDirExists()`)
- 记录目录统计信息到日志

**`buildMemoryPrompt()`** — 组装个人 Memory 的 prompt
```typescript
// 流程：
1. 读取 MEMORY.md 入口文件内容
2. 调用 truncateEntrypointContent() 截断到限制
3. 返回格式化字符串: 行为指令 + MEMORY.md 内容
```

**`truncateEntrypointContent(content)`** — 截断逻辑
```
两个独立限制, 取先触达者:
- 行数限制: 200 行后截断
- 字节限制: 25KB 后截断
- 截断时追加警告文本
```

**`buildMemoryLines()`** — 构建行为指令（不含内容）
- 约束 memory 为四类型分类体系
- 定义保存和访问规则

**`ensureMemoryDirExists()`** — 递归创建 `~/.claude/projects/<sanitized-cwd>/memory/` 目录

---

### 2.3 memoryTypes.ts — 类型分类体系与指导文本

**文件路径：** `source/src/memdir/memoryTypes.ts`

定义了 Memory 的**封闭四类型分类法**以及相应的指导 prompt。

#### 四种 Memory 类型

| 类型 | 用途 | 作用域 | 保存时机 |
|------|------|--------|----------|
| **user** | 用户角色、偏好、知识水平 | 始终私有 | 了解到用户信息时 |
| **feedback** | 工作方式指导（纠正+验证） | 默认私有；组织惯例可 team | 用户纠正或确认方法时 |
| **project** | 进行中的工作/目标/事件 | 私有或 team，偏 team | 了解谁在做什么、为什么、截止何时 |
| **reference** | 外部系统的指针 | 通常 team | 了解到外部资源位置时 |

#### 导出的 Prompt 片段

| 导出名 | 说明 |
|--------|------|
| `TYPES_SECTION_INDIVIDUAL` | 单目录模式（无 scope 标签） |
| `TYPES_SECTION_COMBINED` | 合并模式（含 `<scope>` XML 标签） |
| `WHAT_NOT_TO_SAVE_SECTION` | 不应保存的内容（代码模式、git 历史等） |
| `WHEN_TO_ACCESS_SECTION` | 何时访问 memory（含陈旧度警告） |
| `TRUSTING_RECALL_SECTION` | 如何在推荐前验证 memory 声明 |
| `MEMORY_FRONTMATTER_EXAMPLE` | 文件前置元数据格式示例 |

#### Frontmatter 格式

```markdown
---
name: {{memory name}}
description: {{一行描述 — 用于未来对话的相关性判断}}
type: {{user | feedback | project | reference}}
---

{{memory 内容}}
```

---

### 2.4 memoryScan.ts — Memory 文件发现与清单

**文件路径：** `source/src/memdir/memoryScan.ts`

扫描 Memory 目录并提取文件元数据。

#### 核心函数

**`scanMemoryFiles(memoryDir)`**
```
功能：
- 读取目录中所有 .md 文件（排除 MEMORY.md）
- 解析每个文件的 frontmatter 元数据
- 按修改时间降序排列（最新优先）
- 最多返回 200 个文件
返回：文件头信息数组 { name, description, type, path, mtime }
```

**`formatMemoryManifest(headers)`**
```
格式化输出：
[type] filename (ISO时间戳): description
例: [feedback] testing_approach.md (2026-04-10): 集成测试必须使用真实数据库
```

---

### 2.5 memoryAge.ts — 陈旧度跟踪

**文件路径：** `source/src/memdir/memoryAge.ts`

计算 Memory 文件年龄并生成陈旧度警告。

#### 函数

| 函数 | 功能 |
|------|------|
| `memoryAgeDays(path)` | 返回 `Math.floor(天数差)` |
| `memoryAge(path)` | 人类可读: "today" / "yesterday" / "N days ago" |
| `memoryFreshnessText(path)` | >1天的 memory 生成时间点警告文本 |
| `memoryFreshnessNote(path)` | 同上，包裹在 `<system-reminder>` 标签中 |

**使用场景：** FileReadTool 读取旧 memory 文件时，在输出中附加陈旧度警告，提醒 Claude 该信息可能已过时。

---

### 2.6 findRelevantMemories.ts — 查询时 Memory 智能选择

**文件路径：** `source/src/memdir/findRelevantMemories.ts`

使用 Sonnet 模型智能选择与当前查询最相关的 Memory 文件。

#### 核心函数

**`findRelevantMemories(query, memoryDir)`**
```
流程：
1. 调用 scanMemoryFiles() 获取所有 memory 文件元数据
2. 排除 MEMORY.md（已在 system prompt 中）
3. 过滤掉已在使用中的工具参考文档
4. 调用 selectRelevantMemories() — Sonnet 侧查询
5. 返回最多 5 个最相关文件 { path, mtimeMs }
```

**`selectRelevantMemories(query, manifest)`**
```
调用 Claude Sonnet:
- 输入: 用户查询 + memory 清单
- 输出: JSON schema 约束的排名列表
- 目的: 根据描述判断哪些 memory 与当前对话相关
```

**智能过滤机制：**
- 排除 MEMORY.md（避免重复注入）
- 过滤已读文件（`alreadySurfaced` 集合跟踪）
- 过滤正在使用的工具参考文档

---

### 2.7 teamMemPaths.ts — 团队 Memory 安全验证

**文件路径：** `source/src/memdir/teamMemPaths.ts`

团队 Memory 的路径验证，具备**符号链接逃逸防护**。

#### 核心函数

| 函数 | 功能 |
|------|------|
| `isTeamMemoryEnabled()` | 检查 feature gate `tengu_herring_clock`（需 auto-memory 启用） |
| `getTeamMemPath()` | 返回 `<autoMemPath>/team/` |
| `getTeamMemEntrypoint()` | 返回 `<autoMemPath>/team/MEMORY.md` |
| `isTeamMemPath(path)` | 字符串级包含检查 |
| `validateTeamMemWritePath(path)` | **安全核心**：解析符号链接，检查真实路径包含性 |
| `validateTeamMemKey(key)` | 验证服务端返回的相对路径键，防符号链接攻击 |

#### 安全防护

```
防御层次:
├── 路径穿越 (.. 段落)
├── 符号链接逃逸 (realpath 验证)
├── 悬挂符号链接
├── URL 编码穿越 (%2e%2e)
└── Unicode 规范化攻击 (NFC 一致性)
```

---

### 2.8 teamMemPrompts.ts — 团队 Memory Prompt 构建

**文件路径：** `source/src/memdir/teamMemPrompts.ts`

构建包含私有 + 团队 Memory 的合并 prompt。

**`buildCombinedMemoryPrompt()`**
```
生成内容:
1. 私有目录说明 (auto-memory 路径)
2. 团队目录说明 (team 子目录路径)
3. Scope 指导 (哪些 memory 放私有/团队)
4. 保存方式说明 (两步流程: 写文件 + 更新索引)
```

---

## 三、CLAUDE.md 文件发现与加载系统

**文件路径：** `source/src/utils/claudemd.ts`

这是 Memory 系统中**最核心的文件加载器**，负责发现并加载所有层级的 CLAUDE.md 文件。

### 文件加载优先级

```
优先级 (低 → 高):
1. /etc/claude-code/CLAUDE.md          — Managed Memory (组织级)
2. ~/.claude/CLAUDE.md                  — User Memory (用户级)
3. CLAUDE.md / .claude/CLAUDE.md        — Project Memory (项目级)
   .claude/rules/*.md                   
4. CLAUDE.local.md                      — Local Memory (本地私有)
```

### 核心函数

**`getMemoryFiles()`** — Memoized 主函数
```
功能:
- 从 CWD 向上遍历到根目录
- 扫描所有 4 层级的 .md 文件
- 返回 MemoryFileInfo[] 数组 { type, path, content }
- 按 isClaudeMdExcluded() 设置过滤

类型识别:
- 'AutoMem': auto-memory 目录下的文件
- 'TeamMem': team memory 目录下的文件  
- 'Claudemd': 项目级 CLAUDE.md
- 'LocalClaudemd': CLAUDE.local.md
```

**`getClaudeMds(memoryFiles)`** — 组装为单一字符串
```
处理:
1. 团队 memory 包裹在 <team-memory-content> 标签中
2. 前置 MEMORY_INSTRUCTION_PROMPT:
   "Codebase and user instructions are shown below. Be sure to adhere to 
    these instructions. IMPORTANT: These instructions OVERRIDE any default 
    behavior and you MUST follow them exactly as written."
3. 返回格式化的合并内容
```

**`filterInjectedMemoryFiles(files)`** — 过滤 + 预处理
```
处理步骤:
1. 剥离 frontmatter
2. 剥离 HTML 注释 (<!-- -->, 仅块级)
3. 截断 MEMORY.md 到 200行/25KB
4. 保留项目级和本地级文件
```

### @include 指令支持

```
语法:
  @path                    — 相对于项目根
  @./relative/path         — 相对于当前文件
  @~/home/path             — 相对于 home 目录
  @/absolute/path          — 绝对路径

特性:
- 仅在叶文本节点中生效（不在代码块中）
- 被包含的文件作为独立条目添加到包含文件之前
- 循环引用防护（文件路径追踪）
- 不存在的文件静默忽略
```

### 缓存机制

```
memoize() 缓存策略:
- 会话期间缓存结果
- /clear 或 /compact 时清除缓存
- systemPromptInjection 变更时清除
- 手动调用 clearCache() 清除
```

---

## 四、Context 构建与注入流程

### 4.1 context.ts — 系统/用户上下文构建

**文件路径：** `source/src/context.ts`

#### `getUserContext()`

```typescript
// 核心流程:
1. 调用 getMemoryFiles() 发现所有 CLAUDE.md 文件
2. 调用 filterInjectedMemoryFiles() 过滤和预处理
3. 调用 getClaudeMds() 组装为单一字符串
4. 缓存到 bootstrap state (供 auto-mode classifier 使用)
5. 返回 { claudeMd: "...", currentDate: "2026-04-12" }

环境变量控制:
- CLAUDE_CODE_DISABLE_CLAUDE_MDS → 禁用加载
- CLAUDE_CODE_SIMPLE / --bare → 跳过自动发现
```

#### `getSystemContext()`

```typescript
// 核心流程:
1. 调用 getGitStatus() 获取 git 信息
2. 包含 branch, 最近 commits, working tree status
3. CCR 模式或禁用 git 指令时跳过
4. 返回 { gitStatus: "..." }
```

两个函数都使用 `memoize()` 缓存。

---

### 4.2 prompts.ts — System Prompt 生成

**文件路径：** `source/src/constants/prompts.ts`

#### `getSystemPrompt()`

```typescript
// 返回 string[] 数组，各 section 组成完整 prompt:
[
  introduction,           // 身份和系统指令
  doingTasks,             // 任务执行指导
  toolUsage,              // 工具使用规则
  languagePrefs,          // 语言偏好
  outputStyle,            // 输出风格
  
  // ↓ 关键: Memory 注入点
  systemPromptSection('memory', () => loadMemoryPrompt()),
  
  mcpInstructions,        // MCP 协议指令
  tokenBudget,            // Token 预算（如启用）
]
```

#### 缓存边界

```
SYSTEM_PROMPT_DYNAMIC_BOUNDARY 标记:
├── 之前: scope='global' → prompt 缓存（静态内容）
└── 之后: session-specific → 每次变更使缓存失效
```

---

### 4.3 api.ts — Context 注入 API 调用

**文件路径：** `source/src/utils/api.ts`

#### `appendSystemContext(systemPrompt, systemContext)`

将系统上下文（git status 等）追加到 system prompt 末尾。

#### `prependUserContext(messages, userContext)`

将用户上下文（CLAUDE.md 内容）作为**合成 user 消息**前置到消息列表：

```xml
<system-reminder>
As you answer the user's questions, you can use the following context:
# claudeMd
{{CLAUDE.md 合并内容}}
# currentDate
Today's date is 2026-04-12.
</system-reminder>
```

- 标记为 `isMeta: true`（系统元数据消息）
- 测试模式跳过

#### `logContextMetrics()`

记录上下文大小遥测：
- `git_status_size`: git 状态字节数
- `claude_md_size`: 加载的 memory 文件字节数
- `total_context_size`: 合计大小
- 各工具的 token 计数

---

### 4.4 queryContext.ts — 上下文获取编排

**文件路径：** `source/src/utils/queryContext.ts`

#### `fetchSystemPromptParts()`

```typescript
// 返回三个组件:
{
  defaultSystemPrompt: string[],    // getSystemPrompt() 结果
  userContext: { claudeMd, ... },   // getUserContext() 结果
  systemContext: { gitStatus, ... } // getSystemContext() 结果
}
```

在 QueryEngine 中被调用，最终组装为完整的 API 请求。

---

## 五、Memory 在查询引擎中的流转

### 5.1 Memory Prefetch — 异步预取

**文件路径：** `source/src/utils/attachments.ts` + `source/src/query.ts`

#### 异步预取机制

```typescript
// query.ts 中:
using pendingMemoryPrefetch = startRelevantMemoryPrefetch()
// ↑ 使用 symbol.dispose() 模式自动清理

// attachments.ts 中:
startRelevantMemoryPrefetch()
├── Feature gate: tengu_moth_copse
├── 在模型流式响应期间异步触发（隐藏延迟）
├── 调用 Sonnet 模型选择相关 memory
├── 字节预算: 累计 60KB/会话, 5×4KB/轮
├── 用户 Escape 时中止
└── 返回 MemoryPrefetch 句柄 { promise, telemetry }
```

#### Memory 注入流程 (query.ts)

```typescript
// 第一步: 在 tool 结果收集后检查预取结果
if (pendingMemoryPrefetch?.settledAt !== null 
    && pendingMemoryPrefetch.consumedOnIteration === -1) {
  
  // 第二步: 去重（排除已读文件）
  const memoryAttachments = filterDuplicateMemoryAttachments(
    await pendingMemoryPrefetch.promise,
    toolUseContext.readFileState,  // 对已读文件去重
  )
  
  // 第三步: 作为 Attachment 消息注入
  for (const memAttachment of memoryAttachments) {
    yield createAttachmentMessage(memAttachment)
    toolResults.push(memAttachment)  // 加入下次 API 调用
  }
}
```

#### 去重逻辑

```typescript
filterDuplicateMemoryAttachments(memories, readFileState)
├── 对照 readFileState 检查（本轮已读的文件）
├── 标记已过滤的 memory 到 readFileState（防止再次浮现）
└── 仅返回新颖的 memory
```

---

### 5.2 Attachment 系统 — Memory 注入消息流

**文件路径：** `source/src/utils/attachments.ts`

```typescript
getAttachmentMessages(query, toolUseContext, ...)
├── 异步生成器，yield AttachmentMessage
├── 调用 getAttachments() 计算所有附件类型
│   ├── 相关 memory
│   ├── 技能
│   ├── 通知
│   └── 其他
├── 仅在有附件时 yield
└── 添加到 toolResults[]
```

---

### 5.3 Context 压缩与 Compact

**文件路径：** `source/src/services/compact/compact.ts`

#### 压缩前处理

| 函数 | 功能 |
|------|------|
| `stripImagesFromMessages()` | 移除图片块（防 prompt 过长） |
| `stripReinjectedAttachments()` | 移除技能发现/列表（噪声，compact 后重注入） |
| `truncateHeadForPTLRetry()` | compact 请求本身触发 413 时丢弃最旧消息组 |

#### Compact 后重注入

```
重注入预算:
├── 最多 5 个文件
├── 50K token 总预算
├── 单文件上限: 5K tokens
├── 单技能上限: 5K tokens  
├── 技能总预算: 25K tokens (~5 个技能)
└── 通过 generateFileAttachment(mode:'compact') 恢复
```

#### 恢复层次（API 错误时）

```
错误恢复优先级:
1. Context collapse drain (如已启用)
2. Reactive compact (prompt-too-long 或 media-size 错误)
3. Surface error + exit (恢复失败)
```

---

## 六、Session 持久化与恢复

### Session 存储

**文件路径：** `source/src/utils/sessionStorage.ts`

```typescript
getTranscriptPath()
├── 返回当前会话的 JSONL 路径
├── 尊重 sessionProjectDir 设置
└── 持久化选择:
    ├── isTranscriptMessage() → 持久化 (user/assistant/attachment/system)
    ├── isEphemeralToolProgress() → 不持久化 (bash_progress, sleep_progress)
    └── 消息链: parentUuid 链接，isChainParticipant() 判定
```

### Session 恢复

**文件路径：** `source/src/utils/sessionRestore.ts`

```typescript
restoreSessionStateFromLog()
├── 文件历史快照恢复
├── Attribution 快照恢复（commit 历史）
├── Context-collapse commit 日志 + staged 快照
├── TodoWrite 状态恢复
└── 从 transcript 重建

restoreAgentFromSession()
├── 重新应用 agent type
└── 恢复 model override

restoreSessionMetadata()
├── 加载会话元数据
└── 包括 name, tags 等
```

### Bootstrap State

**文件路径：** `source/src/bootstrap/state.ts`

全局单例 `State` 对象：

```typescript
State = {
  // 身份
  sessionId, parentSessionId, sessionProjectDir,
  
  // 上下文缓存
  cachedClaudeMdContent,        // CLAUDE.md 缓存内容
  systemPromptSectionCache,     // prompt section 缓存
  
  // 查询追踪
  queryTracking: { depth, chainId },  // 递归查询追踪
  
  // API 状态
  lastAPIRequest, lastAPIRequestMessages,
  lastApiCompletionTimestamp,
  
  // 模型状态
  mainLoopModelOverride, initialMainLoopModel, modelUsage,
  
  // 技能状态
  invokedSkills: Map  // 跨 compact 保留
}
```

---

## 七、Memory 提取服务

### 7.1 extractMemories — 后台自动提取

**文件路径：** `source/src/services/extractMemories/extractMemories.ts`

后台运行的 Memory 提取 agent，在会话轮次结束时提取持久 memory。

```
触发条件:
├── Feature gate: tengu_passport_quail
├── 非交互模式: tengu_slate_thimble
└── 在 turn 结束时运行

提取逻辑:
├── hasMemoryWritesSince() → 检查主 agent 是否已写 memory
│   └── 如已写，跳过提取（主 agent 优先）
├── Fork 子 agent, 有限工具集:
│   ├── File Read/Write/Edit
│   ├── Bash (只读)
│   ├── Grep, Glob
│   └── 无网络/无 Agent/无 SendMessage
└── 使用 extractMemories/prompts.ts 中的提取 prompt
```

---

### 7.2 SessionMemory — 会话内记忆

**文件路径：** `source/src/services/SessionMemory/sessionMemory.ts`

维护当前会话的笔记，不打断主对话流。

```
Feature gate: tengu_session_memory

shouldExtractMemory(messages[]) 决策:
├── 初始化阈值: 上下文超过限制
├── 更新阈值: 自上次提取后足够的 token/tool 调用
└── 在自然间断时触发（无活跃 tool 调用）

存储位置: ~/.claude/projects/<project>/sessionMemory/

提取方式:
├── Fork 子 agent, 使用主循环相同的 system prompt
├── 维护 markdown 笔记文件
├── manuallyExtractSessionMemory() → 手动触发
└── buildSessionMemoryUpdatePrompt() → 构建提取 prompt
```

---

### 7.3 Team Memory Sync — 团队同步

**文件路径：** `source/src/services/teamMemorySync/index.ts`

本地文件系统与 Claude.ai API 之间同步团队 memory。

```
同步语义:
├── Pull: 服务端覆盖本地（服务端优先）
├── Push: Delta 上传（仅内容 hash 不同的 key）
└── 删除: 不传播（服务端 upsert 语义保留）

大小限制:
├── 单条: 250KB 最大
├── PUT body: 200KB (大批次自动拆分)
└── 服务端 max_entries (从 413 响应学习)

状态追踪:
SyncState = {
  etag,                // 版本标记
  contentHashes,       // 内容 hash 映射
  watcherSuppression   // 监视器抑制
}
```

---

## 八、Agent Memory — Agent 专属记忆

**文件路径：** `source/src/tools/AgentTool/agentMemory.ts`

每种类型的 Agent 拥有独立的、持久化的 memory 系统。

### 三个作用域

| 作用域 | 路径 | 说明 |
|--------|------|------|
| `'user'` | `~/.claude/agent-memory/<agentType>/MEMORY.md` | 全局跨项目 |
| `'project'` | `.claude/agent-memory/<agentType>/MEMORY.md` | 通过 git 共享 |
| `'local'` | `.claude/agent-memory-local/<agentType>/MEMORY.md` | 机器特定，不提交 |

### 核心函数

```typescript
getAgentMemoryDir(agentType, scope)        // → memory 目录路径
getAgentMemoryEntrypoint(agentType, scope)  // → MEMORY.md 路径
loadAgentMemoryPrompt(agentType, scope)     // → 加载并返回 prompt
isAgentMemoryPath(absolutePath)             // → 安全检查（防路径穿越）
```

Memory 目录在 agent 生成时异步创建 (`ensureMemoryDirExists()`)，agent 在 API 往返后才会尝试写入。

### Agent Memory Snapshots

**文件路径：** `source/src/tools/AgentTool/agentMemorySnapshot.ts`

项目级 Agent memory 快照，用于团队协作：

```
快照目录: .claude/agent-memory-snapshots/<agentType>/

函数:
├── checkAgentMemorySnapshot() → 检查快照是否比本地更新
├── initializeFromSnapshot()   → 首次设置，从快照复制
├── replaceFromSnapshot()      → 用快照替换本地
└── markSnapshotSynced()       → 记录同步元数据

返回 action: 'none' | 'initialize' | 'prompt-update'
```

---

## 九、Agent 与 SubAgent 通信机制

### 9.1 AgentTool — Agent 生成入口

**文件路径：** `source/src/tools/AgentTool/AgentTool.tsx`

AgentTool 是生成子 agent 的主要机制：

```
生成模式:
├── 同步 (foreground): agent 运行完成后返回结果
├── 异步 (background): agent 在后台运行
│   ├── isBackgrounded: true
│   └── pendingMessages 队列用于中途通信
└── Fork: 子 agent 继承父级完整上下文

注册流程:
1. 创建 AgentDefinition (类型、工具集、模型)
2. registerAsyncAgent() → 创建 LocalAgentTaskState
3. runAgent() → 后台生成执行循环
4. 完成时发送 <task-notification> 通知
```

---

### 9.2 forkSubagent — Fork 模式上下文继承

**文件路径：** `source/src/tools/AgentTool/forkSubagent.ts`

实现**隐式 fork**，子 agent 继承父级完整上下文。

#### 核心函数

**`buildForkedMessages(directive, assistantMessage)`**

```typescript
// Fork 消息构建:
1. 保留完整的父级 assistant 消息
   (所有 tool_use 块、thinking、text)

2. 构建单一 user 消息:
   ├── 每个 tool_use 的占位 tool_result
   └── 追加 per-child directive 文本
       ├── 模板规则 (不递归 fork、直接执行、提交变更)
       └── 实际任务描述

3. isInForkChild(messages):
   检查 fork 模板标签防止递归 fork
```

**`FORK_AGENT`** — 合成 agent 定义：
```typescript
{
  tools: ['*'],        // 继承所有工具
  model: 'inherit'     // 继承父级模型
}
```

**`buildWorktreeNotice()`** — 通知 fork 子级关于隔离 worktree 中的路径转换

#### Fork 子级规则

子 agent 收到的模板规则：
1. 不递归 fork
2. 直接执行任务
3. 提交变更
4. 用结构化格式报告: Scope / Result / Key files / Files changed / Issues

---

### 9.3 runAgent — 核心执行与上下文传递

**文件路径：** `source/src/tools/AgentTool/runAgent.ts`

Agent 执行循环的核心，管理所有上下文传递。

#### 函数签名

```typescript
export async function* runAgent({
  agentDefinition,          // Agent 定义 (类型、工具、模型)
  promptMessages,           // 初始 prompt 消息
  toolUseContext,           // 父级的上下文
  forkContextMessages,      // 完整对话用于继承
  override?: {
    userContext,            // 自定义用户上下文
    systemContext,          // 自定义系统上下文
    systemPrompt,           // 父级确切的 system prompt 字节 (缓存保留)
  },
  availableTools,           // 预计算的 agent 工具池
})
```

#### 关键上下文共享机制

**1. File State Cache 克隆**
```typescript
const agentReadFileState =
  forkContextMessages !== undefined
    ? cloneFileStateCache(toolUseContext.readFileState)
    : createFileStateCacheWithSizeLimit(...)

// Fork 时: 子级继承父级的文件读取缓存
// 非 Fork: 创建新的有大小限制的缓存
```

**2. ToolUseContext 访问**
```typescript
const appState = toolUseContext.getAppState()
const rootSetAppState = 
  toolUseContext.setAppStateForTasks ?? toolUseContext.setAppState

// 嵌套 async→async agent: setAppState 为 no-op
// session 级写入通过 setAppStateForTasks 访问根 store
```

**3. System Prompt 传递**
```typescript
override?.systemPrompt ??     // Fork: 使用确切父级字节
override?.userContext ??       // 自定义上下文
override?.systemContext ??     // 自定义系统上下文

// Fork resume 通过 toolUseContext.renderedSystemPrompt
// 传递精确字节以匹配 API 缓存
```

**4. 消息过滤**
```typescript
const contextMessages: Message[] = forkContextMessages
  ? filterIncompleteToolCalls(forkContextMessages)
  : []
const initialMessages = [...contextMessages, ...promptMessages]

// 过滤未完成的 tool_use 块防止 API 错误
// 父级对话前置到子级消息中
```

**5. 权限模式继承**
```typescript
// 子 agent 权限来源:
agentDefinition.permissionMode  // Agent 定义中指定
  ?? parentPermissionMode       // 或继承父级
```

---

### 9.4 resumeAgent — Agent 恢复与续接

**文件路径：** `source/src/tools/AgentTool/resumeAgent.ts`

从磁盘 transcript 恢复已停止的 agent，带新消息续接。

```typescript
export async function resumeAgentBackground({
  agentId,        // 要恢复的 agent
  prompt,         // 新消息
  toolUseContext,
  canUseTool,
  invokingRequestId,
}): Promise<ResumeAgentResult>
```

#### 恢复流程

```
1. Load Transcript
   ├── 读取 agent 的 transcript 和元数据
   └── 过滤不完整 tool 调用和孤立 thinking

2. Reconstruct System Prompt
   ├── Fork resume: 使用精确父级 prompt 字节
   │   (toolUseContext.renderedSystemPrompt)
   └── 非 Fork: 在 cwd override 下重新计算

3. Register Task
   ├── 注册为新的 async task
   └── 不写入 name registry (原始条目保留)

4. Setup Context
   AgentContext = {
     agentId,
     parentSessionId,
     agentType: 'subagent',
     subagentName: selectedAgent.agentType,
     isBuiltIn,
     invokingRequestId,
     invocationKind: 'resume',
   }

5. Worktree 保留
   ├── 尝试使用原始 worktree（如仍存在）
   ├── 不存在则回退到父级 cwd
   └── 更新 mtime 防止 stale worktree 清理
```

---

## 十、Agent 间通信系统

### 10.1 SendMessageTool — 消息路由

**文件路径：** `source/src/tools/SendMessageTool/SendMessageTool.ts`

Agent 间结构化消息发送和控制流命令。

#### 输入 Schema

```typescript
{
  to: string,      // 目标:
                    //   队友名称
                    //   "*" 广播
                    //   "bridge:<session-id>" 远程
                    //   "uds:<socket-path>" Unix 域套接字
  summary?: string, // 5-10 词预览
  message: string | StructuredMessage
}
```

#### 结构化消息类型

| 类型 | 字段 | 用途 |
|------|------|------|
| `shutdown_request` | `{ type, reason }` | 请求关闭 |
| `shutdown_response` | `{ type, request_id, approve, reason }` | 同意/拒绝关闭 |
| `plan_approval_response` | `{ type, request_id, approve, feedback }` | 计划审批响应 |

#### 路由机制

```
消息路由优先级:

1. 进程内子 Agent (按名称)
   ├── 查找 appState.agentNameRegistry
   ├── 运行中: queuePendingMessage() 入队
   └── 已停止: resumeAgentBackground() 自动恢复

2. 广播 (to = "*")
   └── 写入每个队友的 mailbox（除发送者）

3. 文件邮箱 (默认)
   └── 写入 ~/.claude/teams/{teamName}/inboxes/{agentName}.json

4. 跨机器桥接 (to = "bridge:...")
   ├── postInterClaudeMessage() 发送
   └── 需要显式用户同意（安全检查）

5. UDS 套接字 (to = "uds:...")
   └── 本地 peer session 直接套接字通信
```

#### 关闭流程

```
shutdown_request → 队友收到 → agent 可批准/拒绝
├── 批准: agent 优雅退出
└── 拒绝: 继续工作
```

#### 计划审批流程

```
Team lead → plan_approval_response → team member
└── Member 检查消息 → 进入实施阶段
```

---

### 10.2 File-based Mailbox — 文件邮箱系统

**文件路径：** `source/src/utils/teammateMailbox.ts`

```
邮箱路径: ~/.claude/teams/{team_name}/inboxes/{agent_name}.json
```

#### 消息格式

```typescript
type TeammateMessage = {
  from: string,       // 发送者
  text: string,       // 消息内容
  timestamp: string,  // ISO 时间戳
  read: boolean,      // 已读标记
  color?: string,     // UI 颜色
  summary?: string    // 5-10 词预览
}
```

#### 核心函数

| 函数 | 功能 |
|------|------|
| `writeToMailbox()` | 带文件锁写入（10 次重试，5-100ms 退避） |
| `readMailbox()` | 读取所有消息 |
| `readUnreadMessages()` | 仅读取未读消息 |
| `markMessageAsReadByIndex()` | 按索引标记已读 |
| `markMessagesAsRead()` | 标记全部已读 |

#### 并发处理

```
文件锁模式:
├── proper-lockfile 库
├── 10 次重试, 5-100ms 指数退避
├── 获取锁后重读文件获取最新状态
└── Fire-and-forget 方式（不等待）避免阻塞 agent 循环
```

---

### 10.3 LocalAgentTask — 本地 Agent 任务管理

**文件路径：** `source/src/tasks/LocalAgentTask/LocalAgentTask.tsx`

跟踪通过 AgentTool 生成的本地 agent。

#### 任务状态

```typescript
type LocalAgentTaskState = TaskStateBase & {
  type: 'local_agent',
  agentId: string,
  prompt: string,
  selectedAgent?: AgentDefinition,
  agentType: string,
  isBackgrounded: boolean,
  pendingMessages: string[],    // 中途排队的消息
  retain: boolean,              // UI 保持此任务
  diskLoaded: boolean,
  ...
}
```

#### 消息传递机制

**1. Pending Message Queue — 消息排队**

```typescript
queuePendingMessage(taskId, msg, setAppState)
// SendMessage 工具在 turn 中途入队消息
// → task.pendingMessages.push(msg)
```

**2. Drain Pending Messages — 消息排空**

```typescript
drainPendingMessages(taskId, getAppState, setAppState): string[]
// 在 agent 循环边界调用
// 清空并返回所有待处理消息
// → 作为新的 user 消息注入 agent 对话
```

**3. Agent Notification — Agent 通知**

```typescript
enqueueAgentNotification({ taskId, ... })
// Agent 状态变更时入队通知到消息队列
```

#### 通知格式

```xml
<task-notification>
  <task-id>{agentId}</task-id>
  <status>completed|failed|killed</status>
  <summary>{状态摘要}</summary>
  <result>{agent 最终文本}</result>
  <usage>
    <total_tokens>N</total_tokens>
    <tool_uses>N</tool_uses>
    <duration_ms>N</duration_ms>
  </usage>
</task-notification>
```

工作者结果作为 user-role 消息到达（不是实际用户输入）。

---

### 10.4 Coordinator Mode — 协调者模式

**文件路径：** `source/src/coordinator/coordinatorMode.ts`

编排模式：协调者生成工作者并综合结果。

```
Feature gate: feature('COORDINATOR_MODE')
环境变量: CLAUDE_CODE_COORDINATOR_MODE
互斥: 与 fork subagent 模式不兼容

协调者可用工具:
├── Agent (生成工作者)
├── SendMessage (继续工作者)
├── TaskStop (停止工作者)
└── PR 订阅工具

System prompt 指示协调者指挥工作者
```

---

## 十一、In-Process Teammate — 进程内队友系统

### 11.1 TeammateContext — AsyncLocalStorage 隔离

**文件路径：** `source/src/utils/teammateContext.ts`

使用 Node.js `AsyncLocalStorage` 为进程内队友提供隔离执行上下文。

```typescript
export type TeammateContext = {
  agentId: string,              // 完整 ID, e.g. "researcher@my-team"
  agentName: string,            // 显示名称
  teamName: string,             // 团队成员身份
  color?: string,               // UI 颜色
  planModeRequired: boolean,    // Plan mode 门控
  parentSessionId: string,      // Leader 的 session ID
  isInProcess: true,            // 鉴别器
  abortController: AbortController  // 生命周期控制
}
```

#### 执行模型

```typescript
export function runWithTeammateContext<T>(
  context: TeammateContext,
  fn: () => T,
): T {
  return teammateContextStorage.run(context, fn)
}

// AsyncLocalStorage 隔离:
// 每个 teammate 有独立的上下文
// 支持并发执行无全局状态冲突
```

---

### 11.2 Teammate 身份解析

**文件路径：** `source/src/utils/teammate.ts`

多级身份解析（优先级顺序）：

```
1. AsyncLocalStorage (进程内 teammate) ← getTeammateContext()
2. dynamicTeamContext (tmux teammate, CLI 参数)
3. 环境变量:
   ├── CLAUDE_CODE_AGENT_ID
   ├── CLAUDE_CODE_AGENT_NAME
   ├── CLAUDE_CODE_TEAM_NAME
   └── CLAUDE_CODE_TEAMMATE_COLOR
```

#### 导出函数

| 函数 | 功能 |
|------|------|
| `getAgentId()` | Agent 完整 ID |
| `getAgentName()` | 显示名称 |
| `getTeamName()` | 团队名称 |
| `getTeammateColor()` | UI 颜色 |
| `isTeammate()` | 是否为 teammate |
| `isTeamLead()` | 是否为 team lead |
| `isInProcessTeammate()` | 是否为进程内 teammate |
| `getParentSessionId()` | 关联 transcript 的父 session ID |
| `hasActiveInProcessTeammates()` | 是否有活跃队友 |
| `hasWorkingInProcessTeammates()` | 是否有工作中的队友 |
| `waitForTeammatesToBecomeIdle()` | 等待所有队友空闲的 Promise |

---

### 11.3 InProcessBackend — 进程内后端

**生成 (spawn):**

```
文件: source/src/utils/swarm/spawnInProcess.ts

spawnInProcessTeammate(config, context)
├── 1. 创建独立 AbortController (不链接到父级，存活于父查询中断)
├── 2. 创建 TeammateContext
├── 3. 注册 InProcessTeammateTaskState 到 AppState
├── 4. 注册 cleanup handler
└── 返回: { success, agentId, taskId, abortController, teammateContext }
```

**执行 (run):**

```
文件: source/src/utils/swarm/inProcessRunner.ts

startInProcessTeammate(params)
├── runWithTeammateContext(ctx, async () => {
│     runWithAgentContext(agentCtx, async () => {
│       // 1. 在背景中运行 agent
│       // 2. 跟踪进度, 更新 task state
│       // 3. 处理 plan mode 审批流程
│       // 4. 轮询待处理消息 (inbox)
│       // 5. 完成时发送 idle 通知
│       // 6. abort 或 shutdown 审批后清理
│     })
│   })
```

**后端接口:**

```
文件: source/src/utils/swarm/backends/InProcessBackend.ts

实现 TeammateExecutor 接口:
├── spawn()       → spawnInProcessTeammate + startInProcessRunner
├── sendMessage() → 写入文件邮箱
├── terminate()   → 发送 shutdown 请求, 等待批准
├── kill()        → 立即 abort (AbortController)
└── isActive()    → 检查 task 运行中 + controller 未 abort
```

---

## 十二、Memory 共享矩阵与数据流总图

### Memory 共享矩阵

| 共享类型 | 作用域 | 机制 | 共享目标 | 持久性 |
|----------|--------|------|----------|--------|
| **对话上下文** | Fork | `forkContextMessages` 传递 | 子级继承完整父级对话 | Agent 生命周期 |
| **文件状态缓存** | Fork | `cloneFileStateCache()` | 子级共享父级读取缓存 | Agent 生命周期 |
| **System Prompt** | Fork & Resume | `renderedSystemPrompt` 精确字节 | 缓存一致的 API 前缀 | Agent 生命周期 |
| **待处理消息** | 本地 Agent | `pendingMessages[]` 队列 | tool 轮边界排空 | 排空前 |
| **权限模式** | 所有 Agent | `agentDefinition.permissionMode` | 子级获得自定义或父级模式 | Agent 生命周期 |
| **Agent Memory** | 所有 Agent | MEMORY.md 文件 | 通过 system prompt 注入 | 跨生成持久化 |
| **Team Context** | 进程内队友 | AsyncLocalStorage | `runWithTeammateContext()` | Teammate 生命周期 |
| **邮箱消息** | 队友间 | JSON 文件邮箱 | 邮箱轮询循环 | 读取/删除前 |
| **AppState** | 所有 Agent | `getAppState()` / `setAppState()` | 只读或通过根写入 | Session 生命周期 |
| **Worktree** | Fork Agent | `runWithCwdOverride()` | 子级在隔离目录运行 | Agent 生命周期 |

### 完整数据流总图

```
用户输入
    │
    ▼
┌─── Context 组装 ────────────────────────────────────────────┐
│ getSystemContext() → git status, injection                   │
│ getUserContext()   → CLAUDE.md 扫描, 日期                    │
│ loadMemoryPrompt() → auto memory / team memory prompt        │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌─── Query 循环入口 ──────────────────────────────────────────┐
│ startRelevantMemoryPrefetch()  [异步, 隐藏延迟]              │
│ fullSystemPrompt = appendSystemContext(systemPrompt, sysCtx) │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌─── API 前处理 ──────────────────────────────────────────────┐
│ applyToolResultBudget()  → 大结果持久化到磁盘               │
│ snipCompactIfNeeded()    → 丢弃旧消息                       │
│ microcompact()           → 缓存编辑                         │
│ contextCollapse()        → staged archives                   │
│ autocompact()            → 摘要压缩 → buildPostCompactMsgs() │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌─── 消息组装 for API ────────────────────────────────────────┐
│ 1. messagesForQuery (compact 边界后)                         │
│ 2. assistantMessages (API 响应)                              │
│ 3. toolResults (tool_result 块 + 持久化引用)                 │
│ 4. getAttachmentMessages() → 相关 memory + 技能 + 通知       │
│ 5. pendingMemoryPrefetch (如已 settled, 去重后)              │
│ 6. skillPrefetch (如已 resolved)                             │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌─── prependUserContext() ────────────────────────────────────┐
│ 包裹 userContext 为合成 user 消息:                            │
│ <system-reminder>                                            │
│   # claudeMd                                                 │
│   {{CLAUDE.md 内容}}                                         │
│   # currentDate                                              │
│   Today's date is 2026-04-12.                                │
│ </system-reminder>                                           │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌─── API 调用 ────────────────────────────────────────────────┐
│ {                                                            │
│   systemPrompt: fullSystemPrompt,                            │
│   messages: [userCtxMsg, ...query, ...assist, ...tools,      │
│              ...attachments],                                │
│   tools: toolUseContext.options.tools                         │
│ }                                                            │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌─── 工具执行 ────────────────────────────────────────────────┐
│ runTools() / StreamingToolExecutor                            │
│ ├── 包含 Memory 写入 (FileWriteTool → auto-memory 路径)      │
│ ├── Agent 生成 (AgentTool → 继承 context)                    │
│ └── 结果收集到 toolResults[]                                  │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌─── Session 持久化 ──────────────────────────────────────────┐
│ recordContentReplacement() → tool result 引用                │
│ Transcript 保存到 getTranscriptPath() (JSONL)                │
│ sessionStorage.reAppendSessionMetadata()                     │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌─── 后台提取 ────────────────────────────────────────────────┐
│ extractMemories → 后台 agent 提取持久 memory                 │
│ SessionMemory → 会话内笔记更新                               │
│ TeamMemorySync → 团队 memory 同步到服务端                     │
└──────────────────────────────────────────────────────────────┘
```

### Agent 间通信流图

```
┌──────────────────────────────────────────────────────────────┐
│ 父 Agent (主会话)                                            │
│                                                               │
│  1. AgentTool 调用 (subagent_type 或省略 = fork)              │
│  2. buildForkedMessages() 构建上下文:                         │
│     ├── 完整 assistant 消息 (所有 tool_use, thinking, text)   │
│     └── user 消息: 占位 results + directive                   │
│  3. registerAsyncAgent() → LocalAgentTaskState                │
│  4. runAgent() 后台生成                                       │
│                                                               │
│  → 收到 <task-notification> 完成通知                          │
│  → 可 SendMessage 到 agentId 继续                             │
└──────────────────────────────────────────────────────────────┘
                        │
                        │ Context 继承
                        ▼
┌──────────────────────────────────────────────────────────────┐
│ 子 Agent (Fork 或 Background)                                │
│                                                               │
│  1. runAgent({forkContextMessages, override: {systemPrompt}}) │
│  2. 继承内容:                                                │
│     ├── 完整父级对话 (forkContextMessages)                    │
│     ├── 文件读取缓存 (cloneFileStateCache)                    │
│     ├── 精确 system prompt 字节 (缓存匹配)                    │
│     └── 父级工具集 (if fork)                                  │
│  3. 执行 directive 中的任务                                   │
│  4. 提交变更, 结构化输出报告                                  │
│  5. Task 完成 → 父级收到通知                                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ 进程内 Teammate (Agent Swarms)                               │
│                                                               │
│  1. spawnInProcessTeammate() → TeammateContext                │
│     (AsyncLocalStorage 隔离)                                  │
│  2. InProcessTeammateTaskState 注册到 AppState                │
│  3. startInProcessTeammate() 启动执行循环:                    │
│     ├── runWithTeammateContext() 隔离执行                     │
│     ├── 轮询 mailbox 获取待处理消息                           │
│     └── 排空 pendingUserMessages                              │
│  4. SendMessage 写入文件邮箱                                  │
│  5. 循环: 读 inbox → 处理消息 → 回复 leader                  │
│     (或等待新消息, mailbox 轮询)                               │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ Teammate ↔ Team Lead 通信                                     │
│                                                               │
│  通道: 文件邮箱 (JSON, 带锁)                                  │
│  路径: ~/.claude/teams/{teamName}/inboxes/{agentName}.json    │
│                                                               │
│  结构化消息:                                                  │
│  ├── shutdown_request: 请求关闭                               │
│  ├── shutdown_response: 同意/拒绝关闭                         │
│  └── plan_approval_response: 计划审批                         │
│                                                               │
│  纯文本消息: 带 summary 预览                                  │
│  文件级持久化 (非内存)                                        │
│  locked writes 防并发竞争                                     │
└──────────────────────────────────────────────────────────────┘
```

---

## 十三、权限与安全机制

### Memory 写入权限

**文件路径：** `source/src/utils/permissions/filesystem.ts`

```
isAutoMemPath() 检查用于 Memory 写入豁免:
├── auto-memory 路径下的文件可以写入
│   (无需 dangerous-directory 警告)
├── FileWriteTool 检查此条件
├── 尊重 hasAutoMemPathOverride()
│   (Cowork 环境覆盖禁用豁免)
└── Agent Memory 路径同样受 isAgentMemoryPath() 保护
```

### CLAUDE.md 在权限评估中的作用

```
文件: source/src/utils/permissions/yoloClassifier.ts

cachedClaudeMdContent 可用于权限上下文:
├── 包裹在 <user_claude_md> 标签中
├── 传递给 YOLO classifier
├── 帮助判断请求操作是否与用户声明的指令一致
└── 影响自动批准/拒绝决策
```

---

## 十四、Feature Gates 与环境变量

### Feature Gates

| Gate | 功能 |
|------|------|
| `tengu_herring_clock` | 团队 memory 启用 |
| `tengu_moth_copse` | 跳过 MEMORY.md 索引在 prompt 中 / memory prefetch |
| `tengu_passport_quail` | 后台 memory 提取 agent |
| `tengu_slate_thimble` | 非交互模式 memory 提取 |
| `tengu_coral_fern` | "Searching past context" 段落 |
| `tengu_session_memory` | Session memory 功能 |
| `KAIROS` | 助手模式，追加式日志范式 |
| `EXTRACT_MEMORIES` | 后台 memory 提取 |
| `MEMORY_SHAPE_TELEMETRY` | Memory 召回分析日志 |
| `COORDINATOR_MODE` | 协调者模式 |

### 环境变量

| 变量 | 功能 |
|------|------|
| `CLAUDE_CODE_DISABLE_AUTO_MEMORY` | 完全禁用 auto-memory |
| `CLAUDE_CODE_DISABLE_CLAUDE_MDS` | 禁用 CLAUDE.md 加载 |
| `CLAUDE_CODE_REMOTE_MEMORY_DIR` | 覆盖 memory 基目录 (Cowork) |
| `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` | 完整路径覆盖 (Cowork) |
| `CLAUDE_COWORK_MEMORY_EXTRA_GUIDELINES` | 额外 memory 指南 |
| `CLAUDE_CODE_SIMPLE` / `--bare` | 禁用 CLAUDE.md 自动发现 |
| `CLAUDE_CODE_DISABLE_1M_CONTEXT` | 禁用 1M 上下文 (HIPAA) |
| `CLAUDE_CODE_COORDINATOR_MODE` | 启用协调者模式 |
| `CLAUDE_CODE_AGENT_ID` | Agent 身份 ID |
| `CLAUDE_CODE_AGENT_NAME` | Agent 显示名称 |
| `CLAUDE_CODE_TEAM_NAME` | 团队名称 |
| `CLAUDE_CODE_TEAMMATE_COLOR` | 队友 UI 颜色 |

---

## 十五、目录结构总览

```
~/.claude/
├── CLAUDE.md                                    # 用户全局指令
├── settings.json                                # 配置 (autoMemoryEnabled, autoMemoryDirectory)
├── projects/
│   └── <sanitized-git-root>/
│       ├── memory/                              # Auto-Memory (私有)
│       │   ├── MEMORY.md                        # 索引入口 (200行/25KB)
│       │   ├── *.md                             # 主题文件
│       │   ├── logs/                            # KAIROS 助手模式
│       │   │   └── YYYY/MM/YYYY-MM-DD.md        # 日志
│       │   └── team/                            # Team Memory (共享)
│       │       ├── MEMORY.md                    # 团队索引
│       │       └── *.md                         # 团队主题文件
│       └── sessionMemory/                       # Session Memory
├── agent-memory/
│   └── <agentType>/
│       └── MEMORY.md                            # Agent Memory (user 级)
└── teams/
    └── {team_name}/
        └── inboxes/
            └── {agent_name}.json                # 文件邮箱

项目根目录:
├── CLAUDE.md                                    # 项目级指令 (版本控制)
├── CLAUDE.local.md                              # 本地私有指令
├── .claude/
│   ├── CLAUDE.md                                # 替代位置
│   ├── rules/*.md                               # 规则文件
│   ├── agent-memory/
│   │   └── <agentType>/
│   │       └── MEMORY.md                        # Agent Memory (project 级)
│   ├── agent-memory-local/
│   │   └── <agentType>/
│   │       └── MEMORY.md                        # Agent Memory (本地级)
│   └── agent-memory-snapshots/
│       └── <agentType>/                         # 快照同步
│           └── *.md

/etc/claude-code/
└── CLAUDE.md                                    # Managed Memory (组织级)
```

---

## 十六、关键文件索引

### Memory 核心

| 文件 | 功能 |
|------|------|
| `source/src/memdir/paths.ts` | 路径解析与安全验证 |
| `source/src/memdir/memdir.ts` | Memory prompt 构建主入口 |
| `source/src/memdir/memoryTypes.ts` | 四类型分类体系 |
| `source/src/memdir/memoryScan.ts` | 文件发现与元数据 |
| `source/src/memdir/memoryAge.ts` | 陈旧度跟踪 |
| `source/src/memdir/findRelevantMemories.ts` | Sonnet 智能选择 |
| `source/src/memdir/teamMemPaths.ts` | 团队 memory 安全 |
| `source/src/memdir/teamMemPrompts.ts` | 团队 memory prompt |
| `source/src/utils/claudemd.ts` | CLAUDE.md 发现与加载 |
| `source/src/context.ts` | 系统/用户上下文构建 |
| `source/src/constants/prompts.ts` | System prompt 生成 |
| `source/src/utils/api.ts` | Context 注入 API |

### Memory 服务

| 文件 | 功能 |
|------|------|
| `source/src/services/extractMemories/extractMemories.ts` | 后台自动提取 |
| `source/src/services/SessionMemory/sessionMemory.ts` | 会话内记忆 |
| `source/src/services/teamMemorySync/index.ts` | 团队同步 |

### Agent 生成与上下文

| 文件 | 功能 |
|------|------|
| `source/src/tools/AgentTool/AgentTool.tsx` | Agent 生成入口 |
| `source/src/tools/AgentTool/runAgent.ts` | 核心执行 + 上下文传递 |
| `source/src/tools/AgentTool/forkSubagent.ts` | Fork 逻辑 + 模板 |
| `source/src/tools/AgentTool/agentMemory.ts` | Agent 专属 memory |
| `source/src/tools/AgentTool/agentMemorySnapshot.ts` | 快照同步 |
| `source/src/tools/AgentTool/resumeAgent.ts` | Agent 恢复 |

### Agent 通信

| 文件 | 功能 |
|------|------|
| `source/src/tools/SendMessageTool/SendMessageTool.ts` | 消息路由 |
| `source/src/utils/teammateMailbox.ts` | 文件邮箱系统 |
| `source/src/utils/teammate.ts` | 身份解析 |
| `source/src/utils/teammateContext.ts` | AsyncLocalStorage 上下文 |
| `source/src/utils/swarm/spawnInProcess.ts` | 进程内生成 |
| `source/src/utils/swarm/inProcessRunner.ts` | 进程内执行循环 |
| `source/src/utils/swarm/backends/InProcessBackend.ts` | 进程内后端接口 |
| `source/src/tasks/LocalAgentTask/LocalAgentTask.tsx` | 本地 Agent 任务管理 |
| `source/src/tasks/InProcessTeammateTask/InProcessTeammateTask.tsx` | 进程内队友组件 |
| `source/src/coordinator/coordinatorMode.ts` | 协调者模式 |

### 状态与持久化

| 文件 | 功能 |
|------|------|
| `source/src/bootstrap/state.ts` | 全局 Bootstrap 状态 |
| `source/src/utils/sessionStorage.ts` | Session 持久化 |
| `source/src/utils/sessionRestore.ts` | Session 恢复 |
| `source/src/utils/toolResultStorage.ts` | Tool 结果存储 |
| `source/src/utils/attachments.ts` | Memory 附件 + prefetch |

---

> **分析结论：** Claude Code 的 Memory 系统是一个精心设计的多层持久化架构。核心创新在于：
> 1. **四层 CLAUDE.md 优先级** 实现组织→用户→项目→本地的指令继承
> 2. **Sonnet 侧查询** 在流式响应期间异步选择相关 memory（隐藏延迟）
> 3. **文件邮箱 + AsyncLocalStorage** 实现高效的 Agent 间通信
> 4. **Fork 模式** 通过精确字节复制 system prompt 实现 API 缓存匹配
> 5. **三作用域 Agent Memory** (user/project/local) 支持不同粒度的持久化
