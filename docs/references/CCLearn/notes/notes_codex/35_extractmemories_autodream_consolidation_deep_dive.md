# Memory 深拆 03：extractMemories / autoDream / consolidation

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/32_arch_memory_full_framework.md`
- 当前主题：**extractMemories / autoDream / consolidation 深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. Claude Code 如何从对话中抽取 durable memories
2. autoDream / consolidation 如何对已有 memories 再整理  (==原理职责讲清楚==)
3. prompt suggestion 与 memory 收尾治理之间的关系

---

## 2. 主链图

```text
当前对话 / session 结束阶段
      │
      ▼
services/extractMemories/extractMemories.ts
  - 从会话中抽取 durable memory 条目
      │
      ▼
services/autoDream/autoDream.ts
  - consolidation / dream
  - 对已有 memories 做整理浓缩
      │
      ▼
memdir/** durable storage
      │
      ▼
下次 relevant retrieval 再回到 query
```

---

## 3. 关键文件职责

### `source/src/services/extractMemories/extractMemories.ts`
- 抽取 durable memories 的主逻辑
- 把会话中的短期信息转成长期记忆

### `source/src/services/extractMemories/prompts.ts`
- extract memories 使用的 prompt 模板

### `source/src/services/autoDream/autoDream.ts`
- autoDream / consolidation 主逻辑
- 让 durable memory 被进一步整理、压缩、重组

### `source/src/services/autoDream/config.ts`
- autoDream 配置

### `source/src/services/autoDream/consolidationLock.ts`
- consolidation 锁，避免并发整理冲突

### `source/src/services/autoDream/consolidationPrompt.ts`
- consolidation/dream prompt 模板

### `source/src/services/PromptSuggestion/promptSuggestion.ts`
- prompt suggestion 主逻辑，与会话收尾和后续建议相关

### `source/src/services/PromptSuggestion/speculation.ts`
- prompt suggestion/speculation 辅助

### `source/src/services/compact/sessionMemoryCompact.ts`
- 说明 memory 不只用于 retrieval，也被用于 compact 治理路径

---

## 4. 关键结论

1. **extractMemories 负责“生成记忆”**
2. **autoDream/consolidation 负责“整理记忆”**
3. **memory 是持续演化资产，而不是只会追加文件**
4. **prompt suggestion 与 memory 收尾治理是相邻系统**
