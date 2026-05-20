# OpenAI SDK / API Harness 机制完整解读：哪些已经由 SDK 提供，哪些需要你自己做

> 面向你的 Hackathon SME 方向：用 OpenAI SDK 构建一套可复用的 **AI Business Operator / SME Agent Harness**。  
> 更新时间：2026-04-28  
> 主要依据：OpenAI 官方 Developers / API 文档、Agents SDK 文档、Responses API 文档、Prompt Caching 文档、Function Calling、Structured Outputs、Conversation State、Tools、Evals、Observability 等。

---

## 0. 一句话结论

如果你要做 Hackathon 项目，我建议你的底层不要再从零写一个“模型调用循环”。你应该把 **OpenAI Responses API + OpenAI Agents SDK** 当作核心 agentic runtime，把你自己的工作重点放在：

1. **业务语义层**：SME 的真实任务、业务对象、工作流、权限、审批、账户、订单、财务、客户沟通。
2. **产品 harness 层**：任务拆解、状态机、可视化 trace、用户确认、失败恢复、demo 叙事。
3. **长期记忆和企业上下文层**：客户画像、公司知识库、历史任务、偏好、业务 KPI、CRM/订单/日历/邮件等私有数据。
4. **评测与可靠性层**：demo 主路径、任务成功率、工具调用正确性、guardrail、成本和延迟监控。

不要重复造：

- SDK 客户端封装；
- 基础 HTTP 调用；
- 简单 tool-call loop；
- prompt KV/cache 的底层实现；
- 基础 structured output 解析；
- 基础 web/file/code interpreter/computer/MCP 工具接入；
- 基础 agent handoff / agents-as-tools 编排；
- 基础 tracing / eval 入口。

你要做的是 **product harness**，不是重新实现 OpenAI 的 runtime。

---

## 1. 你的核心判断是对的：不管项目是什么，都需要一套可复用的 harness

你今天说的关键判断非常重要：

> 不管我做什么项目，我都需要一套基于 OpenAI SDK 的 harness 模型。

这句话本质上是在区分两层东西：

| 层级 | 含义 | 你是否应该自己做 |
|---|---|---|
| Model API Layer | 调用模型、传 input、拿 output、处理 streaming、tools、usage | **不应该重造**，直接用 SDK / Responses API |
| Agent Runtime Layer | 循环调用模型、执行工具、handoff、guardrail、session、trace | **大部分不应该重造**，优先用 Agents SDK |
| Product Harness Layer | 把 agent 能力变成具体产品工作流、UI、权限、业务状态、审计、重试、用户确认 | **必须自己做** |
| Domain Intelligence Layer | SME 场景知识、行业 workflow、财务/营销/客服/供应链模板 | **必须自己做** |
| Data / Memory Layer | 公司知识库、用户偏好、历史任务、长期记忆、业务数据库同步 | **必须自己做，但可用 File Search / Vector Store / Responses state 辅助** |
| Reliability / Evaluation Layer | 评测集、trace grading、主路径可靠性、成本预算、fallback | **需要自己设计，但 OpenAI 提供 eval/tracing 基础设施** |

所以你的正确路线不是“写一个 Claude Code / Codex clone”，而是：

> 用 OpenAI 官方 SDK 和 agentic primitive 作为底层，把自己的独特能力放在 SME 场景、业务流程、记忆系统、产品体验、真实可交付结果上。

---

## 2. OpenAI 现在的推荐基础：Responses API 是新项目主入口

OpenAI 官方文档明确说：**Responses API 是新的 API primitive，是 Chat Completions 的演进，推荐所有新项目使用 Responses API**。它把文本生成、工具调用、多模态、状态、agentic loop 等能力集中在一个接口中。

### 2.1 为什么新项目应该优先用 Responses API

Responses API 的核心价值：

1. **Agentic by default**：一次 API 请求内部可以让模型调用多个工具，包括 web search、file search、code interpreter、image generation、remote MCP、自定义 functions。
2. **内置工具支持**：不必所有工具都手写 function calling wrapper。
3. **更好的推理模型体验**：reasoning models 在 Responses API 中有更完整的 tool usage 支持。
4. **更好的 cache 利用**：官方迁移文档提到，Responses 相比 Chat Completions 在内部测试中有更好的 cache utilization。
5. **状态管理更简单**：支持 `previous_response_id`、Conversations API、`store` 等机制。
6. **输出结构更清楚**：Responses 返回的是 typed Items，例如 message、function_call、tool result、reasoning 等，而不是 Chat Completions 里把很多内容塞进 message/choices。
7. **未来方向更明确**：OpenAI 明确说 Responses API 是 building agents 的未来方向，Assistants API 已进入迁移/弃用路径。

### 2.2 对你的 harness 意味着什么

你应该把 Responses API 作为最底层的统一 model execution primitive：

```text
Your Product UI
  ↓
Your Backend Harness / Orchestrator
  ↓
OpenAI Responses API / Agents SDK
  ↓
OpenAI Models + Built-in Tools + Custom Tools
```

不要再基于旧 Chat Completions 重新发明一套 agent runtime，除非你有非常明确的兼容需求。

---

## 3. OpenAI SDK 已经做了什么

OpenAI SDK 已经解决了很多“基础工程问题”。这些你不需要重复造。

### 3.1 官方 SDK 与 API Key 管理

OpenAI 官方 SDK 支持多语言环境，并且文档说明 SDK 会自动从环境变量读取 `OPENAI_API_KEY`。

常见选择：

| 语言 / 环境 | 推荐使用方式 | 适合场景 |
|---|---|---|
| TypeScript / Node.js | `openai` SDK + `@openai/agents` | 你当前 NestJS / Nuxt 技术栈最适合 |
| Python | `openai` SDK + Python Agents SDK | 快速实验、数据处理、AI workflow prototyping |
| .NET | 官方 C# SDK | 企业客户 / Windows / Microsoft 生态 |
| Java | 官方 Java SDK beta | Java 企业系统集成 |
| Raw HTTP | 直接请求 `/v1/responses` | 特殊网关、非官方语言、最小依赖场景 |

对你来说，Hackathon 期间最现实的选择是：

```text
Frontend: Nuxt / Vue / Tailwind
Backend: NestJS
Agent Runtime: OpenAI TypeScript SDK + @openai/agents
Database: PostgreSQL / Redis
Memory: 自己的业务记忆表 + OpenAI File Search / Vector Store 可选
```

### 3.2 Responses API 的基础调用

Python 示例：

```python
from openai import OpenAI
client = OpenAI()

response = client.responses.create(
    model="gpt-5.5",
    input="Write a one-sentence bedtime story about a unicorn."
)

print(response.output_text)
```

TypeScript 示例：

```ts
import OpenAI from "openai";

const client = new OpenAI();

const response = await client.responses.create({
  model: "gpt-5.5",
  input: "Write a one-sentence bedtime story about a unicorn."
});

console.log(response.output_text);
```

这意味着：

- 你不需要自己封装基础 HTTP；
- 不需要自己解析大量复杂响应；
- 不需要自己写基础 retry / client class / API key 注入；
- 不需要自己把 `output` 遍历拼成普通文本，SDK 提供了 `output_text` helper。

---

## 4. Prompt Caching：他们说得对，底层 caching 已经自动集成，不需要你自己做 KV-cache

你今天上午和 OpenAI employee 聊到的点是正确的：**OpenAI 的 Prompt Caching 已经自动工作，不需要你自己写底层缓存代码**。

OpenAI 官方文档说明：Prompt Caching 会自动应用于所有 API 请求，无需改代码，也没有额外费用；它通过把包含重复内容的 prompt 路由到最近处理过同一 prompt 前缀的服务器，从而降低延迟和输入 token 成本。

### 4.1 不需要你做的 caching

你不需要自己实现：

- 模型 KV cache；
- GPU attention key/value tensor 缓存；
- prefix hash routing；
- OpenAI 服务器侧 prompt reuse；
- cached input token 计价逻辑；
- SDK 级 token prefix cache。

### 4.2 你仍然需要做的 caching / cache-aware design

你仍然要做这些：

| 你要做的事 | 为什么 |
|---|---|
| 把静态 system prompt / tool schema / examples 放前面 | Prompt cache 依赖 exact prefix match，静态内容越靠前越容易命中 |
| 把动态用户输入 / 当前任务 / 检索结果放后面 | 避免动态内容破坏前缀缓存 |
| 监控 `cached_tokens` | 判断 cache 是否真的命中 |
| 合理设置 `prompt_cache_key` | 多个请求共享长前缀时提高路由命中率 |
| 应用级结果缓存 | 对业务查询、数据库结果、网页搜索结果、RAG 检索结果做缓存 |
| 文件/知识库缓存 | 向量库、embedding、document chunk 不要每次重算 |
| Tool output cache | 例如汇率、库存、客户资料、产品列表等短期缓存 |

### 4.3 Prompt Caching 的关键规则

OpenAI 文档中的重要规则：

1. **1024 tokens 以上的 prompt 才有 caching 机会**。
2. **cache hit 依赖 exact prefix match**。
3. 静态内容应该放在 prompt 开头，动态内容放在后面。
4. tools、images、structured output schema 也会影响缓存；它们必须保持一致。
5. 使用 `prompt_cache_key` 可以影响路由，提高共享长前缀时的命中率。
6. Extended Prompt Caching 在支持模型上最长可让 cached prefix 活跃到 24 小时。
7. `cached_tokens` 会出现在 usage 信息里，你应该记录它。
8. Prompt caches 不会跨 organization 共享。

### 4.4 对你的 SME harness 的具体建议

你的 prompt 应该拆成稳定前缀 + 动态尾部：

```text
[Stable Prefix]
- Product identity
- SME operator role
- Safety policy
- Tool usage policy
- Output schema
- Business workflow rules
- Few-shot examples

[Dynamic Middle]
- Current user business profile
- Retrieved company memory
- Current documents / orders / customers

[Dynamic Tail]
- User's exact current request
- Current task id
- Current UI state
```

更进一步，你可以按 agent 类型设计不同稳定前缀：

```text
sme-manager-v1
finance-agent-v1
customer-support-agent-v1
marketing-agent-v1
operations-agent-v1
```

每个 agent 的 system prompt 不要频繁变化，否则 cache 命中率会下降。

---

## 5. Tools：OpenAI 已经提供了非常多内置工具，但业务工具仍然要你自己做

OpenAI 现在的工具体系大致分为：

1. **Built-in tools**：web search、file search、code interpreter、image generation、computer use 等。
2. **Function calling**：你自己的业务函数。
3. **Tool search**：工具很多时，模型先搜索并加载相关工具。
4. **Remote MCP**：连接第三方 MCP server。
5. **Agents SDK tools**：把 function、agent、MCP、hosted tools 等挂到 agent 上。

### 5.1 OpenAI 已经提供的工具能力

| 工具能力 | 已有程度 | 你的处理方式 |
|---|---|---|
| Web Search | 已有 built-in tool | 直接配置 `tools: [{ type: "web_search" }]` |
| File Search | 已有 built-in tool + vector store | 用于上传文档、政策、FAQ、产品手册 |
| Code Interpreter | 已有 built-in tool | 用于表格计算、数据分析、文件处理 |
| Image Generation | 已有 built-in tool | 用于营销素材、广告图、商品图方案 |
| Computer Use | 已有工具能力 | 谨慎使用，涉及真实环境操作要加审批 |
| Remote MCP | 已有接口 | 用于连接外部服务 / SaaS / internal tools |
| Custom Function Calling | 已有 schema + tool-call mechanism | 你只需要写业务函数本身 |
| Tool Search | 已有，用于大量工具的延迟加载 | 适合未来你的 SME tool ecosystem |

### 5.2 你仍然必须自己做的业务工具

SME 方向真正有价值的是这些工具：

| 工具名 | 输入 | 输出 | 价值 |
|---|---|---|---|
| `get_business_profile` | business_id | 公司行业、规模、目标、地区、现金流状态 | 所有 agent 的上下文入口 |
| `list_recent_orders` | business_id, date_range | 订单列表 / 销售概览 | 支撑运营建议 |
| `get_customer_profile` | customer_id | 客户画像、历史沟通、偏好 | 支撑客服和营销 |
| `draft_customer_reply` | issue, tone, policy | 可发送的回复草稿 | SME 省时间的核心 demo |
| `analyze_cashflow` | revenue, expenses, invoices | 现金流风险和建议 | SME 很痛的财务场景 |
| `generate_marketing_campaign` | product, audience, channel | 营销计划和素材文案 | 快速出效果 |
| `create_followup_task` | task info | task_id | 把建议变成执行任务 |
| `send_email_draft` | to, subject, body | draft_id | 真实业务闭环，需人工确认 |
| `update_inventory_note` | sku, note | status | 业务系统写入，需 guardrail |
| `schedule_reminder` | date, message | reminder_id | 长周期经营助手 |

### 5.3 Function calling 的正确理解

Function calling 不等于模型真的执行了函数。它是：

1. 你把可用工具及其 JSON Schema 给模型；
2. 模型判断需要调用哪个工具；
3. 模型输出一个 tool call，包含函数名和参数；
4. 你的后端执行真实函数；
5. 你的后端把函数结果返回给模型；
6. 模型基于结果继续推理或给最终答案。

所以你不能把 function calling 视为“自动安全执行”。真正的权限、审计、幂等、审批、重试都要在你的 harness 里做。

### 5.4 Tool Search 的意义

当你的 SME 系统工具越来越多，例如 CRM、财务、库存、邮件、日历、支付、营销、客服、文档、网站发布等，如果每次都把所有工具 schema 塞进 prompt，会导致：

- prompt 过长；
- token 成本升高；
- tool 选择混乱；
- cache 命中率下降。

OpenAI 的 `tool_search` 允许模型在需要时搜索相关工具，再加载这些工具。这个机制非常适合你未来做 “SME Tool Marketplace / Business Skills Library”。

Hackathon 阶段可以先不做复杂 tool_search，但你可以在架构图里展示：

```text
Manager Agent
  ↓ tool_search
Business Tool Registry
  ├── Finance tools
  ├── Customer support tools
  ├── Marketing tools
  ├── Operations tools
  └── Commerce tools
```

---

## 6. Structured Outputs：稳定 JSON 输出已经内置，不要再靠 prompt 硬凑格式

OpenAI 的 Structured Outputs 可以让模型输出严格遵循你提供的 JSON Schema。文档说明它能减少遗漏 required key、invalid enum、格式不一致等问题。

### 6.1 你不需要做的

不要再用这种低可靠方式：

```text
请严格输出 JSON，不要输出任何解释，不要使用 Markdown，如果失败我会惩罚你……
```

这类 prompt-only 格式控制在 demo 时很容易翻车。

### 6.2 你应该做的

为每个关键节点定义 schema：

```ts
type SMEPlan = {
  problem_summary: string;
  business_context: {
    business_type: string;
    stage: "solo" | "small_team" | "growing";
    urgency: "low" | "medium" | "high";
  };
  recommended_actions: Array<{
    title: string;
    owner: "founder" | "finance_agent" | "marketing_agent" | "support_agent" | "ops_agent";
    reason: string;
    expected_impact: string;
    risk_level: "low" | "medium" | "high";
  }>;
  needs_human_approval: boolean;
};
```

关键原则：

| 场景 | 用什么 |
|---|---|
| 想让模型调用你的工具 | Function calling |
| 想让模型最终输出稳定业务对象 | Structured Outputs |
| 想让工具参数稳定 | Function schema with strict mode |
| 想让 UI 稳定渲染 | Structured Outputs |

---

## 7. Conversation State：OpenAI 提供了状态机制，但你的长期业务记忆仍然要自己做

OpenAI 文档说明，API 提供多种管理 conversation state 的方式：

1. 手动把历史消息传入下一次请求；
2. Responses API 的 `previous_response_id`；
3. Conversations API，用 conversation id 持久化跨 session / device / job 的状态；
4. Agents SDK session；
5. 你自己的数据库。

### 7.1 已经由 OpenAI 提供的状态机制

| 机制 | 状态在哪里 | 适合什么 |
|---|---|---|
| 手动 history replay | 你的应用 | 完全控制、简单可调试 |
| `previous_response_id` | OpenAI Responses API | 连续多轮、轻量级 server-managed continuation |
| Conversations API | OpenAI Conversations | 跨 session / device / job 的持久会话 |
| Agents SDK session | 你的 storage + SDK | agent run 的可恢复状态 |
| `store: false` | 禁用 response storage | 有合规/隐私要求时 |

### 7.2 你必须自己做的长期记忆

OpenAI 的 conversation state 不是完整的业务长期记忆系统。你的 SME 产品需要自己维护：

```text
Business Memory
  ├── Company profile
  ├── Founder preferences
  ├── Brand voice
  ├── Products / services
  ├── Customers
  ├── Orders / invoices
  ├── Previous campaigns
  ├── Support tickets
  ├── Decisions made
  ├── Pending tasks
  └── Lessons learned
```

原因很简单：

- conversation state 记录的是对话和工具上下文；
- SME memory 记录的是业务事实、偏好、决策和长期目标；
- 业务记忆需要权限、版本、删除、审计、结构化查询；
- 业务记忆还要跨 agent、跨任务、跨时间线复用。

### 7.3 推荐架构

```text
OpenAI Conversation State
  用于：当前多轮任务的上下文连续性

Your Business Memory DB
  用于：长期公司知识、用户偏好、历史任务、业务事实

OpenAI File Search / Vector Store
  用于：文档、合同、FAQ、政策、产品手册、知识库检索

Redis / App Cache
  用于：短期工具结果缓存、任务状态、rate limit、lock
```

---

## 8. Agents SDK：很多 agent loop / handoff / guardrail / tracing 已经做了

OpenAI Agents SDK 的定义非常接近你所说的 harness。官方文档描述 agent 是能够 plan、call tools、collaborate across specialists、keep enough state to complete multi-step work 的应用。

### 8.1 Agent loop 已经由 SDK 提供

Agents SDK 的一个 run 本质上是一个 application-level turn。runner 会循环：

1. 调用当前 agent 的模型；
2. 检查模型输出；
3. 如果有 tool calls，执行工具并继续；
4. 如果发生 handoff，切换到 specialist agent 并继续；
5. 如果模型输出 final answer 且没有更多工具工作，返回结果。

这意味着你不需要自己写最基础的循环：

```text
while true:
  call model
  parse tool calls
  execute tool
  append tool result
  call model again
  detect final answer
```

如果你用 Agents SDK，这个循环大部分已经有了。

### 8.2 Agents SDK 提供的编排模式

OpenAI 文档明确区分两种多 agent 编排：

| 模式 | 适用场景 | 控制权 |
|---|---|---|
| Handoffs | specialist 应该接管某个分支的对话 | 控制权移交给 specialist |
| Agents as tools | manager 应该保持最终答复控制，只把 specialist 当能力调用 | manager 保持控制 |

对你的 SME 方向，我强烈建议用 **Agents as tools** 作为主结构，而不是大量 handoffs。

原因：

- SME 用户不关心“谁接管了对话”；
- 用户希望一个统一的 business operator 给结果；
- manager agent 应该负责最终答案、优先级和商业判断；
- specialist agent 只作为 bounded capability。

推荐架构：

```text
SME Manager Agent
  ├── Finance Analyst Agent as Tool
  ├── Customer Support Agent as Tool
  ├── Marketing Agent as Tool
  ├── Operations Agent as Tool
  ├── Compliance / Risk Agent as Tool
  └── Document / Knowledge Agent as Tool
```

### 8.3 Guardrails 和 Human Review 已经有框架，但规则要你自己定义

Agents SDK 提供：

- input guardrails；
- output guardrails；
- tool guardrails；
- human-in-the-loop approvals。

但是，**guardrail 的业务规则需要你自己写**。

SME 场景尤其要注意 side effects：

| 操作 | 是否需要审批 | 原因 |
|---|---|---|
| 生成营销计划 | 不需要 | 低风险 |
| 生成邮件草稿 | 不需要或轻审批 | 还没发送 |
| 发送邮件 | 需要 | 对外沟通 |
| 修改客户资料 | 需要 | 影响业务数据 |
| 发退款 | 强审批 | 影响资金 |
| 生成财务建议 | 需要 disclaimer / guardrail | 防止被误认为专业财务建议 |
| 下单采购 | 强审批 | 真实金钱和库存影响 |
| 发布广告 | 强审批 | 预算消耗 |

你的产品应该展示：

```text
Agent can prepare.
Human approves before irreversible business action.
```

这会极大提升评委对 real-world viability 的信任。

### 8.4 Tracing / Observability 已经有，但产品级 trace UI 仍要你做

OpenAI SDK / Platform 提供 built-in tracing，可以看到：

- model calls；
- tool calls；
- guardrails；
- handoffs；
- approvals；
- end-to-end run trace。

但是，评委和 SME 用户不能去看 OpenAI dashboard。你需要在产品里做一个简化版 trace UI：

```text
Task: Prepare a weekly business action plan

1. Manager Agent understood the business goal
2. Finance Agent checked cashflow risk
3. Customer Agent summarized urgent customers
4. Marketing Agent proposed a campaign
5. Operations Agent found inventory bottleneck
6. Manager Agent prioritized 3 actions
7. Human approval required before sending customer emails
```

这个 UI 对 Hackathon 非常重要，因为它直接对应评审标准里的：

- Technical Depth
- Demo Reliability
- Pitch Clarity
- Real-world Viability

### 8.5 Evals 已经有基础设施，但你的 eval dataset 必须自己做

OpenAI Platform 提供 evaluation tools，包括 traces、graders、datasets、eval runs。它们可以评估：

- agent 是否选对工具；
- handoff 是否发生在正确时机；
- workflow 是否违反指令或安全策略；
- prompt / routing 变化是否提升端到端表现。

但是你的 SME 产品需要自己的 eval cases。

建议 Hackathon 准备 10 个最小 eval：

| Eval Case | 期望行为 |
|---|---|
| 用户想减少客服压力 | 调用 customer support + FAQ + draft reply |
| 用户想改善现金流 | 调用 finance agent，不能直接给非法财务承诺 |
| 用户想发促销邮件 | 先生成草稿，再请求人工确认 |
| 用户上传供应商合同 | 调用 file search，总结风险 |
| 用户要求自动退款 | 触发 human approval |
| 用户请求违法/欺诈营销 | guardrail 拒绝 |
| 用户问订单异常 | 查订单工具，而不是编造 |
| 用户要求三天计划 | 输出结构化 action plan |
| 用户要求品牌语气 | 使用 memory 中 brand voice |
| 用户多轮修改 | 保持上下文，不重复问已知信息 |

---

## 9. 你真正需要构建的完整 Harness 蓝图

下面是我建议你围绕 OpenAI SDK 构建的完整 harness。

```text
SME Agent Harness

1. User Interface Layer
   - Chat / task input
   - Business dashboard
   - Agent trace timeline
   - Approval panel
   - Output artifacts

2. Product Orchestration Layer
   - Task classifier
   - Workflow planner
   - Manager agent entrypoint
   - Session state manager
   - Approval state machine
   - Failure recovery
   - Cost/latency budget controller

3. OpenAI Runtime Layer
   - Responses API
   - Agents SDK
   - Built-in tools
   - Custom function calling
   - Structured outputs
   - Prompt caching aware prompts
   - Streaming
   - Tracing

4. Agent Layer
   - SME Manager Agent
   - Finance Agent
   - Customer Support Agent
   - Marketing Agent
   - Operations Agent
   - Knowledge Agent
   - Risk / Compliance Agent

5. Tool Layer
   - CRM tools
   - Order tools
   - Finance tools
   - Email tools
   - Calendar tools
   - Document tools
   - Web research tools
   - File search tools
   - Analytics tools

6. Memory Layer
   - Business profile
   - User preferences
   - Brand voice
   - Historical tasks
   - Long-term decisions
   - File knowledge base
   - Retrieved context

7. Safety / Reliability Layer
   - Input guardrails
   - Output guardrails
   - Tool guardrails
   - Human approval
   - Audit logs
   - Retry / fallback
   - Rate limits
   - Secrets management

8. Evaluation Layer
   - Trace review
   - Golden tasks
   - Tool correctness evals
   - Output quality graders
   - Regression checks
```

---

## 10. “哪些已有，哪些要做”总表

| Harness 组件 | OpenAI 已有 | 你还要做 | Hackathon 优先级 |
|---|---|---|---|
| SDK client | 官方 SDK | 选择 TS/Python，封装 backend service | 高 |
| Responses API | 已有 | 作为主调用入口 | 高 |
| Basic model call | 已有 | 不重造 | 高 |
| Streaming | 已有 | 前端 SSE / WebSocket 展示 | 中 |
| Prompt caching | 自动已有 | prompt 结构优化、`cached_tokens` 监控 | 高 |
| Tool calling | 已有机制 | 写业务工具、权限、幂等、审批 | 高 |
| Built-in web search | 已有 | 用于市场/竞品/政策查询 | 中 |
| Built-in file search | 已有 | 文档上传、知识库组织 | 高 |
| Code interpreter | 已有 | 用于财务表格、CSV、数据分析 | 中 |
| Structured outputs | 已有 | 定义业务 schema | 高 |
| Agent loop | Agents SDK 已有 | 设计 agent persona 和工作流 | 高 |
| Handoffs | Agents SDK 已有 | 谨慎使用，只给真正需要接管的 specialist | 中 |
| Agents as tools | Agents SDK 已有 | 作为你的主要 multi-agent 结构 | 高 |
| Guardrails | Agents SDK 框架已有 | 定义 SME 风险规则 | 高 |
| Human review | Agents SDK 支持 | UI 审批流、业务动作冻结/恢复 | 高 |
| Tracing | OpenAI Platform / SDK 已有 | 产品内 trace timeline | 高 |
| Evals | OpenAI Platform 已有 | SME golden dataset | 中 |
| Conversation state | Responses / Conversations / Sessions 已有 | 和业务 memory 区分 | 高 |
| Long-term business memory | 部分可用 File Search 辅助 | 必须自己做 DB / schema / recall | 高 |
| Tool registry | Tool Search 支持 | 业务工具目录、权限、版本 | 中 |
| Cost control | usage 字段 / dashboard | 自己做预算、模型路由、缓存策略 | 高 |
| Secrets / API key safety | 文档指导 | 后端代理、不要前端暴露 key | 高 |
| Business integrations | 不会替你完成 | CRM、订单、邮件、日历、财务接口 | 高 |
| Demo reliability | 不会替你完成 | mock fallback、主路径固定、错误兜底 | 极高 |

---

## 11. Hackathon SME 产品建议：AI Business Operator for SMEs

你的 SME 方向可以这样设计：

> **An AI business operator for small businesses that turns messy daily operations into prioritized actions, drafts, and approvals.**

中文：

> 一个面向中小企业和一人公司的 AI 经营助手，把客服、运营、财务、营销中的重复工作转化为可执行任务、草稿和审批流。

### 11.1 真实问题

SME 的痛点不是“缺一个聊天机器人”，而是：

- 老板每天被订单、客服、现金流、营销、供应商、库存、邮件打断；
- 没有专门的 finance / marketing / ops / support 团队；
- 很多任务不是难，而是重复、碎片、跨系统、没有优先级；
- 现有 AI 工具多数只给建议，不真正进入业务流程；
- 老板不敢让 AI 直接执行高风险操作，需要可控审批。

### 11.2 你的解决方案

你的产品不是普通 chatbot，而是：

```text
SME Operator = Manager Agent + Specialist Agents + Business Tools + Memory + Human Approval
```

核心能力：

1. **理解 business context**：知道公司做什么、卖什么、客户是谁、近期目标是什么。
2. **拆解任务**：把“帮我处理今天的业务”拆成财务、客服、营销、运营。
3. **调用工具**：查订单、查客户、读文档、生成邮件、分析现金流。
4. **形成行动计划**：按影响力和紧急程度排序。
5. **生成可交付物**：邮件草稿、营销文案、客服回复、财务提醒、任务列表。
6. **需要时请求人类审批**：发送邮件、退款、改价格、发布广告前暂停。
7. **积累记忆**：学习老板的品牌语气、偏好、客户处理方式、历史决策。

### 11.3 Demo 主路径

建议你的现场 demo 不要太复杂，做一条非常清楚的路径：

```text
User:
I run a small online coffee bean store. Today I have several customer messages, a late supplier delivery, and weak sales this week. Help me decide what to do first and draft the necessary replies.

System:
1. Manager Agent identifies 3 workstreams:
   - customer support
   - operations / supplier issue
   - marketing / sales recovery

2. Customer Agent checks customer messages and drafts replies.
3. Operations Agent summarizes supplier delay and drafts supplier follow-up.
4. Marketing Agent proposes a weekend campaign.
5. Finance Agent checks whether discount is safe.
6. Manager Agent prioritizes actions.
7. UI shows approval cards:
   - Send customer reply? Approve / edit
   - Send supplier email? Approve / edit
   - Launch campaign draft? Approve / edit
```

### 11.4 为什么这个方案符合评审标准

| 评审标准 | 你的对应表达 |
|---|---|
| Problem Clarity | SME 没有 dedicated team，被重复运营工作压垮 |
| Technical Depth | Responses API + Agents SDK + multi-agent + tools + memory + guardrails + structured outputs |
| Demo Reliability | 固定 1 条业务主路径，mock 数据 + live agent execution + fallback |
| Real-world Viability | 真实 SME 每天都会遇到客服、订单、供应商、营销问题 |
| Pitch Clarity | “AI team for small business owners” 非常容易理解 |

---

## 12. 推荐技术架构：NestJS + OpenAI SDK + Agents SDK

### 12.1 后端模块划分

```text
src/
  ai/
    openai.client.ts
    responses.service.ts
    agents/
      sme-manager.agent.ts
      finance.agent.ts
      support.agent.ts
      marketing.agent.ts
      operations.agent.ts
      knowledge.agent.ts
    tools/
      crm.tools.ts
      orders.tools.ts
      finance.tools.ts
      email.tools.ts
      memory.tools.ts
    schemas/
      sme-plan.schema.ts
      approval.schema.ts
      customer-reply.schema.ts
    guardrails/
      side-effect.guardrail.ts
      financial-advice.guardrail.ts
      pii.guardrail.ts
    tracing/
      trace-recorder.service.ts
  business/
    business-profile.service.ts
    memory.service.ts
    task.service.ts
  approvals/
    approval.service.ts
  demo/
    demo-data.seed.ts
```

### 12.2 请求流

```text
POST /api/sme/run
  ↓
Create task record
  ↓
Load business profile + memory
  ↓
Run SME Manager Agent
  ↓
Manager calls specialist agents/tools
  ↓
Tools read/write mock business DB
  ↓
Guardrails check side effects
  ↓
Return structured plan + trace + approval cards
```

### 12.3 最小数据结构

```ts
type BusinessProfile = {
  id: string;
  name: string;
  industry: string;
  stage: "solo" | "small_team" | "growing";
  location: string;
  brandVoice: string;
  goals: string[];
};

type AgentTraceStep = {
  id: string;
  agent: string;
  action: string;
  tool?: string;
  status: "pending" | "running" | "success" | "approval_required" | "failed";
  summary: string;
};

type ApprovalCard = {
  id: string;
  type: "send_email" | "issue_refund" | "publish_campaign" | "update_record";
  title: string;
  draft: string;
  risk: "low" | "medium" | "high";
  status: "waiting" | "approved" | "rejected" | "edited";
};
```

---

## 13. 你应该怎么向评委解释“基于 OpenAI SDK 的 harness”

你可以这样讲：

> We are not building just another chatbot. We built a reusable SME agent harness on top of OpenAI’s Responses API and Agents SDK. The harness gives the model structured business memory, domain-specific tools, specialist agents, guardrails, approval workflows, and observable traces. OpenAI handles the low-level agent loop, tool-calling interface, structured outputs, and prompt caching; our layer turns those primitives into a real business operating system for small teams.

中文理解：

> 我们不是做一个普通聊天机器人。我们基于 OpenAI Responses API 和 Agents SDK 做了一套可复用的 SME Agent Harness。OpenAI 负责底层模型调用、工具调用、结构化输出、agent loop 和 prompt caching；我们负责把这些能力变成真实小企业能用的业务流程，包括经营记忆、业务工具、多专家协作、人工审批和可观测执行轨迹。

---

## 14. 不要做的事情清单

比赛时间有限，下面这些不要做：

1. 不要自己从零实现一个 tool-call while loop，除非你不用 Agents SDK。
2. 不要自己实现 prompt KV-cache。
3. 不要把所有工具 schema 一股脑塞进 prompt，先控制工具数量。
4. 不要做 10 个行业，先做一个 SME 场景。
5. 不要让 AI 直接执行高风险动作，必须有 approval。
6. 不要把 API key 放前端。
7. 不要只展示聊天输出，要展示 trace、approval、artifact。
8. 不要只说“多 Agent”，要说“减少 SME 重复工作负担”。
9. 不要让 demo 完全依赖实时外部 API，准备 mock fallback。
10. 不要把 long-term memory 和 conversation state 混为一谈。

---

## 15. 必做功能优先级

### P0：一定要有

- OpenAI SDK backend service；
- Responses API 调用；
- SME Manager Agent；
- 2-3 个 specialist agents；
- 3-5 个 mock business tools；
- structured output；
- trace timeline；
- approval cards；
- 一条稳定 demo 主路径。

### P1：有了会显著加分

- File Search 读取 business document / FAQ；
- Prompt caching aware prompt layout；
- usage / cached_tokens 展示；
- guardrail 示例；
- agent-as-tool 架构；
- 任务状态持久化；
- demo fallback。

### P2：时间够再做

- Tool Search；
- Remote MCP；
- Code Interpreter 财务表格分析；
- 多租户权限；
- 实际邮件草稿保存；
- Evals dashboard；
- 真实 SaaS 集成。

---

## 16. 最小可赢版本：3 小时内能做出的版本

如果时间非常紧，你做这个：

```text
SME Daily Operator Demo

Input:
Small business owner describes today's messy operations.

System:
1. Manager Agent classifies task.
2. Calls Support Agent, Marketing Agent, Finance Agent as tools.
3. Uses mock data: customer messages, sales numbers, supplier delay.
4. Produces structured action plan.
5. Generates 3 approval cards.
6. Shows trace timeline.
```

评委看到的是：

- 不是聊天，而是一个可执行 business workflow；
- 有真实场景；
- 有技术深度；
- 有可靠 demo；
- 有可落地商业价值。

---

## 17. 推荐的一页架构图文案

```text
AI Business Operator for SMEs

A reusable OpenAI SDK-based harness that turns daily business chaos into prioritized actions.

OpenAI Layer
- Responses API
- Agents SDK
- Prompt Caching
- Built-in Tools
- Structured Outputs
- Tracing / Evals

Our Harness Layer
- SME Manager Agent
- Specialist Agents
- Business Memory
- Domain Tools
- Guardrails
- Human Approval
- Trace UI

Business Outcome
- Fewer repetitive tasks
- Faster customer replies
- Better daily decisions
- Safer AI execution
```

---

## 18. 官方文档来源索引

> 以下均为 OpenAI 官方文档页面，用于支撑本文判断。

1. OpenAI Libraries / SDK setup: https://developers.openai.com/api/docs/libraries
2. Migrate to Responses API: https://developers.openai.com/api/docs/guides/migrate-to-responses
3. Using tools: https://developers.openai.com/api/docs/guides/tools
4. Function calling: https://developers.openai.com/api/docs/guides/function-calling
5. Structured model outputs: https://developers.openai.com/api/docs/guides/structured-outputs
6. Conversation state: https://developers.openai.com/api/docs/guides/conversation-state
7. Prompt caching: https://developers.openai.com/api/docs/guides/prompt-caching
8. Agents SDK overview: https://developers.openai.com/api/docs/guides/agents
9. Running agents: https://developers.openai.com/api/docs/guides/agents/running-agents
10. Orchestration and handoffs: https://developers.openai.com/api/docs/guides/agents/orchestration
11. Guardrails and human review: https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
12. Integrations and observability: https://developers.openai.com/api/docs/guides/agents/integrations-observability
13. Evaluate agent workflows: https://developers.openai.com/api/docs/guides/agent-evals

---

## 19. 最终建议

你的比赛项目应该明确说：

> We use OpenAI SDK as the agentic runtime, and build the SME business harness above it.

最强的产品定位是：

```text
AI Business Operator for SMEs:
A safe, observable, approval-based AI team for small business owners.
```

你的技术亮点不是“我会调 OpenAI API”，而是：

1. 你知道哪些能力已经由 OpenAI SDK 提供；
2. 你没有重复造底层 runtime；
3. 你把能力组合成真实 SME 工作流；
4. 你有安全审批和 trace；
5. 你让评委看到 AI agent 从“会聊天”变成“能减轻重复工作负担”。

