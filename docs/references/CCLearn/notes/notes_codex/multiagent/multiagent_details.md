# 多 Agent 体系补充细节：RemoteAgentTask 的意义 & 三种 Backend 的设计原理

> 本文补充解答两个问题：
> 1. 既然已经有 LocalAgentTask，为什么还要 **RemoteAgentTask（云端长时会话）**？
> 2. Swarm 的三种后端（InProcess / Tmux / Pane）为什么要并存？尤其是，**InProcessBackend 在同一个 Node event loop 里跑多个 query loop，为什么状态不会互相污染**？
>
> 本文中的所有结论都有源码证据，位置在 `E:\Au_notes\claude_code\source\src`。

---

## Part 1 · RemoteAgentTask 的意义：为什么要「把 agent 搬到云上」

### 1.1 先明确：LocalAgentTask 和 RemoteAgentTask 不是「两种等价方案」

很多人会把它俩理解成「本地后台 / 云端后台」这种纯位置差异。实际上它俩解决的是**不同类型的问题**。看源码的这个枚举就很清楚：

```ts
// source/src/tasks/RemoteAgentTask/RemoteAgentTask.tsx:60
const REMOTE_TASK_TYPES = [
  'remote-agent',      // 通用远程 agent
  'ultraplan',         // 深度规划（多轮研究 + 澄清）
  'ultrareview',       // 深度代码审查（多 agent 交叉验证 bug）
  'autofix-pr',        // 自动修复 PR 的 CI 失败
  'background-pr'      // 后台跑通整个 PR 的实现
] as const;
```

这 5 种都是 Local 版本**根本做不了的 workflow**。Local 只能做「你本地能算的事」，Remote 是一整套**托管产品能力**。下面逐个维度展开。

### 1.2 六个「Local 做不了 / 不该做」的理由

#### 理由 ① 生命周期脱离你的本地进程

Local task 的生命周期绑死在当前 Node 进程：

- 你按 Ctrl+C、关终端、关电脑、笔记本休眠 → task 就没了。
- session crash（OOM、未捕获异常）→ task 也没了。
- 重启电脑 → 从 sidechain.jsonl 能恢复状态，但 task 本身**没在跑**。

Remote task 跑在 Anthropic 的服务器上，生命周期独立：

```ts
// RemoteAgentTask.tsx:41
pollStartedAt: number;   // 当前本地 poller 开始观察的时间
                         // 注意是"观察"，不是"启动"，因为 task 早就在云端跑了
```

代码里的这个字段是个关键证据。它刻意区分「task 被创建的时间」和「我（本地）开始轮询它的时间」。因为你完全可以：

1. 昨天 10 点在家启动一个 `ultrareview`
2. 今天 9 点打开 Claude Code，它连上云，看到这个 task 已经跑了 23 小时
3. 继续拉最新进度

L38–40 的注释原文：`"a restore doesn't immediately time out a task spawned >30min ago"` —— 这是作者明确考虑了**跨会话恢复**的证据。

#### 理由 ② 计算密度不同

`ultraplan` 和 `ultrareview` 这类任务有什么特点？看它们的进度字段：

```ts
// RemoteAgentTask.tsx:45-50
reviewProgress?: {
  stage?: 'finding' | 'verifying' | 'synthesizing';
  bugsFound: number;
  bugsVerified: number;
  bugsRefuted: number;
};
```

**`verifying` 和 `refuted` 这两个词很关键**：一个 bug 被 finder agent 报出来后，会有另一个 verifier agent 去独立验证，甚至可能把它推翻（refuted）。这是一个 **多 agent 交叉验证** 的 pipeline，内部可能同时跑几十个子 agent、消耗几百万 tokens。

如果放在本地：

- 你的笔记本要扛起几十个 HTTPS 长连接 + 几十份 context 窗口。
- 你的网络要承受持续的 streaming 流量。
- 你的 token 配额按你的个人 key 算（rate limit 容易打爆）。

放云端：

- 用服务端的高带宽、高并发。
- 用托管的 **rate limit 分摊** 和 **model 专用通道**。
- 你本地只是轮询一个 session endpoint，消耗极低。

#### 理由 ③ 和外部系统的集成需要「服务端身份」

看这两个类型：

```ts
'autofix-pr' | 'background-pr'
```

它们要干的事：

- 监听 GitHub webhooks（你的笔记本不在 webhook 可达范围）
- 推 commit、开 PR、关 PR、comment PR（需要 GitHub App token）
- 订阅 CI 失败事件

这些都需要一个 **always-on 的服务端身份**。让每个用户自己的笔记本都去干这事不现实 —— 不可能要求用户保持电脑常开、不休眠、公网可达、并在本地保管 GitHub App 的私钥。

代码里 `remoteTaskMetadata` 的结构证实了这点：

```ts
// RemoteAgentTask.tsx:65-69
export type AutofixPrRemoteTaskMetadata = {
  owner: string;       // GitHub 组织
  repo: string;        // 仓库名
  prNumber: number;    // PR 号
};
```

#### 理由 ④ 跨设备接力

你的使用场景很可能是：

- 早上通勤时在手机 claude.ai 上启动一个 "review PR #123" 的任务。
- 到公司后打开笔记本，`claude` 一跑，本地就看到这个 task 的进度。
- 午休时用 iPad 查看 bug 列表。

Local task **死死绑在一台机器**。Remote task 则是 session 级别 —— 任意有权限的设备都能 attach 到同一个 `sessionId` 上。这就是 `RemoteAgentTaskState.sessionId` 作为主键的原因。

#### 理由 ⑤ Long-running 语义

```ts
// RemoteAgentTask.tsx:32-35
/**
 * Long-running agent that will not be marked as complete after the first `result`.
 */
isLongRunning?: boolean;
```

这是一个 Local 没有的概念。Long-running agent 会 **一直收反馈、一直迭代**，直到你显式关闭它。例子：

- `background-pr` 类型：跑一个需求 → 收到 CI 反馈 → 自己改 → 再提交 → 再等 CI … 直到 PR 绿。

这种「无限周期」的活儿，本地根本撑不住（睡眠/重启都会中断）；只能跑在云端 24×7 基础设施上。

#### 理由 ⑥ 特殊模型 / 特殊 workflow 只在云端启用

`ultraplan` / `ultrareview` 这类是 **产品级 workflow**，不是单纯「换个更贵的模型」。它们在云端可能用：

- 专用的多 agent 编排模板（Anthropic 内部维护）
- 专用的 system prompt（比本地版本精细很多）
- 专用的 tool set（访问内部代码索引、安全扫描器等）
- 专用的后处理（生成结构化报告）

这些都是服务端资产，本地 runAgent 无法复刻。

### 1.3 通信协议层面：Local vs Remote 的分野

| 维度 | LocalAgentTask | RemoteAgentTask |
|---|---|---|
| 存放介质 | 本机 `~/.claude/sessions/` | 云端 session 存储 |
| 发送命令 | `AbortController` / `SendMessage`（内存+邮箱） | HTTPS POST `/v1/sessions/{id}/...` |
| 读进度 | 读 sidechain.jsonl | `pollRemoteSessionEvents()` 走 HTTPS |
| 解析完成信号 | task.terminalState 标记 | 从 assistant 消息中 extractTag(`<task-notification>`) |
| 关闭时会发生什么 | 进程退出 = task 死 | session 继续跑，只是你断开了观察 |
| 恢复 | 从 AppState + sidechain 重构 | 从云端拉 log 重构 |

`RemoteAgentTask.tsx:19` 的 `pollRemoteSessionEvents` 是这个协议的核心。它本质是一个 **event sourcing**：云端维护一个 ordered event stream，本地只负责从上次的 cursor 位置增量拉取：

```ts
import { archiveRemoteSession, pollRemoteSessionEvents } from '../../utils/teleport.js';
```

注意引入的路径叫 `teleport.js` —— 「传送」。这个命名暗示了它的本质：**把一个异地的 session 状态「传送」到你本地**。

### 1.4 一句话理解

> **LocalAgentTask** 是「我让同一个 Claude 在本地后台多跑一会儿」。
>
> **RemoteAgentTask** 是「我订购 Anthropic 提供的托管 workflow 服务，本地只是一个 dashboard」。
>
> 两者的关系更像是「本地进程 vs SaaS 订阅」，而不是「本地 vs 远程」的同一概念换个位置。

---

## Part 2 · 为什么要有三种 Backend：InProcess / Tmux / Pane

### 2.1 首先澄清一个误区

三种后端不是「三种不同风格的实现给用户选」，而是 **对不同运行环境的适配层**。`registry.ts` 的选择逻辑是：

```
检测当前运行环境 → 能用 InProcess 就用 InProcess → 
否则尝试 Tmux（检测到 TMUX 环境变量）→ 
否则尝试 iTerm2（macOS + iTerm2）→ 
都不行就降级回更简单的模式
```

也就是说，**同一个用户在同一台机器上，在不同 shell 里跑 Claude Code，会自动挑不同的后端**。这是「环境适配」，不是「风格选择」。

### 2.2 三种后端各自适配什么场景

我们先看它们的**物理肉身**有什么差别：

```
InProcessBackend    Tmux / Pane Backend
──────────────     ────────────────────
1 Node.js 进程     多个 Node.js 进程
├─ leader queryLoop  ├─ pane 1: leader
├─ teammate A loop   ├─ pane 2: teammate A
├─ teammate B loop   ├─ pane 3: teammate B  
└─ teammate C loop   └─ pane 4: teammate C
                    （你在终端里看到 4 个分屏）
```

#### 后端 A · InProcessBackend

**适配场景**：用户在任何终端里（哪怕是 IDE 内嵌 terminal、Windows PowerShell、CI 环境）都可以用。不依赖 tmux、不依赖 iTerm2。

**优势**：

- **零启动开销**：不用 fork 进程、不用启动新的 Node runtime。spawn 一个 teammate 就是调一个函数。
- **零 IPC 开销**：teammate 之间共享内存，发消息就是函数调用。
- **无需可视化终端**：在 CI、SSH、VS Code terminal 里都能用。
- **Permission Bridge 简单**：leader 的 UI 直接拿到 teammate 的权限请求（函数回调）。

**劣势**：

- 一个 teammate 崩了（uncaughtException），**整个进程都完蛋**，所有人一起死。
- 共享文件描述符、共享 process.env、共享 cwd，**非状态的东西**容易相互影响。
- leader 的 REPL 要同时显示自己的流 + N 个 teammate 的流，UI 会很拥挤。

#### 后端 B · TmuxBackend

**适配场景**：用户已经在 tmux 会话里跑 Claude Code（`$TMUX` 环境变量存在）。

**做法**：对当前 tmux 会话 `tmux split-window`，在新 pane 里起一个 **完整独立的** `claude --team X --name Y` 子进程。

**优势**：

- **可视化**：每个 teammate 有自己的 pane，你能用眼睛直接看到它在干什么，甚至手动敲字到它的 REPL。
- **进程隔离**：一个 teammate OOM 或者 crash，别的 teammate 不受影响。
- **独立 context**：每个 pane 是独立 CLI 实例，有自己的 AppState、自己的 ink renderer、自己的 stdin。
- **独立日志**：每个 pane 的 stdout 分别滚动，不会混在一起。

**劣势**：

- 重：每个 teammate 一个 Node.js 进程（每个 ~100MB 内存起步）。
- 启动慢：要完整初始化一次 CLI（OAuth、config 加载、hook 注册…大概 1-3 秒）。
- 沟通通过 **邮箱文件**，延迟在百毫秒级。
- 强依赖 tmux 存在。

#### 后端 C · PaneBackendExecutor / ITermBackend

**适配场景**：用户在 iTerm2（macOS 原生高级终端，不用 tmux）里运行。

**做法**：通过 iTerm2 的 AppleScript 或 Python API 创建新 pane，执行一样的 `claude --team X --name Y`。

它和 TmuxBackend **行为几乎一样**，只是「怎么让终端分屏」的 API 不同。所以源码里 `PaneBackendExecutor.ts` 是父类，`ITermBackend.ts` 和 `TmuxBackend.ts` 是两个子类，把「不同终端的分屏原语」抽象掉了。

证据 —— `source/src/utils/swarm/backends/` 目录结构：

```
PaneBackendExecutor.ts   ← 父类：定义"通过某种方式创建 pane + 邮箱通信"的通用流程
TmuxBackend.ts           ← 子类：实现"pane 创建 = tmux split-window"
ITermBackend.ts          ← 子类：实现"pane 创建 = iTerm2 AppleScript"
it2Setup.ts              ← iTerm2 的专属初始化辅助
detection.ts             ← 检测当前环境适合哪个
registry.ts              ← 注册表 + 选择逻辑
```

### 2.3 为什么要三个并存？—— 用户环境的现实分布

Claude Code 的用户画像非常多样：

| 用户类型 | 所在环境 | 适配的 backend |
|---|---|---|
| macOS 资深开发者 | iTerm2 裸用 | **ITerm** |
| Linux 工程师 / SRE | tmux 重度用户 | **Tmux** |
| Windows 用户 | PowerShell / Windows Terminal | **InProcess** |
| VS Code / Cursor 用户 | IDE 内嵌 terminal | **InProcess** |
| CI / 脚本里跑 | 无交互终端 | **InProcess** |
| SSH 到服务器 | 只有基础 shell | **InProcess**（tmux 可用则优先 Tmux） |

如果只有 Tmux Backend：Windows 和 VS Code 用户没法用 Swarm。
如果只有 InProcess Backend：macOS 用户损失了可视化分屏体验。
如果只有 iTerm Backend：Linux 用户没辙。

**所以三种后端的存在，是对「多 Agent 体验」在不同环境下**做渐进降级**的结果**：有条件就给可视化（Pane/Tmux），没条件就吃苦头挤在一个进程里（InProcess）。

### 2.4 它们共享的抽象：TeammateExecutor 接口

三者都实现同一个接口：

```ts
// 简化自 utils/swarm/backends/types.ts
interface TeammateExecutor {
  spawn(config): Promise<SpawnResult>
  sendMessage(agentId, message): Promise<void>
  kill(agentId): Promise<void>
  ...
}
```

上层代码（AgentTool、spawnTeammate）**完全不知道底下是谁**。这就是多态的好处：增加一个新 backend（比如未来 WSL-specific backend），只要实现这个接口就行，不用改调用方。

---

## Part 3 · 关键问题：InProcessBackend 同进程跑多个 query loop，为什么不互相污染？

这是全文最烧脑的部分，我们慢慢拆。

### 3.1 为什么这本来**应该**污染

先理解"污染"是怎么发生的。假设你有这样一段传统代码：

```ts
// 伪代码
let currentAgent = null;   // 模块级全局变量

function startAgent(id) {
  currentAgent = id;
  runQueryLoop();
}

function runQueryLoop() {
  while (true) {
    const response = await callAPI();
    logEvent({ agentId: currentAgent, event: response });  // ← 用全局变量
  }
}

// 并发跑两个
startAgent('alice');  // 不 await！
startAgent('bob');    // 不 await！
```

这段代码 **100% 会污染**。为什么？

1. `startAgent('alice')` 执行 → `currentAgent = 'alice'` → 进入 `runQueryLoop` → `await callAPI()` → 让出 event loop。
2. `startAgent('bob')` 执行 → **`currentAgent = 'bob'`** → 进入 `runQueryLoop` → `await callAPI()` → 让出。
3. alice 的 `callAPI()` 先返回 → 恢复执行 → 调 `logEvent` → 读 `currentAgent` → **读到 'bob'** → 事件挂错 agent。

这就是作者在 `agentContext.ts:16–22` 写下的那段注释要解决的问题：

```
WHY AsyncLocalStorage (not AppState):
When agents are backgrounded (ctrl+b), multiple agents can run 
concurrently in the same process. AppState is a single shared state 
that would be overwritten, causing Agent A's events to incorrectly 
use Agent B's context. AsyncLocalStorage isolates each async 
execution chain, so concurrent agents don't interfere with each other.
```

**作者原文翻译**：AppState 是单一共享状态，会被覆盖，导致 Agent A 的事件错误地挂在 Agent B 的 context 上。AsyncLocalStorage 隔离了每条异步执行链，让并发 agent 不互相干扰。

### 3.2 AsyncLocalStorage 到底是个什么东西

这是 Node.js 的一个内置 API（`async_hooks` 模块里），心智模型如下：

**想象每个 Promise、每个 setTimeout 回调、每个 fs.readFile 回调，都悄悄背着一个「背包」。**

```ts
import { AsyncLocalStorage } from 'async_hooks';

const als = new AsyncLocalStorage<{ agentId: string }>();

// 在 als.run 里启动一条异步链，这条链上所有后续 await 都会继承这个 store
als.run({ agentId: 'alice' }, async () => {
  await doSomething();        // 这个 await 里 als.getStore() → { agentId: 'alice' }
  await doAnother();          // 这个里也是 { agentId: 'alice' }
  setTimeout(() => {
    als.getStore();            // 还是 { agentId: 'alice' }！尽管 setTimeout 是"脱离"当前栈的
  }, 1000);
});

als.run({ agentId: 'bob' }, async () => {
  await doSomething();        // 这里 als.getStore() → { agentId: 'bob' }
});
```

**关键理解**：两段 `als.run` 是在**同一个 Node 进程、同一个 event loop** 里跑的，它们的 `await` 会互相穿插调度（event loop 就是在各种 pending async 之间切换），但每当一条异步链被恢复执行，它携带的「背包」都是它自己最初被启动时的那个 store。

### 3.3 Node 是怎么做到的：AsyncWrap 和 async_hooks

这块说清楚有助于真正理解。底层机制：

1. **Node 给每个异步资源分配一个 asyncId**。Promise、Timer、TCP socket、fs 操作等都是异步资源。
2. **父子关系**：A 内部创建 B，则 B 的 triggerAsyncId = A 的 asyncId。
3. **AsyncLocalStorage 内部维护一棵树**：当 A 创建 B 时，B 自动继承 A 绑定的 store。
4. **当 Node 调度器恢复执行某个异步回调前**，它查这个 callback 对应的 asyncId 绑定了哪个 store，把它设为"当前 store"。
5. 执行结束后恢复到之前的 store。

这一切都是 Node runtime 层面做的，**JavaScript 代码看不到这个切换过程**，感觉就像「store 跟着我的异步调用走」。

所以你写 `als.getStore()`，Node 查"当前正在执行哪个 async 回调"→"这个回调的 store 是什么"→ 返回那个 store。不会串线。

### 3.4 Claude Code 里的具体应用

源码里有**三个**独立的 AsyncLocalStorage，每个管一类信息：

| 文件 | ALS 变量 | 存什么 |
|---|---|---|
| `utils/agentContext.ts:93` | `agentContextStorage` | agent 身份（分析/遥测用） |
| `utils/teammateContext.ts:41` | `teammateContextStorage` | teammate 的 agentId / abortController |
| `utils/workloadContext.ts` | `workloadContextStorage` | workload 类型标记 |

它们各自负责一类状态。真正 spawn teammate 的代码（`utils/swarm/inProcessRunner.ts`）会把 teammate 的 `runAgent()` 包在 `teammateContextStorage.run(context, () => runAgent(...))` 里。

伪代码大约这样：

```ts
// 简化自 inProcessRunner.ts
async function startInProcessTeammate(handle) {
  const teammateCtx = { agentId, parentId, abortController, ... };
  const agentCtx = { type: 'teammate', agentId, ... };

  // 嵌套的 ALS run：两个 store 同时激活
  await agentContextStorage.run(agentCtx, async () => {
    await teammateContextStorage.run(teammateCtx, async () => {
      // 这里面的所有 await 都会同时持有两个 store
      for await (const msg of runAgent(...)) {
        // 每次从 runAgent yield 出来，ALS 都还在
        processMessage(msg);
      }
    });
  });
}
```

这段代码对每个 teammate 跑一次。每次的 `teammateCtx` 不同。每个 teammate 的整条异步链都持有自己那份 store，**互不可见**。

### 3.5 用一个具体时序图看"为什么不污染"

假设我们在同一进程里 spawn 了 2 个 teammate：alice 和 bob。它们都在查 API。

```
时间轴         Alice 的链                    Bob 的链
─────────      ──────────────────────        ──────────────────────
t=0            als.run({id:'alice'}, async→)
                Alice 执行到 await fetch
                → 让出 event loop
                (背包里装着 'alice')
                
t=1                                          als.run({id:'bob'}, async→)
                                              Bob 执行到 await fetch
                                              → 让出 event loop
                                              (背包里装着 'bob')

t=2            Bob 的 fetch 先返回
                                              Node runtime 看：
                                                这个 callback 属于哪条异步链？
                                                → Bob 的链
                                                → 激活 {id:'bob'} 的 store
                                              Bob 继续执行：
                                                als.getStore() → 'bob' ✓
                                                log({agentId:'bob', ...})
                                                await 下一步
                                              Node runtime 恢复到 Bob 的 store 激活前的状态

t=3            Alice 的 fetch 返回
               Node runtime：
                 这个 callback 属于 Alice 的链
                 → 激活 {id:'alice'} 的 store
               Alice 继续：
                 als.getStore() → 'alice' ✓ 
                 log({agentId:'alice', ...})
               
```

**关键点**：t=2 时 Bob 的 callback 被调用之前，Node runtime 主动帮你切换了"当前 store"。这个切换不是 JS 代码做的，是 runtime 机制。JS 代码完全透明地用 `als.getStore()` 就能拿到正确答案。

### 3.6 那么**什么东西还是会污染**？

ALS **只隔离挂在 ALS 里的状态**。以下东西不在 ALS 保护范围内，共享即污染：

| 共享资源 | 是否污染 | 为什么 |
|---|---|---|
| 模块级 `let currentFoo = ...` | **会污染** | 写 ALS 外的全局变量就是共享的 |
| `process.env.SOMETHING` | **会污染** | 进程级环境变量 |
| `process.cwd()` / `process.chdir()` | **会污染** | cwd 是进程级属性 |
| 文件系统（同路径并发写） | **会污染** | 物理资源竞争 |
| Ink renderer / terminal stdout | **共享** | 只有 leader 有 UI，teammate 不直接写 stdout |
| 单例 API client 里的内部 queue | 取决于实现 | 如果它也用 ALS 或 per-call 参数就 OK |
| 模块级定时器 | **会污染** | 定时器回调不一定携带正确 ALS |

Claude Code 的做法是：**把所有跨 teammate 应该隔离的东西都放进 ALS**，包括：

- `AppState` 的关键字段：不再是全局单例，而是通过 `getAgentContext()` / `getTeammateContext()` 动态解析。
- `AbortController`：每个 teammate 自己的 abort 信号。
- tool use context：权限模式、hook 列表等。
- Analytics metadata：确保每个事件挂对 agent id。

**而需要共享的东西**（文件系统、网络、leader 的 UI），就让它们真的共享，靠别的机制（锁、队列、permission bridge）协调。

### 3.7 一个 corner case：teammate 通过 env var 传递身份的原因

注意 `teammateContext.ts:7-14` 这段注释：

```
Relationship with other teammate identity mechanisms:
- Env vars (CLAUDE_CODE_AGENT_ID): Process-based teammates spawned via tmux
- dynamicTeamContext (teammate.ts): Process-based teammates joining at runtime
- TeammateContext (this file): In-process teammates via AsyncLocalStorage
```

为什么 **Tmux 下的 teammate 用 env var、in-process 的用 ALS**？

- Tmux teammate 是独立进程，ALS 是 Node 进程内的机制，跨进程不存在。但 env var 在 `fork/exec` 时会继承，正好用来传身份。
- in-process teammate 在同进程里共享 env var（一改全改，污染），所以不能用 env var，只能用 ALS。

**同一个逻辑问题（"我是哪个 agent？"）在两种后端下用了两种不同方案**，每种方案都是"该环境下能保证隔离的最省力机制"。这是个相当精妙的工程设计。

### 3.8 小结：为什么不污染的一句话答案

> 因为 **Node 的 AsyncLocalStorage 给每条异步执行链挂了一个隐形"背包"**，event loop 调度切到哪条链就激活哪个背包。Claude Code 把 teammate 的身份、abort、AppState 关键字段都塞进这个背包，所以即便 5 个 query loop 的 await 在同一个 event loop 里你来我往、交错恢复，每次恢复后代码看到的都是"自己那只背包"里的状态，而不是全局共享的最新写入值。

---

## Part 4 · 两个问题连起来看

这两个设计（RemoteAgentTask / 三种 Backend）其实在回答**同一个根本问题**：

> **"多 Agent 协作"这件事，在不同部署条件下最合适的实现是什么？"**

答案是一张光谱：

```
「最轻量、最快」                                      「最重量、最强」
          ←————————————————————————————————————————→
InProcess  →  Tmux/Pane  →  LocalTask  →  Bridge  →  RemoteAgent
同进程       多进程同机    本地异步      跨设备      完全云上
  |            |            |            |            |
  |            |            |            |            └─ 托管 workflow，
  |            |            |            |              独立生命周期，
  |            |            |            |              服务端集成
  |            |            |            └─ 本地权力 + 云端 UI
  |            |            └─ 本地后台
  |            └─ 进程隔离 + 可视化
  └─ 零开销
```

**用户需要一个 teammate 做 30 秒的小活**（查文件、跑测试）？InProcessBackend。
**用户需要 4 人团队并行工作并肉眼观察进度**？Tmux/Pane Backend。
**用户需要一个后台任务跑 10 分钟**？LocalAgentTask。
**用户希望在家控制公司机器**？Bridge。
**用户希望云端一直盯着一个 PR 直到合入**？RemoteAgentTask (`background-pr`)。

每一档都是针对一种真实场景，**不能用下一档替代**（下一档太重或不符合语义）、**不能用上一档替代**（上一档不够强）。所以 Claude Code 不是选一个赢家，而是把**整条光谱都实现了**，让框架根据场景自动选。

---

## 附录 · 关键源码位置

| 主题 | 文件 | 行 |
|---|---|---|
| RemoteTask 类型枚举 | `tasks/RemoteAgentTask/RemoteAgentTask.tsx` | 60–61 |
| RemoteTask state 定义 | 同上 | 22–59 |
| ultrareview 进度字段 | 同上 | 44–50 |
| teleport 通信层 | `utils/teleport.ts` | 全文件 |
| InProcess backend | `utils/swarm/backends/InProcessBackend.ts` | 38–144 |
| Tmux backend | `utils/swarm/backends/TmuxBackend.ts` | 100+ |
| Pane backend 父类 | `utils/swarm/backends/PaneBackendExecutor.ts` | 全文件 |
| iTerm backend | `utils/swarm/backends/ITermBackend.ts` | 全文件 |
| Backend 注册选择 | `utils/swarm/backends/registry.ts` | 全文件 |
| Backend 环境检测 | `utils/swarm/backends/detection.ts` | 全文件 |
| **AgentContext ALS（附作者 WHY 注释）** | `utils/agentContext.ts` | 16–22, 93 |
| **TeammateContext ALS（附三种机制对比）** | `utils/teammateContext.ts` | 4–14, 41 |
| in-process 启动器 | `utils/swarm/inProcessRunner.ts` | 全文件 |
| 权限桥 | `utils/swarm/leaderPermissionBridge.ts` | 25–54 |
| 邮箱读写 | `utils/teammateMailbox.ts` | 全文件 |

---

## Part 5 · 磁盘存储：Teammate 和 Task 的文件到底在哪儿

上面反复说"邮箱"、"team file"、"sidechain transcript"，那它们在你电脑的哪个目录？这节把所有落盘位置列清楚。

### 5.1 根目录：`~/.claude/`（Windows 上是 `C:\Users\{你}\.claude\`）

所有 Claude Code 的用户级数据都落在这里。路径解析在 `utils/envUtils.ts:7–14`：

```ts
export const getClaudeConfigHomeDir = memoize((): string => {
  return (process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), '.claude'))
         .normalize('NFC')
})
```

**可以通过 `CLAUDE_CONFIG_DIR` 环境变量覆盖**。如果你设了这个环境变量，所有路径都会挪过去。

### 5.2 Swarm / Team 目录：`~/.claude/teams/{team_name}/`

这是 **Swarm 本身** 的数据所在，由 `utils/envUtils.ts:16` 的 `getTeamsDir()` 解析：

```
~/.claude/teams/
├── devteam/                         ← 一个 swarm/team 一个目录
│   ├── config.json                  ← TeamFile，见下
│   └── inboxes/                     ← 每个 teammate 的收件箱
│       ├── alice.json
│       ├── bob.json
│       └── carol.json
├── review-squad/
│   ├── config.json
│   └── inboxes/
│       └── ...
└── default/                         ← 未命名 team 会落到这里
    └── inboxes/
```

#### `config.json`（Team File）

由 `utils/swarm/teamHelpers.ts:115–124` 生成：`getTeamDir(team) = join(getTeamsDir(), sanitizeName(team))`；`getTeamFilePath(team) = join(getTeamDir(team), "config.json")`。

完整结构（定义在 `teamHelpers.ts:64–90`）：

```json
{
  "name": "devteam",
  "description": "Full-stack 4-person swarm",
  "createdAt": 1744000000000,
  "leadAgentId": "leader@devteam",
  "leadSessionId": "session-uuid-for-discovery",
  "hiddenPaneIds": ["%12"],
  "teamAllowedPaths": [
    { "path": "/abs/path", "toolName": "Edit",
      "addedBy": "alice", "addedAt": 1744000000000 }
  ],
  "members": [
    {
      "agentId": "alice@devteam",
      "name": "alice",
      "agentType": "general-purpose",
      "model": "claude-sonnet-4-6",
      "prompt": "你是测试工程师...",
      "color": "blue",
      "planModeRequired": false,
      "joinedAt": 1744000001000,
      "tmuxPaneId": "%3",
      "cwd": "/path/to/repo",
      "worktreePath": "/path/to/repo-alice-wt",
      "sessionId": "alice-session-uuid",
      "subscriptions": ["file-changes"],
      "backendType": "tmux",
      "isActive": true,
      "mode": "default"
    },
    { "name": "bob", ... },
    { "name": "carol", ... }
  ]
}
```

关键字段解读：

| 字段 | 含义 |
|---|---|
| `members[].agentId` | 全局唯一标识，格式 `{name}@{team}` |
| `members[].tmuxPaneId` | 对 Tmux/Pane backend 才有，指向具体 pane（`%N` 这种语法是 tmux 的 pane id） |
| `members[].worktreePath` | 如果 spawn 时开了 worktree 隔离，记下 worktree 的绝对路径 |
| `members[].sessionId` | 每个 teammate 自己的 session id（独立 transcript） |
| `members[].backendType` | "inprocess" / "tmux" / "iterm" — 知道这个 teammate 是哪类肉身 |
| `members[].isActive` | idle hook 触发时会改为 false；新 prompt 到来时改回 true |
| `members[].mode` | "default" / "acceptEdits" / "bypassPermissions" — 权限模式 |
| `teamAllowedPaths` | "白名单路径"。team 成员在这些路径下用 Edit/Write 不会再问权限 |
| `hiddenPaneIds` | 用户手动把某个 pane 折叠掉了，记下来 |

**这个文件既是配置也是运行时状态**。Claude 启动时读它来发现 team，teammate 加入/退出时更新它，leader 用它来知道"我的 team 现在有谁"。

#### `inboxes/{agent_name}.json`（邮箱）

来自 `utils/teammateMailbox.ts:56–66`：`getInboxPath(agentName, teamName) = {teamDir}/inboxes/{sanitize(agentName)}.json`。

文件内容是 **一个 JSON 数组**（注意不是 JSONL），每条是 `TeammateMessage`（`teammateMailbox.ts:43–50`）：

```json
[
  {
    "from": "leader",
    "text": "Alice, 麻烦先跑一下 npm test",
    "timestamp": "2026-04-14T12:00:00Z",
    "read": true,
    "color": "green",
    "summary": "Run npm test"
  },
  {
    "from": "bob",
    "text": "我改完 login.ts 了，你能 review 一下吗？",
    "timestamp": "2026-04-14T12:15:00Z",
    "read": false,
    "color": "blue",
    "summary": "Login.ts ready for review"
  },
  {
    "from": "leader",
    "text": "<shutdown-request>...</shutdown-request>",
    "timestamp": "2026-04-14T18:00:00Z",
    "read": false
  }
]
```

#### 邮箱读写的并发控制（关键细节）

好几个 teammate 会同时写同一个人的邮箱。怎么防止竞态？

`teammateMailbox.ts:23, 35–41` 用了 **lockfile**：

```ts
import * as lockfile from './lockfile.js'

const LOCK_OPTIONS = {
  retries: {
    retries: 10,
    minTimeout: 5,
    maxTimeout: 100,
  },
}
```

每次写邮箱时：`lockfile.lock(path) → 读 → 改 → 写 → unlock`。
如果另一个进程（或另一个 in-process teammate 的异步链）拿着锁，就指数退避重试，最多 10 次。

这解释了为什么是 **JSON 数组而不是 JSONL**：JSONL 可以并发 append 不冲突，但 JSON 数组必须原子读改写。选数组是因为读的时候 UI 需要随机访问（按 index 标记已读），不是纯消费队列。

#### 消息类型（邮箱里不止聊天）

邮箱里除了普通聊天消息，还承载了协议消息。`teammateMailbox.ts` 里定义了多种：

- `TEAMMATE_MESSAGE_TAG` —— 普通聊天/指令（XML 包装，会以 attachment 形式注入到收件人的下一个 prompt）
- **idle notification** (L392)：teammate 的 Stop hook 触发时发给 leader，告诉它"我空下来了"
- **plan approval request** (L682)：teammate 想退出 plan mode 但需要 leader 批准
- **shutdown request/approved/rejected** (L718/735/753)：关闭握手
- **task assignment** (L951)：leader 派活
- **team permission update** (L980)：leader 广播全组权限变更
- **mode set request** (L1016)：leader 命令某人切换 permission mode

**也就是说，邮箱既是聊天信道，也是 RPC 信道**。它实际上是 teammate 间的**唯一**通信通道（除了 in-process 下的 leaderPermissionBridge 函数回调）。

### 5.3 Session Transcript：`~/.claude/projects/{sanitized-cwd}/`

这不是 swarm 特有的，是所有 Claude session 都有的，但 teammate 的对话也落在这里。

路径来自 `sessionStorage.ts:199`：`getProjectsDir() = join(claudeHome, 'projects')`。每个 **cwd**（工作目录）对应一个项目子目录（路径被 sanitize，比如 `/` → `-`）。

```
~/.claude/projects/
└── E--Au-notes-claude-code/          ← 你的 repo 路径 sanitize 后的结果
    ├── {sessionId-1}.jsonl           ← 主 session 的完整 transcript
    ├── {sessionId-2}.jsonl           ← 另一个 session（比如你昨天的）
    └── {sessionId-1}/                ← 这个 session 专属的 metadata 子目录
        ├── subagents/                ← 子 agent 的 sidechain transcript
        │   └── {agentId}/
        │       └── sidechain.jsonl
        ├── remote-agents/            ← Remote agent 恢复用的元数据
        │   └── remote-agent-{taskId}.meta.json
        └── ...
```

#### `{sessionId}.jsonl`

每行一个 JSON，包含一条消息或一个事件。由 `getTranscriptPathForSession(sessionId)`（`sessionStorage.ts:207–224`）解析。

#### `subagents/{agentId}/sidechain.jsonl`

这就是本文档第一篇（`multiagent_add.md`）里反复提到的 **sidechain**。

- LocalAgentTask 把后台子 agent 的每一条 message append 进去。
- 每条消息带 UUID，重启 session 时 UUID 去重合并回内存 messages。
- TaskOutputTool 读这个文件返回给模型。

**同时 in-process teammate 也用它**：每个 teammate 有独立 sessionId，它的对话会写自己的 `{teammateSessionId}.jsonl`，如果也是 spawn 的 sub-agent 角色，还会有自己的 subagents/ 目录。

#### `remote-agents/remote-agent-{taskId}.meta.json`

代码 `sessionStorage.ts:320–344`：

```ts
function getRemoteAgentsDir(): string {
  const projectDir = getSessionProjectDir() ?? getProjectDir(getOriginalCwd())
  return join(projectDir, getSessionId(), 'remote-agents')
}

function getRemoteAgentMetadataPath(taskId: string): string {
  return join(getRemoteAgentsDir(), `remote-agent-${taskId}.meta.json`)
}
```

文件内容（`RemoteAgentMetadata`）只包含 **身份信息**，不包含消息内容：

```json
{
  "taskId": "remote-task-abc123",
  "sessionId": "ccr-session-xyz",
  "remoteTaskType": "ultrareview",
  "title": "Review PR #456",
  "command": "/ultrareview 456",
  "spawnedAt": 1744000000000,
  "toolUseId": "toolu_...",
  "isLongRunning": true,
  "isUltraplan": false,
  "isRemoteReview": true,
  "remoteTaskMetadata": { ... }
}
```

注释 L332–336 说得很明白：**"status is always fetched fresh from CCR on restore — only identity is persisted locally"**。
即本地只存「指针」，task 的真实状态在云端；session 重启时用 `taskId` + `sessionId` 去云端拉最新进度。

### 5.4 Task Output（一次性大文件）：`/tmp/claude-{uid}/{sanitized-cwd}/{sessionId}/tasks/{taskId}.output`

这是 LocalAgentTask 异步 agent 产出的**原始 stdout/stderr** 输出，不是消息结构化 JSON。

路径来自 `utils/task/diskOutput.ts:50–73`：

```ts
export function getTaskOutputDir(): string {
  return join(getProjectTempDir(), getSessionId(), 'tasks')
}
export function getTaskOutputPath(taskId: string): string {
  return join(getTaskOutputDir(), `${taskId}.output`)
}
```

而 `getProjectTempDir()`（`permissions/filesystem.ts:376–378`）：

```ts
// /tmp/claude-{uid}/{sanitized-cwd}/
return join(getClaudeTempDir(), sanitizePath(getOriginalCwd())) + sep
```

为什么放 `/tmp`（Windows 上是 `%TEMP%\claude-{uid}\...`）而不是 `~/.claude/`？

- 体积可能很大（一个 agent 跑几小时的完整 stdout），不应该污染家目录。
- 重启机器就自动清掉（符合 "output 本应临时" 的语义）。
- L17–18 的安全注释：tasks 目录的写入用了 `O_NOFOLLOW` 防止 symlink 攻击。

### 5.5 Worktree：不在 `.claude` 里

当 teammate 或 subagent 用 `isolation: "worktree"` spawn 时，会创建 **git worktree**（见 `utils/worktree.ts`）。

worktree 的落点**不**在 `.claude/`，而是和你的 repo **同级或指定位置**。典型路径：

```
/path/to/your-repo/                   ← 你的主 checkout
/path/to/your-repo-{agentName}-wt/    ← teammate alice 的 worktree（举例）
```

具体路径记在 `TeamFile.members[].worktreePath` 字段里。

**这个分离很重要**：代码隔离放磁盘上别处（git 的物理隔离），而 teammate 的"状态"文件（config、inbox）留在 `.claude/teams/`。两者关注点分开。

### 5.6 所有路径汇总（一张表）

| 数据 | 绝对路径 | 解析函数 | 生命周期 |
|---|---|---|---|
| Team 配置 | `~/.claude/teams/{team}/config.json` | `getTeamFilePath()` | Team 生命周期 |
| Teammate 收件箱 | `~/.claude/teams/{team}/inboxes/{agent}.json` | `getInboxPath()` | Team 生命周期 |
| 主 session 对话 | `~/.claude/projects/{cwd}/{sessionId}.jsonl` | `getTranscriptPathForSession()` | 永久（可手动删） |
| Sub-agent sidechain | `~/.claude/projects/{cwd}/{sessionId}/subagents/{agentId}/sidechain.jsonl` | sessionStorage 内部 | 永久 |
| Remote agent 指针 | `~/.claude/projects/{cwd}/{sessionId}/remote-agents/remote-agent-{taskId}.meta.json` | `getRemoteAgentMetadataPath()` | Remote task 结束后可清 |
| Async task 输出 | `/tmp/claude-{uid}/{cwd}/{sessionId}/tasks/{taskId}.output` | `getTaskOutputPath()` | 重启清空 |
| Worktree（代码） | 和 repo 同级的临时目录 | `utils/worktree.ts` | 显式清理 |

### 5.7 实际验证方法

你可以现在就去本地看：

```bash
# 看所有 team
ls ~/.claude/teams/

# 看某个 team 的成员
cat ~/.claude/teams/devteam/config.json | jq '.members[].name'

# 看 alice 的未读消息
cat ~/.claude/teams/devteam/inboxes/alice.json | jq '.[] | select(.read==false)'

# 看某个 session 的主 transcript（注意 cwd 要做路径替换）
ls ~/.claude/projects/
head -1 ~/.claude/projects/E--Au-notes-claude-code/{sessionId}.jsonl | jq .

# Windows PowerShell
Get-Content "$env:USERPROFILE\.claude\teams\devteam\config.json" | ConvertFrom-Json
```

### 5.8 关键洞察

1. **Swarm 的持久化是文件系统级的**。不依赖数据库、不依赖中心服务，靠 `~/.claude/teams/` 目录 + lockfile 协调。所以即使所有 teammate 进程都挂了，重启后从磁盘加载 config.json 就能恢复 team 结构。

2. **Inbox = 跨进程跨设备都一致的通信层**。InProcess teammate 用它，Tmux/Pane teammate 也用它。这是唯一无论后端是什么都成立的通信通道 —— 因为本地文件所有后端都能读。

3. **每个 teammate 的独立对话分两层存**：
   - **Config（身份/元数据）** → `~/.claude/teams/{team}/config.json` 里的 members entry
   - **Transcript（聊天内容）** → `~/.claude/projects/{cwd}/{agentSessionId}.jsonl`
   - 两者通过 `sessionId` 字段关联

4. **Remote 和 Local 的分野在磁盘上也能看到**：Local task 的完整输出在 `/tmp/.../tasks/`，Remote task 的本地只有 meta.json 指针。这就是"Local 是后台进程、Remote 是托管服务"的物理表现。
