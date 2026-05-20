# 代码审计级深挖 03：`microCompact.ts + compact.ts + promptCacheBreakDetection.ts` Cache 机制链

- 仓库路径：`cc/claude_code`
- 当前主题：**Prompt Cache / Cache Edit / Full Compact 的协作机制深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

> **当 prompt 变长、缓存开始失效时，系统如何尽量保缓存、轻量修复，最后才升级到 full compact。**

关键文件：
- `source/src/services/compact/microCompact.ts`
- `source/src/services/compact/apiMicrocompact.ts`
- `source/src/services/compact/compact.ts`
- `source/src/services/compact/autoCompact.ts`
- `source/src/services/api/promptCacheBreakDetection.ts`
- `source/src/services/compact/prompt.ts`

---

## 2. cache 机制链总图

```text
正常 query prompt
      │
      ▼
promptCacheBreakDetection.ts
  - 检测缓存前缀是否稳定
      │
      ├── 若仍稳定 -> 正常 caching
      │
      ├── 若部分低价值内容可清 -> microCompact.ts
      │       - cached microcompact
      │       - time-based microcompact
      │       - cache_edits / tool_result clearing
      │
      └── 若仍过长 / 已失控 -> autoCompact.ts
              -> compact.ts
              -> compact/prompt.ts
              -> postCompactCleanup.ts
```

---

## 3. 关键文件职责深拆

### 3.1 `promptCacheBreakDetection.ts`
- 判断 prompt cache prefix 是否断裂
- 为 query/api/microcompact 提供“还能不能保缓存”的依据

### 3.2 `microCompact.ts`
- 优先做 cache-aware 的轻量重写
- 删除旧 tool results 或通过 cache edits 缩减输入成本
- 尽量不真正重写整个 prompt 视图

### 3.3 `apiMicrocompact.ts`
- 帮助把 microcompact 的意图翻译成 API/cache-edit 语义
- 更贴近请求层的 microcompact 支撑文件

### 3.4 `autoCompact.ts`
- 决定什么时候该从轻量修复升级到 full compact
- 控制 warning / threshold / circuit breaker

### 3.5 `compact.ts`
- 当轻量修复不够时，真正重构 prompt 视图
- 生成 compact summary + restored attachments

### 3.6 `compact/prompt.ts`
- 生成 compact 自己使用的 prompt
- 也就是“用来压缩历史”的 prompt 模板层

---

## 4. 这条链最关键的设计点

1. **系统不会一上来就 full compact，而是先尝试保缓存的轻量修复**
2. **microcompact 的核心目标不是摘要，而是缓存友好**
3. **promptCacheBreakDetection 是这条链的前哨雷达**
4. **full compact 是最后手段，代价最高，但恢复能力也最强**
5. **compact 自己也需要 prompt，因此 compact/prompt.ts 本质上是“用于压缩 prompt 的 prompt”**

---

## 5. 最关键的结论

Claude Code 的 prompt cache / compact 机制不是单点优化，而是一条分层策略链：

> **先检测缓存稳定性 -> 再尽量做 cache-aware 轻量修复 -> 最后才 full compact 重构。**
