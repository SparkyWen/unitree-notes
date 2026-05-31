# Claude Code 代码库学习地图 - 模块 2：命令系统模块

- 模块名称：命令系统（Slash Commands / Prompt Commands / Local Commands / Skills / Plugin Commands）
- 目标：还原 Claude Code 的命令注册、命令来源、命令协议、技能装载、插件命令装载与动态命令发现机制

---

## 1. 功能概述

Claude Code 的“命令”不是一个单一概念，而是一个统一协议下的多来源集合。

这个模块主要回答：

- `/help`、`/clear`、`/compact` 这类命令是怎么注册的？
- skill 型命令（markdown prompt command）是怎么从目录中发现并转换成命令对象的？
- 插件里的 commands/skills 是怎么接入的？
- bundled skills 和 built-in plugins 有什么区别？
- command 的类型系统如何把“本地 JSX 对话框命令”“本地逻辑命令”“prompt 型技能命令”统一起来？

如果说工具系统是“模型能调用什么能力”，那么命令系统更像：

> **“用户和模型在会话层面可触发的高层操作入口层”**

它既服务用户 slash command，也服务模型技能调用、插件扩展和 MCP skill 暴露。

---

## 2. 解决的问题

### 2.1 命令来源异构
命令可能来自：
- 内建 slash commands
- skills 目录
- 旧版 commands 目录
- 插件 commands
- 插件 skills
- bundled skills
- built-in plugins
- MCP skills
- workflow-backed commands

系统需要把它们统一成可枚举、可显示、可执行、可过滤的对象。

### 2.2 命令类型异构
命令本身也有三大类：
- `prompt`：本质上是把 markdown prompt 注入到会话
- `local`：纯本地逻辑处理
- `local-jsx`：会弹出 UI / Dialog / Interactive flow 的命令

这三类命令需要在同一个 autocomplete、help、dispatch 系统里工作。

### 2.3 markdown 技能需要变成结构化命令对象
markdown 技能并不是简单读文件后拼接给模型，还需要：
- frontmatter 解析
- 参数占位替换
- allowed-tools 解析
- model/effort/context/agent/hooks 等元数据提取
- shell 注入执行
- 安全策略处理

### 2.4 插件命令/技能需要支持强扩展性
插件命令不只是“额外文件”，还要支持：
- 多目录
- metadata override
- inline content
- plugin variable substitution
- user config substitution
- skills 与 commands 双轨加载

### 2.5 命令可见性需要受设置源与策略控制
例如：
- bare 模式下只允许显式路径
- project settings / policy / plugin-only 策略会影响 skills 可用性
- built-in plugin 是否启用由 user settings 决定

---

## 3. 涉及文件（本轮深读）

1. `source/src/commands.ts`
2. `source/src/types/command.ts`
3. `source/src/skills/loadSkillsDir.ts`
4. `source/src/skills/bundledSkills.ts`
5. `source/src/plugins/builtinPlugins.ts`
6. `source/src/utils/plugins/loadPluginCommands.ts`
7. `source/src/utils/settings/constants.ts`

此外，本轮还扫描了整个 `source/src/commands/**` 子树，用于后续逐命令补齐。

---

## 4. 模块核心入口文件

### 核心入口文件
- `source/src/commands.ts`

### 最值得先读的 3~8 个文件
1. `source/src/commands.ts`
2. `source/src/types/command.ts`
3. `source/src/skills/loadSkillsDir.ts`
4. `source/src/utils/plugins/loadPluginCommands.ts`
5. `source/src/skills/bundledSkills.ts`
6. `source/src/plugins/builtinPlugins.ts`
7. `source/src/utils/settings/constants.ts`

### 容易被忽视但关键的文件
- `source/src/types/command.ts`
- `source/src/skills/loadSkillsDir.ts`
- `source/src/utils/settings/constants.ts`

很多人会只盯 `commands.ts` 和 `commands/**`，但真正理解命令系统，必须先理解：
- 命令协议长什么样
- skills 如何转成命令
- 设置源如何控制命令发现边界

---

## 5. 整体调用链 / 执行流程

先给一个命令系统总图：

```text
main.tsx / setup.ts
  -> getCommands(cwd)
      -> commands.ts
          -> 注册 builtin slash commands
          -> getSkillDirCommands(cwd)
              -> loadSkillsDir.ts
                  -> 从 skills/ 与 legacy commands/ 读 markdown
                  -> parse frontmatter
                  -> createSkillCommand()
          -> getBundledSkills()
              -> bundledSkills.ts
          -> getBuiltinPluginSkillCommands()
              -> builtinPlugins.ts
          -> getPluginCommands() / getPluginSkills()
              -> loadPluginCommands.ts
          -> 可能再合并 workflow / MCP command
      -> 返回统一 Command[]
  -> UI autocomplete / slash dispatch / 模型可调用命令列表 使用这些命令
```

这说明命令系统不是简单静态表，而是一个**多来源命令聚合器**。

---

## 6. 核心文件详细讲解

---

## 6.1 `source/src/commands.ts`

### 文件作用
这是**命令系统总注册中心**。

它负责：
- 定义内建命令集合
- 统一加载不同来源命令
- 过滤可见性/可用性
- 输出最终命令列表

### 为什么它是中枢
因为所有命令最终都要在这里汇总成统一的 `Command[]`。

### 当前已确认的职责
从上一轮读取可确定它至少承担：
- builtin commands
- internal-only commands
- dynamic skill discovery
- plugin commands / plugin skills
- bundled skills
- workflow commands
- remote-safe / bridge-safe 过滤

### 设计意图
让调用方只关心：
- 我要一个可用命令列表

而不关心：
- 命令到底来自内建、技能、插件还是 MCP

### 它解决的核心工程问题
**把“命令来源异构性”收敛到一个统一出口。**

### 设计优点
- 上层（REPL / UI / dispatch）不用感知来源差异
- 可集中做排序、过滤、可见性控制、来源标识
- 未来增加新命令源时，接入点清晰

### 潜在风险
- `commands.ts` 容易越来越胖
- 各类来源命令都耦合到这个中枢，调试时需要跳很多层

> 后续我会专门再补一轮 `commands.ts` 逐函数深拆。

---

## 6.2 `source/src/types/command.ts`

### 文件作用
这是整个命令系统的**协议定义中心**。

如果没有它，你很难真正理解命令系统，因为它定义了：
- 命令有哪些种类
- 每种命令的执行契约是什么
- 命令完成后的回调与显示行为是什么
- 命令如何嵌入 ToolUseContext

### 这个文件的重要性
非常高。

它不是普通类型文件，而是：

> **命令系统的领域模型定义文件**

---

### 核心类型拆解

#### 1) `PromptCommand`

这是 skill / markdown command / prompt command 的类型。

##### 关键字段
- `type: 'prompt'`
- `progressMessage`
- `contentLength`
- `argNames?`
- `allowedTools?`
- `model?`
- `source`
- `pluginInfo?`
- `disableNonInteractive?`
- `hooks?`
- `skillRoot?`
- `context?: 'inline' | 'fork'`
- `agent?`
- `effort?`
- `paths?`
- `getPromptForCommand(args, context)`

##### 为什么重要
这说明 skill 不是一段死文本，而是可执行配置对象：
- 能带参数
- 能指定模型
- 能声明允许工具
- 能声明 fork 到 sub-agent
- 能挂 hooks
- 能设置 effort
- 能做路径条件激活

##### 设计亮点
它把 markdown 技能从“文档”提升成了“可执行命令描述对象”。

---

#### 2) `LocalCommand`

##### 关键字段
- `type: 'local'`
- `supportsNonInteractive`
- `load(): Promise<LocalCommandModule>`

##### 模块形态
`LocalCommandModule = { call: LocalCommandCall }`

##### 含义
这类命令：
- 不是 prompt 注入
- 也不是 JSX UI
- 而是本地逻辑运行

并且采用 lazy load。

---

#### 3) `LocalJSXCommand`

##### 关键字段
- `type: 'local-jsx'`
- `load(): Promise<LocalJSXCommandModule>`

##### 模块形态
`LocalJSXCommandModule = { call: LocalJSXCommandCall }`

##### 含义
这类命令会：
- 打开一个 JSX/Ink 交互界面
- 通常用于配置、登录、安装、向导、dialog 类命令

比如 `/login`、`/plugin`、`/permissions` 这类命令通常会更偏这一类。

---

#### 4) `CommandBase`

这是所有命令共享元数据。

##### 关键字段
- `availability?`
- `description`
- `hasUserSpecifiedDescription?`
- `isEnabled?`
- `isHidden?`
- `name`
- `aliases?`
- `isMcp?`
- `argumentHint?`
- `whenToUse?`
- `version?`
- `disableModelInvocation?`
- `userInvocable?`
- `loadedFrom?`
- `kind?: 'workflow'`
- `immediate?`
- `isSensitive?`
- `userFacingName?`

##### 这套字段说明什么
命令系统不只是执行系统，还是一个：
- autocomplete 元数据系统
- help 元数据系统
- 访问控制系统
- 来源溯源系统

---

#### 5) `Command = CommandBase & (PromptCommand | LocalCommand | LocalJSXCommand)`

这是最重要的组合定义。

它的意义是：

> 上层永远只需要处理 `Command`，而不用纠结来源与执行模式。

然后在真正执行时按 `type` 分派。

---

### 关键辅助函数

#### `getCommandName(cmd)`
- 解析用户可见命令名，默认回退 `cmd.name`

#### `isCommandEnabled(cmd)`
- 如果没定义 `isEnabled`，默认 true

这两个函数看似简单，但它们把“命令对象协议默认值”标准化了。

---

### 设计意图
- 统一命令抽象
- 支持 lazy loading
- 支持 prompt/local/local-jsx 三种执行模型
- 支持命令来源溯源
- 支持模型调用与用户调用分离

### 容易忽略的关键点

#### 点 1：`availability` 和 `isEnabled()` 是两层概念
源码注释已经讲得很清楚：
- `availability` = 你属于哪类用户/认证模式，静态资格
- `isEnabled()` = 当前功能是否开着，动态开关

这是一种很成熟的权限/可用性分层。

#### 点 2：`loadedFrom` 与 `source` 不是完全同义
- `source` 更偏运行来源/逻辑来源
- `loadedFrom` 更偏被哪个加载器接入

#### 点 3：`isSensitive` 支持参数脱敏
这是日志/历史记录安全边界的重要基础。

---

## 6.3 `source/src/skills/loadSkillsDir.ts`

### 文件作用
这是**文件系统技能命令加载器**。

它负责把磁盘上的 skills / legacy commands markdown 文件，转换成标准 `Command`。

这是整个命令系统里最值得深入理解的文件之一。

---

### 它解决的问题
技能目录不是统一格式，系统要同时支持：

#### 现代格式
- `/skills/skill-name/SKILL.md`

#### 旧格式
- `/commands/foo.md`
- `/commands/bar/SKILL.md`

还要处理：
- frontmatter
- shell frontmatter
- allowed-tools
- argument substitution
- dynamic paths activation
- hooks
- userInvocable
- source / loadedFrom
- file-level deduplication
- additional directories (`--add-dir`)
- policy / project settings / bare mode / plugin-only lock

---

### 关键函数拆解

#### 函数 1：`getSkillsPath(source, dir)`

##### 作用
根据 setting source 推导不同的 skills/commands 根目录。

##### 逻辑
- `policySettings` -> managed path 下的 `.claude/dir`
- `userSettings` -> `~/.claude/dir`
- `projectSettings` -> `.claude/dir`
- `plugin` -> `plugin`

##### 价值
把“设置源”和“实际磁盘位置”统一映射起来。

---

#### 函数 2：`parseSkillFrontmatterFields(frontmatter, markdownContent, resolvedName, descriptionFallbackLabel)`

这是 skill 解析最核心的函数之一。

##### 输入参数
- `frontmatter`
- `markdownContent`
- `resolvedName`
- `descriptionFallbackLabel`

##### 返回值
一组结构化字段：
- `displayName`
- `description`
- `hasUserSpecifiedDescription`
- `allowedTools`
- `argumentHint`
- `argumentNames`
- `whenToUse`
- `version`
- `model`
- `disableModelInvocation`
- `userInvocable`
- `hooks`
- `executionContext`
- `agent`
- `effort`
- `shell`

##### 内部执行步骤
```ts
1. 校验 description frontmatter
2. 若无 description，则从 markdown 正文提取描述
3. 解析 user-invocable
4. 解析 model（支持 inherit / alias）
5. 解析 effort
6. 解析 allowed-tools
7. 解析 argument-hint / arguments
8. 解析 when_to_use / version
9. 解析 hooks
10. 解析 context=fork / agent
11. 解析 shell frontmatter
```

##### 为什么重要
这说明一个 skill markdown 文件，并不是“内容 + 名称”这么简单，而是能表达一整套执行元数据。

---

#### 函数 3：`createSkillCommand(...)`

这是把解析后的 skill 数据真正变成 `Command` 的工厂函数。

##### 输入
大量结构化字段，包括：
- `skillName`
- `displayName`
- `description`
- `markdownContent`
- `allowedTools`
- `source`
- `baseDir`
- `loadedFrom`
- `hooks`
- `executionContext`
- `agent`
- `paths`
- `effort`
- `shell`

##### 返回值
一个 `Command`（类型为 `prompt`）

##### 内部执行逻辑
重点在 `getPromptForCommand(args, toolUseContext)`：

```ts
finalContent = markdownContent
if baseDir:
  前缀加上 Base directory for this skill: ...

finalContent = substituteArguments(finalContent, args, ...)
替换 ${CLAUDE_SKILL_DIR}
替换 ${CLAUDE_SESSION_ID}

如果 loadedFrom !== 'mcp':
  executeShellCommandsInPrompt(finalContent, context, `/${skillName}`, shell)

返回 [{ type: 'text', text: finalContent }]
```

##### 最关键的设计点

###### 设计点 1：skills 会注入 base directory
这样模型就知道：
- 技能相关参考文件在哪里
- 可以再用 Read/Grep 去读它们

###### 设计点 2：参数替换是命令级能力
说明 skill 不只是静态 prompt，还可以参数化。

###### 设计点 3：skill markdown 里支持 shell command execution
但 **MCP skills 被明确禁止执行 inline shell**。

这是很关键的安全边界：
- 本地技能可以在 trust/permission 框架下执行 shell injection
- 远端 MCP skills 被视为不可信，不能这样做

###### 设计点 4：通过改写 `getAppState().toolPermissionContext.alwaysAllowRules.command`
让 executeShellCommandsInPrompt 在 skill 允许的工具范围内运行。

这说明 skill prompt 的 shell 注入，不是完全自由执行，而是要走允许工具规则。

---

#### 函数 4：`loadSkillsFromSkillsDir(basePath, source)`

##### 作用
从现代 `/skills/` 目录加载技能。

##### 支持格式
只支持：
- `skill-name/SKILL.md`

##### 不支持
- 单文件 `.md`

##### 实现逻辑
- 遍历目录项
- 只接受目录或符号链接
- 读取 `SKILL.md`
- 解析 frontmatter
- `createSkillCommand()`

---

#### 函数 5：`loadSkillsFromCommandsDir(cwd)`

##### 作用
兼容老式 `/commands/` 目录。

##### 支持格式
- 普通 `.md`
- `SKILL.md` 目录式格式

##### 特别处理
通过 `transformSkillFiles()`：
- 如果某目录下有 `SKILL.md`
- 就只加载这个 skill file
- 忽略同目录其他普通 md，避免命令冲突

这是很有经验的兼容设计。

---

#### 函数 6：`getSkillDirCommands(cwd)`

这是 skill 加载的总入口。

##### 作用
从所有可能来源加载技能，并输出统一 `Command[]`

##### 来源包括
- managed skills dir
- user skills dir
- project skills dirs
- additional dirs (`--add-dir`)
- legacy commands dir

##### 关键逻辑

###### bare 模式
- 跳过自动发现
- 只加载显式 `--add-dir`
- 仍受 `projectSettingsEnabled` / policy 约束

###### skillsLocked / projectSettingsEnabled
- 如果策略锁为 plugin-only，就禁用 skills discovery

###### 并行加载
所有目录来源并行读取，提高速度。

###### file identity dedup
使用 `realpath()` 做文件身份去重，避免：
- 符号链接重复
- 父目录重叠导致重复加载

###### conditional skills
带 `paths` frontmatter 的 skill：
- 初始不直接加入 unconditional skills
- 先放到 `conditionalSkills`
- 只有当用户/模型触碰到匹配路径时才激活

这非常关键。

---

### 动态技能发现机制

#### `discoverSkillDirsForPaths(filePaths, cwd)`

##### 作用
根据“当前操作到的文件路径”，向上回溯搜索嵌套 `.claude/skills` 目录。

##### 设计意义
技能不是只能在启动时静态装载。
它还支持：
- 当模型开始接触某个子目录文件
- 才发现该目录局部 skill

这是一种很聪明的上下文局部化机制。

#### `addSkillDirectories(dirs)`
- 加载动态发现的目录
- deeper path 优先覆盖 shallower path
- 成功后发 `skillsLoaded` signal

#### `activateConditionalSkillsForPaths(filePaths, cwd)`
- 用 `ignore` 库匹配 gitignore 风格 paths
- 一旦某 skill 匹配文件路径，就转入 `dynamicSkills`
- 记录 telemetry

这意味着命令系统和文件访问行为之间是联动的。

---

### 安全性分析
- MCP skills 禁止 shell inline execution
- gitignored 目录中的 skills 不自动发现
- bare 模式严控自动发现范围
- policy / plugin-only 限制会阻断技能目录加载

### 性能分析
- `memoize(getSkillDirCommands)`
- 多目录并行加载
- `realpath` 预计算去重
- conditional skills 延迟激活
- dynamic skill discovery 缓存已检查目录

### 设计亮点总结
这是一个非常成熟的“markdown skill -> executable command”转译器。

---

## 6.4 `source/src/skills/bundledSkills.ts`

### 文件作用
这是**内置 bundled skills 注册表**。

这些技能：
- 跟 CLI 一起发版
- 编译进产物
- 对所有用户可用

### 和普通 skills 的区别
普通 skills 来自磁盘目录；bundled skills 来自代码注册。

### 和 built-in plugins 的区别
bundled skills：
- 更像“内建 skill”
- 直接注册成命令
- 不经过 /plugin 启停界面

built-in plugins：
- 在 /plugin UI 中出现
- 用户可启停
- 可包含 skill/hook/MCP server 多种组件

---

### 核心函数

#### `registerBundledSkill(definition)`

##### 输入
`BundledSkillDefinition`
关键字段包括：
- `name`
- `description`
- `aliases?`
- `whenToUse?`
- `argumentHint?`
- `allowedTools?`
- `model?`
- `disableModelInvocation?`
- `userInvocable?`
- `isEnabled?`
- `hooks?`
- `context?`
- `agent?`
- `files?`
- `getPromptForCommand`

##### 逻辑亮点
如果 skill 带 `files`：
- 计算 extraction dir
- 在首次调用时懒提取 reference files 到磁盘
- 然后把 `Base directory for this skill: ...` 前缀加到 prompt 前面

##### 为什么这么设计
因为 bundled skill 的参考文件原本在二进制里，不在文件系统。
模型如果要再 Read/Grep，就必须先把这些参考文件落盘。

这就是一种：
> **把编译进产物的资源，在首次需要时 materialize 到磁盘**

---

#### `extractBundledSkillFiles(skillName, files)`
- 提取 bundled skill 附带文件到固定目录
- 返回目录路径，失败则返回 null

#### `writeSkillFiles(dir, files)`
- 按 parent dir 分组写入
- 先 mkdir，再 safeWriteFile

#### `safeWriteFile(p, content)``
- 使用 `O_EXCL` / `O_NOFOLLOW` / 0600
- Windows 用 `'wx'`

#### `resolveSkillFilePath(baseDir, relPath)`
- 拦截 path traversal
- 禁止 `..` 和绝对路径逃逸

### 安全设计亮点
这个文件虽然只是 bundled skill 支持，但安全做得非常细：
- owner-only mode
- nofollow
- traversal 防御
- 写失败 skill 仍可工作，只是没有 base dir prefix

这属于“防御式资源提取”设计。

---

## 6.5 `source/src/plugins/builtinPlugins.ts`

### 文件作用
这是**内建插件注册表**。

### 它解决的问题
有些功能不适合做成“永远开启的 bundled skill”，而更适合做成：
- 随 CLI 附带
- 能被用户在 /plugin UI 里启用/禁用
- 还能同时提供 hooks / MCP servers / skills

于是就有了 built-in plugin 概念。

---

### 核心数据结构
- `BUILTIN_PLUGINS: Map<string, BuiltinPluginDefinition>`
- `BUILTIN_MARKETPLACE_NAME = 'builtin'`

### 核心函数

#### `registerBuiltinPlugin(definition)`
注册内建插件定义。

#### `isBuiltinPluginId(pluginId)`
判断 `{name}@builtin` 格式。

#### `getBuiltinPluginDefinition(name)`
供 /plugin UI 查询。

#### `getBuiltinPlugins()`

##### 作用
根据 user settings，把 built-in plugins 分成：
- enabled
- disabled

##### 逻辑
- 读取 `enabledPlugins[pluginId]`
- 若用户没显式设置，则 fallback 到 `defaultEnabled ?? true`
- 组装成 `LoadedPlugin`

##### 关键点
这里已经把“代码定义的 plugin”映射成“运行态已加载插件对象”。

#### `getBuiltinPluginSkillCommands()`

##### 作用
从 enabled built-in plugins 中，把 skill definitions 转成 `Command[]`

##### 内部逻辑
- 先 `getBuiltinPlugins()` 只取 enabled
- 遍历 `definition.skills`
- 用 `skillDefinitionToCommand()` 转为 `Command`

### `skillDefinitionToCommand()` 设计细节
它把 built-in plugin skill 映射成：
- `type: 'prompt'`
- `source: 'bundled'`
- `loadedFrom: 'bundled'`

源码注释特地说明：
**虽然它来自 built-in plugin，但 source 仍然用 `bundled`，不是 `builtin`。**

原因是：
- `builtin` 在命令 source 里意味着硬编码 slash commands
- 使用 `bundled` 能让这些技能继续出现在 Skill tool listing、analytics、prompt truncation exemption 中

这属于非常细的领域语义区分。

---

## 6.6 `source/src/utils/plugins/loadPluginCommands.ts`

### 文件作用
这是**插件 commands / skills 加载器**。

它把启用状态的 marketplace / inline plugin 中的命令与技能，装配成 `Command[]`。

这是命令系统里另一个非常重的文件。

---

### 它解决的问题
插件比本地 skill 更复杂，因为它支持：
- commandsPath
- commandsPaths
- skillsPath
- skillsPaths
- commandsMetadata
- inline content
- source file + metadata override
- plugin root variables
- user config substitution
- plugin-level dedup

---

### 关键函数拆解

#### 1) `collectMarkdownFiles(dirPath, baseDir, loadedPaths)`

##### 作用
递归收集插件目录内 markdown 文件。

##### 特点
- 用 `walkPluginMarkdown`
- 遇到 skill dir 时会 stopAtSkillDir
- 用 `isDuplicatePath` 避免重复路径

---

#### 2) `getCommandNameFromFile(filePath, baseDir, pluginName)`

##### 作用
根据文件路径计算命令名。

##### 命名规则
- skill 文件：用父目录名
- 普通 markdown：用文件名去 `.md`
- 命名统一加 plugin 前缀，并支持 namespace 层级

例如会变成：
- `pluginName:foo`
- `pluginName:ns:bar`

##### 设计意图
插件命令名必须 namespace 化，避免和其他命令冲突。

---

#### 3) `createPluginCommand(...)`

这是插件命令的核心工厂函数。

##### 输入
- `commandName`
- `file`
- `sourceName`
- `pluginManifest`
- `pluginPath`
- `isSkill`
- `config`

##### 关键解析逻辑
- 解析 description
- 解析 allowed-tools（先做 plugin variable substitution）
- 解析 argument-hint / arguments / whenToUse / version / displayName
- 解析 model / effort
- 解析 disable-model-invocation / user-invocable
- 解析 shell frontmatter

##### `getPromptForCommand()` 的关键逻辑
```ts
finalContent = content
if skill mode:
  加 Base directory for this skill

substituteArguments(finalContent, args)
substitutePluginVariables(${CLAUDE_PLUGIN_ROOT}, ${CLAUDE_PLUGIN_DATA})
substituteUserConfigInContent(${user_config.X})
if skillMode:
  替换 ${CLAUDE_SKILL_DIR}
替换 ${CLAUDE_SESSION_ID}
executeShellCommandsInPrompt(...)
return text block
```

##### 安全设计亮点
- `${user_config.X}` 对敏感 key 不直接暴露真实值
- shell execution 仍然挂在 permission context 下
- plugin variables 统一替换，避免 prompt 作者自己拼路径

---

#### 4) `getPluginCommands()`

##### 作用
加载所有已启用插件里的 commands。

##### 关键逻辑
- bare 模式下，如果没有显式 `--plugin-dir`，直接返回空
- `loadAllPluginsCacheOnly()` 只取 enabled plugins
- 每个 plugin 并行处理
- 同一个 plugin 内部用 `loadedPaths` 去重

##### 它支持的命令来源
1. `plugin.commandsPath`
2. `plugin.commandsPaths`
3. `plugin.commandsMetadata` with source file override
4. `plugin.commandsMetadata` with inline content

##### 这是最强的地方
插件命令不止能来自文件，还能：
- 通过 metadata 覆盖 frontmatter
- 甚至完全以内联 content 的形式定义命令

这让插件 manifest 拥有极强的命令定义能力。

---

#### 5) `loadSkillsFromDirectory(...)`

##### 作用
加载插件 skills。

##### 支持两种情况
1. 传入的目录本身就是 skill dir（直接有 `SKILL.md`）
2. 目录里有若干子目录，每个子目录是一个 skill dir

##### 设计点
这和本地 skills loader 的格式保持一致，但命名会自动加插件前缀。

---

#### 6) `getPluginSkills()`

##### 作用
加载所有启用插件中的 skills。

##### 逻辑
- bare 模式同样遵守 inline plugin 例外
- 只加载 enabled plugins
- 从 `skillsPath` / `skillsPaths` 读取
- 最终返回标准 `Command[]`

---

### 性能分析
- `memoize(getPluginCommands)` / `memoize(getPluginSkills)`
- 插件级并行
- path 级并行
- `loadedPaths` 去重避免重复解析

### 安全性分析
- bare 模式默认禁 marketplace plugin auto-load
- user config 替换不直接泄露敏感值
- shell 执行仍经 executeShellCommandsInPrompt + permission context

### 设计亮点总结
这个文件让插件命令系统具备了“接近一等公民”的能力，已经远不只是简单扩展脚本。

---

## 6.7 `source/src/utils/settings/constants.ts`

### 文件作用
这是**设置源定义中心**。

它本身不是命令加载器，但它决定了：
- 哪些 settings source 可以启用
- skills/commands 应从哪些层读取
- source display name 如何显示

因此它是命令系统的关键基础设施。

---

### 核心常量

#### `SETTING_SOURCES`
顺序非常重要：
1. `userSettings`
2. `projectSettings`
3. `localSettings`
4. `flagSettings`
5. `policySettings`

源码注释已经说明：
**后面的 source 覆盖前面的 source。**

### 核心函数

#### `parseSettingSourcesFlag(flag)`
把 CLI `--setting-sources` 转成 `SettingSource[]`

#### `getEnabledSettingSources()`
返回允许的 source，并强制把：
- `policySettings`
- `flagSettings`
始终加入

#### `isSettingSourceEnabled(source)`
判断某个 source 当前是否有效。

### 为什么对命令系统重要
`loadSkillsDir.ts` 就依赖这里去判断：
- user skills 可不可读
- project skills 可不可读
- bare 模式 / policy / flag 下的装载边界

也就是说，这个文件定义的是：

> **命令/技能发现的“配置合法边界”**

---

## 7. 数据流 / 状态流

### 7.1 命令装载状态流

```text
启动时 main/setup
  -> getCommands(cwd)
      -> builtin commands
      -> getSkillDirCommands(cwd)
      -> getBundledSkills()
      -> getBuiltinPluginSkillCommands()
      -> getPluginCommands()
      -> getPluginSkills()
      -> workflow/MCP commands
  -> 输出统一 Command[]
  -> autocomplete/help/dispatch/model-invocation 使用
```

### 7.2 skill markdown -> prompt command 数据流

```text
SKILL.md / foo.md
  -> parseFrontmatter()
  -> parseSkillFrontmatterFields()
  -> createSkillCommand()
      -> 形成 type='prompt' 的 Command
      -> getPromptForCommand() 内做参数替换 / shell 执行 / env substitution
  -> 最终交给命令系统注册
```

### 7.3 plugin markdown -> command 数据流

```text
plugin manifest / plugin commandsPath / commandsMetadata
  -> collectMarkdownFiles()
  -> createPluginCommand()
      -> 替换 plugin variables / user config / skill dir / session id
      -> executeShellCommandsInPrompt()
  -> 返回 Command[]
```

### 7.4 conditional skill 激活流

```text
启动时加载 skills
  -> 带 paths frontmatter 的技能先进入 conditionalSkills
  -> 文件操作发生后
  -> activateConditionalSkillsForPaths(filePaths, cwd)
  -> 命中 pattern
  -> skill 转入 dynamicSkills
  -> skillsLoaded.emit()
  -> 上层清缓存 / 刷新命令列表
```

---

## 8. 配置项 / 环境变量 / 依赖注入方式

### 8.1 关键配置来源
- settings sources (`user/project/local/flag/policy`)
- `--add-dir`
- bare 模式
- plugin-only policy
- managed path
- plugin manifest
- commandsMetadata / skillsPath / commandsPath

### 8.2 关键环境/状态影响项

| 项目 | 来源 | 影响 |
|---|---|---|
| `isBareMode()` | env/CLI 模式 | 阻断自动 skills/plugin commands 发现 |
| `getAdditionalDirectoriesForClaudeMd()` | bootstrap state | 加载额外目录中的 `.claude/skills` |
| `isRestrictedToPluginOnly('skills')` | policy/settings | 禁用目录技能加载 |
| `isSettingSourceEnabled('projectSettings')` | settings constants | 决定 project skills 是否装载 |
| `getInlinePlugins()` | bootstrap state | bare 模式下允许显式 plugin-dir |
| `enabledPlugins[pluginId]` | user settings | 决定 built-in plugin 启停 |

### 8.3 依赖注入方式

#### 方式 1：Command 对象内闭包注入
例如：
- `getPromptForCommand(args, context)`

#### 方式 2：ToolUseContext 注入
命令生成 prompt 时能拿到完整 tool/use/session/appState 上下文。

#### 方式 3：global bootstrap state
例如：
- `getSessionId()`
- `getAdditionalDirectoriesForClaudeMd()`
- `getInlinePlugins()`

#### 方式 4：plugin manifest / frontmatter 元数据
决定命令行为、显示与安全边界。

---

## 9. 错误处理 / 边界条件

### `loadSkillsDir.ts`
- 读目录失败：记录错误，返回空
- `SKILL.md` 不存在：静默跳过
- invalid hooks：log debug，忽略 hooks
- invalid effort：log debug，忽略 effort
- file identity 获取失败：不 dedup，但继续加载
- outside cwd / invalid relative path：conditional path activation 直接跳过

### `bundledSkills.ts`
- 文件提取失败：只是不加 baseDir prefix，skill 仍可运行
- path traversal：直接抛错阻止写入

### `builtinPlugins.ts`
- unavailable built-in plugin：直接 omit
- user setting 未定义：fallback 到 defaultEnabled

### `loadPluginCommands.ts`
- 插件加载错误：记录但尽量继续
- custom path 不是目录/文件：跳过
- metadata/source 对不上：回退到文件名推断
- inline content 解析失败：只跳过该命令

---

## 10. 安全性 / 性能 / 扩展性分析

### 10.1 安全性

#### 做得好的地方
1. **MCP skills 禁止 shell inline execution**
2. **bare 模式严格限制自动加载范围**
3. **plugin-only policy 真正影响 skills 发现**
4. **bundled skill 文件提取有 traversal / symlink / mode 防护**
5. **user_config 敏感值不会直接裸注入 prompt**

#### 仍值得关注的点
- 本地/plugin markdown skill 支持 shell 执行，这本身能力很强，必须依赖外层 permission/trust 体系兜底
- 插件命令内容来源复杂，审计成本高

### 10.2 性能

#### 优化手段
- memoize 缓存命令加载
- 多目录并行
- 插件并行
- 文件身份去重
- 动态技能延迟激活
- 已检查技能目录缓存

#### 成本点
- frontmatter 解析和 markdown 扫描量大时仍可能昂贵
- 插件命令多时命令聚合会变重

### 10.3 扩展性
命令系统扩展性很强，原因是：
- 统一 `Command` 协议
- markdown -> command 的工厂函数清晰
- plugin skill / command 和 local skill / command 都能接入同一模型
- built-in / bundled / plugin / managed / mcp 都能在 `commands.ts` 聚合

这是这个项目工程设计里非常强的一块。

---

## 11. 与其他模块的关系

### 上游
- 启动模块：`main.tsx`, `setup.ts`
- 设置系统：`utils/settings/**`
- 插件系统：`utils/plugins/**`
- 技能系统：`skills/**`

### 下游
- REPL slash command 选择器与执行器
- Help / autocomplete UI
- 模型技能调用 / prompt command dispatch
- 远程/桥接模式下命令过滤

### 关键耦合点
- `ToolUseContext`：prompt command 执行时需要它
- `settings/constants.ts`：决定装载边界
- `bootstrap/state.ts`：提供 sessionId、additional dirs、inline plugins

---

## 12. 学习这个模块时建议的阅读顺序

### 推荐顺序
1. `source/src/types/command.ts`
2. `source/src/commands.ts`
3. `source/src/skills/loadSkillsDir.ts`
4. `source/src/utils/plugins/loadPluginCommands.ts`
5. `source/src/skills/bundledSkills.ts`
6. `source/src/plugins/builtinPlugins.ts`
7. `source/src/utils/settings/constants.ts`
8. 然后再进入 `source/src/commands/**` 逐命令目录

### 为什么这样排
- 先看协议
- 再看聚合器
- 再看两种最复杂来源：本地 skills 与 plugin commands
- 最后再看内建与设置边界

---

## 13. 容易忽略但关键的隐藏细节

### 细节 1：skills 并不是启动时一次性静态装载完
有 dynamic discovery 和 conditional activation。

### 细节 2：带 `paths` 的 skills 默认不直接给模型看
只有真正接触匹配文件才激活。

### 细节 3：bundled skill 的 files 不是编译时就落盘，而是首次调用时懒提取
这兼顾了首屏速度与可读资源支持。

### 细节 4：plugin command 支持 metadata override 与 inline content
说明插件 manifest 自身就能成为命令定义的一部分。

### 细节 5：`Command.source` / `loadedFrom` / pluginInfo / availability / isEnabled 都是不同维度
把这些混为一谈会看不懂命令系统。

---

## 14. 逐文件精讲（本轮覆盖文件）

### 14.1 `source/src/commands.ts`
- **文件作用**：命令系统总注册中心
- **导出的内容**：命令列表构建/聚合相关函数
- **主要逻辑**：收集 builtin、skills、plugins、bundled、workflow、mcp 等来源命令
- **被谁使用**：`main.tsx`, `setup.ts`, REPL/dispatcher/autocomplete
- **依赖了谁**：`types/command.ts`, `skills/loadSkillsDir.ts`, plugin 命令加载器等
- **是否值得重点精读**：极高

### 14.2 `source/src/types/command.ts`
- **文件作用**：命令协议模型定义
- **导出的内容**：`Command`, `PromptCommand`, `LocalCommand`, `LocalJSXCommand`, 回调类型与辅助函数
- **主要逻辑**：统一命令类型系统与执行契约
- **被谁使用**：整个命令系统、UI、dispatcher
- **依赖了谁**：ToolUseContext、message/types、settings/constants 等
- **是否值得重点精读**：极高

### 14.3 `source/src/skills/loadSkillsDir.ts`
- **文件作用**：本地技能/legacy commands 加载器
- **导出的内容**：`getSkillDirCommands`, `createSkillCommand`, `parseSkillFrontmatterFields`, 动态技能发现相关函数
- **主要逻辑**：扫描 markdown、frontmatter 解析、转 Command、dedup、conditional activation、dynamic discovery
- **被谁使用**：`commands.ts`、MCP skill builder registry、测试
- **依赖了谁**：frontmatter parser、markdown loader、settings/constants、bootstrap/state、argument substitution
- **是否值得重点精读**：极高

### 14.4 `source/src/skills/bundledSkills.ts`
- **文件作用**：bundled skill 注册与懒提取
- **导出的内容**：`registerBundledSkill`, `getBundledSkills`, `clearBundledSkills` 等
- **主要逻辑**：把代码内定义的 skill 转成 Command，并在首次调用时安全落盘附带文件
- **被谁使用**：bundled skills 初始化、`commands.ts`
- **依赖了谁**：filesystem permissions utils、ToolUseContext
- **是否值得重点精读**：高

### 14.5 `source/src/plugins/builtinPlugins.ts`
- **文件作用**：内建插件注册表
- **导出的内容**：built-in plugin 注册、查询、转 skill commands
- **主要逻辑**：依据 user settings 计算 built-in plugin enabled/disabled，并暴露技能命令
- **被谁使用**：/plugin UI、`commands.ts`
- **依赖了谁**：settings、plugin types、bundled skill definition
- **是否值得重点精读**：中高

### 14.6 `source/src/utils/plugins/loadPluginCommands.ts`
- **文件作用**：插件 commands/skills 加载器
- **导出的内容**：`getPluginCommands`, `getPluginSkills`, cache clear helpers
- **主要逻辑**：递归扫描 markdown、命名空间化、frontmatter 解析、plugin variable/user config 替换、metadata override、inline content 支持
- **被谁使用**：`commands.ts`
- **依赖了谁**：plugin loader、frontmatter parser、markdown walker、plugin options storage、ToolUseContext
- **是否值得重点精读**：极高

### 14.7 `source/src/utils/settings/constants.ts`
- **文件作用**：设置源常量与启用规则
- **导出的内容**：`SETTING_SOURCES`, `isSettingSourceEnabled`, `parseSettingSourcesFlag` 等
- **主要逻辑**：定义 settings source 优先级与启用边界
- **被谁使用**：skills/commands/settings/permissions 多模块
- **依赖了谁**：bootstrap/state
- **是否值得重点精读**：高

---

## 15. 本轮已完成分析的文件列表（相对路径）

- `source/src/commands.ts`
- `source/src/types/command.ts`
- `source/src/skills/loadSkillsDir.ts`
- `source/src/skills/bundledSkills.ts`
- `source/src/plugins/builtinPlugins.ts`
- `source/src/utils/plugins/loadPluginCommands.ts`
- `source/src/utils/settings/constants.ts`
- 以及 `source/src/commands/**` 全目录文件清单扫描

---

## 16. 本轮未完成但下一轮建议继续分析的模块

1. 工具系统模块（`tools.ts` + `tools/**` + `Tool.ts` 深拆）
2. Agent 主循环模块（`query.ts` + compact/tool executor/api stream）
3. `source/src/commands/**` 逐命令补齐与分组讲解
4. 文件总索引表第二批（commands/tools/query）

---

## 17. 当前累计已覆盖文件数 / 总文件数

- 已完成深读与模块级分析：**23 / 1954**
- 已完成路径扫描：**1954 / 1954**

---

## 18. 当前代码库学习进度

- **整体学习进度：26%**
- **命令系统理解进度：65%**
- **内容级深读进度：约 23 / 1954**

下一步建议优先进入：**工具系统模块**。
因为命令系统之后，最自然的主链就是 `tools.ts` + `Tool.ts` + `tools/**`，这样再去看 `query.ts` 的 tool orchestration 就会顺很多。
