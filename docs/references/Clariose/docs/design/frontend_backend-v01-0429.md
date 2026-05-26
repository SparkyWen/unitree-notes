# CareNote v0.1 — 前后端完成事项清单（2026-04-29）

本文记录本次落地的全部完成事项。范围覆盖：发现报告、设计文档、Codex-only 多智能体 harness 脚手架、Realtime 转写流水线、医疗安全收敛器、测试与运行脚本。

> 工作目录：`/home/ubuntu/Zai`
> 范围：本次只动 CareNote 模块；既有 Clariose 后端 (`modules/{auth,realtime,sessions,reminders,agents,health}`) 与前端均未改动。

---

## 1. 阶段总览

| 阶段 | 任务 | 状态 |
|---|---|---|
| Phase 0 | 仓库 + 笔记发现报告 | ✅ |
| Phase 1 | 8 篇设计文档 | ✅ |
| Phase 2a | Codex-only harness 核心脚手架 | ✅ |
| Phase 2b | Realtime + 转写事件总线 + 11 个 agent prompt | ✅ |
| Phase 2c | 安全测试 + README + npm 脚本 | ✅ |

完成度：上述全部交付物落盘并通过 `tsc --noEmit` 与 21/21 Jest 测试。

---

## 2. 设计文档（`docs/design/`）

| 文件 | 内容 |
|---|---|
| `00_repository_discovery_report.md` | Qagent / CCLearn / CDXLearn 深度发现报告：Qagent 模块图、Claude 运行时生命周期、记忆/召回管线、可复用与必弃模式、Codex SDK/CLI/app-server 实测 API、订阅鉴权可行性、推荐运行时排名、风险清单 |
| `01_carenote_product_requirements.md` | 产品定位、目标用户、就诊前/中/后用户流、做与不做、MVP 范围、成功标准、显性非目标、外部假设 |
| `02_realtime_transcript_pipeline.md` | 端到端流程图、服务端 broker、客户端 WebRTC、Realtime session config（`create_response=false` 默认）、delta/completed 处理、`previous_item_id` 排序与降级、VAD/降噪、用户触发摘要、失败模式 |
| `03_codex_only_harness_architecture.md` | 11 个 agent 角色表、`CodexRuntime` 抽象、`CodexThreadStore` / `CodexAgentRegistry` / `CodexAgentTeam` / `CodexJobQueue` / `CodexRunManager` / `CodexOutputParser` / `CodexSchemaValidator` / `CodexGuardrailReducer`、Realtime → Codex 任务映射、并发与幂等、可审计性、显性禁止行为 |
| `04_persistent_agent_team_design.md` | 团队清单格式、`codex_agent_threads` 表、JSON 镜像、幂等引导、prompt 漂移防护、长程上下文摘要、线程重置/版本化、患者记忆 vs 角色记忆防火墙、每轮 prompt 组装结构 |
| `05_medical_safety_and_privacy.md` | 三层防御（prompt + schema + reducer）、医疗安全边界、隐私边界、知情同意流程、原始音频策略、转写策略、家属共享策略、删除/导出策略、审计日志、提醒/记忆确认策略、PHI 日志策略、紧急情况重定向规则、强制免责声明 |
| `06_migration_from_claude_harness_to_codex_harness.md` | Qagent ↔ CareNote 概念映射表、保留与丢弃模式、不引入 provider 抽象、迁移阶段、移除 Claude 依赖计划、命名卫生 |
| `07_mvp_implementation_plan.md` | M0–M9 里程碑、本次 PR 任务顺序、API 端点清单、验收标准、本次范围之外项 |
| `08_testing_and_eval_plan.md` | 测试分层、10 个 fixture 描述、医疗安全 eval、无诊断 eval、无自动提醒 eval、记忆确认 eval、Realtime 排序属性测试、运行命令、未来 eval |

---

## 3. Operator README

`docs/CODEx_HARNESS_README.md`：依赖安装、Codex 订阅鉴权步骤、健康检查、引导团队、运行 mock 转写、Realtime demo（M7 占位）、运行测试、查看 agent runs、重置线程、新增 agent 角色步骤、已知限制、上线前安全 checklist。

---

## 4. Prompt 包（11 个 agent + 1 个修复）

`prompts/codex-agents/`，全部英文：

- `visit_orchestrator.md`
- `transcript_quality.md`
- `speaker_role.md`
- `medical_instruction_extractor.md`
- `medication_reminder_draft.md`
- `follow_up_task_draft.md`
- `safety_clarification.md`
- `family_summary.md`
- `memory_update.md`
- `compliance_guardrail.md`
- `final_visit_summary.md`
- `_json_repair.md`（一次性修复 prompt）

每个 prompt 都明确：禁止诊断 / 禁止开药 / 禁止推断缺失字段 / 必带 `source_turn_ids` / 草稿必须 `requires_user_confirmation=true` / 仅返回 JSON。

---

## 5. 团队清单 + 自定义 agent 配置

| 文件 | 用途 |
|---|---|
| `config/codex-teams/carenote-doctor-visit.team.json` | 团队清单（11 个角色、prompt/schema 版本、运行时偏好、`sandboxMode=read-only`、`approvalPolicy=never`、`networkAccessEnabled=false`） |
| `.codex/agents/carenote_*.toml` ×11 | 项目级 Codex 自定义 agent 配置（每角色 1 个，全部 `read-only`） |

---

## 6. TypeScript 脚手架（`backend/src/modules/carenote/`）

### Realtime 流水线
- `realtime/realtimeEventTypes.ts` — Realtime delta/completed/committed/failed 事件类型 + bus 事件类型
- `realtime/realtimeConfig.ts` — `gpt-realtime-1.5` session config builder（VAD / 降噪 / `create_response=false`）
- `realtime/transcriptAssembler.ts` — 纯类，处理 delta/completed/failed/committed，按 `previous_item_id` 重建顺序，置信度 high/medium/low
- `realtime/transcriptEventBus.ts` — 基于 RxJS `Subject` 的内存 pub/sub，留好 BullMQ 接口

### Codex harness
- `codex-harness/codexRuntime.ts` — `CodexRuntime` 接口（仅 Codex 实现）
- `codex-harness/codexSdkRuntime.ts` — 包装 `@openai/codex-sdk`，按角色缓存 `Thread`，剥离 `OPENAI_API_KEY` 默认走订阅鉴权
- `codex-harness/codexCliRuntime.ts` — 通过 `codex exec --json --sandbox read-only --output-schema` 落地的 fallback
- `codex-harness/codexAppServerRuntime.ts` — 占位（MVP 不实现 JSON-RPC 协议）
- `codex-harness/stubRuntime.ts` — 测试/无 Codex 场景的确定性 stub，保留全部安全不变量
- `codex-harness/codexRuntimeFactory.ts` — 自动选择 `codex-sdk` → `codex-cli` → `stub`，支持 `CARENOTE_CODEX_RUNTIME` 强制
- `codex-harness/codexThreadStore.ts` — JSON 文件 + 内存两个实现，键为 `(team_id, role)`
- `codex-harness/codexAgentRegistry.ts` — 启动时从清单 + prompt loader 构建
- `codex-harness/codexAgentTeam.ts` — 绑定 manifest+registry+runtime+store，提供 `ensureThreads/run/resetThread`
- `codex-harness/codexJobQueue.ts` — 内存队列，**按 visit 串行**，跨 visit 并发
- `codex-harness/codexRunManager.ts` — 编排器：Pass 1（4 个并行）→ Pass 2（4 个并行）→ guardrail → reducer
- `codex-harness/codexOutputParser.ts` — 剥 ```json``` 围栏 + JSON.parse
- `codex-harness/codexSchemaValidator.ts` — 11 个角色 Zod 复校
- `codex-harness/codexGuardrailReducer.ts` — 应用 `ComplianceGuardrailOutput`，丢被拦截项、追加必需用户确认到 `clarifying_questions`
- `codex-harness/codexPromptLoader.ts` — 按相对路径读 prompt + 缓存
- `codex-harness/codexTeamBootstrap.ts` — 幂等装配（清单校验 + 注册表 + 运行时 + 团队 + ensureThreads）
- `codex-harness/zodToJsonSchemaShim.ts` — 优先 `zod-to-json-schema`，否则手卷的最小子集

### 医疗模型
- `medical/medicalSchemas.ts` — 14 个核心 schema + 11 个 per-role 输出 schema + role→schema 映射；Zod 即真实源
- `medical/medicalReducers.ts` — `VisitStateReducer.reduceTurn`：丢弃无 `source_turn_ids` 的 fact、强制 `requires_user_confirmation=true` 与 `confirmation_status="pending"`、强制 med-missing-fields → `needs_user_confirmation`、自动合成确认任务、显式拒绝直接写入 memory
- `medical/memoryRetrieval.ts` — `confirmed_only` 检索接口 + 内存实现
- `medical/visitStateStore.ts` — 内存 `VisitState` 仓储

### Prompts 与 API
- `prompts/realtimeSessionPrompt.ts` — 患者向 Realtime 持久 prompt
- `prompts/transcriptionPrompt.ts` — ASR 提示（保留药名、剂量、复诊）
- `prompts/codexAgentPrompts.ts` — role → prompt file 路径映射
- `api/codexHarnessApi.ts` — `assembleHarness()`：装配 bootstrap+queue+manager+bus+visits+memory，并把 bus 接到 queue
- `api/health.cli.ts` — `npm run carenote:codex:health`
- `api/bootstrap.cli.ts` — `npm run carenote:codex:bootstrap`
- `api/mock-turn.cli.ts` — `npm run carenote:codex:mock-turn`
- `index.ts` — 模块统一导出

### Fixtures（`backend/src/modules/carenote/fixtures/transcripts/`）
- `fixture-1-missing-dose.json`
- `fixture-2-name-clarified.json`
- `fixture-3-followup-date.json`
- `fixture-4-patient-symptom.json`
- `fixture-5-allergy.json`

---

## 7. 测试（`backend/test/carenote/`）

| Spec | 覆盖范围 |
|---|---|
| `transcriptAssembler.spec.ts` | delta 累加、completed 触发发布、空 transcript 不发布、`previous_item_id` 链式重建、缺链兜底为 `created_at` 顺序 + 低置信 |
| `codexOutputParser.spec.ts` | ```json``` 与裸 ``` 围栏剥离、合法 JSON 解析、非法 JSON 报错 |
| `complianceGuardrailReducer.spec.ts` | 安全输出原样通过、`required_user_confirmations` 入 `clarifying_questions` 高优先级、`blocked_items` 转 `guardrail_blocked` 安全旗标 |
| `visitStateReducer.spec.ts` | 强制 `requires_user_confirmation=true`、丢弃无 `source_turn_ids` 的 fact、缺字段 → `needs_user_confirmation` + 自动确认任务、memory candidate 必带 pending |
| `teamPersistence.spec.ts` | 引导幂等、`prompt_version` / `schema_version` / `runtime` 落盘、第二次引导不重置 |
| `jsonRepairFlow.spec.ts` | 围栏 JSON 通过、不可解析连续两次 → `failed`/`invalid` 且不并入 VisitState |
| `mockTurnEnd2End.spec.ts` | 缺剂量 → 提醒 pending + 缺字段安全旗标；过敏 → memory candidate 待确认；患者主诉 ≠ 用药指示 |

测试结果：

```
Test Suites: 7 passed, 7 total
Tests:       21 passed, 21 total
Time:        ~6s
```

`tsc --noEmit -p tsconfig.json`：无报错。

---

## 8. npm 脚本（`backend/package.json`）

```jsonc
"carenote:test":              "jest test/carenote",
"carenote:codex:health":      "ts-node src/modules/carenote/api/health.cli.ts",
"carenote:codex:bootstrap":   "ts-node src/modules/carenote/api/bootstrap.cli.ts",
"carenote:codex:mock-turn":   "ts-node src/modules/carenote/api/mock-turn.cli.ts",
"carenote:realtime:dev":      "echo '...M7 占位...'"
```

新增依赖：`zod`（生产）、`jest` / `ts-jest` / `@types/jest`（开发）。`@openai/codex-sdk` 留作可选运行时依赖。

`backend/jest.config.cjs` 新增。

---

## 9. `.gitignore` 增补

```
.data/
.carenote/
codex-agent-team-state.json
.codex/auth*
.codex/sessions/
.codex/state*.sqlite
.codex/logs*.sqlite
.codex/session_index.jsonl
.env
.env.*
*.local
```

防止把 Codex 鉴权 token、本地团队状态、会话 rollout 误入仓库。

---

## 10. 关键安全不变量（已在三处强制）

1. **每条 fact 必带 `source_turn_ids`**：Zod schema `min(1)` + reducer 主动丢弃。
2. **每个草稿任务/记忆候选 `requires_user_confirmation=true` 且 `confirmation_status="pending"`**：`forceDraft()` 在 spread 之后**覆盖**字段，agent 无法 opt-out。
3. **memory 不能直写**：reducer 只接受 `memory_candidates`，`rejectMemoryWrite()` 显式拒绝。
4. **缺医嘱字段 → `needs_user_confirmation` + 自动合成确认任务**。
5. **`compliance_guardrail` 必经**：`runManager.analyzeTurn` 在 reducer 之前必须执行 guardrail；Codex 输出无效时安全 fallback 为 `is_safe=false`。
6. **沙箱 read-only + 网络禁用**：所有 CareNote agent 在 `sandboxMode="read-only"`、`networkAccessEnabled=false`、`approvalPolicy="never"`。
7. **订阅鉴权优先**：默认从子进程 env 中剔除 `OPENAI_API_KEY`，除非显式设置 `CARENOTE_CODEX_ALLOW_API_KEY=1`。
8. **PHI 日志收敛**：默认日志不含转写文本；需 `DEBUG_CARENOTE_PHI=true` 才打开。

---

## 11. 当前选型与运行时检测

`npm run carenote:codex:health` 在本机输出：

```json
{
  "runtime": "stub",
  "selection_reason": "no Codex runtime available (sdk:false, cli:false, auth:false) — falling back to stub. Run `codex login --device-auth` to enable subscription auth.",
  "detected": {
    "has_sdk": false,
    "has_cli": false,
    "has_subscription": false,
    "has_api_key_opt_in": false
  },
  "runtime_health": { "ok": true, "runtime": "stub", "auth_mode": "unknown" },
  "manifest_ok": true
}
```

部署主机执行：

```bash
codex login --device-auth                  # 一次性
npm install --save @openai/codex-sdk       # 可选
```

之后 factory 会自动切到 `codex-sdk`，`auth_mode` 变为 `chatgpt_subscription`。

---

## 12. 未在本次范围（M7+ 待办）

- 真实 Realtime broker 控制器与前端 `useRealtime` 适配。
- Prisma 迁移：`visits / transcript_turns / agent_runs / extracted_facts / draft_tasks / memory_candidates / memory_entries / codex_agent_threads`。
- NestJS 控制器：`/api/visits/...`、`/api/codex-team/...`、`/api/realtime/session`。
- 草稿确认/拒绝 UI、最终摘要 UI、记忆页。
- BullMQ 化 `CodexJobQueue`（Redis 已具备）。
- ESLint 规则：禁止 `modules/carenote/**` 引入 Claude/Anthropic/OpenAI Agents SDK/LangChain/LangGraph。
- 真 Codex 烟雾测试 (`CARENOTE_E2E=1`)。

---

## 13. 一句话总结

CareNote 的 Codex-only 多智能体 harness 已落地：11 个角色、持久化团队、Realtime 与 harness 完全解耦、医疗安全在 prompt+schema+reducer 三层强制、21/21 测试通过、健康/引导/mock-turn 三个 CLI 可直接演示，等待 M7 的 Realtime 与 API 接线即可联调真实就诊场景。
