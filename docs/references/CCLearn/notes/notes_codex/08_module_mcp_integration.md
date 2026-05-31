# Claude Code 代码库学习地图 - 模块 7：MCP 集成模块

- 模块名称：MCP 集成（MCP Config / Connection / Tool & Prompt Import / Auth / Policy / Runtime Integration）
- 目标：还原 Claude Code 如何把本地/远程/插件/claude.ai/SDK 的 MCP server 接入到命令系统与工具系统中，并在权限、安全、连接、认证、输出治理层面完成统一整合

---

## 1. 功能概述

MCP（Model Context Protocol）是 Claude Code 最重要的扩展支点之一。

对这个项目来说，MCP 不只是“多了几个外部工具”，而是一整套：
- 外部 server 配置发现
- 多种 transport 建连
- OAuth / Auth / Step-up / Needs-auth 缓存
- 工具 schema 导入
- prompt/skills/resources 导入
- 企业 allowlist/denylist/policy
- 插件 MCP server 合并与去重
- Claude.ai connector 与本地 MCP server 去重
- 与 query/tool/command/UI/runtime 的统一接轨

也就是说，Claude Code 不是“支持 MCP”，而是已经把 MCP 当成：

> **工具系统、命令系统和平台扩展系统的一级公民。**

---

## 2. 解决的问题

### 2.1 MCP server 来源很多，且优先级不同
server 可能来自：
- enterprise managed MCP config
- user config
- project `.mcp.json`
- local config
- plugin MCP servers
- dynamic runtime MCP servers
- claude.ai connectors
- SDK in-process MCP servers

这些来源需要统一合并，又要有优先级和策略边界。

### 2.2 transport 异构
MCP server 可能是：
- stdio
- sse
- http (streamable HTTP)
- ws
- sse-ide / ws-ide
- sdk
- claudeai-proxy

每种 transport 的认证、超时、连接生命周期都不同。

### 2.3 认证问题非常复杂
尤其远程 MCP server 可能涉及：
- OAuth token 过期
- step-up auth
- session ingress token
- claude.ai proxy OAuth retry
- 401 需要转成 needs-auth，而不是普通 failed

### 2.4 MCP 引入的不只是工具，还有 prompts / resources / skills
这意味着 MCP 必须同时接入：
- 工具系统
- 命令系统
- 资源读取系统
- 技能系统

### 2.5 企业策略不能只做 UI 限制
必须支持：
- allowlist / denylist
- command/url/name 级别匹配
- plugin-only 锁定
- project MCP server approval 状态
- disabled/enabled server state

### 2.6 大规模并发连接与重连必须足够稳
一个用户可能有几十个 MCP server。
系统需要：
- 批量连接
- 本地和远程不同并发度
- stale connection 检测
- cache 清理
- session expired 自动恢复
- resources / commands / tools fetch 缓存

---

## 3. 涉及文件（本轮深读）

1. `source/src/services/mcp/config.ts`
2. `source/src/services/mcp/client.ts`
3. `source/src/services/mcp/types.ts`
4. `source/src/services/mcp/utils.ts`

另外已扫描目录：
- `source/src/services/mcp/**`

其中还包括后续值得继续深挖的文件：
- `auth.ts`
- `channelAllowlist.ts`
- `channelPermissions.ts`
- `headersHelper.ts`
- `normalization.ts`
- `officialRegistry.ts`
- `MCPConnectionManager.tsx`
- `useManageMCPConnections.ts`
- `elicitationHandler.ts`
- `claudeai.ts`
- `SdkControlTransport.ts`
- `InProcessTransport.ts`

---

## 4. 模块核心入口文件

### 核心入口文件
- `source/src/services/mcp/config.ts`
- `source/src/services/mcp/client.ts`

### 最值得先读的 3~8 个文件
1. `source/src/services/mcp/types.ts`
2. `source/src/services/mcp/config.ts`
3. `source/src/services/mcp/client.ts`
4. `source/src/services/mcp/utils.ts`
5. `source/src/services/mcp/auth.ts`（下一轮建议补）
6. `source/src/services/mcp/headersHelper.ts`（下一轮建议补）
7. `source/src/services/mcp/elicitationHandler.ts`（下一轮建议补）
8. `source/src/services/mcp/claudeai.ts`（下一轮建议补）

### 容易被忽视但关键的文件
- `source/src/services/mcp/config.ts`
- `source/src/services/mcp/utils.ts`
- `source/src/services/mcp/types.ts`

很多人看 MCP 会先盯 client/connect 逻辑，但真正难点是：
- 配置来源合并
- policy/approval/disabled 状态
- 工具/命令/资源名称与 scope 归属

---

## 5. 整体调用链 / 执行流程

### 5.1 MCP 配置发现链

```text
startup / reconnect / /mcp
  -> getAllMcpConfigs()
      -> getClaudeCodeMcpConfigs(...)
          -> enterprise/user/project/local configs
          -> plugin MCP servers
          -> dynamic servers
          -> policy filtering
          -> dedup plugin servers vs manual servers
      -> fetchClaudeAIMcpConfigsIfEligible()
      -> dedup claude.ai connectors vs manual servers
  -> 得到最终 scoped MCP configs
```

### 5.2 MCP 建连链

```text
getMcpToolsCommandsAndResources(onConnectionAttempt, configs)
  -> 按 local / remote 分组
  -> processBatched(...) with different concurrency
  -> connectToServer(name, config)
      -> choose transport
      -> connect client
      -> fetch tools / prompts / skills / resources
      -> emit onConnectionAttempt
```

### 5.3 MCP 工具/命令接入链

```text
client.ts::fetchToolsForClient(client)
  -> MCP tool metadata -> Tool
  -> tools.ts / query runtime 可见

client.ts::fetchCommandsForClient(client)
  -> MCP prompts -> Command(prompt)
  -> commands.ts / slash command system 可见

feature('MCP_SKILLS')
  -> fetchMcpSkillsForClient(client)
  -> MCP resources -> skill commands
```

### 5.4 MCP 工具执行链

```text
query/toolExecution
  -> MCPTool.call(...)
      -> ensureConnectedClient(client)
      -> callMCPToolWithUrlElicitationRetry(...)
          -> callMCPTool(...)
          -> processMCPResult(...)
              -> transformMCPResult / persist large output / image resize
```

---

## 6. 核心文件详细讲解

---

## 6.1 `source/src/services/mcp/types.ts`

### 文件作用
这是 MCP 子系统的**类型与 schema 中心**。

它定义了：
- 配置 schema
- transport 种类
- scoped config 形态
- server connection union type
- CLI state serialization 结构

### 为什么重要
MCP 这套系统的复杂度，很大程度来自 transport/config/state 变体太多。
要读懂 config.ts 和 client.ts，必须先理解这里的类型系统。

---

### 配置 schema 体系

#### 1) `ConfigScopeSchema`
允许：
- `local`
- `user`
- `project`
- `dynamic`
- `enterprise`
- `claudeai`
- `managed`

##### 含义
MCP 配置不是单一来源，而是带 provenance 的。
这个 provenance 后面会影响：
- 优先级
- 展示文案
- 是否允许编辑
- 策略过滤

---

#### 2) `TransportSchema`
允许：
- `stdio`
- `sse`
- `sse-ide`
- `http`
- `ws`
- `sdk`

##### 注意
运行时里还存在 `claudeai-proxy`，它通过单独 schema 定义，不在基础 TransportSchema 里。

这表明 claude.ai proxy 是“特殊 transport 变体”，而不是标准 MCP transport。

---

#### 3) 各类 `Mcp*ServerConfigSchema`

##### `McpStdioServerConfigSchema`
- `command`
- `args`
- `env`

##### `McpSSEServerConfigSchema`
- `url`
- `headers`
- `headersHelper`
- `oauth`

##### `McpHTTPServerConfigSchema`
- `url`
- `headers`
- `headersHelper`
- `oauth`

##### `McpWebSocketServerConfigSchema`
- `url`
- `headers`
- `headersHelper`

##### `McpSdkServerConfigSchema`
- `type: sdk`
- `name`

##### `McpClaudeAIProxyServerConfigSchema`
- `type: claudeai-proxy`
- `url`
- `id`

### 设计亮点
- 以 zod schema 为中心，配置读取后第一时间 validate
- 各 transport 形状差异被建模得很明确
- OAuth 配置内聚在远程 transport schema 中

---

### `ScopedMcpServerConfig`

#### 定义
`McpServerConfig & { scope, pluginSource? }`

#### 为什么关键
它让“配置内容”和“配置来源”合并进一个对象。
后面：
- policy filtering
- dedup
- /mcp UI 显示
- pluginSource 通道 allowlist

都依赖这个附加元数据。

---

### `MCPServerConnection` 联合类型
允许：
- `ConnectedMCPServer`
- `FailedMCPServer`
- `NeedsAuthMCPServer`
- `PendingMCPServer`
- `DisabledMCPServer`

#### 设计价值
MCP server 状态不是二元 connected/failed，而是更丰富的状态机。
这对：
- /mcp UI
- reconnect 逻辑
- needs-auth 提示
- lazy retry

都非常重要。

---

## 6.2 `source/src/services/mcp/config.ts`

### 文件作用
这是 MCP 的**配置发现、合并、策略过滤、增删改写中心**。

它负责：
- 读取 `.mcp.json` / user/local/enterprise config
- 解析和 validate config
- plugin MCP server 导入
- claude.ai connector 合并
- policy allow/deny 过滤
- duplicate server suppression
- add/remove/toggle MCP server

### 为什么它是 MCP 配置层核心
MCP 的接入逻辑并不主要在“client 如何连”，而在“哪些 server 最终被允许存在”。
这个问题的答案几乎都在 `config.ts`。

---

### 关键函数 1：`getMcpServerSignature(config)`

#### 作用
把 server config 归一成 dedup signature。

#### 规则
- stdio server -> `stdio:<json(command+args)>`
- remote server -> `url:<normalizedURL>`
- sdk -> `null`

#### 为什么重要
server key/name 可能不同，但底层其实是同一个 server。
必须用“内容签名” dedup，而不能只比名字。

---

### 关键函数 2：`dedupPluginMcpServers(...)`

#### 作用
去掉与 manual-configured server 重复的 plugin MCP server；插件之间也 first-loaded wins。

#### 设计逻辑
- manual server 优先于 plugin server
- plugin server key 带 namespace，但仍可能底层指向同一进程/URL
- 所以需要内容级 signature dedup

#### 为什么关键
否则会出现：
- 同一 server 被连接两次
- 重复工具/命令/资源
- token/context 也跟着膨胀

---

### 关键函数 3：`dedupClaudeAiMcpServers(...)`

#### 作用
抑制与手动配置 server 重复的 claude.ai connectors。

#### 典型场景
- 用户本地手动配了 Slack MCP
- claude.ai connector 也带 Slack
- 若不 dedup，会同时出现：
  - `mcp__slack__*`
  - `mcp__claude_ai_Slack__*`

不仅重复，而且每轮 prompt 还会额外浪费数百字符。

---

### 关键函数 4：`isMcpServerDenied(...)` / `isMcpServerAllowedByPolicy(...)`

这是企业策略最关键的判断层。

#### 支持的匹配方式
- `serverName`
- `serverCommand`（stdio）
- `serverUrl`（remote）

#### 关键设计点
##### 点 1：denylist 绝对优先
无论 allowlist 是否命中，deny 先胜。

##### 点 2：allowlist 可以按 server type 变语义
- 若 allowlist 中存在任何 command entries，则 stdio server 必须匹配 command 规则
- 若存在任何 URL entries，则 remote server 必须匹配 URL 规则
- 否则再退回 name-based allow

这不是简单名单，而是按 transport 类型的“强 allow policy”。

##### 点 3：allowManagedMcpServersOnly
若 policySettings 指定：
- allowlist 只读 managed settings
- 但 denylist 仍可从用户设置合并

这又是一个很成熟的“组织控制 allow，用户仍可 self-deny”的策略设计。

---

### 关键函数 5：`getProjectMcpConfigsFromCwd()` / `getMcpConfigsByScope(scope)`

#### `getProjectMcpConfigsFromCwd()`
- 只读当前目录 `.mcp.json`
- 用于 add/remove 精确修改当前文件

#### `getMcpConfigsByScope('project')`
- 从 CWD 向上遍历父目录
- root -> cwd 顺序 merge
- closer file 覆盖 parent config

##### 设计意义
项目级 `.mcp.json` 不是单点文件，而是支持目录树继承覆盖。

这点非常重要。

---

### 关键函数 6：`getClaudeCodeMcpConfigs(...)`

这是 Claude Code 自己 MCP config 的总入口。

#### 执行步骤
```ts
1. enterprise config 若存在，则独占所有 MCP servers
2. 若 policy 锁到 plugin-only：禁 user/project/local
3. 读取 user/project/local configs
4. loadAllPluginsCacheOnly()
5. getPluginMcpServers()
6. project servers 只保留 approved ones
7. dedup plugin servers vs enabled manual servers
8. merge precedence: plugin < user < project < local
9. policy filtering
10. return servers + mcpErrors
```

### 最关键设计点

#### 点 1：enterprise config 是排它控制
组织可完全接管 MCP surface。

#### 点 2：plugin-only lock 不等于“只有 enterprise”
这里只阻断 user/project/local，但保留 plugin servers。

#### 点 3：project servers 还要看 approval status
`.mcp.json` 里的 server 不是读到就生效，而要看：
- approved / rejected / pending

这与用户信任/审批体系对齐。

---

### 关键函数 7：`getAllMcpConfigs()`

#### 作用
最终把：
- Claude Code MCP configs
- claude.ai connectors

合并起来。

#### 关键优化
- 先启动 `fetchClaudeAIMcpConfigsIfEligible()` promise
- 再去跑 `getClaudeCodeMcpConfigs()`
- 两边 overlap，不串行等待

这是很标准的 latency overlap 设计。

---

### 配置写入相关函数

#### `addMcpConfig(name, config, scope)`
- validate config
- reserved name 检查
- enterprise exclusive 检查
- allow/deny policy 检查
- 再写入 `.mcp.json` / user / local config

#### `writeMcpjsonFile(config)`
- preserve existing mode
- temp file -> datasync -> rename
- best-effort cleanup temp

##### 设计点
这是非常标准的安全原子写文件模式。

#### `removeMcpConfig(name, scope)`
- scope-aware 删除
- project scope 时 strip 掉 scope metadata 再写回

#### `setMcpServerEnabled(name, enabled)`
- built-in default-disabled server 走 `enabledMcpServers`
- 其他走 `disabledMcpServers`

##### 为什么分两套
因为 built-in default-disabled server 语义是 opt-in，普通 server 语义是 opt-out。

---

## 6.3 `source/src/services/mcp/client.ts`

### 文件作用
这是 MCP 的**连接运行时、工具/命令/资源导入器、工具调用桥接器**。

如果 `config.ts` 决定“哪些 server 存在”，那 `client.ts` 决定：
- 怎么连上它们
- 怎么拿到 tools/prompts/resources
- 怎么把 MCP tool 包装成 Claude Code Tool
- 怎么把 MCP prompt 包装成 Command
- 怎么做 reconnect/cache/auth handling

这基本就是 MCP 的运行时中枢。

---

### 核心函数 1：`connectToServer(name, serverRef, serverStats?)`

这是整个文件最重要的函数之一。

#### 作用
根据 server config 建立 MCP 连接，返回 `MCPServerConnection`。

#### 主要 transport 分支

##### 1) `sse`
- `ClaudeAuthProvider`
- `getMcpServerHeaders(...)`
- `wrapFetchWithTimeout(wrapFetchWithStepUpDetection(...))`
- EventSource fetch 不加 timeout（长连接）

##### 2) `http`
- StreamableHTTPClientTransport
- 认证 provider
- proxy options
- fresh timeout per request
- step-up detection

##### 3) `ws`
- WebSocket headers/proxy/TLS

##### 4) `sse-ide` / `ws-ide`
- IDE 专用 transport
- 不同认证/统计语义

##### 5) `claudeai-proxy`
- 用 `createClaudeAiProxyFetch(...)`
- 自动附带 claude.ai OAuth bearer token
- 401 时尝试 handleOAuth401Error 后 retry 一次

##### 6) `stdio`
- `StdioClientTransport`
- 支持 shell prefix
- 支持 env merge
- stderr 单独 pipe 以避免污染 UI

##### 7) in-process 特例
- Claude in Chrome MCP server
- Computer Use MCP server

这两个都不会起子进程，而是在本进程里通过 `InProcessTransport` 跑。

### 设计亮点

#### 点 1：transport 与 auth 策略是耦合设计的
不同 transport 不是只有连接方式不同，认证与 timeout 行为也一起变。

#### 点 2：EventSource 长连接显式跳过 timeout wrapper
否则 60s timeout 会把本该长期存活的 SSE stream 干掉。

#### 点 3：HTTP/claudeai proxy 都会对 step-up / 401 做专门处理
这说明作者已经专门针对实际 OAuth/step-up 故障设计过补丁。

---

### 连接后的运行时增强

#### client request handlers
- `ListRootsRequestSchema` -> 返回当前 originalCwd root
- `ElicitRequestSchema` -> 初始默认 cancel，后续由 registerElicitationHandler 覆盖

#### close/error hooks
为 client 装配：
- enhanced `onerror`
- enhanced `onclose`
- stale connection / session expired 检测
- repeated terminal errors -> close transport -> clear cache

### 非常关键的设计点

#### 点 1：HTTP transport 的 session expired 检测
如果 server 返回：
- HTTP 404 + JSON-RPC code -32001
则认为 MCP session 已失效，要清 cache 并重连。

#### 点 2：`McpError -32000 Connection closed` 也可能意味着 session expired
因为 transport close 之后，挂起的 tool call 会以 connection closed 形式报出来。

这非常实战。

#### 点 3：缓存清理不仅清连接，还清 fetch cache
否则重连后 tools/resources/commands 还可能拿旧缓存。

---

### 核心函数 2：`fetchToolsForClient(client)`

#### 作用
把 MCP tools 转成 Claude Code 内部 `Tool[]`。

#### 关键步骤
```ts
1. client.request('tools/list')
2. recursivelySanitizeUnicode(result.tools)
3. 对每个 tool 构造 MCPTool wrapper
   - name: mcp__server__tool
   - mcpInfo: {serverName, toolName}
   - isMcp = true
   - description/prompt 截断到 MAX_MCP_DESCRIPTION_LENGTH
   - readOnly/concurrencySafe/destructive/openWorld 来自 annotations
   - checkPermissions -> passthrough + addRules suggestion
   - call(...) -> ensureConnectedClient -> callMCPToolWithUrlElicitationRetry
4. filter out excluded IDE tools
```

### 最关键的设计点

#### 点 1：MCP tool 被包装成标准 Tool
所以后续：
- tools.ts
- query.ts
- toolExecution.ts

完全可以把它当本地工具一样处理。

#### 点 2：MCP tool 的权限提示用 passthrough
权限最终仍由 Claude Code 的统一 permission 系统决定。

#### 点 3：MCP tool 也会接入 collapse/classifier/readOnly semantics
不是“远程黑盒工具”，而是尽量映射到本地工具语义层。

---

### 核心函数 3：`fetchCommandsForClient(client)`

#### 作用
把 MCP prompts 转成 Claude Code `Command[]`。

#### 命名规则
- `mcp__<server>__<prompt>`

#### `getPromptForCommand(args)`
- `connectedClient.client.getPrompt(...)`
- 再把 prompt messages 通过 `transformResultContent(...)` 转成内部 content blocks

### 设计价值
MCP prompt 被直接视作 slash/prompt command 的一个来源。

这正好与前面 `commands.ts` 模块里的 `source: 'mcp'` 命令体系闭环。

---

### 核心函数 4：`callMCPToolWithUrlElicitationRetry(...)`

#### 作用
处理 MCP 工具调用时，server 返回 `UrlElicitationRequiredError (-32042)` 的情况。

#### 逻辑
```ts
1. 调 callMCPTool()
2. 若报 -32042:
   - 提取 elicitations
   - 先跑 elicitation hooks
   - hook 未处理则：
     - print/SDK mode -> handleElicitation callback
     - REPL mode -> queue ElicitationDialog
   - 再跑 ElicitationResult hooks
   - accept 则 retry tool call
   - decline/cancel 则返回 explanatory content
3. 最多 retry 3 次
```

### 为什么重要
这说明 Claude Code 不只是“调用 MCP tool”，还完整支持：
- 需要用户打开 URL 认证/确认
- 认证完成后继续 retry tool call

这让 MCP server 的复杂交互式 auth/consent 流真正可用。

---

### 核心函数 5：`callMCPTool(...)`

#### 作用
真正执行 MCP tool call，并转成内部 `MCPToolResult`。

#### 关键逻辑
- `client.callTool(...)`
- 自己再用 Promise.race 加 timeout（防 SDK 自身 timeout 无效）
- 支持 progress callback 映射到 `mcp_progress`
- `isError` -> 抛 `McpToolCallError`
- `processMCPResult(result, tool, name)`
- 401 -> 抛 `McpAuthError`
- session expired -> clear cache 并抛 `McpSessionExpiredError`

### 关键设计点

#### 点 1：即便 SDK 已有 timeout，仍自己包一层 race timeout
因为 SSE stream 断掉等情况下 SDK timeout 可能不可靠。

#### 点 2：错误包装成 telemetry-safe 错误
避免只剩 `Error` / `McpError` 这种无上下文错误类别。

#### 点 3：session expired 错误会触发 clearServerCache
确保下一次 tool call 真正重建 session，而不是继续用坏连接。

---

### 核心函数 6：`processMCPResult(...)`

#### 作用
把 MCP result 转成 Claude Code 内部可用内容，并处理超大输出。

#### 逻辑
1. `transformMCPResult(...)`
2. IDE 工具直接返回，不走大输出逻辑
3. 若输出不大，直接返回
4. 若大输出且 feature 允许：
   - `persistToolResult(contentStr, persistId)`
   - 返回 “输出已保存到文件，如何读取” 的文本指引
5. 若包含图片，则不用 persist-json，改走截断策略

### 设计价值
MCP 工具结果与本地 Bash/File 工具一样，都接入了“大输出治理”体系。

---

### 核心函数 7：`getMcpToolsCommandsAndResources(...)`

#### 作用
批量连接所有 MCP servers，并逐个把：
- client
- tools
- commands
- resources
回调给调用方。

#### 关键流程
```ts
1. disabled servers 直接回调 disabled client
2. 计算 transport counts 做 telemetry
3. partition: localServers / remoteServers
4. local 用较低 concurrency, remote 用较高 concurrency
5. processServer(entry)
   -> connectToServer
   -> fetchToolsForClient
   -> fetchCommandsForClient
   -> fetchMcpSkillsForClient (if enabled)
   -> fetchResourcesForClient
   -> onConnectionAttempt(result)
```

### 设计亮点
#### 点 1：本地和远程分组不同并发度
- stdio/sdk 启进程成本高
- remote server 只是网络连接，可以更高并发

#### 点 2：需要 auth 的 server 不报 failed，而是 `needs-auth`
并自动暴露 `createMcpAuthTool(name, config)`

这使认证修复本身也被建模成工具能力的一部分。

---

### 核心函数 8：`reconnectMcpServerImpl(...)`

#### 作用
执行一次 server reconnect。

#### 关键步骤
- `clearKeychainCache()`
- `clearServerCache(name, config)`
- `connectToServer(...)`
- 再 fetch tools/commands/resources

### 为什么先 clearKeychainCache
因为另一个进程（例如 VS Code extension host）可能刚更新了 token。
如果子进程继续用旧 keychain cache，就永远感知不到 auth 变化。

这很细，但很关键。

---

## 6.4 `source/src/services/mcp/utils.ts`

### 文件作用
这是 MCP 的**辅助策略与过滤工具层**。

它负责：
- tool/command/resource 按 server 过滤
- stale client 检测与剔除
- scope 说明/解析
- project MCP server approval 状态
- agent frontmatter 里的 MCP server 提取
- logging safe base URL

### 为什么重要
它把：
- /mcp UI 展示
- reconnect / stale cleanup
- project approval 语义
- command/tool 归属判断

这些跨切面逻辑从主 client/config 文件里抽出来，降低了耦合。

---

### 关键函数 1：`commandBelongsToServer(...)`

#### 重要细节
MCP prompt 与 MCP skill 命名不同：
- prompt: `mcp__<server>__<prompt>`
- skill: `<server>:<skill>`

所以判断 command 是否属于某 server，不能只看一种前缀。

这是一个非常容易漏掉的细节。

---

### 关键函数 2：`excludeStalePluginClients(...)`

#### 作用
在 `/reload-plugins` 时，剔除 stale MCP clients。

#### stale 条件
- `scope === dynamic` 且 name 已不在 configs
- 或 config hash changed（任何 scope）

#### 为什么要这样设计
- dynamic missing config 说明 plugin disabled/removed
- 但 user-configured server 暂时不在 in-memory config，不应该误删，除非 config 真变了

这是个非常精细的 stale 策略。

---

### 关键函数 3：`getProjectMcpServerStatus(serverName)`

#### 返回
- `approved`
- `rejected`
- `pending`

#### 决策逻辑
1. 若在 `disabledMcpjsonServers` -> rejected
2. 若在 `enabledMcpjsonServers` 或 `enableAllProjectMcpServers` -> approved
3. 若 dangerous skip permission prompt 且 projectSettings enabled -> approved
4. 若 non-interactive session 且 projectSettings enabled -> approved
5. 否则 pending

### 非常关键的安全点
源码注释明确说明：
- **不能**用 project settings 来接受 bypass dialog
- 因为 repo-level settings 不应能替用户批准危险权限

这与前面 memdir 的“repo config 不可信边界”是一致的。

---

### 关键函数 4：`getMcpServerScopeFromToolName(toolName)`

#### 作用
从工具名反查 server scope。

#### 用途
便于：
- permission / UI / telemetry 按来源展示
- `claudeai` fallback 命名识别

---

## 7. 数据流 / 状态流

### 7.1 MCP server 配置状态流

```text
enterprise/user/project/local/plugin/dynamic/claudeai
  -> parse + validate
  -> add scope
  -> dedup by signature
  -> policy filter
  -> disabled/approved gating
  -> final ScopedMcpServerConfig map
```

### 7.2 MCP connection 状态流

```text
ScopedMcpServerConfig
  -> connectToServer()
  -> pending -> connected / failed / needs-auth / disabled
  -> cache by getServerCacheKey(name, config)
  -> onclose/onerror clear cache
```

### 7.3 MCP tool/command/resource 导入流

```text
connected client
  -> tools/list -> Tool[]
  -> prompts/list -> Command[]
  -> resources/list -> ServerResource[]
  -> skill:// resources -> skill commands
```

### 7.4 MCP tool 执行状态流

```text
MCP Tool wrapper
  -> ensureConnectedClient
  -> callMCPToolWithUrlElicitationRetry
  -> callMCPTool
  -> transform/processMCPResult
  -> toolExecution.ts 常规 tool result 流
```

---

## 8. 配置项 / 环境变量 / 依赖注入方式

### 8.1 MCP config / policy 相关

| 项目 | 来源 | 影响 |
|---|---|---|
| `.mcp.json` | project config | 项目级 server 声明 |
| global/local config | user settings | user/local MCP server |
| enterprise managed-mcp.json | managed path | enterprise exclusive MCP control |
| `allowManagedMcpServersOnly` | policy settings | allowlist 只读 managed settings |
| `allowedMcpServers` / `deniedMcpServers` | settings | command/url/name 级 allow/deny |
| `disabledMcpServers` / `enabledMcpServers` | currentProjectConfig | server 启停 |
| plugin-only policy | settings/policy | 锁掉 user/project/local，仅保留 plugin/enterprise |

### 8.2 连接 / 认证相关

| 项目 | 来源 | 影响 |
|---|---|---|
| `MCP_TIMEOUT` | env | connect timeout |
| `MCP_TOOL_TIMEOUT` | env | tool call timeout |
| `MCP_SERVER_CONNECTION_BATCH_SIZE` | env | local server 并发 |
| `MCP_REMOTE_SERVER_CONNECTION_BATCH_SIZE` | env | remote server 并发 |
| `CLAUDE_AGENT_SDK_MCP_NO_PREFIX` | env | SDK MCP tool 命名策略 |
| `ENABLE_MCP_LARGE_OUTPUT_FILES` | env | MCP 大结果持久化 |
| `CLAUDE_CODE_SHELL_PREFIX` | env | stdio server command wrapping |
| `CLAUDE_CODE_REMOTE` / ingress token | runtime env | remote MCP auth routing |

### 8.3 依赖注入方式

#### 方式 1：`ScopedMcpServerConfig`
配置内容 + 来源元数据。

#### 方式 2：transport-specific auth providers / fetch wrappers
例如：
- `ClaudeAuthProvider`
- `createClaudeAiProxyFetch`
- timeout/step-up wrappers

#### 方式 3：Tool/Command wrapper injection
MCP tool/prompt 被包装成内部协议对象。

#### 方式 4：AppState / onConnectionAttempt callback
MCPConnectionManager / UI 层逐步接收连接结果。

---

## 9. 错误处理 / 边界条件

### config.ts
- invalid config schema -> structured validation errors
- missing file 并不算 fatal（按 scope 语义处理）
- plugin MCP errors 单独汇总为 `mcpErrors`
- enterprise config 存在时独占控制
- add/remove/toggle 都做 reserved name 和 policy 检查

### client.ts
- connect timeout 自己 race 一层
- Unauthorized -> `needs-auth`
- session expired -> clear cache + `McpSessionExpiredError`
- stale transport -> repeated terminal errors then close
- tools/resources/commands fetch 失败 fail-soft 为 []
- reconnect 前清 keychain cache 防止 stale token

### utils.ts
- command prompt 与 skill 命名格式不同，过滤需兼容两者
- stale plugin clients 只按动态消失或 config-hash-change 判定
- project approval 在 dangerous/non-interactive 下有特例 auto-approve，但不会让 repo-level bypass 代替用户批准

---

## 10. 安全性 / 性能 / 扩展性分析

### 10.1 安全性

#### 做得好的地方
1. **MCP server allow/deny 支持 name/command/url 三层匹配**
2. **enterprise config 可独占控制 MCP surface**
3. **project MCP server 需要 approval status，不是读到就生效**
4. **needs-auth 与 failed 分离，避免误把 auth 问题当服务故障**
5. **URL logging 会 strip query，避免 token 泄露**
6. **claude.ai proxy 401 会先尝试 token refresh，避免因 stale memo cache 大面积误 needs-auth**

#### 风险点
- 外部 MCP server 天生是扩展边界，server 质量和协议遵守程度差异很大
- transport/认证分支很多，组合态较多，长期维护成本高

### 10.2 性能

#### 优化手段
1. plugin 与 claude.ai config fetch overlap
2. local/remote servers 分组并发
3. connectToServer memoize
4. fetchTools/resources/commands LRU cache
5. MCP tool description/instructions 截断
6. 大 MCP output 持久化到文件而不是塞满上下文

#### 成本点
- 大量 MCP servers 时 startup 仍会有明显成本
- reconnect path 需要同时清 connection cache + fetch caches，状态复杂

### 10.3 扩展性
MCP 模块扩展性很强，原因是：
- transport schema 明确
- config merge/policy 单独成层
- runtime connect/fetch/call 单独成层
- Tool/Command/Skill/Resource 分层导入

新增 transport 或新种类 connector，基本都有明确接入点。

---

## 11. 与其他模块的关系

### 上游
- 启动模块 / setup / main.tsx
- settings / policy / plugin loader
- query/tool runtime

### 下游
- tools.ts 工具池
- commands.ts 命令池
- resources / ReadMcpResourceTool / ListMcpResourcesTool
- MCP auth tool / /mcp UI / reconnect manager

### 关键耦合点
- `tools.ts`：MCP tools merge 到最终 tool pool
- `commands.ts`：MCP prompts/skills merge 到命令池
- `toolExecution.ts`：MCP tool 最终作为标准 Tool 执行
- `query.ts`：工具/命令/attachment 下一轮继续使用

---

## 12. 学习这个模块时建议的阅读顺序

### 推荐顺序
1. `source/src/services/mcp/types.ts`
2. `source/src/services/mcp/config.ts`
3. `source/src/services/mcp/utils.ts`
4. `source/src/services/mcp/client.ts`
5. 然后继续：
   - `source/src/services/mcp/auth.ts`
   - `source/src/services/mcp/headersHelper.ts`
   - `source/src/services/mcp/elicitationHandler.ts`
   - `source/src/services/mcp/claudeai.ts`
   - `source/src/services/mcp/MCPConnectionManager.tsx`

### 为什么这样排
- 先理解类型与配置来源
- 再理解 policy/merge/approval
- 最后再进连接与工具导入运行时

---

## 13. 容易忽略但关键的隐藏细节

### 细节 1：plugin/claude.ai/manual MCP server 去重靠“签名”，不是名字
这是内容级 dedup，而不是 key dedup。

### 细节 2：project `.mcp.json` 支持从 root 到 cwd 的层级合并
不是只看当前目录。

### 细节 3：MCP prompts 和 MCP skills 的命名规则不同
一个是 `mcp__server__prompt`，一个是 `server:skill`。

### 细节 4：HTTP/SSE transport 的 needs-auth 判断不是简单失败，而会专门转 `needs-auth` 状态并暴露 auth tool
这让认证修复成为可操作流程，而不是死错误。

### 细节 5：session expired 不是只看 404，还要兼容 SDK 关闭后转出的 `Connection closed`
非常实战。

### 细节 6：`reconnectMcpServerImpl` 先清 keychain cache，再清 server cache
否则会被另一个进程刚更新的 token“卡住看不见”。

---

## 14. 逐文件精讲（本轮覆盖文件）

### 14.1 `source/src/services/mcp/config.ts`
- **文件作用**：MCP 配置发现、合并、策略过滤与配置写入中心
- **导出的内容**：config parse/get/add/remove/toggle/dedup/policy helpers
- **主要逻辑**：enterprise/user/project/local/plugin/claudeai/dynamic 多来源 merge，policy allow/deny，project approval，duplicate suppression
- **被谁使用**：startup、/mcp、MCP connection manager、plugin system、main/query 初始化路径
- **依赖了谁**：settings/config/plugin loader/claudeai/env expansion/types/utils
- **是否值得重点精读**：最高优先级之一

### 14.2 `source/src/services/mcp/client.ts`
- **文件作用**：MCP 连接运行时与工具/命令/资源导入器
- **导出的内容**：connect/reconnect/fetch tools/fetch commands/call tool/setup SDK MCP clients 等
- **主要逻辑**：多 transport 建连、auth handling、needs-auth cache、tool wrapper、prompt wrapper、large output persistence、URL elicitation retry、session expired recovery
- **被谁使用**：MCP connection manager、tools/commands 集成、query/tool runtime
- **依赖了谁**：MCP SDK、auth、headers、tools/commands/resource wrappers、tool result storage、proxy/TLS utils
- **是否值得重点精读**：最高优先级之一

### 14.3 `source/src/services/mcp/types.ts`
- **文件作用**：MCP 类型与 schema 中心
- **导出的内容**：config schemas、scoped config、server connection union、resource/CLI state types
- **主要逻辑**：统一 transport/config/state 协议
- **被谁使用**：config.ts、client.ts、UI、/mcp、plugin/MCP 集成全链路
- **依赖了谁**：zod、MCP SDK 类型、lazySchema
- **是否值得重点精读**：极高

### 14.4 `source/src/services/mcp/utils.ts`
- **文件作用**：MCP 过滤、stale cleanup、scope/approval 与 agent MCP extraction 辅助层
- **导出的内容**：tool/command/resource 过滤、stale client 剔除、project approval、scope helpers、safe base URL helpers
- **主要逻辑**：按 server 过滤资源、管理 stale clients、解析 tool->scope、计算 project MCP status
- **被谁使用**：/mcp UI、reload-plugins、permission/UI 展示、config/runtime 辅助逻辑
- **依赖了谁**：settings、commands、tools、agent definitions、config helpers
- **是否值得重点精读**：高

---

## 15. 本轮已完成分析的文件列表（相对路径）

- `source/src/services/mcp/config.ts`
- `source/src/services/mcp/client.ts`
- `source/src/services/mcp/types.ts`
- `source/src/services/mcp/utils.ts`
- 以及 `source/src/services/mcp/**` 全目录清单扫描

---

## 16. 本轮未完成但下一轮建议继续分析的模块

1. 模型 client/provider/config/认证模块
2. 插件 / skills 生态细分模块
3. `source/src/commands/**` 逐文件精讲
4. `source/src/tools/**` 其余工具族逐文件精讲
5. MCP 深挖补充：`auth.ts`, `headersHelper.ts`, `elicitationHandler.ts`, `claudeai.ts`, `MCPConnectionManager.tsx`
6. 文件总索引表与覆盖审计推进

---

## 17. 当前累计已覆盖文件数 / 总文件数

- 已完成深读与模块级分析：**54 / 1954**
- 已完成路径扫描：**1954 / 1954**

---

## 18. 当前代码库学习进度

- **整体学习进度：71%**
- **MCP 集成理解进度：72%**
- **内容级深读进度：约 54 / 1954**

下一步建议：进入 **模型 client/provider/config/认证模块**，这样就能把：
- 启动
- query
- compact
- retry
- memory
- MCP

这些主链外围，全部和“模型提供方/认证/配置注入”闭环起来。
