# Clariose / Zai 后端全流程与多 Agent 通信设计文档

> 文档版本：2026‑04‑29
> 适用范围：`backend/`（NestJS 11 + Prisma 6 + PostgreSQL + OpenAI Realtime + Codex Harness）
> 目标读者：需要彻底理解后端运行机制与多 Agent 通信协议的工程师

---

## 0. 全局速览

Clariose（域名 `zai.gold`）是一个 **医生–患者沟通桥** 应用：

1. 浏览器侧通过 **WebRTC 直连 OpenAI `gpt-realtime`**，实时拿到对话转写。
2. 转写按句（utterance / turn）回传后端，后端做幂等落库。
3. 后端内置 **三套 Agent 流水线**（按演进顺序）：
   - **v1 Legacy**：5 个 Review Agent 在转写完成后做 fan‑out（`agents/`）。
   - **v1.5 Team DAG**：8 个 Agent 的有向无环图（`team/`），带阶段依赖、blackboard、SSE 流。
   - **v2 CareNote / CLARIOSE_V01**：11 个 Codex Role 的 Codex Harness（`carenote/`），带 4 层通信、记忆召回、Auto‑Dream 巩固，每一句 turn 触发一次完整流水线。
4. 产物经用户确认后写入 `Reminder / FollowUp / FamilyDigest / MedicationPlan`，提醒经 `DRAFT → SCHEDULED` 显式提升后才会真正“点亮”。

部署模型：单进程 PM2 fork（`exec_mode: 'fork', instances: 1`，禁止 cluster 化），监听 `127.0.0.1:4400`，nginx 终结 TLS 反向代理 `/api/`。

```
┌──────────────────────────────── Browser (Nuxt SSR) ─────────────────────────────────┐
│  /consult (CSR)  ──WebRTC──▶  api.openai.com  (gpt-realtime, ephemeral key)         │
│        │                                                                             │
│        │  realtime events                                                            │
│        ▼                                                                             │
│  POST /api/visits/:id/realtime-events     SSE: /api/visits/:id/events                │
└──────────────────────┬─────────────────────────────────────▲────────────────────────┘
                       │ HTTPS                              │ SSE
                       ▼                                    │
┌────────────────────────── NestJS @ 127.0.0.1:4400 (单 fork) ───────────────────────┐
│ AuthModule │ RealtimeModule │ SessionsModule │ AgentsModule(v1) │ TeamModule(v1.5) │
│                                                                                    │
│  CareNoteModule (v2)                                                               │
│   ├─ TranscriptAssembler (Realtime → turn)                                         │
│   ├─ CodexJobQueue (per-visit 串行)                                                │
│   ├─ CodexRunManager (analyze_turn / summarise / single_role)                      │
│   ├─ CodexAgentTeam ─▶ CodexRuntime (sdk / cli / app-server / stub)                │
│   ├─ Blackboard / Mailbox / SubscriptionRegistry  ← 4 层通信                       │
│   ├─ MemoryRecall (scan → sideQuery → surface → inject)                            │
│   └─ AutoDream (cron 每日巩固)                                                     │
└──────┬─────────────────────────────────────────────────┬───────────────────────────┘
       ▼                                                 ▼
   PostgreSQL                                File System (.data/carenote/…)
   (Prisma client)                           memory/users/<u>/{facts,skills,candidates}
                                             teams/<v>/inboxes/<role>.json
```

---

## 1. 进程入口与全局装配

### 1.1 `backend/src/main.ts`

启动时做的事，按顺序：

1. `NestFactory.create(AppModule)` 建立 Nest 应用。
2. `app.setGlobalPrefix('api')`：所有控制器路径自动加 `/api` 前缀。
3. 限定 `body-parser` 上限为 256 KB（防止恶意大包）。
4. `app.enableCors({...})`：生产仅同源（`APP_BASE_URL`，默认 `https://zai.gold`），开发放开为 `*`。
5. 注入全局 `ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })`：所有 DTO 必须声明字段，未声明字段被剥离，类型自动转换。
6. 注入 `ThrottlerGuard`（默认 120 req/min/IP，`X-Forwarded-For` 信任 nginx），`auth/login` 与 `auth/register` 通过装饰器再覆盖更严格的限速。
7. `await app.listen(APP_PORT, '127.0.0.1')`，仅监听 loopback。

### 1.2 `app.module.ts`

根模块依次装配：`ConfigModule.forRoot({ isGlobal: true })`、`ScheduleModule.forRoot()`（用于 AutoDream cron）、`ThrottlerModule.forRoot()`、`PrismaModule`、`AuthModule`、`RealtimeModule`、`SessionsModule`、`AgentsModule`、`TeamModule`、`RemindersModule`、`CareNoteModule`。

### 1.3 `common/prisma/prisma.service.ts`

继承 `PrismaClient`，实现 `OnModuleInit / OnModuleDestroy`：启动时 `$connect()`，关闭时 `$disconnect()`。**全应用共享同一个 PrismaClient 实例**（这就是为什么不能切 cluster 模式——内存状态会被分裂）。

---

## 2. 领域模型（Prisma Schema）

`backend/prisma/schema.prisma` 中的核心实体（仅列关键字段，完整以代码为准）：

| 表 | 角色 | 关键字段 |
|----|------|----------|
| `User` | 登录主体 | `id (cuid)`, `email @unique`, `passwordHash` (argon2id), `role` (`PATIENT/CLINICIAN/CARETAKER/ADMIN`), `displayName`, `isActive`, `lastLoginAt`, `autoDreamEnabled`, `lastDreamedAt` |
| `Patient` / `Clinician` | 用户的医患档案 | `userId @unique`，`fullName`，过敏史/既往病史 JSON 数组 |
| `ConsultSession` | 一次问诊（v2 称 visit），所有产物挂在它下面 | `id`, `ownerUserId`, `patientId`, `clinicianId?`, `status` (`ACTIVE/ENDED/ARCHIVED`), `realtimeModel`, `realtimeId`, `utteranceCount`, `summaryMd`, `language`, `consentRecorded`, `rawAudioSaved`, `visitState (Json)` |
| `TranscriptUtterance` | 一句被实时模型最终化的对白 | `sessionId`, `speaker` (`DOCTOR/PATIENT/UNKNOWN`), `text`, `startedAtMs`, `endedAtMs?`, `realtimeItemId`, `isFinal`，`@@unique([sessionId, realtimeItemId])` 用于幂等 |
| `AgentRun` | v1/v1.5 每次 Agent 执行的遥测 | `kind`, `agentId?`, `stage?`, `status`, `prompt`, `output`, `errorMessage?`, `model`, `inputTokens`, `outputTokens`, `latencyMs` |
| `MedicationPlan` | 提取的用药 | `drug, dose, frequency, duration, citationMs, approved` |
| `FollowUp` | 风险随访 | `question, because, severity, resolvedAt?` |
| `FamilyDigest` | 家属摘要（每 session 一行） | `summaryMd, watchFor[], doTonight[], followUps[]` |
| `Reminder` | 状态机 | `DRAFT → SCHEDULED → DONE/PAUSED/CANCELLED`，含 `cron`、`nextFireAt`、`channel` |
| `AuditLog` | 合规审计 | `action`, `resource`, `ip`, `detail` |
| `CarenoteTask` | v2 第 2 层：可持久化任务单 | `visitId`, `parentTaskId?`, `createdByRole`, `taskType`, `status`, `inputJson`, `outputJson?`, `blackboardKeys[]` |
| `CarenoteBlackboard` | v2 第 1 层：黑板 KV（数据库镜像） | `(visitId, key, value, writtenBy, version)` |
| `CarenoteMailbox` | v2 第 1 层：邮箱 DB 镜像 | `(visitId, recipientRole, fromRole, payloadJson, isRead, fileIndex)` |
| `CarenoteAgentRun` | v2 Codex 运行遥测 | `role, kind` (`turn/dream/json_repair`), `validationStatus`, `threadId`, `latencyMs` |
| `UserDreamLock` | v2 Auto‑Dream 互斥锁 | `userId @id`, `expiresAt`, `acquiredByPid` |

主要索引：`(ownerUserId, startedAt)`、`(patientId, startedAt)` 用于 dashboard；`AgentRun` 上 `(sessionId, kind, startedAt)` 与 `(sessionId, agentId, startedAt)` 用于按角色筛遥测。

---

## 3. 鉴权（Auth）

### 3.1 模块结构

`auth.module.ts` 配置 JWT：`expiresIn: 7d`、`issuer: "clariose"`、`audience: "clariose-web"`，密钥读 `JWT_SECRET`（≥32 字节，缺失时仅 dev 落到常量）。

### 3.2 接口

- `POST /api/auth/register`：`class-validator` 严校验 email/password/displayName/role；限速 5/h/IP；建 User 后按 role 自动建 Patient 或 Clinician。
- `POST /api/auth/login`：限速 5/min/IP；返回 `{ token, user }`。
- `GET /api/auth/me`：JWT 守卫，返回公开字段。

### 3.3 密码与 Token

- **Argon2id** 参数 `memoryCost=19MiB / timeCost=2 / parallelism=1`（约 100 ms）。对未知 email 也跑一次预计算 dummy hash 防止时序型账号枚举。登录时若参数变更触发 lazy rehash。
- JWT payload `{ sub: user.id, email, role }`，验证强制 issuer + audience 校验。
- `JwtStrategy` 同时支持 `Authorization: Bearer …` 与 `?token=…` 查询参数（SSE 用，因为 EventSource 无法发自定义 header）。

### 3.4 审计

每一次 `auth.login.ok / login.failed / login.disabled / register` 写一条 `AuditLog`，附带 `clientIp()`（优先 `X-Forwarded-For`）。

---

## 4. Realtime 接入（最敏感的一段）

### 4.1 流程

```
Browser ─POST /api/realtime/sessions(JWT)─▶ NestJS
   │                                          │
   │                                          ├─ SessionsService.create(user.id) → ConsultSession 行
   │                                          ├─ RealtimeService.mintEphemeralKey()
   │                                          │   └─ POST https://api.openai.com/v1/realtime/sessions
   │                                          │       Authorization: Bearer $OPENAI_API_KEY
   │                                          │       body: { model, modalities: ['text'], instructions }
   │                                          ├─ SessionsService.attachRealtime(sessionId, model, realtimeId)
   │                                          ▼
   │             { sessionId, model, clientSecret, expiresAt }  ← 5 分钟有效
   │
   └─WebRTC offer/answer 直连 api.openai.com（用 clientSecret 而非长寿命 key）
```

要点：长寿命 `OPENAI_API_KEY` **永不离开服务器**；浏览器只拿短寿命 client_secret，直接和 OpenAI 建立媒体通道；服务端不转发音频流，只接收前端回传的 *转写文本事件*。`OPENAI_REALTIME_MODEL` 默认 `gpt-realtime`，可经 env 覆盖。若 `OPENAI_API_KEY` 缺失，此接口返 503（v1/v2 Agent 仍可走 fixture 模式，但实时转写无法做）。

### 4.2 失败回退

`OPENAI_API_KEY` 为空时 `OpenAiService` 在 v1 Agents、CodexRuntime stub 中分别返回**确定性 fixture**，让 demo 不挂；这条双模式必须保留（CLAUDE.md 强制）。

---

## 5. 转写采集与 Session 生命周期

### 5.1 接口（`sessions.controller.ts`）

| 方法 | 路径 | 作用 |
|-----|------|------|
| GET | `/api/sessions` | 列出当前 user 的最近 50 个 session |
| POST | `/api/sessions/:id/utterances` | 入库一句最终化转写 |
| POST | `/api/sessions/:id/end` | 标记 ENDED，计算 `durationSec` |
| POST | `/api/sessions/:id/agents/run` | 触发 v1（5‑agent fan‑out）/ v1.5（8‑agent DAG）流水线 |
| GET | `/api/sessions/:id/agents` | Agent 状态快照（轮询用） |
| GET | `/api/sessions/:id/digest` | 装配 FamilyDigest 视图 |
| GET | `/api/sessions/latest/digest` | 最近一次 digest |
| POST | `/api/sessions/:id/reminders/accept` | 把 DRAFT 提醒批量提升为 SCHEDULED |

### 5.2 幂等去重

`POST /utterances` 体内携带 `realtimeItemId`，Service 调用 `prisma.transcriptUtterance.upsert({ where: { sessionId_realtimeItemId } })`。前端可放心重发（网络抖动、SSR 重试）；同时 `ConsultSession.utteranceCount` 用原子 `increment` 更新。

### 5.3 触发 Agent

`runAgents()` 内部分支：

- 若请求体或 env 标记 v2，则把请求转给 `TeamRunner`（DAG 流水线）。
- 默认走 `AgentsService.runAll()` 的 v1 fan‑out。
- v2 CareNote 的 turn 级流水线 **不在这条路径**——它由 `TranscriptAssembler` 检测到 turn 完成时由 `CodexJobQueue` 主动触发。

---

## 6. v1 Legacy Agents（`agents/`）

### 6.1 流水线

`AgentsService.runAll(sessionId)` 的执行图：

```
1. 装配 prompt 用的 transcript 文本
   "[doctor @ 1234ms] …\n[patient @ 2000ms] …"
2. MEDICATION  ─▶ 解析 JSON → MedicationPlan 表
3. 同时启动:
     RISK     ─▶ FollowUp 表
     FAMILY   ─▶ FamilyDigest 表 + ConsultSession.summaryMd
     REMINDER ─▶ AgentRun.output（不直接落 Reminder 表，等用户 accept）
                 输入里塞 MEDICATION 的输出作为依据
4. 异步、非阻塞：REVIEWER（审查 MED+RISK 是否冲突，仅写日志）
```

### 6.2 提示词（`prompts.ts`）

每个 Agent 的 prompt 都强约束 “只返回 JSON、字段语义、citationMs 必须等于真实 utterance startedAtMs、frequency 用人话不用 q.i.d.、duration 必须答出 ‘多久’、severity ∈ {LOW, MEDIUM, HIGH}、cron 5 段、PRN 跳过”等等。

### 6.3 OpenAI 客户端（`openai.service.ts`）

`OpenAiService` 包装 OpenAI Node SDK：模型默认 `gpt-4o-mini`（env `OPENAI_AGENT_MODEL` 可改），`response_format: { type: "json_object" }`。无 key → fixture 路径。每次调用记录 `inputTokens / outputTokens / latencyMs` 写回 `AgentRun`。

---

## 7. v1.5 Team DAG（`team/`）

### 7.1 8 个 Agent 与依赖

```
Stage 0:  orchestrator                          (准入门控；TOO_SHORT 即短路)
Stage 1:  transcript-verification ∥ speaker-role
Stage 2:  medical-instruction-extractor
Stage 3:  clarification-question
        ∥ medication-schedule-draft
        ∥ caregiver-notification
Stage 4:  safety-guardrail                      (审计末班车)
```

每个 Agent 在磁盘上是一个目录，结构：

```
team/
  team.json                  # DAG 清单
  <agent-id>/
    agent.md                 # 提示词
    schema.json              # 输出 JSON Schema
    meta.json                # tone / displayName / agentKind / reads / writes / stage
```

`TeamLoader`（`team.loader.ts`）启动时按 `CLARIOSE_TEAM_ROOT` / 几个候选路径定位并装载，dev 下可调用 `reload()` 热刷。

### 7.2 `TeamRunner.runInner(sessionId)`

```
1. 装配 transcript，写入 blackboard.key = "transcript.raw"
2. emit('run.started')
3. for stage in DAG:
     emit('stage.started', stage)
     await Promise.all(stage.agents.map(runAgent))
     emit('stage.finished', stage)
     if stage === 0 && orchestrator.plan.readiness === 'TOO_SHORT':
         break
4. emit('run.finished')
```

`runAgent`：读取 `reads` 指定的 blackboard 键 → 调 OpenAI（`json_object`） → 校验 schema → `persistAndPropagate()`：

- `transcript-verification` → blackboard `transcript.verified` / `transcript.lowConfidence`
- `speaker-role` → blackboard `speakers.assignments`，并**回写 TranscriptUtterance.speaker** 修正
- `medical-instruction-extractor` → blackboard + `MedicationPlan` 表
- `clarification-question` → `FollowUp` 表；HIGH + `askLive` 时额外 emit `clarification.requested`，前端 SSE 监听后通过 WebRTC data channel 注入 `response.create` 让实时模型在线提问
- `medication-schedule-draft` → blackboard 草稿
- `caregiver-notification` → `FamilyDigest`
- `safety-guardrail` → blackboard `audit.issues`

### 7.3 Blackboard & EventBus

- `Blackboard`（`blackboard.ts`）：**进程内** `Map<sessionId, Map<key, BlackboardEntry>>`。每次 `write` 把 `version` 自增，`writtenBy` 记录写入者；提供 `read / readMany / snapshot`。**单 fork 的设计前提下不需要锁**——JS 单线程串行执行。
- `EventBus`（`event-bus.ts`）：基于 RxJS `Subject<TeamEvent>`，按 `sessionId` 过滤。事件类型见上。SSE 控制器订阅 `bus.stream(sessionId)`，把 RxJS observable 映射成 `MessageEvent`，附加 15 s 心跳 interval。

### 7.4 Team Controller 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sessions/:id/team/run` | fire-and-forget，触发 DAG |
| GET | `/api/sessions/:id/team` | DAG 当前快照（每个 agent 的状态/输出/耗时） |
| GET | `/api/sessions/:id/team/manifest` | DAG 清单（前端渲染节点图用） |
| SSE | `/api/sessions/:id/team/stream` | 实时事件流 |

---

## 8. v2 CareNote / CLARIOSE_V01（重头戏）

> 这一节是「多 Agent 通信」的全部技术细节。CareNote 有 **11 个 Codex Role**、**4 层通信协议**、**记忆召回**、**Auto‑Dream 巩固**，并且 **每接收到一句 turn 就跑一次完整 11 角色流水线**。

### 8.1 模块装配（`carenote/api/carenote.module.ts`）

`CareNoteModule` providers：

- 业务层：`CareNoteService`（外观）、`CarenoteEventBus`（SSE 总线）。
- Recall 流水线 5 个类：`MemoryRecallService / MemoryScanService / MemorySideQueryService / MemorySurfaceService / RecallBudgetService / RecallCacheService`。
- 4 层通信：`InMemory/FileBackedBlackboard`、`MailboxService`、`SubscriptionRegistry`、`CarenoteEventBus`。
- Auto‑Dream：`AutoDreamService`、`DreamCronService`、`ConsolidationLockService`。

模块通过 `assembleHarness()`（`api/codexHarnessApi.ts`）把以上拼装成一个 `CareNoteHarness` 单例，注入到 `CareNoteService`。`assembleHarness` 是幂等的，子模块支持热替换（测试夹具用）。

### 8.2 Visit 接口（`carenote.controller.ts`）

所有路由 JWT 守卫。所有写接口先 `ensureOwner(visit_id, user_id)`，**用户不是 owner 直接 404**（不泄露 visit 是否存在）。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/visits` | 建 visit（要求 `consent_recorded=true`） |
| GET | `/api/visits/:visitId` | 元信息 + VisitState + 已确认任务/记忆 + 队列状态 |
| SSE | `/api/visits/:visitId/events` | 事件流（见下） |
| POST | `/api/visits/:visitId/realtime-events` | **核心入口**：把浏览器侧的 OpenAI Realtime 原始事件发回服务器 |
| POST | `/api/visits/:visitId/stage-summary` | 阶段总结（异步） |
| POST | `/api/visits/:visitId/final-summary` | 最终总结（异步） |
| POST | `/api/visits/:visitId/draft-tasks/:taskId/{confirm\|reject}` | 用户确认/拒绝草稿任务 |
| POST | `/api/visits/:visitId/memory-candidates/:cid/{confirm\|reject}` | 用户确认/拒绝记忆候选 |
| DELETE | `/api/visits/:visitId` | 软删（status → ARCHIVED） |
| POST | `/api/admin/auto-dream/run` | 仅管理员，立即触发巩固 |

### 8.3 CareNoteService 内存状态

`carenote.service.ts` 持久状态在内存里有：

```ts
visits:            Map<visitId, CareNoteVisitMeta>
confirmedTasks:    Map<visitId, Map<taskId, ConfirmedTask>>
confirmedMemories: Map<visitId, ConfirmedMemory[]>
```

冷启动通过 `hydrateVisit()` 从 `ConsultSession.visitState` 还原 VisitState，从而支撑 PM2 reload 场景。

`ingestRealtimeEvent` 是最热的代码路径：

```
ingestRealtimeEvent(visit_id, rawEvent):
  ensureOwner
  hydrateVisit if cold
  result = TranscriptAssembler.apply(rawEvent)   // 见 §8.6
  if result.emitted_turn:
      bus.emit('transcript_turn_committed', turn)
      transcriptEventBus.emit({type:'transcript_turn_completed', visit_id, turn})
  fire-and-forget: persistVisitState(visit_id)   // 把 VisitState JSON 落 ConsultSession.visitState
  return { accepted, emitted_transcript_turn, job_id, duplicate }
```

### 8.4 Codex Harness 总览

`codex-harness/` 下大约 20 个文件，分四层：

```
┌────────────────────────────────────────────────────────────────┐
│  Public façade            assembleHarness / CareNoteHarness     │
├────────────────────────────────────────────────────────────────┤
│  Orchestration            CodexRunManager (analyze_turn /       │
│                            summarise / single_role)             │
│                           CodexJobQueue (per-visit serial)      │
├────────────────────────────────────────────────────────────────┤
│  Team plumbing            CodexAgentTeam, CodexAgentRegistry,   │
│                            CodexThreadStore, CodexTeamBootstrap │
│                           CodexPromptLoader, PromptAssembler,   │
│                            GuardrailReducer                     │
├────────────────────────────────────────────────────────────────┤
│  Runtime adapters         CodexRuntimeFactory →                 │
│                            ┌─ codexSdkRuntime  (SDK，首选)      │
│                            ├─ codexCliRuntime  (子进程 fallback)│
│                            ├─ codexAppServerRuntime (占位)      │
│                            └─ stubRuntime      (CI / 演示)      │
└────────────────────────────────────────────────────────────────┘
```

### 8.5 11 个 Codex Role

`medical/medicalSchemas.ts` 里 `CodexAgentRole` 枚举：

```
visit_orchestrator
transcript_quality
speaker_role
medical_instruction_extractor
medication_reminder_draft
follow_up_task_draft
safety_clarification
family_summary
memory_update
compliance_guardrail
final_visit_summary
```

每个 role 都有：

- **Persona prompt**（`prompts/codexAgentPrompts.ts` + 可选磁盘覆盖）
- **Zod schema**（`medicalSchemas.ts` 中的 `RoleOutputSchemas[role]`）—— 用 `zodToJsonSchemaShim` 转 OpenAI strict JSON Schema
- **持久化的 Codex thread_id**（`CodexThreadStore`），同 role 跨 turn 复用 thread，使模型能自我累积上下文
- **可选订阅**（`SubscriptionRegistry`）—— 关心哪些 blackboard key / 邮件即被异步唤醒

### 8.6 Realtime → Turn 装配（`carenote/realtime/`）

`TranscriptAssembler.apply(event)` 维护 item 状态机，识别以下事件：

- `response.audio_transcript.delta` / `response.audio.delta`：累计文本
- `conversation.item.completed` / `response.content_block.completed`：item 完成
- `response.done`：回合结束
- speaker label 由 `speaker_role` agent 在事后回填

每当 turn 状态从 `in_progress → completed`，Assembler 返回 `{accepted, emitted_turn}`，CareNoteService 让 `transcriptEventBus` 发 `transcript_turn_completed`。

`assembleHarness` 把 bus → queue 串起来：

```ts
bus.on('transcript_turn_completed', t => {
  queue.enqueue({ kind: 'analyze_turn', visit_id, turn_id, transcript, previous_item_id })
})
```

### 8.7 CodexJobQueue（`codexJobQueue.ts`）

```ts
class InMemoryCodexJobQueue {
  pending: Map<visitId, CodexJob[]>
  busy:    Set<visitId>

  enqueue(job)            // 推到 visit 队列尾
  tick()                  // 对每个非 busy 的 visit shift 一个 job 执行
                          // 完成后清 busy 并递归 tick
}
```

设计要点：

- **同 visit 严格串行**（避免对同一 VisitState/blackboard 并发写）。
- **跨 visit 并行**（仅靠 Node 事件循环天然交错）。
- 任务种类：`analyze_turn`、`stage_summary`、`final_summary`、`single_role`（订阅触发）。
- 没有外部依赖，单进程单 fork 下足够；如需跨进程伸缩，先把状态搬到 Redis，再换队列实现（这是 CLAUDE.md 明确的扩展路径）。

### 8.8 CodexRunManager.analyzeTurn —— 一次 turn 的完整 11 角色流水线

下面是单次 `analyze_turn` 在 `codexRunManager.ts` 中的真实步骤（按代码顺序）：

```
analyzeTurn(job):
  visit = visitStateGet(visit_id)

  ────────────────────────────────────────
  ① Memory Recall（CLARIOSE_V01 §4，详见 §8.10）
  recall = await opts.recall?.prefetch({
      visit_id, user_id, query: transcript
  })   // 4-phase: scan → sideQuery → surface → inject
       // 每个 turn 只跑一次；所有 11 角色共享同一 RecallResult

  ────────────────────────────────────────
  ② Pass 1：可并行的“事实抽取”三连
  [tq, sr, ie] = await Promise.all([
      runRole<TranscriptQualityOutput>('transcript_quality', …),
      runRole<SpeakerRoleOutput>('speaker_role', …),
      runRole<MedicalInstructionExtractorOutput>('medical_instruction_extractor', …),
  ])

  ────────────────────────────────────────
  ③ Pass 1.5：依赖前一阶段的“澄清”
  sc = await runRole<SafetyClarificationOutput>('safety_clarification', …)
       // 接收 tq/ie 输出（ambiguities, missing_critical_fields）

  ────────────────────────────────────────
  ④ Pass 2：可并行的“决策与产物”四连
  [mr, ft, fs, mu] = await Promise.all([
      runRole<MedicationReminderDraftOutput>('medication_reminder_draft', …),
      runRole<FollowUpTaskDraftOutput>('follow_up_task_draft', …),
      runRole<FamilySummaryOutput>('family_summary', …),
      runRole<MemoryUpdateOutput>('memory_update', …),
  ])

  ────────────────────────────────────────
  ⑤ 合规护栏（compliance_guardrail）
  cg = await runRole<ComplianceGuardrailOutput>(
      'compliance_guardrail',
      envelope = { tq, sr, ie, sc, mr, ft, fs, mu }
  )

  ────────────────────────────────────────
  ⑥ Guardrail 应用：屏蔽不安全条目
  { envelope: safeEnvelope, blocked } = applyGuardrail(envelope, cg)

  ────────────────────────────────────────
  ⑦ Reducer：把 envelope 折进 VisitState
  reduced = reduceTurn(visit, safeEnvelope)
  await opts.visitStateSet(visit_id, reduced.next)

  ────────────────────────────────────────
  ⑧ 发布到 Blackboard（仅写差异，避免无谓震荡）
  if (opts.blackboard) publishToBlackboard(visit_id, safeEnvelope)
      // 写：allergies / medication_plan_draft / follow_up_tasks /
      //     safety_flags / family_brief
      // 每次 write 触发 SubscriptionRegistry.fire（见 §8.13）

  ────────────────────────────────────────
  ⑨ 遥测：onAnalyzed({ visit_state, envelope, blocked, runs })
```

`final_visit_summary`、`visit_orchestrator` 在 `summarise` / 单跑路径上调用，不在每个 turn 跑。

#### 8.8.1 `runRole<T>` 的内部步骤

```ts
async runRole<T>(role, visit_id, event, visit_state, memory_context, recall):
  ① 拉邮箱（Layer 1）
     inbox = await opts.mailbox?.drainUnread(visit_id, role)
     // [{from, text, color, summary, structured, fileIndex, timestamp}]

  ② 读黑板订阅子集（Layer 1）
     keys = opts.subscriptions?.blackboardKeysFor(role) ?? []
     blackboard = await opts.blackboard?.readMany(visit_id, keys)

  ③ 组装结构化 user message（CLARIOSE_V01 §6）
     assembled = assembleCodexPrompt({
        role, visitState, event, recall, inbox, blackboard
     })
     // 段落顺序固定：visit_context → recent_transcript →
     //   inbox → blackboard → event → expected_output_schema_name

  ④ SSE 通知：agent_run_started
     opts.eventBus?.emit({ type:'agent_run_started', visitId, role, runId })

  ⑤ 调 Codex 运行时
     out = await opts.team.run(role, {
        team_id, visit_id, role, event,
        visit_state_snapshot, memory_context,
        instructions: '',                      // role 持久 prompt 由 team.run 注入
        extra_instructions: recall?.append,    // 把召回结果以 Markdown 块追加
        pre_built_user_message: assembled.userMessage,
        expected_output_schema_name: role,
        expected_output_schema: jsonSchema
     })

  ⑥ 解析+校验+一次性修复
     result = await validateAndMaybeRepair<T>(role, out)

  ⑦ 写遥测
     await opts.recordAgentRun(agentRunRecorded)

  ⑧ SSE 通知：agent_run_completed
```

#### 8.8.2 `validateAndMaybeRepair`

- `parseCodexJson(out.raw_text)`：剥 ```json 围栏 / 容忍尾逗号 / 解析。
- 解析失败 → 调 `gpt-4o-mini`（`response_format: json_object`）做 **一次性 JSON 修复**，失败标记 `validation_status: failed`。
- 解析成功 → `validateRoleOutput(role, parsed)`（Zod `safeParse`），失败再尝试一次修复；最终标 `valid / repaired / failed`，`raw_output_preview` 保留前 400 字符。

### 8.9 Codex Runtime 抽象（`codexRuntime.ts` + 工厂 + 4 实现）

接口：

```ts
interface CodexRuntime {
  readonly name: 'codex-sdk' | 'codex-cli' | 'codex-app-server' | 'stub'
  startOrResumeThread(input): Promise<{ thread_id }>
  run(input: CodexAgentRunInput): Promise<CodexAgentRunOutput>
  healthCheck(): Promise<{ ok, runtime, auth_mode?, details? }>
}
```

`CodexAgentRunInput` 包含：`team_id, visit_id, role, thread_id?, prompt_version, schema_version, event, visit_state_snapshot, memory_context, instructions, extra_instructions, pre_built_user_message, expected_output_schema_name, expected_output_schema`。

`CodexAgentRunOutput`：`{ team_id, visit_id, role, thread_id, run_id, raw_text, parsed_json?, validation_status, errors?, started_at, completed_at, extra? }`。

`codexRuntimeFactory` 探测 `auth_mode`（`chatgpt_subscription / api_key / unknown`），按可用性顺序回退：SDK → CLI → AppServer（暂占位） → Stub。`CodexAgentTeam.ensureThreads()` 在启动期为每个 role 在 `CodexThreadStore`（`thread-state-store.json`）建/校 thread，prompt 或 schema 版本变化时自动 `reset_reason`。

### 8.10 记忆召回（4‑Phase）

`MemoryRecallService.prefetch` 是一个**异步、可超时、可预算**的子流水线，每次 `analyze_turn` 跑一次。

```
Phase 1 — Scan
  MemoryScanService.list(user_id)
    → 扫 .data/carenote/memory/users/<u>/{facts,skills,candidates}
    → 返回 ManifestEntry[]：{ relpath, size, mtime }
    → 结果走 RecallCacheService（Redis 或 in-mem，TTL = MANIFEST_CACHE_TTL_SEC，默认 300s）

Phase 2 — Side-query（让 LLM 排序）
  MemorySideQueryService.rank(manifest, query)
    → 调 gpt-4o-mini（system + manifest BM25 摘要 + query）
    → 让模型挑出 top-N 相关相对路径（默认 8）
    → 整体超时 SIDEQUERY_TIMEOUT_MS（默认 5000ms），超时即返空、skipped='timeout'

Phase 3 — Surface
  MemorySurfaceService.read(selected, budget)
    → 读文件，按 SURFACE_FILE_MAX_BYTES 截断
    → 累计字节，受 RECALL_BUDGET_BYTES_PER_VISIT 限额
    → RecallBudgetService 维护“每个 visit 累计注入字节数”

Phase 4 — Inject
  assembleAppendBlock(files):
    ### Relevant prior context
    - **<file>**: <truncated content>
    - **<file>**: …
  → 与历史注入做去重；返回 string|null

Skip 条件：
  isSubagentFork=true / 整体禁用 / no_user_id / no_visit / 空 manifest
  / sidequery_timeout / visit_budget / dedup_skipped
```

`RecallResult` 通过 `extra_instructions` 注入到所有 11 个角色的 prompt 末尾，**保证一次 turn 内所有角色看到一致的“相关历史”**。

### 8.11 4 层通信框架（CLARIOSE_V01 §3）—— 多 Agent 通信的核心

> 这是文档的核心。下面把 4 层逐一说清楚。

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 0  Events (CarenoteEventBus, RxJS Subject)                 │
│   transcript_turn_committed / agent_run_started / completed /    │
│   blackboard_updated / mailbox_message / dream_completed         │
│   订阅者：SSE 控制器、SubscriptionRegistry、CodexRunManager      │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1  共享状态                                                │
│   ┌─ Blackboard (cross-cutting KV)                               │
│   │     read / readMany / write / snapshot                       │
│   │     write 自增 version → emit 'blackboard_updated'           │
│   │     存储：内存 Map + DB 镜像 (CarenoteBlackboard)            │
│   └─ Mailbox (role-to-role 邮件)                                 │
│         真源：.data/carenote/teams/<v>/inboxes/<role>.json       │
│         DB 镜像：CarenoteMailbox（best-effort，幂等）            │
│         API：send / drainUnread                                  │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2  Tasks (CarenoteTask 表) —— 持久协作单                   │
│   pending / running / completed / failed / cancelled             │
│   parentTaskId 形成树；blackboardKeys 描述读集合                 │
│   Agents 之间从不直接“调用”，而是建 task 让 RunManager 调度     │
├──────────────────────────────────────────────────────────────────┤
│ Layer 3  Subscriptions (SubscriptionRegistry) —— 按需触发        │
│   role 订阅 onBlackboardKeys[] / onMailboxFromAnyone             │
│   bus.on(blackboard_updated|mailbox_message)                      │
│     → cooldown 2s/(visit, role) 防抖                             │
│     → hop ≤ 3 防 A→B→A 死循环                                    │
│     → 入队 single_role job → CodexRunManager.runOneRoleOnDemand  │
└──────────────────────────────────────────────────────────────────┘
```

#### 8.11.1 Blackboard

文件：`carenote/swarm/blackboard.ts`。

- 数据结构：`Map<visitId, Map<key, BlackboardEntry>>`，`BlackboardEntry = { key, value, writtenBy, version, updatedAt }`。
- `write` 仅在 JSON 序列化结果变化时落写（**节流是订阅者抗抖的核心保证**）。
- 同步写 DB（`CarenoteBlackboard`），失败 `.catch` 静默——邮箱/黑板的 DB 镜像永远是 best-effort，事件总线已经发出。
- 标准化键（CodexRunManager 会写）：`allergies / medication_plan_draft / follow_up_tasks / safety_flags / family_brief`。

#### 8.11.2 Mailbox

文件：`swarm/mailboxFile.ts` + `mailboxService.ts` + `mailboxMessages.ts`。

- 真源是磁盘 JSON：每个 role 一个 `inboxes/<role>.json`，原子追加（写 tmp 后 `rename`）。
- DB 镜像 `CarenoteMailbox` 带 `fileIndex`（在文件中的位置），便于 reconcile。
- `send(visit_id, to_role, from_role, payload, color?, summary?)`：payload 可以是自由文本，也可以是 `StructuredMessage`（结构化对象会被序列化进 `text`）。
- `drainUnread(visit_id, role)`：读未读、按 `fileIndex` 排序、批量标读、返回数组。RunManager 在 `runRole` 第 ① 步调用一次。
- 一旦 send，发出 `mailbox_message` 事件 → SubscriptionRegistry 决定是否触发对方的 `runOneRoleOnDemand`。

#### 8.11.3 Tasks

文件：`swarm/tasks.ts`。

- `CarenoteTask` 是**唯一**承载“agent 想让另一个 agent 干活”的载体。
- 任意 role 想让别的 role 跑一遍，就 `tasks.create({visit_id, createdByRole, taskType, description, inputJson, blackboardKeys})`。
- RunManager 监听 task 队列（或 SubscriptionRegistry 把 task 作为黑板写的“同义词”）将任务调度成 `single_role` job。
- task 完成后 `outputJson` 落库；前端可以基于 task 表渲染“处置面板”。

#### 8.11.4 SubscriptionRegistry

文件：`swarm/subscriptionRegistry.ts`。

- `register({ role, onBlackboardKeys?, onMailboxFromAnyone? })`：幂等。
- `registerDefaultsFor(team_roles)` 安装默认订阅（关键的耦合关系都在这里）：
  - `medication_reminder_draft` 监听 `[allergies, medication_plan_draft]`
  - `safety_clarification` 监听 `[safety_flags]`
  - `family_summary` 监听 `[family_brief, safety_flags]`
- `start(handler)` 把 bus 上的两类事件接到 `fire()`：
  - `blackboard_updated{visit, key}` → 命中订阅 → `fire({visit, role, reason: 'blackboard:'+key, hop})`
  - `mailbox_message{visit, role}` → `fire({visit, role, reason: 'mailbox', hop})`
- `fire` 内部：
  1. **冷却** —— `(visit, role)` 2 秒内只触发一次；
  2. **跳数限制** —— `hop ≤ 3`，每次扩散+1，超限 emit `cycle_breaker` 日志并丢弃；
  3. **去重** —— 同一 reason 在冷却内合并；
  4. **入队** —— `queue.enqueue({ kind:'single_role', visit_id, role, reason, hop })`；
  5. RunManager 拿到 `single_role` 后调 `runOneRoleOnDemand`（**只跑该 role、写遥测、不做 reduceTurn / 不发新黑板**——避免再次扇出造成抖动；MVP 做到这里，后续 Week 4 会让 on‑demand 也参与 reducer）。

#### 8.11.5 全图：一次 turn 引起的多 Agent 通信轨迹

```
[Realtime Δ] ──▶ TranscriptAssembler
                      │ emitted_turn
                      ▼
       transcript_turn_completed (Layer 0)
                      │ enqueue analyze_turn
                      ▼
       ┌──────────── CodexRunManager.analyzeTurn ────────────┐
       │ ① recall.prefetch (4-phase)                         │
       │ ② Pass 1   tq ∥ sr ∥ ie     ─┐                      │
       │ ③ Pass 1.5 sc                │ runRole 内部:        │
       │ ④ Pass 2   mr ∥ ft ∥ fs ∥ mu │  - drain mailbox    │
       │ ⑤ guardrail cg               │  - read blackboard  │
       │ ⑥ applyGuardrail             │  - assemble prompt  │
       │ ⑦ reduceTurn → VisitState    │  - team.run (Codex) │
       │ ⑧ publishToBlackboard ───────┘  - validate+repair  │
       │     (按键差异写)                                    │
       └─────────────────────────────────────────────────────┘
                      │
   ┌──────────────────┼──────────────────────────────┐
   ▼                  ▼                              ▼
SSE 事件流     CarenoteEventBus              Blackboard write
(浏览器)       'blackboard_updated'           ──────────────►
                  │
                  ▼
            SubscriptionRegistry
              cooldown / hop check
                  │ enqueue single_role
                  ▼
            CodexRunManager.runOneRoleOnDemand
              （仅记录、不扩散）
```

说明：**“扩散”在第二跳就被 `hop=2` 标记，第三跳后即被 cycle breaker 截断；同时第二跳的 single_role 不写黑板**——双重防止震荡。这就是 4 层通信能在「单 fork 进程 + 真实并发的 SDK 调用」前提下保持稳定的关键设计。

### 8.12 Auto-Dream（每日记忆巩固）

文件：`swarm/autoDream.ts`、`swarm/dreamCron.ts`、`swarm/consolidationLock.ts`。

5 道闸门必须全过才会跑：

1. **Enabled**：`CARENOTE_DREAM_ENABLED !== "false"`。
2. **Kairos**：`User.lastDreamedAt + MIN_HOURS_SINCE_LAST(20h) ≤ now`。
3. **Session count**：自上次 dream 之后 `≥ MIN_SESSIONS(1)` 个已 ENDED。
4. **Scan throttle**：每个 user 的 `lastScanAt + SCAN_THROTTLE_MS(10m) ≤ now`。
5. **Lock**：`ConsolidationLockService` 取 `users/<u>/.consolidation.lock` 文件锁（5 分钟过期）；DB 镜像 `UserDreamLock`，多进程也能互斥。

巩固步骤：

1. 选 `endedAt ∈ [lastDreamedAt - 1h, now)` 的 ConsultSession。
2. 每个 session 取最终 VisitState + 转写。
3. 调 `gpt-4o-mini`（最大 2000 tokens）按合并 prompt 产出补丁：`{memory_summary, rollout_summaries, skills, allergies, conditions}`。
4. 解析 → 原子 write‑backup‑then‑write 到：
   - `users/<u>/memory_summary.md`
   - `users/<u>/rollout_summaries/<visit_id>.md`
   - `users/<u>/skills/<name>.md`
   - 可选 `users/<u>/canonical_allergies.json`、`canonical_conditions.json`
5. 更新 `User.lastDreamedAt`，emit `dream_completed`。
6. 释放锁。

`DreamCronService` 用 `ScheduleModule` 的 cron（默认每天 03:00）扫描所有启用 `autoDreamEnabled` 的用户。

### 8.13 Reducer 与 VisitState

`medical/medicalSchemas.ts` 的 `VisitStateSchema`：

```ts
{
  visit_id, user_id, patient_id, language,
  turns: TranscriptTurn[],
  facts: Fact[],
  draft_reminders: ReminderDraft[],
  draft_tasks: TaskDraft[],
  draft_candidates: MemoryCandidate[],
  family_brief: FamilyBrief,
  safety_flags: SafetyFlag[],
  confirmed_tasks: { [task_id]: ConfirmedTask },
  confirmed_memories: { [cid]:  ConfirmedMemory },
  final_summary: { … }
}
```

`medical/medicalReducers.ts` 的 `reduceTurn(visit, envelope)`：

- 把抽取出的 `facts` 追加（同源 `source_turn_ids` 去重）；
- 把 `medication_reminder_draft / follow_up_task_draft / memory_update.candidates` 追加为 draft；
- 用 `compliance_guardrail.safe_output_patch` 覆写不安全字段；
- 标 `requires_user_confirmation` 的条目仍处于 pending；
- 用户确认后由 `CareNoteService.confirmTask / confirmMemory` 把 draft 升级为 confirmed。

### 8.14 提醒生命周期（与 v1 共享）

CareNote 的 `medication_reminder_draft` 输出被 reducer 折进 `draft_reminders`，**前端确认后**调用 `POST /api/sessions/:id/reminders/accept`（v1 / v2 共用此路由）→ `RemindersService` 把对应记录写入 `Reminder` 表，状态 `DRAFT → SCHEDULED`，并填 `nextFireAt`、`cron`。后续状态机：

```
SCHEDULED ──▶ PAUSED  (用户暂停)
SCHEDULED ──▶ DONE    (任务到期 / 完成)
SCHEDULED ──▶ CANCELLED (用户取消)
```

`PATCH /api/reminders/:id` 改 status；列表接口默认隐藏 DRAFT。

---

## 9. 错误处理、并发与遥测

### 9.1 单进程并发模型

- PM2 单 fork、单事件循环：所有内存共享状态（Blackboard、in-mem 队列、CareNoteService.maps）天然原子。
- Mailbox 的真源是文件，写时 `mkstemp + rename` 原子追加。
- DB 写既作为副本也作为冷启动恢复源：`ConsultSession.visitState` 是 VisitState 的快照、`CarenoteBlackboard` 是黑板镜像、`CarenoteMailbox` 是邮件镜像。
- 跨 visit 并行；同 visit 严格串行（CodexJobQueue）。
- AutoDream 跨进程互斥（DB + 文件锁双保险）。

### 9.2 失败容忍

| 失败点 | 行为 |
|--------|------|
| Codex 输出非 JSON | 一次修复 pass；仍失败 → `parsed=null, validation_status='failed'`；写遥测，流水线继续 |
| 单个 role 调用异常 | 日志 + `agent_run_failed` 事件，envelope 中该 role 缺失，guardrail 仍跑 |
| Blackboard / Mailbox DB 写失败 | `.catch` 静默；事件已通过 RxJS 总线发出，订阅者不受影响 |
| Recall 超时 | `skipped='timeout'`，append 为空，分析继续 |
| Realtime 注入 503（无 OPENAI_API_KEY） | 实时不可用；v1 / v2 Agent 仍可走 fixture 演示 |
| AutoDream 锁未拿到 | 跳过本轮，留待下次 cron |

### 9.3 关键日志

```
[recall]            visit=… turn=… latency=… files=… bytes=… selected=…
[blackboard]        publish failed visit=… turn=… err=…
[cycle_breaker]     visit=… role=… reason=… hop=…
[autoDream]         user=… picked=N elapsed=…ms patches=…
[carenote.runManager] role=… runId=… status=valid|repaired|failed
```

每条 Codex 调用都落 `CarenoteAgentRun`：`role, kind, status, validationStatus, threadId, latencyMs, prompt(裁剪), rawOutput(预览), parsedJson, errorMessage`。

---

## 10. 完整时序图（一次问诊从头到尾）

```
Browser                              NestJS                                  OpenAI / FS / DB
   │                                    │                                          │
   │ POST /api/auth/login               │                                          │
   │ ─────────────────────────────────▶ │ argon2 verify, sign JWT                 │
   │ ◀────────────────────────────── token,user                                    │
   │                                    │                                          │
   │ POST /api/visits  (consent=true)   │                                          │
   │ ─────────────────────────────────▶ │ CareNoteService.createVisit              │
   │                                    │   + ConsultSession 行                    │
   │                                    │   + harness.visits.ensure                │
   │ ◀──────── visit_id, status         │                                          │
   │                                    │                                          │
   │ POST /api/realtime/sessions        │                                          │
   │ ─────────────────────────────────▶ │ POST /v1/realtime/sessions ─────────────▶│ ephemeral key
   │ ◀──── clientSecret, expiresAt      │ ◀──── client_secret                      │
   │                                    │                                          │
   │ ── WebRTC offer/answer ─────────────────────── direct ──────────────────────▶ │ gpt-realtime
   │ ◀── transcript / audio events ───────────────────────────────────────────────│
   │                                    │                                          │
   │ POST /api/visits/:id/realtime-events (event)                                  │
   │ ─────────────────────────────────▶ │ TranscriptAssembler.apply                │
   │                                    │ persistVisitState (ConsultSession)       │
   │                                    │ bus.emit transcript_turn_completed       │
   │                                    │ queue.enqueue analyze_turn               │
   │ ◀──── { accepted, job_id }         │                                          │
   │                                    │                                          │
   │ open SSE /api/visits/:id/events    │                                          │
   │ ◀══════════════════════════════════│ agent_run_started/completed,             │
   │ ◀══════════════════════════════════│ blackboard_updated, mailbox_message      │
   │                                    │                                          │
   │                                    │ analyze_turn:                            │
   │                                    │   recall.prefetch (scan/side/surface)    │
   │                                    │   Pass1 (tq, sr, ie)        [Codex SDK] ▶│
   │                                    │   Pass1.5 (sc)              [Codex SDK] ▶│
   │                                    │   Pass2 (mr, ft, fs, mu)    [Codex SDK] ▶│
   │                                    │   guardrail cg              [Codex SDK] ▶│
   │                                    │   reduceTurn → VisitState                 │
   │                                    │   publishToBlackboard                     │
   │                                    │     ↳ Subscription fire (single_role)    │
   │                                    │                                          │
   │ POST /api/visits/:id/draft-tasks/:t/confirm                                  │
   │ ─────────────────────────────────▶ │ confirmedTasks set, reducer flag         │
   │                                    │                                          │
   │ POST /api/sessions/:id/reminders/accept                                      │
   │ ─────────────────────────────────▶ │ Reminder DRAFT → SCHEDULED, nextFireAt   │
   │                                    │                                          │
   │ POST /api/visits/:id/final-summary │ queue final_summary job                  │
   │                                    │                                          │
   │ POST /api/sessions/:id/end         │ status=ENDED, durationSec                │
   │                                    │                                          │
   │                  (T+~24h cron)     │ DreamCronService 扫用户                  │
   │                                    │ AutoDreamService.run(user)               │
   │                                    │  - 闸门 5 项                              │
   │                                    │  - gpt-4o-mini 巩固                      │
   │                                    │  - 写 .data/carenote/memory/users/<u>/   │
   │                                    │  - User.lastDreamedAt = now              │
```

---

## 11. 安全与合规

- **同源 CORS + JWT issuer/audience 校验** 防 CSRF / 跨站。
- **ValidationPipe whitelist + forbidNonWhitelisted** 阻断未知字段提权。
- **Argon2id + dummy-hash on miss** 防时序枚举。
- **限速** 全局 120/min，auth 5/min，register 5/h。
- **Visit 拥有权 ensureOwner ⇒ 404**（不泄露存在性）。
- **PHI**：`carenote/api/redactPhi.ts` 在 `CARENOTE_DEBUG_PHI_WARN=1` 时对 transcript/state 做关键字告警，仅在 dev；生产关闭。原始音频默认不存盘（`raw_audio_saved` 标记位用于将来对接独立存储）。
- **审计**：所有 auth、admin 操作写 `AuditLog`，含 `X-Forwarded-For`。

---

## 12. 多 Agent 通信框架图（一图汇总）

```
                                ┌──────────────────────────────────────┐
                                │         CarenoteEventBus (RxJS)      │
                                │  transcript_turn_committed           │
                                │  agent_run_started/completed/failed  │
                                │  blackboard_updated                  │
                                │  mailbox_message                     │
                                │  dream_completed                     │
                                └────────┬───────────────┬─────────────┘
                                         │               │
              ┌──────────────────────────┘               └──────────────────────────┐
              ▼                                                                       ▼
      SSE Controller                                                       SubscriptionRegistry
      /api/visits/:id/events                                               on(blackboard_updated|mailbox_message)
      heartbeat 15s                                                          cooldown 2s, hop ≤ 3
                                                                              │ enqueue single_role
                                                                              ▼
              ┌────────────────────────────────────────────────────┐
              │              CodexJobQueue (per-visit serial)      │
              │  analyze_turn / single_role / stage_summary /      │
              │  final_summary                                     │
              └─────────────────────┬──────────────────────────────┘
                                    ▼
              ┌────────────────────────────────────────────────────┐
              │             CodexRunManager                        │
              │  analyzeTurn:                                      │
              │    ① recall.prefetch (scan→sideQuery→surface→inj.) │
              │    ② Pass 1   transcript_quality                  │
              │                speaker_role                        │
              │                medical_instruction_extractor       │
              │    ③ Pass 1.5 safety_clarification                │
              │    ④ Pass 2   medication_reminder_draft           │
              │                follow_up_task_draft                │
              │                family_summary                      │
              │                memory_update                       │
              │    ⑤ compliance_guardrail (override / block)      │
              │    ⑥ reduceTurn → VisitState                      │
              │    ⑦ publishToBlackboard (delta-only)             │
              │  runRole<T>:                                       │
              │    drainMailbox → readBlackboard(subset) →         │
              │    assembleCodexPrompt → team.run (Codex Runtime)  │
              │    → parseCodexJson → validateRoleOutput →         │
              │      [json_repair if fail] → recordAgentRun        │
              └──┬───────────┬───────────┬───────────┬─────────────┘
                 ▼           ▼           ▼           ▼
              Mailbox    Blackboard   Tasks      VisitState (snapshot)
              ── file ── KV map ──── DB row ──── ConsultSession.visitState
              (truth)   (truth)     (truth)
                 ▲           ▲
                 │ DB mirror │ DB mirror
              CarenoteMailbox  CarenoteBlackboard

              CodexAgentTeam ──▶ CodexRuntimeFactory ──▶
                  codexSdkRuntime  (主)
                  codexCliRuntime  (子进程兜底)
                  codexAppServerRuntime (占位)
                  stubRuntime      (CI / 演示)
              CodexThreadStore: thread_id 持久化（每 role）
              CodexPromptLoader / Assembler: 角色 persona + 结构化 user message
              GuardrailReducer: cg.safe_output_patch + blocked_items 应用
```

11 个 Codex Role 与默认订阅：

```
visit_orchestrator                — 准入 / 阶段切换
transcript_quality                — ambiguities, missing_critical_fields
speaker_role                      — 说话人指派（事后回填 utterance）
medical_instruction_extractor     — facts: medication / allergy / dx / ...
safety_clarification (subscribes safety_flags)  — 当面再问
medication_reminder_draft (subscribes allergies, medication_plan_draft)  — 提醒草稿
follow_up_task_draft              — 随访任务
family_summary (subscribes family_brief, safety_flags)  — 家属摘要
memory_update                     — 跨次记忆候选
compliance_guardrail              — PHI / 安全 / 阻断
final_visit_summary               — 终结摘要（在 final_summary job 跑）
```

---

## 13. 总结

- **后端是“两条流水线 + 一条记忆主干”**：v1 fan‑out 与 v1.5 DAG 是合规演进的产物，v2 CareNote 才是生产形态。所有路径共享同一份 ConsultSession 与 Reminder 状态机。
- **多 Agent 通信靠 4 层栈**：Layer 0 事件总线广播变化；Layer 1 黑板 + 邮箱负责共享与定向消息；Layer 2 Tasks 表是“委派”这件事的唯一合法载体；Layer 3 SubscriptionRegistry 把变化转化为按需 Agent 触发，并用 cooldown + hop 限制保证收敛。
- **Codex Harness 把 11 个 role 装在一个有界并发的 turn 流水线里**：3 阶段（Pass1 / Pass1.5 / Pass2）+ 合规护栏 + reducer + 黑板写入，每次 turn 一致地完成抽取、决策、安全审计。所有运行细节都被 `CarenoteAgentRun` 记录，便于回溯与调参。
- **记忆侧** 由 `MemoryRecall`（实时召回）与 `AutoDream`（离线巩固）构成闭环：召回把过去注入当前 turn，AutoDream 把当前压缩成将来可召回的素材。
- **失败被设计成“安静地降级”**：JSON 修复一次、recall 超时即跳过、DB 镜像 best-effort、Realtime 失效仍走 fixture——这套系统的“可观测—可恢复—可演示”是同等重要的工程目标。

> 若需把 CareNote 横向伸缩，路径已经写在 CLAUDE.md：先把 Blackboard / Mailbox / JobQueue 的真源迁到 Redis（事件总线本身可继续 RxJS in‑proc，跨进程时换成 Redis Streams 或 NATS），然后才考虑 PM2 cluster；在那之前，**单 fork** 就是这套多 Agent 通信能保持可推理的边界。
