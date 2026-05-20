# Claude Code 深度系统学习指南：会话记录、工具编排与多Agent通信全流程

> 基于 `@anthropic-ai/claude-code@2.1.88` 源码深度分析
> 目标：彻底理解 `.jsonl` 会话文件的完整结构、工具编排全流程、多Agent通信机制，为自行构建类似系统提供完整参考。

---

## 目录

1. [.jsonl 会话文件完整解剖](#1-jsonl-会话文件完整解剖)
2. [会话持久化全流程](#2-会话持久化全流程)
3. [系统提示词组装流程](#3-系统提示词组装流程)
4. [Query Loop 主循环详解](#4-query-loop-主循环详解)
5. [工具编排系统](#5-工具编排系统)
6. [工具执行管线](#6-工具执行管线)
7. [权限系统](#7-权限系统)
8. [Hook 系统](#8-hook-系统)
9. [消息压缩（Compaction）机制](#9-消息压缩compaction机制)
10. [多Agent系统架构](#10-多agent系统架构)
11. [构建你自己的系统：架构设计指南](#11-构建你自己的系统架构设计指南)

---

## 1. .jsonl 会话文件完整解剖

### 1.1 文件位置与命名

**源码文件**: `utils/sessionStorage.ts:202-260`

```
~/.claude/projects/
  └── <sanitized-project-path>/          # 项目路径经 sanitizePath() 处理
      ├── <session-uuid>.jsonl           # 主会话 transcript
      ├── <session-uuid>/
      │   ├── subagents/
      │   │   ├── agent-<agent-id>.jsonl      # 子agent独立transcript
      │   │   ├── agent-<agent-id>.meta.json  # 子agent元数据
      │   │   └── <subdir>/                   # 分组子目录（如workflows/）
      │   │       └── agent-<agent-id>.jsonl
      │   └── remote-agents/
      │       └── remote-agent-<task-id>.meta.json
```

**路径生成函数**:
- `getTranscriptPath()` → 当前session的 `.jsonl` 路径 (line 202)
- `getTranscriptPathForSession(sessionId)` → 指定session的路径 (line 207)
- `getAgentTranscriptPath(agentId)` → 子agent的transcript路径 (line 247)
- `getProjectDir(projectPath)` → 项目目录（`sanitizePath` + hash截断）(line 436)

**路径清理规则** (`sessionStoragePortable.ts:311-319`):
- 非字母数字字符替换为 `-`
- 路径超过200字符时，使用 `djb2Hash` 生成后缀截断

### 1.2 .jsonl 文件中的 Entry 类型完整列表

**源码文件**: `types/logs.ts:297-317`

每一行是一个独立的 JSON 对象（JSONL格式），由以下 Entry 类型之一组成：

```typescript
type Entry =
  | TranscriptMessage           // 用户/助手/附件/系统消息（核心对话内容）
  | SummaryMessage              // Compaction 压缩摘要
  | CustomTitleMessage          // 用户手动重命名的会话标题
  | AiTitleMessage              // AI 自动生成的会话标题
  | LastPromptMessage           // 最近一次用户输入（用于 --resume 展示）
  | TaskSummaryMessage          // 定期fork生成的任务摘要
  | TagMessage                  // 会话标签（支持搜索）
  | AgentNameMessage            // Agent 自定义名称
  | AgentColorMessage           // Agent 颜色标识
  | AgentSettingMessage         // 使用的 Agent 定义
  | PRLinkMessage               // 关联的 GitHub PR 链接
  | FileHistorySnapshotMessage  // 文件编辑历史快照
  | AttributionSnapshotMessage  // 文件归属追踪（谁写了哪些代码）
  | QueueOperationMessage       // 消息队列状态操作
  | SpeculationAcceptMessage    // 推测执行结果
  | ModeEntry                   // coordinator vs normal 模式
  | WorktreeStateEntry          // Worktree 会话状态
  | ContentReplacementEntry     // 内容替换存根
  | ContextCollapseCommitEntry  // 上下文折叠提交
  | ContextCollapseSnapshotEntry // 上下文折叠快照
```

### 1.3 TranscriptMessage 完整 Schema

这是最核心的消息类型，包含所有对话内容。

**源码文件**: `types/logs.ts:8-231`

```typescript
// 首先继承 Message 类型的所有字段
type TranscriptMessage = Message & {
  // === 序列化上下文字段 (SerializedMessage) ===
  cwd: string                    // 消息产生时的工作目录
  userType: string               // 'external'（用户）或 'internal'（Ant内部）
  entrypoint?: string            // 入口点标识：'cli' | 'sdk-ts' | 'sdk-py' 等
  sessionId: string              // 会话 UUID（fork/resume时重新盖章）
  timestamp: string              // ISO 时间戳
  version: string                // Claude Code 版本号
  gitBranch?: string             // 消息时的 git 分支名
  slug?: string                  // 会话 slug（用于 plan 文件等）

  // === Transcript 链接字段 ===
  parentUuid: UUID | null        // 父消息UUID（形成消息链）
  logicalParentUuid?: UUID | null // 逻辑父UUID（compaction时保留）
  isSidechain: boolean           // true=子agent消息，false=主会话
  agentId?: string               // 子agent ID（sidechain transcript用）
  teamName?: string              // 团队名称（swarm模式）
  agentName?: string             // Agent 自定义名称
  agentColor?: string            // Agent 颜色
  promptId?: string              // OTel关联ID
}
```

### 1.4 消息内容的 content 字段结构

#### 用户消息 (type: 'user')

```jsonc
{
  "type": "user",
  "uuid": "550e8400-...",
  "parentUuid": "6ba7b810-...",
  "isSidechain": false,
  "message": {
    "content": [
      // 情况1: 纯文本
      { "type": "text", "text": "请帮我修复这个bug" },
      
      // 情况2: 图片
      { "type": "image", "source": { "type": "base64", "data": "...", "media_type": "image/png" } },
      
      // 情况3: 工具结果（tool_result）
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01abc...",      // 对应 tool_use 的 id
        "content": "文件内容或执行结果...",      // 工具执行输出
        "is_error": false                      // 是否为错误结果
      },
      
      // 情况4: 文档
      { "type": "document", "source": { "type": "base64", "data": "...", "media_type": "application/pdf" } }
    ]
  },
  // 元数据
  "cwd": "/home/user/project",
  "userType": "external",
  "sessionId": "abc-123",
  "timestamp": "2026-04-16T10:30:00.000Z",
  "version": "2.1.88"
}
```

#### 助手消息 (type: 'assistant')

```jsonc
{
  "type": "assistant",
  "uuid": "7c9e8f00-...",
  "parentUuid": "550e8400-...",
  "isSidechain": false,
  "message": {
    "content": [
      // 文本响应
      { "type": "text", "text": "我来帮你修复这个问题。" },
      
      // 思考过程（extended thinking启用时）
      { "type": "thinking", "thinking": "让我分析这个bug的根本原因..." },
      
      // 工具调用
      {
        "type": "tool_use",
        "id": "toolu_01abc...",               // 唯一工具调用ID
        "name": "Read",                        // 工具名称
        "input": {                             // 工具参数（Zod schema验证后的）
          "file_path": "/src/main.ts",
          "offset": 0,
          "limit": 100
        }
      }
    ],
    // API使用统计
    "usage": {
      "input_tokens": 15234,
      "output_tokens": 892,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 12000
    }
  },
  "cwd": "/home/user/project",
  "sessionId": "abc-123",
  "timestamp": "2026-04-16T10:30:05.000Z",
  "version": "2.1.88"
}
```

### 1.5 元数据条目详细结构

这些条目穿插在消息之间，由 `reAppendSessionMetadata()` 在 compaction 和退出时重写到文件末尾。

```jsonc
// 最近一次用户输入（用于 --resume 列表展示）
{"type":"last-prompt","lastPrompt":"请帮我修复这个bug","sessionId":"abc-123"}

// 用户自定义标题
{"type":"custom-title","customTitle":"修复登录bug","sessionId":"abc-123"}

// AI生成的标题
{"type":"ai-title","aiTitle":"Fix login authentication bug","sessionId":"abc-123"}

// 会话标签
{"type":"tag","tag":"bugfix","sessionId":"abc-123"}

// Agent 名称和颜色
{"type":"agent-name","agentName":"code-reviewer","sessionId":"abc-123"}
{"type":"agent-color","agentColor":"#FF5733","sessionId":"abc-123"}

// 使用的Agent定义
{"type":"agent-setting","agentSetting":"explore","sessionId":"abc-123"}

// GitHub PR 关联
{"type":"pr-link","sessionId":"abc-123","prNumber":42,"prUrl":"https://github.com/org/repo/pull/42","prRepository":"org/repo","timestamp":"2026-04-16T10:30:00Z"}

// 工作模式
{"type":"mode","mode":"coordinator","sessionId":"abc-123"}

// Worktree 状态
{"type":"worktree-state","sessionId":"abc-123","worktreeSession":{"originalCwd":"/src","worktreePath":"/tmp/wt-abc","worktreeName":"agent-abc12345","worktreeBranch":"agent-abc12345"}}

// Compaction 摘要
{"type":"summary","leafUuid":"xxx-xxx","summary":"用户正在调试登录模块的认证问题..."}

// 任务摘要（后台agent进度）
{"type":"task-summary","sessionId":"abc-123","summary":"正在搜索相关文件并分析代码结构","timestamp":"2026-04-16T10:35:00Z"}

// 文件编辑历史快照
{"type":"file-history-snapshot","messageId":"uuid-xxx","snapshot":{...},"isSnapshotUpdate":false}

// 文件归属快照
{"type":"attribution-snapshot","messageId":"uuid-xxx","surface":"cli","fileStates":{"src/main.ts":{"contentHash":"sha256-xxx","claudeContribution":1500,"mtime":1713267000000}},"promptCount":15}

// 推测执行
{"type":"speculation-accept","timestamp":"2026-04-16T10:30:00Z","timeSavedMs":1200}

// 内容替换存根
{"type":"content-replacement","sessionId":"abc-123","replacements":[{"toolUseId":"toolu_xxx","replacementType":"disk","path":"/tmp/result.txt"}]}

// Compaction 边界标记
{"type":"system","subtype":"compact_boundary","compactMetadata":{"preservedSegment":false},...}

// 上下文折叠提交
{"type":"marble-origami-commit","sessionId":"abc-123","collapseId":"0000000000000001","summaryUuid":"uuid-xxx","summaryContent":"<collapsed id=\"1\">摘要内容</collapsed>","summary":"摘要文本","firstArchivedUuid":"uuid-start","lastArchivedUuid":"uuid-end"}

// 上下文折叠快照
{"type":"marble-origami-snapshot","sessionId":"abc-123","staged":[{"startUuid":"...","endUuid":"...","summary":"...","risk":0.3,"stagedAt":1713267000000}],"armed":true,"lastSpawnTokens":50000}
```

### 1.6 一个完整的 .jsonl 文件示例（包含所有类型）

```
<第1行> {"type":"mode","mode":"normal","sessionId":"abc-123"}
<第2行> {"type":"user","uuid":"u1","parentUuid":null,"isSidechain":false,"message":{"content":[{"type":"text","text":"帮我读取main.ts"}]},"cwd":"/project","userType":"external","sessionId":"abc-123","timestamp":"2026-04-16T10:00:00Z","version":"2.1.88","gitBranch":"main"}
<第3行> {"type":"assistant","uuid":"a1","parentUuid":"u1","isSidechain":false,"message":{"content":[{"type":"text","text":"我来读取这个文件。"},{"type":"tool_use","id":"toolu_001","name":"Read","input":{"file_path":"/project/main.ts"}}],"usage":{"input_tokens":5000,"output_tokens":200}},"cwd":"/project","sessionId":"abc-123","timestamp":"2026-04-16T10:00:02Z","version":"2.1.88"}
<第4行> {"type":"user","uuid":"u2","parentUuid":"a1","isSidechain":false,"message":{"content":[{"type":"tool_result","tool_use_id":"toolu_001","content":"// main.ts内容...","is_error":false}]},"cwd":"/project","sessionId":"abc-123","timestamp":"2026-04-16T10:00:03Z","version":"2.1.88"}
<第5行> {"type":"assistant","uuid":"a2","parentUuid":"u2","isSidechain":false,"message":{"content":[{"type":"text","text":"文件内容如上所示。这个文件包含..."}],"usage":{"input_tokens":6000,"output_tokens":500}},"cwd":"/project","sessionId":"abc-123","timestamp":"2026-04-16T10:00:05Z","version":"2.1.88"}
<第6行> {"type":"file-history-snapshot","messageId":"a1","snapshot":{"files":{"main.ts":{"hash":"sha256-xxx"}}},"isSnapshotUpdate":false}
<第7行> {"type":"last-prompt","lastPrompt":"帮我读取main.ts","sessionId":"abc-123"}
```

---

## 2. 会话持久化全流程

### 2.1 写入流程概览

**核心类**: `Project`（`sessionStorage.ts:532+`）

```
用户输入/API响应
    ↓
recordTranscript(messages)          ← sessionStorage.ts:1408
    ↓
cleanMessagesForLogging(messages)   ← 清理消息（过滤临时数据）
    ↓
检查 UUID 去重 (messageSet)          ← 防止重复写入
    ↓
Project.insertMessageChain()        ← sessionStorage.ts:993
    │
    ├── 首次写入 → materializeSessionFile()   ← 创建文件+写metadata
    │   ├── ensureCurrentSessionFile()        ← 确定文件路径
    │   ├── reAppendSessionMetadata()         ← 写入初始metadata
    │   └── 刷出 pendingEntries 缓冲          ← 将预缓冲的条目写出
    │
    ├── 获取 gitBranch, slug                  ← 上下文快照
    │
    └── for each message:
        ├── 构建 TranscriptMessage            ← 注入 cwd, sessionId, version等
        ├── 设置 parentUuid 链                ← 消息链接
        ├── appendEntry(transcriptMessage)     ← sessionStorage.ts:1128
        │   ├── 按类型路由:
        │   │   ├── metadata类型 → 直接 enqueueWrite
        │   │   ├── sidechain → 写入 agent transcript
        │   │   └── 主会话消息 → 去重后 enqueueWrite
        │   │
        │   └── persistToRemote()             ← 远程持久化（CCR/Ingress）
        │
        └── 更新 parentUuid 游标
```

### 2.2 写入队列系统

**源码**: `sessionStorage.ts:550-686`

```typescript
class Project {
  private pendingEntries: Entry[] = []           // 预materialization缓冲
  private writeQueues = new Map<string, Entry[]> // 每文件写入队列
  private flushTimer: setTimeout | null          // 定时刷出
  private FLUSH_INTERVAL_MS = 100                // 默认100ms（远程CCR为10ms）
  private MAX_CHUNK_BYTES = 100_000_000          // 单次写入最大100MB
}
```

**刷出流程**:

```
enqueueWrite(filePath, entry)
    ↓
scheduleDrain()           ← 设置 100ms 定时器
    ↓
drainWriteQueue()         ← 定时器触发
    ├── 遍历所有文件队列
    ├── 批量序列化: jsonStringify(entry) + '\n'
    ├── 分块写入（不超过 MAX_CHUNK_BYTES）
    ├── appendToFile(filePath, content)  ← 权限 0o600
    └── 清空已写入队列
```

**关键细节**:
- 首条 user/assistant 消息触发 `materializeSessionFile()` 创建文件
- hook/attachment消息单独存在时只进入 `pendingEntries` 缓冲，不触发文件创建
- 进程退出时 `flushSessionStorage()` 等待所有 pending 写入完成
- Sidechain（子agent）消息写入独立的 agent transcript 文件
- UUID去重：`messageSet` 跟踪已写入消息，防止重复

### 2.3 EOF Metadata 机制

**源码**: `sessionStorage.ts:721-839`

元数据被写入文件末尾（EOF），原因是 `readLiteMetadata()` 只读取最后 64KB（`LITE_READ_BUF_SIZE`）来快速展示 `--resume` 列表。

在以下时机重写metadata：
1. **Compaction期间**: 在 boundary marker 之前写入
2. **退出时**: 写在文件末尾

**SDK兼容性**: 外部SDK可能通过 `renameSession/tagSession` 写入 custom-title/tag。CLI在重写前先读取尾部扫描窗口，吸收SDK写入的较新值。

### 2.4 消息链 (Message Chain)

每条消息通过 `parentUuid` 链接到前一条消息，形成有向链表：

```
user(u1) → assistant(a1) → user(u2/tool_result) → assistant(a2) → ...
                                ↑
                     sourceToolAssistantUUID = a1
```

**特殊处理**:
- `tool_result` 消息的 `parentUuid` 使用 `sourceToolAssistantUUID`（直接指向发出 tool_use 的 assistant 消息）
- Compact boundary 消息的 `parentUuid` 设为 `null`，`logicalParentUuid` 保留逻辑链接
- Sidechain 消息不加入主 `messageSet`，避免UUID冲突

---

## 3. 系统提示词组装流程

### 3.1 组装入口

**源码**: `constants/prompts.ts:444` (`getSystemPrompt()`)

系统提示词分为**静态可缓存部分**和**动态部分**，由 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` 分隔。

```
getSystemPrompt()
    ├── [静态/可缓存] ─────────────────────────
    │   ├── getSimpleIntroSection()         ← 角色定义、安全准则
    │   ├── getSimpleSystemSection()        ← 系统行为指南
    │   ├── getSimpleDoingTasksSection()    ← 任务执行规范、代码风格
    │   ├── getActionsSection()             ← 可逆性和风险提示
    │   ├── getUsingYourToolsSection()      ← 工具使用偏好
    │   └── getSimpleToneAndStyleSection()  ← 沟通风格
    │
    ├── ── SYSTEM_PROMPT_DYNAMIC_BOUNDARY ──
    │
    └── [动态/session-specific] ────────────
        ├── getSessionSpecificGuidanceSection() ← Agent/Skill/权限指导
        ├── loadMemoryPrompt()                  ← 记忆系统指令
        ├── getAntModelOverrideSection()        ← Ant内部配置
        ├── computeSimpleEnvInfo()              ← 环境信息（模型、平台、Shell等）
        ├── getLanguageSection()                ← 语言偏好
        ├── getOutputStyleSection()             ← 输出风格配置
        ├── getMcpInstructionsSection()         ← MCP服务器说明
        ├── getScratchpadInstructions()         ← 临时文件指导
        └── getFunctionResultClearingSection()  ← 缓存微压缩指导
```

### 3.2 上下文注入

**源码**: `context.ts:116-155`、`utils/api.ts:437-449`

```
// 系统上下文（附加到system prompt末尾）
appendSystemContext(systemPrompt, systemContext)
  └── systemContext 包含:
      ├── gitStatus        ← git branch, status, recent commits
      └── systemPromptInjection ← 从 getSystemContext() 获取

// 用户上下文（创建meta用户消息，置于消息序列开头）
prependUserContext(messages, userContext)
  └── userContext 包含:
      ├── claudeMd         ← CLAUDE.md 文件内容
      ├── userEmail        ← 用户邮箱
      ├── currentDate      ← 当前日期
      └── ... 其他用户级上下文
```

---

## 4. Query Loop 主循环详解

### 4.1 核心循环结构

**源码**: `query.ts:220-1730`

```typescript
// 入口
async function* query(params: QueryParams): AsyncGenerator<...> {
  yield* queryLoop(state)
}

// 主循环
async function* queryLoop(initialState): AsyncGenerator<...> {
  let state = initialState
  
  while (true) {  // 无限循环，直到退出条件满足
    // ====== 每轮迭代 ======
    
    // 1. 解构当前状态
    const { messages, toolUseContext, turnCount, ... } = state
    
    // 2. 历史裁剪 (HISTORY_SNIP)
    // 3. 微压缩 (microcompact)
    // 4. 上下文折叠 (context collapse)
    // 5. 自动压缩检查 (autocompact)
    
    // 6. 组装系统提示词
    const fullSystemPrompt = asSystemPrompt(
      appendSystemContext(systemPrompt, systemContext)
    )
    
    // 7. 硬token限制检查
    
    // 8. API 流式调用
    for await (const message of deps.callModel({
      messages: prependUserContext(messagesForQuery, userContext),
      systemPrompt: fullSystemPrompt,
      tools: toolUseContext.options.tools,
      ...
    })) {
      // 处理流式响应
      yield message  // 传给UI/SDK
      收集 assistantMessages[]
      提取 toolUseBlocks[]
      StreamingToolExecutor.addTool()  // 并行启动工具
    }
    
    // 9. 后流式处理
    //    - executePostSamplingHooks()
    //    - 检查 abort
    //    - 产出 pending tool summary
    
    // 10. 如果没有 tool_use → 尝试恢复或退出
    if (!needsFollowUp) {
      // 尝试: reactive compact, context collapse drain, max_output recovery
      // 执行 stop hooks
      // 检查 token budget
      return { reason: 'completed' }
    }
    
    // 11. 执行工具
    const toolUpdates = streamingToolExecutor
      ? streamingToolExecutor.getRemainingResults()
      : runTools(toolUseBlocks, ...)
    
    for await (const update of toolUpdates) {
      yield update.message      // 工具结果传给UI
      toolResults.push(...)     // 收集结果
    }
    
    // 12. 收集附件 (attachments)
    //     - 文件变更
    //     - 记忆文件
    //     - 队列命令
    //     - 技能发现
    
    // 13. 递归准备
    state = {
      messages: [...messagesForQuery, ...assistantMessages, ...toolResults, ...attachments],
      toolUseContext: updated,
      turnCount: turnCount + 1,
    }
    continue  // 回到 while(true) 开头
  }
}
```

### 4.2 API 调用详细流程

**源码**: `services/api/claude.ts:1017+`

```
queryModel(messages, systemPrompt, tools, ...)
    ├── 1. 检查功能开关（off-switch）
    ├── 2. 提取前一个请求ID（关联请求）
    ├── 3. 合并 beta headers（工具搜索、思考模式等）
    ├── 4. 生成工具 schemas: toolToAPISchema() × N
    ├── 5. 分离 deferred tools（延迟加载的工具）
    ├── 6. 确定全局缓存作用域
    ├── 7. 消息规范化: normalizeMessagesForAPI()
    ├── 8. 指纹去重
    ├── 9. 构建系统提示词块 + 缓存标记
    └── 10. 发起流式 API 调用
         params = {
           model: resolvedModel,
           messages: normalizedMessages,
           system: systemPromptBlocks,
           tools: toolSchemas,
           max_tokens: computed,
           temperature: ...,
           thinking: ...,
         }
```

### 4.3 消息规范化

**源码**: `utils/messages.ts:1989` (`normalizeMessagesForAPI()`)

```
内部 Message[] → API 兼容格式
    ├── 重排附件消息（向上冒泡到合适位置）
    ├── 过滤虚拟消息（display-only）
    ├── 处理错误块（过大PDF/图片）
    ├── 仅保留 user/assistant/attachment/system 类型
    ├── 合并连续 user 消息（Bedrock兼容）
    ├── 移除 tool_reference 块（工具搜索关闭时）
    └── 插入 ensureToolResultPairing()
        ↑ 为孤立的 tool_use 插入合成 tool_result（API要求配对）
```

---

## 5. 工具编排系统

### 5.1 工具注册与发现

**源码**: `tools.ts:193-299`

```typescript
// 主注册表
function getAllBaseTools(): Tool[] {
  return [
    // 文件操作
    FileReadTool, FileEditTool, FileWriteTool, GlobTool, GrepTool,
    // 执行
    BashTool, PowerShellTool, AgentTool,
    // 外部
    WebSearchTool, WebFetchTool, MCPTool,
    // 交互
    AskUserQuestionTool, SendMessageTool,
    // 系统
    TaskCreateTool, EnterWorktreeTool, SkillTool,
    // 条件工具（Feature Flag控制）
    ...(feature('SLEEP_TOOL') ? [SleepTool] : []),
    ...(feature('MONITOR_TOOL') ? [MonitorTool] : []),
    // ... 共80+工具
  ]
}

// 过滤器
function getTools(permissionContext): Tools {
  const allTools = getAllBaseTools()
  // 1. 模式过滤（SIMPLE/COORDINATOR）
  // 2. 权限deny规则过滤
  return filterToolsByDenyRules(allTools, permissionContext)
}
```

### 5.2 工具 Schema 发送给 API

**源码**: `utils/api.ts:119-266` (`toolToAPISchema()`)

```
Tool 定义
    ↓
toolToAPISchema(tool, options)
    ├── 缓存检查（按 tool.name 或 name:inputJSONSchema hash）
    │
    ├── 生成 schema:
    │   ├── name: tool.name
    │   ├── description: tool.prompt()    ← 动态生成的工具描述
    │   ├── input_schema:
    │   │   ├── MCP工具: 直接使用 inputJSONSchema
    │   │   └── 内置工具: zodToJsonSchema(tool.inputSchema)
    │   ├── strict?: boolean              ← 严格模式
    │   └── eager_input_streaming?: true   ← 细粒度流式
    │
    ├── 请求级覆盖:
    │   ├── defer_loading: true           ← 延迟加载的工具
    │   └── cache_control: {...}          ← 提示缓存控制
    │
    └── 返回 BetaTool schema
```

### 5.3 Tool Search（工具搜索/延迟加载）

**源码**: `utils/toolSearch.ts`

当工具数量过多时，不全部发送给API，而是使用 `ToolSearchTool` 让模型按需搜索：

```
启用条件：工具占用 ≥ 上下文窗口的 ~10%

流程：
1. 标记大部分工具为 defer_loading: true（只发名称，不发schema）
2. 模型可调用 ToolSearchTool(query) 搜索匹配的工具
3. 搜索结果中的工具名被追踪在 extractDiscoveredToolNames()
4. 后续对已发现工具的调用正常执行
```

### 5.4 工具池组装 (Per-Turn)

**源码**: `query.ts:561-572`、`utils/toolPool.ts`

```
每轮迭代:
    ├── toolUseContext.options.tools = getTools(permissionContext)
    ├── 创建 StreamingToolExecutor（如果启用）
    └── 传给 callModel():
        tools: toolUseContext.options.tools

工具刷新（轮间）:
    └── refreshTools()   ← MCP 服务器可能重连，新增工具
```

---

## 6. 工具执行管线

### 6.1 完整执行流水线

**核心文件**:
- `services/tools/toolExecution.ts` — 完整执行管线
- `services/tools/toolOrchestration.ts` — 批处理和并发
- `services/tools/StreamingToolExecutor.ts` — 流式并行执行

```
query.ts 检测到 tool_use blocks
    ↓
┌─────────────────────────────────────────────────────┐
│  runTools() (toolOrchestration.ts:19)                │
│                                                      │
│  partitionToolCalls()  ← 分组并发/串行              │
│    ├── Batch 1: [工具A, 工具B]  → 并发安全 → runToolsConcurrently()
│    └── Batch 2: [工具C]         → 非并发安全 → runToolsSerially()
│                                                      │
│  对每个 tool_use block:                              │
│    runToolUse()                                      │
│      ├── 工具名查找                                  │
│      ├── Abort 检查                                  │
│      └── streamedCheckPermissionsAndCallTool()       │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│  streamedCheckPermissionsAndCallTool()               │
│  (toolExecution.ts:615+)                             │
│                                                      │
│  1. INPUT VALIDATION                                 │
│     ├── Zod schema 验证 (line 615)                   │
│     └── tool.validateInput() (line 683)              │
│                                                      │
│  2. PRE-TOOL HOOKS                                   │
│     ├── executePreToolHooks() (line 800)             │
│     ├── 处理 hook 结果: 消息、权限、输入修改         │
│     └── 超过500ms时产出 hook 摘要 (line 874)         │
│                                                      │
│  3. PERMISSION CHECK                                 │
│     ├── 推测性 bash 分类器 (line 746, 并行)          │
│     ├── resolveHookPermissionDecision() (line 921)   │
│     └── canUseTool() 回调 (line 924)                 │
│         ├── checkRuleBasedPermissions()              │
│         │   ├── alwaysAllowRules                     │
│         │   ├── alwaysDenyRules                      │
│         │   └── alwaysAskRules                       │
│         └── tool.checkPermissions()                  │
│                                                      │
│  4. PERMISSION DECISION                              │
│     ├── 'allow' → 继续执行                          │
│     ├── 'deny'  → 返回错误消息 (line 1064)          │
│     └── 'ask'   → 用户交互提示                      │
│                                                      │
│  5. TELEMETRY                                        │
│     ├── startToolSpan() (line 909)                   │
│     └── 工具耗时追踪 (line 1223)                     │
│                                                      │
│  6. TOOL EXECUTION                                   │
│     tool.call(processedInput, context, canUseTool,   │
│               assistantMessage, onProgress)           │
│     (line 1207)                                      │
│                                                      │
│     → 返回 ToolResult<Output>:                       │
│       {                                              │
│         data: T,                    // 工具输出       │
│         newMessages?: Message[],    // 新增消息       │
│         contextModifier?: fn,       // 上下文更新     │
│         mcpMeta?: { _meta, structuredContent }        │
│       }                                              │
│                                                      │
│  7. RESULT MAPPING                                   │
│     ├── tool.mapToolResultToToolResultBlockParam()   │
│     ├── 大结果 → 持久化到磁盘 (> maxResultSizeChars)│
│     └── → ToolResultBlockParam                       │
│                                                      │
│  8. POST-TOOL HOOKS                                  │
│     ├── runPostToolUseHooks() (line 1483)            │
│     ├── MCP工具: hook可修改输出                      │
│     └── 超过500ms时产出 hook 摘要                    │
│                                                      │
│  9. RESULT MESSAGE CREATION                          │
│     addToolResult() (line 1403)                      │
│     → createUserMessage({                            │
│         content: [{ type:'tool_result', ... }],      │
│         sourceToolAssistantUUID: parentAssistantId   │
│       })                                             │
└─────────────────────────────────────────────────────┘
```

### 6.2 并发 vs 串行执行

**源码**: `toolOrchestration.ts:19-82`

```typescript
function partitionToolCalls(toolUseBlocks, tools): ToolUseBlock[][] {
  // 规则：
  // 1. 并发安全的工具（tool.isConcurrencySafe(input) === true）分在同一批
  // 2. 非并发安全的工具单独一批
  // 3. 同一批内的工具并行执行，批次间串行
  
  // 例如：[Read, Read, Bash, Grep] → [[Read, Read], [Bash], [Grep]]
  //  第1批并行执行两个Read，完成后执行Bash，再执行Grep
}
```

### 6.3 流式工具执行

**源码**: `StreamingToolExecutor.ts`

```
API 流式响应期间:
    model 产出 tool_use block
        ↓
    StreamingToolExecutor.addTool(toolUseBlock)
        ↓
    processQueue() → executeTool() [并行启动]
        ↓
    工具在模型继续流式输出时就开始执行
        ↓
    模型完成后:
    streamingToolExecutor.getRemainingResults()
        ← 等待所有工具完成，收集结果
```

优势：工具不需要等待模型完全结束才开始执行。

### 6.4 工具结果大小管理

```
tool.maxResultSizeChars: 结果字符限制
    ├── 超限 → processToolResultBlock() 持久化到磁盘
    │          返回预览 + 文件路径
    ├── FileReadTool 设为 Infinity（防止循环读取）
    └── applyToolResultBudget() (query.ts:380) 全局预算
```

### 6.5 buildTool() 工具定义模式

每个工具目录下的实现遵循统一模式:

```typescript
// 示例: tools/FileReadTool/FileReadTool.ts
export function buildTool(): Tool<FileReadInput, FileReadOutput> {
  return {
    name: 'Read',
    
    // 动态生成工具描述（发送给API）
    prompt(options): string {
      return `Reads a file from the local filesystem...`
    },
    
    // Zod输入schema
    inputSchema: z.object({
      file_path: z.string(),
      offset: z.number().optional(),
      limit: z.number().optional(),
    }),
    
    // 工具执行
    async call(input, context, canUseTool, assistant, onProgress): Promise<ToolResult<FileReadOutput>> {
      const content = await readFile(input.file_path)
      return { data: { content } }
    },
    
    // 结果映射（转换为API格式）
    mapToolResultToToolResultBlockParam(output, toolUseId): ToolResultBlockParam {
      return {
        type: 'tool_result',
        tool_use_id: toolUseId,
        content: output.content,
      }
    },
    
    // 并发安全性
    isConcurrencySafe(input): boolean {
      return true  // 读取操作是安全的
    },
    
    // 只读性
    isReadOnly(input): boolean {
      return true
    },
    
    // 权限检查
    checkPermissions(input, context): PermissionResult {
      return { behavior: 'allow' }
    },
  }
}
```

---

## 7. 权限系统

### 7.1 权限模式

**源码**: `types/permissions.ts`、`utils/permissions/`

| 模式 | 说明 | 行为 |
|------|------|------|
| `default` | 正常模式 | 交互式权限提示，用户可单次/永久允许或拒绝 |
| `plan` | 计划模式 | 所有工具被阻塞，用户审查计划后再执行 |
| `auto` | 自动模式 | Transcript分类器自动评估工具安全性 |
| `acceptEdits` | 接受编辑 | 文件编辑自动允许 |
| `bypassPermissions` | 跳过权限 | 所有工具自动允许 |
| `dontAsk` | 不询问 | 不安全操作直接拒绝而非询问 |

### 7.2 权限检查流程

```
resolveHookPermissionDecision()
    ├── [Hook决定] → 使用hook结果
    │   └── hook 可返回 'allow' | 'deny' | 'ask'
    │
    └── [否则] → canUseTool()
        ├── 执行 bash 分类器（推测性，并行）
        ├── 评估权限规则:
        │   ├── checkRuleBasedPermissions()
        │   │   ├── alwaysAllowRules   ← 永久允许规则
        │   │   ├── alwaysDenyRules    ← 永久拒绝规则
        │   │   └── alwaysAskRules     ← 永久询问规则
        │   └── tool.checkPermissions()
        │
        ├── Auto模式: 分类器 + 拒绝追踪
        └── 返回 PermissionResult
            {
              behavior: 'allow' | 'deny' | 'ask',
              updatedInput?: 修改后的输入,
              message?: 拒绝原因,
              decisionReason?: { type, ...metadata }
            }
```

### 7.3 权限规则结构

```typescript
{
  source: 'localSettings' | 'userSettings' | 'cliArg' | 'session' | 'policySettings',
  rules: {
    tool: 'Bash(git *)',  // 工具名+内容模式匹配
    allow?: ToolPermissionRulesBySource,
    deny?: ToolPermissionRulesBySource,
    ask?: ToolPermissionRulesBySource
  }
}
```

---

## 8. Hook 系统

### 8.1 Hook 类型

**源码**: `utils/hooks/`、`services/tools/toolHooks.ts`

| Hook类型 | 触发时机 | 能力 |
|----------|----------|------|
| PreToolUse | 工具执行前（权限检查前） | 修改输入、覆盖权限、注入上下文、阻止执行 |
| PostToolUse | 工具执行后 | 修改输出(MCP)、注入上下文 |
| PreSampling | 模型响应后 | 后处理 |
| PostSampling | 采样后 | 后处理 |
| Stop | 每轮结束时 | 阻止继续对话 |

### 8.2 Hook 执行返回值

```typescript
// PreToolUse Hook 返回
{
  message?: AttachmentMessage | ProgressMessage,  // 注入消息
  hookPermissionResult?: PermissionResult,         // 覆盖权限
  hookUpdatedInput?: modified_input,               // 修改输入
  preventContinuation?: true,                      // 阻止继续
  stopReason?: string,                             // 停止原因
  additionalContext?: message,                     // 额外上下文
}

// PostToolUse Hook 返回
{
  message?: AttachmentMessage | ProgressMessage,
  updatedMCPToolOutput?: modified_output,          // MCP工具输出修改
  preventContinuation?: boolean,
  stopReason?: string,
  additionalContexts?: message[],
}
```

### 8.3 Hook 配置

在 `settings.json` 中配置:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "command": "validate-bash-command.sh"
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "command": "log-tool-result.sh"
      }
    ]
  }
}
```

---

## 9. 消息压缩（Compaction）机制

### 9.1 触发条件

**源码**: `services/compact/compact.ts`、`services/compact/autoCompact.ts`

| 触发方式 | 条件 | 位置 |
|----------|------|------|
| 自动 | token数量超过阈值 + 连续失败检查 | `query.ts:455-469` |
| 被动 | API返回 prompt-too-long 错误 | `query.ts:1121` |
| 手动 | 用户执行 `/compact` 命令 | 命令系统 |

### 9.2 压缩流程

```
compactConversation() (compact.ts:387)
    ├── 1. 从消息中移除图片（不需要用于摘要）
    ├── 2. Fork agent 调用 Haiku 生成摘要
    ├── 3. 返回 CompactionResult:
    │   ├── boundaryMarker    ← 系统消息标记压缩点
    │   ├── summaryMessages   ← 生成的摘要消息
    │   ├── messagesToKeep    ← 保留的最近消息
    │   ├── attachments       ← 重注入的 skills/agent 列表
    │   └── hookResults       ← post-compact hook 输出
    │
    └── 4. 构建新消息序列:
        buildPostCompactMessages()
        → [boundaryMarker, ...summaries, ...messagesToKeep, ...attachments, ...hookResults]
```

### 9.3 Compact Boundary 标记

```json
{
  "type": "system",
  "subtype": "compact_boundary",
  "compactMetadata": {
    "preservedSegment": false  // true=手动保留，false=正常归档
  }
}
```

---

## 10. 多Agent系统架构

### 10.1 Agent 类型

**源码**: `tools/AgentTool/loadAgentsDir.ts`

| 类型 | Source | 说明 |
|------|--------|------|
| BuiltIn | `'built-in'` | 内置agent（Explore、Plan、GeneralPurpose等） |
| Custom | `'userSettings'/'projectSettings'` | `.claude/agents/` 下的Markdown定义 |
| Plugin | `'plugin'` | 插件提供的agent |

### 10.2 Agent 定义 Schema

```typescript
type BaseAgentDefinition = {
  agentType: string            // Agent类型标识
  whenToUse: string            // 何时使用描述
  source: string               // 来源
  tools?: string[]             // 可用工具列表（默认全部）
  disallowedTools?: string[]   // 禁用工具列表
  model?: string               // 模型（'inherit'=继承父级）
  permissionMode?: 'plan' | 'acceptEdits' | 'bubble'
  effort?: number              // 推理努力程度 0-100
  maxTurns?: number            // 最大对话轮次
  mcpServers?: (string | {...})[]  // MCP 服务器配置
  hooks?: HooksSettings        // 会话级 hook 注册
  skills?: string[]            // 预加载的技能
  memory?: 'user' | 'project' | 'local'  // 持久记忆范围
  background?: boolean         // 始终后台运行
  isolation?: 'worktree' | 'remote'  // 隔离方式
  initialPrompt?: string       // 首轮前置提示
}
```

### 10.3 Agent 生成流程

**源码**: `tools/AgentTool/AgentTool.tsx`

```
AgentTool.call(input, context)
    ├── 1. 解析 agent 定义和类型
    ├── 2. 验证兼容性
    ├── 3. 判断同步/异步执行
    │
    ├── [同步Agent]
    │   ├── createSubagentContext()       ← 隔离可变状态
    │   ├── filterToolsForAgent()         ← 过滤可用工具
    │   ├── runAgent() [递归调用 query()] ← 完整对话循环
    │   └── 返回摘要 + 新消息
    │
    └── [异步Agent]
        ├── registerAsyncAgent()          ← 创建 LocalAgentTask
        ├── 队列 worktree 创建（如果 isolation: 'worktree'）
        ├── runAsyncAgentLifecycle()       ← 后台执行
        │   ├── 进度追踪: updateProgressFromMessage()
        │   ├── transcript 记录: recordSidechainTranscript()
        │   ├── 完成: completeAsyncAgent()
        │   └── 通知: enqueueAgentNotification()
        └── 立即返回 { status: 'async_launched', agentId }
```

### 10.4 子Agent上下文隔离

**源码**: `tools/AgentTool/AgentTool.tsx` (`createSubagentContext()`)

```typescript
// 隔离的状态
{
  readFileState: clone,           // 独立的文件状态缓存
  abortController: linked,        // 子级链接到父级（父abort→子abort）
  setAppState: no-op,             // 默认不影响父级UI
  contentReplacementState: fresh,  // 独立的内容替换
  toolDecisions: fresh,           // 独立的工具决策记录
}

// 按需共享
{
  shareSetAppState: opt-in,       // 共享UI状态更新
  shareAbortController: opt-in,   // 共享中止控制
}
```

### 10.5 工具过滤

**源码**: `tools/AgentTool/agentToolUtils.ts`

```
ALL_AGENT_DISALLOWED_TOOLS (永远禁止):
  AgentTool, ConfigTool, EnterPlanMode, ExitPlanMode,
  EnterWorktree, ExitWorktree, Teammate, TeamDelete, ...

ASYNC_AGENT_ALLOWED_TOOLS (异步agent白名单):
  Bash, Read, Write, Grep, Glob, Sleep, Monitor,
  WebSearch, WebFetch, MCP, Skill, TaskStop, SendMessage, Agent

CUSTOM_AGENT_DISALLOWED_TOOLS (自定义agent额外限制):
  + 更多限制

IN_PROCESS_TEAMMATE_ALLOWED_TOOLS (进程内队友):
  TaskCreate, TaskDelete, SendMessage (协调工具)
```

### 10.6 Sidechain Transcript 记录

**源码**: `sessionStorage.ts:1451-1462`

```
recordSidechainTranscript(messages, agentId, startingParentUuid)
    ├── Project.insertMessageChain(messages, isSidechain=true, agentId)
    ├── 写入路径: getAgentTranscriptPath(agentId)
    │   → ~/.claude/projects/{projectDir}/{sessionId}/subagents/agent-{agentId}.jsonl
    ├── 独立 parentUuid 链（不与主transcript混合）
    └── UUID不加入主 messageSet（避免去重冲突）
```

### 10.7 Agent Metadata

```json
// agent-{agentId}.meta.json
{
  "agentType": "explore",
  "worktreePath": "/tmp/wt-abc12345",
  "description": "Search for authentication patterns"
}
```

### 10.8 异步Agent通知

**源码**: `tasks/LocalAgentTask/LocalAgentTask.tsx`

```xml
<task-notification>
  <task-id>{agentId}</task-id>
  <output-file>{transcript_path}</output-file>
  <status>completed|failed|killed</status>
  <summary>找到了3个相关的认证模式...</summary>
  <result>详细结果...</result>
  <usage>
    <total_tokens>15234</total_tokens>
    <tool_uses>8</tool_uses>
    <duration_ms>12500</duration_ms>
  </usage>
  <worktree>
    <path>/tmp/wt-abc12345</path>
    <branch>agent-abc12345</branch>
  </worktree>
</task-notification>
```

### 10.9 Coordinator 模式

**源码**: `coordinator/coordinatorMode.ts`

```
Coordinator（协调者）
    ├── 可用工具: AgentTool, SendMessageTool, TaskStopTool
    ├── 系统提示: 生成worker、合成结果、管理并发
    │
    ├── 生成 Worker 1 (async agent)
    │   ├── 独立 worktree
    │   ├── 受限工具集
    │   └── 完成后发送 <task-notification>
    │
    ├── 生成 Worker 2 (async agent)
    │   └── 并行执行
    │
    └── 接收通知，合成结果，决定下一步
```

### 10.10 Team/Swarm 系统

**源码**: `utils/swarm/teamHelpers.ts`、`tools/shared/spawnMultiAgent.ts`

```
Team 配置文件: ~/.claude/teams/{teamName}/config.json
{
  "teamName": "review-team",
  "leadAgentId": "leader@review-team",
  "members": [
    { "name": "reviewer", "agentId": "reviewer@review-team", "agentType": "code-reviewer" },
    { "name": "tester", "agentId": "tester@review-team", "agentType": "test-runner" }
  ]
}

Agent间通信:
    SendMessageTool({ to: "reviewer", message: "请检查auth模块" })
        ├── In-Process: → task.pendingUserMessages 队列
        └── Tmux: → .claude/teamMailbox/{agentId}.txt 文件
```

### 10.11 Worktree 隔离

**源码**: `utils/worktree.ts`

```
createAgentWorktree(slug)
    ├── 尝试 hook-based 创建（WorktreeCreate hook）
    ├── 回退到 git worktree add
    ├── 返回:
    │   ├── worktreePath    ← 独立的工作目录
    │   ├── worktreeBranch  ← agent-{8hex} 分支
    │   ├── headCommit      ← 基于的 commit
    │   └── gitRoot         ← git 根目录
    │
    └── 清理:
        hasWorktreeChanges() → 检测未提交变更
        removeAgentWorktree() → 删除 worktree + 临时分支
```

### 10.12 Fork Subagent

**源码**: `tools/AgentTool/forkSubagent.ts`

Fork 是一种特殊的 agent 生成方式，用于缓存优化：

```
Fork 流程:
    1. 克隆父级完整的 assistant message（所有 tool_use blocks）
    2. 添加相同的 placeholder tool_results
    3. 追加每个子级的特定指令
    
    优势: Fork 子级保持与父级完全相同的工具定义和系统提示
         → 字节一致的 API 前缀 → prompt cache 命中
    
    防递归: isInForkChild() 检测 fork boilerplate tag
```

---

## 11. 构建你自己的系统：架构设计指南

### 11.1 核心架构分层

基于 Claude Code 的设计，一个完整的多Agent、多工具、有记忆的系统应该包含以下层次：

```
┌─────────────────────────────────────────────────────────┐
│                    用户界面层 (UI)                       │
│  REPL / CLI / Web / IDE Extension                       │
├─────────────────────────────────────────────────────────┤
│                 会话管理层 (Session)                     │
│  SessionStorage / TranscriptPersistence / Resume        │
├─────────────────────────────────────────────────────────┤
│               查询引擎层 (Query Engine)                  │
│  QueryLoop / MessageNormalization / SystemPrompt        │
├─────────────────────────────────────────────────────────┤
│               工具编排层 (Tool Orchestration)            │
│  ToolRegistry / ToolExecution / StreamingExecutor       │
├─────────────────────────────────────────────────────────┤
│              权限与安全层 (Permissions)                   │
│  PermissionRules / Hooks / Classifiers                  │
├─────────────────────────────────────────────────────────┤
│              Agent管理层 (Agent Management)              │
│  AgentSpawning / SubagentContext / Coordination         │
├─────────────────────────────────────────────────────────┤
│              记忆与上下文层 (Memory)                      │
│  CLAUDE.md / MemoryDir / Compaction / ContextCollapse   │
├─────────────────────────────────────────────────────────┤
│              外部集成层 (Integrations)                    │
│  MCP Servers / API Clients / Git / FileSystem           │
└─────────────────────────────────────────────────────────┘
```

### 11.2 你需要实现的核心模块

#### 模块 1: 会话持久化引擎

```
关键设计:
  ├── JSONL格式 (一行一个JSON，追加写入)
  ├── 消息链 (parentUuid 链接)
  ├── 写入队列 (批量异步写入，定时刷出)
  ├── UUID去重 (防止重复消息)
  ├── EOF元数据 (快速读取尾部获取会话信息)
  └── 独立的agent transcript文件

要实现的函数:
  - insertMessageChain(messages, isSidechain, agentId)
  - appendEntry(entry) [按类型路由到正确文件]
  - enqueueWrite(filePath, entry) [写入队列]
  - drainWriteQueue() [批量刷出]
  - reAppendSessionMetadata() [EOF元数据维护]
  - recordTranscript(messages) [公共API]
  - recordSidechainTranscript(messages, agentId) [子agent]
```

#### 模块 2: 查询循环

```
关键设计:
  ├── 无限 while(true) 循环
  ├── 每轮: 组装提示 → 调用API → 处理流式响应 → 工具执行 → 收集附件 → 递归
  ├── 退出条件: 无tool_use / abort / maxTurns / 错误
  ├── 流式响应与工具执行并行
  └── 异常恢复: prompt-too-long → compact / max-tokens → 升级

要实现的流程:
  1. assembleSystemPrompt(staticParts, dynamicParts, context)
  2. normalizeMessages(internalMessages) → API格式
  3. streamAPICall(messages, tools, systemPrompt) → 流式响应
  4. extractToolUseBlocks(response) → 工具调用列表
  5. executeTools(toolBlocks) → 工具结果
  6. collectAttachments() → 附件消息
  7. 递归: messages += [response, toolResults, attachments]
```

#### 模块 3: 工具注册与执行

```
关键设计:
  ├── 统一工具接口: { name, prompt, inputSchema, call, mapResult }
  ├── 工具注册表: getAllTools() → 动态过滤
  ├── 并发分区: isConcurrencySafe → 并行/串行批处理
  ├── 流式执行: 模型流式输出时就开始执行工具
  ├── 结果映射: 内部结果 → API tool_result 格式
  └── 大结果处理: 超限时持久化到磁盘

要实现的接口:
  interface Tool<Input, Output> {
    name: string
    prompt(): string                    // API工具描述
    inputSchema: ZodSchema              // 输入验证
    call(input, context): ToolResult    // 执行
    mapResult(output, id): ToolResultBlock  // 结果格式化
    isConcurrencySafe(input): boolean   // 并发安全性
    isReadOnly(input): boolean          // 只读性
    checkPermissions(input): PermissionResult
  }
```

#### 模块 4: 权限系统

```
关键设计:
  ├── 三阶段检查: Rules → Hooks → Interactive
  ├── 规则来源: settings / CLI args / session / policy
  ├── 模式切换: default / auto / plan / bypass
  └── 拒绝追踪: 防止重复询问

要实现的:
  - checkPermissions(tool, input, context) → allow/deny/ask
  - resolveHookPermission(hookResult, fallback) → 最终决定
  - PermissionRule: { tool, pattern, source, behavior }
```

#### 模块 5: Agent管理

```
关键设计:
  ├── 同步agent: 阻塞父级，递归 query()
  ├── 异步agent: 后台执行，通知机制
  ├── 上下文隔离: 独立 readFileState, abortController
  ├── 工具过滤: 禁止列表 + 白名单
  ├── Worktree隔离: git worktree 独立工作目录
  ├── Transcript分离: 独立 .jsonl 文件
  └── 通知机制: XML格式的 task-notification

要实现的:
  - spawnAgent(prompt, agentType, options)
  - createSubagentContext(parentContext, overrides)
  - filterToolsForAgent(tools, agentDef)
  - recordSidechainTranscript(messages, agentId)
  - enqueueNotification(agentId, result)
```

#### 模块 6: 记忆系统

```
关键设计:
  ├── 文件级记忆: CLAUDE.md / .claude/memory/ 目录
  ├── 注入方式: system prompt + user context
  ├── 自动压缩: token超限时 compact
  ├── 上下文折叠: 选择性折叠旧消息
  └── 记忆前缀: startRelevantMemoryPrefetch() 异步预取

要实现的:
  - loadMemory(projectPath) → 记忆内容
  - injectMemory(systemPrompt, memory) → 增强的系统提示
  - compactMessages(messages) → 压缩后的消息
  - createCompactBoundary() → 压缩边界标记
```

### 11.3 数据流完整图示

```
╔═══════════════════════════════════════════════════════════════════╗
║                     完整数据流                                    ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  用户输入                                                         ║
║    │                                                              ║
║    ▼                                                              ║
║  query() 入口                                                     ║
║    │                                                              ║
║    ├── 加载: systemPrompt + userContext + systemContext            ║
║    │   ├── getSystemPrompt() → 静态+动态提示词                   ║
║    │   ├── getUserContext() → CLAUDE.md + 日期 + 邮箱            ║
║    │   └── getSystemContext() → git状态 + 系统注入               ║
║    │                                                              ║
║    ├── 预处理消息:                                                ║
║    │   ├── snipOldMessages()    → 裁剪旧消息                    ║
║    │   ├── microcompact()       → 缓存编辑微压缩                ║
║    │   └── autocompact()        → token超限自动压缩              ║
║    │                                                              ║
║    ├── API调用:                                                   ║
║    │   ├── prependUserContext(messages, userContext)               ║
║    │   ├── normalizeMessagesForAPI(messages, tools)                ║
║    │   ├── toolToAPISchema(tool) × N → 工具schema               ║
║    │   └── streamingAPICall(messages, system, tools)               ║
║    │                                                              ║
║    ├── 流式处理:                                                  ║
║    │   ├── 收集 assistantMessages[]                               ║
║    │   ├── 提取 toolUseBlocks[]                                   ║
║    │   ├── StreamingToolExecutor.addTool() → 并行启动             ║
║    │   └── yield message → UI/SDK                                 ║
║    │                                                              ║
║    ├── 工具执行:                                                  ║
║    │   ├── partitionToolCalls() → 并行/串行分批                  ║
║    │   ├── for each tool:                                         ║
║    │   │   ├── validateInput()       → Zod验证                   ║
║    │   │   ├── preToolHooks()        → 前置hook                  ║
║    │   │   ├── checkPermissions()    → 权限检查                  ║
║    │   │   ├── tool.call()           → 实际执行                  ║
║    │   │   ├── mapResult()           → 结果格式化                ║
║    │   │   └── postToolHooks()       → 后置hook                  ║
║    │   └── 收集 toolResults[]                                     ║
║    │                                                              ║
║    ├── 收集附件:                                                  ║
║    │   ├── 文件变更附件                                           ║
║    │   ├── 记忆文件附件                                           ║
║    │   ├── 队列命令附件                                           ║
║    │   └── 技能发现附件                                           ║
║    │                                                              ║
║    ├── 持久化:                                                    ║
║    │   └── recordTranscript(allMessages)                           ║
║    │       ├── cleanMessagesForLogging()                           ║
║    │       ├── UUID去重                                           ║
║    │       ├── insertMessageChain()                                ║
║    │       │   ├── 构建 TranscriptMessage (注入metadata)          ║
║    │       │   ├── 设置 parentUuid 链                             ║
║    │       │   └── enqueueWrite() → 写入队列                      ║
║    │       └── drainWriteQueue() → .jsonl 文件                    ║
║    │                                                              ║
║    └── 递归:                                                      ║
║        messages = [...old, ...assistant, ...toolResults, ...attach]║
║        turnCount++                                                ║
║        continue → 回到循环开头                                    ║
║                                                                   ║
║  退出条件:                                                        ║
║    ├── 无 tool_use → return { reason: 'completed' }              ║
║    ├── abort → return { reason: 'aborted' }                      ║
║    ├── maxTurns → yield max_turns_reached                         ║
║    └── 错误恢复失败 → return { reason: 'error' }                ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
```

### 11.4 关键源码文件索引

| 文件 | 功能 | 关键行号 |
|------|------|----------|
| `query.ts` | 主查询循环 | 220 (entry), 660 (API call), 1381 (tool exec) |
| `Tool.ts` | 工具类型定义 | 362 (Tool type), 321 (ToolResult) |
| `tools.ts` | 工具注册表 | 193 (getAllBaseTools), 271 (getTools) |
| `sessionStorage.ts` | 持久化引擎 | 606 (enqueueWrite), 993 (insertMessageChain), 1128 (appendEntry), 1408 (recordTranscript) |
| `sessionStoragePortable.ts` | 跨平台读取 | 717 (readTranscriptForLoad) |
| `types/logs.ts` | 所有Entry类型定义 | 8-317 |
| `types/message.ts` | 消息类型定义 | - |
| `utils/messages.ts` | 消息规范化 | 1989 (normalizeMessagesForAPI) |
| `utils/api.ts` | Schema转换+上下文注入 | 119 (toolToAPISchema), 437 (appendSystemContext) |
| `constants/prompts.ts` | 系统提示词组装 | 444 (getSystemPrompt) |
| `context.ts` | 上下文构建 | 116 (getSystemContext), 155 (getUserContext) |
| `services/api/claude.ts` | API调用 | 1017 (queryModel), 752 (streaming) |
| `services/tools/toolExecution.ts` | 工具执行管线 | 615 (validation), 800 (hooks), 924 (permission), 1207 (call) |
| `services/tools/toolOrchestration.ts` | 并发编排 | 19 (runTools), partitionToolCalls |
| `services/tools/StreamingToolExecutor.ts` | 流式执行 | addTool, getRemainingResults |
| `services/tools/toolHooks.ts` | Hook编排 | executePreToolHooks, executePostToolHooks |
| `services/compact/compact.ts` | 消息压缩 | 387 (compactConversation), 330 (buildPostCompact) |
| `utils/permissions/` | 权限系统 | checkRuleBasedPermissions, PermissionRule |
| `utils/hooks/` | Hook基础设施 | 18个文件 |
| `tools/AgentTool/AgentTool.tsx` | Agent生成 | call(), 1397行 |
| `tools/AgentTool/runAgent.ts` | Agent执行循环 | runAgent(), 973行 |
| `tools/AgentTool/agentToolUtils.ts` | 工具过滤 | filterToolsForAgent |
| `tools/AgentTool/forkSubagent.ts` | Fork系统 | buildForkedMessages |
| `tools/AgentTool/loadAgentsDir.ts` | Agent定义加载 | getAgentDefinitions |
| `tasks/LocalAgentTask/LocalAgentTask.tsx` | 后台agent | 682行 |
| `tasks/RemoteAgentTask/RemoteAgentTask.tsx` | 远程agent | 855行 |
| `coordinator/coordinatorMode.ts` | 协调器 | getCoordinatorSystemPrompt |
| `utils/swarm/teamHelpers.ts` | Team系统 | team config |
| `utils/swarm/inProcessRunner.ts` | 进程内队友 | 完整隔离循环 |
| `utils/worktree.ts` | Worktree隔离 | createAgentWorktree |

### 11.5 你的系统 MVP 实现路线图

#### 第一阶段：单Agent + 工具系统

1. **定义工具接口** — `buildTool()` 模式
2. **实现工具注册表** — `getAllTools()` + `getTools()`
3. **实现查询循环** — `while(true)` + API调用 + tool_use检测 + 工具执行 + 递归
4. **实现JSONL持久化** — 写入队列 + 消息链 + UUID去重
5. **基本权限** — allow/deny 规则

#### 第二阶段：记忆 + 压缩

6. **CLAUDE.md 注入** — 系统提示词 + 用户上下文
7. **消息压缩** — token计数 + Haiku摘要 + boundary标记
8. **会话恢复** — `--resume` 从 .jsonl 重建消息链

#### 第三阶段：多Agent

9. **Agent生成** — 同步/异步 + 上下文隔离
10. **Sidechain Transcript** — 独立的 agent .jsonl 文件
11. **工具过滤** — 子agent工具限制
12. **通知机制** — XML通知 + 消息队列

#### 第四阶段：高级特性

13. **Coordinator模式** — 多worker编排
14. **Worktree隔离** — git worktree 独立环境
15. **MCP集成** — 外部工具服务器
16. **Hook系统** — 预/后置工具hook
17. **Team/Swarm** — 命名agent路由 + 邮箱通信
18. **流式工具执行** — 模型流式输出时并行执行工具

---

## 附录 A: 关键类型定义速查

```typescript
// 消息类型
type Message = UserMessage | AssistantMessage | AttachmentMessage | 
               ProgressMessage | SystemMessage | TombstoneMessage

// 工具结果
type ToolResult<T> = {
  data: T
  newMessages?: Message[]
  contextModifier?: (ctx: ToolUseContext) => ToolUseContext
  mcpMeta?: { _meta?, structuredContent? }
}

// 权限结果
type PermissionResult = {
  behavior: 'allow' | 'deny' | 'ask'
  updatedInput?: modified_input
  message?: string
  decisionReason?: { type: string, ...metadata }
}

// 工具执行上下文
type ToolUseContext = {
  options: {
    tools: Tools
    mainLoopModel: string
    thinkingConfig: ThinkingConfig
    mcpClients: MCPServerConnection[]
  }
  abortController: AbortController
  getAppState(): AppState
  setAppState(f): void
  messages: Message[]
  toolUseId?: string
  readFileState: FileStateCache
  queryTracking?: { chainId, depth }
  agentId?: AgentId
}

// Query 参数
type QueryParams = {
  messages: Message[]
  systemPrompt: SystemPrompt
  userContext: { [k: string]: string }
  systemContext: { [k: string]: string }
  canUseTool: CanUseToolFn
  toolUseContext: ToolUseContext
  querySource: QuerySource
  maxOutputTokensOverride?: number
  taskBudget?: { total: number }
}
```

## 附录 B: 遥测事件清单

| 事件 | 说明 |
|------|------|
| `tengu_tool_use_success` | 工具执行成功（含耗时、结果大小） |
| `tengu_tool_use_error` | 工具执行错误 |
| `tengu_tool_use_cancelled` | 工具被取消 |
| `tengu_tool_use_can_use_tool_allowed` | 权限允许 |
| `tengu_tool_use_can_use_tool_rejected` | 权限拒绝 |
| `tengu_query_before_attachments` | 附件处理前消息计数 |
| `tengu_query_after_attachments` | 附件处理后消息计数 |
| `tengu_streaming_tool_execution_used` | 流式工具执行已使用 |
| `tengu_session_persistence_failed` | 持久化失败 |
| `tengu_post_autocompact_turn` | 自动压缩后的轮次 |

---

> **文档版本**: 1.0  
> **基于源码**: @anthropic-ai/claude-code@2.1.88  
> **分析日期**: 2026-04-16  
> **涵盖范围**: 会话持久化、工具编排、权限系统、Hook系统、消息压缩、多Agent架构、Team/Swarm系统
