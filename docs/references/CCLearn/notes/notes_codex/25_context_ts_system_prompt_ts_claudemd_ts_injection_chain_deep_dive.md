# 代码审计级深挖 02：`context.ts + systemPrompt.ts + claudemd.ts` 注入链

- 仓库路径：`cc/claude_code`
- 当前主题：**System Prompt 与运行时 Context 注入链的逐层拆解**

---

## 1. 这份文档聚焦什么

这里只研究：

> **静态 system prompt + 动态运行时 context 是如何合成到 prompt 中的**

关键文件：
- `source/src/context.ts`
- `source/src/utils/systemPrompt.ts`
- `source/src/utils/claudemd.ts`
- `source/src/constants/prompts.ts`
- `source/src/constants/systemPromptSections.ts`

---

## 2. 注入链总图

```text
静态基底
  ├── constants/prompts.ts
  └── constants/systemPromptSections.ts
        │
        ▼
system prompt 组装
  └── utils/systemPrompt.ts
        │
        ▼
运行时 context 生成
  ├── context.ts::getSystemContext()
  ├── context.ts::getUserContext()
  └── utils/claudemd.ts
        │
        ▼
claude.ts::buildSystemPromptBlocks(...)
        │
        ▼
最终 system blocks + messages
```

---

## 3. 关键文件职责深拆

### 3.1 `constants/prompts.ts`
- 定义静态 prompt 基底文本
- 是 Claude Code 行为规则和默认提示的一部分来源

### 3.2 `constants/systemPromptSections.ts`
- 定义 system prompt 各 section 的结构与顺序
- 让 system prompt 更稳定、可拆分、可缓存

### 3.3 `utils/systemPrompt.ts`
- 把 sections 与 runtime 注入信息组合起来
- 输出系统层可交给 API 编译器处理的 prompt block 结构

### 3.4 `context.ts`
- `getSystemContext()`：主要提供仓库状态等系统视角信息
- `getUserContext()`：主要提供 CLAUDE.md、日期、用户侧上下文
- 这些 context 在运行时生成，并且会缓存/按需刷新

### 3.5 `utils/claudemd.ts`
- 负责发现与读取 `CLAUDE.md`
- 把本地项目说明文档转成可注入的上下文内容

---

## 4. 这条链最值得注意的设计点

1. **system prompt 与 user context 是分层的，不混成一个大字符串**
2. **CLAUDE.md 是 user-side context，不是静态 system prompt 常量的一部分**
3. **git snapshot / currentDate 这种 runtime 信息来自 `context.ts`，不是 prompt 常量**
4. **`systemPrompt.ts` 更像系统提示结构化组装器，而不是纯文本文件**
5. **最终真正进入 API 之前，还会在 `claude.ts` 再做一次 block 级整合**

---

## 5. 最关键的结论

这条链说明 Claude Code 对 prompt 的设计是：

> **静态规则、运行时仓库信息、项目说明文档、用户侧上下文分层注入，而不是粗暴拼接成一大段文本。**
