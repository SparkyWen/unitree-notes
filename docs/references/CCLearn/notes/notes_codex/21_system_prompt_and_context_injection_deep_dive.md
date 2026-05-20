# Prompt 专项深挖 01：System Prompt 与 Context 注入

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/20_arch_prompt_assembly_and_cache_framework.md`
- 当前主题：**System Prompt 与 Context 注入专项深拆**

---

## 1. 这个专项在研究什么

这个专项只聚焦两件事：

1. **System Prompt 本身是怎么被组织出来的**
2. **运行时 context 是如何注入 system/user prompt 结构中的**

它不再泛泛讲整个 prompt 系统，而是专门回答：

- 静态 system prompt 文本在哪里
- system prompt 为什么是 section/block 结构
- `systemContext` 和 `userContext` 是怎么来的
- `CLAUDE.md` / git snapshot / currentDate / memory / attachments 是如何进入 prompt 的
- 哪些注入是启动期完成，哪些是 query 每轮动态完成

---

## 2. 关键架构图

```text
静态 prompt 基底
  ├── constants/prompts.ts
  ├── constants/systemPromptSections.ts
  └── utils/systemPrompt.ts
          │
          ▼
运行时 context 生成
  ├── context.ts
  ├── utils/context.ts
  ├── utils/claudemd.ts
  ├── SessionMemory/**
  ├── memdir/findRelevantMemories.ts
  └── attachments.ts
          │
          ▼
query.ts 组装消息与上下文
          │
          ▼
services/api/claude.ts
  ├── buildSystemPromptBlocks(...)
  ├── normalizeMessagesForAPI(...)
  └── system + messages + tools
          │
          ▼
最终送给模型的 system blocks + normalized messages
```

---

## 3. 核心文件与职责

### 3.1 `source/src/constants/prompts.ts`
- 静态 prompt 文本与模板仓库
- 放系统基础说明、固定提示片段、通用模板

### 3.2 `source/src/constants/systemPromptSections.ts`
- 把 system prompt 切成结构化 sections
- 便于稳定拼装、缓存、按段组合

### 3.3 `source/src/utils/systemPrompt.ts`
- 真正的 system prompt 组装器
- 把静态 sections + 运行态注入信息组合成最终 system prompt blocks

### 3.4 `source/src/utils/systemPromptType.ts`
- 定义 system prompt 相关类型
- 给组装器与 API 编译层提供统一结构约束

### 3.5 `source/src/context.ts`
- 生成 `systemContext`
- 生成 `userContext`
- 获取 git snapshot
- currentDate 注入
- 配合 CLAUDE.md 聚合形成 runtime prompt 上下文

### 3.6 `source/src/utils/context.ts`
- context 处理辅助逻辑
- 帮助分析、组织或规范化 context 结构

### 3.7 `source/src/utils/claudemd.ts`
- 查找和读取 CLAUDE.md
- 聚合项目说明类上下文
- 供 `userContext` 注入 prompt

### 3.8 `source/src/utils/attachments.ts`
- 把运行时副作用变成 attachment messages
- attachments 最终会回到下一轮 messages，成为 prompt 输入的一部分

### 3.9 `source/src/services/SessionMemory/sessionMemory.ts`
- SessionMemory 主服务
- 给 query/runtime 提供当前 session 应该带回来的 memory 内容

### 3.10 `source/src/services/SessionMemory/sessionMemoryUtils.ts`
- SessionMemory 相关辅助函数
- 做筛选、格式化、协同处理

### 3.11 `source/src/services/SessionMemory/prompts.ts`
- SessionMemory 子流程自己的 prompt 模板

### 3.12 `source/src/memdir/findRelevantMemories.ts`
- 在 durable memory 中检索与当前 query 最相关的 memory

### 3.13 `source/src/memdir/memdir.ts`
- durable memory 目录服务
- 为检索与写入提供底层支持

### 3.14 `source/src/memdir/paths.ts`
- 决定 memory 放在哪、哪些 path 合法
- 影响 memory 能否稳定地被注入 prompt

### 3.15 `source/src/query.ts`
- 把上面这些动态 context 与 messages 真正组织进 query 运行时

### 3.16 `source/src/services/api/claude.ts`
- `buildSystemPromptBlocks(...)`
- 最终把 system blocks + normalized messages 编译成 API 请求

---

## 4. system prompt 与 context 注入的关键结论

1. **system prompt 不是纯字符串，而是 block/section 化结构**
2. **`context.ts` 是 system/user runtime context 的主入口**
3. **`CLAUDE.md`、memory、attachments 都属于运行时注入，而不是静态 prompt**
4. **真正发给模型前，`claude.ts` 还会再把 system blocks 与 messages 统一编译**
5. **context 注入不是一次性的；每轮 query 都可能因为 attachments/memory/compact 发生变化**

---

## 5. 本专项输出

已完成：
- system prompt 与 context 注入专项架构图
- 核心文件职责说明
- 关键结论整理
