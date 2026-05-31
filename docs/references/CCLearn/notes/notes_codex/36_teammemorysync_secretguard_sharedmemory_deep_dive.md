# Memory 深拆 04：teamMemorySync / secret guard / shared memory

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/32_arch_memory_full_framework.md`
- 当前主题：**teamMemorySync / secret guard / shared memory 深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. team/shared memory 如何同步
2. team memory 为什么需要单独的 secret guard
3. 协作 memory 与普通 memory 的区别是什么

---

## 2. 主链图

```text
team / teammate memory 事件
      │
      ▼
services/teamMemorySync/index.ts
      │
      ├── watcher.ts
      ├── secretScanner.ts
      ├── teamMemSecretGuard.ts
      └── types.ts
      │
      ▼
memdir/teamMemPaths.ts
memdir/teamMemPrompts.ts
      │
      ▼
shared/team memory 被持久化并在需要时注入 query
```

---

## 3. 关键文件职责

### `source/src/services/teamMemorySync/index.ts`
- team memory sync 主入口
- 组织 watcher、scanner、guard、写入/同步流程

### `source/src/services/teamMemorySync/watcher.ts`
- 监听 team memory 变化与同步触发

### `source/src/services/teamMemorySync/secretScanner.ts`
- 在共享 memory 写入前扫描 secrets

### `source/src/services/teamMemorySync/teamMemSecretGuard.ts`
- 防止敏感信息进入 shared/team memory

### `source/src/services/teamMemorySync/types.ts`
- team memory sync 相关类型

### `source/src/memdir/teamMemPaths.ts`
- team/shared memory 的路径规划

### `source/src/memdir/teamMemPrompts.ts`
- team memory 提取/使用时的 prompt 模板

### `source/src/utils/teamMemoryOps.ts`
- team memory 操作辅助工具

### `source/src/components/messages/teamMemCollapsed.tsx`
- team memory collapsed 消息展示

### `source/src/components/messages/teamMemSaved.ts`
- team memory saved 消息辅助

---

## 4. 关键结论

1. **team memory 是独立于普通 memory 的共享层**(==需要详细探究解释说明为什么不同， 哪儿不同==)
2. **因为会跨 agent / teammate / shared context，所以必须加 secret guard**
3. **watcher + scanner + guard 形成 team memory 的写入控制链**
4. **team memory 的路径和 prompt 都是专门建模的，不是复用普通 memory 即可**
