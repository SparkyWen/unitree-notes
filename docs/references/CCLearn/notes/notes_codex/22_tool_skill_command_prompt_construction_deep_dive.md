# Prompt 专项深挖 02：Tool / Skill / Command Prompt 构造

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/20_arch_prompt_assembly_and_cache_framework.md`
- 当前主题：**Tool / Skill / Command Prompt 构造专项深拆**

---

## 1. 这个专项在研究什么

这个专项只聚焦：

1. **工具 prompt/schema 是怎么定义的**
2. **skill prompt / markdown command prompt 是怎么生成的**
3. **plugin command / plugin skill prompt 是怎么生成的**
4. **prompt 中 shell 插值、参数替换、目录注入是怎么做的**

---

## 2. 关键架构图

```text
Tool prompt 层
  └── tools/**/prompt.ts
        │
        ▼
Tool.ts / tools.ts
  - 把 prompt/schema 暴露给模型
        │
        ▼
Skill prompt 层
  ├── skills/loadSkillsDir.ts
  ├── skills/bundledSkills.ts
  ├── skills/bundled/**
  └── skills/mcpSkillBuilders.ts
        │
        ▼
Plugin command prompt 层
  └── utils/plugins/loadPluginCommands.ts
        │
        ▼
Prompt 动态处理层
  ├── utils/promptShellExecution.ts
  ├── utils/promptCategory.ts
  ├── utils/promptEditor.ts
  └── utils/toolSearch.ts
        │
        ▼
最终进入 commands.ts / tools.ts / services/api/claude.ts
```

---

## 3. 工具 prompt 文件职责

tools 下几乎每个家族都带 `prompt.ts`，它们共同承担：
- 向模型暴露工具说明
- 提供 schema/usage/when-to-use 语义
- 帮助 API 层构建 tool schema

### 3.1 tools/**/prompt.ts 全体职责
- `AgentTool/prompt.ts`：AgentTool prompt/schema
- `AskUserQuestionTool/prompt.ts`：AskUserQuestion prompt/schema
- `BashTool/prompt.ts`：BashTool prompt/schema
- `BriefTool/prompt.ts`：BriefTool prompt/schema
- `ConfigTool/prompt.ts`：ConfigTool prompt/schema
- `EnterPlanModeTool/prompt.ts`：EnterPlanModeTool prompt/schema
- `EnterWorktreeTool/prompt.ts`：EnterWorktreeTool prompt/schema
- `ExitPlanModeTool/prompt.ts`：ExitPlanModeTool prompt/schema
- `ExitWorktreeTool/prompt.ts`：ExitWorktreeTool prompt/schema
- `FileEditTool/prompt.ts`：FileEditTool prompt/schema
- `FileReadTool/prompt.ts`：FileReadTool prompt/schema
- `FileWriteTool/prompt.ts`：FileWriteTool prompt/schema
- `GlobTool/prompt.ts`：GlobTool prompt/schema
- `GrepTool/prompt.ts`：GrepTool prompt/schema
- `LSPTool/prompt.ts`：LSPTool prompt/schema
- `ListMcpResourcesTool/prompt.ts`：ListMcpResourcesTool prompt/schema
- `MCPTool/prompt.ts`：MCPTool prompt/schema
- `NotebookEditTool/prompt.ts`：NotebookEditTool prompt/schema
- `PowerShellTool/prompt.ts`：PowerShellTool prompt/schema
- `ReadMcpResourceTool/prompt.ts`：ReadMcpResourceTool prompt/schema
- `RemoteTriggerTool/prompt.ts`：RemoteTriggerTool prompt/schema
- `ScheduleCronTool/prompt.ts`：Cron 家族 prompt/schema
- `SendMessageTool/prompt.ts`：SendMessageTool prompt/schema
- `SkillTool/prompt.ts`：SkillTool prompt/schema
- `SleepTool/prompt.ts`：SleepTool prompt/schema
- `TaskCreateTool/prompt.ts`：TaskCreateTool prompt/schema
- `TaskGetTool/prompt.ts`：TaskGetTool prompt/schema
- `TaskListTool/prompt.ts`：TaskListTool prompt/schema
- `TaskStopTool/prompt.ts`：TaskStopTool prompt/schema
- `TaskUpdateTool/prompt.ts`：TaskUpdateTool prompt/schema
- `TeamCreateTool/prompt.ts`：TeamCreateTool prompt/schema
- `TeamDeleteTool/prompt.ts`：TeamDeleteTool prompt/schema
- `TodoWriteTool/prompt.ts`：TodoWriteTool prompt/schema
- `ToolSearchTool/prompt.ts`：ToolSearchTool prompt/schema
- `WebFetchTool/prompt.ts`：WebFetchTool prompt/schema
- `WebSearchTool/prompt.ts`：WebSearchTool prompt/schema

---

## 4. Skill / Command Prompt 构造核心文件

### 4.1 `source/src/skills/loadSkillsDir.ts`
- 从本地 skills/commands markdown 生成 `PromptCommand`
- 解析 frontmatter：description/allowed-tools/model/effort/hooks/context/agent/shell
- 做参数替换、`${CLAUDE_SKILL_DIR}` / `${CLAUDE_SESSION_ID}` 注入
- 可执行 shell frontmatter 来动态生成 prompt 内容

### 4.2 `source/src/skills/bundledSkills.ts`
- 把代码内 bundled skill definition 转成 `PromptCommand`
- 若附带 files，会落盘并把 base directory 注入 prompt

### 4.3 `source/src/skills/bundled/**`
- 各个 bundled skill 的具体 prompt 内容来源
- 如 `remember.ts`、`simplify.ts`、`verify.ts` 等

### 4.4 `source/src/skills/mcpSkillBuilders.ts`
- 把 MCP 资源/skill/prompt 适配到命令/skill prompt 体系中

### 4.5 `source/src/utils/plugins/loadPluginCommands.ts`
- 从 plugin markdown / inline content / metadata 生成命令 prompt
- 替换 `${CLAUDE_PLUGIN_ROOT}`、`${CLAUDE_PLUGIN_DATA}`、`${user_config.X}`
- 支持 plugin skills 与 plugin commands 双轨构造

---

## 5. Prompt 动态处理辅助文件

### 5.1 `source/src/utils/promptShellExecution.ts`
- 在 prompt 中执行 shell 命令并把结果注入 prompt 内容
- 是 skill / plugin prompt 动态拼接的关键

### 5.2 `source/src/utils/promptCategory.ts`
- 给 prompt 分类，辅助系统识别 prompt 类型/用途

### 5.3 `source/src/utils/promptEditor.ts`
- prompt 编辑辅助，用于构造、调整或可视化 prompt 内容

### 5.4 `source/src/utils/toolSearch.ts`
- 与 deferred tools / tool search 相关的 prompt 面组织辅助

---

## 6. 关键结论

1. **tools 的 prompt 主要承担 schema/能力描述，不像 skill prompt 那样长文本任务模板化**
2. **skills / commands / plugin commands 才是高层 prompt 模板系统的核心来源**
3. **`promptShellExecution.ts` 是动态 prompt 构造里最强的一条链**
4. **plugin command prompt 已经是一等公民，不只是 markdown 附属物**
5. **MCP prompt/skill 也被并入同一 prompt command 体系**

---

## 7. 本专项输出

已完成：
- Tool / Skill / Command Prompt 构造专项架构图
- 核心文件职责说明
- 关键结论整理
