# Memory 深拆 02：Durable memdir / paths / versions

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/32_arch_memory_full_framework.md`
- 当前主题：**durable memdir / paths / versions 深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. durable memory 存在哪
2. path override / worktree-shared root / safety validation 怎么做
3. memory 文件结构、版本与识别机制是什么

---

## 2. 主链图

```text
settings/env/project root
      │
      ▼
memdir/paths.ts
  - resolve auto-memory root
  - validate path
      │
      ▼
memdir/memdir.ts
  - durable read/write
      │
      ▼
utils/memory/types.ts
utils/memory/versions.ts
utils/memoryFileDetection.ts
      │
      ▼
被 SessionMemory / extract / autoDream / teamMemory 复用
```

---

## 3. 关键文件职责

### `source/src/memdir/paths.ts`
- 决定 memory 根目录
- 校验 path 安全性
- 控制 trusted settings 才能 override
- 让同仓 worktrees 共享 memory root

### `source/src/memdir/memdir.ts`
- durable memory 目录主服务
- 负责 memory 文件访问与基础读写

### `source/src/utils/memory/types.ts`
- durable memory 领域通用类型定义

### `source/src/utils/memory/versions.ts`
- 版本与兼容性支持
- 让 memory 文件格式可以演进

### `source/src/utils/memoryFileDetection.ts`
- 识别哪些文件属于 memory 文件
- 支撑扫描/读写/注入流程

### `source/src/memdir/memoryTypes.ts`
- memdir 层自己的 memory 类型定义

---

## 4. 关键结论

1. **memory path 是安全边界，不只是路径配置**
2. **durable memory 和 session transcript 是两套不同持久化层**
3. **versions/types/file detection 说明 memory 文件格式是受控演进的，不是随便落文本**
4. **worktree-shared root 让同仓多工作树能共用长期记忆**
