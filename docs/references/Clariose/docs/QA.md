# Clariose / Zai 后端：三套 Agent 流水线疑问彻底答疑

> 文档版本：2026-04-29
> 配套阅读：`docs/design/cdx_multiagent.md`
> 答疑范围：`backend/src/modules/{agents,team,carenote,sessions,realtime}/`

写这份 QA 的起因是你看完 `cdx_multiagent.md` 后提出三个核心疑问。我先通读了你目前真实的后端代码（不是只看文档），把每个问题对应到具体文件和行号做了比对，发现你的直觉很多地方都是对的——文档把"演进路径"写成了"并存的三条产品流水线"，这造成了不少混淆。下面逐题回答，并在最后给一张"现在到底是什么在跑"的总图。

---

## 问题 1 — 为什么会有三套 Agent 流水线？

**短答案**：不是"三套并存的产品流水线"，是"三代代码遗留物"，目前真正还会跑的只剩两条；其中一条（v1）实际上 **只剩读接口在用，runner 已经是 dead code**。

### 1.1 三代分别是什么、为什么出现

| 代号 | 触发时机 | 模型 | 文件位置 | 现在还跑吗？ |
|------|---------|------|---------|-----|
| **v1 Legacy**（5 agents fan-out） | 用户结束问诊后，前端调一次 `/sessions/:id/agents/run` | `gpt-4o-mini` 直连 | `backend/src/modules/agents/` | **runner 已无任何调用方**（见 1.2）；snapshot/digest/accept 这三个**读**接口仍在用 |
| **v1.5 Team DAG**（8 agents） | 同上：用户结束问诊后调 `/sessions/:id/agents/run` 或 `/sessions/:id/team/run` | `gpt-4o-mini` + JSON Schema 校验 + Blackboard | `backend/src/modules/team/` + `team/team.json` | **是**，是当前 legacy `/consult` 页面真正跑的 runner |
| **v2 CareNote / CLARIOSE_V01**（11 Codex roles） | 浏览器每发一个 OpenAI Realtime 事件就走一次；当一个 turn 完成时触发完整 11-role 流水线 | Codex SDK / CLI（chatgpt 订阅或 api key），fallback 到 gpt-4o-mini 修复 JSON | `backend/src/modules/carenote/` | **是**，是新 `/carenote/visit/:id` 页面跑的主线 |

代码里这三代真实并存的事实证据：

- `backend/src/modules/agents/agents.service.ts:27` 定义了 `runAll(sessionId)`（v1）。
- `backend/src/modules/sessions/sessions.controller.ts:64-72` 把 `POST /sessions/:id/agents/run` 委派给了 `this.team.run(sessionId)`——**不是 v1**；
  ```ts
  // Delegates to the 8-agent TeamRunner. The runner writes AgentRun rows
  // with the same AgentKind values the legacy snapshot reads, so this
  // endpoint stays backwards compatible with the original 2x2 UI.
  void this.team.run(sessionId).catch(() => {});
  ```
- `grep -rn "agents.runAll\|AgentsService\." backend/src/` 的结果显示：**没有任何地方调用 `runAll`**；只有 `agents.snapshot()`、`agents.composeDigest()`、`agents.promoteReminderDrafts()` 还有调用方。
- `backend/src/modules/team/team.runner.ts` 真正执行 `team.json` 里那张 5 阶段 DAG。
- `backend/src/modules/carenote/api/codexHarnessApi.ts:111-122` 把 `transcript_turn_completed` 总线事件接到 `queue.enqueue({ kind:'analyze_turn', ... })`——v2 的入口完全独立于 `/sessions/:id/agents/run`。

### 1.2 你的原始期望 vs. 现在的代码

> "我的想法不是直接通过 gpt-realtime 拿实时输入，然后直接通过 8 个 agent 根据 transcript 完成接下来的工作？"

你的期望本质上是 **"一条流水线：realtime → 一个 agent 团队"**。这跟 v2 CareNote 是一致的（虽然 v2 是 11 个，不是 8 个）。

那为什么还有 v1 / v1.5？
1. **v1** 是早期 MVP，按 session 结束时一次性 fan-out 5 个 review agent，落到 `MedicationPlan / FollowUp / FamilyDigest` 表里。前端旧 `/consult` + `/summary` 页面读的就是这几张表。
2. **v1.5** 是 v1 之后引入"DAG + Blackboard + JSON Schema"做的一次升级——把 5 个 agent 拆得更细成 8 个，加了 schema 校验和 SSE 流，但**写回的还是同一批表**，所以前端 UI 不用改。控制器注释里那行 `stays backwards compatible with the original 2x2 UI` 就是这个意思。
3. **v2** 是真正的 turn 级 streaming 架构，使用 Codex Harness + 4 层通信 + 持久化 thread。这才是你脑子里那套"多 agent 协作"。它**没有替换 v1/v1.5**，而是在另一条 URL 路径 (`/api/visits/...`) 上独立跑——所以同一个仓库里同时存活了三代。

### 1.3 现在的真实结论

- **v1 的 runner 是死代码**——可以下掉 `runAll` / `runOne` / `prompts.ts`，唯一保留的是 `snapshot / composeDigest / promoteReminderDrafts` 这三个读 helper（被 SessionsController 用作 legacy `/consult` 页的读接口和提醒接受路由）。
- **v1.5 仍然活着**：当用户在前端点了"运行 agents"时调的就是它（`team.runner.ts:49 run()`）。
- **v2 是新生产形态**：它跟 v1.5 完全独立，没有共享任何 runner。两者唯一交集是同一个 `Reminder` 表（v2 的 `medication_reminder_draft` 也走 `/api/sessions/:id/reminders/accept` 把 DRAFT 升级成 SCHEDULED）。

> 文档里第 5.3 节那句"默认走 v1 fan‑out"是**错的**——代码已经把默认路径切到 v1.5 了。这是文档需要更正的第一个事实性错误。

---

## 问题 2 — 为什么 v1.5 是 DAG，而不是 leader / coordinator 模式？

**短答案**：DAG 描述的是 **执行调度形状**，不是 **通信形状**。Blackboard 才是通信。这两件事不互斥——v1.5 既是 DAG 调度，也是基于黑板的多 agent 通信系统；而且它确实**有一个 leader**：stage 0 的 `orchestrator`。

### 2.1 为什么需要执行依赖

打开 `team/team.json` 看 stages：

```
Stage 0  orchestrator                            (准入门控)
Stage 1  transcript-verification ∥ speaker-role
Stage 2  medical-instruction-extractor
Stage 3  clarification-question
       ∥ medication-schedule-draft
       ∥ caregiver-notification
Stage 4  safety-guardrail
```

这些依赖都是**真的数据依赖**，不是随便排出来的：

- `medical-instruction-extractor`（stage 2）必须等 `transcript-verification` + `speaker-role`（stage 1）跑完——否则它读不到"已校正的转写"和"speaker 标签"。
- `medication-schedule-draft`、`caregiver-notification`、`clarification-question`（stage 3）都依赖 stage 2 抽取出的"指令清单"。
- `safety-guardrail`（stage 4）要审 stage 3 全部产物。

如果你把它做成"coordinator 一次性把 transcript 派给 8 个 agent 并行跑"，结果就是：
- 每个下游 agent 都得自己重新做一遍 speaker 归属、schema 抽取——浪费成本而且**结论可能互相不一致**。
- safety 守卫无法对其它 agent 的输出做审计（因为它们还没开始跑）。
- 一旦 stage 0 判定 transcript 太短（`readiness === 'TOO_SHORT'`），后面 7 个 agent 全部应该跳过——这恰好是 `team.runner.ts:79-86` 写的"短路"逻辑。

### 2.2 DAG 与 leader-coordinator 不是对立面

你说的"leader / coordinator 把任务发放给子 agent"在 v1.5 里就是：

- **`orchestrator` = leader**（stage 0 单独占一阶段，做准入决策、读 `transcript.raw`、写 `orchestrator.plan`）。
- **`TeamRunner` = scheduler / dispatcher**（按 DAG 阶段调度，发起每个 agent 的运行）。
- **`Blackboard` = 通信总线**（agent 之间不直接调用对方，全部通过 KV `read / readMany / write`）。

也就是说，v1.5 的"多 agent 协作"框架由三个组件拼成：DAG（**谁先谁后**）+ Blackboard（**怎么交换信息**）+ Orchestrator（**要不要全跑**）。DAG 不取代多 agent 通信，它只是规定了调度顺序——同 stage 的 agent **完全是并行的**，并行 agent 之间通过 Blackboard 看到上一 stage 留下的状态。

> 一个直观的类比：DAG 像"**流水线工位的物理顺序**"，Blackboard 像"**车间共享的零件架**"。每个工位（agent）从架子上取自己关心的零件、做完再放回去；工位之间不打电话，但因为站位有先后，下一道工序总能拿到前一道的产出。

### 2.3 v1.5 vs v2：通信复杂度的真正差距

如果你想要的是"更动态的多 agent 互通"——agent 之间能互相发消息、能动态决定"我现在该不该跑"——那 v2 才是你想要的形态：

| 维度 | v1.5 DAG | v2 CareNote |
|------|----------|-------------|
| 调度 | 静态 DAG（5 阶段写死在 `team.json`） | 动态：每 turn 跑一次完整 11-role；外加 SubscriptionRegistry 触发 `single_role` 按需调用 |
| 通信 | 仅 Blackboard | Blackboard + Mailbox（点对点邮件）+ Tasks（任务委派）+ EventBus（事件广播）共 4 层 |
| 触发 | 用户结束问诊后一次性 | 每个 transcript turn 完成立即触发 |
| 防震荡 | 不需要（一次性跑完就停） | cooldown 2s + hop ≤ 3 + cycle_breaker（`subscriptionRegistry.ts`） |
| 状态 | 进程内 Blackboard，跑完即扔 | 进程内 Map + DB 镜像 + VisitState JSON 持久化 |

所以你"应该是多 agent 通信而不是 DAG"的直觉，本身没错——只不过对 v1.5 来说 DAG 已经够用（一次性的 review pipeline，不需要 agent 之间临时商量），到了 v2 才升级成完整的多 agent 通信框架。

---

## 问题 3 — v2 CareNote / CLARIOSE_V01 到底是什么？我现在 realtime 后真正跑的是哪条？

**短答案**：v2 是你当前 `/carenote/visit/:id` 页面在跑的**主线**，跟 v1/v1.5 完全独立。"realtime input 之后调用的都是 v2 CareNote 的 turn 级流水线"——这句话**对了一半**：CareNote 路径下确实是 v2，但你同时还有一条 legacy `/consult` 路径会跑 v1.5。两者由前端的不同页面分别触发，**后端两套都活着**。

### 3.1 前端有两条页面/触发路径

`grep` 前端代码可见：

- `frontend/composables/useRealtime.ts:187` —— 老 `/consult` 页：每次 transcript 完成调 `POST /sessions/:id/utterances`；用户结束后调 `/sessions/:id/team/run`（v1.5）。
- `frontend/composables/useCareNote.ts` + `frontend/pages/carenote/visit/[id].vue` —— 新 CareNote 页：每个 OpenAI Realtime 事件直接 POST 到 `/api/visits/:id/realtime-events`，从此走 v2。

也就是说，**"realtime input 之后跑哪套"取决于用户进的是哪个前端页面**：

```
旧页面 /consult           新页面 /carenote/visit/:id
   │                           │
   │ POST /utterances          │ POST /visits/:id/realtime-events
   │ POST /team/run            │ (每事件)
   ▼                           ▼
v1.5 DAG (8 agents)        v2 CareNote (11 Codex roles, turn-level)
   │                           │
   ▼                           ▼
MedicationPlan/FollowUp/    VisitState JSON (ConsultSession.visitState)
FamilyDigest 表             + CarenoteTask/CarenoteBlackboard/
                            CarenoteMailbox/CarenoteAgentRun 表
```

### 3.2 为什么文档里那句话让你觉得"不在这条路径"？

文档第 5.3 节说："**v2 CareNote 的 turn 级流水线不在这条路径**——它由 `TranscriptAssembler` 检测到 turn 完成时由 `CodexJobQueue` 主动触发。"

这句话的意思是："**v2 不是被 `/sessions/:id/agents/run` 这个 HTTP 接口触发的**——它是被 realtime 事件流自己触发的。" 它没说"v2 不跑了"。整条触发链如下（来自 `carenote.service.ts:490-590` 和 `codexHarnessApi.ts:111-122`）：

```
浏览器收到 OpenAI Realtime delta
   │
   ▼
POST /api/visits/:id/realtime-events (event)        ← 控制器入口
   │
   ▼
CareNoteService.ingestRealtimeEvent
   │
   ├─ applyRealtimeEventToVisitState  (立刻把转写写进 VisitState JSON)
   │
   └─ TranscriptAssembler.apply      (累积 delta，识别 turn 完成)
        │
        │ emitted_turn （turn 完成才返回非空）
        ▼
   harness.bus.publish(TurnCompleted)   (RxJS Subject)
        │
        ▼
   InMemoryCodexJobQueue.enqueue({ kind:'analyze_turn', ... })
        │   per-visit 串行；同 visit 不会并发
        ▼
   CodexRunManager.process(job)
        │
        ▼
   CodexRunManager.analyzeTurn(job)        ← 这就是"完整 11 角色流水线"
        ① recall.prefetch (4 phase)
        ② Pass 1   tq ∥ sr ∥ ie
        ③ Pass 1.5 sc
        ④ Pass 2   mr ∥ ft ∥ fs ∥ mu
        ⑤ guardrail cg
        ⑥ applyGuardrail
        ⑦ reduceTurn → VisitState
        ⑧ publishToBlackboard
```

也就是说：

- **触发口**：`POST /api/visits/:id/realtime-events`（不是 `/sessions/:id/agents/run`）
- **真正驱动者**：`TranscriptAssembler`（拼 turn）+ `CodexJobQueue`（串行跑 turn）
- **和 v1/v1.5 的关系**：完全没有走 `AgentsService` / `TeamRunner` 这两个老 runner

### 3.3 v2 比 v1.5 多出来的几样东西

如果对 v2 没有"感觉"，关键差异列在这里（每条都附代码位置）：

1. **11 个 Codex Role**（`carenote/medical/medicalSchemas.ts` `CodexAgentRole` 枚举）
   - `visit_orchestrator / transcript_quality / speaker_role / medical_instruction_extractor / medication_reminder_draft / follow_up_task_draft / safety_clarification / family_summary / memory_update / compliance_guardrail / final_visit_summary`
   - 每个 role 有持久化的 `thread_id`（`CodexThreadStore`），跨 turn 复用同一个 Codex 线程，让模型自己累积上下文。这在 v1/v1.5 里没有——它们每次都从空白上下文开始。

2. **4 层通信**（`carenote/swarm/`）
   - **Layer 0 EventBus**：`CarenoteEventBus`（RxJS）广播 `transcript_turn_committed / agent_run_started / agent_run_completed / blackboard_updated / mailbox_message / dream_completed`。
   - **Layer 1 共享状态**：`Blackboard`（KV，DB 镜像 `CarenoteBlackboard`）+ `Mailbox`（文件真源 + DB 镜像 `CarenoteMailbox`），后者是 role-to-role 邮件。
   - **Layer 2 Tasks**：`CarenoteTask` 表，是"想让别的 role 干活"的唯一合法载体，可形成树状（`parentTaskId`）。
   - **Layer 3 SubscriptionRegistry**：role 订阅黑板键 / 邮箱事件，命中时入队 `single_role` job——cooldown 2s、hop ≤ 3 防震荡（`subscriptionRegistry.ts`）。

3. **每 turn 都跑完整流水线**（`codexRunManager.ts:analyzeTurn`）
   - 你看到一句话进来，背后就是 11 个 Codex 调用一次跑完（Pass1 三连并行 → Pass1.5 → Pass2 四连并行 → guardrail → reducer）。
   - 这意味着 **延迟敏感**——所以 `CodexJobQueue` per-visit 串行（避免同 visit 状态被并发写坏），跨 visit 才并行。

4. **记忆召回 4‑Phase**（`carenote/recall/`）
   - 每 turn 跑一次 `MemoryRecall.prefetch`：scan 用户 `.data/carenote/memory/users/<u>/{facts,skills,candidates}` → side-query 调 gpt-4o-mini 排序选 top-N → surface 读文件、按字节预算截断 → inject 拼成 Markdown 块通过 `extra_instructions` 注入所有 11 个 role 的 prompt 末尾。
   - 这保证一 turn 内所有 role 看到一致的"相关历史"。v1/v1.5 完全没有这层。

5. **Auto-Dream 巩固**（`carenote/swarm/autoDream.ts` + `dreamCron.ts`）
   - 每天 03:00 cron 扫所有启用 `autoDreamEnabled` 的用户，过 5 道闸门（enabled / kairos / session count / scan throttle / lock）后，把当天 ENDED session 调 gpt-4o-mini 折成补丁，原子写到 memory 文件夹，作为下次 turn recall 的素材。
   - 闭环：召回把过去注入当前 → AutoDream 把当前压缩成将来。

### 3.4 为什么对 v1 和 v3 都"没感觉"是合理的

- **v1**：你对它没感觉是因为它**没在跑**。runner 已经死了，活着的只有读 helper。文档把它写成"Agent 流水线"会误导。
- **v2 (CareNote)**：你对它没感觉，可能是因为它的入口**完全没经过你熟悉的 `/sessions/...` 路由家族**——CareNote 自己另起 `/api/visits/...` 一套接口，事件流也是 SSE 而不是轮询。你看 SessionsController 看不到它，要看 `carenote.controller.ts` 才看得到。
- **v1.5**：因为前端老 `/consult` 页直接调它，并且写回的是"看得见摸得着"的 `MedicationPlan / FollowUp / FamilyDigest` 表，最容易留下印象。

---

## 总图：现在三套真实的运行状态

```
                    ┌──────────────────────────────────────────┐
                    │  Browser                                 │
                    └───┬───────────────────────────┬──────────┘
                        │ legacy /consult           │ /carenote/visit/:id
                        │                           │ (新页面)
   POST /sessions/:id/utterances       POST /api/visits/:id/realtime-events
   POST /sessions/:id/agents/run                    │
   POST /sessions/:id/team/run                      │
                        │                           │
                        ▼                           ▼
  ┌──────────────────────────────┐   ┌──────────────────────────────────┐
  │ v1.5  TeamRunner             │   │ v2  CareNoteService.ingest…      │
  │ (team/team.runner.ts)        │   │  → TranscriptAssembler           │
  │ 5-stage DAG, 8 agents,       │   │  → CodexJobQueue (per-visit)     │
  │ Blackboard 进程内             │   │  → CodexRunManager.analyzeTurn   │
  │ 模型: gpt-4o-mini             │   │     · recall (4-phase)          │
  │                              │   │     · 11 roles, 3 passes        │
  │ 写: AgentRun, MedicationPlan,│   │     · guardrail + reducer       │
  │     FollowUp, FamilyDigest   │   │     · publishToBlackboard       │
  └─────────────┬────────────────┘   │  → SubscriptionRegistry         │
                │                    │     · single_role on demand     │
                │  (读)              │ 模型: Codex SDK / CLI            │
                ▼                    │                                 │
  ┌──────────────────────────────┐   │ 写: ConsultSession.visitState,  │
  │ v1 AgentsService             │   │     CarenoteAgentRun,           │
  │ (agents/agents.service.ts)   │   │     CarenoteTask,               │
  │ runAll(): DEAD CODE,无调用方  │   │     CarenoteBlackboard,         │
  │ 只剩三个读 helper:            │   │     CarenoteMailbox             │
  │   snapshot()                 │   └──────────────────────────────────┘
  │   composeDigest()            │
  │   promoteReminderDrafts()    │
  │  (被 SessionsController 用作 │
  │   /sessions/:id/agents 等读  │
  │   接口与 reminder accept)    │
  └──────────────────────────────┘

  共享：Reminder 表（v1.5 写 DRAFT, v2 写 draft_reminders → 用户 confirm 后
        都走 POST /api/sessions/:id/reminders/accept 升级为 SCHEDULED）
```

---

## 文档需要修正的事实性错误

按当前代码核对 `cdx_multiagent.md`：

1. **§5.3 "默认走 v1 fan‑out"** — 错。`SessionsController` 的 `POST /sessions/:id/agents/run` 已经直接委派给 `TeamRunner`（v1.5），不会再调 `AgentsService.runAll`。
2. **§6 "v1 Legacy Agents"** — 实质是死代码。runner 没人调用；保留的只是 snapshot/digest/accept reminder 这三个读路径。建议改名为"Legacy 读 Helper"，或干脆把 runAll 删掉。
3. **§0 总图里"三套 Agent 流水线"** — 严格说目前只有"两条会跑的流水线 + 一组兼容性读 helper"。"三套"是历史叙事，不是当前事实。

---

## 如果想化简

如果你想让架构回到你的最初设想（"realtime → 一组 agent → 完成工作"），现在唯一需要做的是：

- 把 v1 `agents/` 里的 runner 部分（`runAll`、`runOne`、`prompts.ts` 中跟 runner 相关的常量）删掉，保留 `composeDigest`、`promoteReminderDrafts`、`snapshot` 这三个还在被调用的读 helper（或把它们抽到 `sessions/` 模块里）。
- 决定 `/consult` 老页面是不是要废弃；如果是，那 v1.5 的 `team/` 模块也可以下掉，前端只剩 `/carenote/visit/:id`。
- 这之后整个后端就是 **唯一一条 v2 主线 + Reminder 状态机**，跟你最初的想法一致。

如果你确认要做这个清理，我可以下次帮你出一个具体的删改清单。
