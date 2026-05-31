# Claude Code Memory 相关完整架构图（全量专项版）

- 仓库路径：`cc/claude_code`
- 当前主题：**Memory 相关完整架构：SessionMemory / memdir / relevant memory / extractMemories / autoDream / teamMemory / attachments / session persistence / memory UI**
- 当前目标：
  1. 给出 memory 相关完整架构图
  2. 给出 memory 相关相对路径索引
  3. 对这个功能块所有涉及文件总结作用

> 说明：这次不只覆盖之前那份“Memory / Attachment / Session 恢复层”概览，而是把 memory 相关更完整的子系统一起纳入：
> - SessionMemory
> - memdir
> - extractMemories
> - autoDream
> - teamMemorySync
> - memory 命令 / UI / hooks / message 组件
> - memory 类型与版本辅助
>
> 目标是做成一份更像“memory 专项总图”的文档。

---

## 1. Claude Code 里的 memory 到底分几层

Claude Code 里的 memory 不是一个文件，也不是一个 prompt 片段，而是分成多层：

1. **Session Memory**
   - 当前 session 相关记忆的组织层
2. **Durable Memory（memdir）**
   - 落盘的长期记忆目录
3. ==**Relevant Memory Retrieval**==
   - 针对当前 query 检索相关 memory 的层
4. **Extract Memories**
   - 从当前对话/历史中抽取记忆写回 durable storage 的层
5. **Auto Dream / Consolidation**
   - 自动整理、合并、浓缩 memory 的层
6. **Team Memory / Shared Memory**
   - 协作体/团队相关的 memory 同步层
7. **Attachment / Session Persistence Bridge**
   - 把 memory 以 attachments/messages 形式回灌到 query 的层
8. **UI / Commands / Hooks / Notifications**
   - 让用户看见、管理和触发 memory 相关流程的层

一句话：

> **Claude Code 的 memory 体系是“会话级记忆 + durable memory 存储 + 自动提取/整理 + query 注入”的组合系统。**

---

## 2. Memory 完整总架构图

```text
Claude Code Memory 系统
├── A. Session Memory 服务层
│   ├── services/SessionMemory/sessionMemory.ts
│   ├── services/SessionMemory/sessionMemoryUtils.ts
│   └── services/SessionMemory/prompts.ts
│
├── B. Durable Memory / memdir 层
│   ├── memdir/memdir.ts
│   ├── memdir/paths.ts
│   ├── memdir/findRelevantMemories.ts
│   ├── memdir/memoryScan.ts
│   ├── memdir/memoryAge.ts
│   ├── memdir/memoryTypes.ts
│   ├── memdir/teamMemPaths.ts
│   └── memdir/teamMemPrompts.ts
│
├── C. Memory 提取与整理层
│   ├── services/extractMemories/**
│   ├── services/autoDream/**
│   ├── services/PromptSuggestion/**
│   └── services/compact/sessionMemoryCompact.ts
│
├── D. Team Memory 同步层
│   └── services/teamMemorySync/**
│
├── E. Query / Attachment / Session Bridge 层
│   ├── utils/attachments.ts
│   ├── utils/sessionStorage.ts
│   ├── utils/sessionStoragePortable.ts
│   ├── utils/teamMemoryOps.ts
│   ├── utils/memory/**
│   └── utils/memoryFileDetection.ts
│
├── F. 命令 / UI / Hooks / 消息层
│   ├── commands/memory/**
│   ├── components/memory/**
│   ├── components/messages/UserMemoryInputMessage.tsx
│   ├── components/messages/teamMemCollapsed.tsx
│   ├── components/messages/teamMemSaved.ts
│   ├── hooks/useMemoryUsage.ts
│   ├── hooks/usePromptSuggestion.ts
│   ├── components/MemoryUsageIndicator.tsx
│   └── Feedback / new-agent wizard memory 相关组件
│
└── G. 相关支撑层
    ├── skills/bundled/remember.ts
    ├── tools/AgentTool/agentMemory.ts
    ├── tools/AgentTool/agentMemorySnapshot.ts
    └── tools/BriefTool/attachments.ts
```

---

## 3. Memory 动态运行流程图

```text
当前 session 持续产生对话 / 工具结果 / attachments
        │
        ▼
[SessionMemory]
  - 组织当前 session 可用记忆
        │
        ▼
[memdir/findRelevantMemories.ts]（核心， 扫描header， 然后给sonnet）
  - 去 durable memory 中找最相关 memories
        │
        ▼
[query.ts + attachments.ts]
  - 把 relevant memories / memory deltas 注入下一轮 prompt
        │
        ▼
运行结束 / stopHooks / extract mode active
        │
        ├── extractMemories.ts
        │      - 抽取当前会话中的 durable memories
        │
        ├── autoDream/**
        │      - consolidation / dream / memory 整理
        │
        └── teamMemorySync/**
               - 协作 memory 的同步与 secret guard
        │
        ▼
[memdir.ts / teamMemPaths.ts]
  - memory 落盘 / 归档 / 扫描 / 后续再被 relevant retrieval 命中
```

---

## 4. 相对路径索引（全量）

下面按层把当前收拢到的 memory 相关文件全部列出来。

---

### 4.1 SessionMemory 服务层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/SessionMemory/prompts.ts` | SessionMemory 相关 prompt 模板 |
| `source/src/services/SessionMemory/sessionMemory.ts` | SessionMemory 主服务 |
| `source/src/services/SessionMemory/sessionMemoryUtils.ts` | SessionMemory 辅助逻辑 |

---

### 4.2 memdir / durable memory 层

| 相对路径 | 作用 |
|---|---|
| `source/src/memdir/findRelevantMemories.ts` | relevant memories 检索 |
| `source/src/memdir/memdir.ts` | durable memory 目录主服务 |
| `source/src/memdir/memoryAge.ts` | memory 时效/新鲜度辅助 |
| `source/src/memdir/memoryScan.ts` | memory 扫描 |
| `source/src/memdir/memoryTypes.ts` | memory 类型 |
| `source/src/memdir/paths.ts` | memory 路径、安全边界与作用域规则 |
| `source/src/memdir/teamMemPaths.ts` | team memory 路径规则 |
| `source/src/memdir/teamMemPrompts.ts` | team memory prompt 模板 |

---

### 4.3 提取、整理、dream、suggestion 层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/extractMemories/extractMemories.ts` | 从会话/上下文中抽取 durable memories |
| `source/src/services/extractMemories/prompts.ts` | extract memories prompt 模板 |
| `source/src/services/autoDream/autoDream.ts` | auto dream / memory consolidation 主逻辑 |
| `source/src/services/autoDream/config.ts` | autoDream 配置 |
| `source/src/services/autoDream/consolidationLock.ts` | consolidation 锁，避免并发整理 |
| `source/src/services/autoDream/consolidationPrompt.ts` | consolidation/dream prompt 模板 |
| `source/src/services/PromptSuggestion/promptSuggestion.ts` | prompt suggestion 主逻辑 |
| `source/src/services/PromptSuggestion/speculation.ts` | prompt suggestion/speculation 辅助 |
| `source/src/services/compact/sessionMemoryCompact.ts` | 利用 session memory 路径做 compact 的支路 |

---

### 4.4 Team Memory 同步层

| 相对路径 | 作用 |
|---|---|
| `source/src/services/teamMemorySync/index.ts` | team memory sync 主入口 |
| `source/src/services/teamMemorySync/secretScanner.ts` | team memory 写入前的 secret 扫描 |
| `source/src/services/teamMemorySync/teamMemSecretGuard.ts` | team memory secret guard |
| `source/src/services/teamMemorySync/types.ts` | team memory sync 类型 |
| `source/src/services/teamMemorySync/watcher.ts` | team memory watcher / 同步监听 |

---

### 4.5 Query / Attachment / Session Bridge 层

| 相对路径 | 作用 |
|---|---|
| `source/src/utils/attachments.ts` | 把 memory 相关副作用组织成 attachment messages |
| `source/src/utils/sessionStorage.ts` | session transcript 持久化与恢复 |
| `source/src/utils/sessionStoragePortable.ts` | portable session storage 适配 |
| `source/src/utils/memory/types.ts` | memory 领域通用类型 |
| `source/src/utils/memory/versions.ts` | memory 版本/兼容性辅助 |
| `source/src/utils/memoryFileDetection.ts` | memory 文件识别辅助 |
| `source/src/utils/teamMemoryOps.ts` | team memory 操作辅助 |

---

### 4.6 命令 / UI / Hook / 消息层

| 相对路径 | 作用 |
|---|---|
| `source/src/commands/memory/index.ts` | memory 命令注册入口 |
| `source/src/commands/memory/memory.tsx` | memory 命令 UI/逻辑 |
| `source/src/components/memory/MemoryFileSelector.tsx` | memory 文件选择 UI |
| `source/src/components/memory/MemoryUpdateNotification.tsx` | memory 更新通知 UI |
| `source/src/components/messages/UserMemoryInputMessage.tsx` | 用户 memory 输入消息渲染 |
| `source/src/components/messages/teamMemCollapsed.tsx` | team memory collapsed 消息渲染 |
| `source/src/components/messages/teamMemSaved.ts` | team memory saved 消息辅助 |
| `source/src/components/MemoryUsageIndicator.tsx` | memory 使用量指标 UI |
| `source/src/components/FeedbackSurvey/useMemorySurvey.tsx` | memory 相关反馈问卷 hook |
| `source/src/components/agents/new-agent-creation/wizard-steps/MemoryStep.tsx` | 新 agent 创建流程中的 memory 设置步骤 |
| `source/src/hooks/useMemoryUsage.ts` | memory usage hook |
| `source/src/hooks/usePromptSuggestion.ts` | prompt suggestion hook |

---

### 4.7 相关支撑层

| 相对路径 | 作用 |
|---|---|
| `source/src/skills/bundled/remember.ts` | bundled skill：remember / 记忆相关能力 |
| `source/src/tools/AgentTool/agentMemory.ts` | agent memory 相关辅助 |
| `source/src/tools/AgentTool/agentMemorySnapshot.ts` | agent memory snapshot 支持 |
| `source/src/tools/BriefTool/attachments.ts` | brief 场景与 attachments/memory 相关辅助 |

---

## 5. Memory 主骨架文件详细说明

下面先把真正支撑 memory 体系的核心文件讲清楚。

---

### 5.1 `source/src/services/SessionMemory/sessionMemory.ts`

**定位：** SessionMemory 主服务。

**负责：**
- 组织当前 session 相关记忆
- query / compact / restore / stopHooks 与 memory 体系之间的桥接
- relevant memory prefetch / restore 协同

**为什么重要：**
它是“当前对话上下文”和“durable memory 存储”之间的中间层，不等于 transcript，也不等于 memdir 本身。

**一句话总结：**
> 当前 session 与 durable memory 之间的 memory 中介层。

---

### 5.2 `source/src/services/SessionMemory/sessionMemoryUtils.ts`

**定位：** SessionMemory 辅助逻辑层。

**负责：**
- memory 相关筛选、格式化、协同计算
- 支撑 query/compact/restore 等路径中的 SessionMemory 使用

**一句话总结：**
> SessionMemory 的工具函数与协同层。

---

### 5.3 `source/src/memdir/memdir.ts`

**定位：** durable memory 目录主服务。

**负责：**
- memory 文件的基础读写
- memory 存储与读取的统一入口
- 为 relevant memory、extract、dream 等子系统提供底层支持

**一句话总结：**
> durable memory 存储层的主服务。

---

### 5.4 `source/src/memdir/findRelevantMemories.ts`

**定位：** relevant memory 检索器。

**负责：**
- 根据当前 query / session 上下文寻找最相关的 memory 片段
- 给下一轮 prompt 注入提供记忆候选

**一句话总结：**
> 当前 query 的 memory 检索器。

---

### 5.5 `source/src/memdir/paths.ts`

**定位：** auto-memory 路径与安全边界中枢。

**负责：**
- 决定 memory 存放位置
- 验证哪些 path 合法
- 控制 trusted settings 才能 override memory path
- 保证 worktree 可以共享同一 repo memory root

**一句话总结：**
> memory 文件系统边界的守门员。

---

### 5.6 `source/src/services/extractMemories/extractMemories.ts`

**定位：** memory 抽取器。

**负责：**
- 从当前对话或历史里提取 durable memories
- 把短期会话内容转化成长期 memory 条目

**一句话总结：**
> 从对话流中蒸馏 durable memory 的提取器。

---

### 5.7 `source/src/services/autoDream/autoDream.ts`

**定位：** memory 自动整理/巩固器。

**负责：**
- consolidation / dream 逻辑
- 把已有 memories 再压缩、整理、合并
- 让 durable memory 不只是堆积，而是逐渐被整理

**一句话总结：**
> durable memory 的自动整理器。

---

### 5.8 `source/src/services/teamMemorySync/index.ts`

**定位：** team memory 同步主入口。

**负责：**
- 协作 memory 的同步与 watcher 组织
- 配合 secret guard/secret scanner 控制共享 memory 的安全边界

**一句话总结：**
> 协作型 memory 的同步中枢。

---

### 5.9 `source/src/utils/attachments.ts`

**定位：** memory 回灌桥。

**负责：**
- 把 memory 变化、files、plans、delta 等组织成 attachments
- 再送回下一轮 query，让 memory 真正影响模型上下文

**一句话总结：**
> memory 回流到 query prompt 的桥接器。

---

### 5.10 `source/src/utils/sessionStorage.ts`

**定位：** session transcript 持久化与恢复中心。

**负责：**
- 存储 session 对话与 metadata
- 支撑 resume/continue
- 是 SessionMemory 与 durable memory 之外的“原始事件层”

**一句话总结：**
> memory 体系依赖的原始会话事件底座。

---

## 6. 所有 memory 相关文件逐项职责总结

下面把这次收拢到的 memory 相关文件全部逐项总结。

---

## 6.1 `services/SessionMemory/**` 全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/SessionMemory/prompts.ts` | SessionMemory 子流程使用的 prompt 模板 |
| `source/src/services/SessionMemory/sessionMemory.ts` | SessionMemory 主服务，负责当前 session 记忆组织与桥接 |
| `source/src/services/SessionMemory/sessionMemoryUtils.ts` | SessionMemory 的辅助函数与协同逻辑 |

---

## 6.2 `memdir/**` 全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/memdir/findRelevantMemories.ts` | 检索与当前上下文最相关的 memories |
| `source/src/memdir/memdir.ts` | durable memory 目录主服务与基础读写 |
| `source/src/memdir/memoryAge.ts` | memory 新鲜度/时间权重判断辅助 |
| `source/src/memdir/memoryScan.ts` | 扫描 memory 文件并产出候选集 |
| `source/src/memdir/memoryTypes.ts` | memory 类型与数据结构定义 |
| `source/src/memdir/paths.ts` | memory 路径、安全校验与作用域规则中心 |
| `source/src/memdir/teamMemPaths.ts` | team memory 路径规划 |
| `source/src/memdir/teamMemPrompts.ts` | team memory 相关 prompt 模板 |

---

## 6.3 提取 / dream / suggestion / compact 相关文件全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/extractMemories/extractMemories.ts` | 从对话中提取 durable memories |
| `source/src/services/extractMemories/prompts.ts` | extract memories prompt 模板 |
| `source/src/services/autoDream/autoDream.ts` | autoDream / consolidation 主逻辑 |
| `source/src/services/autoDream/config.ts` | autoDream 配置 |
| `source/src/services/autoDream/consolidationLock.ts` | consolidation 并发锁 |
| `source/src/services/autoDream/consolidationPrompt.ts` | consolidation / dream prompt 模板 |
| `source/src/services/PromptSuggestion/promptSuggestion.ts` | prompt suggestion 主逻辑（和 memory 收尾治理有关） |
| `source/src/services/PromptSuggestion/speculation.ts` | prompt suggestion/speculation 辅助 |
| `source/src/services/compact/sessionMemoryCompact.ts` | session memory 路径的 compact 支路 |

---

## 6.4 Team Memory Sync 全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/services/teamMemorySync/index.ts` | team memory sync 主入口 |
| `source/src/services/teamMemorySync/secretScanner.ts` | team memory 写入前 secret 扫描 |
| `source/src/services/teamMemorySync/teamMemSecretGuard.ts` | team memory secret guard |
| `source/src/services/teamMemorySync/types.ts` | team memory sync 类型 |
| `source/src/services/teamMemorySync/watcher.ts` | team memory 变化监听与同步 |

---

## 6.5 Query / Attachment / Session Bridge 层全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/utils/attachments.ts` | 将 memory 与其他 runtime side effects 组织成 attachment messages |
| `source/src/utils/sessionStorage.ts` | session transcript 持久化与 resume 恢复 |
| `source/src/utils/sessionStoragePortable.ts` | portable session storage 适配 |
| `source/src/utils/memory/types.ts` | memory 领域通用类型 |
| `source/src/utils/memory/versions.ts` | memory 数据结构版本与兼容性支持 |
| `source/src/utils/memoryFileDetection.ts` | 识别 memory 文件与 memory 相关路径 |
| `source/src/utils/teamMemoryOps.ts` | team memory 操作辅助 |

---

## 6.6 命令 / UI / Hooks / 消息层全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/commands/memory/index.ts` | memory 命令注册入口 |
| `source/src/commands/memory/memory.tsx` | memory 命令 UI/逻辑 |
| `source/src/components/FeedbackSurvey/useMemorySurvey.tsx` | memory 相关反馈问卷 hook |
| `source/src/components/MemoryUsageIndicator.tsx` | memory 使用量展示组件 |
| `source/src/components/agents/new-agent-creation/wizard-steps/MemoryStep.tsx` | 新 agent 创建时的 memory 配置步骤 |
| `source/src/components/memory/MemoryFileSelector.tsx` | memory 文件选择 UI |
| `source/src/components/memory/MemoryUpdateNotification.tsx` | memory 更新通知 UI |
| `source/src/components/messages/UserMemoryInputMessage.tsx` | memory 输入消息渲染 |
| `source/src/components/messages/teamMemCollapsed.tsx` | team memory collapsed 消息渲染 |
| `source/src/components/messages/teamMemSaved.ts` | team memory saved 消息辅助 |
| `source/src/hooks/useMemoryUsage.ts` | 读取/订阅 memory usage 的 hook |
| `source/src/hooks/usePromptSuggestion.ts` | prompt suggestion hook（与 memory 收尾治理相连） |

---

## 6.7 相关支撑文件全量职责总结

| 相对路径 | 作用总结 |
|---|---|
| `source/src/skills/bundled/remember.ts` | 内建 remember skill，帮助把信息写入记忆体系 |
| `source/src/tools/AgentTool/agentMemory.ts` | agent memory 相关辅助 |
| `source/src/tools/AgentTool/agentMemorySnapshot.ts` | agent memory snapshot 支持 |
| `source/src/tools/BriefTool/attachments.ts` | brief 场景下和 attachments/memory 相关辅助 |

---

## 7. Memory 体系的关键设计结论

### 结论 1：Claude Code 的 memory 体系至少分成 4 层

- 原始会话事件层：`sessionStorage.ts`
- 当前 session 记忆组织层：`SessionMemory/**`
- durable memory 存储层：`memdir/**`
- 抽取/整理/同步层：`extractMemories` / `autoDream` / `teamMemorySync`

---

### 结论 2：relevant memory 检索不是附属能力，而是 query prompt 动态注入的重要来源

也就是说 memory 不是“存着不用”，而是持续参与下一轮 prompt 构造。

---

### 结论 3：autoDream / extractMemories / teamMemorySync 说明 memory 体系是主动演化的，不是被动文件夹

memory 会：
- 被抽取
- 被整理
- 被浓缩
- 被同步
- 被 secret guard 限制

---

### 结论 4：memory 路径是安全边界，不只是存储路径

`memdir/paths.ts` 很关键，因为 memory path override 会影响文件系统权限与可信边界。

---

### 结论 5：attachments 是 memory 回灌到主循环的关键桥

memory 真正影响模型，不是因为它存在磁盘上，而是因为：
- relevant retrieval
- attachments
- query 注入

这条链把它重新带回运行时。

---

## 8. 当前输出结果

本轮已完成：
- **memory 相关完整架构图**
- **memory 动态运行流程图**
- **memory 相对路径全量索引**
- **memory 主骨架文件详细说明**
- **memory 相关所有涉及文件职责总结**

已保存到：
- `cc/cc_learn/32_arch_memory_full_framework.md`

---

## 9. 如果继续深挖 memory，建议下一步怎么拆

如果你还要把 memory 做到更细，我建议再拆成 4 份：

1. **SessionMemory / relevant retrieval 深拆**
2. **durable memdir / paths / versions 深拆**
3. **extractMemories / autoDream / consolidation 深拆**
4. **teamMemorySync / secret guard / shared memory 深拆**

如果你愿意，我下一步可以直接继续做：

> **SessionMemory / relevant retrieval 深拆版**