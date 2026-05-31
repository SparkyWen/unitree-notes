# Codex Harness 机制完整拆解：哪些 Codex 已经做了，哪些需要你自己做

> 适用目标：Hackathon demo 阶段优先使用 **Codex OAuth / ChatGPT subscription** 作为本地 execution harness 的核心大脑；正式产品化时再迁移或补充 OpenAI Responses API / Agents SDK / MCP / 自研业务 runtime。
>
> 当前判断基于 OpenAI 官方 Codex / Agents 文档，检索日期：2026-04-28。

---

## 0. 一句话结论

如果你的目标只是黑客松 demo，并且 demo 重点是：

- 本地执行；
- 读取/修改项目文件；
- 自动生成 SME 业务工作流；
- 自动创建页面、脚本、模板、报告；
- 展示“AI 不只是聊天，而是能把业务意图转成可执行系统”；

那么可以把 **Codex** 当成已经封装好的底层 agent harness，不需要你从零做：

- OAuth / subscription 登录；
- 模型调用；
- coding agent loop；
- 本地 repo 上下文读取；
- 文件修改；
- shell 命令执行；
- sandbox；
- approval；
- MCP 接入；
- CLI / exec / app-server / SDK 等调用接口。

但是你仍然必须自己做 **业务 harness**：

- SME 场景定义；
- 输入表单和业务意图解析；
- 工作流拆解；
- prompt / AGENTS.md / skill 设计；
- 业务工具连接；
- session 与结果管理；
- 业务审批；
- 输出物结构化；
- demo UI；
- 评委能看懂的故事线。

最准确的技术定位是：

```text
Codex = 底层 execution harness / coding-agent harness
你自己做 = SME product harness / business workflow harness
```

---

## 1. Harness 到底是什么？

在 AI Agent 产品里，**harness** 不是单个 SDK，也不是一个 prompt。它是一整套让模型变成“能持续执行任务的系统”的外壳。

一个完整 harness 通常包含 18 层：

| 层级 | Harness 步骤 | 核心问题 |
|---:|---|---|
| 1 | Authentication | 谁在使用模型？用 subscription、API key 还是 workspace 权限？ |
| 2 | Model access | 如何调用模型、选择模型、处理模型限制？ |
| 3 | Runtime shell | 模型是否能执行命令、读写文件、调用工具？ |
| 4 | Context loading | 模型怎么知道当前项目、文件、业务资料？ |
| 5 | Instruction layer | 系统规则、项目规则、任务规则在哪里定义？ |
| 6 | Agent loop | 模型如何“思考 → 行动 → 观察 → 再行动”？ |
| 7 | Tool registry | 有哪些工具？工具 schema 和权限如何暴露？ |
| 8 | Sandboxing | 模型的操作边界在哪里？哪些文件/命令/网络不能碰？ |
| 9 | Approval policy | 哪些动作必须先问人？ |
| 10 | State / session | 多轮任务如何继续？历史如何保存？ |
| 11 | Memory | 哪些信息要长期复用？哪些只是一次性上下文？ |
| 12 | Error recovery | 命令失败、文件冲突、依赖缺失时怎么办？ |
| 13 | Output schema | 最终结果如何结构化，如何给 UI 和用户使用？ |
| 14 | Streaming / events | 过程如何实时展示？ |
| 15 | Trace / observability | 每一步工具调用和决策如何记录？ |
| 16 | Evaluation | 怎么判断 agent 做得好不好？ |
| 17 | Cost / quota | 如何控制 credits、调用频率和上下文大小？ |
| 18 | Product workflow | 如何把所有能力包装成用户能理解的产品流程？ |

**Codex 已经覆盖的是底层 agent execution harness。** 你要补的是产品和业务层 harness。

---

## 2. 总览：Codex 已做 vs 你需要做

| Harness 模块 | Codex 是否已做 | 你是否还要做 | 对你 Hackathon demo 的建议 |
|---|---:|---:|---|
| ChatGPT / Codex OAuth 登录 | ✅ 已做 | ❌ 不要重做 | 直接用 `codex login --device-auth` 或 `codex login`。 |
| Subscription / API key 双认证 | ✅ 已做 | ❌ 不要重做 | Demo 用 ChatGPT subscription；CI/生产自动化再考虑 API key。 |
| 登录态缓存 | ✅ 已做 | ⚠️ 只需保护 | 不要把 `~/.codex/auth.json` 上传、提交、暴露。 |
| 模型调用 | ✅ 已做 | ❌ 不要重做 | 不要自己封装底层模型请求。 |
| Prompt caching / context optimization | ✅ 平台侧/模型侧已有部分能力 | ⚠️ 你要优化 prompt 结构 | 不需要自己做缓存引擎，但要把稳定规则放在固定位置。 |
| Repo 读取 | ✅ 已做 | ⚠️ 要控制工作区 | 在 demo repo 内运行 Codex，别让它扫无关目录。 |
| 文件修改 | ✅ 已做 | ⚠️ 要定义允许修改范围 | 建议输出都写到 `/outputs`、`/generated`、`/workflows`。 |
| Shell 命令执行 | ✅ 已做 | ⚠️ 要限制危险命令 | 用 sandbox 和 approval policy。 |
| Sandbox | ✅ 已做 | ⚠️ 要配置策略 | 默认安全，但 demo 前要明确允许哪些操作。 |
| Approval | ✅ 已做 | ⚠️ 要设置业务审批点 | 文件/命令审批 Codex 做；业务动作审批你做。 |
| MCP client | ✅ 已做 | ⚠️ 你配置具体 MCP server | 可接浏览器、Figma、docs、数据库、你自己的 SME tools。 |
| Codex as MCP server | ✅ 已做 | ⚠️ 如要 Agents SDK 编排才需要 | 纯 Codex demo 可不接；高级 demo 可接。 |
| Skills / plugins | ✅ 有机制 | ✅ 你要写 SME skills | 写 `sme-operator`、`weekly-report`、`customer-reply` 等技能。 |
| AGENTS.md / instructions | ✅ 有机制 | ✅ 必须写 | 这是你控制 Codex 行为的核心。 |
| App-server streamed events | ✅ 有接口 | ⚠️ 高级 UI 才需要 | 如果时间紧，用 CLI stdout；如果要炫技，用 app-server。 |
| 多 agent 编排 | ⚠️ Codex 可做单 agent/会话，Agents SDK 更强 | ✅ 如果要稳定多角色 | Demo 可以用 prompt 模拟多角色；严肃编排用 Agents SDK。 |
| 业务输入 schema | ❌ 未做 | ✅ 必须做 | SME 用户输入、业务类型、痛点、数据源、目标。 |
| SME 业务流程库 | ❌ 未做 | ✅ 必须做 | 这是项目差异化核心。 |
| 业务数据连接 | ❌ 未做 | ✅ 必须做/可 mock | Demo 可先用 CSV/JSON/mock data。 |
| 业务审批与合规 | ❌ 未做 | ✅ 必须做 | 例如发邮件、改日程、改报价前必须 human approval。 |
| 最终 demo UI | ❌ 未做 | ✅ 必须做 | 让评委看到“输入 → 过程 → 产物”。 |
| 用户/组织/计费 | ❌ 未做 | ❌ Demo 可不做 | 正式产品再做。 |

---

## 3. 官方能力边界：Codex 已经提供了哪些底层 harness 能力

### 3.1 Authentication：OAuth / subscription 登录已经做好

OpenAI 官方 Codex authentication 文档说明，Codex 支持两种登录方式：

1. **Sign in with ChatGPT for subscription access**；
2. **Sign in with an API key for usage-based access**。

Codex Cloud 需要 ChatGPT 登录；Codex CLI 和 IDE extension 同时支持 ChatGPT 登录和 API key 登录。官方还说明，CLI 在没有有效 session 时，默认使用 ChatGPT 登录路径。

对你来说，这意味着：

```text
你不需要自己实现 OpenAI OAuth token exchange。
你不需要自己保存 refresh token。
你不需要自己把 ChatGPT subscription 映射成模型调用能力。
你只需要调用官方登录命令。
```

推荐 demo 命令：

```bash
npm i -g @openai/codex
codex login --device-auth
codex login status
```

如果有浏览器环境，也可以：

```bash
codex login
```

**你要做的只有：**

- 在 README 或 setup 脚本中引导用户运行 `codex login --device-auth`；
- 检查 `codex login status`；
- 在你的 wrapper 里发现未登录时给出友好提示；
- 保护本地 credentials。

不要做：

- 不要自己抓 OAuth callback；
- 不要要求用户把 OpenAI access token 复制给你的服务器；
- 不要把 `~/.codex/auth.json` 上传到云端；
- 不要把 Codex subscription 当成公开 SaaS 的多人后端。

参考：OpenAI Codex Authentication 文档。

---

### 3.2 Login caching：登录态缓存已经做好

OpenAI 文档说明，Codex app、CLI、IDE extension 登录后会缓存登录信息，下次启动复用。缓存位置通常是：

```text
~/.codex/auth.json
```

或 OS credential store。Codex 的高级配置也说明，本地状态默认位于：

```text
CODEX_HOME=~/.codex
```

常见文件包括：

```text
config.toml
unsafe-auth.json / auth.json 或系统 keyring
history.jsonl
logs / caches
```

**Codex 已做：**

- 登录态缓存；
- CLI / IDE extension 共享登录状态；
- 本地配置目录管理。

**你要做：**

- 不要提交 `.codex`；
- 不要把 `auth.json` 放进 Docker image；
- 比赛 repo 加 `.gitignore`：

```gitignore
.codex/
*.auth.json
auth.json
.env
.env.local
```

---

### 3.3 Local coding agent：读取、修改、运行代码已经做好

OpenAI Codex CLI 官方描述：Codex CLI 是可以在本地 terminal 运行的 coding agent，能够在选定目录中读取、修改、运行代码。

这就是底层 harness 的核心：

```text
用户任务
  ↓
Codex 读取 workspace
  ↓
Codex 计划修改
  ↓
Codex 编辑文件
  ↓
Codex 执行命令 / 测试
  ↓
Codex 观察结果
  ↓
继续修正
```

**Codex 已做：**

- repo context；
- file read；
- file edit；
- shell command；
- patch / modify；
- test / run；
- iterative repair loop。

**你要做：**

- 设计工作区结构；
- 设计输出目录；
- 写清楚哪些文件可以改、哪些不能改；
- 为 SME demo 准备模板和 mock data。

建议 demo repo：

```text
sme-codex-demo/
  AGENTS.md
  package.json
  src/
    server.ts
    ui/
    harness/
  sme_templates/
    tutoring_studio.md
    restaurant.md
    ecommerce_shop.md
  mock_data/
    customers.csv
    orders.csv
    messages.json
  workflows/
  outputs/
  generated/
```

---

### 3.4 CLI / exec 非交互模式已经做好

Codex CLI reference 说明，CLI 的默认配置来自 `~/.codex/config.toml`，命令行 `-c key=value` 可以覆盖单次调用配置。Codex 也支持 `codex exec` 这种非交互执行模式，适合脚本化调用。

对你的 demo 来说，最实用的是：

```bash
codex exec --cd . --sandbox workspace-write "Generate an SME weekly report workflow based on mock_data/messages.json"
```

**Codex 已做：**

- 非交互任务执行；
- 从指定工作目录运行；
- 命令行覆盖配置；
- 输出给 stdout / wrapper 捕获。

**你要做：**

- 写 wrapper；
- 把前端输入转成 Codex prompt；
- 捕获输出；
- 解析产物；
- 给用户展示。

最小 Node wrapper：

```ts
import { spawn } from "child_process";

export function runCodexExec(prompt: string, cwd = process.cwd()) {
  return new Promise<string>((resolve, reject) => {
    const child = spawn("codex", [
      "exec",
      "--cd", cwd,
      "--sandbox", "workspace-write",
      prompt,
    ]);

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => stdout += chunk.toString());
    child.stderr.on("data", (chunk) => stderr += chunk.toString());

    child.on("close", (code) => {
      if (code === 0) resolve(stdout);
      else reject(new Error(`Codex failed: ${code}\n${stderr}`));
    });
  });
}
```

---

### 3.5 Sandbox / approval 已经做好，但策略要你定

OpenAI Codex sandboxing 文档说明，sandbox 决定 Codex 技术上能做什么，例如可以修改哪些文件、命令是否能访问网络；approval policy 决定 Codex 什么时候必须停下来问人。

OpenAI Agent approvals & security 文档也说明，Codex 默认网络访问关闭，本地 Codex 通过 OS-enforced sandbox 限制它能触碰的范围，通常限制在当前 workspace，并通过 approval policy 控制越界操作。

**Codex 已做：**

- OS-level sandbox；
- workspace 边界；
- network 控制；
- approval flow；
- 命令执行边界；
- 超出边界时暂停请求确认。

**你要做：**

- 明确 demo 允许范围；
- 避免让 Codex 修改真实系统文件；
- 把 demo 全部限制在一个临时 repo；
- 把网络访问最小化；
- 业务层动作仍要你自己审批。

推荐 demo 原则：

```text
允许：
- 修改 /outputs
- 修改 /generated
- 修改 /workflows
- 读取 /mock_data
- 运行 npm test / npm run dev / python scripts

禁止：
- 删除项目根目录
- 访问用户主目录
- 上传 auth.json
- 自动发送真实邮件
- 自动修改真实日历
- 自动调用真实支付接口
```

**关键区分：**

```text
Codex approval = 文件/命令/网络层面的安全确认
你的业务 approval = 是否真的给客户发邮件、修改订单、发付款提醒
```

Codex 不会自动知道哪些 SME 业务动作需要 human approval，这部分必须你定义。

---

### 3.6 MCP 接入机制已经做好，具体业务工具要你做

OpenAI Codex MCP 文档说明，MCP 用于把模型连接到工具和上下文，例如第三方文档、浏览器、Figma 等；Codex CLI 和 IDE extension 都支持 MCP servers。

**Codex 已做：**

- MCP client 能力；
- 能连接外部 MCP server；
- 能通过 MCP 扩展工具和上下文。

**你要做：**

- 选择要接的 MCP server；
- 配置 MCP；
- 为 SME 场景写自己的 MCP server；
- 做业务权限控制。

SME demo 里最有价值的 MCP / tool：

| SME 工具 | Demo 版本 | 正式版本 |
|---|---|---|
| Gmail / Email | mock messages JSON | Gmail OAuth + MCP / API |
| Calendar | mock schedule JSON | Google Calendar / Outlook |
| Sheets | local CSV | Google Sheets / Excel / Airtable |
| CRM | local customers.csv | HubSpot / Notion / 自研 CRM |
| POS / orders | local orders.csv | Shopify / Square / Stripe |
| Docs | local templates | Drive / Notion / SharePoint |

Demo 阶段不用真的接所有工具。你可以先用本地 mock data：

```text
mock_data/messages.json
mock_data/customers.csv
mock_data/orders.csv
mock_data/calendar.json
```

然后让 Codex 生成：

```text
outputs/customer_replies.md
outputs/weekly_summary.md
outputs/follow_up_tasks.json
outputs/cashflow_alerts.md
outputs/calendar_actions.json
```

---

### 3.7 Skills / plugins 机制已经有，但 SME 技能要你写

OpenAI Codex skills 文档说明，本地 skill folder 适合本地 authoring 和 repo-scoped workflows；如果要分发可复用 skill，可以打包成 plugin。Plugins 可以包含多个 skills，也可以包含 app mappings、MCP server config 和 presentation assets。

**Codex 已做：**

- skill 机制；
- plugin 分发机制；
- curated skills 安装机制；
- skill detection。

**你要做：**

- 写自己的 SME skills；
- 把业务流程写成可复用技能；
- 在 AGENTS.md 中告诉 Codex 何时使用哪个 skill。

建议技能设计：

```text
skills/
  sme-intake/
    SKILL.md
  customer-reply-drafting/
    SKILL.md
  weekly-business-report/
    SKILL.md
  small-business-ops-plan/
    SKILL.md
  human-approval-check/
    SKILL.md
```

示例 `skills/weekly-business-report/SKILL.md`：

```md
# Weekly Business Report Skill

Use this skill when the user asks to summarize a small business's weekly operation status.

Inputs:
- customer messages
- order records
- payment status
- schedule data

Process:
1. Identify customer issues.
2. Summarize revenue/order changes.
3. Extract overdue follow-ups.
4. Generate owner action list.
5. Separate automated actions from human-approval actions.

Output files:
- outputs/weekly_business_report.md
- outputs/action_items.json
- outputs/human_approval_required.md
```

这部分就是你的差异化，因为别人也能用 Codex，但未必有你的 SME workflow library。

---

### 3.8 Codex as MCP Server 已经做好，是否使用取决于你是否要多 agent 编排

OpenAI 官方 “Use Codex with the Agents SDK” 文档说明：可以把 Codex CLI 暴露为 MCP server，再用 OpenAI Agents SDK 编排，从单 agent 扩展到完整 software delivery pipeline。该文档还说明 MCP server 暴露 `codex()` 和 `codex-reply()` 两个工具，用于开始和继续 Codex session。

**Codex 已做：**

- 可以作为 MCP server；
- 可以被 Agents SDK 调用；
- 可以保留 Codex 会话；
- 可以接入更复杂的多 agent / handoff / guardrail / trace 编排。

**你要做：**

- 如果只是 demo，可以不接 Agents SDK；
- 如果想展示“多 agent 正规架构”，可以用 Agents SDK 调 Codex MCP；
- 定义 Planner / Operator / Reviewer / Codex Executor 等角色。

高级架构：

```text
Frontend
  ↓
Backend Orchestrator
  ↓
OpenAI Agents SDK
  ├─ SME Planner Agent
  ├─ Business Risk Reviewer Agent
  └─ Codex MCP Executor
        ↓
      Codex CLI
        ↓
      Files / commands / generated artifacts
```

什么时候值得用？

| 情况 | 是否用 Agents SDK + Codex MCP |
|---|---:|
| 只有半天时间做 demo | ❌ 不建议，直接 Codex CLI wrapper |
| 需要评委看到清晰多 agent 架构 | ✅ 可以用 |
| 需要 trace / handoff / guardrails | ✅ 可以用 |
| 只是生成页面、报告、模板 | ❌ Codex exec 足够 |

---

### 3.9 App-server 已经做好，但只有深度客户端才需要

OpenAI Codex app-server 文档说明，app-server 是 Codex 用来支持 rich clients 的接口，例如 VS Code extension；适合做深度产品集成，提供 authentication、conversation history、approvals 和 streamed agent events。它使用 JSON-RPC 2.0，支持 stdio 和实验性 websocket transport。

**Codex 已做：**

- rich-client protocol；
- conversation history；
- approvals；
- streamed agent events；
- JSON-RPC 通信；
- app / IDE extension 级集成接口。

**你要做：**

- 如果只是黑客松 demo，不一定要用 app-server；
- 如果要做一个漂亮的“agent trace UI”，可以研究 app-server；
- 需要写 JSON-RPC client 或用 SDK 封装。

建议：

```text
第一版：codex exec + 输出文件 + 简单 UI
第二版：Codex SDK / app-server + streamed events
第三版：Agents SDK + Codex MCP + trace UI
```

不要一开始就用最复杂的 app-server，否则容易把时间耗在协议适配上。

---

## 4. 你自己的 Harness 应该怎么设计

你要做的不是底层模型 harness，而是 **SME Business Harness**。

建议整体结构：

```text
SME User Input
  ↓
Business Intake Harness
  ↓
Scenario Classifier
  ↓
Workflow Planner
  ↓
Codex Execution Harness
  ↓
Generated Operational Artifacts
  ↓
Human Approval Layer
  ↓
Demo UI / Export / Action Plan
```

---

## 5. 针对 SMEs 方向，你必须自己做的 12 个核心模块

### 5.1 SME Intake Schema

Codex 不知道你的小企业用户到底是什么业务。你必须把输入结构化。

建议 schema：

```json
{
  "business_type": "tutoring_studio | restaurant | ecommerce | agency | clinic | fitness_studio",
  "business_goal": "reduce admin work / increase repeat purchase / improve follow-up",
  "pain_points": [
    "too many customer messages",
    "manual scheduling",
    "no weekly report"
  ],
  "data_sources": [
    "messages.json",
    "orders.csv",
    "calendar.json"
  ],
  "allowed_actions": [
    "draft_email",
    "generate_report",
    "create_follow_up_tasks"
  ],
  "forbidden_actions": [
    "send_email_without_approval",
    "charge_payment",
    "delete_customer_data"
  ]
}
```

### 5.2 Business Scenario Library

准备 3 个最强 SME 场景即可：

| 场景 | 痛点 | Demo 产物 |
|---|---|---|
| 小型补习机构 | 家长消息、排课、学生反馈、付款提醒 | 家长回复模板、周报、待办任务、课程安排建议 |
| 小餐厅/咖啡店 | 评论回复、活动推广、库存提醒、客户复购 | 评论分析、促销文案、库存提醒、复购名单 |
| 小电商店铺 | 订单咨询、退换货、评价分析、商品优化 | 客服草稿、FAQ、商品优化建议、售后任务 |

不要一开始做 10 个行业。比赛更重要的是把一个场景打穿。

### 5.3 Prompt Pack / AGENTS.md

你要写一个明确的 `AGENTS.md` 控制 Codex 行为。

示例：

```md
# SME Codex Harness Instructions

You are operating inside an SME automation demo workspace.

Core objective:
Turn a small business owner's messy operational problem into concrete business artifacts.

Rules:
1. Never modify files outside `/outputs`, `/generated`, `/workflows`, unless explicitly asked.
2. Never send real emails, make payments, or call external APIs without human approval.
3. Always separate:
   - automated drafts
   - human approval required actions
   - risky or unsupported actions
4. Prefer creating structured output files over only replying in text.
5. For every run, create:
   - `/outputs/business_diagnosis.md`
   - `/outputs/agent_workflow.md`
   - `/outputs/action_items.json`
   - `/outputs/human_approval_required.md`
6. If mock data is available, use it. If not, create clearly labeled mock examples.
```

### 5.4 Output Artifact Contract

你必须固定输出格式，否则每次 demo 结果不稳定。

建议每次运行固定生成：

```text
outputs/
  business_diagnosis.md
  agent_workflow.md
  customer_reply_drafts.md
  weekly_report.md
  action_items.json
  human_approval_required.md
  demo_summary.md
```

`action_items.json` 示例：

```json
[
  {
    "task": "Draft payment reminder for overdue parents",
    "owner": "AI Operator",
    "risk": "medium",
    "requires_human_approval": true,
    "suggested_action": "Review and send manually"
  }
]
```

### 5.5 Human Approval Layer

Codex 的 approval 只管文件/命令安全，不管 SME 业务安全。

你需要自己规定：

| 业务动作 | 是否允许自动执行 | 规则 |
|---|---:|---|
| 生成报告 | ✅ | 可自动生成 |
| 起草邮件 | ✅ | 可自动生成草稿 |
| 发送邮件 | ❌ | 必须人工确认 |
| 修改日程 | ⚠️ | Demo 可生成建议，不实际提交 |
| 修改价格 | ❌ | 必须人工确认 |
| 收款/退款 | ❌ | 不允许自动执行 |
| 删除客户记录 | ❌ | 禁止 |

### 5.6 Business Memory

Codex 有本地历史，但这不是你的产品 memory。

你要自己做：

```text
business_memory/
  owner_preferences.json
  customer_segments.json
  repeated_questions.json
  weekly_summary_history.jsonl
  approved_templates.md
```

Memory 设计原则：

- Codex history：用于 Codex 自己继续会话；
- Product memory：用于你的 SME 产品长期了解业务；
- 不要混在一起。

### 5.7 Tool Registry

即使 Codex 能接 MCP，你也要定义业务工具清单。

示例：

```json
{
  "tools": [
    {
      "name": "read_customer_messages",
      "type": "local_file",
      "path": "mock_data/messages.json",
      "risk": "low"
    },
    {
      "name": "draft_parent_reply",
      "type": "artifact_generation",
      "output": "outputs/customer_reply_drafts.md",
      "risk": "medium",
      "requires_approval_before_real_send": true
    }
  ]
}
```

### 5.8 Error Recovery Rules

Codex 会自我修复代码错误，但业务错误你要定义。

例如：

```text
如果 mock_data 缺失：生成 sample data，并标记为 demo mock。
如果客户数据字段不完整：输出 missing_fields.md。
如果任务涉及真实外发：改为生成 draft，不执行发送。
如果 action risk = high：进入 human_approval_required.md。
```

### 5.9 Demo Trace UI

你需要让评委看到“发生了什么”。

最简单的 trace：

```json
[
  { "step": 1, "agent": "Intake", "action": "Parsed SME problem" },
  { "step": 2, "agent": "Planner", "action": "Designed workflow" },
  { "step": 3, "agent": "Operator", "action": "Generated customer replies" },
  { "step": 4, "agent": "Reviewer", "action": "Flagged approval-required items" }
]
```

你可以让 Codex 每次写：

```text
outputs/trace.json
```

前端直接读取展示。

### 5.10 Evaluation Rubric

你需要自己定义 demo 成功标准。

```text
1. 是否准确识别小企业痛点？
2. 是否生成可执行工作流？
3. 是否输出真实可用 artifact？
4. 是否区分自动化和人工审批？
5. 是否能复用到其他 SME 场景？
```

### 5.11 Credit / Usage Strategy

Codex subscription 可以让你快速 demo，但你仍然要控制调用次数。

建议：

```text
开发期：多用 Codex interactive / exec。
演示期：准备 1 条稳定主流程。
备用：提前保存生成过的 outputs，现场失败时可展示 fallback。
```

### 5.12 Product Narrative

你要把技术翻译成评委能懂的产品价值：

```text
Small businesses do not need another chatbot.
They need an AI operator that turns messy daily work into concrete operating artifacts:
reply drafts, weekly reports, follow-up lists, approval queues, and reusable workflows.
```

---

## 6. 完整 Harness 流程：一步一步看哪些 Codex 做，哪些你做

| 步骤 | 流程 | Codex 做什么 | 你做什么 |
|---:|---|---|---|
| 1 | 用户打开 demo | 无 | 你做 frontend / CLI UI |
| 2 | 检查登录 | `codex login status` | wrapper 检测失败并提示登录 |
| 3 | 用户输入 SME 问题 | 无 | 表单/schema/行业选择 |
| 4 | 生成任务 prompt | 无 | prompt builder / AGENTS.md / skills |
| 5 | 调用 Codex | CLI/exec/SDK/app-server | wrapper 调用方式 |
| 6 | 读取 workspace | Codex 自动读取相关文件 | 控制目录结构和上下文 |
| 7 | 计划任务 | Codex agent loop | 提供明确任务边界 |
| 8 | 调用工具/命令 | Codex 执行命令 | 设置 sandbox/approval |
| 9 | 生成文件 | Codex 修改/创建文件 | 规定 output contract |
| 10 | 处理失败 | Codex 可迭代修复 | 规定 fallback 和业务错误处理 |
| 11 | 产物解析 | 无 | 读取 outputs / JSON / markdown |
| 12 | 展示 trace | app-server 可提供事件；CLI 可输出文本 | 你做 UI trace / timeline |
| 13 | 业务审批 | Codex 不懂具体业务风险 | human approval layer |
| 14 | 保存业务 memory | Codex history 不是产品 memory | 你做 business_memory |
| 15 | 导出结果 | Codex 可生成文件 | 你做下载/展示/分享 |
| 16 | 复用到下个场景 | Codex 可继续会话 | 你做 scenario library / templates |

---

## 7. 三种实现路线

### 路线 A：最快 demo —— Codex CLI + wrapper

适合：时间短、要快速展示。

```text
Frontend / CLI
  ↓
Node/Python wrapper
  ↓
codex exec
  ↓
outputs files
  ↓
UI 展示
```

优点：

- 最快；
- 直接用 Codex OAuth；
- 不需要自己写复杂 agent runtime；
- 现场可控。

缺点：

- 事件流和 trace 不如 app-server 漂亮；
- 多 agent 编排偏 prompt 层模拟；
- 不适合公网多人使用。

推荐你黑客松优先采用。

---

### 路线 B：中级 demo —— Codex MCP + Agents SDK

适合：你想展示“真正多 agent 架构”。

```text
Frontend
  ↓
Backend
  ↓
Agents SDK
  ├─ Planner
  ├─ Risk Reviewer
  └─ Codex MCP Executor
```

优点：

- 架构更正规；
- 支持 handoff / guardrail / trace；
- 更容易向生产架构过渡。

缺点：

- 需要 API key；
- 搭建更复杂；
- 不如纯 Codex subscription 简单。

适合你有余力时做第二版。

---

### 路线 C：高级 rich client —— Codex app-server

适合：你想做自己的“Claude Code / Codex Desktop-like UI”。

```text
Frontend rich client
  ↓
JSON-RPC / WebSocket / stdio
  ↓
codex app-server
  ↓
Codex runtime
```

优点：

- 可拿到 streamed agent events；
- 可做漂亮过程 UI；
- 更像专业开发者产品。

缺点：

- 协议复杂；
- 比赛时间不一定够；
- 对 SME 价值不如业务场景本身重要。

建议作为后续研究，不建议第一天就上。

---

## 8. 推荐给你的最终 Hackathon 架构

### 8.1 你的产品标题

```text
SME Codex Operator
An AI execution harness that turns small-business intent into operational artifacts.
```

### 8.2 架构图

```text
Small Business Owner
  ↓
SME Intake UI
  ↓
Business Harness Layer
  ├─ scenario schema
  ├─ prompt builder
  ├─ approval policy
  ├─ output contract
  └─ business memory
  ↓
Codex Execution Harness
  ├─ ChatGPT OAuth / subscription auth
  ├─ repo context
  ├─ file generation
  ├─ shell execution
  ├─ sandbox
  ├─ approval
  └─ MCP/tools
  ↓
Generated Artifacts
  ├─ diagnosis
  ├─ workflow
  ├─ replies
  ├─ weekly report
  ├─ tasks
  └─ approval queue
```

### 8.3 最小可运行流程

```text
1. 用户选择行业：补习机构 / 餐厅 / 电商。
2. 用户输入痛点：消息太多、排课混乱、没有周报。
3. 后端生成 prompt。
4. 调用 codex exec。
5. Codex 读取 mock_data 和 templates。
6. Codex 生成 outputs。
7. 前端读取 outputs 并展示：
   - Business Diagnosis
   - Agent Workflow
   - Draft Replies
   - Weekly Report
   - Action Items
   - Human Approval Queue
8. 评委看到：AI 已把一个小企业的模糊问题变成了可执行运营系统。
```

---

## 9. 你不需要重做的 Codex Harness 功能清单

明确不要浪费时间做：

```text
❌ 自己实现 OpenAI OAuth
❌ 自己保存 refresh token
❌ 自己实现 ChatGPT subscription billing mapping
❌ 自己写底层 model API wrapper
❌ 自己实现 repo file editing engine
❌ 自己实现 shell execution engine
❌ 自己实现 sandbox
❌ 自己实现 file patch mechanism
❌ 自己实现 command approval flow
❌ 自己从零做 MCP client
❌ 自己从零做 Codex session continuation
❌ 自己从零做 app-server protocol，除非你明确需要 rich client
```

你应该把这些全部交给 Codex。

---

## 10. 你必须自己实现的 Harness 功能清单

必须做：

```text
✅ SME 业务场景选择
✅ SME 输入 schema
✅ 业务痛点解析
✅ 业务工作流模板
✅ prompt builder
✅ AGENTS.md
✅ SME skills
✅ mock data
✅ output file contract
✅ human approval policy
✅ trace.json / demo timeline
✅ frontend 展示
✅ fallback outputs
✅ pitch narrative
```

可选做：

```text
⚠️ Codex MCP + Agents SDK 编排
⚠️ app-server streamed events
⚠️ 真正 Gmail / Calendar / Sheets OAuth
⚠️ 多租户用户系统
⚠️ API cost dashboard
⚠️ production migration to Responses API
```

---

## 11. 你应该如何向评委解释

### 英文技术表达

```text
For this hackathon, we use Codex as the execution harness rather than rebuilding the low-level agent runtime ourselves. Codex already provides subscription-based authentication, local repository context, file operations, shell execution, sandboxing, approvals, and MCP extensibility.

Our contribution is the SME business harness on top: business intake schemas, workflow templates, human approval policies, output contracts, and reusable operating artifacts for small businesses.

In production, the same business harness can be migrated to OpenAI Responses API and Agents SDK for multi-user deployment, business integrations, audit logs, and billing control.
```

### 中文解释

```text
我们没有重复造底层 agent harness，因为 Codex 已经提供了 OAuth 登录、本地上下文、文件操作、命令执行、沙箱、审批和 MCP 扩展能力。

我们真正做的是 SME 业务 harness：把小企业老板的模糊需求转成结构化业务输入、工作流、审批规则和可执行产物。

所以这个 demo 不是一个普通聊天机器人，而是一个能把小企业日常运营问题转成实际运营文件和行动清单的 AI Operator。
```

---

## 12. 推荐的目录结构

```text
sme-codex-operator/
  AGENTS.md
  README.md
  package.json
  .gitignore

  src/
    server.ts
    codex_runner.ts
    prompt_builder.ts
    output_reader.ts
    ui/

  skills/
    sme-intake/
      SKILL.md
    weekly-report/
      SKILL.md
    customer-reply/
      SKILL.md
    human-approval/
      SKILL.md

  sme_templates/
    tutoring_studio.md
    restaurant.md
    ecommerce_shop.md

  mock_data/
    tutoring_messages.json
    tutoring_schedule.json
    tutoring_payments.csv
    restaurant_reviews.json
    ecommerce_orders.csv

  workflows/
    .gitkeep

  outputs/
    .gitkeep

  generated/
    .gitkeep

  business_memory/
    owner_preferences.json
    approved_templates.md
```

---

## 13. 最小开发顺序

### Day 0 / Hackathon 前 1 小时

```bash
npm i -g @openai/codex
codex login --device-auth
codex login status
```

### Step 1：建立 demo repo

```bash
mkdir sme-codex-operator
cd sme-codex-operator
npm init -y
mkdir -p src skills sme_templates mock_data workflows outputs generated business_memory
```

### Step 2：写 AGENTS.md

先写清楚 Codex 只能生成 outputs，不要碰真实业务。

### Step 3：准备一个主场景

建议先做：**小型补习机构**。

原因：

- 信息流多；
- 家长沟通频繁；
- 排课/付款/反馈都很典型；
- 很容易让评委理解。

### Step 4：写 wrapper

用 Node 或 Python 调 `codex exec`。

### Step 5：固定输出文件

要求 Codex 每次创建固定文件。

### Step 6：做 UI

展示输入、trace、产物、approval queue。

### Step 7：准备 fallback

提前保存一组成功 outputs，现场失败时可展示。

---

## 14. 最重要的风险

| 风险 | 说明 | 应对 |
|---|---|---|
| 误把 Codex subscription 当 SaaS 后端 | 不适合公开多人产品 | Demo 可以，正式产品换 Responses API / Agents SDK |
| OAuth token 泄露 | `auth.json` 很敏感 | 不上传、不提交、不部署到公网 |
| 输出不稳定 | Codex 每次生成可能不同 | 固定 AGENTS.md、output contract、mock data |
| 现场网络/权限问题 | device auth 或调用失败 | 提前登录，准备 fallback outputs |
| 业务风险没讲清 | 评委担心自动发邮件/收款 | 强调 human approval queue |
| 只像“套壳聊天” | 没有可执行产物 | 必须生成文件、workflow、report、tasks |

---

## 15. 最终建议

你这次 Hackathon 可以坚定采用：

```text
Codex OAuth / subscription
+ Codex CLI exec
+ SME business harness
+ fixed output artifacts
+ human approval queue
+ demo UI
```

不要一开始就陷入 OpenAI Agents SDK / app-server 的复杂实现。你需要展示的不是“我能调多少 SDK”，而是：

```text
我理解 Codex 已经做好的底层 agent harness，
所以我把全部精力放在 SME 业务 harness 上，
让小企业老板的真实问题变成可执行的运营系统。
```

这会比单纯说“我接了 OpenAI SDK”更有冲击力。

---

## 16. 参考资料

- OpenAI Codex Authentication: https://developers.openai.com/codex/auth
- OpenAI Codex CLI: https://developers.openai.com/codex/cli
- OpenAI Codex CLI Reference: https://developers.openai.com/codex/cli/reference
- OpenAI Codex Sandbox: https://developers.openai.com/codex/concepts/sandboxing
- OpenAI Codex Agent approvals & security: https://developers.openai.com/codex/agent-approvals-security
- OpenAI Codex Advanced Configuration: https://developers.openai.com/codex/config-advanced
- OpenAI Codex MCP: https://developers.openai.com/codex/mcp
- OpenAI Codex Skills: https://developers.openai.com/codex/skills
- OpenAI Use Codex with Agents SDK: https://developers.openai.com/codex/guides/agents-sdk
- OpenAI Codex SDK: https://developers.openai.com/codex/sdk
- OpenAI Codex App Server: https://developers.openai.com/codex/app-server
- OpenAI Agents SDK Running agents: https://developers.openai.com/api/docs/guides/agents/running-agents
