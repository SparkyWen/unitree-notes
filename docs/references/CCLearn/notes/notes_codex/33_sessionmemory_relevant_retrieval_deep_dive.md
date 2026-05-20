# Memory 深拆 01：SessionMemory / Relevant Retrieval

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/32_arch_memory_full_framework.md`
- 当前主题：**SessionMemory / relevant retrieval 深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. 当前 session 的记忆是如何被组织的
2. durable memory 中哪些内容会被检索回当前 query
3. relevant retrieval 是如何成为下一轮 prompt 注入来源的

---

## 2. 主链图

```text
当前 session 运行中产生 messages / tools / attachments
        │
        ▼
services/SessionMemory/sessionMemory.ts
        │
        ▼
services/SessionMemory/sessionMemoryUtils.ts
        │
        ▼
memdir/findRelevantMemories.ts
  -> memoryScan.ts
  -> memoryAge.ts
  -> memdir.ts
        │
        ▼
相关 memories 返回给 query / attachments / prompts
```

---

## 3. 关键文件职责

### `source/src/services/SessionMemory/sessionMemory.ts`
- SessionMemory 主服务
- 组织当前 session 相关记忆
- 为 query/compact/restore 提供 session-level memory 视图

### `source/src/services/SessionMemory/sessionMemoryUtils.ts`
- SessionMemory 辅助逻辑
- 做筛选、格式化、协同计算

### `source/src/services/SessionMemory/prompts.ts`
- SessionMemory 子流程 prompt 模板

### `source/src/memdir/findRelevantMemories.ts`
- 从 durable memory 里检索最相关的 memories
- 是 relevant retrieval 的主入口

### `source/src/memdir/memdir.ts`
- durable memory 目录服务
- 提供底层读写和 memory 内容访问

### `source/src/memdir/memoryScan.ts`
- 扫描 memory 文件并产出候选集

### `source/src/memdir/memoryAge.ts`
- 提供 time-based relevance / freshness 支持

### `source/src/memdir/memoryTypes.ts`
- 定义 retrieval 用到的数据类型

---

## 4. 关键结论

1. **SessionMemory 与 durable memory 不是一回事**
2. **relevant retrieval 是 query 注入 memory 的关键入口**
3. **memory 检索不是全文搜索壳，而是带 freshness/候选筛选的 retrieval 流程**
4. **当前 session 的语义与 durable memory 的候选筛选会在这一层汇合**
