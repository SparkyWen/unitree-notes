# Codex OAuth 接入与使用深度调研：面向 Hackathon Demo 的 OpenAI Harness 方案

> 生成日期：2026-04-28  
> 目标：帮助你基于 **Codex 的 ChatGPT OAuth / subscription 登录方式**，搭建一个可展示、可运行、可解释的 agent harness。  
> 结论先行：如果只是 Hackathon demo，并且你想展示“像 Claude Code / Claude SDK 一样的本地 agent harness”，**Codex OAuth / subscription 是合理路线**；但如果要做正式多租户 SME SaaS，仍应迁移到 OpenAI API / Responses API / Agents SDK。

---

## 0. 你现在真正要做的事情

你不是简单要“调用模型 API”。你要的是：

```text
用户 / 参赛者 / SME 场景输入
  ↓
Codex OAuth 登录后的本地 agent harness
  ↓
模型推理 + 文件读写 + 命令执行 + 工具调用 + MCP + 计划/执行/验证循环
  ↓
生成真实 artifact：文档、代码、页面、流程配置、业务报告、自动化脚本
```

这和普通 OpenAI SDK 后端调用不一样。普通 API 调用的核心是：

```text
你的后端
  ↓
OpenAI API key
  ↓
Responses API
  ↓
返回模型结果
```

而 Codex OAuth 路线更像：

```text
你的本地机器 / 可信运行环境
  ↓
codex login --device-auth
  ↓
ChatGPT / Codex subscription session
  ↓
Codex CLI / Codex SDK / Codex MCP server
  ↓
一个已经封装好的 coding-agent harness
```

因此，你的 Hackathon 策略应该是：

> **用 Codex OAuth 快速拿到“可执行 agent harness”，把精力放在 SME 业务层，而不是自己重造底层 agent loop。**

---

## 1. 官方资料地图：你应该看哪些文档

下面是本次调研中最重要的官方资料入口。

### 1.1 Codex 总览与 Quickstart

| 资料 | 作用 |
|---|---|
| OpenAI Codex 总览 | 了解 Codex 是什么、哪些 ChatGPT plan 包含 Codex、适合什么任务 |
| Codex Quickstart | 安装、登录、Agent mode、基本使用 |
| Codex CLI Reference | 查看 `codex login`、`codex exec`、`codex mcp-server`、`codex mcp` 等命令 |
| Codex Changelog | 查看当前模型、功能、CLI 版本变化 |

重要事实：

- Codex 是 OpenAI 的 software development coding agent。
- ChatGPT Plus、Pro、Business、Edu、Enterprise 等计划包含 Codex。
- Codex 支持在 CLI、IDE extension、Codex app、Codex web/cloud 等不同形态中使用。
- Codex Agent mode 默认可以读文件、运行命令、修改项目目录。

参考：

- https://developers.openai.com/codex
- https://developers.openai.com/codex/quickstart
- https://developers.openai.com/codex/cli/reference
- https://developers.openai.com/codex/changelog

---

### 1.2 Codex Authentication / OAuth / Device code

这是你最关心的部分。

官方明确：Codex 使用 OpenAI models 时支持两种登录方式：

```text
1. Sign in with ChatGPT for subscription access
2. Sign in with an API key for usage-based access
```

其中：

- Codex Cloud 要求 ChatGPT 登录。
- Codex CLI 和 IDE Extension 同时支持 ChatGPT 登录与 API key 登录。
- ChatGPT 登录可走 browser OAuth，也可走 device code flow。
- device code flow 适合远程服务器、headless 机器、localhost callback 失败的环境。

参考：

- https://developers.openai.com/codex/auth
- https://developers.openai.com/codex/auth/ci-cd-auth

---

### 1.3 Codex Agent Loop / Harness 原理

OpenAI 官方博客《Unrolling the Codex agent loop》非常关键，因为它解释了 Codex 为什么能作为 harness。

核心要点：

- Codex 的核心是 agent loop。
- Agent loop 负责用户输入、模型推理、工具调用、观察结果、再次推理、最终返回。
- Codex CLI 实际通过 Responses API 发送模型请求。
- ChatGPT 登录和 API key 登录会使用不同 endpoint：
  - ChatGPT login：`https://chatgpt.com/backend-api/codex/responses`
  - API key：`https://api.openai.com/v1/responses`
- Codex 自己处理工具列表、sandbox instructions、AGENTS.md、skills、MCP tools、上下文压缩、prompt caching 友好结构等问题。

这篇文章直接证明：

> Codex 不是一个简单 CLI 包装器，而是一个已经实现了 agent loop、工具执行、上下文管理、权限边界和 prompt 结构的 harness。

参考：

- https://openai.com/index/unrolling-the-codex-agent-loop/

---

### 1.4 Codex SDK / MCP / App Server

如果你想把 Codex 放进自己的程序，有三条路线。

| 路线 | 作用 | 适合你吗 |
|---|---|---|
| Codex CLI / `codex exec` | 最快做 demo，直接从程序调用命令行 | 非常适合 |
| Codex SDK | 在 Node.js 服务端程序中控制 Codex thread | 非常适合 |
| Codex MCP Server + Agents SDK | 把 Codex 暴露成 MCP 工具，由另一个 agent 调用 | 适合高级多 agent demo |
| Codex App Server | 深度集成：auth、conversation history、approvals、streamed events | 适合后续做类 IDE / rich client 产品 |

参考：

- https://developers.openai.com/codex/sdk
- https://developers.openai.com/codex/guides/agents-sdk
- https://developers.openai.com/codex/app-server
- https://developers.openai.com/codex/mcp

---

### 1.5 配置、安全、AGENTS.md、MCP、Skills、Plugins

这些决定你的 demo 是否像一个真正 harness。

| 能力 | 文档 |
|---|---|
| Config basics | `~/.codex/config.toml` 和项目级 `.codex/config.toml` |
| Config reference | 所有配置项 |
| Sandboxing | 限制 Codex 命令执行边界 |
| Agent approvals & security | 审批、网络访问、安全边界 |
| Rules | 精细控制命令 allow / prompt / forbidden |
| AGENTS.md | 给 Codex 自动加载项目规则和上下文 |
| MCP | 接外部工具和服务 |
| Skills | 复用工作流 |
| Plugins | 分发 skills、app integrations、MCP servers |
| Subagents | 并行专门 agent 工作流 |

参考：

- https://developers.openai.com/codex/config-basic
- https://developers.openai.com/codex/config-reference
- https://developers.openai.com/codex/concepts/sandboxing
- https://developers.openai.com/codex/agent-approvals-security
- https://developers.openai.com/codex/rules
- https://developers.openai.com/codex/guides/agents-md
- https://developers.openai.com/codex/mcp
- https://developers.openai.com/codex/skills
- https://developers.openai.com/codex/plugins
- https://developers.openai.com/codex/subagents

---

## 2. Codex OAuth / subscription 方式到底怎么工作

### 2.1 登录方式区别

| 方式 | 命令 / 配置 | 费用来源 | 适合场景 |
|---|---|---|---|
| ChatGPT OAuth 登录 | `codex login` | ChatGPT / Codex subscription / credits | 本地开发、Hackathon demo、个人可信机器 |
| Device code OAuth | `codex login --device-auth` | ChatGPT / Codex subscription / credits | 远程服务器、无浏览器机器、SSH 环境 |
| API key 登录 | API key / stdin / auth config | OpenAI Platform API 计费 | CI/CD、生产自动化、团队可控计费 |

你要的是第二种：

```bash
codex login --device-auth
```

它会让你：

```text
1. 终端输出登录链接和一次性 code
2. 你在浏览器打开链接
3. 登录 ChatGPT / OpenAI account
4. 输入或确认 code
5. Codex CLI 缓存登录态
6. 后续 CLI / SDK / IDE extension 可以复用登录态
```

### 2.2 device auth 前置条件

官方文档提到，device code login 需要：

```text
个人账号：在 ChatGPT security settings 启用 device code login
Workspace：由 workspace admin 在权限里启用 device code login
```

如果 device code login 未启用，Codex 会回退到标准 browser-based login flow。

### 2.3 登录态保存位置

Codex 会缓存登录信息：

```text
~/.codex/auth.json
```

或者使用系统 credential store。

可通过配置控制：

```toml
# ~/.codex/config.toml
# file | keyring | auto
cli_auth_credentials_store = "keyring"
```

含义：

| 值 | 含义 |
|---|---|
| `file` | 存在 `~/.codex/auth.json` |
| `keyring` | 存在系统凭证存储 |
| `auto` | 优先系统凭证，不可用时退回文件 |

重要安全提示：

> `~/.codex/auth.json` 包含 access tokens，要像密码一样保护；不要提交到 GitHub，不要贴给别人，不要放进前端，不要放在公开服务器里给陌生用户共享。

### 2.4 ChatGPT OAuth 登录是否会自动刷新

官方文档说明：

- Codex 使用 ChatGPT 登录时，会在使用中自动刷新 token。
- 因此活跃 session 通常不需要频繁重新浏览器登录。
- CLI 和 IDE Extension 共享同一套 cached login details。
- 在其中一个地方 logout，会影响另一个地方。

这就是它适合 demo 的原因：

```text
一次登录
  ↓
多次调用 Codex CLI / SDK / IDE
  ↓
持续使用同一个 Codex subscription session
```

---

## 3. 最小可用：安装、OAuth 登录、验证

### 3.1 安装 Codex CLI

```bash
npm install -g @openai/codex
```

检查版本：

```bash
codex --version
```

升级：

```bash
npm install -g @openai/codex@latest
```

### 3.2 使用 device auth 登录

```bash
codex login --device-auth
```

然后按终端提示：

```text
1. 打开验证链接
2. 登录你的 ChatGPT / OpenAI 账号
3. 输入一次性 code
4. 回到终端
```

### 3.3 检查登录状态

```bash
codex login status
```

如果你希望明确使用 ChatGPT 登录，而不是 API key：

```toml
# ~/.codex/config.toml
forced_login_method = "chatgpt"
```

如果你在团队 workspace 中，还可以限制 workspace：

```toml
forced_chatgpt_workspace_id = "00000000-0000-0000-0000-000000000000"
```

### 3.4 第一个测试命令

```bash
codex "Explain this project structure and suggest a 3-step plan to improve it."
```

或者非交互执行：

```bash
codex exec --json "Create a concise SME automation product plan for a small tutoring business."
```

---

## 4. 你的 Hackathon 推荐架构

你想做 SMEs 方向，并且打算用 Codex OAuth。最推荐的 demo 架构是：

```text
Frontend Demo Page
  ↓
Local Backend / Node.js API
  ↓
Codex SDK 或 codex exec wrapper
  ↓
Codex OAuth session
  ↓
Workspace / templates / tools / MCP servers
  ↓
Generated SME artifacts
```

### 4.1 你的 demo 不应该只是聊天

不要做成：

```text
老板问问题 → AI 回答建议
```

要做成：

```text
老板输入业务痛点
  ↓
Codex harness 分析业务
  ↓
自动生成 SME operating workspace
  ↓
创建文档、流程、客户回复模板、营销计划、报表、页面、自动化脚本
  ↓
展示这些真实文件和页面
```

### 4.2 推荐 demo 名称

```text
SME Agent Harness
AI Business Operator for Small Businesses
One-person Company Operating System powered by Codex
```

### 4.3 推荐 demo 主线

以小型补习机构为例：

```text
业务场景：
一家小型 tutoring studio，有 3 位老师、80 个学生、每天大量家长消息、课程安排、学生反馈、付款提醒。

用户输入：
“我想把每天重复的家长沟通、排课、学生周报和付款提醒自动化。”

Codex harness 输出：
1. business_diagnosis.md
2. agent_workflow.json
3. parent_reply_templates.md
4. weekly_student_report_template.md
5. payment_reminder_plan.md
6. dashboard.html / dashboard.tsx
7. implementation_plan.md
```

---

## 5. 方式一：直接使用 Codex CLI / `codex exec`

这是最快、最稳、最适合比赛的方式。

### 5.1 基础调用

```bash
codex exec --json "Analyze this SME business and generate an automation plan."
```

### 5.2 指定工作目录

```bash
codex exec \
  --cd ./sme-demo \
  --sandbox workspace-write \
  --json \
  "Generate files for an AI business operator demo."
```

### 5.3 推荐 prompt

```bash
codex exec --cd ./sme-demo --sandbox workspace-write --json '
You are building a hackathon demo called SME Agent Harness.

Target user:
A small tutoring business owner.

Goal:
Turn the owner’s repetitive work into a set of AI-generated operational artifacts.

Please create the following files:
1. outputs/business_diagnosis.md
2. outputs/agent_workflow.json
3. outputs/parent_reply_templates.md
4. outputs/weekly_student_report_template.md
5. outputs/payment_reminder_plan.md
6. outputs/demo_script.md

Requirements:
- The result must be practical for a real small business.
- Clearly separate automation and human approval.
- Explain how Codex acts as the execution harness.
- Do not use fake unsupported claims.
'
```

### 5.4 Node.js 封装 `codex exec`

文件：`src/codex-exec-runner.ts`

```ts
import { spawn } from "child_process";

export type CodexExecOptions = {
  cwd: string;
  prompt: string;
  sandbox?: "read-only" | "workspace-write" | "full-access";
};

export function runCodexExec(options: CodexExecOptions): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      "codex",
      [
        "exec",
        "--cd",
        options.cwd,
        "--sandbox",
        options.sandbox ?? "workspace-write",
        "--json",
        options.prompt,
      ],
      {
        stdio: ["ignore", "pipe", "pipe"],
      }
    );

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("close", (code) => {
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(new Error(`codex exec failed with code ${code}\n${stderr}`));
      }
    });
  });
}
```

调用示例：

```ts
import { runCodexExec } from "./codex-exec-runner";

async function main() {
  const output = await runCodexExec({
    cwd: process.cwd(),
    sandbox: "workspace-write",
    prompt: `
Build a SME automation demo.
Create outputs/business_diagnosis.md and outputs/agent_workflow.json.
Focus on small business repetitive operations.
`,
  });

  console.log(output);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
```

优点：

```text
- 不需要研究复杂 SDK API
- 复用 Codex OAuth 登录态
- 适合本地 demo
- 可以真实创建文件
- 评委容易看到 agent 执行痕迹
```

缺点：

```text
- 进程调用成本较高
- 流式事件处理不如 SDK / app-server 精细
- 不适合大规模生产服务
```

---

## 6. 方式二：使用 Codex SDK

Codex SDK 更适合你做自己的 Node.js harness。

官方 TypeScript SDK 示例核心是：

```ts
import { Codex } from "@openai/codex-sdk";

const codex = new Codex();
const thread = codex.startThread();
const result = await thread.run("Make a plan to diagnose and fix the CI failures");
console.log(result);
```

### 6.1 初始化项目

```bash
mkdir sme-codex-harness
cd sme-codex-harness
npm init -y
npm install @openai/codex-sdk express cors zod dotenv
npm install -D typescript tsx @types/node @types/express @types/cors
npx tsc --init
```

先完成 OAuth 登录：

```bash
codex login --device-auth
codex login status
```

### 6.2 Codex SDK 核心文件

文件：`src/sme-codex-harness.ts`

```ts
import { Codex } from "@openai/codex-sdk";
import { z } from "zod";

export const SMEInputSchema = z.object({
  businessType: z.string(),
  businessGoal: z.string(),
  painPoints: z.array(z.string()).default([]),
  availableData: z.array(z.string()).default([]),
});

export type SMEInput = z.infer<typeof SMEInputSchema>;

function buildPrompt(input: SMEInput): string {
  return `
You are Codex acting as an execution harness for an SME AI Business Operator demo.

Business type:
${input.businessType}

Business goal:
${input.businessGoal}

Pain points:
${input.painPoints.map((x, i) => `${i + 1}. ${x}`).join("\n")}

Available data:
${input.availableData.map((x, i) => `${i + 1}. ${x}`).join("\n")}

Task:
Create a practical SME automation plan and generate implementation-ready artifacts.

Required output:
1. Problem diagnosis
2. Repetitive-work map
3. Agent workflow design
4. Human approval checkpoints
5. Files that should be generated
6. 7-day MVP plan
7. Demo script for hackathon judges

Be concrete, operational, and suitable for a small business owner.
`;
}

export async function runSMECodexHarness(rawInput: unknown) {
  const input = SMEInputSchema.parse(rawInput);

  const codex = new Codex();
  const thread = codex.startThread();

  const result = await thread.run(buildPrompt(input));

  return result;
}
```

### 6.3 Express API 包装

文件：`src/server.ts`

```ts
import express from "express";
import cors from "cors";
import { runSMECodexHarness } from "./sme-codex-harness";

const app = express();
app.use(cors());
app.use(express.json({ limit: "2mb" }));

app.post("/api/sme-harness", async (req, res) => {
  try {
    const result = await runSMECodexHarness(req.body);
    res.json({ ok: true, result });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

app.listen(3001, () => {
  console.log("SME Codex Harness API running on http://localhost:3001");
});
```

运行：

```bash
npx tsx src/server.ts
```

测试：

```bash
curl -X POST http://localhost:3001/api/sme-harness \
  -H "Content-Type: application/json" \
  -d '{
    "businessType": "small tutoring studio",
    "businessGoal": "reduce daily admin workload by 50%",
    "painPoints": [
      "too many parent messages",
      "manual lesson scheduling",
      "weekly progress reports take too long",
      "payment reminders are inconsistent"
    ],
    "availableData": [
      "student spreadsheet",
      "lesson timetable",
      "parent message examples",
      "payment status sheet"
    ]
  }'
```

### 6.4 什么时候用 SDK，而不是 `codex exec`

| 需求 | 选择 |
|---|---|
| 最快跑通 demo | `codex exec` |
| 想在 Node 服务中保持 thread | Codex SDK |
| 想继续同一个 conversation | Codex SDK `thread.run()` |
| 想恢复历史 thread | Codex SDK `resumeThread(threadId)` |
| 想做 rich client / streamed events | App Server |

---

## 7. 方式三：Codex MCP Server + OpenAI Agents SDK

这是最像“高级 harness”的做法。

Codex CLI 可以作为 MCP server，被 OpenAI Agents SDK 调用。官方 guide 说明，Codex MCP server 暴露两个工具：

```text
codex()        开始一个 Codex conversation
codex-reply()  继续一个已有 Codex conversation
```

### 7.1 适合场景

```text
Planner Agent
  ↓
调用 Codex MCP
  ↓
Codex 负责工程实现 / 文件生成 / 命令执行
  ↓
Reviewer Agent 检查结果
  ↓
Final Agent 输出 demo summary
```

也就是说，你可以让 Codex 成为更大 agent 系统中的“执行工程师”。

### 7.2 安装

```bash
mkdir sme-codex-mcp
cd sme-codex-mcp
python -m venv .venv
source .venv/bin/activate
pip install --upgrade openai openai-agents python-dotenv
```

确保 Codex 已登录：

```bash
codex login --device-auth
codex login status
```

如果 Agents SDK 需要 API key 做外层 orchestration：

```bash
printf "OPENAI_API_KEY=sk-..." > .env
```

### 7.3 最小 MCP 启动示例

文件：`codex_mcp_check.py`

```python
import asyncio
from agents.mcp import MCPServerStdio

async def main() -> None:
    async with MCPServerStdio(
        name="Codex CLI",
        params={
            "command": "npx",
            "args": ["-y", "codex", "mcp-server"],
        },
        client_session_timeout_seconds=360000,
    ):
        print("Codex MCP server started.")

if __name__ == "__main__":
    asyncio.run(main())
```

运行：

```bash
python codex_mcp_check.py
```

### 7.4 SME 多 Agent 示例

文件：`sme_agent_team.py`

```python
import asyncio
from agents import Agent, Runner
from agents.mcp import MCPServerStdio

SME_TASK = """
We are building a hackathon demo called SME Agent Harness.

Target user:
A small tutoring business owner.

Goal:
Use Codex as the execution harness to generate practical business automation artifacts.

The system should produce:
1. business diagnosis
2. agent workflow
3. parent reply templates
4. weekly student report template
5. payment reminder plan
6. demo script for judges

Make the output practical and easy to demo.
"""

async def main() -> None:
    async with MCPServerStdio(
        name="Codex CLI",
        params={
            "command": "npx",
            "args": ["-y", "codex", "mcp-server"],
        },
        client_session_timeout_seconds=360000,
    ) as codex_mcp_server:
        planner = Agent(
            name="SME Product Planner",
            instructions=(
                "You are a product strategist for SME automation. "
                "Use Codex when you need to create concrete files, implementation plans, "
                "or technical artifacts."
            ),
            mcp_servers=[codex_mcp_server],
        )

        result = await Runner.run(planner, SME_TASK)
        print(result.final_output)

if __name__ == "__main__":
    asyncio.run(main())
```

这个架构最适合你在评审面前讲：

> We use OpenAI Agents SDK for orchestration and Codex MCP as the execution harness.

但如果你想完全使用 Codex subscription，避免外层 API key 依赖，比赛当天最稳仍然是 CLI / SDK 路线。

---

## 8. 方式四：Codex App Server

Codex App Server 是 Codex 用来支持 rich clients 的接口，例如 VS Code extension。

官方定位：

```text
Use it when you want a deep integration inside your own product:
- authentication
- conversation history
- approvals
- streamed agent events
```

这条路线适合你后续做：

```text
自己的 Codex-like client
自己的 agent desktop app
自己的 SME command center
自己的 rich frontend with approvals and streaming events
```

但它比 CLI / SDK 复杂。Hackathon 当天不建议优先做。

参考：

- https://developers.openai.com/codex/app-server

---

## 9. Codex 配置：让 demo 更稳定

### 9.1 用户级配置

Codex 默认用户配置：

```text
~/.codex/config.toml
```

项目级配置：

```text
.codex/config.toml
```

CLI 和 IDE extension 共享配置。

### 9.2 推荐 Hackathon 配置

```toml
# ~/.codex/config.toml

# 明确使用 ChatGPT 登录方式，避免不小心走 API key 计费
forced_login_method = "chatgpt"

# 凭证优先存入系统 keyring
cli_auth_credentials_store = "keyring"

# 默认模型，可按你实际可用模型调整
model = "gpt-5.4"

# 默认 sandbox：允许写当前 workspace，但不要 full access
sandbox_mode = "workspace-write"

# 对越界操作请求人工确认
approval_policy = "on-request"
```

如果 `forced_login_method = "chatgpt"` 导致环境报错，可以先删除该行，用 `codex login status` 检查当前实际登录方式。

### 9.3 避免误用 API key

社区里有用户反馈过一种情况：以为自己用 ChatGPT 登录，结果 Codex 发现并使用了环境变量里的 `OPENAI_API_KEY`，导致产生 API charge。

因此比赛环境里，如果你想确保走 subscription：

```bash
unset OPENAI_API_KEY
unset OPENAI_BASE_URL
codex login status
```

或者在配置中强制：

```toml
forced_login_method = "chatgpt"
```

---

## 10. AGENTS.md：你必须写

Codex 会自动读取 `AGENTS.md`，这是你把“业务 harness 规则”注入 Codex 的最好方式。

### 10.1 放置位置

全局：

```text
~/.codex/AGENTS.md
```

项目级：

```text
./AGENTS.md
```

更细粒度目录：

```text
./backend/AGENTS.md
./frontend/AGENTS.md
./workflows/AGENTS.md
```

Codex 会按目录层级加载更具体的规则。

### 10.2 推荐 SME Hackathon `AGENTS.md`

文件：`AGENTS.md`

```md
# SME Agent Harness Instructions

## Product Goal

We are building a hackathon demo called **SME Agent Harness**.
The product helps small business owners reduce repetitive operational work by turning business intent into concrete artifacts, workflows, templates, and automation plans.

## Target User

Small business owners with no dedicated operations team, such as:

- tutoring studios
- small clinics
- restaurants
- local service providers
- solo founders
- small e-commerce stores

## Core Demo Principle

Do not produce only advice. Always create concrete operational artifacts when possible.

Examples of artifacts:

- business diagnosis markdown
- agent workflow JSON
- customer reply templates
- weekly report templates
- payment reminder plan
- dashboard page
- task execution checklist
- human approval checklist

## Safety and Human Approval

Always separate:

1. fully automatable actions
2. actions requiring human approval
3. actions that should not be automated yet

Never claim the system has sent emails, charged customers, accessed private data, or completed real external actions unless a real tool call has been configured and executed.

## Output Style

Use concise, practical, investor-friendly language.
Every output should be understandable to a non-technical small business owner.

## Verification

Before finishing:

- list the files created or changed
- explain how to demo them
- identify the next technical step
```

### 10.3 为什么它重要

AGENTS.md 可以让你不用每次 prompt 都重复：

```text
- 产品定位
- 目标用户
- 风格要求
- 安全边界
- 文件生成要求
- demo 叙事
```

这就是 harness 的“长期系统提示层”。

---

## 11. Sandbox / Approval / Rules：比赛时不要 full access

### 11.1 Sandbox 是什么

Sandbox 定义 Codex 能在什么边界内自动行动：

```text
- 能不能写文件
- 能写哪些目录
- 能不能访问网络
- 命令执行是否受限制
```

Approval policy 决定什么时候要停下来问你。

推荐比赛配置：

```text
sandbox_mode = workspace-write
approval_policy = on-request
```

不建议默认：

```text
sandbox_mode = full-access
approval_policy = never
```

除非你非常确定环境是干净 demo sandbox。

### 11.2 Rules 示例

你可以用 rules 禁止危险命令。

```toml
[[rules]]
pattern = ["rm", "-rf"]
decision = "forbidden"
justification = "Dangerous destructive command. Use a safer cleanup script instead."

[[rules]]
pattern = ["git", "push"]
decision = "prompt"
justification = "Pushing code requires human approval during hackathon demo."

[[rules]]
pattern = ["npm", "install"]
decision = "prompt"
justification = "Installing dependencies may access network and change lockfiles."
```

### 11.3 评审时可以怎么讲

> We do not let the agent blindly execute everything. Codex runs inside a workspace-write sandbox with approval gates. The harness separates autonomous generation from human-approved external actions.

这对 SMEs 特别重要，因为小企业涉及客户、付款、消息和隐私数据。

---

## 12. MCP：让 Codex 接外部工具

Codex 支持 MCP servers。MCP 是把外部工具暴露给 agent 的通道。

### 12.1 用 CLI 添加 MCP server

```bash
codex mcp add context7 -- npx -y @upstash/context7-mcp
```

查看：

```bash
codex mcp --help
```

在 Codex TUI 里：

```text
/mcp
```

### 12.2 项目级 MCP 配置

```toml
# .codex/config.toml

[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
```

### 12.3 对 SME demo 有价值的 MCP 类型

| MCP 类型 | 用途 |
|---|---|
| 文件 / 文档 MCP | 读取业务文档、生成报告 |
| Google Drive / Sheets | 读取小企业表格 |
| Gmail / Outlook | 起草客户回复 |
| Calendar | 生成排课和提醒 |
| Browser / Playwright | 展示 dashboard 和网页验证 |
| GitHub / Gitea | 管理项目版本 |
| Figma / design MCP | 快速生成前端设计 |

### 12.4 重要安全边界

MCP 工具不是 Codex 本身的 shell sandbox。外部 MCP server 需要自己实现权限和 guardrails。对于真实 SME 数据，必须有：

```text
- OAuth scope
- approval gate
- audit log
- no silent external action
- read/draft/send 分离
```

比赛 demo 可以只做 mock 工具或本地文件工具，避免真实客户数据风险。

---

## 13. Skills / Plugins / Subagents：Codex 里的可复用 harness 层

### 13.1 Skills

Skills 是复用工作流的 authoring format。

你可以把“如何为 SME 生成自动化方案”做成一个 skill：

```text
skills/sme-operator/SKILL.md
```

内容包括：

```md
# SME Operator Skill

Use this skill when the user asks to automate repetitive small business work.

Steps:
1. Identify business type.
2. Identify repetitive tasks.
3. Map data sources.
4. Separate automation from human approval.
5. Generate operational artifacts.
6. Produce a demo-ready implementation plan.
```

### 13.2 Plugins

Plugins 可以打包：

```text
- skills
- app integrations
- MCP servers
```

如果你未来要把 SME workflow 作为可安装能力分发，可以做成 plugin。

### 13.3 Subagents

Codex 支持 subagent workflows：

```text
主 agent
  ├─ Market Research subagent
  ├─ Workflow Design subagent
  ├─ Frontend Builder subagent
  ├─ Report Writer subagent
  └─ Reviewer subagent
```

这对你 Hackathon 演示“多 agent 协作”很有价值。

---

## 14. Codex OAuth 路线的最佳 demo 实现方案

### 14.1 文件结构

```text
sme-codex-demo/
  AGENTS.md
  package.json
  src/
    server.ts
    codex-exec-runner.ts
    prompts.ts
  public/
    index.html
  outputs/
    .gitkeep
  workflows/
    .gitkeep
  .codex/
    config.toml
```

### 14.2 package.json

```json
{
  "name": "sme-codex-demo",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "tsx src/server.ts",
    "codex:login": "codex login --device-auth",
    "codex:status": "codex login status",
    "demo:generate": "tsx src/run-demo.ts"
  },
  "dependencies": {
    "@openai/codex-sdk": "latest",
    "cors": "latest",
    "express": "latest",
    "zod": "latest"
  },
  "devDependencies": {
    "@types/cors": "latest",
    "@types/express": "latest",
    "@types/node": "latest",
    "tsx": "latest",
    "typescript": "latest"
  }
}
```

### 14.3 prompts.ts

```ts
export function buildSMEDemoPrompt(input: {
  businessType: string;
  goal: string;
  painPoints: string[];
}) {
  return `
You are Codex running as an execution harness for a hackathon demo.

Product:
SME Agent Harness — AI Business Operator for Small Businesses.

Business type:
${input.businessType}

Goal:
${input.goal}

Pain points:
${input.painPoints.map((x, i) => `${i + 1}. ${x}`).join("\n")}

Create the following files under outputs/:

1. business_diagnosis.md
2. repetitive_work_map.md
3. agent_workflow.json
4. customer_reply_templates.md
5. weekly_report_template.md
6. human_approval_checklist.md
7. judge_demo_script.md

Create a simple dashboard file under public/demo-dashboard.html that summarizes the workflow.

Requirements:
- Be practical for a real small business.
- Do not claim external emails/messages were sent.
- Separate draft generation from approved execution.
- Explain why Codex is used as the local execution harness.
- Keep the output judge-friendly.
`;
}
```

### 14.4 run-demo.ts

```ts
import { runCodexExec } from "./codex-exec-runner";
import { buildSMEDemoPrompt } from "./prompts";

async function main() {
  const prompt = buildSMEDemoPrompt({
    businessType: "small tutoring studio",
    goal: "reduce repetitive admin workload by 50%",
    painPoints: [
      "parents ask repeated questions every day",
      "lesson scheduling is manual",
      "weekly progress reports take too long",
      "payment reminders are inconsistent",
    ],
  });

  const result = await runCodexExec({
    cwd: process.cwd(),
    sandbox: "workspace-write",
    prompt,
  });

  console.log(result);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
```

运行流程：

```bash
npm install
npm run codex:login
npm run codex:status
npm run demo:generate
```

---

## 15. 远程服务器 / VPS / Headless 环境

你之前经常在 VPS 上开发，所以这部分很关键。

### 15.1 首选：device auth

```bash
ssh ubuntu@your-vps
codex login --device-auth
```

然后在你本地浏览器打开链接，输入 code。

### 15.2 如果 device auth 不可用

官方 fallback：在有浏览器的机器上登录，然后复制 auth cache。

```bash
# 本地机器
codex login
ls ~/.codex/auth.json

# 复制到远程机器
ssh user@remote 'mkdir -p ~/.codex'
scp ~/.codex/auth.json user@remote:~/.codex/auth.json
```

或者：

```bash
ssh user@remote 'mkdir -p ~/.codex && cat > ~/.codex/auth.json' < ~/.codex/auth.json
```

安全警告：

```text
这只能用于你自己控制的可信机器。
不要把 auth.json 放进公开 repo、公共服务器、共享容器、前端包或 CI 日志。
```

### 15.3 SSH localhost callback 转发

如果 standard browser login 依赖 localhost callback，可以转发：

```bash
ssh -L 1455:localhost:1455 user@remote
```

然后在该 SSH session 里运行：

```bash
codex login
```

---

## 16. CI/CD 中维护 Codex account auth

官方明确说：

> 自动化的默认推荐是 API key。只有当你确实需要以 Codex account 身份运行 workflow 时，才使用维护 Codex account auth 的高级方案。

也就是说，比赛 demo 可以用 Codex OAuth；生产 CI/CD 更建议 API key。

如果你仍要在可信 CI/CD runner 中使用 Codex OAuth，需要让 Codex 自己刷新 `auth.json`，并在 job 之间保存更新后的 auth cache。不要自己调用 OAuth token endpoint。

这适合：

```text
- 私有 runner
- 你自己的可信机器
- hackathon demo runner
- 内部工具
```

不适合：

```text
- public CI runner
- 开源项目共享 token
- 多用户 SaaS 后端
```

参考：

- https://developers.openai.com/codex/auth/ci-cd-auth

---

## 17. 费用、credits 与 subscription 使用

### 17.1 Codex 与 ChatGPT plan

OpenAI help 文档说明，Codex usage limits 取决于你的 plan。任务越复杂、代码库越大、session 越长、上下文越多，消耗越高。

参考：

- https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan

### 17.2 Flexible credits

如果你 hit usage limit，可能会看到 “Add credits”。Codex credits 可以在 Codex Settings → Usage → Credits 查看和购买。

参考：

- https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-plus-pro

### 17.3 Codex rate card

Codex flexible credits 的消耗按 token usage 计算，包括：

```text
- input tokens
- cached input tokens
- output tokens
```

这说明：

```text
长 prompt、大文件、长会话、多工具输出、反复失败重试都会烧 credits。
```

参考：

- https://help.openai.com/en/articles/20001106-codex-rate-card

### 17.4 你的比赛 credits 使用策略

推荐：

| 阶段 | 预算 |
|---|---:|
| 架构设计 / prompt / AGENTS.md | 10% |
| Codex 生成项目与核心文件 | 30% |
| UI / dashboard / demo artifacts | 20% |
| debug / 修复 / polish | 25% |
| 决赛备用 | 15% |

避免：

```text
- 一上来让 Codex 全仓库乱扫
- 反复让它重写整个项目
- 每次 prompt 都贴超长背景
- 没有 AGENTS.md 导致重复解释
- 不做 mock，直接连真实工具反复测试
```

---

## 18. 社区论坛调研：大家遇到什么问题

OpenAI Community 上有不少 Codex CLI / OAuth / MCP 讨论。它们不是官方规范，但有实用参考价值。

### 18.1 常见问题

| 问题 | 说明 |
|---|---|
| ChatGPT 登录后出现 401 / 403 / token exchange failed | 常见于账号迁移、workspace 权限、device auth 未启用、网络/代理问题 |
| 以为用 ChatGPT subscription，结果走了 API key | 环境变量 `OPENAI_API_KEY` 或配置优先级导致 |
| VS Code extension 与 CLI 登录态共享问题 | 需要理解 `auth.json` / keyring / config.toml |
| MCP server 是否真的被使用 | 社区有人希望 UI 更清楚展示 skill/MCP 使用状态 |
| 多 agent / thread 通信 | 社区有人探索 Codex LAN bridge、context handoff MCP 等模式 |

### 18.2 对你的实战建议

```bash
# 运行 demo 前检查
codex login status

# 避免误走 API key
unset OPENAI_API_KEY
unset OPENAI_BASE_URL

# 登录异常时备份 auth cache
mv ~/.codex/auth.json ~/.codex/auth.json.bak
codex login --device-auth

# 确认版本
codex --version
npm install -g @openai/codex@latest
```

### 18.3 参考社区入口

- https://community.openai.com/c/codex/codex-cli/39
- https://community.openai.com/t/connect-codex-to-openai-developer-docs-via-mcp/1371352
- https://community.openai.com/t/unexpected-api-charges-from-codex-cli-despite-chatgpt-login/1358277
- https://community.openai.com/t/stream-error-exceeded-retry-limit-last-status-401-unauthorized-with-chatgpt-signin-after-account-migration/1363168

---

## 19. 你应该怎么向评委解释“为什么用 Codex OAuth”

### 19.1 英文技术叙事

```text
For this hackathon, we use Codex OAuth and ChatGPT subscription access as the execution harness. Codex already provides a strong local agent loop: model inference, tool calls, file operations, shell execution, sandboxing, approval gates, context management, AGENTS.md instructions, MCP integrations, and reusable skills.

This lets us focus on the SME workflow layer instead of rebuilding the low-level harness from scratch. The demo turns a small business owner’s intent into concrete operational artifacts: customer reply templates, weekly reports, scheduling workflows, payment reminder plans, and a judge-ready dashboard.

For production, the same workflow can be migrated to OpenAI Responses API and Agents SDK with project-based API billing, tenant isolation, audit logs, and business integrations.
```

### 19.2 中文解释

```text
这次 demo 我们使用 Codex OAuth / subscription，不是为了偷懒，而是因为 Codex 已经封装了一个成熟的本地 agent harness：模型推理、工具调用、文件读写、命令执行、sandbox、approval、上下文管理、AGENTS.md、MCP 和 skills。

所以我们不重复造底层 agent loop，而是把精力放在 SME 小企业业务流程层：把老板的业务意图转化成真实可用的运营文件、回复模板、周报、排课流程、付款提醒计划和 dashboard。

正式产品化时，同一套业务流程可以迁移到 OpenAI Responses API 和 Agents SDK，用 API project、租户隔离、审计日志、权限控制和业务工具集成来支撑真实客户。
```

---

## 20. 最终推荐实现路线

### 第 1 小时：环境打通

```bash
npm install -g @openai/codex@latest
codex login --device-auth
codex login status
codex exec --json "Generate a 5-step plan for an SME AI operator demo."
```

### 第 2 小时：项目骨架

```bash
mkdir sme-codex-demo
cd sme-codex-demo
npm init -y
npm install express cors zod tsx typescript @openai/codex-sdk
mkdir -p src outputs workflows public .codex
```

### 第 3 小时：写 AGENTS.md

把本文第 10 节的 `AGENTS.md` 放进项目根目录。

### 第 4 小时：实现 `codex exec` wrapper

用第 5 节代码。

### 第 5 小时：生成 artifacts

目标至少生成：

```text
outputs/business_diagnosis.md
outputs/agent_workflow.json
outputs/customer_reply_templates.md
outputs/weekly_report_template.md
outputs/human_approval_checklist.md
public/demo-dashboard.html
```

### 第 6 小时：做前端展示

前端只需要展示：

```text
1. 用户输入业务痛点
2. 点击 Generate SME Operating System
3. 显示 Codex execution log
4. 展示生成文件列表
5. 打开 dashboard
6. 展示 human approval checkpoints
```

### 第 7 小时：准备 pitch

一句话：

```text
SME Agent Harness turns small business intent into operational systems, using Codex as the local execution harness.
```

### 第 8 小时：备用和防故障

准备静态 fallback：

```text
- 录屏
- 已生成 outputs 文件
- dashboard 静态页面
- demo script
```

现场如果网络或 OAuth 出问题，也能展示。

---

## 21. 关键判断：Codex OAuth 是否够用？

### 21.1 对 Hackathon demo：够用，而且很适合

因为你的 demo 目标是：

```text
- 展示 OpenAI agentic ecosystem 理解
- 展示 Codex harness 的执行能力
- 快速生成真实 artifact
- 做出不同于 chatbot 的产品体验
```

Codex OAuth 可以支撑。

### 21.2 对正式产品：不够

因为正式 SME SaaS 需要：

```text
- 多用户登录
- 租户隔离
- 企业数据权限
- API billing
- 业务工具 OAuth
- 审计日志
- 后台任务队列
- 失败重试
- 成本控制
- 合规策略
```

这些应使用：

```text
OpenAI Responses API
OpenAI Agents SDK
MCP / function calling
你自己的后端权限与计费系统
```

### 21.3 最聪明的说法

```text
Demo uses Codex OAuth as the execution harness.
Production uses Responses API + Agents SDK as the multi-tenant runtime.
```

这是最稳、最专业、最不会被评委质疑的表述。

---

## 22. 最短行动清单

```bash
# 1. 安装 Codex
npm install -g @openai/codex@latest

# 2. OAuth device code 登录
codex login --device-auth

# 3. 检查登录方式
codex login status

# 4. 避免误走 API key
unset OPENAI_API_KEY
unset OPENAI_BASE_URL

# 5. 创建项目
mkdir sme-codex-demo && cd sme-codex-demo
mkdir -p src outputs workflows public .codex

# 6. 写 AGENTS.md
# 7. 跑 Codex 生成 artifacts
codex exec --cd . --sandbox workspace-write --json "Create the SME Agent Harness demo artifacts."
```

---

## 23. 资料索引

### Official Codex Docs

- Codex Overview: https://developers.openai.com/codex
- Codex Quickstart: https://developers.openai.com/codex/quickstart
- Codex Authentication: https://developers.openai.com/codex/auth
- CI/CD Codex account auth: https://developers.openai.com/codex/auth/ci-cd-auth
- CLI Reference: https://developers.openai.com/codex/cli/reference
- Codex SDK: https://developers.openai.com/codex/sdk
- Codex MCP with Agents SDK: https://developers.openai.com/codex/guides/agents-sdk
- Codex MCP: https://developers.openai.com/codex/mcp
- Codex App Server: https://developers.openai.com/codex/app-server
- Config Basics: https://developers.openai.com/codex/config-basic
- Config Reference: https://developers.openai.com/codex/config-reference
- AGENTS.md: https://developers.openai.com/codex/guides/agents-md
- Sandboxing: https://developers.openai.com/codex/concepts/sandboxing
- Agent approvals & security: https://developers.openai.com/codex/agent-approvals-security
- Rules: https://developers.openai.com/codex/rules
- Skills: https://developers.openai.com/codex/skills
- Plugins: https://developers.openai.com/codex/plugins
- Subagents: https://developers.openai.com/codex/subagents
- Best Practices: https://developers.openai.com/codex/learn/best-practices
- Changelog: https://developers.openai.com/codex/changelog

### Official OpenAI Blog / Engineering Posts

- Introducing Codex: https://openai.com/index/introducing-codex/
- Unrolling the Codex agent loop: https://openai.com/index/unrolling-the-codex-agent-loop/
- Codex for almost everything: https://openai.com/index/codex-for-almost-everything/
- Run long horizon tasks with Codex: https://developers.openai.com/blog/run-long-horizon-tasks-with-codex
- Open-source Codex orchestration: Symphony: https://openai.com/index/open-source-codex-orchestration-symphony/
- Workspace agents in ChatGPT: https://openai.com/index/introducing-workspace-agents-in-chatgpt/

### Help Center

- Using Codex with your ChatGPT plan: https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- Codex rate card: https://help.openai.com/en/articles/20001106-codex-rate-card
- Flexible usage credits: https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-plus-pro
- ChatGPT vs Platform billing: https://help.openai.com/en/articles/9039756-billing-settings-in-chatgpt-vs-platform
- API usage dashboard: https://help.openai.com/en/articles/10478918-api-usage-dashboard

### Community Forum Signals

- Codex CLI category: https://community.openai.com/c/codex/codex-cli/39
- Connect Codex to OpenAI Developer Docs via MCP: https://community.openai.com/t/connect-codex-to-openai-developer-docs-via-mcp/1371352
- Unexpected API charges despite ChatGPT login: https://community.openai.com/t/unexpected-api-charges-from-codex-cli-despite-chatgpt-login/1358277
- ChatGPT sign-in 401 / 403 issue discussion: https://community.openai.com/t/stream-error-exceeded-retry-limit-last-status-401-unauthorized-with-chatgpt-signin-after-account-migration/1363168

---

## 24. 最终结论

你这次 Hackathon 如果决定使用 **Codex OAuth / subscription**，技术上是合理的，产品叙事上也是有优势的。

你应该把 Codex 定位为：

```text
OpenAI-provided local execution harness
```

而不是普通模型 API。

你的比赛主张可以是：

```text
Small businesses do not need another chatbot. They need an operator that can turn intent into working systems. Codex gives us the execution harness to build that operator quickly: it can read the workspace, create files, run commands, follow project instructions, use tools, and generate reviewable business artifacts.
```

中文：

```text
小企业不需要另一个聊天机器人，而需要一个能把业务意图转化为真实运营系统的 AI 运营员。Codex 提供了底层执行 harness：它能读取工作区、创建文件、运行命令、遵循项目规则、调用工具，并生成可审查的业务 artifact。
```

最重要的边界：

```text
Hackathon demo：Codex OAuth / subscription 完全可以用。
正式 SaaS：迁移到 Responses API + Agents SDK + MCP + 自有权限/计费系统。
```
