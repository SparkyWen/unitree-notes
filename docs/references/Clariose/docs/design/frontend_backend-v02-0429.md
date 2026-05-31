# CareNote v0.2 — M7 前后端联调完成事项清单（2026-04-29）

本文档记录在 v0.1（设计文档 + Codex-only harness 脚手架 + 21 个测试）基础上，
**M7：Realtime + API + Frontend 端到端打通**的全部交付物。

> 工作目录：`/home/ubuntu/Zai`
> 范围：CareNote 模块；既有 Clariose 后端 (`modules/{auth,sessions,reminders,agents,health,realtime}`) 与既有前端页面均未改动。
> 前置状态：v0.1 完成；Codex CLI 已用 ChatGPT 订阅鉴权；`carenote:test` 11 个 suite × 43 测试通过；mock-turn 在真实 Codex CLI 下产出有效 VisitState。

---

## 1. M7 总览

| 子里程碑 | 任务 | 状态 |
|---|---|---|
| M7-A | 后端 API 端点（visits / realtime / drafts / memory） | ✅ |
| M7-B | 前端 Nuxt 页面（start / record / summary） | ✅ |
| M7-C | 前端 useRealtimeVisit composable | ✅ |
| M7-D | 本地持久化（沿用脚手架 InMemory store；接口已为 Postgres 预留） | ✅ |
| M7-E | API 测试（consent / ingest / confirm / reject / delete） | ✅ |
| M7-F | redactPhi 日志助手 + 启动告警 | ✅ |
| M7-G | docs/CODEx_HARNESS_README.md 更新 | ✅ |
| M7-H | 手动 smoke test 步骤说明 | ✅ |
| 回归 | v0.1 既有 11 suite × 43 测试无回归 | ✅ |

**测试结果**：`npm run carenote:test` → **12 suites × 52 tests，全绿**（+1 suite, +9 tests）。
**类型检查**：`npx tsc --noEmit` → 干净。
**Nest 构建**：`npx nest build` → 干净，`dist/modules/carenote/api/*` 全部产出。

---

## 2. 运行时数据流

```
Mobile/Web microphone
  → OpenAI Realtime API (WebRTC, browser-side)
  → transcript delta/completed events (data channel)
  → POST /api/visits/:visitId/realtime-events
  → TranscriptAssembler.apply()
  → InMemoryTranscriptEventBus.publish()  ← 仅在 completed 时触发
  → CodexJobQueue.enqueue(analyze_turn)
  → CodexRunManager.analyzeTurn()
  → 11-role pipeline + schema validation
  → ComplianceGuardrailReducer
  → VisitStateReducer
  → InMemoryVisitStateStore.set()
  → 前端轮询 GET /api/visits/:visitId 显示
```

**关键约束（在 M7 中保留并由测试保证）：**

1. 浏览器只见 ephemeral `client_secret`，从不持有 `OPENAI_API_KEY`。
2. Realtime session config 默认 `create_response: false` / `interrupt_response: false` —— AI 不打断医生。
3. delta 事件**不**入队 Codex；只有 completed 才触发 analyze_turn。
4. 所有 medication reminders / draft tasks / memory candidates 落入
   VisitState 时强制 `requires_user_confirmation: true` &
   `confirmation_status: "pending"`。
5. 每条 fact 必须带 `source_turn_ids`；reducer 丢弃不带的。
6. 默认不保存原始音频；`raw_audio_saved=true` 仅是元数据 flag，无音频写入路径。
7. 默认对日志做 PHI redact（transcript / delta / partial_transcript 等字段）；
   `DEBUG_CARENOTE_PHI=true` 才放开，且启动时打印一次性告警。

---

## 3. 后端 — 新增/修改文件

### 新增（`backend/src/modules/carenote/api/`）

| 文件 | 作用 |
|---|---|
| `redactPhi.ts` | 中央 PHI 脱敏函数；`isPhiDebugEnabled()`；`assertPhiDebugWarningPrinted()` 一次性启动告警 |
| `carenote.service.ts` | `CareNoteService` 单例：harness 懒加载、visit 元数据存储（consent/raw_audio/status）、ingest、mintRealtimeSession、stage/final summary、confirm/reject draft tasks、confirm/reject memory candidates、deleteVisit、`waitForQueueIdle()` |
| `carenote.controller.ts` | `CareNoteVisitsController` —— 全部 `/api/visits/*` 路由，DTO 校验 |
| `carenoteRealtime.controller.ts` | `CareNoteRealtimeController` —— `POST /api/realtime/session`（与既有 Clariose `/realtime/sessions` 路径不冲突） |
| `carenote.module.ts` | NestJS module wiring |

### 新增（`backend/test/carenote/`）

| 文件 | 作用 |
|---|---|
| `carenoteApi.spec.ts` | 9 个集成测试，直接驱动 `CareNoteService`，覆盖所有 M7-E 场景 |

### 修改

| 文件 | 修改 |
|---|---|
| `backend/src/app.module.ts` | 注册 `CareNoteModule` |
| `backend/src/modules/carenote/index.ts` | 导出 `CareNoteModule` / `CareNoteService` / `redactPhi` / `isPhiDebugEnabled` |

---

## 4. 后端 — API 端点（全部已实现）

所有路由挂在 `main.ts` 的全局 `api` 前缀下。Body 走 `ValidationPipe(whitelist:true, transform:true)`。
M7 MVP 不挂 JWT（trusted client + nginx 终结）；M8 接入用户模型后再加 `AuthGuard('jwt')`。

| Method | Path | DTO / 行为 |
|---|---|---|
| POST | `/api/visits` | `{user_id, patient_id?, language?, consent_recorded:true, raw_audio_saved?}`；`consent_recorded !== true` → 400；返回 `{visit_id, status:"active"}` |
| GET | `/api/visits/:visitId` | 返回 `{meta, state, confirmed_tasks, confirmed_memories, job_status, transcript_stats}` |
| POST | `/api/realtime/session` | `{visit_id, mode:"doctor_visit"}`；校验 visit 存在 + active + 同意；调 OpenAI `/v1/realtime/sessions`；返回 `{visit_id, client_secret, expires_at, model:"gpt-realtime-1.5", config}` |
| POST | `/api/visits/:visitId/realtime-events` | `{event:RawRealtimeEvent}`；走 `TranscriptAssembler.apply`；completed 才 publish；返回 `{accepted, emitted_transcript_turn, job_id}` |
| POST | `/api/visits/:visitId/stage-summary` | `{last_n_turns?:1..200, mode?}`；入队 `stage_summary` job；HTTP 202 |
| POST | `/api/visits/:visitId/final-summary` | 标记 visit ended；入队 `final_summary` job；HTTP 202 |
| POST | `/api/visits/:visitId/draft-tasks/:taskId/confirm` | 在 `draft_tasks` / `draft_reminders` 里查找 → 移除 → 写入 `confirmedTasks` 桶 |
| POST | `/api/visits/:visitId/draft-tasks/:taskId/reject` | 直接从 drafts 中移除 |
| POST | `/api/visits/:visitId/memory-candidates/:candidateId/confirm` | 创建 `ConfirmedMemory`，写入 `confirmedMemories` + 注入 `InMemoryMemoryRetrievalService.add` 让后续 turn 可召回 |
| POST | `/api/visits/:visitId/memory-candidates/:candidateId/reject` | 从 `memory_candidates` 中移除 |
| DELETE | `/api/visits/:visitId` | 标记 deleted + 清空 visit state / drafts / confirmed / memory candidates；HTTP 204 |

### Realtime session config（M7 锁死的安全默认）

```ts
{
  type: "realtime",
  model: "gpt-realtime-1.5",
  output_modalities: ["text"],
  audio: {
    input: {
      transcription: {
        model: "gpt-4o-transcribe",
        language: "zh",                   // 默认；"en" / "mixed" 客户可选
        prompt: TRANSCRIPTION_PROMPT,     // 偏置医学词汇 + 禁止改写
      },
      noise_reduction: { type: "near_field" },
      turn_detection: {
        type: "server_vad",
        threshold: 0.5,
        prefix_padding_ms: 300,
        silence_duration_ms: 700,
        create_response: false,            // ★ AI 不自动响应
        interrupt_response: false,         // ★ AI 不打断医生
      },
    },
    output: { voice: "marin" },           // 配置但不触发
  },
  include: ["item.input_audio_transcription.logprobs"],
  instructions: REALTIME_SESSION_PROMPT,
}
```

---

## 5. 前端 — 新增文件

### 路由 / 页面

| 文件 | 路由 | 作用 |
|---|---|---|
| `frontend/pages/carenote/index.vue` | `/carenote` | 同意书 + 语言选择 + raw_audio toggle + Start visit |
| `frontend/pages/carenote/visit/[id].vue` | `/carenote/visit/:id` | 实时录音页：连接状态、麦克电平、partial transcript、完成 turn 卡片、提取的 facts、draft reminder cards、follow-up tasks、clarifying questions、safety flags；Start / Pause / Resume / Stage Summary / What should I ask? / End visit 按钮 |
| `frontend/pages/carenote/visit/[id]/summary.vue` | `/carenote/visit/:id/summary` | 终极摘要页：plain-language summary、medications、follow-up tasks、questions to ask、family summary（可复制）、memory candidates（确认/拒绝按钮）、safety flags、Delete visit data |

### Composables

| 文件 | 职责 |
|---|---|
| `frontend/composables/useCareNote.ts` | `createVisit / getVisit / stageSummary / finalSummary / confirmTask / rejectTask / confirmMemory / rejectMemory / deleteVisit` 类型安全包装 |
| `frontend/composables/useRealtimeVisit.ts` | 申请麦克权限、建 `RTCPeerConnection`、附麦克轨、建 data channel、SDP 交换、监听 `committed / delta / completed / failed / speech_started / speech_stopped / error`、维护本地 `partial / turns` 反应式状态、把所有事件 forward 到 `/api/visits/:id/realtime-events`；`onBeforeUnmount` 自动 stop |

### 组件

| 文件 | 作用 |
|---|---|
| `frontend/components/carenote/Panel.vue` | 通用 Panel 容器（标题 + 空状态文案 + slot） |

### 配置

| 文件 | 修改 |
|---|---|
| `frontend/nuxt.config.ts` | `routeRules: { '/carenote/**': { ssr: false } }` —— mic 捕获页强制 client-only |

**说明：** 前端使用 `useApi()` 走 `NUXT_PUBLIC_API_BASE`（默认 `/api`），与既有 consult 流量共用 nginx 终结。OpenAI key 不进浏览器；只有 ephemeral `client_secret`（由 `/api/realtime/session` 中转）会走到 `api.openai.com`。

---

## 6. 测试 — 新增 9 个集成测试

文件：`backend/test/carenote/carenoteApi.spec.ts`，运行：`npm run carenote:test`。

| # | 测试名 | 覆盖 |
|---|---|---|
| 1 | POST /api/visits requires consent_recorded=true | consent 开关；`BadRequestException` 路径 |
| 2 | POST /api/realtime/session rejects deleted/ended visits | visit 状态机；`ConflictException` |
| 3 | realtime-events: delta does not enqueue codex job, completed does | `emitted_transcript_turn` 标志；queue 计数；stub harness 完整 11-role 跑完 |
| 4 | confirm draft task moves it from pending → confirmed and out of drafts | draft → confirmed 桶迁移 |
| 5 | reject draft task removes it without creating a confirmed entry | reject 路径 + 二次 confirm 抛 NotFound |
| 6 | memory candidate confirm creates a confirmed memory; reject does not | confirm 创建 `mem-*` id；从 candidates 中移除；二次 confirm 抛 NotFound |
| 7 | DELETE visit removes local visit state entirely | delete 后 GET 抛 NotFound |
| 8 | ingestRealtimeEvent on a non-active visit is rejected | ended 后 ingest 抛 ConflictException |
| 9 | buildSessionConfig honours create_response=false and interrupt_response=false | 安全默认不被静默改回 |

测试使用 `forceStub` 装载 harness，无需 Codex CLI / 网络。

**回归**：v0.1 的 11 个 suite × 43 测试全部继续通过。

---

## 7. 隐私 / PHI

`redactPhi(input)` 规则（默认开启）：

- 删除字段：`transcript / delta / partial_transcript / text / content / raw_text / logprobs / raw_events`，替换为 `[redacted:N]`（N=原字符串长度）。
- 保留字段：事件类型、`item_id`、`visit_id`、时间戳、其他结构化标量。

`DEBUG_CARENOTE_PHI=true` 时：

- 透传不脱敏。
- `CareNoteService` 构造时调用 `assertPhiDebugWarningPrinted(logger)`，logger 输出
  `DEBUG_CARENOTE_PHI=true — transcript content WILL be written to logs. Local development only.`，每个进程仅打印一次。

测试期间已在 stdout 看到正确脱敏：`{"type":"…delta","item_id":"i1","delta":"[redacted:2]"}`。

**音频**：`raw_audio_saved` 默认 false；目前 harness 没有任何音频写入路径，开关只是承诺。

---

## 8. docs/CODEx_HARNESS_README.md 更新点

- §7 「Run a Realtime demo」从 stub 描述改写为完整 M7 wiring：流程图、API 表、安全默认表、前端清单、运行命令。
- §13 新增「M7 manual smoke test」13 步（含麦克 zh 种子句子 *"这个药每天饭后吃一次，连续吃三天。"*）。
- §14 新增「Privacy & PHI redaction」章节：脱敏规则、`DEBUG_CARENOTE_PHI` 开关、警告与禁用范围。
- §12 「Known limitations」更新：去掉「broker is a stub」「Realtime client wiring is M7 work」；改为标注 M8 待办（Postgres 化、SSE）。

---

## 9. 手动 smoke test（M7-H）

```bash
# Terminal 1 — 后端
cd backend
npm install
npm run carenote:codex:health
npm run carenote:codex:bootstrap
npm run dev               # nest start --watch — 监听 127.0.0.1:4400

# Terminal 2 — 前端
cd frontend
npm install
npm run dev               # nuxt dev — 监听 :3300
```

操作顺序：

1. 打开 `http://localhost:3300/carenote`。
2. 勾选 consent，选 `中文`，**Start visit**。
3. 落到 `/carenote/visit/<id>`，点 **Start recording**，授予麦克权限。
4. 说出种子句子：「这个药每天饭后吃一次，连续吃三天。」
5. 1 秒内 `partial transcript` 显示，几秒后完成 turn 卡片落地。
6. 「Codex queue」`pending · running` 计数应短暂上升再回零。
7. 「Draft medication reminders」面板出现一张卡，`missing: dose` 黄色徽章。
8. 「Safety flags」面板出现 `missing_dose` 红色卡。
9. 点 **End visit** → 跳转 summary。
10. 在 summary 页：confirm 一个 draft task → 卡片移到绿色「✓」区；reject 一个 → 消失；
    save 一个 memory candidate → 写入 confirmed memory；点 Copy family summary 验证剪贴板。
11. （可选）**Delete visit data** → 回 `/carenote`；GET `/api/visits/<id>` 应返回 404。

无麦克替代方案（CI 友好）：

```bash
npm run carenote:codex:mock-turn -- backend/src/modules/carenote/fixtures/transcripts/fixture-1-missing-dose.json
```

---

## 10. 不受影响的既有约束（持续保护）

- **不引入** Claude SDK / Anthropic SDK / OpenAI Agents SDK / LangChain / LangGraph。
- 模型保持 `gpt-5.5`（manifest），`gpt-5-codex` 不回退。
- OpenAI 严格 schema 兼容 (`openAiStrictSchema.ts`) 对每个输出 schema 启用。
- Realtime 不直接调 Codex —— transcript 通过 `TranscriptEventBus` 异步喂给 Codex harness。
- 单 backend 进程 + PM2 fork 模式（`ecosystem.config.cjs` 不变）。
- VisitStateReducer 仍然是状态写入唯一入口；guardrail 仍然在 reducer 之前应用。

---

## 11. 已知边界 / 后续 (M8 候选)

| 项 | 现状 | M8 计划 |
|---|---|---|
| 持久化 | `InMemoryVisitStateStore` + `Map<visit_id, ConfirmedTask>` 进程内 | Prisma schema：`Visit`、`Turn`、`Fact`、`DraftTask`、`Reminder`、`MemoryCandidate`、`ConfirmedMemory`、`AgentRun` |
| 推送 | 前端 1.5–2s 轮询 `/api/visits/:id` | SSE 频道 `GET /api/visits/:id/stream` |
| 鉴权 | 无 JWT；`user_id` 从 body 直传 | `AuthGuard('jwt')` + 用户/visit 归属校验 |
| job_id | 字符串关联键，不可索引 | BullMQ + Redis；`/api/visits/:id/jobs/:jobId` |
| 音频 | 无写入路径 | 视产品决定是否落 S3-style 对象存储 + retention TTL |
| 记忆召回 | `InMemoryMemoryRetrievalService` 子串匹配 | Postgres + embedding |
| 前端测试 | 暂无运行器 | 加入 Vitest + Vue Test Utils |

---

## 12. 文件清单（M7 增量）

```
backend/src/modules/carenote/api/redactPhi.ts                  # NEW
backend/src/modules/carenote/api/carenote.service.ts           # NEW
backend/src/modules/carenote/api/carenote.controller.ts        # NEW
backend/src/modules/carenote/api/carenoteRealtime.controller.ts # NEW
backend/src/modules/carenote/api/carenote.module.ts            # NEW
backend/src/modules/carenote/index.ts                          # MOD
backend/src/app.module.ts                                       # MOD
backend/test/carenote/carenoteApi.spec.ts                      # NEW
frontend/composables/useCareNote.ts                            # NEW
frontend/composables/useRealtimeVisit.ts                       # NEW
frontend/components/carenote/Panel.vue                         # NEW
frontend/pages/carenote/index.vue                              # NEW
frontend/pages/carenote/visit/[id].vue                         # NEW
frontend/pages/carenote/visit/[id]/summary.vue                 # NEW
frontend/nuxt.config.ts                                        # MOD
docs/CODEx_HARNESS_README.md                                    # MOD
docs/design/frontend_backend-v02-0429.md                       # NEW (this file)
```

---

## 13. 一句话验收

> M7 完成：浏览器麦克 → OpenAI Realtime → 后端 ingest → Codex 11-role harness → VisitState → 前端 UI 端到端联通；52/52 测试绿；安全默认（不打断、不诊断、所有 reminder/记忆需 confirm、PHI 默认脱敏）由 schema + reducer + 测试三层共同守住。
