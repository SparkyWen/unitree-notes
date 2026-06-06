# AI Coordinator 指挥调度中心设计文档

> **面向对象**：你现有的跨机器人厂商 harness 系统。该系统已经预留 `remote bridge` 与 `swarm` 层，且单个机器人已经具备 harness 快慢脑、MCP 调用能力与本地安全机制。  
> **目标**：在不破坏现有单机自治与安全边界的前提下，把系统扩展成一个可批量控制、指挥、调度、审计、回放、持续优化的 AI 指挥调度中心。  
> **调研日期**：2026-06-06。  
> **文档性质**：架构设计 + 研发路线图 + 参考标准/论文清单。  

---

## 0. 一句话定型

你的系统不应该把 AI coordinator 做成“能直接遥控机器人底层动作的大脑”，而应该做成一个**任务级、策略级、证据级、可审计的指挥调度控制面**：

- **机器人本地 harness 仍然是执行与安全最终责任主体**。
- **Coordinator 只发布带约束、带租约、带权限、可回滚、可拒绝的任务/能力合约**。
- **Swarm 层负责多机器人任务分配、资源冲突、交通/区域/协同策略**。
- **Remote bridge 层负责跨厂商协议、状态、命令语义归一化**。
- **MCP 只能作为工具与上下文接入机制，不能绕开安全门直接进入运动控制路径**。

一句原则：

> **AI 负责“理解、规划、解释、建议、重规划”；确定性调度器与安全门负责“验证、分配、授权”；机器人本地 harness 负责“准入、执行、避障、急停、自我保护”。**

---

## 1. 我对你当前设计想法的理解

你已经有一个跨厂商机器人 harness 系统，它的关键价值不是“又做一个机器人 SDK”，而是抽象出跨品牌、跨形态、跨通信协议的机器人运行时。你当前基础可以理解为：

```text
┌───────────────────────────────────────────────────────────────┐
│                     Future AI Coordinator                      │
│      自然语言/任务意图 → 任务图 → 调度 → 监控 → 重规划 → 审计       │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────┐
│                         Swarm Layer                            │
│ 多机器人任务分配 | 资源锁 | 队形/集群行为 | 交通协调 | 故障转移      │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────┐
│                       Remote Bridge Layer                       │
│ ROS 2 / Open-RMF / VDA5050 / MQTT / REST / gRPC / Vendor SDK    │
│ 状态归一化 | 命令归一化 | 协议适配 | 安全隧道 | 离线缓存            │
└──────────────────────────────┬────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────┐
│                    Per-Robot Harness Runtime                    │
│ 快脑: 反应式控制/避障/急停 | 慢脑: 本地推理/工具调用/MCP/任务落地     │
│ 本地安全机制 | 能力合约执行 | 状态回报 | 任务拒绝/降级               │
└───────────────────────────────────────────────────────────────┘
```

你的下一步不是推倒重来，而是把现有系统升级成**分层自治系统**：

| 层级 | 角色 | 是否可用 AI | 是否可直接动机器人底层 |
|---|---|---:|---:|
| AI Coordinator | 战略规划、任务拆解、跨机器人指挥、解释、审计 | 是 | 否 |
| Swarm Layer | 任务分配、队伍协同、资源/交通冲突解决 | 可辅助 | 否，最多发任务级/路径级合约 |
| Remote Bridge | 协议转换、状态统一、南向接入 | 通常不用 | 否，只转译已授权命令 |
| Robot Harness Slow Brain | 单机局部规划、语义理解、工具调用、MCP | 是 | 间接，仍经本地安全门 |
| Robot Harness Fast Brain | 避障、控制、急停、实时反射 | 否或极少 | 是，但必须本地、安全、实时 |

---

## 2. 相关资料与最新做法提炼

这一节不是简单罗列资料，而是抽取与你架构直接相关的结论。

### 2.1 多机器人 + LLM 的研究共识

2026 年的综述《Large Language Models for Multi-Robot Systems: A Survey》把 LLM 在多机器人系统中的用途分成四类：**高层任务分配/规划、中层运动规划、低层动作生成、人类介入**。该综述同时指出，多机器人系统落地面临协调、可扩展、真实世界适应性、幻觉、延迟与基准评测等挑战。参考：<https://arxiv.org/html/2502.03814v5>

对你的系统的启发：

- AI coordinator 最适合先落在**高层任务分配/规划**与**人机交互/解释**。
- 中层运动规划可以由 swarm/fleet scheduler 与机器人本地导航共同完成。
- 低层动作生成不应由中心 AI 直接控制，除非在仿真、沙箱、低风险技能或本地经过强安全门的场景。
- 必须把 AI 输出转成结构化任务图，再由确定性验证器、调度器、安全策略引擎检查。

### 2.2 SMART-LLM 的可借鉴流程

SMART-LLM 研究把高层任务指令转换为多机器人任务计划，流程包括**任务拆解、联盟形成、任务分配**，并在仿真和真实场景做实验。参考：<https://arxiv.org/abs/2309.10062>

对你的系统的启发：

```text
Operator Intent
   ↓
AI Task Decomposition
   ↓
Coalition / Capability Matching
   ↓
Task Allocation
   ↓
Executable Plan
   ↓
Robot-local Admission + Execution
```

这正好对应你的 coordinator → swarm → remote bridge → robot harness 结构。

### 2.3 Open-RMF：跨机器人 fleet 与基础设施互操作的工程基线

Open-RMF 官方定位是一个开放、模块化的软件系统，用于多个机器人 fleet 与门、电梯、楼宇系统等物理基础设施之间的共享和互操作。参考：<https://www.open-rmf.org/>

OpenRMF 文档说明其核心能力包括：任务排队、无冲突资源调度、fleet adapter 工具等，并且虽然基于 ROS 2，但使用 Open-RMF 不要求直接使用 ROS 2。参考：<https://openrmf.readthedocs.io/en/latest/>

Fleet Adapter 教程中，`fleet_adapter` 被定义为机器人与 RMF 核心系统之间的桥，负责上报机器人位置、任务、电量等状态，并把 RMF 的任务/导航命令转成厂商 API。参考：<https://osrf.github.io/ros2multirobotbook/integration_fleets_adapter_tutorial.html>

对你的系统的启发：

- 你的 `remote bridge` 可以吸收 Open-RMF fleet adapter 的思想。
- 如果你不想完全绑定 Open-RMF，也应实现类似的 adapter contract。
- Open-RMF 可作为某些场景的南向/中间层集成对象，而不是必须成为你的核心。

### 2.4 VDA5050：AGV/AMR 与中心 fleet control 的标准命令接口

VDA5050 3.0.0 是面向移动机器人 fleet 与中心 fleet control 通信的开放标准。官方 GitHub 说明其由 VDA、VDMA、KIT IFL 和产业贡献者共同开发。参考：<https://github.com/VDA5050/VDA5050>

VDA5050 规范明确目标包括：减少移动机器人接入 fleet control 的复杂度、支持不同厂商的异构移动机器人在同一物理环境中协同运行、提供通用且领域无关的接口定义。规范也明确它不定义功能安全、交通管理算法或网络安全机制；命令/订单通过 MQTT 传输。参考：<https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md>

对你的系统的启发：

- VDA5050 很适合作为 `remote bridge` 的一个南向 adapter。
- 它不能替代你的安全系统、调度算法或 AI coordinator。
- 你的架构应该把 VDA5050 当作“机器人订单/状态协议”，而不是完整智能系统。

### 2.5 MassRobotics AMR Interoperability：状态/健康/位置共享基线

MassRobotics AMR Interoperability 标准让不同类型的自主车辆共享位置、速度、方向、健康、任务/可用性与性能特征，也允许人类作业员通过移动设备提供类似信息，从而与机器人一起被编排。参考：<https://github.com/MassRobotics-AMR/AMR_Interop_Standard>

对你的系统的启发：

- 它非常适合做监控、数字孪生、统一状态面。
- 它更像“状态互操作/可见性标准”，不是完整控制协议。

### 2.6 ISO/FDIS 21423：工业 AMR 通信与互操作

ISO/FDIS 21423 处于开发阶段，目标是规定不同厂商工业 AMR 系统之间互操作的通信协议，覆盖 AMR、fleet manager 设备和工业环境中的企业资源，但排除 AMR 系统的安全相关要求。参考：<https://www.iso.org/standard/86749.html>

对你的系统的启发：

- 你的 contract/schema 应该避免过早耦合某个厂商字段。
- 保持 `remote bridge` adapter 可替换，未来可接 ISO 21423。

### 2.7 ROS 2 通信、安全与规模化经验

ROS 2 QoS 支持可靠/尽力而为、持久性、deadline、lifespan、liveliness 等策略，能适配无线网络与实时系统，但 QoS 不兼容会导致消息无法投递。参考：<https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Quality-of-Service-Settings.html>

SROS2 提供在 DDS-Security 之上使用 ROS 2 的工具与说明。参考：<https://docs.ros.org/en/rolling/Tutorials/Advanced/Security/Introducing-ros2-security.html>

Fast DDS Discovery Server 提供中心化动态发现，相比默认 DDS 分布式发现，在节点增多或 Wi-Fi 场景下可减少发现流量和 multicast 依赖。参考：<https://docs.ros.org/en/rolling/Tutorials/Advanced/Discovery-Server/Discovery-Server.html>

2025 年无线 ROS 2 通信论文指出，大图像和 LiDAR 点云在 lossy wireless 下会遇到 IP 分片、重传时机、缓冲突发等问题，并提出通过 XML QoS 配置优化 DDS，无需改协议。参考：<https://arxiv.org/abs/2508.11366>

2026 年 SFG-ROS 论文提出在多机器人密集感知中使用 schema-driven routing、targeted Fast DDS routing 与集中解码，缓解网络饱和、命名空间冲突和 CPU 开销。参考：<https://arxiv.org/abs/2605.23832>

对你的系统的启发：

- 不要默认把所有机器人的原始传感器数据都推到中心。
- `remote bridge` 应做**语义状态归一化**，不是全量传感器汇聚。
- 视频/点云应按需、降采样、压缩、边缘解码、事件触发。
- 多机器人规模化时要重视命名空间、QoS、发现机制、网络预算。

### 2.8 ROS2swarm：swarm 行为原语

ROS2swarm 提供了 ROS 2 上可复用的 swarm 行为原语，包括 aggregation、dispersion、collective decision-making，并在 TurtleBot3 与 Jackal 等平台上验证。参考：<https://arxiv.org/abs/2405.02438>

对你的系统的启发：

- 你的 swarm 层不应只有“中心分配任务”，还应提供若干去中心/半中心的群体行为原语。
- 当网络退化或 coordinator 不可用时，swarm 层可以切换到有限自治策略。

### 2.9 MCP：工具/上下文协议，但必须强约束

MCP 是把 LLM 应用与外部数据源、工具连接的开放协议，使用 JSON-RPC 2.0，包含 hosts、clients、servers、resources、prompts、tools 等概念。参考：<https://modelcontextprotocol.io/specification/2025-11-25>

MCP 规范明确强调安全与信任：MCP 会带来任意数据访问与代码执行路径，必须关注用户同意、数据隐私、工具安全与采样控制。参考：<https://modelcontextprotocol.io/specification/2025-11-25>

MCP Authorization 规范说明 HTTP transport 的授权能力，并基于 OAuth 2.1 等机制；MCP 安全最佳实践还讨论 confused deputy、token passthrough、SSRF、session hijacking、本地 MCP server compromise 等风险。参考：<https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization> 与 <https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices>

对你的系统的启发：

- Coordinator 和单机慢脑都可以用 MCP 调工具，但 MCP 工具输出必须被视为**不可信输入**。
- MCP 工具调用不能直接拥有机器人运动控制权限。
- 高风险工具必须 dry-run、人工确认、权限隔离、审计记录。

### 2.10 安全标准与机器人网络安全趋势

2025 版 ISO 10218 对工业机器人安全要求做了更新，TÜV Rheinland 的解读指出新版标准加入了网络安全要求，以防止未授权访问、操纵和数据丢失。参考：<https://www.tuv.com/landingpage/en/robotics/main/standard-update-alert/>

IEC 62443 系列面向工业自动化与控制系统安全；IEC 62443-3-2 要求定义系统边界、划分 zones/conduits、逐区评估风险、建立目标安全等级并记录安全要求。参考：<https://webstore.iec.ch/en/publication/30727>

NIST Cybersecurity Framework 2.0 是组织理解和改善网络安全风险管理的通用框架。参考：<https://www.nist.gov/cyberframework>

对你的系统的启发：

- 机器人安全不再只是物理急停、碰撞和避障，也包括账户、证书、更新、供应链、审计、网络分区。
- AI coordinator 必须有安全 case、风险分级、权限边界和审计证据。

### 2.11 SROS2 供应链攻击论文的警示

2025 年一篇 SROS2 供应链攻击论文展示：恶意 Debian 包可篡改 ROS 2 安全命令并通过 DNS 泄露 keystore 凭据，攻击者获得凭据后可作为认证参与者发布伪造控制或感知消息。论文强调需要供应链完整性控制与运行时语义验证。参考：<https://arxiv.org/abs/2511.00140>

对你的系统的启发：

- mTLS/SROS2 不是终点，密钥被盗后仍会“合法地作恶”。
- 必须引入运行时语义检查：速度/区域/任务/时间/身份/上下文不符合的消息即使认证通过也要拒绝。
- 需要 SBOM、签名包、镜像签名、硬件根信任、密钥轮换与异常检测。

### 2.12 LLM-guided safety agent 的启发

2026 年 LLM-guided safety agent 论文提出将自然语言安全规则转换成可执行 predicates，并部署在冗余异构边缘运行时中，以满足低延迟、功能安全和 ISO 13849 Category 3 / PL d 方向的需求。参考：<https://arxiv.org/abs/2604.20193>

对你的系统的启发：

- AI 可以帮助把安全规则“生成/维护”为 predicate，但执行必须确定性。
- 安全逻辑应尽可能部署在边缘/本地，不能依赖云端 LLM 实时判断。

### 2.13 机器人 foundation model 趋势

Google DeepMind 的 Gemini Robotics-ER 1.6 被定位为机器人高层 embodied reasoning 模型，可处理视觉/空间理解、任务规划和成功检测，并可调用工具、VLA 或用户函数。参考：<https://deepmind.google/blog/gemini-robotics-er-1-6/>

NVIDIA Isaac GR00T N1.7 是开放的 VLA 模型，面向通用 humanoid robot skills，支持语言和图像等多模态输入，并通过后训练适配特定机器人、任务和环境。参考：<https://github.com/NVIDIA/Isaac-GR00T>

对你的系统的启发：

- 未来机器人单机慢脑/VLA 会越来越强；coordinator 不应把所有智能集中在中心。
- Coordinator 的核心价值是跨机器人、跨厂商、跨任务、跨资源、跨安全边界的“编排与治理”。

---

## 3. 总体设计原则

### 3.1 十二条不可破坏原则

1. **AI 不直控底层运动**：coordinator 不能直接发布 `/cmd_vel`、关节速度、原始 actuator command。
2. **本地安全最终裁决**：机器人本地 harness 可以拒绝任何中心任务。
3. **任务合约化**：所有跨层命令都必须是 typed capability contract，而不是自由文本。
4. **租约化执行**：任务必须带 lease、TTL、取消策略、心跳要求；lease 过期进入安全策略。
5. **状态证据化**：调度依据必须来自带时间戳、置信度、来源、签名/认证上下文的状态。
6. **AI 输出必须验证**：LLM 生成计划只是一份 proposal，必须经 schema、policy、world model、solver、simulation 或 dry-run 验证。
7. **跨厂商只认能力，不认品牌**：调度层按能力、约束、健康、位置、负载、电量、权限匹配机器人。
8. **安全策略多层执行**：中心、swarm、bridge、机器人本地、物理安全系统都要有独立防线。
9. **观测优先于控制**：先做 read-only shadow mode，再逐步开放控制。
10. **所有决策可追溯**：谁下达、AI 如何解释、哪些证据、哪个版本策略、哪个机器人接收、为什么拒绝，都要可回放。
11. **网络分区默认会发生**：机器人必须能在 coordinator 失联时安全停止、继续当前安全任务或回撤。
12. **工具不等于权限**：MCP/插件/脚本/厂商 SDK 都必须被权限、沙箱和审计包裹。

### 3.2 AI Coordinator 的职责边界

AI Coordinator 应该做：

- 理解自然语言/业务系统任务意图。
- 查询上下文：地图、任务队列、库存、工单、机器人状态、历史事件。
- 生成任务 DAG/HTN 计划。
- 解释计划、风险和替代方案。
- 触发确定性调度器/优化器。
- 请求人工批准。
- 监控执行、发现异常、建议重规划。
- 生成事后报告与改进建议。

AI Coordinator 不应该做：

- 不应直接控制电机、速度、力矩、夹爪闭合力等。
- 不应绕开 swarm 层资源锁与交通协调。
- 不应绕开 remote bridge 的协议校验。
- 不应绕开单机 harness 安全门。
- 不应无审计地调用 MCP 高风险工具。

---

## 4. 目标架构

### 4.1 全局架构图

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                           Human / Business Layer                            │
│  Operator Console | Mission UI | ERP/MES/WMS | Incident Review | Approvals  │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────────┐
│                             AI Coordinator                                  │
│ ┌───────────────┐ ┌──────────────┐ ┌───────────────┐ ┌───────────────────┐ │
│ │ Intent Parser │ │ Plan Builder │ │ Risk Explainer│ │ Human Approval UI │ │
│ └───────┬───────┘ └──────┬───────┘ └───────┬───────┘ └─────────┬─────────┘ │
│         │                │                 │                   │           │
│ ┌───────▼────────────────▼─────────────────▼───────────────────▼─────────┐ │
│ │ Mission Control Plane: typed DAG, policy check, simulation, audit log    │ │
│ └───────┬─────────────────────────────────────────────────────────────────┘ │
│         │                                                                   │
│ ┌───────▼────────┐ ┌────────────────┐ ┌────────────────┐ ┌───────────────┐ │
│ │ MCP Tool Guard │ │ Knowledge/RAG   │ │ Policy Engine  │ │ Digital Twin  │ │
│ └────────────────┘ └────────────────┘ └────────────────┘ └───────────────┘ │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │ typed mission/task contracts
┌───────────────────────────────────▼────────────────────────────────────────┐
│                              Swarm Layer                                    │
│ Fleet Registry | Capability Matching | MRTA | Resource Locks | Traffic      │
│ Zone Coordinator | Battery/Charging | Replanning | Degraded Swarm Behaviors │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │ capability leases / task commands
┌───────────────────────────────────▼────────────────────────────────────────┐
│                            Remote Bridge Layer                              │
│ Adapter Runtime | Protocol Translation | State Normalization | AuthN/AuthZ   │
│ ROS2/DDS | Open-RMF | VDA5050/MQTT | MassRobotics | REST/gRPC | Vendor SDK   │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │ vendor/local commands, telemetry
┌───────────────────────────────────▼────────────────────────────────────────┐
│                         Per-Robot Harness Runtime                           │
│ Local Admission Gate | Slow Brain | Fast Brain | MCP Sandbox | Safety Monitor│
│ Skill Executor | Local Planner | E-stop | Telemetry | Result/Refusal Events │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 四个时间尺度的自治闭环

| 闭环 | 位置 | 时间尺度 | 典型动作 | 是否允许 AI |
|---|---|---:|---|---:|
| L0 快反射/安全闭环 | 机器人本地、控制器、安全 PLC | 毫秒到几十毫秒 | 急停、避障、限速、碰撞保护 | 不建议 |
| L1 单机任务闭环 | 机器人 harness | 百毫秒到数秒 | 局部导航、技能执行、本地慢脑推理 | 可以，但受本地安全门约束 |
| L2 Swarm/Fleet 闭环 | swarm 层/边缘 | 秒到分钟 | 任务分配、交通协调、资源锁、充电调度 | 可辅助，不可独裁 |
| L3 Coordinator 战略闭环 | 指挥中心/云边协同 | 分钟到小时 | 任务理解、跨队计划、业务优化、报告 | 是，必须验证 |

### 4.3 推荐部署形态

```text
Cloud / Control Room
  - AI Coordinator
  - Mission UI
  - Knowledge/RAG
  - Long-term event store
  - Analytics / reporting

Site Edge Cluster
  - Swarm scheduler
  - Remote bridge adapters
  - Digital twin cache
  - Local policy engine
  - Event broker
  - Video/sensor gateway

Robot / Vendor Fleet Manager
  - Per-robot harness agent
  - Local slow brain / skill executor
  - Fast brain / safety monitor
  - MCP sandbox where applicable
```

设计要点：

- 低延迟和安全相关逻辑尽量放到 site edge 或机器人本地。
- 云端 coordinator 可以做复杂推理、报告和优化，但不能成为安全实时依赖。
- Edge 需要缓存任务、地图、策略和身份凭据，支持短时间断网安全运行。

---

## 5. 核心抽象：从“控制机器人”变成“发布能力合约”

### 5.1 Capability Contract 是全系统中心

你需要建立一个跨厂商统一的能力合约层。Coordinator 不应该说“调用某品牌 API 让机器人去 x,y”，而应该说：

> 在某个时间窗口内，请一个满足能力约束的执行体，在安全策略 S 和资源锁 R 下，完成任务 T；执行体可以接受、拒绝、降级或请求澄清。

### 5.2 Robot Capability Descriptor

```yaml
robot_id: amr-042
vendor: vendor_x
model: amr_800
harness_version: 1.8.0
trust_level: production_certified
embodiment:
  type: amr
  payload_kg: 800
  max_speed_mps: 1.5
  footprint_m: {length: 1.1, width: 0.75}
localization:
  map_ids: [warehouse_A_v12]
  frames: [map, odom, base_link]
capabilities:
  - name: navigate_to
    contract_version: 1.0
    risk_level: medium
    params_schema: NavigateTo.v1
  - name: dock_charge
    contract_version: 1.0
    risk_level: low
  - name: carry_pallet
    contract_version: 1.0
    risk_level: medium
    constraints:
      max_payload_kg: 800
safety:
  e_stop: true
  local_obstacle_avoidance: true
  geofence: true
  max_certified_speed_mps: 1.5
mcp:
  enabled: true
  allowed_tool_profiles: [local_diagnostics_readonly, vendor_manual_lookup]
```

### 5.3 Robot State

```json
{
  "robot_id": "amr-042",
  "timestamp": "2026-06-06T08:00:00Z",
  "pose": {"map_id": "warehouse_A_v12", "x": 12.4, "y": 7.8, "theta": 1.57, "covariance": "..."},
  "motion_state": "idle",
  "task_state": "available",
  "battery": {"soc": 0.72, "charging": false, "estimated_runtime_min": 95},
  "health": {"level": "ok", "faults": []},
  "current_lease": null,
  "capability_status": {
    "navigate_to": "ready",
    "carry_pallet": "ready"
  },
  "safety_state": {
    "e_stop": false,
    "geofence_ok": true,
    "human_nearby": false
  }
}
```

### 5.4 Mission Intent

```yaml
mission_id: mission-20260606-001
created_by: operator:li
intent_text: "今晚 18 点前，让 10 台 AMR 把 A 区待补货托盘搬到 B 区，优先保证冷链货物。"
priority: high
business_constraints:
  deadline: "2026-06-06T18:00:00+10:00"
  priority_rules:
    - cold_chain_first
    - avoid_blocking_loading_dock
risk_policy:
  max_risk_level_without_human_approval: medium
  require_approval_for:
    - entering_human_dense_zone
    - disabling_any_safety_limit
```

### 5.5 Task Spec

```yaml
task_id: task-0007
mission_id: mission-20260606-001
type: transport_pallet
required_capabilities:
  - carry_pallet
  - navigate_to
pickup:
  zone: A
  location_id: A-PICK-03
dropoff:
  zone: B
  location_id: B-STAGE-02
constraints:
  payload_kg: 420
  temperature_sensitive: true
  deadline: "2026-06-06T17:30:00+10:00"
preconditions:
  - source_pallet_present
  - route_available
  - destination_slot_reserved
success_criteria:
  - pallet_at_destination
  - robot_reports_task_complete
  - inventory_system_acknowledged
cancel_policy:
  on_network_loss: continue_until_next_safe_checkpoint
  on_human_blocking: pause_and_request_replan
```

### 5.6 Command Envelope

所有跨层命令都必须包裹在 envelope 内。

```json
{
  "command_id": "cmd-01HX...",
  "trace_id": "trace-abc",
  "issued_by": "swarm-scheduler-1",
  "issued_to": "amr-042",
  "issued_at": "2026-06-06T08:02:00Z",
  "expires_at": "2026-06-06T08:07:00Z",
  "idempotency_key": "mission-001-task-0007-attempt-1",
  "capability": "transport_pallet",
  "payload": {
    "pickup": "A-PICK-03",
    "dropoff": "B-STAGE-02"
  },
  "safety_envelope": {
    "max_speed_mps": 1.0,
    "allowed_zones": ["A", "main_corridor", "B"],
    "forbidden_zones": ["maintenance_zone"],
    "human_approval_id": "approval-8842"
  },
  "lease": {
    "lease_id": "lease-77",
    "heartbeat_interval_sec": 2,
    "ttl_sec": 300,
    "on_expire": "safe_pause"
  }
}
```

### 5.7 Result / Refusal Event

机器人拒绝任务不是异常，而是一等公民。

```yaml
event_type: task_refused
robot_id: amr-042
task_id: task-0007
reason_code: LOCAL_SAFETY_PRECONDITION_FAILED
reason_detail: "front safety scanner degraded; cannot carry pallet in production mode"
recommended_action:
  - assign_other_robot
  - send_robot_to_maintenance
telemetry_refs:
  - health_snapshot: hs-20260606-080201
```

---

## 6. AI Coordinator 详细设计

### 6.1 内部模块

```text
AI Coordinator
├── Intent Understanding
│   ├── natural language parser
│   ├── business rule extractor
│   └── ambiguity detector
├── Context Engine
│   ├── robot/fleet state retrieval
│   ├── maps/zones/resources
│   ├── ERP/MES/WMS/work orders
│   ├── historical incident retrieval
│   └── MCP tool gateway
├── Plan Builder
│   ├── task decomposition
│   ├── DAG/HTN generation
│   ├── constraints extraction
│   └── plan alternatives
├── Plan Verifier
│   ├── schema validation
│   ├── policy validation
│   ├── resource feasibility
│   ├── route/zone feasibility
│   ├── simulation/dry-run
│   └── human approval gating
├── Swarm Dispatch Interface
│   ├── task publication
│   ├── allocation requests
│   └── replan triggers
├── Execution Monitor
│   ├── event stream consumer
│   ├── anomaly detector
│   ├── replan proposer
│   └── mission progress reporter
└── Audit / Explainability
    ├── decision log
    ├── plan explanation
    ├── risk explanation
    └── post-mission report
```

### 6.2 AI 输出的标准流程

```text
1. Operator / Business System 提交任务意图
2. Coordinator 提取结构化 MissionIntent
3. Coordinator 调用上下文工具获取状态、地图、库存、工单、机器人能力
4. LLM 生成 candidate task graph
5. Schema validator 检查格式
6. Policy engine 检查权限、安全、业务规则
7. Feasibility checker 检查资源、地图、能力、电量、时间窗
8. Simulation / dry-run 检查明显冲突
9. 人工批准高风险任务
10. Swarm scheduler 做分配与执行计划
11. Remote bridge 下发能力合约
12. 机器人本地 harness admission gate 再次验证并执行/拒绝
13. Coordinator 监控、解释、重规划、归档
```

### 6.3 LLM 在 coordinator 中的正确位置

| 功能 | LLM 适合度 | 是否需要确定性验证 |
|---|---:|---:|
| 自然语言任务理解 | 高 | 是 |
| 任务拆解 | 高 | 是 |
| 业务规则解释 | 高 | 是 |
| 多方案生成 | 高 | 是 |
| 风险说明/报告 | 高 | 是，至少要引用事件证据 |
| 实时交通仲裁 | 低 | 是，不建议 LLM 主导 |
| 低层控制 | 极低 | 必须禁止中心 LLM 直控 |
| 安全规则生成 | 中 | 必须编译成 predicate 并测试 |
| MCP 工具选择 | 中高 | 是 |

### 6.4 防幻觉与防越权机制

Coordinator 的 LLM 应采用以下结构：

```text
LLM Proposal
   ↓
JSON Schema / Typed AST
   ↓
Policy-as-code
   ↓
World Model Validator
   ↓
Deterministic Optimizer / Scheduler
   ↓
Simulation / Dry-run
   ↓
Human Approval if needed
   ↓
Dispatch
```

关键约束：

- LLM 不能直接输出可执行脚本进入生产控制路径。
- LLM 输出必须是严格 schema，例如 `MissionIntent.v1`、`TaskDAG.v1`。
- 每个 task 都必须有 preconditions、success criteria、cancel policy。
- AI 不确定时必须生成 `needs_clarification` 或 `needs_approval`，不能臆造地图、机器人、库存或能力。
- 所有 planner prompt 都要注入当前 state snapshot 的版本号，防止“基于旧状态做新计划”。

### 6.5 Coordinator 与单机慢脑的关系

你已经有单机器人 harness 快慢脑。扩展后建议分工：

| 能力 | Coordinator 慢脑 | 单机慢脑 |
|---|---|---|
| 业务目标理解 | 主 | 辅 |
| 全局任务拆解 | 主 | 辅 |
| 多机器人分配 | 主导，但经 swarm solver | 不做或只报价 |
| 局部环境理解 | 只看摘要/事件 | 主 |
| 工具调用 | 调企业系统、知识库、调度系统 MCP | 调本地诊断、设备、局部工具 MCP |
| 任务落地 | 生成 contract | admission + skill execution |
| 安全最终裁决 | 不能最终裁决 | 本地最终裁决 |

---

## 7. Swarm Layer 详细设计

### 7.1 Swarm 层职责

Swarm 层不是 AI 大脑，而是多机器人运行的确定性协调中枢：

- Fleet registry：机器人注册、能力、健康、位置、电量。
- Task allocation：多机器人任务分配。
- Coalition formation：组合多个机器人完成一个任务。
- Resource locking：门、电梯、窄通道、充电桩、装卸口、工位。
- Traffic coordination：路径冲突、会车、死锁解除。
- Zone coordination：按区域分片管理机器人。
- Battery/charging scheduling：充电、换电、任务续航评估。
- Degraded mode：中心不可用或网络差时切换到有限 swarm 行为。
- Replanning：机器人故障、任务失败、环境变化、业务优先级改变时重分配。

### 7.2 任务分配算法建议

第一阶段不要一开始做复杂端到端 AI 调度。建议采用“AI 提案 + 传统优化/启发式裁决”的混合方式。

| 规模/场景 | 推荐方法 | 说明 |
|---|---|---|
| 机器人 < 20、任务 < 100 | 中心化 CP-SAT/MILP/启发式 | 易解释、易 debug |
| 动态任务流 | auction / market-based allocation | 每个机器人报价，中心或区域 coordinator 选择 |
| 多机器人协作任务 | coalition formation + constraint solver | 例如双臂/多车搬运 |
| 路径冲突明显 | MAPF/CBS/优先级规划 + Open-RMF 类资源调度 | 避免死锁 |
| 大规模多区域 | hierarchical scheduler | 每个 zone 有局部 coordinator |
| 网络不稳定 | decentralized swarm primitives | 聚集、分散、避让、局部共识 |

### 7.3 Replanning 触发器

```yaml
replan_triggers:
  robot_fault:
    severity: warning_or_above
    action: remove_robot_from_candidate_pool
  task_timeout:
    threshold: dynamic_eta_p95_exceeded
    action: reassign_or_split_task
  battery_low:
    threshold_soc: 0.18
    action: send_to_charge_after_safe_checkpoint
  route_blocked:
    threshold_sec: 30
    action: reroute_or_pause_upstream_tasks
  human_dense_zone:
    action: reduce_speed_or_request_approval
  high_priority_mission_arrival:
    action: preempt_low_priority_if_allowed
  network_partition:
    action: switch_to_lease_policy
```

### 7.4 Resource Lock 模型

资源锁是多机器人系统落地的关键，尤其在门、电梯、窄通道、装卸区、充电桩等场景。

```yaml
resource_lock:
  resource_id: corridor-C12
  type: narrow_corridor
  lock_mode: exclusive
  holder: amr-042
  granted_for_task: task-0007
  valid_from: "2026-06-06T08:10:00Z"
  valid_until: "2026-06-06T08:10:45Z"
  preemptible: false
  release_conditions:
    - robot_exits_region
    - timeout
    - emergency_override
```

### 7.5 Swarm fallback 行为

当 coordinator 或网络不可用时，不同风险等级对应不同 fallback：

| 当前任务风险 | 网络断开策略 | 机器人行为 |
|---|---|---|
| 低风险巡检 | 可继续到下一个安全 checkpoint | 本地执行，缓存事件 |
| 中风险搬运 | 继续到安全停靠点或暂停 | 不接受新任务 |
| 高风险人机混行 | 安全减速/暂停 | 等待人工或本地恢复 |
| 任何急停/安全故障 | 停止 | 本地安全系统接管 |

---

## 8. Remote Bridge Layer 详细设计

### 8.1 Remote bridge 的定位

Remote bridge 是跨厂商、跨协议、跨部署环境的南向适配层。它不应该承载 AI 逻辑，而应该承载：

- 协议转换。
- 状态归一化。
- 命令 envelope 校验。
- 厂商 API 错误标准化。
- 认证授权。
- 限流与熔断。
- 离线缓存与重放保护。
- 语义映射：地图坐标、任务状态、错误码、能力名。

### 8.2 Adapter 类型

| Adapter | 用途 | 备注 |
|---|---|---|
| ROS 2 Adapter | 原生 ROS 2 机器人或仿真 | 注意 QoS、SROS2、Discovery Server |
| Open-RMF Adapter | 接入 RMF 生态和设施调度 | 可作为 fleet adapter 或 RMF client |
| VDA5050 Adapter | AGV/AMR order/state over MQTT | 适合仓储/制造 AMR |
| MassRobotics Adapter | 状态/健康/位置互操作 | 更适合 observability |
| Vendor REST/gRPC Adapter | 厂商 fleet manager | 最常见，需做语义归一化 |
| WebSocket/MQTT Adapter | 实时遥测和事件 | 注意 backpressure 和重连 |
| Legacy Adapter | 串口、TCP、自定义协议 | 必须放在隔离网络与强审计中 |

### 8.3 Adapter contract

每个 adapter 至少实现：

```typescript
interface RobotBridgeAdapter {
  describeCapabilities(robotId: string): Promise<CapabilityDescriptor>;
  getState(robotId: string): Promise<RobotState>;
  submitCommand(envelope: CommandEnvelope): Promise<CommandAccepted | CommandRejected>;
  cancel(commandId: string, reason: string): Promise<CancelResult>;
  streamEvents(filter: EventFilter): AsyncIterable<RobotEvent>;
  healthCheck(): Promise<AdapterHealth>;
}
```

### 8.4 状态归一化策略

不要试图让所有厂商字段都进入核心模型。核心模型保持小而稳定，厂商字段放入 extension。

```json
{
  "core": {
    "robot_id": "amr-042",
    "pose": "...",
    "battery": "...",
    "task_state": "available",
    "health_level": "ok"
  },
  "extensions": {
    "vendor_x": {
      "raw_mode": "AUTO_READY",
      "firmware": "4.2.1",
      "localization_quality": 0.96
    }
  }
}
```

### 8.5 坐标系与地图映射

跨厂商调度经常失败在地图语义不一致：

- 每个 robot/fleet manager 的 map version 必须显式记录。
- 每个位置必须有 `map_id`、`frame_id`、`transform_version`。
- 坐标转换必须是可审计对象，不能藏在 adapter 代码里。
- Open-RMF fleet adapter 教程也提到，如果机器人坐标系与 RMF 不一致，需要 reference coordinates 来估计坐标变换。

推荐对象：

```yaml
map_transform:
  transform_id: vendorX_to_global_A_v3
  source_map: vendorX_warehouse_A_20260601
  target_map: warehouse_A_global_v12
  method: affine_2d
  reference_points:
    - source: [1.2, 3.4]
      target: [10.0, 20.0]
  valid_from: "2026-06-01"
  validated_by: mapping_team
  max_error_m: 0.15
```

---

## 9. Safety & Security Architecture

### 9.1 命令安全门流水线

所有命令都必须经过以下流水线：

```text
Command Proposal
   ↓
Identity Authentication
   ↓
Authorization / RBAC / ABAC
   ↓
Schema Validation
   ↓
Policy-as-code
   ↓
World Model Feasibility
   ↓
Resource Lock Check
   ↓
Risk Classification
   ↓
Human Approval if required
   ↓
Bridge Translation
   ↓
Robot Local Admission Gate
   ↓
Execution
   ↓
Telemetry + Audit + Replay
```

### 9.2 安全分层

| 层 | 安全能力 | 失败时 |
|---|---|---|
| Physical | 急停、安全激光、力矩/速度限制、安全 PLC | 立即停止或进入安全状态 |
| Robot Fast Brain | 避障、限速、局部控制、碰撞保护 | 暂停/停车 |
| Robot Harness Gate | 任务准入、能力检查、电量/健康检查 | 拒绝任务 |
| Remote Bridge | envelope 校验、协议限权、重放保护 | 不转发 |
| Swarm | 资源锁、交通冲突、任务冲突 | 重规划/等待 |
| Coordinator | 风险识别、审批、解释、审计 | 阻止发布或请求人工 |
| Enterprise Security | 身份、密钥、网络分区、供应链 | 隔离/吊销/恢复 |

### 9.3 权限模型

建议采用 RBAC + ABAC：

- RBAC：角色，例如 operator、supervisor、safety_engineer、developer、robot_service。
- ABAC：属性，例如任务风险、区域、人群密度、时间、机器人认证等级、是否生产环境。

示例：

```yaml
policy: high_risk_zone_entry
rule:
  when:
    task.risk_level: high
    zone.human_density: high
  require:
    - approval.role: safety_supervisor
    - robot.safety.geofence: true
    - robot.health.level: ok
  deny_if:
    - robot.trust_level != production_certified
```

### 9.4 MCP 工具安全策略

MCP 在你的系统里很有价值，但风险也很大。推荐分级：

| 工具等级 | 示例 | 默认权限 | 是否需要审批 |
|---|---|---|---:|
| L0 只读知识 | 查手册、查 SOP、查历史事件 | 允许 | 否 |
| L1 只读状态 | 查库存、查地图、查 robot state | 允许但审计 | 否 |
| L2 业务写入 | 创建工单、更新库存状态 | 受限 | 视业务而定 |
| L3 调度影响 | 创建任务、取消任务、变更优先级 | 强审计 | 是/按策略 |
| L4 机器人动作 | 下发运动/技能命令 | 默认禁止 MCP 直连 | 必须经 coordinator + swarm + local gate |
| L5 安全绕过 | 禁用安全限制、修改 geofence | 禁止 | 特殊离线流程 |

MCP 最低要求：

- MCP server allowlist。
- 每个 tool 有 scope、risk_level、owner、审计策略。
- 高风险工具必须 dry-run。
- Tool output 视为 untrusted data，不可变成 system instruction。
- 禁止 token passthrough。
- 防 SSRF：阻断内网/metadata 地址，使用 egress proxy。
- 本地 MCP server 必须沙箱化，最小文件/网络权限。
- 每次工具调用记录：输入、输出 hash、调用者、审批、trace_id。

### 9.5 供应链与密钥安全

鉴于 SROS2 keystore 泄露攻击的研究，你不能只依赖“消息已认证”。建议：

- 机器人和 bridge 使用硬件根信任或 TPM/TEE 存储关键密钥。
- 镜像、Debian 包、容器、插件、MCP server 全部签名验证。
- 生成 SBOM，CI/CD 做依赖漏洞扫描。
- 禁止生产机器人直接安装未签名包。
- 证书短周期、可吊销、可轮换。
- Topic/API 层做语义异常检测：例如“认证机器人在不可能区域发布高速命令”仍应拦截。
- 对控制命令加入 nonce、TTL、idempotency key、防重放。

### 9.6 安全 case 文档化

每个高风险能力都应维护 safety case：

```yaml
safety_case:
  capability: carry_pallet
  hazards:
    - collision_with_human
    - dropped_payload
    - blocked_emergency_exit
  mitigations:
    - local_obstacle_avoidance
    - speed_limit_in_human_zone
    - payload_weight_check
    - geofence
  verification:
    - simulation_scenarios
    - hardware_in_loop_tests
    - field_acceptance_tests
  runtime_monitors:
    - max_speed_monitor
    - zone_entry_monitor
    - load_stability_monitor
  approval_required_when:
    - payload_kg > 500
    - human_density == high
```

---

## 10. Observability、审计与数字孪生

### 10.1 事件溯源是必须项

建议采用 event-sourcing。每个任务、命令、状态变化、审批、拒绝、重规划都写入 append-only event log。

```yaml
event:
  event_id: evt-01
  trace_id: trace-abc
  mission_id: mission-001
  type: command_accepted
  actor: bridge-vda5050-1
  subject: amr-042
  timestamp: "2026-06-06T08:02:01Z"
  payload_hash: sha256:...
  policy_version: policy-20260601
  world_snapshot_id: world-7781
```

### 10.2 指挥中心 UI 应展示什么

- Mission timeline：任务从意图到完成的全过程。
- Fleet map：机器人位置、状态、任务、风险区域。
- Resource board：门、电梯、窄通道、充电桩、装卸口占用。
- Plan explanation：为什么这么分配，备选方案是什么。
- Risk panel：当前风险、需要审批事项、拒绝原因。
- Incident replay：按 trace_id 回放事件、地图、机器人状态。
- AI confidence/evidence：AI 使用了哪些证据、哪些假设不确定。

### 10.3 指标体系

| 类别 | 指标 |
|---|---|
| 任务 | 成功率、超时率、平均完成时间、P95 完成时间 |
| 调度 | 重规划次数、死锁次数、资源等待时间、机器人利用率 |
| 安全 | 急停次数、近失事件、命令拒绝次数、geofence violation |
| 通信 | 端到端命令延迟、心跳丢失率、遥测延迟、bridge 错误率 |
| AI | 计划被验证器拒绝率、人工修改率、澄清率、幻觉/无效字段率 |
| MCP | 工具调用次数、失败率、高风险调用数、审批耗时 |
| 可靠性 | coordinator failover 次数、partition 次数、恢复时间 |

### 10.4 Sensor Gateway 策略

中心不要默认接收所有视频/点云：

- 默认只上传语义事件：`obstacle_detected`、`human_blocking`、`pallet_detected`。
- 需要时按 trace_id 拉取片段。
- 高带宽传感器走独立 sensor gateway。
- 支持边缘压缩、采样、脱敏。
- 对调度只依赖必要状态，不依赖中心视觉实时闭环。

---

## 11. 可靠性与故障模式

### 11.1 Coordinator 高可用

- Coordinator 可以多副本，但 mission command authority 必须避免 split-brain。
- 调度决策应写入一致性 event store。
- 下发命令必须有单调版本号和 idempotency key。
- Bridge 需要拒绝旧版本/重复/过期命令。

### 11.2 网络分区策略

```yaml
partition_policy:
  if_robot_loses_coordinator:
    low_risk_task: continue_to_safe_checkpoint
    medium_risk_task: pause_at_next_safe_location
    high_risk_task: safe_stop
  if_bridge_loses_vendor_fleet:
    stop_new_dispatch: true
    mark_robot_state_stale_after_sec: 5
  if_state_stale:
    exclude_from_new_allocation: true
```

### 11.3 常见故障模式与处理

| 故障 | 检测 | 处理 |
|---|---|---|
| 机器人不回心跳 | heartbeat timeout | 暂停分配，标记 stale，触发安全策略 |
| 命令重复下发 | idempotency key | bridge/robot 去重 |
| 坐标系错误 | map transform validation | 拒绝任务，要求重新标定 |
| 任务卡住 | ETA deviation / no progress | 重规划或人工介入 |
| 资源锁未释放 | timeout / robot exits region | 自动释放或 supervisor override |
| AI 生成不存在位置 | schema + world validator | 拒绝计划，要求澄清 |
| MCP 工具输出恶意指令 | instruction/data separation | 只作为数据，不执行 |
| 认证凭据被盗 | anomaly + cert revoke | 隔离设备，吊销证书，回滚镜像 |

---

## 12. API 与服务拆分建议

### 12.1 服务边界

```text
services/
  coordinator-api/        # mission API, approvals, UI backend
  coordinator-agent/      # LLM planning/explanation, tool use
  plan-verifier/          # schema, policy, feasibility, dry-run
  swarm-scheduler/        # MRTA, resource locks, replanning
  fleet-registry/         # robot capabilities/state registry
  bridge-runtime/         # adapter host runtime
  adapters/
    ros2/
    open-rmf/
    vda5050/
    massrobotics/
    vendor-x/
  policy-engine/          # policy-as-code
  world-model/            # maps, zones, resources, state snapshots
  event-log/              # append-only event store
  mcp-gateway/            # tool allowlist, sandbox, audit
  digital-twin/           # simulation / replay
  ops-console/            # frontend
```

### 12.2 Northbound API 示例

```http
POST /missions
GET  /missions/{mission_id}
POST /missions/{mission_id}/approve
POST /missions/{mission_id}/cancel
GET  /robots
GET  /robots/{robot_id}
GET  /events?trace_id=...
POST /plans/{plan_id}/dry-run
POST /plans/{plan_id}/dispatch
```

### 12.3 Internal Event Topics 示例

```text
mission.created
mission.plan.proposed
mission.plan.verified
mission.approval.required
mission.dispatched
swarm.task.allocated
bridge.command.accepted
bridge.command.rejected
robot.task.accepted
robot.task.refused
robot.task.progress
robot.task.completed
robot.safety.event
resource.lock.granted
resource.lock.released
coordinator.replan.requested
```

### 12.4 Southbound Bridge Topics 示例

对 VDA5050/MQTT：

```text
vda5050/{interfaceName}/{majorVersion}/{manufacturer}/{serialNumber}/order
vda5050/{interfaceName}/{majorVersion}/{manufacturer}/{serialNumber}/state
vda5050/{interfaceName}/{majorVersion}/{manufacturer}/{serialNumber}/instantActions
```

对 ROS 2：

```text
/harness/{robot_id}/state
/harness/{robot_id}/capabilities
/harness/{robot_id}/command_envelope
/harness/{robot_id}/result_events
/harness/{robot_id}/safety_events
```

---

## 13. 任务执行序列示例

### 13.1 业务任务

Operator 输入：

> “今天 18:00 前，让 10 台 AMR 把 A 区待补货托盘搬到 B 区，冷链优先，不要堵住装卸口。”

### 13.2 系统执行

```text
1. Coordinator 解析 intent
2. 查询 WMS：A 区待补货托盘列表、冷链标记、目的库位
3. 查询 fleet registry：机器人能力、位置、电量、健康
4. 查询 world model：路线、装卸口、窄通道、禁行区
5. LLM 生成任务 DAG：冷链优先，普通托盘次之
6. Verifier 检查：任务位置存在、能力匹配、时间窗可行
7. Swarm scheduler 分配：AMR-001..010 承担第一批任务
8. Resource lock：为窄通道、装卸口、充电桩建立时间窗
9. 高风险部分请求 supervisor approval
10. Remote bridge 转换到各厂商命令
11. 每台 robot harness local admission gate 接受/拒绝
12. 执行中 AMR-004 电量下降，swarm 重新分配其剩余任务
13. Coordinator 汇报：完成率、ETA、异常、重规划原因
14. 任务结束生成 post-mission report
```

### 13.3 AI 解释输出示例

```text
我优先分配 AMR-003、AMR-007、AMR-009 处理冷链托盘，因为它们距离 A 区最近、电量高于 70%、具备 carry_pallet 能力，且不会经过当前人流密集的 C 通道。
AMR-004 未被分配冷链任务，因为其电量 22%，预计完成后无法安全返回充电点。
装卸口 D1 在 16:30-17:00 被人工叉车占用，因此相关路径被排除。
```

注意：这些解释必须引用实际 state snapshot 和 policy，不应只是语言生成。

---

## 14. MVP 到生产的路线图

### Phase 0：架构固化与 contract 定义

交付物：

- `CapabilityDescriptor.v1`
- `RobotState.v1`
- `MissionIntent.v1`
- `TaskSpec.v1`
- `CommandEnvelope.v1`
- `RobotEvent.v1`
- 风险等级与审批策略。
- 现有 harness 与 schema 的映射表。

成功标准：

- 至少 2 个不同厂商机器人能输出统一状态。
- 所有命令都有 trace_id、lease、TTL、risk_level。

### Phase 1：Read-only 指挥中心

目标：先可视化，不控制。

交付物：

- Fleet registry。
- Remote bridge read-only adapters。
- 地图/机器人/任务状态 dashboard。
- 事件日志与 replay。
- MassRobotics-style 状态子集。

成功标准：

- 机器人状态延迟、丢包、stale 状态可观测。
- 操作员能在 UI 中看到统一 fleet 状态。

### Phase 2：Human-approved Dispatch

目标：低风险任务可由中心下发，但必须人工批准。

交付物：

- `POST /missions`。
- Task DAG 生成。
- Plan verifier。
- Human approval UI。
- 两个南向 adapter 支持控制。
- Robot local admission event。

成功标准：

- 能完成低风险点到点/搬运任务。
- 机器人可拒绝任务并被正确重分配。

### Phase 3：Swarm Scheduler

目标：真正多机器人协同。

交付物：

- MRTA 调度。
- Resource locks。
- Battery/charging scheduling。
- Open-RMF 或类 Open-RMF 交通/设施集成。
- Replanning。

成功标准：

- 支持 10+ 机器人并行任务。
- 资源冲突可被预防或自动恢复。

### Phase 4：AI Coordinator Agent

目标：自然语言指挥 + 计划解释 + MCP 工具。

交付物：

- Intent parser。
- LLM task decomposition。
- MCP gateway。
- Plan explanation。
- Risk explanation。
- Post-mission report。

成功标准：

- AI 生成计划必须 100% 经过 verifier。
- 高风险任务必须触发审批。
- AI 计划被拒绝时能给出可操作原因。

### Phase 5：Scale & Resilience

目标：多区域、多厂商、大规模生产。

交付物：

- Zone coordinators。
- Edge deployment。
- Network partition handling。
- Chaos testing。
- Sensor gateway。
- Discovery/QoS tuning。

成功标准：

- 网络抖动下无失控命令。
- Coordinator 重启不导致重复执行。
- 支持回放和事故分析。

### Phase 6：Safety/Cyber Compliance

目标：可向客户、安全团队、审计方解释与证明。

交付物：

- Safety case library。
- Threat model。
- SBOM。
- 签名发布流程。
- Incident response playbook。
- IEC 62443 zone/conduit 文档。
- AI governance 文档，可参考 ISO/IEC 42001:2023 管理系统思路。

成功标准：

- 每个高风险能力有测试证据。
- 每个事故可按 trace_id 回放。
- 每个生产命令可追溯到人、策略、证据和版本。

---

## 15. 推荐最小可行技术栈

这不是唯一答案，而是适合你当前 harness 演进的起点。

### 15.1 控制面

- API：gRPC + REST。
- Event bus：NATS / Kafka / Redpanda 之一。
- State store：PostgreSQL + TimescaleDB 或等价时序存储。
- Event sourcing：append-only log，支持 replay。
- Policy：OPA/Rego 或自研 policy-as-code。
- Workflow：Temporal / Durable execution framework 或自研状态机。
- LLM orchestration：严格 schema 输出 + tool gateway + verifier。

### 15.2 南向接入

- ROS 2：QoS profile、SROS2、Fast DDS Discovery Server。
- MQTT：VDA5050 adapter。
- REST/gRPC：厂商 fleet manager adapter。
- WebSocket：实时状态流。
- Open-RMF：作为设施/交通集成或参考 fleet adapter。

### 15.3 边缘与机器人端

- Edge service：bridge runtime、swarm scheduler、world cache。
- Robot agent：harness local admission gate。
- Safety：本地安全 monitor、急停接入、geofence。
- MCP：只在 sandbox 中运行，按工具等级授权。

---

## 16. 测试与验证体系

### 16.1 测试金字塔

```text
Unit Tests
  - schema validation
  - policy rules
  - adapter mapping
  - command idempotency

Integration Tests
  - coordinator → swarm → bridge → robot harness
  - MCP gateway permission
  - resource lock race conditions

Simulation Tests
  - multi-robot path conflicts
  - blocked corridors
  - battery depletion
  - task priority preemption

Hardware-in-the-loop
  - real robot admission gate
  - emergency stop
  - geofence enforcement
  - network loss

Field Acceptance
  - production-like workflows
  - human operators
  - incident drill

Red Team / Security
  - credential theft
  - replay command
  - malicious MCP server
  - prompt injection
  - rogue adapter
```

### 16.2 AI-specific evaluation

| 测试 | 目标 |
|---|---|
| Schema compliance | LLM 输出是否始终符合 schema |
| Grounding test | 是否引用真实机器人/地图/库存，不臆造 |
| Invalid state test | 给过期状态时是否要求刷新 |
| Ambiguity test | 任务不明确时是否请求澄清 |
| Safety refusal test | 高风险越权任务是否拒绝或要求审批 |
| Tool injection test | MCP 工具输出恶意文本时是否被隔离 |
| Replan quality | 异常发生时重规划是否合理 |
| Explanation faithfulness | 解释是否与实际决策证据一致 |

---

## 17. Prompt/Agent 设计建议

### 17.1 Coordinator system policy 核心内容

Coordinator agent 的系统策略应包含：

```text
你是机器人 fleet 的任务级 coordinator。
你不能直接生成底层运动控制命令。
你只能生成符合 schema 的 MissionIntent、TaskDAG、ReplanProposal 或 Explanation。
你必须使用提供的 world snapshot，不得臆造机器人、位置、地图或能力。
当状态不足、风险过高、任务含糊时，输出 needs_clarification 或 needs_approval。
所有计划必须声明 preconditions、success_criteria、cancel_policy 和 risk_level。
```

### 17.2 Agent 输出类型

```yaml
allowed_outputs:
  - MissionIntent.v1
  - TaskDAG.v1
  - ReplanProposal.v1
  - RiskAssessment.v1
  - OperatorQuestion.v1
  - MissionReport.v1
forbidden_outputs:
  - raw_robot_command
  - shell_script_for_production_control
  - vendor_api_call_without_bridge
  - safety_bypass_instruction
```

### 17.3 AI Replan Proposal 示例

```yaml
type: ReplanProposal.v1
trigger: robot_fault
evidence:
  - event_id: evt-991
    summary: "amr-004 reported battery SOC 0.14"
proposal:
  remove_robot_from_tasks: [amr-004]
  reassign_tasks:
    - task_id: task-0021
      from: amr-004
      to_candidates: [amr-006, amr-008]
  send_robot_to_charge:
    robot_id: amr-004
risk_assessment:
  level: low
  reason: "remaining tasks have slack > 25min"
requires_human_approval: false
```

---

## 18. 与现有 harness 的集成方式

### 18.1 单机 harness 需要暴露的最小接口

```typescript
interface HarnessAgent {
  getCapabilities(): CapabilityDescriptor;
  getState(): RobotState;
  admit(command: CommandEnvelope): AdmissionDecision;
  execute(admittedCommand: AdmittedCommand): AsyncIterable<RobotEvent>;
  cancel(commandId: string, reason: string): CancelResult;
  getSafetyState(): SafetyState;
}
```

### 18.2 Local Admission Gate

本地准入必须检查：

- 命令是否过期。
- 命令是否重复。
- 签名/身份是否有效。
- capability 是否存在。
- 当前 health 是否允许执行。
- 当前地图/坐标是否匹配。
- 是否违反 geofence。
- 是否需要本地人工确认。
- 是否与当前任务冲突。
- MCP 工具是否越权。

### 18.3 快慢脑协作

```text
CommandEnvelope
   ↓
Local Admission Gate
   ↓
Slow Brain
   - 解释任务
   - 查询本地工具/MCP
   - 选择本地技能/behavior tree
   - 生成局部执行计划
   ↓
Fast Brain
   - 控制
   - 避障
   - 安全停止
   - 实时反馈
   ↓
Result Events
```

关键原则：

- Slow brain 不能覆盖 fast brain 的安全停止。
- Fast brain 不需要理解业务意图，只执行安全控制。
- Coordinator 不能绕过 slow brain/local admission gate 直接调用 fast brain。

---

## 19. 生产安全 Checklist

### 19.1 上线前必须具备

- [ ] 所有 command envelope 有 TTL、lease、trace_id、idempotency_key。
- [ ] 所有机器人支持 local refusal。
- [ ] 所有 adapter 有限流、熔断、重试、幂等。
- [ ] 所有高风险任务有人类审批路径。
- [ ] 所有 MCP tools 有 allowlist、scope、risk_level、审计。
- [ ] 所有坐标转换有版本、验证记录和误差界限。
- [ ] 所有安全策略有 policy version。
- [ ] 所有任务可 replay。
- [ ] 网络分区策略测试通过。
- [ ] 急停与本地避障独立于 coordinator。

### 19.2 不应上线的信号

- [ ] AI 可以输出并执行任意脚本。
- [ ] Center 能直接发布底层速度/关节命令。
- [ ] Robot 无法拒绝中心任务。
- [ ] 状态 stale 仍参与调度。
- [ ] 地图坐标转换写死在 adapter 中。
- [ ] MCP server 可访问生产网络内任意地址。
- [ ] 没有命令回放与审计。
- [ ] 网络断开后机器人行为不确定。

---

## 20. 关键技术决策建议

### 20.1 是否把 Open-RMF 作为核心？

建议：**不要把 Open-RMF 当成唯一核心，但要兼容它。**

原因：

- 你的目标更大：跨厂商 harness + AI coordinator + MCP + 单机快慢脑。
- Open-RMF 很适合资源调度、fleet adapter、设施互操作。
- 但你的核心抽象应是自己的 capability contract，这样可接 Open-RMF、VDA5050、厂商 API 和未来标准。

### 20.2 中心化还是分布式？

建议：**分层混合架构**。

- Coordinator：中心化，做战略、解释、审批、跨业务系统协调。
- Swarm：可中心化，也可区域分片。
- Robot harness：本地自治，断网仍安全。
- 某些 swarm behavior：可去中心化。

### 20.3 LLM 是否参与调度器？

建议：**LLM 参与生成候选方案，不作为最终调度器。**

最终调度应由确定性组件完成：

- constraint solver。
- policy engine。
- MAPF/traffic scheduler。
- resource lock manager。
- local admission gate。

### 20.4 MCP 放在哪里？

建议：两层 MCP：

```text
Coordinator MCP Gateway
  - ERP/MES/WMS
  - SOP/知识库
  - incident database
  - simulation/digital twin
  - reporting

Robot Local MCP Sandbox
  - local diagnostics
  - robot manual lookup
  - local perception summary
  - limited device tools
```

严禁：MCP tool 直接绕过 bridge/swarm/local gate 控制机器人。

---

## 21. 推荐仓库结构

```text
robot-coordinator/
  README.md
  docs/
    architecture.md
    safety-case.md
    threat-model.md
    adapter-guide.md
    mcp-tool-policy.md
  contracts/
    capability_descriptor.schema.json
    robot_state.schema.json
    mission_intent.schema.json
    task_spec.schema.json
    command_envelope.schema.json
    robot_event.schema.json
  coordinator/
    api/
    agent/
    plan_builder/
    plan_verifier/
    explanation/
  swarm/
    scheduler/
    resource_lock/
    traffic/
    battery/
    replanner/
  bridge/
    runtime/
    adapters/
      ros2/
      open_rmf/
      vda5050/
      massrobotics/
      vendor_template/
  robot_agent/
    admission_gate/
    skill_executor/
    safety_monitor/
    mcp_sandbox/
  policy/
    rego/
    risk_levels.yaml
    approvals.yaml
  world_model/
    maps/
    zones/
    resources/
    transforms/
  sim/
    digital_twin/
    scenarios/
    replay/
  ops/
    console/
    dashboards/
    alerts/
  security/
    sbom/
    signing/
    cert_rotation/
    red_team_tests/
```

---

## 22. 参考资料清单

### 22.1 标准与工程框架

1. Open-RMF 官网：<https://www.open-rmf.org/>
2. OpenRMF 文档：<https://openrmf.readthedocs.io/en/latest/>
3. Open-RMF Fleet Adapter Tutorial：<https://osrf.github.io/ros2multirobotbook/integration_fleets_adapter_tutorial.html>
4. VDA5050 官方 GitHub：<https://github.com/VDA5050/VDA5050>
5. VDA5050 英文规范：<https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md>
6. MassRobotics AMR Interoperability Standard：<https://github.com/MassRobotics-AMR/AMR_Interop_Standard>
7. ISO/FDIS 21423：<https://www.iso.org/standard/86749.html>
8. ROS 2 QoS：<https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Quality-of-Service-Settings.html>
9. SROS2 Security：<https://docs.ros.org/en/rolling/Tutorials/Advanced/Security/Introducing-ros2-security.html>
10. Fast DDS Discovery Server：<https://docs.ros.org/en/rolling/Tutorials/Advanced/Discovery-Server/Discovery-Server.html>
11. MCP Specification 2025-11-25：<https://modelcontextprotocol.io/specification/2025-11-25>
12. MCP Authorization：<https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization>
13. MCP Security Best Practices：<https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices>
14. ISO 10218-x:2025 update, TÜV Rheinland：<https://www.tuv.com/landingpage/en/robotics/main/standard-update-alert/>
15. IEC 62443-3-2:2020：<https://webstore.iec.ch/en/publication/30727>
16. IEC 62443 overview：<https://www.iec.ch/blog/understanding-iec-62443>
17. NIST Cybersecurity Framework 2.0：<https://www.nist.gov/cyberframework>
18. ISO/IEC 42001:2023 listing：<https://www.iso.org/popular-standards.html>

### 22.2 论文与研究

1. Large Language Models for Multi-Robot Systems: A Survey：<https://arxiv.org/html/2502.03814v5>
2. SMART-LLM: Smart Multi-Agent Robot Task Planning using Large Language Models：<https://arxiv.org/abs/2309.10062>
3. ROS2swarm - A ROS 2 Package for Swarm Robot Behaviors：<https://arxiv.org/abs/2405.02438>
4. Optimizing ROS 2 Communication for Wireless Robotic Systems：<https://arxiv.org/abs/2508.11366>
5. SFG-ROS: A Resource-Aware Framework for Dense Multi-Agent Perception：<https://arxiv.org/abs/2605.23832>
6. Supply Chain Exploitation of Secure ROS 2 Systems：<https://arxiv.org/abs/2511.00140>
7. LLM-Guided Safety Agent for Edge Robotics：<https://arxiv.org/abs/2604.20193>

### 22.3 Foundation model 趋势参考

1. Gemini Robotics-ER 1.6：<https://deepmind.google/blog/gemini-robotics-er-1-6/>
2. NVIDIA Isaac GR00T：<https://github.com/NVIDIA/Isaac-GR00T>

---

## 23. 最终建议

你现在已有的 `remote bridge + swarm + 单机 harness 快慢脑 + MCP + 本地安全机制` 是非常好的基础。下一步最重要的不是先堆更强模型，而是先把系统的**合约、权限、安全门、事件流、状态模型、调度边界**定死。

建议按以下优先级推进：

1. **先定义 capability contract**：这是跨厂商和 AI 安全调度的根。
2. **先做 read-only 指挥中心**：统一看见所有机器人状态和任务流。
3. **再做 human-approved dispatch**：不要一开始全自动。
4. **再加入 swarm scheduler**：资源锁、交通、任务分配。
5. **最后让 AI coordinator 深度参与**：自然语言、任务拆解、解释、重规划。
6. **始终保留本地 harness 最终拒绝权**：这是你系统能安全扩展的核心。

最终形态应是：

```text
AI Coordinator = 战略/语义/解释/治理
Swarm Layer    = 分配/资源/交通/重规划
Remote Bridge  = 协议/状态/厂商适配
Robot Harness  = 本地准入/执行/安全最终裁决
```

这样，你的系统就不是“中心 AI 控一堆机器人”的脆弱架构，而是一个**AI 增强的、跨厂商的、分层自治的机器人指挥调度平台**。
