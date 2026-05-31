# Prompt 专项深挖 03：Prompt Cache / Compact / Cache Edit / Dump Prompts

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/20_arch_prompt_assembly_and_cache_framework.md`
- 当前主题：**Prompt Cache / Compact / Cache Edit / Dump Prompts 专项深拆**

---

## 1. 这个专项在研究什么

这个专项只聚焦：

1. prompt cache 为什么会命中/失效
2. cache break 如何检测
3. cache edits / microcompact 如何尽量保住缓存前缀
4. full compact 如何重构 prompt
5. dump prompts / break-cache / clear caches 如何帮助调试

---

## 2. 关键架构图

```text
正常 query prompt 编译
  -> services/api/claude.ts
  -> promptCacheBreakDetection.ts
        │
        ├── 若 cache 稳定
        │      -> 继续正常 prompt caching
        │
        ├── 若可以轻量修复
        │      -> microCompact.ts
        │      -> apiMicrocompact.ts
        │      -> cache_edits
        │
        └── 若已经过长/失控
               -> autoCompact.ts
               -> compact.ts
               -> compact/prompt.ts
               -> postCompactCleanup.ts

调试支撑
  ├── dumpPrompts.ts
  ├── break-cache/index.js
  ├── clear/caches.ts
  └── cachePaths.ts
```

---

## 3. 核心文件职责

### 3.1 `source/src/services/api/promptCacheBreakDetection.ts`
- 检测 prompt cache break
- 判断缓存前缀是否还能稳定复用
- 给 query/API/compact 体系提供 cache-aware 决策依据

### 3.2 `source/src/services/compact/microCompact.ts`
- 实现 cached microcompact 与 time-based microcompact
- 优先不重写整体 prompt，只删除旧 tool_result 等低价值内容
- 尽量保留 cache prefix

### 3.3 `source/src/services/compact/apiMicrocompact.ts`
- 更贴近 API/cache_edits 语义的微型 compact 支撑层
- 帮助将 microcompact 结果变成 API 可消费的 cache edit 结构

### 3.4 `source/src/services/compact/autoCompact.ts`
- 判断什么时候该从“缓存友好模式”升级到真正 compact
- 管理 warning / threshold / circuit breaker

### 3.5 `source/src/services/compact/compact.ts`
- full/partial compact 主实现
- 把长历史压缩成可继续工作的 summary + restored attachments

### 3.6 `source/src/services/compact/prompt.ts`
- compact agent / compact request 的 prompt 模板和构造逻辑

### 3.7 `source/src/services/compact/grouping.ts`
- 对消息做分组，方便 compact / PTL retry / prompt 重构

### 3.8 `source/src/services/compact/postCompactCleanup.ts`
- compact 后清理 warning、状态和缓存标记

### 3.9 `source/src/services/compact/compactWarningState.ts`
- 保存 compact warning 是否已触发/已抑制等状态

### 3.10 `source/src/services/compact/compactWarningHook.ts`
- compact warning 与 hooks 协作层

### 3.11 `source/src/services/compact/sessionMemoryCompact.ts`
- 尝试通过 session memory 路径先做较轻量 compact

### 3.12 `source/src/services/compact/timeBasedMCConfig.ts`
- time-based microcompact 的配置来源与阈值

### 3.13 `source/src/services/api/dumpPrompts.ts`
- 导出最终 prompt/request 结构供调试
- 是观察 prompt cache 失效前后最直观的工具之一

### 3.14 `source/src/utils/cachePaths.ts`
- 缓存文件/路径组织辅助

### 3.15 `source/src/commands/break-cache/index.js`
- 人工打断/调试 prompt cache 的命令入口

### 3.16 `source/src/commands/clear/caches.ts`
- 清理各类缓存状态的命令逻辑

---

## 4. cache-aware prompt 机制的关键结论

1. **Claude Code 把 prompt cache 当成一等优化目标来设计**
2. **microcompact 的核心不是“压缩历史”，而是“尽量不打断缓存前缀”**
3. **cache break detection 是决定用不用 cache edits / 要不要 full compact 的前哨**
4. **full compact 是最后手段，会真正重构 prompt 视图**
5. **dumpPrompts + break-cache + clear caches 组成了一套 prompt/cache 调试工具链**

---

## 5. 本专项输出

已完成：
- Prompt Cache / Compact / Cache Edit / Dump Prompts 专项架构图
- 核心文件职责说明
- 关键结论整理
