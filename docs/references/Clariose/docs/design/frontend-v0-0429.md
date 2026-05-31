# Clariose v0 — 前后端设计文档（2026-04-29）

> **项目代号：** Clariose（域名 `zai.gold`）
> **定位：** 医患之间的「沟通缓冲层」——把一次面诊变成一份可被反复回看、被家人理解、被时间提醒的清晰记录。
> **不是什么：** 不是医生、不开诊断、不替任何人做医疗决定。是患者一侧的「第二副耳朵」。
> **状态：** v0 已上线 https://zai.gold（无 OpenAI Key 时回退到固定 mock，仍可完整演示）。

本文档落地今天（2026-04-29）这一次完整改造的全部设计：信息架构、UI 设计令牌、Nuxt 前端组件树、NestJS 后端模块、Prisma 数据模型、OpenAI Realtime 集成、四 Agent 协作机制、部署拓扑。后续任何同类站点（医疗 / 医院 / 诊所 / 健康 SaaS）都可以按此模板直接复用。

---

## 0. 一句话产品定义

> **「医生说的每一个字，都能在你回到家时，变成一份你和家人都看得懂的清单。」**

围绕这一句，整个产品拆分为四个动作：

1. **听** — 浏览器麦克风把面诊语音通过 OpenAI Realtime API 实时转录。
2. **审** — 多 Agent 团队并行读转录稿（Reviewer / Medication / Risk / Family / Reminder）。
3. **核** — 所有 Agent 输出都是「草稿」，必须用户手动 *Accept* 才进入正式系统。
4. **续** — Accept 后，定时提醒、家属摘要、复诊待办自动落地，并记录可审计的版本链。

---

## 1. 设计语言（UI / UX 令牌）

整体风格对标 `qai.zone`（memories.ai 风格的克制式 Editorial Minimalism），并为医疗语境做了三处微调：

- **主色** 沿用「暖陶土 Clay #D9501C」——不引发紧张感，但保留行动指示力。
- **新增治愈色** 「鼠尾草 Sage #5F7A4E」——给「确认 / 已完成 / 安全」类信号用，避免医院常见的冷蓝绿。
- **风险色** 「暖琥珀 Amber #BB951E」——替代「告警红」，避免给患者制造焦虑，但仍保留视觉权重。

### 1.1 色彩令牌

| Token        | 值        | 用途                                                  |
| ------------ | --------- | ----------------------------------------------------- |
| `canvas`     | `#F6F3EC` | 页面底色，温暖亚麻                                    |
| `paper`      | `#FFFFFF` | 卡片 / 模态层                                         |
| `ink-50…950` | 9 阶灰   | 全部偏暖灰，不用冷灰；`ink-900` 是正文与标题主色      |
| `clay-500`   | `#D9501C` | 主 CTA、链接 active、品牌句号                         |
| `sage-500`   | `#5F7A4E` | 药物 chip、确认状态、`reminder = ready`               |
| `amber-400`  | `#BB951E` | 风险 follow-up、注意事项点缀                          |
| `line`       | rgba 三阶 | hairline 分隔线（soft / default / strong）            |

> 设计原则：**一画布、一墨色、一暖橙重音、一草绿轻治愈、一暖琥珀提示** —— 五条颜色规则就把整套界面收住。

### 1.2 字体与排印

| 字体                | 用途                              |
| ------------------- | --------------------------------- |
| `Instrument Serif` | Hero / 大标题 / 斜体重音          |
| `Inter`             | 正文 / 控件 / 标签                |
| `Space Grotesk`     | 品牌字（clariose.）+ 数字统计        |
| `JetBrains Mono`    | 时间戳、技术 chip、表格数字       |

排印规则：
- Hero 标题字号 `clamp(46px, 8vw, 132px)`，行高 `0.95`，字距 `-0.02em`（`tracking-editorial`）。
- `.eyebrow`（小标）：`text-[11px] uppercase tracking-[0.22em] text-ink-500`。
- 正文 `text-[14.5px] leading-relaxed text-ink-500`。
- 一切「冷感」工程信息（model id、session id、utterance count）一律 monospace + 大字距（小写或大写都做 `tracking-[0.22em]`）。

### 1.3 容器与栅格

```
.container-narrow   max-w-[920px]
.container-page     max-w-[1200px]
.container-wide     max-w-[1400px]
```

栅格使用 Tailwind 默认（4pt 节奏）。卡片圆角统一 `rounded-3xl`（24px），按钮 `rounded-full`，输入框 `rounded-2xl`。**所有卡片不使用 backdrop-blur，全部用 `paper + hairline shadow`**——这是和 qai.zone 共同的反 glassmorphism 决策，更显高级。

### 1.4 阴影与边框

- `shadow-hairline`：`0 0 0 1px rgba(11,10,9,0.08)`，所有卡片默认。
- `shadow-card`：hover 时上抬，温柔。
- `shadow-lifted`：仅 Hero 中央 orb 与首屏 CTA 用。
- `shadow-focus`：键盘聚焦环用 `0 0 0 3px rgba(217,80,28,0.20)`。

### 1.5 动效

| 动效              | 时长   | 缓动                          | 用途                         |
| ----------------- | ------ | ----------------------------- | ---------------------------- |
| `rise`            | 700ms  | `cubic-bezier(0.22,1,0.36,1)` | 滚动入场                     |
| `ringPulse`       | 2.4s   | ease-out, infinite            | 麦克风录音 / hero 状态点     |
| `breathe`         | 5s     | ease-in-out, infinite         | Hero orb 整体呼吸缩放        |
| Three.js 顶点扰动 | per-frame | 三组 sin/cos 叠加          | Hero orb 表面微涟漪          |

全部动效 **必须** 通过 `prefers-reduced-motion: reduce` 抑制——`main.css` 末尾有统一兜底，把动画时长压到 `0.001ms`。

---

## 2. 信息架构 / 路由地图

| 路由         | 角色          | 关键内容                                                         |
| ------------ | ------------- | ---------------------------------------------------------------- |
| `/`          | 公共落地页    | Hero + Three.js orb · 4 步流程 · 3 场景 · 4 Agent 介绍 · 信任 strip · CTA |
| `/login`     | 公共          | 邮箱 + 密码                                                      |
| `/register`  | 公共          | 邮箱 + 密码 + 姓名 + 角色（PATIENT / CLINICIAN / CARETAKER）     |
| `/dashboard` | 已登录        | 总览 4 项指标 + 最近 session 列表                                |
| `/consult`   | 已登录·CSR-only | **核心页**：麦克风、转录流、四 Agent 面板（详见 §4）           |
| `/reminders` | 已登录        | 已接受的用药/复诊提醒，时间轴形式                                |
| `/summary`   | 已登录        | 单 session 的家属可读摘要（数字便条）                            |

> `/consult` 通过 `nuxt.config.ts` 里的 `routeRules: { '/consult/**': { ssr: false } }` 强制纯 CSR——因为它独占麦克风、WebRTC、Three.js，是浏览器才有的能力。

布局只有一个 `default.vue`，根据路由前缀自动切换 Header 模式（落地态 / 应用态）并隐藏 Footer。

---

## 3. 前端架构（Nuxt 3 + Vue 3 + Tailwind + Three.js）

### 3.1 目录结构

```
frontend/
├── app.vue                       根 NuxtLayout + NuxtPage
├── error.vue                     404 / 500，复用同一套设计语言
├── nuxt.config.ts                SSR + 路由规则 + Google Fonts + runtimeConfig
├── tailwind.config.ts            §1 设计令牌全部落到这里
├── assets/css/main.css           CSS 变量 + 组件层 utility（btn-primary 等）
├── layouts/
│   └── default.vue               根据路径切换 Header 模式
├── pages/                        见 §2
├── components/
│   ├── BrandMark.vue             stylised "L" + dot
│   ├── SiteHeader.vue            sticky + 移动端抽屉
│   ├── SiteFooter.vue            落地页才显示
│   ├── HeroOrb.client.vue        Three.js 暖橙脉冲球
│   ├── AgentCard.vue             落地页四 Agent 卡片
│   └── consult/
│       ├── MicCapture.vue        中央麦克风按钮 + ring pulse + 音量光晕
│       ├── TranscriptStream.vue  双 speaker bubble 列表 + partial 透明气泡
│       └── AgentPanel.vue        Agent 输出卡片（slot 注入具体内容）
├── composables/
│   ├── useReveal.ts              IntersectionObserver → data-reveal
│   ├── useApi.ts                 $fetch wrapper：base + Bearer
│   ├── useAuth.ts                /api/auth/me 状态机
│   └── useRealtime.ts            §5 详解：WebRTC + Realtime 事件机
└── public/
    ├── favicon.svg               黑底 L + 暖橙圆点
    └── robots.txt
```

### 3.2 核心 composable：`useApi`

```ts
// 集中处理 base URL + Bearer 注入 + cookie 持久化
const config = useRuntimeConfig();              // -> /api
const token  = useCookie<string|null>('clariose_token', { sameSite: 'lax' });
```

提供 `get / post / patch / delete` 四个方法，组件层 100% 不需要拼路径。

### 3.3 鉴权 composable：`useAuth`

- 使用 `useState('clariose.user')` 跨组件共享当前用户。
- `refresh()` 通过 `/api/auth/me` 校验 cookie 中的 token，失效时静默清空。
- `login / register / logout` 直连后端，写入 cookie 后跳 `/dashboard`。

### 3.4 Hero Orb（`HeroOrb.client.vue`）

落地页的视觉锚点。技术决策：

- **不使用 TresJS**，直接 `import * as THREE`。理由：减少一层依赖、避免 Nuxt 模块兼容性风险，单文件 client-only 组件即可控制完整生命周期。
- 几何体：`IcosahedronGeometry(1.35, 4)`——足够多面以体现「呼吸感」，但顶点数不超 1k，移动端也流畅。
- 顶点扰动：`Math.sin(x*1.7+t*0.9) + Math.cos(y*1.9+t*0.7) + Math.sin(z*1.5+t*1.1)`，幅度 0.018，避免明显「果冻」。
- 光照：暖橙 `key light` + 鼠尾草 `rim light` + 米色 ambient。
- 外圈一个细 `TorusGeometry`，作为「正在听」的隐喻。
- `prefers-reduced-motion` 时禁用扰动与旋转，保留静态低多边形球体。

### 3.5 SSR / CSR 分配

| 页面            | 模式 | 原因                                |
| --------------- | ---- | ----------------------------------- |
| `/`             | SSR  | 首屏首词高，SEO 关键页              |
| `/login`,`/register` | SSR | 简单表单，无浏览器独占能力          |
| `/dashboard`,`/reminders`,`/summary` | SSR + 客户端 hydrate fetch | 列表受身份令牌保护，SSR 渲染壳即可 |
| `/consult/**`   | CSR  | 麦克风 + WebRTC + Three.js + 高频状态 |

---

## 4. `/consult` 页详解 —— 产品心脏

整个产品所有的价值都在这一页发生。布局：

```
┌──────────────────────────────┬──────────────────────────────┐
│  左栏（capture + transcript）│  右栏（4 Agent 面板 2×2）     │
│                              │                              │
│  ┌────────────────────────┐  │  ┌──────────┐ ┌───────────┐  │
│  │ MicCapture（中央按钮） │  │  │ Med 草稿 │ │ Risk 草稿 │  │
│  └────────────────────────┘  │  └──────────┘ └───────────┘  │
│  ┌────────────────────────┐  │  ┌──────────┐ ┌───────────┐  │
│  │ TranscriptStream       │  │  │ Family   │ │ Reminder  │  │
│  │  (doctor / patient ↕)  │  │  │ digest   │ │ draft     │  │
│  └────────────────────────┘  │  └──────────┘ └───────────┘  │
└──────────────────────────────┴──────────────────────────────┘
```

移动端单列重排：麦克风 → 转录流 → 四 Agent 纵向堆叠。

### 4.1 状态机

`useRealtime()` 暴露的统一状态：

```
idle ─tap▶ connecting ─sdp ok▶ listening ─tap▶ paused ─tap▶ listening
                       └─error──────────────────────────────▶ error
```

UI 三处会随状态变化：
- 中央按钮颜色（ink → clay → amber）
- 顶部状态文案 / chip
- 底部 monospace 状态行（utterance 计数 / session id）

### 4.2 何时触发 Agent

策略：**每累计 3 个 final utterance 触发一次** Agent fan-out，避免每句都打模型。

```ts
watch(() => rt.utterances.value.length, n => {
  if (n && n % 3 === 0) triggerAgents();
});
```

并叠加一个 6 秒轮询 `/api/sessions/:id/agents` 拉取最新快照，无 SSE 也能保证面板「最终一致」。

### 4.3 用户 *Accept* 的语义

只有 `Reminder` 卡片底部的「Accept & schedule」才会真正落地：调用 `POST /api/sessions/:id/reminders/accept`，把当前 `AgentRun.output.items` 物化为 `Reminder` 表的 `SCHEDULED` 行。其他三个 Agent（Medication / Risk / Family）输出始终只读，目的是把「医疗执行」的最后一步保留在用户拇指上。

---

## 5. OpenAI Realtime 集成（前端 + 后端）

### 5.1 鉴权与隔离

**核心原则：长寿命 OpenAI API Key 永远不出服务器。**

```
浏览器                       Clariose 后端                       OpenAI
──────                      ──────────                      ──────
POST /api/realtime/sessions
   ────────────────────────▶
                            POST /v1/realtime/sessions
                            （携带服务器 OPENAI_API_KEY）
                              ────────────────────────▶
                                                       client_secret
                              ◀────────────────────────
   { sessionId, model,
     clientSecret, expiresAt }
   ◀────────────────────────
POST /v1/realtime?model=…  （携带 ephemeral clientSecret）
   ─────────────────────────────────────────────────────▶
                        WebRTC SDP exchange
   ◀─────────────────────────────────────────────────────
```

`clientSecret` 是分钟级失效的临时凭据，泄漏可控。

### 5.2 浏览器侧：`useRealtime()` 实现要点

文件：`frontend/composables/useRealtime.ts`

1. `mintEphemeralKey()` — 同时在后端创建 `ConsultSession`（拿到稳定 sessionId）并取回 `clientSecret`。
2. `getUserMedia({ audio: true })` 取麦克风。
3. 新建 `RTCPeerConnection`，把麦克风轨注入。
4. 新建一个 data channel `oai-events`，用来收 Realtime 的事件流。
5. data channel 打开时立即发 `session.update`，配置：
   - `modalities: ['text']` —— 我们只要文字，不要模型回声。
   - `input_audio_transcription: { model: 'gpt-4o-transcribe' }` —— 启用输入转录。
   - `turn_detection: { type: 'server_vad', threshold: 0.5, silence_duration_ms: 600 }` —— 让服务端做 VAD 切句。
6. 与 `https://api.openai.com/v1/realtime?model=…` 完成 SDP offer/answer 握手。
7. 同时建立一条 `AnalyserNode` 链路读 `getByteTimeDomainData`，每 80ms 算 RMS 给麦克风按钮的「光晕」做实时缩放。

### 5.3 Realtime 事件 → 业务对象

| OpenAI 事件                                                | 我们的处理                                                                 |
| ----------------------------------------------------------- | -------------------------------------------------------------------------- |
| `conversation.item.input_audio_transcription.delta`         | 追加到 `partial`，UI 显示「半透明气泡 + 听… 闪烁圆点」                     |
| `conversation.item.input_audio_transcription.completed`     | 生成最终 `Utterance`，插入 `utterances[]`，并 `POST /api/sessions/:id/utterances`（fire-and-forget）。`speaker` 在 v0 用「奇偶交替」启发式，未来可换 diarisation。 |
| `error`                                                     | 切换到 `error` 状态，把 `error.message` 显示在橙色 banner                  |

### 5.4 配置项

后端 `.env`：

```
OPENAI_API_KEY=sk-…             # 留空 → 自动 mock（仍可演示）
OPENAI_REALTIME_MODEL=gpt-realtime  # 未来切到 gpt-realtime-1.5 / 2 只改这一行
OPENAI_AGENT_MODEL=gpt-4o-mini   # 四 Agent 共享，便宜+准+JSON 严格
```

---

## 6. 多 Agent 团队 Harness

### 6.1 团队成员（5 个，互不重叠）

| 编号 | Kind         | 单一职责                                                         | 输出形态                                                |
| ---- | ------------ | ---------------------------------------------------------------- | ------------------------------------------------------- |
| 01   | `MEDICATION` | 抽取每一种药：drug / dose / frequency / duration / note          | `MedicationPlan` 表（结构化）                           |
| 02   | `RISK`       | 标识患者/家属应追问的红旗（药物互作、过敏、含糊用法）            | `FollowUp` 表（带 severity）                            |
| 03   | `FAMILY`     | 写「厨房餐桌语言」的家属一页摘要                                 | `FamilyDigest`（markdown + 三个数组：watchFor / doTonight / followUps） |
| 04   | `REMINDER`   | 把 medication plan → 真实定时提醒草稿                            | 仅落在 `AgentRun.output`，等待用户 Accept              |
| 05   | `REVIEWER`   | 对照原话，检查另外四个 Agent 是否「过度推断 / 漏 dose / 矛盾」   | `AgentRun.output.issues[]`，未来弹 Toast               |

### 6.2 调度顺序（不是全并行，是 DAG）

```
                        ┌──────── RISK ────────┐
   transcript ─▶ MEDICATION ─▶ ┼──── FAMILY ──────────┼─▶ REVIEWER
                        └──── REMINDER ────────┘
                                  ▲
                            (依赖 medication 输出)
```

理由：
- `MEDICATION` 必须先跑完，因为 `REMINDER` 需要它的结构化结果作为输入。
- `RISK` / `FAMILY` 与 `REMINDER` 三者独立 → `Promise.all`。
- `REVIEWER` 最后看大家的成品。

### 6.3 Prompt 设计哲学（详见 `backend/src/modules/agents/prompts.ts`）

每个 Agent 都遵守同一份契约：

1. **System prompt 给死职责**：你是 X Agent，只做 X，其他不许碰。
2. **强制 STRICT JSON 输出**，并在 prompt 内附带「最小 schema 示例」。后端调用 `chat.completions.create({ response_format: { type: 'json_object' } })` 强制保证。
3. **没素材就返回空数组**，绝不允许「编造」。
4. **citations 必须能回到 transcript ms 偏移**——医生没说的话不算数。
5. 「家属摘要」prompt 里特别标注：≤350 词、第二人称、不准 catastrophise、缺信息要写「Not discussed」。

### 6.4 持久化策略

- **结构化数据**（`MedicationPlan` / `FollowUp` / `FamilyDigest`）写专表，前端容易 query。
- **Reminder 草稿**留在 `AgentRun.output`，**只有 Accept 后**才物化进 `Reminder` 表（`status = SCHEDULED`）。
- 每次 fan-out 跑前 `deleteMany({ where: { sessionId } })`，确保覆盖式更新——避免一边新增一边残留旧版本。
- 所有 Agent 调用都落 `AgentRun` 表（status / model / latency / errorMessage / output JSON），**完整可审计**。

### 6.5 Mock 回退

`OpenAiService.hasKey === false` 时走 `mock(kind)` 分支，给固定的「Lisinopril 10mg / 每天 8 点」演示数据。这让：

- 任何人 clone 仓库 `npm run build` → `pm2 reload` 立刻看得到完整 UI。
- 演示视频不依赖 API quota。
- 未来集成测试不烧钱。

---

## 7. 后端架构（NestJS + Prisma + Postgres + Redis）

### 7.1 目录结构

```
backend/
├── prisma/
│   └── schema.prisma             见 §8
├── src/
│   ├── main.ts                   helmet + global ValidationPipe + CORS
│   ├── app.module.ts             串起 7 个 module + ThrottlerModule
│   ├── common/
│   │   ├── prisma/               PrismaService（onModuleInit/destroy）
│   │   └── decorators/
│   │       └── current-user.decorator.ts
│   └── modules/
│       ├── auth/                 JWT + argon2 + Passport JWT 策略
│       ├── realtime/             mintEphemeralKey + 创建 ConsultSession
│       ├── sessions/             session 生命周期 + utterance 入库
│       ├── agents/               §6 多 Agent harness
│       ├── reminders/            CRUD + 状态切换
│       └── health/               GET /api/health
├── nest-cli.json
├── tsconfig.json
└── .env
```

### 7.2 模块依赖图

```
                  AppModule
                     │
   ┌──────┬─────────┼─────────┬─────────┬───────────┐
   ▼      ▼         ▼         ▼         ▼           ▼
 Auth  Realtime  Sessions  Agents  Reminders   Health
        │           │         ▲
        │           ▼         │
        │       SessionsService ──── 导出
        └──────────┴─────────┘
                              forwardRef → AgentsService
```

`SessionsModule` 通过 `forwardRef` 引入 `AgentsModule`，因为 `AgentsService.runAll(sessionId)` 是 fire-and-forget 触发，但 controller 又需要 `AgentsService.snapshot()` 给前端轮询。

### 7.3 全局约定

- 所有 HTTP 路径以 `/api` 为前缀（`app.setGlobalPrefix('api')`）。
- 所有受保护路由用 `@UseGuards(AuthGuard('jwt'))`。
- 所有入参用 `class-validator` DTO。
- 所有写操作走 Prisma 事务或 `upsert`，避免半成品状态。
- 出错统一抛 Nest 异常（`ForbiddenException` / `NotFoundException` / `ServiceUnavailableException`），交给 Nest 默认 Filter。

### 7.4 关键 API 表

| Method | Path                                    | 说明                                                  |
| ------ | --------------------------------------- | ----------------------------------------------------- |
| POST   | `/api/auth/register`                    | 邮箱+密码+role → JWT；patient 自动建 `Patient` 行     |
| POST   | `/api/auth/login`                       | argon2 校验 → JWT                                     |
| GET    | `/api/auth/me`                          | 拉当前用户                                            |
| POST   | `/api/realtime/sessions`                | 同时建 `ConsultSession` + 取 `clientSecret`           |
| GET    | `/api/sessions`                         | 当前用户最近 50 个 session                            |
| POST   | `/api/sessions/:id/utterances`          | 浏览器把 final utterance 推过来，幂等                 |
| POST   | `/api/sessions/:id/end`                 | 标记结束，写 durationSec                              |
| POST   | `/api/sessions/:id/agents/run`          | 手动触发 fan-out（前端每 3 句也会调一次）             |
| GET    | `/api/sessions/:id/agents`              | 拉四 Agent 当前快照（前端 6s 轮询）                   |
| GET    | `/api/sessions/:id/digest`              | 拉单 session 的家属摘要                               |
| GET    | `/api/sessions/latest/digest`           | `/summary` 默认页用                                   |
| POST   | `/api/sessions/:id/reminders/accept`    | 把 reminder 草稿物化                                  |
| GET    | `/api/reminders`                        | 列出当前用户提醒                                      |
| PATCH  | `/api/reminders/:id`                    | 切 status：scheduled / paused / done / cancelled      |
| GET    | `/api/health`                           | 探活                                                  |

### 7.5 鉴权与会话归属

- JWT 7 天有效（`@nestjs/jwt`），Secret 来自 `.env`，签算法 HS256。
- 浏览器把 token 存 `useCookie('clariose_token', { sameSite: 'lax' })`。
- 每个 session-scoped 接口都先 `ensureOwner(sessionId, userId)`——直接对比 `ownerUserId`，不允许跨账户访问别人的转录。

---

## 8. 数据模型（Prisma Schema）

完整文件见 `backend/prisma/schema.prisma`。本节给出 ER 关系与设计动机。

### 8.1 实体关系

```
User ──┬──< Patient    (one-to-one for PATIENT users)
       ├──< Clinician  (one-to-one for CLINICIAN users)
       ├──< ConsultSession  (ownerUserId)
       ├──< Reminder
       └──< AuditLog

Patient ──< ConsultSession ──┬──< TranscriptUtterance
                              ├──< AgentRun
                              ├──< MedicationPlan
                              ├──< FollowUp
                              ├──── FamilyDigest  (one-to-one)
                              └──< Reminder
```

### 8.2 关键设计决策

- **`User`、`Patient`、`Clinician` 拆开**：未来同一个 `User` 可以既是 patient 又是 caretaker；现在 v0 简化成 1:1，但表结构留好扩展位。
- **`ConsultSession.ownerUserId` 与 `patientId` 分离**：让 caretaker 可以替老人 / 子女发起 session（v1 直接放开就行）。
- **`TranscriptUtterance` 的幂等键** = `@@unique([sessionId, realtimeItemId])`：浏览器重试推同一句话不会重复。
- **`AgentRun.output` 用 `Json`**：所有 schema 演化都不需要迁移，前端按 `kind` 渲染。
- **`Reminder.status` 含 DRAFT**：严格区分「Agent 提议」与「用户接受」。
- **`MedicationPlan.citationMs`**：每条药物输出都能回到 transcript 时间戳，前端未来可点击跳读。
- **所有用户数据全部 `onDelete: Cascade` 到 `User`**：满足 GDPR / 个人数据可删除的硬约束。

### 8.3 枚举一览

```
UserRole          PATIENT | CLINICIAN | CARETAKER | ADMIN
SessionStatus     ACTIVE | ENDED | ARCHIVED
Speaker           DOCTOR | PATIENT | UNKNOWN
AgentKind         REVIEWER | MEDICATION | RISK | FAMILY | REMINDER
AgentStatus       PENDING | RUNNING | READY | ERROR
FollowUpSeverity  LOW | MEDIUM | HIGH
ReminderChannel   APP | SMS | EMAIL
ReminderStatus    DRAFT | SCHEDULED | PAUSED | DONE | CANCELLED
```

---

## 9. 端到端时序（一次完整面诊）

```
浏览器                        Clariose 后端                      OpenAI
─────                         ──────────                      ──────
1. 用户登录 ────────────────▶ /api/auth/login → JWT
2. 进入 /consult，点麦克风 ──▶ /api/realtime/sessions
                              · 创建 ConsultSession
                              · 调 OpenAI 创建 Realtime session ─▶
                              ◀── clientSecret
   ◀── { sessionId, clientSecret, model }
3. WebRTC SDP 交换 ─────────────────────────────────────────▶
   ◀──────────────────────────────────────────────────────────
4. 用户开始说话
   · OpenAI 持续发 transcription.delta / .completed
   · 浏览器把 .completed → /api/sessions/:id/utterances
5. 每 3 句 → /api/sessions/:id/agents/run
                              · MEDICATION run（同步）
                              · 并行 RISK / FAMILY / REMINDER
                              · 异步 REVIEWER
6. 前端每 6s → /api/sessions/:id/agents
   · 渲染四面板
7. 用户点 "Accept & schedule"
                              · /api/sessions/:id/reminders/accept
                              · 把草稿物化进 Reminder 表
8. 用户点 "End & review" ────▶ /api/sessions/:id/end
                              · 写 durationSec
   ◀── 跳转 /dashboard?session=…
9. /summary 渲染家属摘要
   · GET /api/sessions/:id/digest
```

---

## 10. 前后端契约（响应格式）

### 10.1 `GET /api/sessions/:id/agents`

```jsonc
{
  "medication": {
    "status": "ready",
    "items": [
      { "drug": "Lisinopril", "dose": "10 mg",
        "frequency": "Once daily, in the morning",
        "duration": "30 days, then re-evaluate",
        "note": "Reduced from 20 mg" }
    ],
    "updatedAt": "2026-04-29T10:11:12.000Z"
  },
  "risk": {
    "status": "ready",
    "items": [
      { "question": "Should I stop ibuprofen while on lisinopril?",
        "because": "NSAIDs can blunt the BP effect of ACE inhibitors",
        "severity": "MEDIUM" }
    ]
  },
  "family":    { "status": "ready", "draft": "## Today's visit …" },
  "reminders": { "status": "ready", "items": [
      { "title": "Take Lisinopril 10 mg", "drug": "Lisinopril", "dose": "10 mg",
        "cadence": "Daily at 08:00", "cron": "0 8 * * *",
        "startsOn": "2026-04-30", "endsOn": "2026-05-30", "channel": "app" }
  ]}
}
```

`status` 枚举固定 4 值：`idle | thinking | ready | error`（前端直接映射颜色与文案）。

### 10.2 `GET /api/sessions/:id/digest`

```jsonc
{
  "sessionId": "cmojt0…",
  "startedAt": "2026-04-29T08:00:00.000Z",
  "doctorName": "Dr. Patel",
  "patientName": null,
  "summaryMd": "## Today's visit …",
  "watchFor":  ["Sudden ankle swelling", "Dizziness on standing"],
  "doTonight": ["Take the new pill with dinner", "Drink an extra glass of water"],
  "followUps": ["Ask about cholesterol numbers next visit"],
  "medications": [{ "drug": "Lisinopril", "dose": "10 mg", "frequency": "…", "duration": "…" }]
}
```

---

## 11. 部署拓扑（PM2 + nginx）

详细哲学已经收录在 `docs/pm2-deploy-design.md`，本节只记产物。

```
                        Cloudflare
                            │
                            ▼
                    nginx (zai.gold:443)
                  ┌────────┴────────┐
                  ▼                 ▼
         /api/* → 4400          /* → 3300
         clariose-backend          clariose-frontend
         (NestJS, fork+1)       (Nuxt 3 SSR, fork+1)
                  │                 │
                  ▼                 ▼
                Postgres (clariose)   静态资源直出 + Nitro SSR
                Redis  (shared)
                  │
                  ▼
                OpenAI Realtime / Chat
                （服务器侧持有 long-lived key）
```

### 11.1 端口

| 服务            | 端口 | 备注                                       |
| --------------- | ---- | ------------------------------------------ |
| `clariose-backend` | 4400 | NestJS，nginx `/api/` 反代                 |
| `clariose-frontend`| 3300 | Nuxt SSR，nginx `/` 反代                   |
| Postgres        | 5432 | DB `clariose`，role `zai`                     |
| Redis           | 6379 | 与同机邻居共享，目前未配 keyPrefix（v1 加） |

### 11.2 PM2 三件套

| 文件                              | 角色                                            |
| --------------------------------- | ----------------------------------------------- |
| `ecosystem.config.cjs`            | 唯一进程清单：fork+1，env_file，kill_timeout 等 |
| `scripts/pm2-auto-reload.cjs`     | postbuild hook，build 成功就 reload             |
| `scripts/deploy.sh`               | 一条命令完成 install / migrate / build / save  |

`postbuild` 钩子写在两个 `package.json` 里：

```json
"postbuild": "node ../scripts/pm2-auto-reload.cjs clariose-backend"
"postbuild": "node ../scripts/pm2-auto-reload.cjs clariose-frontend"
```

每次 `npm run build` 成功 → 自动 `pm2 reload <app> --update-env` → 老进程不会再服务旧代码。

### 11.3 反 cluster 决策

后端写死 `exec_mode: 'fork', instances: 1`，并在 ecosystem 文件顶端注释：

> Clariose 后端持有进程内状态（consult-session 编排、agent 缓存、未来 SSE）。cluster 模式下请求会随机派发到不同 worker，导致 SSE 断链 / 缓存不命中。要扩容请先把状态外迁到 Redis/Postgres。

### 11.4 nginx 关键决策

```
add_header Permissions-Policy "camera=(), microphone=(self), geolocation=()" always;
```

`microphone=(self)` 是 `/consult` 能拿到麦克风权限的硬条件，**不能写成 `microphone=()`** 否则浏览器直接拒绝。

---

## 12. 安全 / 合规姿态

v0 是「演示级安全」，但所有不可逆决策已经按生产标准做：

- 密码：argon2id（`@node-rs/argon2` 同款算法）。
- JWT：HS256 + 强随机 secret + 7 天 TTL；未来可加 refresh-token 旋转。
- 浏览器 token：`SameSite=Lax` cookie，`httpOnly` v1 加（当前 SSR/CSR 混用所以暴露给 JS）。
- OpenAI key：long-lived 永远在服务器，浏览器只拿分钟级 client_secret。
- 麦克风：`Permissions-Policy: microphone=(self)`，且 nginx 强制 HTTPS。
- 用户数据：所有外键 `onDelete: Cascade`，删用户即删一切。
- 审计：`AgentRun` 完整记录每次模型调用的 model / token / latency / status / output。
- 医疗免责：Footer 与 README 都明示「assistive layer, not a substitute for medical care」。

未来上生产前 must-do：
1. 增加 `httpOnly` cookie + CSRF token。
2. `RemindersService` 加上 BullMQ + 真实通道（SMS/Email）发送。
3. `Reviewer` Agent 的 issues 接到 UI 弹窗。
4. PHI 加密存储（field-level）。
5. HIPAA / GDPR 合规审计与 DPA。

---

## 13. v0 已落地清单 & 后续 Roadmap

### 13.1 已落地

- [x] qai.zone 风格的暖色 Editorial 设计语言迁移到医疗语境。
- [x] Three.js Hero orb（呼吸 + 顶点扰动 + 治愈环），尊重 `prefers-reduced-motion`。
- [x] 7 个页面：landing / consult / dashboard / reminders / summary / login / register。
- [x] OpenAI Realtime WebRTC 端到端打通（mock 兜底）。
- [x] 5 Agent harness（Reviewer / Medication / Risk / Family / Reminder），STRICT JSON。
- [x] Reminder 双态（DRAFT → SCHEDULED）+ 用户 Accept 才落地。
- [x] Family Digest 持久化 + `/summary` 页面渲染。
- [x] JWT auth + argon2 + 角色三选一。
- [x] PM2 三件套：ecosystem.config.cjs / pm2-auto-reload.cjs / deploy.sh，postbuild 自动 reload。
- [x] 前后端真分离：`backend/` + `frontend/`，各自独立 npm + 独立 lockfile + 独立 postbuild。
- [x] nginx 反代上线，`Permissions-Policy: microphone=(self)`。

### 13.2 v1 Roadmap

- [ ] SSE 把 Agent 状态推流给 `/consult`（替代 6s 轮询）。
- [ ] BullMQ + Redis 真实定时调度（替换当前的 `nextFireAt` 字段）。
- [ ] Reminder 多通道：APP / SMS（Twilio）/ EMAIL（Postmark）。
- [ ] Reviewer Agent 输出走 toast，必要时打断 Accept 流程。
- [ ] diarisation 真实区分医生/患者（OpenAI Realtime 还没原生支持，可先离线 whisper-diarize）。
- [ ] 多语言（zh-CN 切换）+ i18n 字典化。
- [ ] CI（GitHub Actions）+ 自动化 e2e（Playwright）跑 §10 验证清单。
- [ ] PHI 字段级加密（envelope encryption）。
- [ ] HIPAA / GDPR DPA 与审计日志查询页。

---

## 14. 复用指南（给下一站点）

如果未来要做第二个同结构站点（例如 ywb-medical / new-clinic.io），只需要：

1. `cp -r Zai NewSite && cd NewSite`
2. 替换三处字符串：`clariose-backend / clariose-frontend / zai.gold`。
3. 选三个不冲突的端口（建议 +100 间隔）。
4. 改 `docs/pm2-deploy-design.md` 的项目名和路径。
5. 改 `nginx-…conf` 域名 + cert 路径。
6. `scripts/deploy.sh --install`。
7. `pm2 save && pm2 startup systemd -u ubuntu --hp /home/ubuntu`。

整套设计、目录、契约、令牌、PM2 模式 100% 可复用，单站点首发到上线 < 30 分钟。

---

## 15. 一段话收尾

> Clariose v0 不在比谁的模型大、谁的 UI 炫，而在解决一个所有人都遇到过的小问题：**离开诊室那一刻，你忘了医生说的一半。** 我们让那一半被听见、被审核、被翻译、被定时——但永远不替你按下「确认」按钮。这是医疗 AI 应有的克制：在患者一侧，做一副第二副耳朵。

—— 2026-04-29，Clariose v0
